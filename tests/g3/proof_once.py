#!/usr/bin/env python3
"""G3 A2 (G3_SPEC 7.4): a generic definition is verified ONCE, whatever the number of its instantiations.

    python tests/g3/proof_once.py        -> one line per check, then "N/N passed"; exit 0 on success

The same generic definitions are followed by 1, 2 and 10 callers that instantiate them at different concrete types.
Each program is parsed, checked and verified with verify.TraceRecorder (the official query-recording boundary of
verify.py). The obligation entries recorded for the generic functions (obligation sequence: code, position,
attempts with their SMT text and result) must be identical in the three runs; only the callers' own obligations
may grow. The SMT text is compared after normalizing the per-model datatype prefix (`m<N>t..!`, `m<N>g..!`).
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "pruvc"))

from vparser import parse    # noqa: E402
from check import check      # noqa: E402
import verify                # noqa: E402

GENERIC_FNS = ("identity", "wrap", "first", "dup")

# declarations first, then the generic definitions (so the callers never shift their lines or order)
PRELUDE = """\
struct Pair<A, B> {
  first: A,
  second: B
}

fn identity<T>(x: T) -> T
  ensures result == x
{
  return x;
}

fn wrap<T>(x: T) -> Option<T>
  ensures is_some(result) && some_val(result) == x
{
  return Some::<T>(x);
}

fn first<T: Element>(a: [T]) -> T
  requires len(a) > 0
  ensures result == a[0]
{
  return a[0];
}

fn dup<T>(x: T) -> Pair<T, T>
  ensures result.first == result.second
{
  return Pair::<T, T> { first: x, second: x };
}
"""

# ten distinct instantiations of identity / wrap (callers are appended AFTER the definitions)
TYPES = ["i64", "bool", "Option<i64>", "Option<bool>", "Result<i64>", "Result<bool>",
         "Pair<i64, bool>", "Pair<bool, i64>", "Option<Pair<i64, bool>>", "Pair<Option<bool>, Result<i64>>"]


def caller(i, ty):
    return """
fn use_%d(x: %s) -> %s
  ensures result == x
{
  let y: %s = identity::<%s>(x);
  let w: Option<%s> = wrap::<%s>(y);
  return identity::<%s>(y);
}
""" % (i, ty, ty, ty, ty, ty, ty, ty)


def source(n):
    return PRELUDE + "".join(caller(i, TYPES[i]) for i in range(n))


MODEL_PREFIX = re.compile(r"\bm\d+([tg])(\d+)!")


def norm(x):
    """normalize the per-Model datatype prefix in every string of a recorded obligation"""
    if isinstance(x, str):
        return MODEL_PREFIX.sub(r"m#\1\2!", x)
    if isinstance(x, list):
        return [norm(i) for i in x]
    if isinstance(x, dict):
        return {k: norm(v) for k, v in x.items()}
    return x


def run(n):
    prog = parse(source(n))
    check(prog)
    rec = verify.TraceRecorder()
    errs = verify.verify_program(prog, rec=rec)
    return errs, rec.obligations


cases = []


def case(fn):
    cases.append(fn)
    return fn


_cache = {}


def result(n):
    if n not in _cache:
        _cache[n] = run(n)
    return _cache[n]


def generic_part(obs):
    return [norm(o) for o in obs if o["fn"] in GENERIC_FNS]


@case
def all_programs_verify():
    for n in (1, 2, 10):
        errs, _ = result(n)
        assert not errs, "n=%d: %s" % (n, [e.to_json() for e in errs])


@case
def generic_definitions_have_obligations():
    _, obs = result(1)
    g = generic_part(obs)
    fns = sorted(set(o["fn"] for o in g))
    assert fns == sorted(GENERIC_FNS), fns
    codes = sorted(set(o["code"] for o in g))
    for c in ("ensures", "index_oob", "contract_domain"):
        assert c in codes, (c, codes)


@case
def generic_obligation_sequence_unchanged_1_2_10():
    base = json.dumps(generic_part(result(1)[1]), sort_keys=True)
    for n in (2, 10):
        other = json.dumps(generic_part(result(n)[1]), sort_keys=True)
        assert base == other, "generic obligations differ between 1 and %d instantiations" % n


@case
def each_generic_definition_verified_exactly_once():
    for n in (1, 2, 10):
        _, obs = result(n)
        for fn in GENERIC_FNS:
            mine = [o for o in obs if o["fn"] == fn]
            keys = [(o["line"], o["col"], o["code"], o["phase"], o["cand"]) for o in mine]
            assert mine, (n, fn)
            # no obligation of the definition is recorded twice (a re-verification per instance would repeat them)
            assert len(keys) == len(set(keys)), (n, fn, keys)
            assert all(o["phase"] == "verification" for o in mine), (n, fn)


@case
def only_the_callers_grow():
    c1 = len(result(1)[1])
    c2 = len(result(2)[1])
    c10 = len(result(10)[1])
    assert c1 < c2 < c10, (c1, c2, c10)
    g1 = len(generic_part(result(1)[1]))
    assert g1 == len(generic_part(result(10)[1]))
    for n in (1, 2, 10):
        callers = set(o["fn"] for o in result(n)[1]) - set(GENERIC_FNS)
        assert callers == set("use_%d" % i for i in range(n)), callers


@case
def generic_queries_declare_abstract_sorts():
    _, obs = result(1)
    text = "".join(a["smt2"] for o in obs if o["fn"] == "identity" for a in o["attempts"])
    assert "g3!0!T0" in text, text[:300]   # identity is the first function: declaration index 0


def main():
    passed = 0
    for fn in cases:
        try:
            fn()
            print("PASS %s" % fn.__name__)
            passed += 1
        except Exception as e:   # noqa: BLE001
            print("FAIL %s: %r" % (fn.__name__, e))
    print("%d/%d passed" % (passed, len(cases)))
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
