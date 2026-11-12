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

G4 A2: in explicit visibility mode (prog.explicit) the pass always runs and also renames every nongeneric function / type
to its Rust stem (modules.encode_stem; root host entries and root `pub` types keep the source spelling), builds the pruv_g3
stems from the encoded identity (modules.encode_name / safe_type), and copies pub / host_entry / src_name / mod_path and
`disp` (the identity, for panic text and manifests) onto the concrete declarations; a specialization inherits its generic
declaration's visibility and display name.

Roots are all non-generic functions (they are the public entry points, called or not). Concrete generic calls,
struct literals and enum constructors (the checker records them in `.inst`) are substituted and followed with a
work list (no recursion over call chains). Specializations are deduplicated by declaration identity and the full
type-argument tuple (the stem is injective). Unused generic functions / types generate nothing. `ensures` and
loop invariants are dropped from the concrete functions (code generation never reads them); `requires` is kept
(runtime entry check).

Output order: functions by declaration order, then the lexicographic tuple of argument encodings (G3_SPEC 5.2);
types by the same key, then dependency-first (TypeTable.order, applied by the code generator).

G9 A2 (recursion): an instance is REGISTERED (request_fn / request_type put it into self.fns / self.types and onto the
work list) before its body is copied, and a call is only ever replaced by the stem of a registered instance. Following a
recursive or mutually recursive call therefore finds the instance already registered and adds nothing: specialization of
(mutually) recursive generic functions terminates, and it never recurses over call chains (work list, no recursion over
the call graph). G9 allows only stable type-parameter vectors inside a recursive SCC (check.py), so the number of
instances stays bounded by the existing limits below. The output order (declaration order, then argument encodings) never
walks the call graph; type dependency order is computed by the code generator on the SCC condensation of the type graph.

Limits (G3_SPEC 5.1): 4096 function specializations, 4096 nominal applications, instantiated type nesting depth
128 (the root counts as depth one). Exceeding one raises PruvError(codegen, specialization_limit) naming the
trigger; no plan (hence no output) is produced. One more guard of the same code: a single instantiated type with
more than MAX_TYPE_NODES nodes (a type such as Pair<Pair<..>, Pair<..>> doubles with every level; depth alone does
not bound its size).
"""
from collections import deque

from vast import *
from typeinfo import (bind_args, decl_owner, encode, first_g3_use, format_type, spec_fn_stem, spec_type_stem,
                      substitute, COLLECTION_ARITY)
from foreign import CATALOG   # G6: catalog calls keep their name (never specialized)
from modules import encode_name, encode_stem, identity_components, safe_type   # G4 A2: shared symbol encoding

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
        self.explicit = bool(prog.explicit)
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
        # G4 A2 (explicit mode only): identity -> Rust stem of every NONGENERIC function / type. Root host entries and
        # root `pub` types keep their source spelling; everything else gets its encoded stem (modules.encode_stem).
        # Generic declarations are named by their specialization stems (pruv_g3_*), built from the identity.
        self.rfns = {}
        self.rtypes = {}
        if self.explicit:
            for f in prog.functions:
                if not f.tparams and self.fdecls[f.name] is f:
                    self.rfns[f.name] = f.src_name if f.host_entry else encode_stem("f", f.mod_path + (f.src_name,))
            for d in prog.types:
                if not d.tparams and self.tdecls[d.name] is d:
                    self.rtypes[d.name] = d.src_name if (d.pub and d.mod_path == ()) else \
                        encode_stem("t", d.mod_path + (d.src_name,))
        self.fns = {}            # stem -> FnSpec
        self.types = {}          # stem -> TypeSpec
        self.queue = deque()
        self.map = {}            # substitution of the declaration being copied
        self.pos = (1, 1)

    # ---------- G4 A2 naming (explicit mode) ----------
    def _gname(self, name):
        """the name token of a generic declaration inside a pruv_g3 stem / argument encoding"""
        return encode_name(identity_components(name)) if self.explicit else name

    def _enc(self, t):
        return encode(safe_type(t)) if self.explicit else encode(t)

    def _nom(self, c):
        """explicit mode: a nongeneric nominal type gets its Rust stem"""
        if self.explicit and c.owner is None and not c.args and c.name in self.rtypes:
            return Type(self.rtypes[c.name])
        return c

    def _mark_fn(self, new, f, private):
        if self.explicit:
            new.pub = f.pub                      # a specialization inherits the generic declaration's visibility
            new.host_entry = bool(f.host_entry) and not private
            new.src_name, new.mod_path = f.src_name, f.mod_path
            new.disp = f.name                    # display name = resolved identity (source-qualified)
        return new

    def _mark_type(self, new, d):
        if self.explicit:
            new.pub = d.pub
            new.src_name, new.mod_path = d.src_name, d.mod_path
            new.disp = d.name
        return new

    def _g9_meta(self):
        meta = self.prog.g9
        if not self.explicit or meta is None:
            return meta
        ren = lambda n: self.rtypes.get(n, n)    # noqa: E731
        boxed = []
        for lab in meta["boxed"]:               # "Type.field" / "Type::Variant.field" over identities
            head, _, field = lab.rpartition(".")
            if head in self.rtypes:
                boxed.append("%s.%s" % (ren(head), field))
            else:
                tn, _, v = head.rpartition("::")
                boxed.append("%s::%s.%s" % (ren(tn), v, field))
        return dict(meta, boxed=boxed, extended=[ren(n) for n in meta["extended"]])

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
            return self._nom(c)
        self.check_shape(c, "type")
        return self.lower(c)

    def lower(self, c):
        if c.owner is not None:
            raise RuntimeError("specialization: unbound type parameter %s" % c.name)
        if not c.args:
            return self._nom(c)
        if c.name == "array":
            return mk_array(self.lower(c.args[0]))
        if c.name == "option":
            return mk_option(self.lower(c.args[0]))
        if c.name == "result":
            return mk_result(self.lower(c.args[0]))
        if c.name in COLLECTION_ARITY:   # G6: Vec<T> / HashMap<K, V> keep their name, arguments are lowered
            return Type(c.name, tuple(self.lower(a) for a in c.args))
        return Type(self.request_type(c.name, c.args))

    def concrete_args(self, inst):
        return tuple(substitute(a, self.map) if self.map else a for a in inst["args"])

    def request_type(self, name, args):
        """register the application name<args> (concrete args); returns its stem"""
        args = tuple(args)
        self.check_shape(Type(name, args), "application of %s" % name)
        stem = spec_type_stem(self._gname(name), tuple(safe_type(a) for a in args) if self.explicit else args)
        if stem in self.types:
            return stem
        if len(self.types) >= MAX_TYPE_APPS:
            raise self.limit("more than %d distinct generic type applications (trigger: %s<%s>)" % (
                MAX_TYPE_APPS, name, ", ".join(short_type(a, 32) for a in args)))
        spec = TypeSpec(name, args, stem, tuple(self._enc(a) for a in args))
        self.types[stem] = spec
        self.queue.append(spec)
        return stem

    def request_fn(self, name, args):
        args = tuple(args)
        for a in args:
            self.check_shape(a, "type argument of function %s" % name)
        stem = spec_fn_stem(self._gname(name), tuple(safe_type(a) for a in args) if self.explicit else args)
        if stem in self.fns:
            return stem
        if len(self.fns) >= MAX_FN_SPECS:
            raise self.limit("more than %d distinct generic function specializations (trigger: %s<%s>)" % (
                MAX_FN_SPECS, name, ", ".join(short_type(a, 32) for a in args)))
        spec = FnSpec(name, args, stem, tuple(self._enc(a) for a in args))
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
            if node.old is not None:
                # G5 A1: a resolved old(a) keeps its operand-parameter metadata (parameter names survive module
                # resolution and generic substitution, so the defining parameter is the same name)
                new.old = dict(node.old)
            if node.name in CATALOG:
                # G6: the name stays; `args` = lowered concrete type arguments, `src_args` = concrete but not
                # lowered (source-level spelling and the structural encoding of helper names)
                if node.inst is not None:
                    self.pos = (node.line, node.col)
                    src = self.concrete_args(node.inst)
                    for a in src:
                        self.check_shape(a, "type argument of function %s" % node.name)
                    new.inst = {"decl": node.inst["decl"], "args": tuple(self.ty(a) for a in src),
                                "src_args": src}
            elif node.inst is not None:
                self.pos = (node.line, node.col)
                new.name = self.request_fn(node.name, self.concrete_args(node.inst))
            elif node.name in self.rfns:       # G4 A2: a nongeneric user function -> its Rust stem
                new.name = self.rfns[node.name]
        elif isinstance(node, StructLit):
            if node.inst is not None:
                self.pos = (node.line, node.col)
                new.name = self.request_type(node.name, self.concrete_args(node.inst))
                new.src_name = node.name      # for panic messages (codegen.show)
            elif node.name in self.rtypes:
                new.name = self.rtypes[node.name]
                new.src_name = node.name
        elif isinstance(node, EnumCtor):
            if node.inst is not None:
                self.pos = (node.line, node.col)
                new.enum_name = self.request_type(node.enum_name, self.concrete_args(node.inst))
                new.src_name = node.enum_name
            elif node.enum_name in self.rtypes:
                new.enum_name = self.rtypes[node.enum_name]
                new.src_name = node.enum_name
        elif isinstance(node, (IsVariant, VariantField)):
            if node.enum_ty is not None:
                new.enum_name = self.ty(node.enum_ty).name
                new.src_name = node.enum_name
            elif node.enum_name in self.rtypes:
                new.enum_name = self.rtypes[node.enum_name]
                new.src_name = node.enum_name
        elif isinstance(node, Match):
            sty = new.scrutinee.ty
            if sty is not None:
                for old_arm, arm in zip(node.arms, new.arms):
                    if old_arm.enum_name is not None:
                        arm.enum_name = sty.name
            elif self.explicit:
                for arm in new.arms:
                    if arm.enum_name in self.rtypes:
                        arm.enum_name = self.rtypes[arm.enum_name]
        return new

    def function(self, f, name, mapping, private):
        self.map = mapping
        self.pos = (f.line, f.col)
        params = []
        for p in f.params:
            q = Param(p.name, self.ty(p.type), self.cp(p.refine))
            if p.take:
                q.take = True     # G6
            if p.mode is not None:     # G5 A0: the mode survives specialization
                q.mode = p.mode
                q.mode_pos = p.mode_pos
            params.append(q)
        new = Function(line=f.line, col=f.col, name=name, params=params,
                       ret=self.ty(f.ret), effects=list(f.effects), requires=self.cp(f.requires),
                       ensures=self.cp(f.ensures) if f.foreign is not None else [],   # G6: kept for `all` checks
                       body=self.cp(f.body), ret_refine=self.cp(f.ret_refine))
        new.private = private
        new.file = f.file   # explicit mode: later codegen diagnostics keep the source file (Rust: the tagged line)
        if f.foreign is not None:
            new.foreign = f.foreign
        return self._mark_fn(new, f, private)

    def type_decl(self, d, stem, mapping):
        self.map = mapping
        self.pos = (d.line, d.col)

        def fields(fs):
            return [FieldDecl(fd.line, fd.col, fd.name, self.ty(fd.type)) for fd in fs]
        if isinstance(d, StructDecl):
            return self._mark_type(StructDecl(line=d.line, col=d.col, name=stem, fields=fields(d.fields)), d)
        return self._mark_type(EnumDecl(line=d.line, col=d.col, name=stem,
                                        variants=[VariantDecl(v.line, v.col, v.name, fields(v.fields))
                                                  for v in d.variants]), d)

    # ---------- driver ----------
    def run(self):
        prog = self.prog
        plain_types = {}
        for d in prog.types:
            if d.name in plain_types or d.tparams or self.tdecls[d.name] is not d:
                continue
            plain_types[d.name] = self.type_decl(d, self.rtypes.get(d.name, d.name), {})
        roots = {}
        for f in prog.functions:
            if not f.tparams and self.fdecls[f.name] is f:
                roots[f.name] = self.function(f, self.rfns.get(f.name, f.name), {}, False)
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
        program.uses_inout = getattr(prog, "uses_inout", None)   # G5 A2: keeps codegen's inout gate (as the Rust port)
        # G9 A2: the concrete program keeps the checker's G9 metadata (recursive/boxed/extended declarations). Extended
        # types are never generic (check.py), so their names are the same in the concrete program; the metadata is
        # shared read-only, never mutated.
        if prog.g9 is not None:
            program.g9 = self._g9_meta()      # explicit mode: the same metadata over the Rust stems
        program.explicit = self.explicit      # G4 A2: the code generator applies the explicit visibility rules
        return SpecPlan(prog, program, fn_specs, type_specs, root_names)


def specialize(prog):
    """The specialization plan of a checked program (does not mutate prog). PruvError(codegen,
    specialization_limit) when a limit of G3_SPEC 5.1 is exceeded."""
    return _Mono(prog).run()
