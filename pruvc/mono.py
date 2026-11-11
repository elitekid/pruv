"""G3 A3: shared specialization plan (G3_SPEC 5.1, 5.2).

    plan = specialize(prog)        # prog: a fully checked Program (verified or --no-verify); never mutated

The pass runs after verification (after full checking under --no-verify). It builds a NEW, fully concrete Program,
`plan.program`, in which
  * every generic function specialization is an ordinary Function named by its stem (`pruv_g3_f_...`, marked
    `private = True`: generic implementations are never public Rust items),
  * every generic nominal application is an ordinary StructDecl / EnumDecl named by its stem (`pruv_g3_t_...`),
  * every Type is concrete: a nominal application is `Type(<stem>)` without arguments, Option<X> / Result<X> keep
    their argument unless X is i64 (legacy Option<i64> / Result<i64>), arrays are the legacy [i64]/[bool].
The back ends consume plan.program as if it were an ordinary G1 program (the Rust source back end today, LLVM in A4).

Roots are all non-generic functions (they are the public entry points, called or not). Concrete generic calls,
struct literals and enum constructors (the checker records them in `.inst`) are substituted and followed with a
work list (no recursion over call chains). Specializations are deduplicated by declaration identity and the full
type-argument tuple (the stem is injective). Unused generic functions / types generate nothing. `ensures` and
loop invariants are dropped from the concrete functions (code generation never reads them); `requires` is kept
(runtime entry check).

Output order: functions by declaration order, then the lexicographic tuple of argument encodings (G3_SPEC 5.2);
types by the same key, then dependency-first (TypeTable.order, applied by the code generator).

Limits (G3_SPEC 5.1): 4096 function specializations, 4096 nominal applications, instantiated type nesting depth
128 (the root counts as depth one). Exceeding one raises PruvError(codegen, specialization_limit) naming the
trigger; no plan (hence no output) is produced. One more guard of the same code: a single instantiated type with
more than MAX_TYPE_NODES nodes (a type such as Pair<Pair<..>, Pair<..>> doubles with every level; depth alone does
not bound its size).
"""
from collections import deque

from vast import *
from typeinfo import (bind_args, decl_owner, encode, first_g3_use, format_type, spec_fn_stem, spec_type_stem,
                      substitute)

MAX_FN_SPECS = 4096
MAX_TYPE_APPS = 4096
MAX_DEPTH = 128
MAX_TYPE_NODES = 1 << 16


def is_generic_program(prog):
    """True when the program uses G3 anywhere (a type parameter, a type application, or Option<X>/Result<X>)."""
    return first_g3_use(prog) is not None


def llvm_unsupported_error(prog):
    """codegen/unsupported_type for a generic program on the LLVM backend (until A4); None for other programs.
    The message names "the llvm codegen layer" (tests/run_all.py llvm_pending rows check for it)."""
    hit = first_g3_use(prog)
    if hit is None:
        return None
    line, col, what = hit
    return PruvError("codegen", line, col, "unsupported_type",
                     "generics are not supported yet (%s): the llvm codegen layer is not implemented" % what,
                     "use --backend rust for generic programs for now")


# ---------------------------------------------------------------------------
class _Stop(Exception):
    pass


def short_type(t, limit=64):
    """format_type, cut off after about `limit` characters (a rejected type may be astronomically large)."""
    parts = []
    size = [0]

    def put(s):
        parts.append(s)
        size[0] += len(s)
        if size[0] > limit:
            raise _Stop()

    def go(x):
        if x.owner is not None or not x.args:
            put(format_type(x))
            return
        if x.name == "array":
            put("[")
            go(x.args[0])
            put("]")
            return
        put({"option": "Option", "result": "Result"}.get(x.name, x.name) + "<")
        for i, a in enumerate(x.args):
            if i:
                put(", ")
            go(a)
        put(">")
    try:
        go(t)
    except _Stop:
        return "".join(parts) + "..."
    return "".join(parts)


def measure(t):
    """(depth, tree node count) of a type, iteratively (no recursion limit) and linear in the number of DISTINCT
    sub-objects (shared sub-types are measured once)."""
    memo = {}
    stack = [(t, False)]
    while stack:
        n, post = stack.pop()
        k = id(n)
        if k in memo:
            continue
        if not n.args:
            # the legacy Option<i64> / Result<i64> constants stand for a one-argument application (depth 2)
            memo[k] = (2, 2) if n.owner is None and n.name in ("option", "result") else (1, 1)
            continue
        if not post:
            stack.append((n, True))
            for a in n.args:
                if id(a) not in memo:
                    stack.append((a, False))
        else:
            ds = [memo[id(a)] for a in n.args]
            memo[k] = (1 + max(d for d, _ in ds), 1 + sum(s for _, s in ds))
    return memo[id(t)]


class FnSpec:
    """One specialization of a generic function: decl name, concrete type arguments, stem, sort key, concrete Function."""
    def __init__(self, name, args, stem, encs):
        self.name, self.args, self.stem, self.encs = name, args, stem, encs
        self.func = None

    def __repr__(self):
        return "FnSpec(%s)" % self.stem


class TypeSpec:
    """One application of a generic struct/enum: decl name, concrete type arguments, stem, sort key, concrete decl."""
    def __init__(self, name, args, stem, encs):
        self.name, self.args, self.stem, self.encs = name, args, stem, encs
        self.decl = None

    def __repr__(self):
        return "TypeSpec(%s)" % self.stem


class SpecPlan:
    """Result of specialize(). `program` is the concrete Program; fn_specs / type_specs are the generic
    specializations in output order; roots are the non-generic function names in declaration order."""
    def __init__(self, source, program, fn_specs, type_specs, roots):
        self.source = source
        self.program = program
        self.fn_specs = fn_specs
        self.type_specs = type_specs
        self.roots = roots

    def fn_stems(self):
        return [s.stem for s in self.fn_specs]

    def type_stems(self):
        return [s.stem for s in self.type_specs]

    def describe(self):
        """deterministic JSON-able summary: generic function stems, generic type stems, emitted function and type
        names of the concrete program in output order"""
        return {"fn_specs": self.fn_stems(), "type_specs": self.type_stems(),
                "functions": [f.name for f in self.program.functions],
                "types": [d.name for d in self.program.types]}


class _Mono:
    def __init__(self, prog):
        self.prog = prog
        self.tdecls = {}
        self.tindex = {}
        for i, d in enumerate(prog.types):
            if d.name not in self.tdecls:       # first declaration wins (the checker rejects duplicates)
                self.tdecls[d.name] = d
                self.tindex[d.name] = i
        self.fdecls = {}
        self.findex = {}
        for i, f in enumerate(prog.functions):
            if f.name not in self.fdecls:
                self.fdecls[f.name] = f
                self.findex[f.name] = i
        self.fns = {}            # stem -> FnSpec
        self.types = {}          # stem -> TypeSpec
        self.queue = deque()
        self.map = {}            # substitution of the declaration being copied
        self.pos = (1, 1)

    # ---------- errors ----------
    def limit(self, msg):
        line, col = self.pos
        return PruvError("codegen", line, col, "specialization_limit", msg,
                         "reduce the number or the nesting depth of generic instantiations")

    def check_shape(self, c, what):
        """depth and size limits of one concrete type (checked before it is encoded or lowered)"""
        d, n = measure(c)
        if d > MAX_DEPTH:
            raise self.limit("instantiated type nesting depth %d exceeds the limit of %d (%s: %s)" % (
                d, MAX_DEPTH, what, short_type(c)))
        if n > MAX_TYPE_NODES:
            raise self.limit("instantiated type has more than %d nodes (%s: %s)" % (
                MAX_TYPE_NODES, what, short_type(c)))

    # ---------- types ----------
    def ty(self, t):
        """concrete, lowered form of a declared/checked type in the current substitution"""
        if t is None:
            return None
        c = substitute(t, self.map) if self.map else t
        if c.owner is not None:
            raise RuntimeError("specialization: unbound type parameter %s" % c.name)
        if not c.args:
            return c
        self.check_shape(c, "type")
        return self.lower(c)

    def lower(self, c):
        if c.owner is not None:
            raise RuntimeError("specialization: unbound type parameter %s" % c.name)
        if not c.args:
            return c
        if c.name == "array":
            return mk_array(self.lower(c.args[0]))
        if c.name == "option":
            return mk_option(self.lower(c.args[0]))
        if c.name == "result":
            return mk_result(self.lower(c.args[0]))
        return Type(self.request_type(c.name, c.args))

    def concrete_args(self, inst):
        return tuple(substitute(a, self.map) if self.map else a for a in inst["args"])

    def request_type(self, name, args):
        """register the application name<args> (concrete args); returns its stem"""
        args = tuple(args)
        self.check_shape(Type(name, args), "application of %s" % name)
        stem = spec_type_stem(name, args)
        if stem in self.types:
            return stem
        if len(self.types) >= MAX_TYPE_APPS:
            raise self.limit("more than %d distinct generic type applications (trigger: %s<%s>)" % (
                MAX_TYPE_APPS, name, ", ".join(short_type(a, 32) for a in args)))
        spec = TypeSpec(name, args, stem, tuple(encode(a) for a in args))
        self.types[stem] = spec
        self.queue.append(spec)
        return stem

    def request_fn(self, name, args):
        args = tuple(args)
        for a in args:
            self.check_shape(a, "type argument of function %s" % name)
        stem = spec_fn_stem(name, args)
        if stem in self.fns:
            return stem
        if len(self.fns) >= MAX_FN_SPECS:
            raise self.limit("more than %d distinct generic function specializations (trigger: %s<%s>)" % (
                MAX_FN_SPECS, name, ", ".join(short_type(a, 32) for a in args)))
        spec = FnSpec(name, args, stem, tuple(encode(a) for a in args))
        self.fns[stem] = spec
        self.queue.append(spec)
        return stem

    # ---------- copying with substitution ----------
    def cp(self, node):
        """deep copy of an AST fragment: every Type is substituted and lowered; explicit instantiations are
        replaced by references to their specializations (which are requested on the way)"""
        if node is None:
            return None
        if isinstance(node, list):
            return [self.cp(x) for x in node]
        if isinstance(node, Type):
            return self.ty(node)
        fields = getattr(node, "__dataclass_fields__", None)
        if fields is None:
            return node
        new = type(node)(**dict((n, self.cp(getattr(node, n))) for n in fields))
        if isinstance(node, Call):
            if node.inst is not None:
                self.pos = (node.line, node.col)
                new.name = self.request_fn(node.name, self.concrete_args(node.inst))
        elif isinstance(node, StructLit):
            if node.inst is not None:
                self.pos = (node.line, node.col)
                new.name = self.request_type(node.name, self.concrete_args(node.inst))
                new.src_name = node.name      # for panic messages (codegen.show)
        elif isinstance(node, EnumCtor):
            if node.inst is not None:
                self.pos = (node.line, node.col)
                new.enum_name = self.request_type(node.enum_name, self.concrete_args(node.inst))
                new.src_name = node.enum_name
        elif isinstance(node, (IsVariant, VariantField)):
            if node.enum_ty is not None:
                new.enum_name = self.ty(node.enum_ty).name
                new.src_name = node.enum_name
        elif isinstance(node, Match):
            sty = new.scrutinee.ty
            if sty is not None:
                for old_arm, arm in zip(node.arms, new.arms):
                    if old_arm.enum_name is not None:
                        arm.enum_name = sty.name
        return new

    def function(self, f, name, mapping, private):
        self.map = mapping
        self.pos = (f.line, f.col)
        new = Function(line=f.line, col=f.col, name=name,
                       params=[Param(p.name, self.ty(p.type), self.cp(p.refine)) for p in f.params],
                       ret=self.ty(f.ret), effects=list(f.effects), requires=self.cp(f.requires), ensures=[],
                       body=self.cp(f.body), ret_refine=self.cp(f.ret_refine))
        new.private = private
        return new

    def type_decl(self, d, stem, mapping):
        self.map = mapping
        self.pos = (d.line, d.col)

        def fields(fs):
            return [FieldDecl(fd.line, fd.col, fd.name, self.ty(fd.type)) for fd in fs]
        if isinstance(d, StructDecl):
            return StructDecl(line=d.line, col=d.col, name=stem, fields=fields(d.fields))
        return EnumDecl(line=d.line, col=d.col, name=stem,
                        variants=[VariantDecl(v.line, v.col, v.name, fields(v.fields)) for v in d.variants])

    # ---------- driver ----------
    def run(self):
        prog = self.prog
        plain_types = {}
        for d in prog.types:
            if d.name in plain_types or d.tparams or self.tdecls[d.name] is not d:
                continue
            plain_types[d.name] = self.type_decl(d, d.name, {})
        roots = {}
        for f in prog.functions:
            if not f.tparams and self.fdecls[f.name] is f:
                roots[f.name] = self.function(f, f.name, {}, False)
        while self.queue:
            spec = self.queue.popleft()
            if isinstance(spec, FnSpec):
                f = self.fdecls[spec.name]
                spec.func = self.function(f, spec.stem, bind_args("fn:" + f.name, len(f.tparams), spec.args), True)
            else:
                d = self.tdecls[spec.name]
                spec.decl = self.type_decl(d, spec.stem, bind_args(decl_owner(d.name), len(d.tparams), spec.args))
        # ---- output order ----
        by_fn = {}
        for s in self.fns.values():
            by_fn.setdefault(s.name, []).append(s)
        fn_specs = []
        functions = []
        root_names = []
        for f in prog.functions:
            if self.fdecls[f.name] is not f:
                continue
            if not f.tparams:
                functions.append(roots[f.name])
                root_names.append(f.name)
            else:
                specs = sorted(by_fn.get(f.name, []), key=lambda s: s.encs)
                fn_specs.extend(specs)
                functions.extend(s.func for s in specs)
        keyed = [((self.tindex[n], ()), d) for n, d in plain_types.items()]
        type_specs = sorted(self.types.values(), key=lambda s: (self.tindex[s.name], s.encs))
        keyed += [((self.tindex[s.name], s.encs), s.decl) for s in type_specs]
        keyed.sort(key=lambda kd: kd[0])
        program = Program(functions=functions, types=[d for _, d in keyed])
        return SpecPlan(prog, program, fn_specs, type_specs, root_names)


def specialize(prog):
    """The specialization plan of a checked program (does not mutate prog). PruvError(codegen,
    specialization_limit) when a limit of G3_SPEC 5.1 is exceeded."""
    return _Mono(prog).run()
