#!/usr/bin/env python3
"""G3 A3 specialization-plan cases (G3_SPEC 5.1, 5.2, 7.5): pruvc/mono.py.

    python tests/g3/mono_plan.py     -> one line per case, then "N/N passed"; exit 0 on success

Each case parses and checks a small program (no proof, no code generation unless stated) and inspects the
SpecPlan: the generic function / type specializations (stems), their order, and the concrete program.
Covered: deduplication, nested calls, multiple type parameters, unused definitions, phantom parameters,
dependencies, legacy normalization, deterministic ordering, immutability of the checked program.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "pruvc"))

from vast import *            # noqa: E402
from vparser import parse     # noqa: E402
from check import check       # noqa: E402
from typeinfo import TypeTable  # noqa: E402
from mono import specialize   # noqa: E402

cases = []


def case(fn):
    cases.append(fn)
    return fn


def build(src):
    prog = parse(src)
    check(prog)
    return prog, specialize(prog)


@case
def dedupe_same_arguments():
    _, plan = build("""
fn identity<T>(x: T) -> T { return x; }
fn a(x: i64) -> i64 { return identity::<i64>(x); }
fn b(x: i64) -> i64 { return identity::<i64>(identity::<i64>(x)); }
""")
    return plan.fn_stems() == ["pruv_g3_f_8_identity_1_i"] and plan.type_stems() == []


@case
def distinct_arguments_distinct_specializations():
    _, plan = build("""
fn identity<T>(x: T) -> T { return x; }
fn a(x: i64, y: bool, z: Option<bool>) -> i64 {
  let u: bool = identity::<bool>(y);
  let v: Option<bool> = identity::<Option<bool>>(z);
  return identity::<i64>(x);
}
""")
    return plan.fn_stems() == ["pruv_g3_f_8_identity_1_b", "pruv_g3_f_8_identity_1_i", "pruv_g3_f_8_identity_1_ob"]


@case
def nested_calls_are_followed():
    _, plan = build("""
fn c<T>(x: T) -> T { return x; }
fn b<T>(x: T) -> T { return c::<T>(x); }
fn a<T>(x: T) -> T { return b::<T>(x); }
fn root(x: bool) -> bool { return a::<bool>(x); }
""")
    # only `root` mentions a concrete type; b and c are reached through the substituted bodies
    return (plan.fn_stems() == ["pruv_g3_f_1_c_1_b", "pruv_g3_f_1_b_1_b", "pruv_g3_f_1_a_1_b"]
            and [f.name for f in plan.program.functions] ==
            ["pruv_g3_f_1_c_1_b", "pruv_g3_f_1_b_1_b", "pruv_g3_f_1_a_1_b", "root"])


@case
def multiple_type_parameters():
    _, plan = build("""
struct Pair<A, B> { first: A, second: B }
fn make<A, B>(a: A, b: B) -> Pair<A, B> { return Pair::<A, B> { first: a, second: b }; }
fn r1() -> Pair<i64, bool> { return make::<i64, bool>(1, true); }
fn r2() -> Pair<bool, i64> { return make::<bool, i64>(false, 2); }
""")
    return (plan.fn_stems() == ["pruv_g3_f_4_make_2_b_i", "pruv_g3_f_4_make_2_i_b"]
            and plan.type_stems() == ["pruv_g3_t_4_Pair_2_b_i", "pruv_g3_t_4_Pair_2_i_b"])


@case
def unused_generic_function_generates_nothing():
    _, plan = build("""
fn never<T>(x: T) -> T { return x; }
fn plain(x: i64) -> i64 { return x; }
""")
    return plan.fn_specs == [] and [f.name for f in plan.program.functions] == ["plain"]


@case
def every_non_generic_function_is_a_root():
    _, plan = build("""
struct Unused<T> { v: T }
fn r1() -> i64 { return 1; }
fn r2() -> i64 { return 2; }
""")
    # nobody calls r1 / r2, they are public entry points anyway; the unused generic struct generates nothing
    return (plan.roots == ["r1", "r2"] and plan.type_specs == [] and plan.program.types == []
            and [f.name for f in plan.program.functions] == ["r1", "r2"])


@case
def phantom_parameters_give_distinct_types():
    _, plan = build("""
struct Tag<T> { id: i64 }
fn make<T>(id: i64) -> Tag<T> { return Tag::<T> { id: id }; }
fn tb(id: i64) -> Tag<bool> { return make::<bool>(id); }
fn ti(id: i64) -> Tag<i64> { return make::<i64>(id); }
""")
    same_fields = all([(f.name, f.type) for f in s.decl.fields] == [("id", I64)] for s in plan.type_specs)
    return plan.type_stems() == ["pruv_g3_t_3_Tag_1_b", "pruv_g3_t_3_Tag_1_i"] and same_fields \
        and plan.fn_stems() == ["pruv_g3_f_4_make_1_b", "pruv_g3_f_4_make_1_i"]


@case
def type_dependencies_come_first():
    _, plan = build("""
struct Wrap { p: Pair<i64, bool> }
struct Pair<A, B> { first: A, second: B }
fn use_wrap(w: Wrap) -> i64 { return 0; }
""")
    stem = "pruv_g3_t_4_Pair_2_i_b"
    in_plan = [d.name for d in plan.program.types]          # declaration order, then argument encoding
    emitted = [d.name for d in TypeTable(plan.program).order]   # what the code generator emits: dependencies first
    wrap = [d for d in plan.program.types if d.name == "Wrap"][0]
    return (plan.type_stems() == [stem] and in_plan == ["Wrap", stem] and emitted == [stem, "Wrap"]
            and wrap.fields[0].type == Type(stem))


@case
def legacy_option_result_i64_keep_their_lowering():
    prog, plan = build("""
fn identity<T>(x: T) -> T { return x; }
fn pick<T>(o: Option<T>, d: T) -> T {
  match o {
    Some(v) => { return v; }
    None => { return d; }
  }
}
fn r(o: Option<i64>) -> i64 { return pick::<i64>(o, 0); }
fn s(x: Result<i64>) -> Result<i64> { return identity::<Result<i64>>(x); }
""")
    by = dict((s.stem, s) for s in plan.fn_specs)
    pick = by["pruv_g3_f_4_pick_1_i"].func
    ident = by["pruv_g3_f_8_identity_1_ri"].func
    from codegen import gen_rust
    text = gen_rust(prog, plan=plan)
    return (plan.type_stems() == [] and pick.params[0].type == OPTION and ident.params[0].type == RESULT
            and pick.params[0].type.args == () and "pruv_g3_t_" not in text
            and "fn pruv_g3_f_4_pick_1_i(o: ::std::option::Option<i64>, d: i64) -> i64 {" in text)


@case
def order_is_declaration_then_encoding():
    _, plan = build("""
fn zeta<T>(x: T) -> T { return x; }
fn alpha<T>(x: T) -> T { return x; }
fn caller(x: bool) -> bool {
  let a: bool = alpha::<bool>(x);
  let b: i64 = zeta::<i64>(1);
  let c: bool = zeta::<bool>(x);
  return a;
}
""")
    return plan.fn_stems() == ["pruv_g3_f_4_zeta_1_b", "pruv_g3_f_4_zeta_1_i", "pruv_g3_f_5_alpha_1_b"]


@case
def order_does_not_depend_on_call_order():
    head = """
struct Pair<A, B> { first: A, second: B }
fn make<A, B>(a: A, b: B) -> Pair<A, B> { return Pair::<A, B> { first: a, second: b }; }
"""
    calls = ["fn r1() -> Pair<i64, bool> { return make::<i64, bool>(1, true); }",
             "fn r2() -> Pair<bool, i64> { return make::<bool, i64>(false, 2); }",
             "fn r3() -> Pair<bool, bool> { return make::<bool, bool>(false, true); }"]
    plans = []
    for order in ((0, 1, 2), (2, 1, 0), (1, 2, 0)):
        _, plan = build(head + "\n".join(calls[i] for i in order))
        d = plan.describe()
        d["functions"] = [n for n in d["functions"] if n.startswith("pruv_g3_")]   # roots follow the source order
        plans.append(json.dumps(d, sort_keys=True))
    _, again = build(head + "\n".join(calls))
    return len(set(plans)) == 1 and json.loads(plans[0])["fn_specs"] == [
        "pruv_g3_f_4_make_2_b_b", "pruv_g3_f_4_make_2_b_i", "pruv_g3_f_4_make_2_i_b"] \
        and json.dumps(again.describe(), sort_keys=True) == json.dumps(build(head + "\n".join(calls))[1].describe(),
                                                                        sort_keys=True)


@case
def checked_program_is_not_mutated():
    src = """
struct Pair<A, B> { first: A, second: B }
fn make<A, B>(a: A, b: B) -> Pair<A, B> { return Pair::<A, B> { first: a, second: b }; }
fn swap<A, B>(p: Pair<A, B>) -> Pair<B, A> { return make::<B, A>(p.second, p.first); }
fn r(p: Pair<i64, bool>) -> Pair<bool, i64> { return swap::<i64, bool>(p); }
"""
    prog = parse(src)
    check(prog)
    before = (repr(prog.types), repr(prog.functions),
              [f.name for f in prog.functions], [len(f.tparams) for f in prog.functions],
              [c.inst["decl"] for f in prog.functions for st in f.body if isinstance(st, Return)
               for c in [st.value] if isinstance(c, Call) and c.inst])
    plan = specialize(prog)
    after = (repr(prog.types), repr(prog.functions),
             [f.name for f in prog.functions], [len(f.tparams) for f in prog.functions],
             [c.inst["decl"] for f in prog.functions for st in f.body if isinstance(st, Return)
              for c in [st.value] if isinstance(c, Call) and c.inst])
    # the plan owns separate objects: no node of the concrete program is a node of the checked program
    src_ids = set()

    def walk(n):
        if isinstance(n, list):
            for x in n:
                walk(x)
        elif hasattr(n, "__dataclass_fields__") and not isinstance(n, Type):
            src_ids.add(id(n))
            for k in n.__dataclass_fields__:
                walk(getattr(n, k))
    walk(prog.functions)
    shared = []

    def walk2(n):
        if isinstance(n, list):
            for x in n:
                walk2(x)
        elif hasattr(n, "__dataclass_fields__") and not isinstance(n, Type):
            if id(n) in src_ids:
                shared.append(n)
            for k in n.__dataclass_fields__:
                walk2(getattr(n, k))
    walk2(plan.program.functions)
    return before == after and before[0] != "[]" and not shared and len(plan.fn_specs) == 2


def main():
    ok = 0
    for fn in cases:
        try:
            res = fn()
        except Exception as e:   # a crash is a failure with its message
            print("FAIL %s: %r" % (fn.__name__, e))
            continue
        print("%s %s" % ("PASS" if res else "FAIL", fn.__name__))
        ok += 1 if res else 0
    print("%d/%d passed" % (ok, len(cases)))
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
