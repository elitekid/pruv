# -*- coding: utf-8 -*-
"""G4 (modules, visibility, host entries) source-mutation test.

  python bench/g4/mutate_ops.py [OUT.json] [--jobs N] [--only qNN] [--limit N] [--timeout SEC]
  python bench/g4/mutate_ops.py --self-test      (catalogue checks only, no compiler)
  python bench/g4/mutate_ops.py --list

Mutants are derived from the multi-file reference projects bench/g4/solutions/q01 and q02: explicit edits
(problem, file, find, replace, operator, intent) plus a seeded sample of generic regex operators over all files. The
fixed root entry lines (ENTRY_CONTRACTS of run.py) are never mutated; child contracts, helper bodies, `decreases`
clauses, invariants and all bodies are. G4-specific operators: wrong_target (a cross-module call goes to a same-named
function of another module), weak_ensures (a child's public ensures is weakened while its callers stay), swapped_helper
(a private helper body is replaced), dropped_requires (a `requires` the caller or the body relies on is removed),
off_by_one (a child's loop, range or bound). Others follow bench/g9/mutate_ops.py: wrong_return, false_ensures,
deleted_progress (decreases), missing_base, wrong_arm, swapped_children, equivalent (rx_* are the generic regex ones).

Ground truth ("independent classification"): the mutant project is graded with --no-verify (rs compiler, rust backend)
by bench/g4/run.py. `incorrect` = the grader result is wrong (a crash or a non-terminating run also counts);
`correct` = tests pass; `not_compilable` = rejected even without verification; `unknown` = build failure.
`contract_weak` = wrong results that still satisfy every stated entry ensures on all test inputs (only problems whose
contracts do not state the full meaning, run.py CONTRACT_CHECKS: q02 tree_height), that change no signature/contract
line of any file, and whose every function contract (helpers and child modules included) the independent interpreter
bench/fuzz/oracle.py finds satisfied on all test inputs (weak_eligible; the multi-file project is flattened to one file
for the interpreter, see flatten). A mutant that breaks a helper or child contract is incorrect. Such a mutant is not
a source-contract mutant; it is reported separately and a verified one is not counted as wrong_but_proved.

`intent` is the label the author gave a mutant: incorrect (results differ from the reference), weak (results differ but
all stated contracts hold), contract (behaviour unchanged, a contract or annotation was weakened/falsified so the
modular proof must fail), correct (behaviour and contracts equivalent, a sound verifier may accept it; a rejection is a
false rejection and only reported), auto (generic regex mutant, no intent). Intents that disagree with the ground truth
are listed as intent_mismatch (informational).

Per mutant and per configuration (py/rs x rust/llvm) the verifier verdict plus the grader result give one class:
  rejected_verify    the compiler rejected the mutant in the verifier stage
  rejected_checker   rejected in the parse/type/effect stages
  accepted_correct   accepted, tests pass
  wrong_but_proved   accepted and the grader result is wrong (a failure without a diagnostic counts here too)
  unknown            verify_unknown / inference_timeout
  timeout            compiler timeout or test-run timeout
  crash              compiler crash / internal error / harness error
  unsupported        codegen / unsupported-feature rejection (not a semantic rejection)
  unexecuted         accepted but the generated code could not be built (so no grader result)
Only rejected_* count as successful rejections; unknown/timeout/crash/unsupported/unexecuted are reported as their own
classes. The mutant's overall class is the worst configuration (order: wrong_but_proved, crash, timeout, unsupported,
unknown, unexecuted, accepted_correct, rejected_checker, rejected_verify).
Exit code 1 when wrong_but_proved > 0, when an incorrect mutant has an unresolved class (unknown/timeout/crash/
unsupported/unexecuted) or is accepted with passing tests, when a `contract` mutant is accepted on any configuration, or
when (without --only/--limit) fewer than 30 mutants or fewer than 20 incorrect mutants exist.
"""
import importlib.util
import json
import os
import random
import re
import shutil
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REF_DIR = os.path.join(HERE, "solutions")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load("g4_run", os.path.join(HERE, "run.py"))
try:
    G2M = _load("g2_mutate_ops", os.path.join(ROOT, "bench", "g2", "mutate_ops.py"))   # versions() only
except Exception:                                                                       # pragma: no cover
    G2M = None

CONFIGS = [(c, b) for c in ("py", "rs") for b in ("rust", "llvm")]
CHECK_STAGES = ("parse", "type", "effect")
UNDECIDED_CODES = ("inference_timeout", "verify_unknown")
RJ_V, RJ_C, ACC, WBP, UNK, TMO, CRA, UNS, UNE = ("rejected_verify", "rejected_checker", "accepted_correct",
                                                 "wrong_but_proved", "unknown", "timeout", "crash", "unsupported",
                                                 "unexecuted")
SEVERITY = [WBP, CRA, TMO, UNS, UNK, UNE, ACC, RJ_C, RJ_V]
UNRESOLVED = (CRA, TMO, UNS, UNK, UNE)
RUN_TIMEOUT = 60          # seconds for one generated test program (mutants may loop forever)
MIN_MUTANTS, MIN_INCORRECT, GENERIC_CAP = 30, 20, 20

# ------------------------------------------------------------------ explicit catalogue
EXPLICIT = []   # {"pid", "op", "intent", "desc", "edits": [(file, old, new, occ)]}

R, S, C, T, H = "root.pruv", "store.pruv", "store/check.pruv", "tree.pruv", "tree/shape.pruv"

WT, WE, SH, DR, OB = "wrong_target", "weak_ensures", "swapped_helper", "dropped_requires", "off_by_one"
WR, FE, DP, MB, WA, SC, EQ = ("wrong_return", "false_ensures", "deleted_progress", "missing_base", "wrong_arm",
                              "swapped_children", "equivalent")
INC, WEAK, CON, COR = "incorrect", "weak", "contract", "correct"


def E(pid, op, intent, desc, file, old, new, occ="one"):
    EXPLICIT.append({"pid": pid, "op": op, "intent": intent, "desc": desc, "edits": [(file, old, new, occ)]})


def ME(pid, op, intent, desc, edits):
    EXPLICIT.append({"pid": pid, "op": op, "intent": intent, "desc": desc,
                     "edits": [(e[0], e[1], e[2], e[3] if len(e) > 3 else "one") for e in edits]})


# ---- q01: bounded array service (root.pruv, store.pruv, store/check.pruv)
# store.pruv: find
E("q01", WR, INC, "find: not found gives 0", S, "    return 0 - 1;", "    return 0;")
E("q01", WR, INC, "find: found index plus one", S, "  return i;", "  return i + 1;")
E("q01", WA, INC, "find: loop stops at the first element that differs", S, "&& a[i] != q", "&& a[i] == q")
E("q01", OB, INC, "find: end test one early", S, "if i == len(a) {", "if i + 1 == len(a) {")
E("q01", OB, INC, "find: starts at 1", S, "let mut i: i64 = 0;", "let mut i: i64 = 1;")
E("q01", OB, INC, "find: steps by two", S, "    i = i + 1;\n  }\n  if i == len(a) {",
  "    i = i + 2;\n  }\n  if i == len(a) {")
E("q01", EQ, COR, "find: -1 as unary minus", S, "return 0 - 1;", "return -1;")
E("q01", EQ, COR, "find: end test with >=", S, "if i == len(a) {", "if i >= len(a) {")
E("q01", WE, CON, "find: third ensures dropped (root relies on it)", S,
  "  ensures result < 0 ==> (forall k in 0..len(a): a[k] != q)\n", "")
E("q01", WE, CON, "find: second ensures loses the prefix fact (root relies on it)", S,
  "ensures result >= 0 ==> a[result] == q && (forall k in 0..result: a[k] != q)",
  "ensures result >= 0 ==> a[result] == q")
E("q01", DP, CON, "find: decreases does not shrink", S, "    decreases len(a) - i\n", "    decreases len(a)\n")
# store.pruv: range_sum
E("q01", OB, INC, "range_sum: starts one element late", S, "let mut i: i64 = lo;", "let mut i: i64 = lo + 1;")
E("q01", OB, INC, "range_sum: stops one element early", S, "while i < hi", "while i + 1 < hi")
E("q01", OB, INC, "range_sum: includes the end element", S, "while i < hi", "while i <= hi")
E("q01", WR, INC, "range_sum: subtracts", S, "s = s + a[i];", "s = s - a[i];")
E("q01", WR, INC, "range_sum: loses the running sum", S, "s = s + a[i];", "s = a[i];")
E("q01", WR, INC, "range_sum: sum starts at 1", S, "let mut s: i64 = 0;", "let mut s: i64 = 1;")
E("q01", EQ, COR, "range_sum: commuted addition", S, "s = s + a[i];", "s = a[i] + s;")
# redundant bound: array parameters already have len(a) <= 2^40 (SPEC §6), and 2^40 * 10^6 fits in i64
E("q01", DR, COR, "range_sum: requires loses the length bound (redundant; arrays are at most 2^40 long)", S,
  "requires 0 <= lo && lo <= hi && hi <= len(a) && len(a) <= 1000",
  "requires 0 <= lo && lo <= hi && hi <= len(a)")
E("q01", WE, CON, "range_sum: ensures weakened to a range (root relies on the exact sum)", S,
  "  ensures result == sum(k in lo..hi: a[k])\n", "  ensures result >= -1000000000\n")
E("q01", FE, CON, "range_sum: ensures plus one", S, "ensures result == sum(k in lo..hi: a[k])",
  "ensures result == sum(k in lo..hi: a[k]) + 1")
E("q01", FE, CON, "range_sum: sum invariant dropped", S, "    invariant s == sum(k in lo..i: a[k])\n", "")
E("q01", FE, CON, "range_sum: index invariant loses its upper bound", S, "    invariant lo <= i && i <= hi\n",
  "    invariant lo <= i\n")
# store.pruv: insert and the private helper next
E("q01", WR, INC, "insert: shifted copy writes at the unshifted index", S, "out[s] = a[m];", "out[m] = a[m];")
E("q01", WR, INC, "insert: the new element is 0", S, "out[i] = v;", "out[i] = 0;")
E("q01", OB, INC, "insert: prefix copy reads one element ahead", S, "out[p] = a[p];", "out[p] = a[p + 1];")
E("q01", OB, INC, "insert: suffix copy starts one element late", S, "let mut m: i64 = i;", "let mut m: i64 = i + 1;")
E("q01", OB, INC, "insert: result one element too short", S, "alloc(len(a) + 1, v)", "alloc(len(a), v)")
E("q01", OB, INC, "insert: prefix loop includes position i", S, "while p < i", "while p <= i")
E("q01", EQ, COR, "insert: explicit store of the new element dropped (alloc already fills it)", S,
  "  out[i] = v;\n", "")
E("q01", DR, CON, "insert: requires loses the position bound (the store out[i] is no longer provable)", S,
  "requires 0 <= i && i <= len(a) && len(a) <= 1000", "requires len(a) <= 1000")
E("q01", WE, CON, "insert: length ensures dropped (root indexes the result)", S,
  "  ensures len(result) == len(a) + 1\n", "")
E("q01", WE, CON, "insert: shifted part of the ensures dropped (root relies on it)", S,
  " && (k > i ==> result[k] == a[k - 1])", "")
E("q01", SH, INC, "private next returns x + 2", S, "return x + 1;", "return x + 2;")
ME("q01", SH, INC, "private next returns x + 2 and says so", [(S, "return x + 1;", "return x + 2;"),
                                                                (S, "ensures result == x + 1", "ensures result == x + 2")])
E("q01", DR, CON, "private next loses its requires (overflow no longer provable)", S,
  "  requires 0 <= x && x <= 1000000\n", "")
# store.pruv: within (exclusive end)
E("q01", SH, INC, "store::within body uses an inclusive end", S, "return 0 <= i && i < n;", "return 0 <= i && i <= n;")
E("q01", WE, CON, "store::within ensures weakened to an implication (root relies on both directions)", S,
  "ensures result == (0 <= i && i < n)", "ensures result ==> (0 <= i && i < n)")
E("q01", EQ, COR, "store::within with the comparison commuted", S, "return 0 <= i && i < n;", "return i >= 0 && i < n;")
# store/check.pruv
E("q01", MB, INC, "check::valid_range loses the upper bound test", C, "  if hi > n {\n    return false;\n  }\n", "")
E("q01", MB, INC, "check::valid_range loses the order test", C, "  if lo > hi {\n    return false;\n  }\n", "")
E("q01", OB, INC, "check::valid_range rejects lo == 0", C, "if lo < 0 {", "if lo < 1 {")
E("q01", OB, INC, "check::valid_range rejects empty ranges", C, "if lo > hi {", "if lo >= hi {")
E("q01", OB, INC, "check::within has an exclusive end", C, "return 0 <= i && i <= n;", "return 0 <= i && i < n;")
E("q01", WE, CON, "check::within ensures weakened to an implication", C,
  "  ensures result == (0 <= i && i <= n)", "  ensures result ==> (0 <= i && i <= n)")
E("q01", WE, CON, "check::valid_range ensures weakened to an implication", C,
  "ensures result == (0 <= lo && lo <= hi && hi <= n)", "ensures result ==> (0 <= lo && lo <= hi && hi <= n)")
E("q01", FE, CON, "check::within ensures says exclusive end, body unchanged", C,
  "  ensures result == (0 <= i && i <= n)", "  ensures result == (0 <= i && i < n)")
# root.pruv (entry contract lines are never touched)
E("q01", WR, INC, "find_first forwards 0 instead of q", R, "return crate::store::find(a, q);",
  "return crate::store::find(a, 0);")
E("q01", SC, INC, "sum_range: range arguments swapped in the check", R,
  "crate::store::check::valid_range(lo, hi, len(a))", "crate::store::check::valid_range(hi, lo, len(a))")
E("q01", WR, INC, "sum_range: invalid range answered with 0", R,
  "valid_range(lo, hi, len(a)) {\n    return 0 - 1;", "valid_range(lo, hi, len(a)) {\n    return 0;")
E("q01", OB, INC, "sum_range: forwards hi - 1", R, "crate::store::range_sum(a, lo, hi)",
  "crate::store::range_sum(a, lo, hi - 1)")
E("q01", OB, INC, "insert_get: reads index j + 1", R, "return out[j];", "return out[j + 1];")
E("q01", SC, INC, "insert_get: inserts at j instead of i", R, "crate::store::insert(a, i, v)",
  "crate::store::insert(a, j, v)")
E("q01", MB, INC, "insert_get: j check dropped", R,
  "  if !crate::store::within(j, len(a) + 1) {\n    return 0 - 1;\n  }\n", "")
E("q01", MB, INC, "insert_get: i check dropped", R,
  "  if !crate::store::check::within(i, len(a)) {\n    return 0 - 1;\n  }\n", "")
E("q01", WT, INC, "insert_get: j check goes to check::within (inclusive end) with the same arguments", R,
  "crate::store::within(j, len(a) + 1)", "crate::store::check::within(j, len(a) + 1)")
E("q01", WT, INC, "insert_get: i check goes to store::within (exclusive end)", R,
  "crate::store::check::within(i, len(a))", "crate::store::within(i, len(a))")
E("q01", OB, INC, "insert_get: j check against len(a) with the exclusive store::within", R,
  "crate::store::within(j, len(a) + 1)", "crate::store::within(j, len(a))")
E("q01", WT, COR, "insert_get: j check goes to check::within with the matching bound (equivalent)", R,
  "crate::store::within(j, len(a) + 1)", "crate::store::check::within(j, len(a))")
E("q01", EQ, COR, "sum_range: check compared with == false", R,
  "if !crate::store::check::valid_range(lo, hi, len(a)) {",
  "if crate::store::check::valid_range(lo, hi, len(a)) == false {")

# ---- q02: recursive tree service (root.pruv, tree.pruv, tree/shape.pruv)
# tree.pruv: build
E("q02", DP, INC, "build: right subtree not smaller", T, "build(mid + 1, hi)", "build(mid, hi)")
E("q02", DP, INC, "build: left subtree is the whole range", T, "build(lo, mid)", "build(lo, hi)")
E("q02", OB, INC, "build: left range one too long", T, "build(lo, mid)", "build(lo, mid + 1)")
E("q02", MB, INC, "build loses its base case", T, "  if lo == hi {\n    return Tree::Empty;\n  }\n", "")
E("q02", WR, INC, "build: base case builds a node", T, "return Tree::Empty;",
  "return Tree::Node(lo, Tree::Empty, Tree::Empty);")
E("q02", SC, COR, "build: children built in the other order (same shape, same counts)", T,
  "Tree::Node(mid, build(lo, mid), build(mid + 1, hi))", "Tree::Node(mid, build(mid + 1, hi), build(lo, mid))")
E("q02", WT, WEAK, "build: split by the same-named tree::middle (right-leaning) instead of shape::middle", T,
  "crate::tree::shape::middle(lo, hi)", "middle(lo, hi)")
E("q02", WE, CON, "build: ensures weakened (root make relies on the exact size)", T,
  "  ensures size(result) == 2 * (hi - lo) + 1\n", "  ensures size(result) >= 1\n")
# tree.pruv: node_count / leaf_count
E("q02", WA, INC, "node_count: Empty counts 1", T, "Tree::Empty => { return 0; }", "Tree::Empty => { return 1; }", 0)
E("q02", WA, INC, "node_count: node does not count itself", T, "return 1 + node_count(l) + node_count(r);",
  "return node_count(l) + node_count(r);")
E("q02", SC, INC, "node_count: only the left subtree", T, "return 1 + node_count(l) + node_count(r);",
  "return 1 + node_count(l);")
E("q02", SC, INC, "node_count: right subtree counted twice", T, "return 1 + node_count(l) + node_count(r);",
  "return 1 + node_count(r) + node_count(r);")
E("q02", WA, INC, "node_count: node counts 2", T, "return 1 + node_count(l) + node_count(r);",
  "return 2 + node_count(l) + node_count(r);")
E("q02", EQ, COR, "node_count: commuted addition", T, "return 1 + node_count(l) + node_count(r);",
  "return node_count(l) + 1 + node_count(r);")
E("q02", WE, CON, "node_count: ensures weakened to <= (root relies on equality)", T,
  "ensures 2 * result + 1 == size(t)", "ensures 2 * result + 1 <= size(t)")
E("q02", DR, CON, "node_count: requires loses the size bound (overflow no longer provable)", T,
  "  requires size(t) <= 2001\n", "", 0)
E("q02", DP, CON, "node_count: decreases is constant", T, "decreases size(t)", "decreases 0", 0)
E("q02", WA, INC, "leaf_count: Empty counts 0", T, "Tree::Empty => { return 1; }", "Tree::Empty => { return 0; }")
E("q02", SC, INC, "leaf_count: only the left subtree", T, "return leaf_count(l) + leaf_count(r);",
  "return leaf_count(l);")
E("q02", WA, INC, "leaf_count: node counts 1", T, "return leaf_count(l) + leaf_count(r);",
  "return 1 + leaf_count(l) + leaf_count(r);")
E("q02", SC, INC, "leaf_count: left subtree counted twice", T, "return leaf_count(l) + leaf_count(r);",
  "return leaf_count(l) + leaf_count(l);")
E("q02", EQ, COR, "leaf_count: commuted addition", T, "return leaf_count(l) + leaf_count(r);",
  "return leaf_count(r) + leaf_count(l);")
E("q02", WE, CON, "leaf_count: ensures weakened to <= (root relies on equality)", T,
  "ensures 2 * result - 1 == size(t)", "ensures 2 * result - 1 <= size(t)")
# tree.pruv: height and the private helper larger (the height contract is weak: wrong heights can verify)
E("q02", WR, WEAK, "height: only the left height", T, "return larger(hl, hr) + 1;", "return hl + 1;")
E("q02", WR, WEAK, "height: only the right height", T, "return larger(hl, hr) + 1;", "return hr + 1;")
E("q02", WR, WEAK, "height: node count instead of height", T, "return larger(hl, hr) + 1;", "return hl + hr + 1;")
E("q02", WR, WEAK, "height: the node itself is not counted", T, "return larger(hl, hr) + 1;", "return larger(hl, hr);")
E("q02", SH, INC, "private larger returns the smaller value", T, "if a > b {", "if a < b {")
E("q02", WE, CON, "height: ensures loses the size bound (root relies on it)", T,
  "ensures 0 <= result && result <= size(t)", "ensures 0 <= result")
E("q02", DP, COR, "height: decreases shifted by one (still a valid measure)", T, "decreases size(t)",
  "decreases size(t) + 1", 2)
# tree/shape.pruv
E("q02", SH, INC, "shape::middle returns the right-most index", H, "return lo + (hi - lo) / 2;", "return hi - 1;")
E("q02", SH, INC, "shape::middle returns the left-most index", H, "return lo + (hi - lo) / 2;", "return lo;")
E("q02", OB, INC, "shape::middle rounds up", H, "return lo + (hi - lo) / 2;", "return lo + (hi - lo + 1) / 2;")
ME("q02", WE, CON, "shape::middle: both ensures weakened (build relies on lo <= mid < hi)",
   [(H, "  ensures lo <= result && result < hi\n", "  ensures lo <= result && result <= hi\n"),
    (H, "  ensures result == lo + (hi - lo) / 2\n", "")])
E("q02", WE, COR, "shape::middle: exact-value ensures dropped (build only needs the range)", H,
  "  ensures result == lo + (hi - lo) / 2\n", "")
E("q02", DR, CON, "shape::middle: requires loses lo < hi (the division is no longer provable)", H,
  "requires 0 <= lo && lo < hi", "requires 0 <= lo")
# root.pruv
E("q02", WT, INC, "node_total walks with leaf_count", R, "return crate::tree::node_count(t);",
  "return crate::tree::leaf_count(t);")
E("q02", WT, INC, "leaf_total walks with node_count", R, "return crate::tree::leaf_count(t);",
  "return crate::tree::node_count(t);")
E("q02", OB, INC, "make builds one node too few", R, "return crate::tree::build(0, n);",
  "return crate::tree::build(0, n - 1);")
E("q02", OB, INC, "make builds from 1", R, "return crate::tree::build(0, n);", "return crate::tree::build(1, n);")
E("q02", DR, CON, "make: requires loses the upper bound (build relies on it)", R,
  "  requires 0 <= n && n <= 1000\n", "  requires 0 <= n\n", 0)
E("q02", WE, CON, "make: ensures weakened (the walks rely on the exact size)", R,
  "  ensures size(result) == 2 * n + 1\n", "  ensures size(result) >= 1\n")
E("q02", WT, WEAK, "tree_height answers with node_count (still within the weak contract)", R,
  "return crate::tree::height(t);", "return crate::tree::node_count(t);")
E("q02", WR, WEAK, "tree_height answers 0 (still within the weak contract)", R,
  "return crate::tree::height(t);", "return 0;")


# ------------------------------------------------------------------ generic regex operators
REGEX_OPS = [
    ("rx_le_to_lt", r"<=", "<"),
    ("rx_lt_to_le", r"(?<![<=>!-])<(?![=<-])", "<="),
    ("rx_ge_to_gt", r">=", ">"),
    ("rx_gt_to_ge", r"(?<![=\-<>])>(?![=>])", ">="),
    ("rx_plus1_to_plus0", r"\+ 1\b", "+ 0"),
    ("rx_plus1_to_plus2", r"\+ 1\b", "+ 2"),
    ("rx_minus1_to_minus2", r"- 1\b", "- 2"),
    ("rx_range_from_1", r"\b0\.\.", "1.."),
    ("rx_eq_to_ne", r"==(?!>)", "!="),
    ("rx_ne_to_eq", r"!=", "=="),
    ("rx_and_to_or", r"&&", "||"),
    ("rx_plus_to_minus", r" \+ ", " - "),
]


def ref_files(pid):
    """{relative path: text} of the reference project of pid."""
    out = {}
    for rel in G.FILES[pid]:
        with open(os.path.join(REF_DIR, pid, rel), encoding="utf-8") as f:
            out[rel] = f.read()
    return out


def apply_edit(text, old, new, occ="one"):
    """occ: "one" (anchor must be unique), "all", or the 0-based index of the occurrence."""
    n = text.count(old)
    if n == 0:
        raise ValueError("anchor not found: %r" % old)
    if occ == "all":
        return text.replace(old, new)
    if occ == "one":
        if n != 1:
            raise ValueError("anchor not unique (%d times): %r" % (n, old))
        return text.replace(old, new)
    if occ >= n:
        raise ValueError("occurrence %d of %d not found: %r" % (occ, n, old))
    idx = -1
    for _ in range(occ + 1):
        idx = text.index(old, idx + 1)
    return text[:idx] + new + text[idx + len(old):]


def protected_lines(text, pid, rel):
    """0-based line numbers of the root entry headers (signature, requires, ensures) that must never be mutated."""
    prot = set()
    if rel != "root.pruv":
        return prot
    lines = text.split("\n")
    for name in G.ENTRY_CONTRACTS[pid]:
        m = re.search(r"\bpub\s+fn\s+%s\s*\(" % re.escape(name), text)
        if not m:
            continue
        end = text.find("{", m.start())
        first, last = text.count("\n", 0, m.start()), text.count("\n", 0, end)
        prot.update(range(first, last + 1))
    return prot


def generic_candidates(pid):
    base = ref_files(pid)
    out = []
    for rel in G.FILES[pid]:
        text = base[rel]
        lines = text.split("\n")
        prot = protected_lines(text, pid, rel)
        for op, pat, rep in REGEX_OPS:
            rx = re.compile(pat)
            for i, line in enumerate(lines):
                if i in prot or not line.strip() or line.strip().startswith("//"):
                    continue
                for m in rx.finditer(line):
                    new_line = line[:m.start()] + rep + line[m.end():]
                    files = dict(base)
                    files[rel] = "\n".join(lines[:i] + [new_line] + lines[i + 1:])
                    out.append({"pid": pid, "op": op, "intent": "auto", "files": files,
                                "desc": "%s line %d: `%s` -> `%s`" % (rel, i + 1, m.group(0), rep),
                                "edit": [{"file": rel, "line": i + 1, "from": line.strip(), "to": new_line.strip()}]})
    return out


def _key(files, pid):
    return tuple(files[rel] for rel in G.FILES[pid])


def build_catalogue():
    """List of mutants {"id","pid","op","intent","desc","files","edit"}; identical-to-original and duplicate projects
    are skipped."""
    items, seen = [], {}
    for pid in G.PROBLEMS:
        seen[pid] = {_key(ref_files(pid), pid)}

    def add(it):
        k = _key(it["files"], it["pid"])
        if k in seen[it["pid"]]:
            return False
        seen[it["pid"]].add(k)
        it["id"] = "m%03d" % (len(items) + 1)
        items.append(it)
        return True

    for e in EXPLICIT:
        files = ref_files(e["pid"])
        for rel, old, new, occ in e["edits"]:
            files[rel] = apply_edit(files[rel], old, new, occ)
        add({"pid": e["pid"], "op": e["op"], "intent": e["intent"], "desc": e["desc"], "files": files,
             "kind": "explicit", "edit": [{"file": rel, "from": o, "to": n} for rel, o, n, _ in e["edits"]]})
    cands = []
    for pid in G.PROBLEMS:
        cands += generic_candidates(pid)
    fresh = [c for c in cands if _key(c["files"], c["pid"]) not in seen[c["pid"]]]
    random.Random(4).shuffle(fresh)
    n = 0
    for c in fresh:
        if n >= GENERIC_CAP:
            break
        c["kind"] = "regex"
        n += add(c)
    return items


# ------------------------------------------------------------------ classification
def config_class(r):
    """(class, detail) of one grade_one result."""
    st = r.get("status")
    if st == "pruv_error":
        rc, errs = r.get("rc"), [e for e in (r.get("pruv_errors") or []) if isinstance(e, dict)]
        if rc == -1:
            return TMO, "compiler timeout"
        if rc == -2:
            return CRA, "compiler could not be started"
        if not errs:
            return CRA, "exit %s without a diagnostic: %s" % (rc, (r.get("stderr") or "")[-120:])
        e = errs[0]
        stage, code = e.get("stage"), e.get("code")
        if stage == "grader":
            return CRA, "harness: %s" % e.get("message")
        if stage == "internal":
            return CRA, "internal error: %s" % (e.get("message") or code)
        if all(x.get("code") in UNDECIDED_CODES for x in errs):
            return UNK, "%s/%s" % (stage, code)
        if stage == "codegen" or "unsupported" in str(code):
            return UNS, "%s/%s" % (stage, code)
        return (RJ_C if stage in CHECK_STAGES else RJ_V), "%s/%s" % (stage, code)
    if st == "ok":
        return ACC, "tests pass"
    if st == "wrong":
        return WBP, "accepted but wrong: %s" % (r.get("first_failure") or r.get("first_panic") or
                                                 "exit %s" % r.get("exit_code"))
    if st == "timeout":
        return TMO, "test run timeout"
    if st == "compile_error":
        return UNE, "generated code did not build: %s" % (r.get("compile_error") or "")[:100].replace("\n", " ")
    return CRA, "status %s" % st


# ---- flattening a module project into one file for the independent interpreter (bench/fuzz/oracle.py)
def flatten(files):
    """One single-file program with the same behaviour as the module project, for the reference interpreter, which
    knows neither `mod`, `pub` nor `crate::` paths. Every item of a child module is renamed with its module path
    (functions `mod_store_check_within`, types `ModStoreCheckName`); root items keep their names; `crate::a::b::item` and
    unqualified references (same file only) are rewritten to the new names; `mod x;` lines and `pub` are dropped.
    Mutant projects use only names that exist, so the result is a faithful single-file image of the project."""
    mods = {}
    for rel, text in files.items():
        mp = () if rel == "root.pruv" else tuple(rel[:-len(".pruv")].split("/"))
        mods[mp] = strip(text)
    decl = {}
    for mp, text in mods.items():
        decl[mp] = {name: kind for kind, name in re.findall(r"\b(fn|struct|enum)\s+([A-Za-z_]\w*)", text)}

    def newname(mp, name):
        if mp == () or name not in decl.get(mp, {}):
            return name
        if decl[mp][name] == "fn":
            return "mod_" + "_".join(mp) + "_" + name       # prefixed: root `tree_height` vs `tree::height`
        return "Mod" + "".join(p.capitalize() for p in mp) + name

    tok = re.compile(r"crate(?:::[A-Za-z_]\w*)+|[A-Za-z_]\w*")

    def convert(mp, text):
        def rep(m):
            s = m.group(0)
            if s.startswith("crate::"):
                segs = s.split("::")[1:]
                for n in range(len(segs) - 1, 0, -1):
                    if tuple(segs[:n]) in mods:
                        return newname(tuple(segs[:n]), segs[n]) + "".join("::" + x for x in segs[n + 1:])
                return newname((), segs[0]) + "".join("::" + x for x in segs[1:])
            before = text[max(0, m.start() - 2):m.start()]
            if before == "::" or before.endswith("."):
                return s
            if s in decl[mp]:
                return newname(mp, s)
            return s
        return tok.sub(rep, text)

    parts = []
    for mp in sorted(mods, key=lambda p: (len(p), p)):
        text = re.sub(r"^[ \t]*mod\s+\w+\s*;[ \t]*$", "", mods[mp], flags=re.M)
        text = re.sub(r"\bpub\s+", "", text)
        parts.append(convert(mp, text))
    return "\n".join(parts)


def strip(text):
    return re.sub(r"//[^\n]*", "", text)


_ORACLE_LOCK = threading.Lock()


def _oracle_contract_failures(files, pid):
    """Contract failures (requires/ensures/invariant/assert/decreases of every function of every module) the
    independent reference interpreter bench/fuzz/oracle.py records over all test inputs of pid, or None when the
    interpreter cannot run the (flattened) program."""
    O = _load("fuzz_oracle", os.path.join(ROOT, "bench", "fuzz", "oracle.py"))
    out, box = set(), {}

    def go():
        try:
            prog = O.parse_program(flatten(files))
            for fn, args, _exp in G.tests()[pid]:
                r = O.run(prog, fn, [v for _k, v in args], fn_decreases=True, max_steps=100_000_000)
                out.update(r["contract_failures"])
                if r["kind"] != "ok":
                    out.add("fault %s in %s" % (r["kind"], fn))
            box["ok"] = True
        except (O.OracleUnsupported, O.OracleParseError, RecursionError, ValueError, KeyError):
            box["ok"] = False

    with _ORACLE_LOCK:                   # the recursion limit and thread stack size are process-wide
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 200000))
        threading.stack_size(512 * 1024 * 1024)
        try:
            t = threading.Thread(target=go)
            t.start()
        finally:
            threading.stack_size(0)
        t.join()
    return sorted(out) if box.get("ok") else None


def weak_eligible(files, pid):
    """(eligible, why). A wrong mutant is contract_weak only when no signature/contract line of any file changed and
    the independent interpreter finds every stated contract of every function (helpers and child modules included)
    satisfied on all test inputs. A mutant that breaks a helper or child contract is a source-contract mutant the
    verifier must reject."""
    import difflib
    base = ref_files(pid)
    for rel in G.FILES[pid]:
        if files[rel] == base[rel]:
            continue
        orig = base[rel].split("\n")
        changed = set()
        for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, orig, files[rel].split("\n"),
                                                             autojunk=False).get_opcodes():
            if tag != "equal":
                changed.update(range(i1, max(i2, i1 + 1)))
        src = "\n".join(orig)
        for m in re.finditer(r"^\s*(?:pub\s+)?fn\s+\w+\s*\(", src, re.M):
            first, blin = src.count("\n", 0, m.start()), src.count("\n", 0, src.find("{", m.start()))
            if any(first <= i <= blin for i in changed):
                return False, "edits a signature or contract line in %s" % rel
    fails = _oracle_contract_failures(files, pid)
    if fails is None:
        return False, "reference interpreter cannot run it"
    if fails:
        return False, "breaks %s" % ", ".join(fails[:3])
    return True, ""


def truth_of(path, pid, work, files=None):
    """Independent ground truth from the grader under --no-verify (rs compiler, rust backend); path is the project
    directory."""
    r = G.grade_one(path, pid, "rs", "rust", ["--no-verify"], work, timeout=RUN_TIMEOUT)
    st = r.get("status")
    if st == "wrong":
        if pid in G.CONTRACT_CHECKS and not r.get("exit_code") and files is not None:
            # the stated contracts do not fix the results (PROBLEMS.md q02 tree_height): a mutant whose every result
            # still satisfies the stated ensures is contract-weak, not a source-contract mutant the verifier must reject
            c = G.grade_one(path, pid, "rs", "rust", ["--no-verify"], work, timeout=RUN_TIMEOUT, contracts=True)
            if c.get("status") == "ok":
                ok, why = weak_eligible(files, pid)
                if ok:
                    return "contract_weak", "keeps the stated contracts; %s" % (r.get("first_failure") or "")
                return "incorrect", "%s; %s" % (why, r.get("first_failure") or "")
        return "incorrect", r.get("first_failure") or "exit %s" % r.get("exit_code")
    if st == "timeout":
        return "incorrect", "does not terminate on the tests (timeout)"
    if st == "ok":
        return "correct", "tests pass"
    if st == "pruv_error" and r.get("rc") == 1 and r.get("pruv_errors"):
        e = r["pruv_errors"][0]
        return "not_compilable", "%s/%s" % (e.get("stage"), e.get("code"))
    return "unknown", "%s %s" % (st, (r.get("compile_error") or r.get("stderr") or "")[:100])


def write_project(files, dst):
    for rel, text in files.items():
        p = os.path.join(dst, rel)
        if not os.path.isdir(os.path.dirname(p)):
            os.makedirs(os.path.dirname(p))
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)


def classify_item(it, work):
    path = os.path.join(work, "%s_%s" % (it["id"], it["pid"]))
    write_project(it["files"], path)
    truth, tdetail = truth_of(path, it["pid"], work, it["files"])
    runs = {}
    for comp, backend in CONFIGS:
        r = G.grade_one(path, it["pid"], comp, backend, [], work, timeout=RUN_TIMEOUT)
        cls, detail = config_class(r)
        runs["%s-%s" % (comp, backend)] = {"class": cls, "detail": detail,
                                           "grader": {k: r[k] for k in ("status", "tests_passed", "tests_total",
                                                                         "first_failure", "exit_code") if k in r}}
    classes = [v["class"] for v in runs.values()]
    worst = min(classes, key=SEVERITY.index)
    return {"id": it["id"], "pid": it["pid"], "operator": it["op"], "intent": it["intent"], "kind": it["kind"],
            "desc": it["desc"], "edit": it["edit"], "truth": truth, "truth_detail": tdetail, "class": worst,
            "runs": runs, "config_diff": len(set(classes)) > 1}


INTENT_TRUTH = {"incorrect": ("incorrect",), "weak": ("contract_weak",), "contract": ("correct",),
                "correct": ("correct",)}


def summarize(results):
    inc = [r for r in results if r["truth"] == "incorrect"]
    s = {"total": len(results), "incorrect": len(inc),
         "correct": sum(r["truth"] == "correct" for r in results),
         "not_compilable": sum(r["truth"] == "not_compilable" for r in results),
         "truth_unknown": sum(r["truth"] == "unknown" for r in results),
         "contract_weak": sum(r["truth"] == "contract_weak" for r in results),
         "contract_weak_ids": [r["id"] for r in results if r["truth"] == "contract_weak"]}
    s["incorrect_by_class"] = {c: sum(r["class"] == c for r in inc) for c in SEVERITY}
    s["rejected_per_class"] = {c: s["incorrect_by_class"][c] for c in (RJ_V, RJ_C)}
    s["incorrect_by_config"] = {}
    for comp, backend in CONFIGS:
        k = "%s-%s" % (comp, backend)
        s["incorrect_by_config"][k] = {c: sum(r["runs"][k]["class"] == c for r in inc) for c in SEVERITY}
    s["all_by_class"] = {c: sum(r["class"] == c for r in results) for c in SEVERITY}
    wbp = [r["id"] for r in results if r["truth"] != "contract_weak" and any(v["class"] == WBP for v in r["runs"].values())]
    s["wrong_but_proved"] = len(wbp)
    s["wrong_but_proved_ids"] = wbp
    s["unresolved_incorrect"] = [{"id": r["id"], "class": r["class"], "detail": [v["detail"] for v in r["runs"].values()
                                                                                   if v["class"] in UNRESOLVED][:1]}
                                 for r in inc if r["class"] in UNRESOLVED]
    s["incorrect_accepted_with_passing_tests"] = [r["id"] for r in inc if r["class"] == ACC]
    s["config_diffs"] = [r["id"] for r in results if r["config_diff"]]
    # G4: intents (author labels) against the independent ground truth
    s["by_intent"] = {}
    for r in results:
        s["by_intent"][r["intent"]] = s["by_intent"].get(r["intent"], 0) + 1
    s["intent_mismatch"] = [{"id": r["id"], "intent": r["intent"], "truth": r["truth"]} for r in results
                            if r["intent"] in INTENT_TRUTH and r["truth"] not in INTENT_TRUTH[r["intent"]]]
    # contract mutants (behaviour unchanged, contract or annotation falsified/weakened) must not be accepted
    s["contract_mutants_accepted"] = [r["id"] for r in results
                                      if r["intent"] == "contract" and any(v["class"] in (ACC, WBP)
                                                                           for v in r["runs"].values())]
    s["contract_mutants_rejected"] = sum(r["intent"] == "contract" and r["class"] in (RJ_V, RJ_C) for r in results)
    # correct mutants the verifier rejected: false rejections (incompleteness), informational only
    s["correct_rejected_ids"] = [r["id"] for r in results
                                 if r["intent"] == "correct" and r["class"] in (RJ_V, RJ_C)]
    ops = {}
    for r in results:
        o = ops.setdefault(r["operator"], {"total": 0, "incorrect": 0, "rejected": 0})
        o["total"] += 1
        o["incorrect"] += r["truth"] == "incorrect"
        o["rejected"] += r["class"] in (RJ_V, RJ_C)
    s["by_operator"] = ops
    try:
        s["versions"] = G2M.versions() if G2M else None
    except Exception as e:                                           # versions are informative only
        s["versions"] = "unavailable: %r" % (e,)
    return s


def fault_injections():
    """Compiler fault injections are NOT executed here: they are tracked as the existing differential / runtime / model
    checks. The names below are recorded as strings only."""
    return {"executed": False,
            "note": "Compiler fault injections (privacy bypass, leaf-name identity collision, dropped entry checks, "
                    "missing cross-module recursive obligations) are not part of the source-mutant classification "
                    "and are not run by this script. The commands name the checks that must catch injected faults "
                    "(the exact flags are not verified here); record their results separately.",
            "cases": [
                {"name": "both compilers x both backends agree on the reference solutions",
                 "command": "python3 bench/g4/run.py bench/g4/solutions"},
                {"name": "no-verify grader run on the incorrect source mutants (runtime detection)",
                 "command": "python3 bench/g4/run.py <mutant dir> --no-verify"},
            ]}


def print_table(results):
    print("%-5s %-4s %-17s %-9s %-14s %-17s %s" % ("id", "pid", "operator", "intent", "truth", "class", "detail"))
    for r in results:
        d = next((v["detail"] for v in r["runs"].values() if v["class"] == r["class"]), "")
        print("%-5s %-4s %-17s %-9s %-14s %-17s %s" % (r["id"], r["pid"], r["operator"], r["intent"], r["truth"],
                                                      r["class"], d[:60]))


def print_summary(s):
    print("\nG4 mutants: total %d, incorrect %d (correct %d, not compilable %d, truth unknown %d, contract-weak %d)"
          % (s["total"], s["incorrect"], s["correct"], s["not_compilable"], s["truth_unknown"], s["contract_weak"]))
    print("%-24s %s" % ("class (incorrect)", "overall | " + " ".join("%-8s" % k for k in s["incorrect_by_config"])))
    for c in SEVERITY:
        print("%-24s %7d | %s" % (c, s["incorrect_by_class"][c],
                                  " ".join("%-8d" % s["incorrect_by_config"][k][c] for k in s["incorrect_by_config"])))
    print("wrong_but_proved mutants: %d %s" % (s["wrong_but_proved"], s["wrong_but_proved_ids"]))
    if s["unresolved_incorrect"]:
        print("unresolved incorrect mutants (not successful rejections): %s" % [u["id"] for u in s["unresolved_incorrect"]])
    if s["incorrect_accepted_with_passing_tests"]:
        print("incorrect mutants accepted with passing tests: %s" % s["incorrect_accepted_with_passing_tests"])
    print("intents: %s; contract mutants rejected %d, accepted %s" % (
        s["by_intent"], s["contract_mutants_rejected"], s["contract_mutants_accepted"]))
    if s["intent_mismatch"]:
        print("intent differs from the ground truth: %s" % s["intent_mismatch"])
    if s["correct_rejected_ids"]:
        print("correct mutants rejected by the verifier (false rejections): %s" % s["correct_rejected_ids"])
    print("operators: " + ", ".join("%s %d/%d" % (k, v["incorrect"], v["total"]) for k, v in sorted(s["by_operator"].items())))


def self_test(items):
    bad = 0
    for it in items:
        msg = G.check_contracts(it["files"]["root.pruv"], it["pid"])
        if msg:
            bad += 1
            print("FAIL %s %s: %s" % (it["id"], it["desc"], msg))
        msg = G.check_structure(it["files"], it["pid"])
        if msg:
            bad += 1
            print("FAIL %s %s: %s" % (it["id"], it["desc"], msg))
    for pid in G.PROBLEMS:
        base = ref_files(pid)
        for msg in (G.check_structure(base, pid), G.check_contracts(base["root.pruv"], pid)):
            if msg:
                bad += 1
                print("FAIL reference %s: %s" % (pid, msg))
        if G.check_constructs(base, pid):
            bad += 1
            print("FAIL reference %s lacks %s" % (pid, G.check_constructs(base, pid)))
        if "\n" not in flatten(base):
            bad += 1
            print("FAIL flatten %s" % pid)
    per = {}
    for it in items:
        per[it["pid"]] = per.get(it["pid"], 0) + 1
    by_intent = {}
    for it in items:
        by_intent[it["intent"]] = by_intent.get(it["intent"], 0) + 1
    print("catalogue: %d mutants (explicit %d, regex %d) %s intents %s" % (
        len(items), sum(i["kind"] == "explicit" for i in items), sum(i["kind"] == "regex" for i in items), per,
        by_intent))
    if len(items) < MIN_MUTANTS:
        bad += 1
        print("FAIL fewer than %d mutants" % MIN_MUTANTS)
    if by_intent.get("incorrect", 0) < MIN_INCORRECT:
        bad += 1
        print("FAIL fewer than %d mutants with intent incorrect" % MIN_INCORRECT)
    # the flattened reference of a problem with CONTRACT_CHECKS must run in the interpreter (contract-weak rule)
    for pid in G.CONTRACT_CHECKS:
        fails = _oracle_contract_failures(ref_files(pid), pid)
        if fails is None or fails:
            bad += 1
            print("FAIL interpreter on the reference %s: %s" % (pid, "cannot run it" if fails is None else fails[:3]))
    print("self-test:", "fail %d" % bad if bad else "all pass")
    sys.exit(1 if bad else 0)


def main():
    args = sys.argv[1:]
    opts = {"--jobs": "4", "--only": "", "--limit": "", "--timeout": ""}
    for o in opts:
        if o in args:
            i = args.index(o)
            if i + 1 >= len(args):
                sys.exit("%s needs a value" % o)
            opts[o] = args[i + 1]
            del args[i:i + 2]
    flags = [a for a in args if a.startswith("--")]
    if any(a not in ("--self-test", "--list") for a in flags):
        sys.exit("usage: mutate_ops.py [OUT.json] [--jobs N] [--only qNN] [--limit N] [--timeout SEC] [--self-test] [--list]")
    if opts["--only"] and opts["--only"] not in G.PROBLEMS:
        sys.exit("--only expects one of %s" % ", ".join(G.PROBLEMS))
    global RUN_TIMEOUT
    if opts["--timeout"]:
        RUN_TIMEOUT = int(opts["--timeout"])
    items = build_catalogue()
    if "--self-test" in flags:
        self_test(items)
    if "--list" in flags:
        for it in items:
            print("%s %s %-17s %-9s %s" % (it["id"], it["pid"], it["op"], it["intent"], it["desc"]))
        sys.exit(0)
    positional = [a for a in args if not a.startswith("--")]
    out = positional[0] if positional else os.path.join(HERE, "results", "mutants.json")
    filtered = bool(opts["--only"] or opts["--limit"])
    if opts["--only"]:
        items = [it for it in items if it["pid"] == opts["--only"]]
    if opts["--limit"]:
        items = items[:int(opts["--limit"])]

    work = tempfile.mkdtemp(prefix="g4m_")
    print("mutants: %d" % len(items), flush=True)

    def run(it):
        try:
            return classify_item(it, work)
        except Exception as e:      # a failure of the harness itself is recorded, never hidden
            err = {"class": CRA, "detail": "harness error: %r" % (e,), "grader": {}}
            return {"id": it["id"], "pid": it["pid"], "operator": it["op"], "intent": it["intent"], "kind": it["kind"],
                    "desc": it["desc"], "edit": it["edit"], "truth": "unknown", "truth_detail": "harness error",
                    "class": CRA, "runs": {"%s-%s" % cb: dict(err) for cb in CONFIGS}, "config_diff": False}

    try:
        with ThreadPoolExecutor(max(1, int(opts["--jobs"]))) as ex:
            results = list(ex.map(run, items))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    summary = summarize(results)
    od = os.path.dirname(os.path.abspath(out))
    if not os.path.isdir(od):
        os.makedirs(od)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "fault_injections": fault_injections(), "items": results}, fh, indent=1,
                  ensure_ascii=False)
    print_table(results)
    print_summary(summary)
    print("wrote %s" % out)
    fail = (summary["wrong_but_proved"] or summary["unresolved_incorrect"]
            or summary["incorrect_accepted_with_passing_tests"] or summary["contract_mutants_accepted"]
            or (not filtered and (summary["total"] < MIN_MUTANTS or summary["incorrect"] < MIN_INCORRECT)))
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
