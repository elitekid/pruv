# -*- coding: utf-8 -*-
"""G5 (inout parameters) source-mutation test.

  python bench/g5/mutate_ops.py [OUT.json] [--jobs N] [--only qNN] [--limit N] [--timeout SEC]
  python bench/g5/mutate_ops.py --self-test      (catalogue checks only, no compiler)
  python bench/g5/mutate_ops.py --list

Mutants are derived from the reference projects bench/g5/solutions/q01 (one file) and q02 (root.pruv + xform.pruv):
explicit edits (problem, file, find, replace, operator, intent) plus a seeded sample of generic regex operators over all
files. The fixed root entry lines (ENTRY_CONTRACTS of run.py) are never mutated; helper contracts, loop invariants,
`decreases` clauses and all bodies are. G5-specific operators (behaviourally incorrect unless the intent says otherwise):
wrong_index (a store/read/argument index is off), missing_store (a store or the copy of the input is dropped),
wrong_frame (the code writes outside the promised range, or a frame clause is wrong), old_current (a value is read from
the current contents where the entry contents old(a) are meant, or the other way round), omitted_call (an inout helper
call is dropped), reordered (operations or arguments in another order), wrong_callee (another helper is called),
wrong_value (the stored value is wrong). rx_* are the generic regex operators.

Ground truth ("independent classification"): the mutant project is graded with --no-verify (rs compiler, rust backend)
by bench/g5/run.py. `incorrect` = the grader result is wrong (a crash, a panic or a non-terminating run also counts);
`correct` = tests pass; `not_compilable` = rejected even without verification; `unknown` = build failure. The G5
contracts are exact (content and frame), so there is no contract-weak truth class: every wrong result violates a stated
ensures.

`intent` is the label the author gave a mutant: incorrect (results differ from the reference), contract (behaviour
unchanged, a contract or annotation was falsified or weakened so that the modular proof must fail), correct (behaviour
and contracts equivalent; a sound verifier may accept it, a rejection is a false rejection and only reported), weak
(behaviour unchanged, a contract or annotation was weakened where the verifier may legitimately still accept: redundant
invariant conjuncts, facts that are built in; reported separately, an accepted or a rejected one is no failure), auto
(generic regex mutant, no intent). Intents that disagree with the ground truth are listed as intent_mismatch.

Per mutant and per configuration (py/rs x rust/llvm) the verifier verdict plus the grader result give one class (same as
bench/g4/mutate_ops.py):
  rejected_verify, rejected_checker, accepted_correct, wrong_but_proved, unknown, timeout, crash, unsupported,
  unexecuted.
The mutant's overall class is the worst configuration (order: wrong_but_proved, crash, timeout, unsupported, unknown,
unexecuted, accepted_correct, rejected_checker, rejected_verify).
Exit code 1 when wrong_but_proved > 0, when an incorrect mutant has an unresolved class or is accepted with passing
tests, when a `contract` mutant is accepted on any configuration, or when (without --only/--limit) fewer than 50 mutants
or fewer than 40 incorrect mutants exist.
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
REF_DIR = os.path.join(HERE, "solutions")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load("g5_run", os.path.join(HERE, "run.py"))
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
MIN_MUTANTS, MIN_INCORRECT, GENERIC_CAP = 50, 40, 20

# ------------------------------------------------------------------ explicit catalogue
EXPLICIT = []   # {"pid", "op", "intent", "desc", "edits": [(file, old, new, occ)]}

R, X = "root.pruv", "xform.pruv"

WI, MS, WF, OC, OM, RO = "wrong_index", "missing_store", "wrong_frame", "old_current", "omitted_call", "reordered"
WC, WV, EQ = "wrong_callee", "wrong_value", "equivalent"
# the six fault kinds the catalogue must cover with incorrect mutants (G5_SPEC section 14 item 4)
REQUIRED_KINDS = (WI, MS, WF, OC, OM, RO)
INC, WEAK, CON, COR = "incorrect", "weak", "contract", "correct"


def E(pid, op, intent, desc, file, old, new, occ="one"):
    EXPLICIT.append({"pid": pid, "op": op, "intent": intent, "desc": desc, "edits": [(file, old, new, occ)]})


def ME(pid, op, intent, desc, edits):
    EXPLICIT.append({"pid": pid, "op": op, "intent": intent, "desc": desc,
                     "edits": [(e[0], e[1], e[2], e[3] if len(e) > 3 else "one") for e in edits]})


FRAME = "ensures forall k in 0..len(b): k != i ==> b[k] == old(b)[k]"     # set_byte (0), bump_sat (1), bump_wrap (2)
OUT_FRAME = "ensures forall k in 0..len(b): (k < lo || k >= hi) ==> b[k] == old(b)[k]"   # fill (0), sat (1), wrap (2)

# ---- q01: bounded byte-range transformation (root.pruv only)
# wrong indices
E("q01", WI, INC, "set_byte stores at i + 1", R, "  b[i] = v;", "  b[i + 1] = v;")
E("q01", WI, INC, "set_byte stores at 0", R, "  b[i] = v;", "  b[0] = v;")
E("q01", WI, INC, "bump_sat reads element 0", R, "let x: i64 = b[i] + c;", "let x: i64 = b[0] + c;")
E("q01", WI, INC, "bump_wrap reads element 0", R, "let x: i64 = (b[i] + c) % 256;", "let x: i64 = (b[0] + c) % 256;")
E("q01", WI, INC, "bump_sat saturated store at i - 1", R, "    b[i] = 255;", "    b[i - 1] = 255;")
E("q01", WI, INC, "add_range_sat starts at lo + 1", R, "let mut i: i64 = lo;", "let mut i: i64 = lo + 1;", 1)
E("q01", WI, INC, "fill_range starts at lo + 1", R, "let mut i: i64 = lo;", "let mut i: i64 = lo + 1;", 0)
E("q01", WI, INC, "add_range_wrap starts at lo - 1", R, "let mut i: i64 = lo;", "let mut i: i64 = lo - 1;", 2)
E("q01", WI, INC, "fill_range stores at i + 1", R, "set_byte(inout b, i, v);", "set_byte(inout b, i + 1, v);")
E("q01", WI, INC, "add_range_sat bumps hi - 1 every time", R, "bump_sat(inout b, i, c);",
  "bump_sat(inout b, hi - 1, c);")
E("q01", WI, INC, "add_range_wrap bumps lo every time", R, "bump_wrap(inout b, i, c);", "bump_wrap(inout b, lo, c);")
E("q01", WI, INC, "add_sat forwards hi - 1", R, "add_range_sat(inout w, lo, hi, c);",
  "add_range_sat(inout w, lo, hi - 1, c);")
E("q01", WI, INC, "add_wrap forwards lo + 1", R, "add_range_wrap(inout w, lo, hi, c);",
  "add_range_wrap(inout w, lo + 1, hi, c);")
# missing stores
E("q01", MS, INC, "set_byte lost its store", R, "  b[i] = v;\n", "")
E("q01", MS, INC, "bump_sat: no store when not saturating", R, "  } else {\n    b[i] = x;\n  }", "  }")
E("q01", MS, INC, "bump_sat: the saturated store is a no-op", R, "    b[i] = 255;", "    b[i] = b[i];")
E("q01", MS, INC, "bump_wrap lost its store", R, "% 256;\n  b[i] = x;", "% 256;")
E("q01", MS, INC, "add_sat returns a fresh copy of a instead of the updated one", R, "  return w;",
  "  return copy(a);", 0)
E("q01", MS, INC, "add_wrap returns a fresh copy of a instead of the updated one", R, "  return w;",
  "  return copy(a);", 1)
E("q01", MS, INC, "fill_bytes returns a fresh copy of a instead of the updated one", R, "  return w;",
  "  return copy(a);", 2)
E("q01", MS, INC, "add_sat works on zeros instead of a copy of a", R, "let mut w: [u8] = copy(a);",
  "let mut w: [u8] = alloc(len(a), 0);", 0)
E("q01", MS, INC, "add_wrap works on zeros instead of a copy of a", R, "let mut w: [u8] = copy(a);",
  "let mut w: [u8] = alloc(len(a), 0);", 1)
E("q01", MS, INC, "fill_bytes works on zeros instead of a copy of a", R, "let mut w: [u8] = copy(a);",
  "let mut w: [u8] = alloc(len(a), 0);", 2)
# omitted calls
E("q01", OM, INC, "add_range_sat does not call bump_sat", R, "    bump_sat(inout b, i, c);\n", "")
E("q01", OM, INC, "add_range_wrap does not call bump_wrap", R, "    bump_wrap(inout b, i, c);\n", "")
E("q01", OM, INC, "fill_range does not call set_byte", R, "    set_byte(inout b, i, v);\n", "")
E("q01", OM, INC, "add_sat does not call add_range_sat", R, "  add_range_sat(inout w, lo, hi, c);\n", "")
E("q01", OM, INC, "add_wrap does not call add_range_wrap", R, "  add_range_wrap(inout w, lo, hi, c);\n", "")
E("q01", OM, INC, "fill_bytes does not call fill_range", R, "  fill_range(inout w, lo, hi, v);\n", "")
# reordered operations
E("q01", RO, INC, "add_range_sat: index incremented before the bump", R,
  "    bump_sat(inout b, i, c);\n    i = i + 1;", "    i = i + 1;\n    bump_sat(inout b, i, c);")
E("q01", RO, INC, "add_range_wrap: index incremented before the bump", R,
  "    bump_wrap(inout b, i, c);\n    i = i + 1;", "    i = i + 1;\n    bump_wrap(inout b, i, c);")
E("q01", RO, INC, "fill_range: index incremented before the store", R,
  "    set_byte(inout b, i, v);\n    i = i + 1;", "    i = i + 1;\n    set_byte(inout b, i, v);")
E("q01", RO, INC, "fill_bytes: range arguments swapped", R, "fill_range(inout w, lo, hi, v);",
  "fill_range(inout w, hi, lo, v);")
E("q01", RO, INC, "add_sat: constant and range swapped", R, "add_range_sat(inout w, lo, hi, c);",
  "add_range_sat(inout w, c, hi, lo);")
# wrong callee
E("q01", WC, INC, "add_sat calls the wrapping loop", R, "add_range_sat(inout w, lo, hi, c);",
  "add_range_wrap(inout w, lo, hi, c);")
E("q01", WC, INC, "add_wrap calls the saturating loop", R, "add_range_wrap(inout w, lo, hi, c);",
  "add_range_sat(inout w, lo, hi, c);")
E("q01", WC, INC, "add_range_sat bumps with the wrapping helper", R, "bump_sat(inout b, i, c);",
  "bump_wrap(inout b, i, c);")
# wrong frame (code writes outside the promised range)
E("q01", WF, INC, "fill_range also writes element hi", R, "while i < hi", "while i <= hi", 0)
E("q01", WF, INC, "add_range_sat also bumps element hi", R, "while i < hi", "while i <= hi", 1)
E("q01", WF, INC, "add_range_wrap also bumps element hi", R, "while i < hi", "while i < hi + 1", 2)
E("q01", WF, INC, "set_byte also clobbers element 0", R, "  b[i] = v;", "  b[i] = v;\n  b[0] = v;")
E("q01", WF, INC, "bump_wrap also clobbers element 0", R, "% 256;\n  b[i] = x;", "% 256;\n  b[i] = x;\n  b[0] = 0;")
E("q01", WF, INC, "add_sat clears element 0 after the update", R,
  "  add_range_sat(inout w, lo, hi, c);\n  return w;", "  add_range_sat(inout w, lo, hi, c);\n  w[0] = 0;\n  return w;")
# old/current confusion
E("q01", OC, INC, "bump_wrap applies the update twice (second one reads the current value)", R,
  "  let x: i64 = (b[i] + c) % 256;\n  b[i] = x;",
  "  b[i] = (b[i] + c) % 256;\n  b[i] = (b[i] + c) % 256;")
E("q01", OC, INC, "add_range_sat bumps every element twice", R,
  "    bump_sat(inout b, i, c);\n    i = i + 1;", "    bump_sat(inout b, i, c);\n    bump_sat(inout b, i, c);\n    i = i + 1;")
# wrong values
E("q01", WV, INC, "bump_sat saturates at 254", R, "    b[i] = 255;", "    b[i] = 254;")
E("q01", WV, INC, "bump_sat saturation test lets 256 through", R, "if x > 255 {", "if x > 256 {")
E("q01", WV, INC, "bump_wrap reduces modulo 255", R, "(b[i] + c) % 256;", "(b[i] + c) % 255;")
E("q01", WV, INC, "bump_wrap adds one too much", R, "let x: i64 = (b[i] + c) % 256;",
  "let x: i64 = (b[i] + c + 1) % 256;")
E("q01", WV, INC, "bump_sat adds one too much", R, "let x: i64 = b[i] + c;", "let x: i64 = b[i] + c + 1;")
E("q01", WV, INC, "set_byte stores the complement", R, "  b[i] = v;", "  b[i] = 255 - v;")
# contract mutants: behaviour unchanged, a contract or annotation is falsified/weakened (the proof must fail)
E("q01", WF, CON, "set_byte: frame clause only below i (callers rely on the rest)", R, FRAME,
  "ensures forall k in 0..len(b): k < i ==> b[k] == old(b)[k]", 0)
E("q01", WF, CON, "bump_sat: frame clause dropped", R, "  " + FRAME + "\n", "", 1)
E("q01", WF, CON, "bump_wrap: frame clause dropped", R, "  " + FRAME + "\n", "", 2)
E("q01", OC, CON, "set_byte: frame clause compares with the current contents (trivial)", R, FRAME,
  "ensures forall k in 0..len(b): k != i ==> b[k] == b[k]", 0)
E("q01", OC, CON, "bump_sat: ensures compares with the current element (false for c > 0)", R,
  "old(b)[i] + c <= 255 ==> b[i] == old(b)[i] + c", "old(b)[i] + c <= 255 ==> b[i] == b[i] + c")
E("q01", WF, CON, "add_range_sat: out-of-range frame clause only below lo", R, OUT_FRAME,
  "ensures forall k in 0..len(b): k < lo ==> b[k] == old(b)[k]", 1)
E("q01", WF, CON, "add_range_sat: untouched-element invariant dropped", R,
  "    invariant forall k in 0..n: (k < lo || k >= i) ==> b[k] == old(b)[k]\n", "", 1)
E("q01", OC, CON, "add_range_wrap: content invariant uses the current element instead of old", R,
  "(lo <= k && k < i) ==> b[k] == (old(b)[k] + c) % 256", "(lo <= k && k < i) ==> b[k] == (b[k] + c) % 256")
E("q01", WF, CON, "add_range_sat: decreases does not shrink", R, "decreases hi - i", "decreases hi", 1)
E("q01", WF, CON, "bump_sat: requires strengthened beyond what callers establish", R,
  "requires 0 <= i && i < len(b) && 0 <= c && c <= 255\n  ensures len(b) == len(old(b))\n"
  "  ensures old(b)[i] + c <= 255",
  "requires 0 <= i && i < len(b) && 0 <= c && c <= 100\n  ensures len(b) == len(old(b))\n"
  "  ensures old(b)[i] + c <= 255")
# correct mutants (behaviour and contracts equivalent; a sound verifier may accept)
E("q01", EQ, COR, "bump_sat: saturation test with >= (stores 255 either way)", R, "if x > 255 {", "if x >= 255 {")
E("q01", EQ, COR, "bump_wrap: commuted addition", R, "let x: i64 = (b[i] + c) % 256;",
  "let x: i64 = (c + b[i]) % 256;")
E("q01", EQ, COR, "set_byte: built-in length fact dropped from its ensures", R,
  "  ensures len(b) == len(old(b))\n  ensures b[i] == v", "  ensures b[i] == v")
E("q01", EQ, COR, "bump_sat: requires weakened (c <= 255 is not needed by the body or the callers)", R,
  "requires 0 <= i && i < len(b) && 0 <= c && c <= 255\n  ensures len(b) == len(old(b))\n"
  "  ensures old(b)[i] + c <= 255",
  "requires 0 <= i && i < len(b) && 0 <= c\n  ensures len(b) == len(old(b))\n"
  "  ensures old(b)[i] + c <= 255")
# weak-contract mutants (reported separately; accepted or rejected is no failure)
E("q01", WF, WEAK, "fill_range: invariant loses hi <= n", R,
  "invariant len(b) == n && n == len(old(b)) && hi <= n", "invariant len(b) == n && n == len(old(b))", 0)
E("q01", WF, WEAK, "add_range_sat: invariant loses the built-in n == len(old(b))", R,
  "invariant len(b) == n && n == len(old(b)) && hi <= n", "invariant len(b) == n && hi <= n", 1)
E("q01", WF, WEAK, "add_range_wrap: invariant loses len(b) == n", R,
  "invariant len(b) == n && n == len(old(b)) && hi <= n", "invariant n == len(old(b)) && hi <= n", 2)

# ---- q02: module-based recursive array transformation (root.pruv + xform.pruv)
# xform.pruv: swap_at
E("q02", WV, INC, "swap_at stores y twice", X, "  a[j] = x;", "  a[j] = y;")
E("q02", MS, INC, "swap_at lost the store to j", X, "  a[j] = x;\n", "")
E("q02", MS, INC, "swap_at lost the store to i", X, "  a[i] = y;\n", "")
E("q02", OC, INC, "swap_at reads the already overwritten element", X, "  a[j] = x;", "  a[j] = a[i];")
# xform.pruv: rev_range
E("q02", WI, INC, "rev_range recurses on lo + 1 .. hi", X, "rev_range(inout a, lo + 1, hi - 1);",
  "rev_range(inout a, lo + 1, hi);")
E("q02", WI, INC, "rev_range recurses on lo .. hi - 1", X, "rev_range(inout a, lo + 1, hi - 1);",
  "rev_range(inout a, lo, hi - 1);")
E("q02", WI, INC, "rev_range swaps lo with hi - 1", X, "swap_at(inout a, lo, hi);", "swap_at(inout a, lo, hi - 1);")
E("q02", WI, INC, "rev_range swaps lo with lo + 1", X, "swap_at(inout a, lo, hi);", "swap_at(inout a, lo, lo + 1);")
E("q02", WI, INC, "rev_range stops one level early (needs two elements apart)", X, "if lo < hi {", "if lo + 1 < hi {")
E("q02", WI, INC, "rev_range recurses once more at the middle element", X, "if lo < hi {", "if lo <= hi {")
E("q02", OM, INC, "rev_range does not recurse", X, "    rev_range(inout a, lo + 1, hi - 1);\n", "")
E("q02", OM, INC, "rev_range does not swap", X, "    swap_at(inout a, lo, hi);\n", "")
E("q02", RO, INC, "rev_range: swap arguments exchanged for the recursion order (hi first)", X,
  "swap_at(inout a, lo, hi);\n    rev_range(inout a, lo + 1, hi - 1);",
  "swap_at(inout a, hi, lo);\n    rev_range(inout a, hi - 1, lo + 1);")
# xform.pruv: add_from
E("q02", WV, INC, "add_from subtracts d", X, "a[i] = a[i] + d;", "a[i] = a[i] - d;")
E("q02", WV, INC, "add_from stores d", X, "a[i] = a[i] + d;", "a[i] = d;")
E("q02", WV, INC, "add_from adds one too much", X, "a[i] = a[i] + d;", "a[i] = a[i] + d + 1;")
E("q02", MS, INC, "add_from lost its store", X, "    a[i] = a[i] + d;\n", "")
E("q02", OM, INC, "add_from does not recurse", X, "    add_from(inout a, i + 1, d);\n", "")
E("q02", WI, INC, "add_from skips every other element", X, "add_from(inout a, i + 1, d);", "add_from(inout a, i + 2, d);")
E("q02", WI, INC, "add_from leaves out the last element", X, "if i < len(a) {", "if i + 1 < len(a) {")
E("q02", WI, INC, "add_from updates a[i + 1]", X, "a[i] = a[i] + d;", "a[i + 1] = a[i + 1] + d;")
E("q02", WF, INC, "add_from also updates element 0", X, "    a[i] = a[i] + d;",
  "    a[i] = a[i] + d;\n    a[0] = a[0] + d;")
E("q02", OC, INC, "add_from adds the current value of the next element", X, "a[i] = a[i] + d;",
  "a[i] = a[i] + d + a[len(a) - 1];")
# root.pruv
E("q02", WI, INC, "reverse_window forwards hi - 1", R, "crate::xform::rev_range(inout w, lo, hi);",
  "crate::xform::rev_range(inout w, lo, hi - 1);")
E("q02", WI, INC, "reverse_window forwards lo + 1", R, "crate::xform::rev_range(inout w, lo, hi);",
  "crate::xform::rev_range(inout w, lo + 1, hi);")
E("q02", RO, INC, "reverse_window forwards hi and lo swapped", R, "crate::xform::rev_range(inout w, lo, hi);",
  "crate::xform::rev_range(inout w, hi, lo);")
E("q02", WI, INC, "reverse_all forwards n - 2", R, "crate::xform::rev_range(inout w, 0, n - 1);",
  "crate::xform::rev_range(inout w, 0, n - 2);")
E("q02", WI, INC, "reverse_all starts at 1", R, "crate::xform::rev_range(inout w, 0, n - 1);",
  "crate::xform::rev_range(inout w, 1, n - 1);")
E("q02", WI, INC, "shift_tail starts at i + 1", R, "crate::xform::add_from(inout w, i, d);",
  "crate::xform::add_from(inout w, i + 1, d);")
E("q02", WI, INC, "shift_tail starts at 0", R, "crate::xform::add_from(inout w, i, d);",
  "crate::xform::add_from(inout w, 0, d);")
E("q02", WV, INC, "shift_tail forwards d + 1", R, "crate::xform::add_from(inout w, i, d);",
  "crate::xform::add_from(inout w, i, d + 1);")
E("q02", WV, INC, "shift_tail forwards 0 - d", R, "crate::xform::add_from(inout w, i, d);",
  "crate::xform::add_from(inout w, i, 0 - d);")
E("q02", OM, INC, "reverse_window does not call rev_range", R, "  crate::xform::rev_range(inout w, lo, hi);\n", "")
E("q02", OM, INC, "reverse_all does not call rev_range", R, "  crate::xform::rev_range(inout w, 0, n - 1);\n", "")
E("q02", OM, INC, "shift_tail does not call add_from", R, "  crate::xform::add_from(inout w, i, d);\n", "")
E("q02", MS, INC, "reverse_window returns a fresh copy of a", R, "  return w;", "  return copy(a);", 0)
E("q02", MS, INC, "reverse_all returns a fresh copy of a", R, "  return w;", "  return copy(a);", 1)
E("q02", MS, INC, "shift_tail returns a fresh copy of a", R, "  return w;", "  return copy(a);", 2)
E("q02", MS, INC, "reverse_window works on zeros instead of a copy of a", R, "let mut w: [i64] = copy(a);",
  "let mut w: [i64] = alloc(len(a), 0);", 0)
E("q02", MS, INC, "reverse_all works on zeros instead of a copy of a", R, "let mut w: [i64] = copy(a);",
  "let mut w: [i64] = alloc(len(a), 0);", 1)
E("q02", MS, INC, "shift_tail works on zeros instead of a copy of a", R, "let mut w: [i64] = copy(a);",
  "let mut w: [i64] = alloc(len(a), 0);", 2)
E("q02", WF, INC, "reverse_all clobbers element 0 after the reversal", R,
  "  crate::xform::rev_range(inout w, 0, n - 1);\n  return w;",
  "  crate::xform::rev_range(inout w, 0, n - 1);\n  w[0] = 0;\n  return w;")
# contract mutants
E("q02", WF, CON, "rev_range: frame clause only below lo", X, "ensures forall k in 0..len(a): (k < lo || k > hi) ==> a[k] == old(a)[k]",
  "ensures forall k in 0..len(a): k < lo ==> a[k] == old(a)[k]")
E("q02", OC, CON, "rev_range: content clause compares with the current contents", X,
  "a[k] == old(a)[lo + hi - k]", "a[k] == a[lo + hi - k]")
E("q02", OC, CON, "swap_at: ensures compares a[j] with the current a[i]", X, "ensures a[j] == old(a)[i]",
  "ensures a[j] == a[i]")
E("q02", WF, CON, "swap_at: frame clause dropped", X,
  "  ensures forall k in 0..len(a): k != i && k != j ==> a[k] == old(a)[k]\n", "")
E("q02", WF, CON, "add_from: requires bound dropped (overflow no longer provable)", X,
  "  requires forall k in i..len(a): -1000000 <= a[k] && a[k] <= 1000000\n", "")
E("q02", WF, CON, "add_from: decreases does not shrink", X, "decreases len(a) - i", "decreases len(a)")
E("q02", WF, CON, "add_from: ensures only strictly after i (host relies on k >= i)", X,
  "k >= i ==> a[k] == old(a)[k] + d", "k > i ==> a[k] == old(a)[k] + d")
E("q02", WF, CON, "rev_range: requires loses the empty window (lo == hi + 1)", X,
  "requires 0 <= lo && lo <= hi + 1 && hi < len(a)", "requires 0 <= lo && lo <= hi && hi < len(a)")
# correct mutants
ME("q02", RO, COR, "rev_range: recursion before the swap (disjoint positions, same result)",
   [(X, "    swap_at(inout a, lo, hi);\n    rev_range(inout a, lo + 1, hi - 1);",
     "    rev_range(inout a, lo + 1, hi - 1);\n    swap_at(inout a, lo, hi);")])
ME("q02", RO, COR, "add_from: recursion before the store (disjoint positions, same result)",
   [(X, "    a[i] = a[i] + d;\n    add_from(inout a, i + 1, d);",
     "    add_from(inout a, i + 1, d);\n    a[i] = a[i] + d;")])
E("q02", EQ, COR, "rev_range: another valid measure (decreases by two)", X, "decreases hi - lo + 1",
  "decreases hi - lo + 2")
E("q02", EQ, COR, "swap_at: independent reads in the other order", X,
  "  let x: i64 = a[i];\n  let y: i64 = a[j];", "  let y: i64 = a[j];\n  let x: i64 = a[i];")
E("q02", EQ, COR, "add_from: built-in length fact dropped from its ensures", X,
  "  ensures len(a) == len(old(a))\n  ensures forall k in 0..len(a): k >= i", "  ensures forall k in 0..len(a): k >= i")
# weak-contract mutant
E("q02", WF, WEAK, "add_from: element bound in requires loosened (body and host still satisfy it)", X,
  "requires forall k in i..len(a): -1000000 <= a[k] && a[k] <= 1000000",
  "requires forall k in i..len(a): -2000000 <= a[k] && a[k] <= 2000000")


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
    random.Random(5).shuffle(fresh)
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


def truth_of(path, pid, work, files=None):
    """Independent ground truth from the grader under --no-verify (rs compiler, rust backend); path is the project
    directory. The G5 contracts are exact, so a wrong result is always `incorrect` (no contract-weak class)."""
    r = G.grade_one(path, pid, "rs", "rust", ["--no-verify"], work, timeout=RUN_TIMEOUT)
    st = r.get("status")
    if st == "wrong":
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


# weak: behaviour unchanged, so the no-verify truth is `correct` as well
INTENT_TRUTH = {"incorrect": ("incorrect",), "weak": ("correct",), "contract": ("correct",), "correct": ("correct",)}


def summarize(results):
    inc = [r for r in results if r["truth"] == "incorrect"]
    s = {"total": len(results), "incorrect": len(inc),
         "correct": sum(r["truth"] == "correct" for r in results),
         "not_compilable": sum(r["truth"] == "not_compilable" for r in results),
         "truth_unknown": sum(r["truth"] == "unknown" for r in results)}
    s["incorrect_by_class"] = {c: sum(r["class"] == c for r in inc) for c in SEVERITY}
    s["rejected_per_class"] = {c: s["incorrect_by_class"][c] for c in (RJ_V, RJ_C)}
    s["incorrect_by_config"] = {}
    for comp, backend in CONFIGS:
        k = "%s-%s" % (comp, backend)
        s["incorrect_by_config"][k] = {c: sum(r["runs"][k]["class"] == c for r in inc) for c in SEVERITY}
    s["all_by_class"] = {c: sum(r["class"] == c for r in results) for c in SEVERITY}
    wbp = [r["id"] for r in results if any(v["class"] == WBP for v in r["runs"].values())]
    s["wrong_but_proved"] = len(wbp)
    s["wrong_but_proved_ids"] = wbp
    s["unresolved_incorrect"] = [{"id": r["id"], "class": r["class"], "detail": [v["detail"] for v in r["runs"].values()
                                                                                   if v["class"] in UNRESOLVED][:1]}
                                 for r in inc if r["class"] in UNRESOLVED]
    s["incorrect_accepted_with_passing_tests"] = [r["id"] for r in inc if r["class"] == ACC]
    s["config_diffs"] = [r["id"] for r in results if r["config_diff"]]
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
    # weak-contract mutants are recorded separately (accepted or rejected is informational)
    weak = [r for r in results if r["intent"] == "weak"]
    s["weak_contract"] = {"total": len(weak), "rejected_ids": [r["id"] for r in weak if r["class"] in (RJ_V, RJ_C)],
                          "accepted_ids": [r["id"] for r in weak if r["class"] == ACC]}
    # correct mutants the verifier rejected: false rejections (incompleteness), informational only
    s["correct_rejected_ids"] = [r["id"] for r in results
                                 if r["intent"] == "correct" and r["class"] in (RJ_V, RJ_C)]
    s["correct_accepted_ids"] = [r["id"] for r in results if r["intent"] == "correct" and r["class"] == ACC]
    ops = {}
    for r in results:
        o = ops.setdefault(r["operator"], {"total": 0, "incorrect": 0, "rejected": 0})
        o["total"] += 1
        o["incorrect"] += r["truth"] == "incorrect"
        o["rejected"] += r["class"] in (RJ_V, RJ_C)
    s["by_operator"] = ops
    s["incorrect_by_fault_kind"] = {k: sum(r["truth"] == "incorrect" and r["operator"] == k for r in results)
                                    for k in REQUIRED_KINDS}
    try:
        s["versions"] = G2M.versions() if G2M else None
    except Exception as e:                                           # versions are informative only
        s["versions"] = "unavailable: %r" % (e,)
    return s


def fault_injections():
    """Compiler fault injections are NOT executed here: they are separate checks recorded with patch identity,
    command and detecting test (G5_SPEC section 14 item 5)."""
    return {"executed": False,
            "note": "Compiler fault injections (disabled exclusivity, old bound to current contents, omitted call "
                    "havoc, omitted loop call-write collection, stale return-parameter overlay, readonly retained on "
                    "a mutable LLVM parameter) are not part of the source-mutant classification and are not run by "
                    "this script. Record their results separately.",
            "cases": [
                {"name": "both compilers x both backends agree on the reference solutions",
                 "command": "python3 bench/g5/run.py bench/g5/solutions"},
                {"name": "no-verify grader run on the incorrect source mutants (runtime detection)",
                 "command": "python3 bench/g5/run.py <mutant dir> --no-verify"},
            ]}


def print_table(results):
    print("%-5s %-4s %-17s %-9s %-14s %-17s %s" % ("id", "pid", "operator", "intent", "truth", "class", "detail"))
    for r in results:
        d = next((v["detail"] for v in r["runs"].values() if v["class"] == r["class"]), "")
        print("%-5s %-4s %-17s %-9s %-14s %-17s %s" % (r["id"], r["pid"], r["operator"], r["intent"], r["truth"],
                                                      r["class"], d[:60]))


def print_summary(s):
    print("\nG5 mutants: total %d, incorrect %d (correct %d, not compilable %d, truth unknown %d)"
          % (s["total"], s["incorrect"], s["correct"], s["not_compilable"], s["truth_unknown"]))
    print("%-24s %s" % ("class (incorrect)", "overall | " + " ".join("%-8s" % k for k in s["incorrect_by_config"])))
    for c in SEVERITY:
        print("%-24s %7d | %s" % (c, s["incorrect_by_class"][c],
                                  " ".join("%-8d" % s["incorrect_by_config"][k][c] for k in s["incorrect_by_config"])))
    print("wrong_but_proved mutants: %d %s" % (s["wrong_but_proved"], s["wrong_but_proved_ids"]))
    if s["unresolved_incorrect"]:
        print("unresolved incorrect mutants (not successful rejections): %s" % [u["id"] for u in s["unresolved_incorrect"]])
    if s["incorrect_accepted_with_passing_tests"]:
        print("incorrect mutants accepted with passing tests: %s" % s["incorrect_accepted_with_passing_tests"])
    print("incorrect by fault kind: %s" % s["incorrect_by_fault_kind"])
    print("intents: %s; contract mutants rejected %d, accepted %s" % (
        s["by_intent"], s["contract_mutants_rejected"], s["contract_mutants_accepted"]))
    print("weak-contract mutants: %s" % s["weak_contract"])
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
    per, by_intent, kinds = {}, {}, {k: 0 for k in REQUIRED_KINDS}
    for it in items:
        per[it["pid"]] = per.get(it["pid"], 0) + 1
        by_intent[it["intent"]] = by_intent.get(it["intent"], 0) + 1
        if it["intent"] == INC and it["op"] in kinds:
            kinds[it["op"]] += 1
    print("catalogue: %d mutants (explicit %d, regex %d) %s intents %s" % (
        len(items), sum(i["kind"] == "explicit" for i in items), sum(i["kind"] == "regex" for i in items), per,
        by_intent))
    print("incorrect by fault kind: %s" % kinds)
    if len(items) < MIN_MUTANTS:
        bad += 1
        print("FAIL fewer than %d mutants" % MIN_MUTANTS)
    if by_intent.get("incorrect", 0) < MIN_INCORRECT:
        bad += 1
        print("FAIL fewer than %d mutants with intent incorrect" % MIN_INCORRECT)
    for k, n in kinds.items():
        if n == 0:
            bad += 1
            print("FAIL no incorrect mutant of kind %s" % k)
    for intent in ("correct", "weak", "contract"):
        if not by_intent.get(intent):
            bad += 1
            print("FAIL no mutant with intent %s" % intent)
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

    work = tempfile.mkdtemp(prefix="g5m_")
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
