"""G3 A0 unit cases for the structured Type API (pruvc/vast.py, pruvc/typeinfo.py).
Run: .venv/bin/python tests/g3/type_substitution.py  -> one line per case, then "N/N passed"; exit 0 on success."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "pruvc"))

from vast import *            # noqa: E402
from typeinfo import *        # noqa: E402

# Declarations: struct Pair<T, U> { a: T, b: U }; enum Choice<T> { Left(T), Right(i64) }; struct Wrap<T> { p: Pair<T, T> }
# struct Point { x: i64 }; struct Bad { a: [i64] }; struct Cyc<T> { c: Cyc<T> }; struct Arr<T> { xs: [T] }
def P(decl, i, name):
    return mk_param(decl_owner(decl), i, name)

PT, PU = P("Pair", 0, "T"), P("Pair", 1, "U")
CT = P("Choice", 0, "T")
WT = P("Wrap", 0, "T")
DECLS = {
    "Pair": (2, [PT, PU]),
    "Choice": (1, [CT, I64]),
    "Wrap": (1, [mk_nominal("Pair", (WT, WT))]),
    "Point": (0, [I64]),
    "Bad": (0, [ARRAY]),
    "Cyc": (1, [mk_nominal("Cyc", (P("Cyc", 0, "T"),))]),
    "Arr": (1, [mk_array(P("Arr", 0, "T"))]),
}
FT = mk_param(fn_owner("f"), 0, "T")      # function f<T>
GT = mk_param(fn_owner("g"), 0, "T")      # function g<T>: same name, other declaration
POINT = mk_nominal("Point")

cases = []
def case(fn):
    cases.append(fn)
    return fn

def raises(exc, f):
    try:
        f()
    except exc:
        return True
    return False

@case
def legacy_constants_unchanged():
    return (I64.name == "i64" and I64.args == () and Type("array") == ARRAY and hash(Type("option")) == hash(OPTION)
            and POINT == Type("Point"))

@case
def option_i64_normalizes():
    return mk_option(I64) is OPTION or mk_option(I64) == OPTION

@case
def result_i64_normalizes():
    return mk_result(I64) == RESULT

@case
def arrays_normalize():
    return mk_array(I64) == ARRAY and mk_array(U8) == ARRAY_U8 and mk_array(BOOL) == ARRAY_BOOL

@case
def option_bool_is_structured():
    t = mk_option(BOOL)
    return t != OPTION and t.args == (BOOL,) and t == mk_option(BOOL) and hash(t) == hash(mk_option(BOOL))

@case
def legacy_dump_strings():
    return [type_name(t) for t in (I64, BOOL, UNIT, ARRAY, OPTION, RESULT, ARRAY_U8, ARRAY_BOOL, STR, POINT)] == \
        ["i64", "bool", "()", "[i64]", "Option<i64>", "Result<i64>", "[u8]", "[bool]", "str", "Point"] \
        and legacy_dump(OPTION) == "Option<i64>"

@case
def format_structured():
    return (format_type(mk_nominal("Pair", (I64, BOOL))) == "Pair<i64, bool>" and format_type(mk_array(FT)) == "[T]"
            and format_type(mk_option(BOOL)) == "Option<bool>" and type_name(mk_result(PT)) == "Result<T>"
            and format_type(mk_nominal("Choice", (mk_option(BOOL),))) == "Choice<Option<bool>>")

@case
def substitute_param():
    return substitute(FT, {param_id(FT): BOOL}) == BOOL

@case
def substitute_through_args():
    t = mk_nominal("Pair", (FT, mk_array(FT)))
    return substitute(t, {param_id(FT): I64}) == mk_nominal("Pair", (I64, ARRAY))

@case
def substitute_normalizes_legacy():
    return (substitute(mk_option(FT), {param_id(FT): I64}) == OPTION
            and substitute(mk_result(FT), {param_id(FT): I64}) == RESULT
            and substitute(mk_array(FT), {param_id(FT): U8}) == ARRAY_U8)

@case
def capture_avoidance_same_name():
    # f's T and g's T are both printed "T" but have different identity
    t = mk_nominal("Pair", (FT, GT))
    out = substitute(t, {param_id(FT): I64})
    return FT != GT and out == mk_nominal("Pair", (I64, GT))

@case
def capture_avoidance_simultaneous():
    # T := U-like param with the same name from another declaration is not re-substituted
    t = mk_nominal("Pair", (FT, GT))
    out = substitute(t, {param_id(FT): GT, param_id(GT): BOOL})
    return out == mk_nominal("Pair", (GT, BOOL))

@case
def unmapped_param_kept():
    return substitute(PT, {param_id(PU): I64}) == PT

@case
def same_name_two_declarations_distinct():
    return P("Pair", 0, "T") != P("Choice", 0, "T") and P("Pair", 0, "T") != P("Pair", 1, "T") \
        and len({P("Pair", 0, "T"), P("Choice", 0, "T"), P("Pair", 0, "T")}) == 2

@case
def repeated_parameter():
    m = bind_args(decl_owner("Pair"), 2, (BOOL, BOOL))
    return substitute(mk_nominal("Pair", (PT, PT)), {param_id(PT): I64}) == mk_nominal("Pair", (I64, I64)) \
        and nominal_fields(mk_nominal("Pair", (BOOL, BOOL)), DECLS) == [BOOL, BOOL] and m[(decl_owner("Pair"), 1)] == BOOL

@case
def nested_application_fields():
    t = mk_nominal("Wrap", (mk_option(BOOL),))
    return nominal_fields(t, DECLS) == [mk_nominal("Pair", (mk_option(BOOL), mk_option(BOOL)))]

@case
def nested_substitution():
    t = mk_nominal("Choice", (mk_nominal("Pair", (FT, mk_option(FT))),))
    out = substitute(t, {param_id(FT): BOOL})
    return out == mk_nominal("Choice", (mk_nominal("Pair", (BOOL, mk_option(BOOL))),))

@case
def arity_errors():
    return (raises(TypeArityError, lambda: bind_args(decl_owner("Pair"), 2, (I64,)))
            and raises(TypeArityError, lambda: check_arity(mk_nominal("Pair", (I64,)), DECLS))
            and raises(TypeArityError, lambda: check_arity(mk_nominal("Point", (I64,)), DECLS))
            and raises(TypeArityError, lambda: check_arity(mk_option(mk_nominal("Choice", ())), DECLS))
            and raises(TypeArityError, lambda: check_arity(Type("option", (I64, BOOL)), DECLS))
            and check_arity(mk_nominal("Pair", (I64, BOOL)), DECLS) is None)

@case
def admissible_scalars_and_builtins():
    return (is_value(I64, DECLS) and is_value(BOOL, DECLS) and is_value(OPTION, DECLS) and is_value(RESULT, DECLS)
            and is_value(mk_option(BOOL), DECLS) and is_value(mk_result(mk_option(BOOL)), DECLS))

@case
def inadmissible_types():
    return not any(is_value(t, DECLS) for t in (ARRAY, ARRAY_U8, ARRAY_BOOL, STR, UNIT, U8, mk_option(U8),
                                                mk_option(ARRAY), mk_option(STR)))

@case
def admissible_nominal():
    return (is_value(POINT, DECLS) and is_value(mk_nominal("Pair", (I64, mk_option(BOOL))), DECLS)
            and is_value(mk_nominal("Wrap", (BOOL,)), DECLS) and is_value(FT, DECLS))

@case
def inadmissible_nominal():
    return (not is_value(mk_nominal("Bad"), DECLS)                       # field is an array
            and not is_value(mk_nominal("Pair", (I64, STR)), DECLS)      # array-like argument
            and not is_value(mk_nominal("Arr", (I64,)), DECLS)           # substituted field is [i64]
            and not is_value(mk_nominal("Pair", (I64,)), DECLS)          # wrong arity
            and not is_value(mk_nominal("Nope"), DECLS)                  # unknown declaration
            and not is_value(mk_nominal("Cyc", (I64,)), DECLS))          # cycle guard

@case
def nested_same_declaration_is_value():
    # audit R1: Box<Box<i64>> is finite; the cycle guard must not confuse it with a declaration cycle
    bt = P("Box", 0, "T")
    grow = P("Grow", 0, "T")
    d = dict(DECLS, Box=(1, [bt]), Grow=(1, [mk_nominal("Grow", (mk_option(grow),))]))
    return (is_value(mk_nominal("Box", (mk_nominal("Box", (I64,)),)), d)
            and is_value(mk_nominal("Box", (mk_nominal("Box", (mk_nominal("Box", (BOOL,)),)),)), d)
            and not is_value(mk_nominal("Grow", (I64,)), d)
            and not is_value(mk_nominal("Grow2", (I64,)),
                             dict(d, Grow2=(1, [mk_nominal("Grow2", (mk_option(mk_option(P("Grow2", 0, "T"))),))])))
            and is_value(_deep_box(200), d))     # confirmation audit: no RecursionError, linear in depth


def _deep_box(n):
    t = I64
    for _ in range(n):
        t = mk_nominal("Box", (t,))
    return t

@case
def admissible_with_callable_decls():
    return is_value(mk_nominal("Pair", (I64, BOOL)), lambda n: DECLS.get(n))

@case
def element_check():
    ep = {param_id(FT)}
    return (is_element(I64) and is_element(BOOL) and is_element(FT, ep) and not is_element(FT)
            and not is_element(GT, ep) and not is_element(POINT) and not is_element(U8)
            and not is_element(mk_option(I64)) and not is_element(ARRAY))

@case
def dependencies_nested():
    t = mk_nominal("Pair", (mk_option(POINT), mk_nominal("Choice", (mk_nominal("Pair", (I64, POINT)),))))
    return dependencies(t) == ["Pair", "Point", "Choice"] and dependencies(mk_array(I64)) == [] \
        and dependencies(mk_array(FT)) == [] and dependencies(mk_result(mk_nominal("Wrap", (BOOL,)))) == ["Wrap"]

@case
def encode_scalars_and_builtins():
    return (encode(I64) == "i" and encode(BOOL) == "b" and encode(mk_option(BOOL)) == "ob"
            and encode(mk_result(mk_option(I64))) == "roi" and encode(OPTION) == "oi" and encode(RESULT) == "ri")

@case
def encode_nominal():
    return (encode(POINT) == "n5_Point_0" and encode(mk_nominal("Pair", (I64, BOOL))) == "n4_Pair_2_i_b"
            and encode(mk_nominal("Choice", (mk_nominal("Pair", (BOOL, mk_option(I64))),)))
            == "n6_Choice_1_n4_Pair_2_b_oi")

@case
def encode_name_with_underscore_and_utf8():
    return encode(mk_nominal("A_b", (I64,))) == "n3_A_b_1_i" and encode(mk_nominal("é")) == "n2_é_0"

@case
def encode_rejects_non_values():
    return raises(ValueError, lambda: encode(FT)) and raises(ValueError, lambda: encode(ARRAY)) \
        and raises(ValueError, lambda: encode(mk_option(STR)))

@case
def stem_examples():
    return (spec_fn_stem("identity", (I64,)) == "pruv_g3_f_8_identity_1_i"
            and spec_type_stem("Pair", (I64, BOOL)) == "pruv_g3_t_4_Pair_2_i_b"
            and spec_fn_stem("f", ()) == "pruv_g3_f_1_f_0")

@case
def legacy_helpers_still_work():
    return (is_array(ARRAY_U8) and array_elem(ARRAY) == I64 and array_elem(ARRAY_BOOL) == BOOL
            and array_of(U8) == ARRAY_U8 and not is_user_type(OPTION) and is_user_type(POINT)
            and not is_user_type(FT) and array_elem(mk_array(FT)) == FT and is_array(mk_array(FT)))


def main():
    ok = 0
    for fn in cases:
        try:
            good = bool(fn())
        except Exception as e:      # a crash is a failure, not an abort
            print("FAIL %s: %s: %s" % (fn.__name__, type(e).__name__, e))
            continue
        print("%s %s" % ("ok  " if good else "FAIL", fn.__name__))
        ok += good
    print("%d/%d passed" % (ok, len(cases)))
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
