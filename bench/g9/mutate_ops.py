# -*- coding: utf-8 -*-
"""G9 (recursion, recursive types, buffer fields) mutation test.

  python bench/g9/mutate_ops.py [OUT.json] [--jobs N] [--only qNN] [--limit N] [--timeout SEC]
  python bench/g9/mutate_ops.py --self-test      (catalogue checks only, no compiler)
  python bench/g9/mutate_ops.py --list

Mutants are derived from bench/g9/solutions/ref/q01..q04.pruv: explicit (problem, find, replace, operator) edits plus a
seeded sample of generic regex operators. The fixed wrapper contract lines (WRAPPER_CONTRACTS of run.py) are never
mutated; helper contracts, `decreases` clauses and all bodies are. Operators (docs/G9_SPEC.md 15.1): deleted_progress,
wrong_phase, missing_base, wrong_return, swapped_children, bad_bounds, false_ensures, lost_isolation, wrong_arm,
stale_field (and rx_* for the generic regex operators).

Ground truth ("independent classification"): the mutant is graded with --no-verify (rs compiler, rust backend) by
bench/g9/run.py. `incorrect` = the grader result is wrong (a crash or a non-terminating run also counts);
`correct` = tests pass; `not_compilable` = rejected even without verification; `unknown` = build failure.
`contract_weak` = wrong results that still satisfy every stated wrapper ensures on all test inputs (only problems whose
contracts do not state the full meaning, run.py CONTRACT_CHECKS: q03), that change no signature/contract line, and whose
every function contract (helpers included) the independent interpreter bench/fuzz/oracle.py finds satisfied on all test
inputs (weak_eligible). A mutant that breaks a helper contract is incorrect. Such a mutant is not a source-contract mutant (SPEC 15.1); it is reported
separately and a verified one is not counted as wrong_but_proved.

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
unsupported/unexecuted) or is accepted with passing tests, or when (without --only/--limit) fewer than 100 mutants or
fewer than 80 incorrect mutants exist.
"""
import importlib.util
import json
import os
import random
import re
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REF_DIR = os.path.join(HERE, "solutions", "ref")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load("g9_run", os.path.join(HERE, "run.py"))
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
MIN_MUTANTS, MIN_INCORRECT, GENERIC_CAP = 100, 80, 70

# ------------------------------------------------------------------ explicit catalogue
EXPLICIT = []   # {"pid", "op", "desc", "edits": [(old, new, occ)]}


def E(pid, op, desc, old, new, occ="one"):
    EXPLICIT.append({"pid": pid, "op": op, "desc": desc, "edits": [(old, new, occ)]})


def ME(pid, op, desc, edits):
    EXPLICIT.append({"pid": pid, "op": op, "desc": desc, "edits": [(o, n, "one") for o, n in edits]})


DP, WP, MB, WR, SC, BB, FE, LI, WA, SF = ("deleted_progress", "wrong_phase", "missing_base", "wrong_return",
                                          "swapped_children", "bad_bounds", "false_ensures", "lost_isolation",
                                          "wrong_arm", "stale_field")

# ---- q01: recursive search
S1, S2 = "return search_from(a, q, i + 1);", "return all_below_from(a, t, i + 1);"
E("q01", DP, "search_from does not advance", S1, "return search_from(a, q, i);")
E("q01", DP, "all_below_from does not advance", S2, "return all_below_from(a, t, i);")
E("q01", BB, "search_from steps by two", S1, "return search_from(a, q, i + 2);")
E("q01", BB, "all_below_from steps by two", S2, "return all_below_from(a, t, i + 2);")
E("q01", MB, "search_from loses its base case", "  if i == len(a) { return 0 - 1; }\n", "")
E("q01", MB, "all_below_from loses its base case", "  if i == len(a) { return true; }\n", "")
E("q01", WR, "not found gives 0", "if i == len(a) { return 0 - 1; }", "if i == len(a) { return 0; }")
E("q01", WR, "not found gives len(a)", "if i == len(a) { return 0 - 1; }", "if i == len(a) { return len(a); }")
E("q01", WR, "empty suffix is not below", "return true; }", "return false; }")
E("q01", WR, "found index plus one", "if a[i] == q { return i; }", "if a[i] == q { return i + 1; }")
E("q01", WR, "found gives 0", "if a[i] == q { return i; }", "if a[i] == q { return 0; }")
E("q01", WR, "found gives -1", "if a[i] == q { return i; }", "if a[i] == q { return 0 - 1; }")
E("q01", WA, "match test inverted", "if a[i] == q { return i; }", "if a[i] != q { return i; }")
E("q01", BB, "match test is <=", "if a[i] == q { return i; }", "if a[i] <= q { return i; }")
E("q01", BB, "all_below uses >", "if a[i] >= t { return false; }", "if a[i] > t { return false; }")
E("q01", BB, "all_below uses <=", "if a[i] >= t { return false; }", "if a[i] <= t { return false; }")
E("q01", WA, "violation answers true", "if a[i] >= t { return false; }", "if a[i] >= t { return true; }")
E("q01", BB, "find_first starts at 1", "return search_from(a, q, 0);", "return search_from(a, q, 1);")
E("q01", BB, "all_below starts at 1", "return all_below_from(a, t, 0);", "return all_below_from(a, t, 1);")
E("q01", SC, "search_from arguments swapped (wrapper)", "return search_from(a, q, 0);", "return search_from(a, 0, q);")
E("q01", SC, "search_from arguments swapped (recursion)", S1, "return search_from(a, i + 1, q);")
E("q01", SC, "all_below_from arguments swapped", S2, "return all_below_from(a, i + 1, t);")
E("q01", WR, "find_first off by one", "return search_from(a, q, 0);", "return search_from(a, q, 0) + 1;")
E("q01", WR, "all_below negated", "return all_below_from(a, t, 0);", "return !all_below_from(a, t, 0);")
E("q01", FE, "helper bound ensures false at result == i",
  "ensures result == 0 - 1 || (i <= result && result < len(a))",
  "ensures result == 0 - 1 || (i < result && result < len(a))")
E("q01", FE, "helper bound ensures too tight at the end",
  "ensures result == 0 - 1 || (i <= result && result < len(a))",
  "ensures result == 0 - 1 || (i <= result && result < len(a) - 1)")
E("q01", FE, "helper ensures says a[result] != q", "ensures result >= 0 ==> a[result] == q && (forall k in 0..result: a[k] != q)",
  "ensures result >= 0 ==> a[result] != q && (forall k in 0..result: a[k] != q)", occ=0)
E("q01", FE, "helper ensures range includes result", "ensures result >= 0 ==> a[result] == q && (forall k in 0..result: a[k] != q)",
  "ensures result >= 0 ==> a[result] == q && (forall k in 0..result + 1: a[k] != q)", occ=0)
E("q01", FE, "helper not-found ensures claims presence", "ensures result < 0 ==> (forall k in 0..len(a): a[k] != q)",
  "ensures result < 0 ==> (forall k in 0..len(a): a[k] == q)", occ=0)
E("q01", FE, "all_below_from ensures with <=", "ensures result == (forall k in i..len(a): a[k] < t)",
  "ensures result == (forall k in i..len(a): a[k] <= t)")
E("q01", FE, "all_below_from ensures skips element i", "ensures result == (forall k in i..len(a): a[k] < t)",
  "ensures result == (forall k in i + 1..len(a): a[k] < t)")
E("q01", BB, "invariant covers one element too many", "requires forall k in 0..i: a[k] != q",
  "requires forall k in 0..i + 1: a[k] != q")
E("q01", BB, "helper requires excludes i == len", "requires 0 <= i && i <= len(a)", "requires 0 <= i && i < len(a)", occ=0)
E("q01", WP, "measure does not shrink (search_from)", "decreases len(a) - i", "decreases len(a)", occ=0)
E("q01", WP, "measure grows (all_below_from)", "decreases len(a) - i", "decreases i", occ=1)

# ---- q02: tree build and walk
BLD = "Tree::Node(a[mid], build(a, lo, mid), build(a, mid + 1, hi))"
E("q02", DP, "right subtree not smaller", "build(a, mid + 1, hi)", "build(a, mid, hi)")
E("q02", DP, "left subtree is the whole range", "build(a, lo, mid)", "build(a, lo, hi)")
E("q02", BB, "left range one too long", "build(a, lo, mid)", "build(a, lo, mid + 1)")
E("q02", BB, "right range starts at mid + 2", "build(a, mid + 1, hi)", "build(a, mid + 2, hi)")
E("q02", MB, "build loses its base case", "  if lo == hi { return Tree::Empty; }\n", "")
E("q02", BB, "base case at one element", "if lo == hi {", "if lo + 1 == hi {")
E("q02", WR, "base case builds a node", "{ return Tree::Empty; }", "{ return Tree::Node(a[lo], Tree::Empty, Tree::Empty); }")
E("q02", BB, "mid is hi", "let mid: i64 = lo + (hi - lo) / 2;", "let mid: i64 = hi;")
E("q02", BB, "mid rounds up", "let mid: i64 = lo + (hi - lo) / 2;", "let mid: i64 = lo + (hi - lo) / 2 + 1;")
E("q02", BB, "mid is hi - lo + lo", "let mid: i64 = lo + (hi - lo) / 2;", "let mid: i64 = lo + (hi - lo);")
E("q02", SC, "children swapped (still counts the same)", BLD, "Tree::Node(a[mid], build(a, mid + 1, hi), build(a, lo, mid))")
E("q02", WA, "nodes: Empty counts 1", "Tree::Empty => { return 0; }", "Tree::Empty => { return 1; }")
E("q02", WA, "nodes: node does not count itself", "return 1 + nodes(l) + nodes(r);", "return nodes(l) + nodes(r);")
E("q02", SC, "nodes: only left subtree", "return 1 + nodes(l) + nodes(r);", "return 1 + nodes(l);")
E("q02", SC, "nodes: only right subtree", "return 1 + nodes(l) + nodes(r);", "return 1 + nodes(r);")
E("q02", WA, "nodes: node counts 2", "return 1 + nodes(l) + nodes(r);", "return 2 + nodes(l) + nodes(r);")
E("q02", SC, "nodes: left counted twice", "return 1 + nodes(l) + nodes(r);", "return 1 + nodes(l) + nodes(l);")
E("q02", SC, "nodes: right counted twice", "return 1 + nodes(l) + nodes(r);", "return 1 + nodes(r) + nodes(r);")
E("q02", WA, "empties: Empty counts 0", "Tree::Empty => { return 1; }", "Tree::Empty => { return 0; }")
E("q02", WA, "empties: node counts 1", "return empties(l) + empties(r);", "return 1 + empties(l) + empties(r);")
E("q02", SC, "empties: only left subtree", "return empties(l) + empties(r);", "return empties(l);")
E("q02", SC, "empties: only right subtree", "return empties(l) + empties(r);", "return empties(r);")
E("q02", SC, "empties: left counted twice", "return empties(l) + empties(r);", "return empties(l) + empties(l);")
E("q02", WA, "empties: product", "return empties(l) + empties(r);", "return empties(l) * empties(r);")
E("q02", WR, "node_count plus one", "return nodes(t);", "return nodes(t) + 1;")
E("q02", WR, "empty_count minus one", "return empties(t);", "return empties(t) - 1;")
E("q02", WR, "empty_count returns the node count", "return empties(t);", "return nodes(t);")
E("q02", WR, "node_count returns the empty count", "return nodes(t);", "return empties(t);")
E("q02", BB, "node_count tree skips element 0", "let t: Tree = build(a, 0, len(a));", "let t: Tree = build(a, 1, len(a));", occ=0)
E("q02", BB, "empty_count tree skips element 0", "let t: Tree = build(a, 0, len(a));", "let t: Tree = build(a, 1, len(a));", occ=1)
E("q02", BB, "node_count tree skips the last element", "let t: Tree = build(a, 0, len(a));",
  "let t: Tree = build(a, 0, len(a) - 1);", occ=0)
E("q02", BB, "empty_count tree reads past the end", "let t: Tree = build(a, 0, len(a));",
  "let t: Tree = build(a, 0, len(a) + 1);", occ=1)
E("q02", FE, "build size ensures off by one", "ensures size(result) == 2 * (hi - lo) + 1", "ensures size(result) == 2 * (hi - lo) + 2")
E("q02", FE, "nodes ensures drops the +1", "ensures 2 * result + 1 == size(t)", "ensures 2 * result == size(t)")
E("q02", FE, "empties ensures wrong offset", "ensures 2 * result - 1 == size(t)", "ensures 2 * result + 1 == size(t)")
E("q02", BB, "size bound too small for 1000 elements", "requires size(t) <= 2001", "requires size(t) <= 2000", occ=0)
E("q02", BB, "build requires lo < hi", "requires 0 <= lo && lo <= hi && hi <= len(a) && len(a) <= 1000",
  "requires 0 <= lo && lo < hi && hi <= len(a) && len(a) <= 1000")
E("q02", WP, "build measure is len(a)", "decreases hi - lo", "decreases len(a)")
E("q02", WP, "nodes measure does not shrink", "decreases size(t)", "decreases 0", occ=0)
E("q02", WP, "empties measure grows", "decreases size(t)", "decreases 0 - size(t)", occ=1)

# ---- q03: mutual descent
E("q03", DP, "items_end does not advance past the value", "return items_end(a, k);", "return items_end(a, j);")
E("q03", DP, "value_end does not skip the open token", "return items_end(a, i + 1);", "return items_end(a, i);")
E("q03", BB, "items_end starts two past the open token", "return items_end(a, i + 1);", "return items_end(a, i + 2);")
E("q03", BB, "items_end resumes one past the value", "return items_end(a, k);", "return items_end(a, k + 1);")
E("q03", SF, "inner value read one position late", "let k: i64 = value_end(a, j);", "let k: i64 = value_end(a, j + 1);")
E("q03", MB, "value_end loses its end-of-input case", "  if i == len(a) { return 0 - 1; }\n", "")
E("q03", MB, "items_end loses its end-of-input case", "  if j == len(a) { return 0 - 1; }\n", "")
E("q03", MB, "items_end loses its close case", "  if a[j] == 2 { return j + 1; }\n", "")
E("q03", MB, "value_end loses its atom case", "  if a[i] == 0 { return i + 1; }\n", "")
E("q03", MB, "value_end loses its invalid-token case", "  if a[i] != 1 { return 0 - 1; }\n", "")
E("q03", WR, "end of input gives 0", "if i == len(a) { return 0 - 1; }", "if i == len(a) { return 0; }")
E("q03", WR, "unclosed list gives len(a)", "if j == len(a) { return 0 - 1; }", "if j == len(a) { return len(a); }")
E("q03", WR, "atom ends at its own position", "if a[i] == 0 { return i + 1; }", "if a[i] == 0 { return i; }")
E("q03", WR, "atom ends two later", "if a[i] == 0 { return i + 1; }", "if a[i] == 0 { return i + 2; }")
E("q03", WR, "close ends at its own position", "if a[j] == 2 { return j + 1; }", "if a[j] == 2 { return j; }")
E("q03", WR, "close ends two later", "if a[j] == 2 { return j + 1; }", "if a[j] == 2 { return j + 2; }")
E("q03", WR, "invalid token gives i", "if a[i] != 1 { return 0 - 1; }", "if a[i] != 1 { return i; }")
E("q03", WR, "inner failure gives 0", "if k < 0 { return 0 - 1; }", "if k < 0 { return 0; }")
E("q03", WR, "inner failure gives -2", "if k < 0 { return 0 - 1; }", "if k < 0 { return k - 1; }")
E("q03", BB, "inner failure test too wide", "if k < 0 {", "if k < 3 {")
E("q03", BB, "atom test is <= 0", "if a[i] == 0 {", "if a[i] <= 0 {")
E("q03", BB, "open test is > 1 inverted", "if a[i] != 1 {", "if a[i] > 1 {")
E("q03", BB, "close test is >= 2", "if a[j] == 2 {", "if a[j] >= 2 {")
E("q03", BB, "end-of-input test one early (value_end)", "if i == len(a) {", "if i + 1 == len(a) {")
E("q03", BB, "end-of-input test one early (items_end)", "if j == len(a) {", "if j + 1 == len(a) {")
E("q03", WA, "close test looks for an open token", "if a[j] == 2 {", "if a[j] == 1 {")
E("q03", WA, "atom test looks for a close token", "if a[i] == 0 {", "if a[i] == 2 {")
E("q03", WA, "open test looks for a close token", "if a[i] != 1 {", "if a[i] != 2 {")
ME("q03", SC, "close test after the value call",
   [("  if a[j] == 2 { return j + 1; }\n  let k: i64 = value_end(a, j);\n  if k < 0 { return 0 - 1; }",
     "  let k: i64 = value_end(a, j);\n  if k < 0 { return 0 - 1; }\n  if a[j] == 2 { return j + 1; }")])
E("q03", WR, "is_value accepts any value prefix", "return value_end(a, 0) == len(a);", "return value_end(a, 0) >= 0;")
E("q03", SF, "is_value starts at 1", "return value_end(a, 0) == len(a);", "return value_end(a, 1) == len(a);")
E("q03", WR, "is_value negated", "return value_end(a, 0) == len(a);", "return value_end(a, 0) != len(a);")
E("q03", BB, "is_value uses <=", "return value_end(a, 0) == len(a);", "return value_end(a, 0) <= len(a);")
E("q03", BB, "is_value off by one", "return value_end(a, 0) == len(a);", "return value_end(a, 0) + 1 == len(a);")
E("q03", BB, "is_value compares to len(a) - 1", "return value_end(a, 0) == len(a);", "return value_end(a, 0) == len(a) - 1;")
E("q03", WP, "value_end measure loses its phase", "decreases 2 * (len(a) - i) + 1", "decreases 2 * (len(a) - i)")
E("q03", WP, "items_end measure phase too low", "decreases 2 * (len(a) - j) + 2", "decreases 2 * (len(a) - j) + 1")
E("q03", WP, "items_end measure phase far too low", "decreases 2 * (len(a) - j) + 2", "decreases 2 * (len(a) - j)")
E("q03", WP, "items_end measure ignores the position", "decreases 2 * (len(a) - j) + 2", "decreases len(a) + 2")
E("q03", WP, "value_end measure is constant", "decreases 2 * (len(a) - i) + 1", "decreases len(a)")
E("q03", FE, "items_end bound ensures false at j + 1", "ensures result == 0 - 1 || (j < result && result <= len(a))",
  "ensures result == 0 - 1 || (j + 1 < result && result <= len(a))")
E("q03", FE, "items_end bound ensures too tight", "ensures result == 0 - 1 || (j < result && result <= len(a))",
  "ensures result == 0 - 1 || (j < result && result < len(a))")
E("q03", BB, "items_end requires excludes j == len", "requires 0 <= j && j <= len(a) && len(a) <= 1000",
  "requires 0 <= j && j < len(a) && len(a) <= 1000")

# ---- q04: nested buffer copies
RET4 = "return p.left.data[0] + q.left.data[0];"
E("q04", LI, "result reads only the changed copy", RET4, "return q.left.data[0] + q.left.data[0];")
E("q04", LI, "result reads only the original", RET4, "return p.left.data[0] + p.left.data[0];")
E("q04", SF, "result mixes the unchanged right copy", RET4, "return p.left.data[0] + q.right.data[0];")
E("q04", WR, "result subtracts", RET4, "return p.left.data[0] - q.left.data[0];")
E("q04", WR, "result multiplies", RET4, "return p.left.data[0] * q.left.data[0];")
E("q04", WR, "result plus one", RET4, "return p.left.data[0] + q.left.data[0] + 1;")
E("q04", WR, "result minus d", RET4, "return p.left.data[0] + q.left.data[0] - d;")
E("q04", WR, "bump subtracts", "w[0] = w[0] + d;", "w[0] = w[0] - d;")
E("q04", WR, "bump overwrites", "w[0] = w[0] + d;", "w[0] = d;")
E("q04", WR, "bump is lost", "w[0] = w[0] + d;", "w[0] = w[0];")
E("q04", WR, "bump twice", "w[0] = w[0] + d;", "w[0] = w[0] + d + d;")
E("q04", WR, "bump by one", "w[0] = w[0] + d;", "w[0] = w[0] + 1;")
E("q04", BB, "bump element 1", "w[0] = w[0] + d;", "w[1] = w[1] + d;")
E("q04", SF, "write back to the right buffer", "q.left = Buf { data: copy(w) };", "q.right = Buf { data: copy(w) };")
E("q04", WR, "write back the original instead of the change", "q.left = Buf { data: copy(w) };", "q.left = Buf { data: copy(a) };")
E("q04", SF, "write back the right buffer", "q.left = Buf { data: copy(w) };", "q.left = Buf { data: copy(q.right.data) };")
E("q04", LI, "assert on q instead of p", "assert p.left.data[0] == a[0];", "assert q.left.data[0] == a[0];")
E("q04", LI, "assert compares changed copy with right copy", "assert q.right.data[0] == a[0];",
  "assert q.left.data[0] == a[0];")
E("q04", SF, "stale fact: right copy also changed", "assert q.right.data[0] == a[0];", "assert q.right.data[0] == a[0] + d;")
E("q04", SF, "stale fact: original equals changed copy", "assert q.right.data[0] == a[0];",
  "assert p.left.data[0] == q.left.data[0];")
ME("q04", LI, "assign to p instead of q (p made mutable)",
   [("let p: Pair = Pair { left: Buf { data: copy(a) }, right: Buf { data: copy(a) } };",
     "let mut p: Pair = Pair { left: Buf { data: copy(a) }, right: Buf { data: copy(a) } };"),
    ("q.left = Buf { data: copy(w) };", "p.left = Buf { data: copy(w) };")])
E("q04", WR, "swap does not move the right buffer", "q.left = q.right;", "q.left = q.left;")
E("q04", WR, "swap loses the saved left buffer", "q.right = t;", "q.right = q.right;")
E("q04", WR, "swap duplicates the left buffer", "q.right = t;", "q.right = q.left;")
E("q04", WR, "saved buffer is the right one", "let t: Buf = q.left;", "let t: Buf = q.right;")
E("q04", WR, "lengths in the wrong order", "return 1000 * len(q.left.data) + len(q.right.data);",
  "return len(q.left.data) + 1000 * len(q.right.data);")
E("q04", LI, "result reads the original left length", "return 1000 * len(q.left.data) + len(q.right.data);",
  "return 1000 * len(p.left.data) + len(q.right.data);")
E("q04", SF, "result reads the original right length", "return 1000 * len(q.left.data) + len(q.right.data);",
  "return 1000 * len(q.left.data) + len(p.right.data);")
E("q04", WR, "left length used twice", "return 1000 * len(q.left.data) + len(q.right.data);",
  "return 1000 * len(q.left.data) + len(q.left.data);")
E("q04", WR, "factor 1001", "return 1000 * len(q.left.data) + len(q.right.data);",
  "return 1001 * len(q.left.data) + len(q.right.data);")
E("q04", WR, "lengths subtracted", "return 1000 * len(q.left.data) + len(q.right.data);",
  "return 1000 * len(q.left.data) - len(q.right.data);")
E("q04", WR, "result plus one", "return 1000 * len(q.left.data) + len(q.right.data);",
  "return 1000 * len(q.left.data) + len(q.right.data) + 1;")
E("q04", WR, "unswapped result", "return 1000 * len(q.left.data) + len(q.right.data);",
  "return 1000 * len(q.right.data) + len(q.left.data);")
E("q04", WR, "only the left length", "return 1000 * len(q.left.data) + len(q.right.data);",
  "return 1000 * len(q.left.data);")
E("q04", WR, "only the right length", "return 1000 * len(q.left.data) + len(q.right.data);",
  "return len(q.right.data);")
E("q04", SF, "right buffer built from a", "right: Buf { data: copy(b) }", "right: Buf { data: copy(a) }")
E("q04", SF, "left buffer built from b", "left: Buf { data: copy(a) }, right: Buf { data: copy(b) }",
  "left: Buf { data: copy(b) }, right: Buf { data: copy(b) }")
E("q04", LI, "assert after the swap reads q", "assert len(p.left.data) == len(a);", "assert len(q.left.data) == len(a);")
E("q04", SF, "assert compares with the wrong array", "assert len(p.left.data) == len(a);", "assert len(p.left.data) == len(b);")


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


def ref_text(pid):
    with open(os.path.join(REF_DIR, pid + ".pruv"), encoding="utf-8") as f:
        return f.read()


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


def protected_lines(text, pid):
    """0-based line numbers of the wrapper headers (signature, requires, ensures) that must never be mutated."""
    prot = set()
    for name in G.WRAPPER_CONTRACTS[pid]:
        m = re.search(r"\bfn\s+%s\s*\(" % re.escape(name), text)
        if not m:
            continue
        end = text.find("{", m.start())
        first, last = text.count("\n", 0, m.start()), text.count("\n", 0, end)
        lines = text.split("\n")
        for i in range(first, last + 1):
            if not lines[i].strip().startswith("decreases"):
                prot.add(i)
    return prot


def generic_candidates(pid):
    text = ref_text(pid)
    lines = text.split("\n")
    prot = protected_lines(text, pid)
    out = []
    for op, pat, rep in REGEX_OPS:
        rx = re.compile(pat)
        for i, line in enumerate(lines):
            if i in prot or not line.strip() or line.strip().startswith("//"):
                continue
            for m in rx.finditer(line):
                new_line = line[:m.start()] + rep + line[m.end():]
                new_text = "\n".join(lines[:i] + [new_line] + lines[i + 1:])
                out.append({"pid": pid, "op": op, "text": new_text,
                            "desc": "line %d: `%s` -> `%s`" % (i + 1, m.group(0), rep),
                            "edit": {"line": i + 1, "from": line.strip(), "to": new_line.strip()}})
    return out


def build_catalogue():
    """List of mutants {"id","pid","op","desc","text","edit"}; identical-to-original and duplicate texts are skipped."""
    items, seen = [], {}
    for pid in G.PROBLEMS:
        seen[pid] = {ref_text(pid)}

    def add(it):
        if it["text"] in seen[it["pid"]]:
            return False
        seen[it["pid"]].add(it["text"])
        it["id"] = "m%03d" % (len(items) + 1)
        items.append(it)
        return True

    for e in EXPLICIT:
        text = ref_text(e["pid"])
        for old, new, occ in e["edits"]:
            text = apply_edit(text, old, new, occ)
        add({"pid": e["pid"], "op": e["op"], "desc": e["desc"], "text": text, "kind": "explicit",
             "edit": [{"from": o, "to": n} for o, n, _ in e["edits"]]})
    cands = []
    for pid in G.PROBLEMS:
        cands += generic_candidates(pid)
    fresh = [c for c in cands if c["text"] not in seen[c["pid"]]]
    random.Random(9).shuffle(fresh)
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


import threading
_ORACLE_LOCK = threading.Lock()


def _oracle_contract_failures(text, pid):
    """Contract failures (requires/ensures/invariant/assert/decreases of every function, helpers included) the
    independent reference interpreter bench/fuzz/oracle.py records over all test inputs of pid, or None when the
    interpreter cannot run the program."""
    O = _load("fuzz_oracle", os.path.join(ROOT, "bench", "fuzz", "oracle.py"))
    out, box = set(), {}

    def go():
        try:
            prog = O.parse_program(text)
            for fn, args, _exp in G.tests()[pid]:
                r = O.run(prog, fn, [v for _k, v in args])
                out.update(r["contract_failures"])
                if r["kind"] != "ok":
                    out.add("fault %s in %s" % (r["kind"], fn))
            box["ok"] = True
        except (O.OracleUnsupported, RecursionError, ValueError):
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


def weak_eligible(text, pid):
    """(eligible, why). A wrong mutant is contract_weak only when no signature/contract line changed and the independent
    interpreter finds every stated contract of every function (helpers included) satisfied on all test inputs. A
    mutant that breaks a helper contract is a source-contract mutant the verifier must reject."""
    import difflib
    orig = ref_text(pid).split("\n")
    changed = set()
    for tag, i1, i2, _j1, _j2 in difflib.SequenceMatcher(None, orig, text.split("\n"), autojunk=False).get_opcodes():
        if tag != "equal":
            changed.update(range(i1, max(i2, i1 + 1)))
    src = "\n".join(orig)
    for m in re.finditer(r"^\s*fn\s+\w+\s*\(", src, re.M):
        first, blin = src.count("\n", 0, m.start()), src.count("\n", 0, src.find("{", m.start()))
        if any(first <= i <= blin for i in changed):
            return False, "edits a signature or contract line"
    fails = _oracle_contract_failures(text, pid)
    if fails is None:
        return False, "reference interpreter cannot run it"
    if fails:
        return False, "breaks %s" % ", ".join(fails[:3])
    return True, ""


def truth_of(path, pid, work, text=None):
    """Independent ground truth from the grader under --no-verify (rs compiler, rust backend)."""
    r = G.grade_one(path, pid, "rs", "rust", ["--no-verify"], work, timeout=RUN_TIMEOUT)
    st = r.get("status")
    if st == "wrong":
        if pid in G.CONTRACT_CHECKS and not r.get("exit_code") and text is not None:
            # the stated contracts do not fix the results (PROBLEMS.md q03): a mutant whose every result still
            # satisfies the stated ensures is contract-weak, not a source-contract mutant the verifier must reject
            c = G.grade_one(path, pid, "rs", "rust", ["--no-verify"], work, timeout=RUN_TIMEOUT, contracts=True)
            if c.get("status") == "ok":
                ok, why = weak_eligible(text, pid)
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


def classify_item(it, work):
    path = os.path.join(work, "%s_%s.pruv" % (it["id"], it["pid"]))
    with open(path, "w", encoding="utf-8") as f:
        f.write(it["text"])
    truth, tdetail = truth_of(path, it["pid"], work, it["text"])
    runs = {}
    for comp, backend in CONFIGS:
        r = G.grade_one(path, it["pid"], comp, backend, [], work, timeout=RUN_TIMEOUT)
        cls, detail = config_class(r)
        runs["%s-%s" % (comp, backend)] = {"class": cls, "detail": detail,
                                           "grader": {k: r[k] for k in ("status", "tests_passed", "tests_total",
                                                                         "first_failure", "exit_code") if k in r}}
    classes = [v["class"] for v in runs.values()]
    worst = min(classes, key=SEVERITY.index)
    return {"id": it["id"], "pid": it["pid"], "operator": it["op"], "kind": it["kind"], "desc": it["desc"],
            "edit": it["edit"], "truth": truth, "truth_detail": tdetail, "class": worst, "runs": runs,
            "config_diff": len(set(classes)) > 1}


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
            "note": "Compiler fault injections are not part of the source-mutant classification and are not run by "
                    "this script. The commands name the existing differential checks that must catch injected "
                    "faults (the exact flags are not verified here); record their results separately.",
            "cases": [
                {"name": "both compilers x both backends agree on the reference solutions",
                 "command": "python3 bench/g9/run.py bench/g9/solutions/ref"},
                {"name": "G9 fuzz differential (seeds 41, 56, 57)", "command": "python3 bench/fuzz/run.py --g9"},
                {"name": "G9 generated-program oracle", "command": "python3 bench/fuzz/oracle.py (--g9 mode)"},
                {"name": "mutation test of the shared bench harness", "command": "python3 bench/mutate.py"},
                {"name": "no-verify grader run on the incorrect source mutants (runtime detection)",
                 "command": "python3 bench/g9/run.py <mutant dir> --no-verify"},
            ]}


def print_table(results):
    print("%-5s %-4s %-17s %-14s %-17s %s" % ("id", "pid", "operator", "truth", "class", "detail"))
    for r in results:
        d = next((v["detail"] for v in r["runs"].values() if v["class"] == r["class"]), "")
        print("%-5s %-4s %-17s %-14s %-17s %s" % (r["id"], r["pid"], r["operator"], r["truth"], r["class"], d[:60]))


def print_summary(s):
    print("\nG9 mutants: total %d, incorrect %d (correct %d, not compilable %d, truth unknown %d, contract-weak %d)"
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
    print("operators: " + ", ".join("%s %d/%d" % (k, v["incorrect"], v["total"]) for k, v in sorted(s["by_operator"].items())))


def self_test(items):
    bad = 0
    for it in items:
        msg = G.check_contracts(it["text"], it["pid"])
        if msg:
            bad += 1
            print("FAIL %s %s: %s" % (it["id"], it["desc"], msg))
    for pid in G.PROBLEMS:
        if G.check_contracts(ref_text(pid), pid):
            bad += 1
            print("FAIL reference %s: %s" % (pid, G.check_contracts(ref_text(pid), pid)))
        if G.check_constructs(ref_text(pid), pid):
            bad += 1
            print("FAIL reference %s lacks %s" % (pid, G.check_constructs(ref_text(pid), pid)))
    per = {}
    for it in items:
        per[it["pid"]] = per.get(it["pid"], 0) + 1
    print("catalogue: %d mutants (explicit %d, regex %d) %s" % (
        len(items), sum(i["kind"] == "explicit" for i in items), sum(i["kind"] == "regex" for i in items), per))
    if len(items) < MIN_MUTANTS:
        bad += 1
        print("FAIL fewer than %d mutants" % MIN_MUTANTS)
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
            print("%s %s %-17s %s" % (it["id"], it["pid"], it["op"], it["desc"]))
        sys.exit(0)
    positional = [a for a in args if not a.startswith("--")]
    out = positional[0] if positional else os.path.join(HERE, "results", "mutants.json")
    filtered = bool(opts["--only"] or opts["--limit"])
    if opts["--only"]:
        items = [it for it in items if it["pid"] == opts["--only"]]
    if opts["--limit"]:
        items = items[:int(opts["--limit"])]

    work = tempfile.mkdtemp(prefix="g9m_")
    print("mutants: %d" % len(items), flush=True)

    def run(it):
        try:
            return classify_item(it, work)
        except Exception as e:      # a failure of the harness itself is recorded, never hidden
            err = {"class": CRA, "detail": "harness error: %r" % (e,), "grader": {}}
            return {"id": it["id"], "pid": it["pid"], "operator": it["op"], "kind": it["kind"], "desc": it["desc"],
                    "edit": it["edit"], "truth": "unknown", "truth_detail": "harness error", "class": CRA,
                    "runs": {"%s-%s" % cb: dict(err) for cb in CONFIGS}, "config_diff": False}

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
            or summary["incorrect_accepted_with_passing_tests"]
            or (not filtered and (summary["total"] < MIN_MUTANTS or summary["incorrect"] < MIN_INCORRECT)))
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
