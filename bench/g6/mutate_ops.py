# -*- coding: utf-8 -*-
"""G6 (Rust calls, standard collections) mutation test.

  python bench/g6/mutate_ops.py [OUT.json] [--jobs N] [--only SUBSTR] [--kind pruv|foreign|ownership]
  python bench/g6/mutate_ops.py --self-test      (anchors/liar files/counts only, no compiler)
  python bench/g6/mutate_ops.py --list

Mutants are derived from bench/g6/solutions/ref/q01..q04.pruv (and the adapter crate of q04). Three kinds:
  pruv       30+ incorrect Pruv computations: off-by-one, wrong operator, wrong key, dropped push, swapped arguments,
             wrong constants/returns. Expected: the prover rejects them (the reference contracts are exact).
  foreign    20+ incorrect foreign results/contracts of q04: the trusted contract text is mutated (weakened, strengthened,
             clauses dropped, impossible, domain-unsafe) or the correct contract is kept and the adapter crate is replaced by
             a lying variant bench/g6/adapter/g6q_liar*.rs.
  ownership  10+ ownership/representation faults: removed `move`, use after move, borrowed value moved, `take` on the wrong
             parameter, alias without move, loop that does not restore its owner, bad foreign signatures. Expected: rejected
             at compile time by the checker (parse/type stage), not by the prover.

Classification of every mutant (the verifier verdict is one input; the ground truth comes from running the tests):
  rejected_by_prover     both compilers reject with a verify-stage error (counterexample / unprovable obligation)
  rejected_by_checker    both compilers reject in the parse/type/effect stage (syntax, types, ownership, foreign signature)
  caught_at_runtime_all  accepted by the prover; with `--foreign-checks all` the generated program reports a foreign
                         contract violation or panic (`pruv: foreign ...`) that the tests did not see in default mode,
                         or the foreign panic is already seen in the default mode (detected_in says which)
  wrong_but_verified     accepted by the prover (and the checker) but the tests fail in default mode: a wrong program
                         that verifies (for pruv/ownership kinds this is a finding; exit code 1)
  undetectable_trust     accepted, and the lie is not observable by the tests nor by `--foreign-checks all`
                         (effect lies; wrong results the contract does not constrain): a trust limitation
  equivalent             accepted and indistinguishable on the tests in all modes (a harmless or redundant change)
Accepted mutants run on every accepting compiler and both backends (rust, llvm); each configuration is classified
separately (`runs`) and the worst one decides (crash > wrong_but_verified > undetectable_trust >
caught_at_runtime_all > equivalent).
Anomalies: crash (compiler crash/timeout, a rustc failure on accepted code, or a test-run timeout), undecided
(verify_unknown only). py_rs_diff is reported separately (the compilers disagree in verdict, or configurations
disagree in class).
Exit code 1 if a pruv/ownership mutant is wrong_but_verified, a crash was seen, or fewer than 60 mutants exist.
"""
import glob
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REF_DIR = os.path.join(HERE, "solutions", "ref")
ADAPTER_DIR = os.path.join(HERE, "adapter")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G2M = _load("g2_mutate_ops", os.path.join(ROOT, "bench", "g2", "mutate_ops.py"))   # run_compiler / classify / versions
G = _load("g6_run", os.path.join(HERE, "run.py"))

CLASSES = ["rejected_by_prover", "rejected_by_checker", "caught_at_runtime_all", "wrong_but_verified",
           "undetectable_trust", "equivalent"]
RP, RC, CA, WV, UT, EQ = CLASSES
CHECK_STAGES = ("parse", "type", "effect")
BAD_RUN = ("compile_error", "pruv_error", "missing", "timeout")


# ------------------------------------------------------------------ mutant catalogue
ITEMS = []


def _add(kind, fam, pid, old, new, expect, occ="one", scope=None, liar=None, unobservable=False, desc=""):
    ITEMS.append({"id": "m%02d" % (len(ITEMS) + 1), "kind": kind, "family": fam, "pid": pid, "old": old, "new": new,
                  "occ": occ, "scope": scope, "expect": expect, "liar": liar, "unobservable": unobservable,
                  "desc": desc})


def pm(fam, pid, old, new, occ="one", expect=RP, desc=""):
    _add("pruv", fam, pid, old, new, expect, occ=occ, desc=desc)


def fm(fam, old, new, expect, occ="one", desc=""):
    _add("foreign", fam, "q04", old, new, expect, occ=occ, scope="decl", desc=desc)


def fl(fam, name, expect, unobservable=False, desc=""):
    _add("foreign", fam, "q04", None, None, expect, liar=name, unobservable=unobservable, desc=desc)


def om(fam, pid, old, new, occ="one", expect=RC, desc=""):
    _add("ownership", fam, pid, old, new, expect, occ=occ, desc=desc)


# ---- 1. incorrect Pruv computations (q01 .. q04 client code)
# q01 Vec filter / accumulate
pm("off_by_one", "q01", "if lo <= x && x <= hi {", "if lo < x && x <= hi {", desc="lower bound exclusive")
pm("off_by_one", "q01", "if lo <= x && x <= hi {", "if lo <= x && x < hi {", desc="upper bound exclusive")
pm("wrong_operator", "q01", "if lo <= x && x <= hi {", "if lo <= x || x <= hi {", desc="&& became ||")
pm("dropped_push", "q01", "return vec_push::<i64>(move v, x);", "return move v;", desc="kept element is not pushed")
pm("wrong_branch", "q01", "  return move v;\n}", "  return vec_push::<i64>(move v, x);\n}",
   desc="rejected element is pushed too")
pm("wrong_return", "q01", "return len(v);", "return len(v) + 1;", desc="count is one too large")
pm("wrong_return", "q01", "return len(v);", "return i;", desc="returns the scan position, not the count")
pm("swapped_args", "q01", "v = push_if_in(move v, a[i], lo, hi);", "v = push_if_in(move v, a[i], hi, lo);",
   desc="lo and hi exchanged")
pm("off_by_one", "q01", "v = push_if_in(move v, a[i], lo, hi);", "v = push_if_in(move v, a[i], lo, hi - 1);",
   desc="range shrinks by one (and hi - 1 may overflow)")
pm("wrong_step", "q01", "i = i + 1;", "i = i + 2;", occ=0, desc="count_in_range skips every other element")
pm("wrong_operator", "q01", "s = s + a[i];", "s = s + a[i] + 1;", desc="running sum adds an extra 1")
pm("wrong_value", "q01", "v = vec_push::<i64>(move v, s);", "v = vec_push::<i64>(move v, a[i]);",
   desc="pushes the element instead of the prefix sum")
pm("wrong_index", "q01", "return vec_get::<i64>(v, len(v) - 1);", "return vec_get::<i64>(v, 0);",
   desc="returns the first prefix sum")
pm("off_by_one", "q01", "return vec_get::<i64>(v, len(v) - 1);", "return vec_get::<i64>(v, len(v) - 2);",
   desc="reads the second to last prefix sum")
pm("wrong_constant", "q01", "return 0;", "return 1;", desc="empty input gives 1")
# q02 histogram
pm("dropped_update", "q02", "map_insert::<i64, i64>(move m, x, n + 1);", "map_insert::<i64, i64>(move m, x, n);",
   desc="existing key is not incremented")
pm("wrong_constant", "q02", "map_insert::<i64, i64>(move m, x, 1);", "map_insert::<i64, i64>(move m, x, 0);",
   desc="new key starts at 0")
pm("wrong_key", "q02", "let cur: Option<i64> = map_get::<i64, i64>(m, x);", "let cur: Option<i64> = map_get::<i64, i64>(m, q);",
   desc="count lookup uses the queried value instead of the element")
pm("wrong_key", "q02", "let r: Option<i64> = map_get::<i64, i64>(m, q);", "let r: Option<i64> = map_get::<i64, i64>(m, 0);",
   desc="final lookup of key 0")
pm("wrong_operator", "q02", "if x == q {", "if x != q {", desc="ghost counter counts the other elements")
pm("wrong_step", "q02", "c = c + 1;", "c = c + 2;", desc="ghost counter steps by two")
pm("wrong_return", "q02", "None => { return 0; }", "None => { return 1; }", desc="absent value gives 1")
pm("wrong_key", "q02", "map_insert::<i64, i64>(move m, x, n + 1);", "map_insert::<i64, i64>(move m, q, n + 1);",
   desc="increment is stored under the queried key")
pm("wrong_constant", "q02", "if n < 1000000 {", "if n < 1 {", desc="saturation threshold 1: counts stop at 1")
pm("wrong_operator", "q02", "return n > 0;", "return n > 1;", desc="seen needs two occurrences")
pm("wrong_return", "q02", "Some(n) => { return n; }", "Some(n) => { return n + 1; }", desc="count is one too large")
pm("wrong_constant", "q02", "let mut c: i64 = 0;", "let mut c: i64 = 1;", desc="ghost counter starts at 1")
# q03 String assembly
pm("swapped_args", "q03", "s = string_push_str(move s, a);", "s = string_push_str(move s, b);", occ=0,
   desc="first piece is b")
pm("dropped_push", "q03", "  s = string_push_str(move s, sep);", "  // separator push dropped", occ=0,
   desc="join_pair without separator")
pm("swapped_args", "q03", "s = string_push_str(move s, b);", "s = string_push_str(move s, a);", occ=0,
   desc="second piece is a")
pm("wrong_order", "q03", "  s = string_push_str(move s, sep);\n  s = string_push_str(move s, b);\n  return string_to_str(s);",
   "  s = string_push_str(move s, b);\n  s = string_push_str(move s, sep);\n  return string_to_str(s);",
   desc="b before the separator")
pm("wrong_return", "q03", "return len(s);", "return len(s) + 1;", desc="length one too large")
pm("dropped_push", "q03", "  s = string_push_str(move s, sep);\n  s = string_push_str(move s, c);",
   "  s = string_push_str(move s, c);", desc="second separator dropped")
pm("wrong_value", "q03", "s = string_push_str(move s, c);", "s = string_push_str(move s, b);",
   desc="c replaced by b in joined_len3")
pm("wrong_result", "q03", "return string_to_str(s);", "let e: String = string_new();\n  return string_to_str(e);",
   desc="returns the empty string")
# q04 client code
pm("off_by_one", "q04", "if v >= 0 {", "if v > 0 {", desc="the digit 0 is treated as a failure")
pm("wrong_operator", "q04", "return x + y;", "return x - y;", desc="add_digits subtracts")
pm("wrong_operator", "q04", "return v >= 0;", "return v > 0;", desc="is_digit false for 0")
pm("wrong_return", "q04", "return d;", "return v;", desc="digit_or returns the failure code instead of d")
pm("wrong_operator", "q04", "if x >= 0 {", "if x >= 0 || y >= 0 {", desc="add_digits accepts a single digit")
pm("wrong_constant", "q04", "return -1;", "return 0;", desc="add_digits failure value 0")

# ---- 2. incorrect foreign results / contracts (q04): contract text mutations, correct adapter
fm("drop_clause", "  ensures result >= -1 && result <= 9", "  // range clause dropped", EQ,
   desc="range clause is implied by the other two: redundant")
fm("drop_clause", "  ensures (len(s) == 1 && 48 <= s[0] && s[0] <= 57) ==> result == s[0] - 48",
   "  // value clause dropped", RP, desc="the digit value is no longer known")
fm("drop_clause", "  ensures !(len(s) == 1 && 48 <= s[0] && s[0] <= 57) ==> result == -1",
   "  // failure clause dropped", RP, desc="failure is no longer known to be -1")
fm("weaken", "result <= 9", "result <= 10", EQ, desc="weaker range: still true, harmless control")
fm("wrong_value", "result == s[0] - 48", "result == s[0] - 47", RP, desc="off-by-one value clause")
fm("impossible", "==> result == -1", "==> result == -2", CA,
   desc="failure value -2 contradicts the range clause: failure paths become vacuous for the prover")
fm("wrong_bound", "48 <= s[0]", "49 <= s[0]", RP, occ="all", desc="'0' is declared a non-digit")
fm("wrong_length", "len(s) == 1", "len(s) >= 1", RP, occ="all", desc="multi-character prefixes declared digits")
fm("extra_requires", "  ensures result >= -1 && result <= 9",
   "  requires len(s) >= 1\n  ensures result >= -1 && result <= 9", RP,
   desc="a precondition the wrappers cannot establish")
fm("impossible", "result >= -1 && result <= 9", "result >= 0 && result <= 9", CA,
   desc="range 0..=9 contradicts the failure clause: failure paths become vacuous")
fm("domain", "  ensures !(len(s) == 1 && 48 <= s[0] && s[0] <= 57) ==> result == -1",
   "  ensures !(48 <= s[0] && s[0] <= 57) ==> result == -1", RP,
   desc="s[0] read without the length guard: contract_domain")
# ---- ... correct contract, lying adapter crate
fl("liar_value", "g6q_liar_off_by_one", CA, desc="every digit reported one too large")
fl("liar_value", "g6q_liar_two_chars", CA, desc="'12' parses as 1")
fl("liar_range", "g6q_liar_hex", CA, desc="hex digits give 10..15")
fl("liar_range", "g6q_liar_neg2", CA, desc="failure code -2")
fl("liar_value", "g6q_liar_unicode", CA, desc="non-ASCII numeric characters give 0")
fl("liar_value", "g6q_liar_trim", CA, desc="surrounding whitespace is ignored")
fl("liar_value", "g6q_liar_empty_zero", CA, desc="empty text gives 0")
fl("liar_panic", "g6q_liar_panic", CA, desc="panics on empty text")
fl("liar_effect", "g6q_liar_impure", UT, unobservable=True, desc="hidden global call counter, correct results")
fl("liar_effect", "g6q_liar_prints", UT, unobservable=True, desc="writes to stderr, correct results")

# ---- 3. ownership / representation faults (expected: rejected by the checker)
om("missing_move", "q01", "v = push_if_in(move v, a[i], lo, hi);", "v = push_if_in(v, a[i], lo, hi);",
   desc="owned Vec passed to a take parameter without move")
om("use_after_move", "q01", "return len(v);", "let w: Vec<i64> = move v;\n  return len(v);", desc="len of a moved Vec")
om("take_removed", "q01", "fn push_if_in(take v: Vec<i64>,", "fn push_if_in(v: Vec<i64>,",
   desc="moving a borrowed parameter")
om("return_without_move", "q01", "return move v;", "return v;", desc="returning an owned binding without move")
om("immutable_owner", "q02", "let mut m: HashMap<i64, i64> = map_new::<i64, i64>();",
   "let m: HashMap<i64, i64> = map_new::<i64, i64>();", desc="reassigning an immutable HashMap local")
om("take_on_array", "q02", "fn count_value(a: [i64], q: i64) -> i64 ! alloc",
   "fn count_value(take a: [i64], q: i64) -> i64 ! alloc", desc="take on a non-collection parameter")
om("borrow_after_move", "q02", "map_insert::<i64, i64>(move m, x, 1);", "map_insert::<i64, i64>(move m, x, len(m));",
   desc="the moved map is borrowed again in the same call")
om("loop_not_restored", "q02", "m = map_insert::<i64, i64>(move m, x, 1);",
   "let t: HashMap<i64, i64> = map_insert::<i64, i64>(move m, x, 1);",
   desc="one match arm leaves the loop-carried map dead")
om("missing_move", "q03", "s = string_push_str(move s, a);", "s = string_push_str(s, a);", occ=0,
   desc="owned String passed to a take parameter without move")
om("alias_without_move", "q03", "return string_to_str(s);", "let t: String = s;\n  return string_to_str(t);",
   desc="String aliased by plain let")
om("owned_result_type", "q03", "fn join_pair(a: str, b: str, sep: str) -> str ! alloc",
   "fn join_pair(a: str, b: str, sep: str) -> String ! alloc", desc="String where the wrapper must give a str")
om("foreign_take", "q04", "trusted rust fn parse_digit(s: str) -> i64", "trusted rust fn parse_digit(take s: str) -> i64",
   desc="take parameter on a trusted declaration")
om("foreign_collection", "q04", "trusted rust fn parse_digit(s: str) -> i64", "trusted rust fn parse_digit(s: Vec<i64>) -> i64",
   desc="collection argument on a trusted declaration")


# ------------------------------------------------------------------ materializing
def ref_text(pid):
    with open(os.path.join(REF_DIR, pid + ".pruv"), encoding="utf-8") as f:
        return f.read()


def apply_edit(text, old, new, occ="one", scope=None):
    """Replace anchor `old` in text. occ: "one" (must be unique), "all", or the 0-based index of the occurrence.
    scope "decl": only the part before the trusted declaration's path line is edited."""
    head, tail = text, ""
    if scope == "decl":
        end = text.index('\n  = "::')
        head, tail = text[:end], text[end:]
    n = head.count(old)
    if n == 0:
        raise ValueError("anchor not found: %r" % old)
    if occ == "all":
        return head.replace(old, new) + tail
    if occ == "one":
        if n != 1:
            raise ValueError("anchor not unique (%d times): %r" % (n, old))
        return head.replace(old, new) + tail
    if occ >= n:
        raise ValueError("occurrence %d of %d not found: %r" % (occ, n, old))
    idx = -1
    for _ in range(occ + 1):
        idx = head.index(old, idx + 1)
    return head[:idx] + new + head[idx + len(old):] + tail


def materialize(it):
    base = ref_text(it["pid"])
    if it["old"] is None:
        return base
    return apply_edit(base, it["old"], it["new"], it["occ"], it["scope"])


# ------------------------------------------------------------------ verdicts and execution
def verdict(comp, path, extra, work):
    d = tempfile.mkdtemp(prefix="g6v_", dir=work)
    p, err, _ = G2M.run_compiler(comp, path, os.path.join(d, "out.rs"), extra)
    if p is None:
        return {"verdict": "crash", "code": err, "stage": None}
    v, code = G2M.classify(p.returncode, p.stdout)
    stage = None
    for line in p.stdout.splitlines():
        if line.startswith("{"):
            try:
                stage = json.loads(line).get("stage")
            except ValueError:
                stage = None
            break
    r = {"verdict": v, "code": code, "stage": stage}
    if v == "crash":
        r["detail"] = (p.stderr or p.stdout).strip()[-300:]
    return r


def foreign_panic(r):
    return bool(r) and "pruv: foreign" in ((r.get("first_panic") or "") + (r.get("stderr") or ""))


def brief(r):
    if r is None:
        return None
    keys = ("status", "tests_passed", "tests_total", "panics", "first_panic", "first_failure", "compile_error",
            "exit_code")
    return {k: r[k] for k in keys if k in r}


def exec_class(it, r0, r1):
    """Ground truth of an accepted mutant in one configuration. r0: default mode run, r1: --foreign-checks all run
    (foreign kind only). Timeouts and build failures are anomalies (crash); a mutant only counts as caught when a
    `pruv: foreign ...` diagnostic is seen."""
    if r0["status"] in BAD_RUN:
        return "crash", "default run: %s" % r0["status"], None
    if it["kind"] != "foreign":
        if r0["status"] == "ok":
            return EQ, "tests pass", None
        return WV, "tests fail in default mode: %s" % r0.get("first_failure", r0["status"]), None
    if r1["status"] in BAD_RUN:
        return "crash", "all-mode run: %s" % r1["status"], None
    if r0["status"] == "ok":
        if r1["status"] == "ok":
            return (UT, "no test and no runtime check sees the lie", None) if it["unobservable"] else \
                (EQ, "tests pass in default and all mode", None)
        if foreign_panic(r1):
            return CA, "tests pass by default; all mode: %s" % r1.get("first_panic"), "all"
        return WV, "tests pass by default but fail in all mode without a foreign diagnostic: %s" % (
            r1.get("first_failure") or r1["status"]), None
    if foreign_panic(r0):
        return CA, "foreign failure already in default mode: %s" % r0.get("first_panic"), "requires"
    if foreign_panic(r1):
        return CA, "wrong results by default; all mode: %s" % r1.get("first_panic"), "all"
    return UT, "tests observe wrong results, not caught by --foreign-checks all: %s" % r0.get("first_failure"), None


# worst class wins when configurations disagree
SEVERITY = ["crash", WV, UT, CA, EQ]
CONFIGS = [(c, b) for c in ("py", "rs") for b in ("rust", "llvm")]


def classify_item(it, work, rlibs):
    path = os.path.join(work, "%s_%s.pruv" % (it["id"], it["pid"]))
    with open(path, "w", encoding="utf-8") as f:
        f.write(materialize(it))
    rl = rlibs[it["liar"] or "correct"] if it["pid"] in G.NEEDS_EXTERN else None
    extra = ["--rust-extern", "%s=%s" % (G.EXTERN_NAME, rl)] if rl else []
    vs = {c: verdict(c, path, extra, work) for c in ("py", "rs")}
    out = {"id": it["id"], "kind": it["kind"], "family": it["family"], "pid": it["pid"], "desc": it["desc"],
           "edit": None if it["old"] is None else {"from": it["old"], "to": it["new"]}, "liar": it["liar"],
           "expect": it["expect"], "verdicts": vs, "py_rs_diff": vs["py"]["verdict"] != vs["rs"]["verdict"]}
    kinds = [vs[c]["verdict"] for c in ("py", "rs")]
    if "crash" in kinds:
        out.update({"class": "crash", "detail": "compiler crash/timeout: %s" % [vs[c] for c in ("py", "rs")]})
        return out
    if "accepted" not in kinds:
        if "rejected" in kinds:
            st = vs["rs"]["stage"] if vs["rs"]["verdict"] == "rejected" else vs["py"]["stage"]
            out.update({"class": RC if st in CHECK_STAGES else RP,
                        "detail": "%s/%s" % (st, (vs["rs"] if vs["rs"]["verdict"] == "rejected" else vs["py"])["code"])})
        else:
            out.update({"class": "undecided", "detail": "verify_unknown in both compilers"})
        return out
    # run every accepted compiler on both backends; the worst configuration decides the class
    runs = {}
    for comp, backend in CONFIGS:
        if vs[comp]["verdict"] != "accepted":
            continue
        r0 = G.grade_one(path, it["pid"], comp, backend, [], work, rl)
        r1 = None
        if it["kind"] == "foreign" and r0["status"] not in BAD_RUN:
            r1 = G.grade_one(path, it["pid"], comp, backend, ["--foreign-checks", "all"], work, rl)
        cls, detail, det_in = exec_class(it, r0, r1)
        runs["%s_%s" % (comp, backend)] = {"class": cls, "detail": detail, "detected_in": det_in,
                                            "run_default": brief(r0), "run_all": brief(r1)}
    worst = min(runs, key=lambda k: SEVERITY.index(runs[k]["class"]))
    w = runs[worst]
    classes = sorted(set(r["class"] for r in runs.values()))
    out.update({"class": w["class"], "detail": "%s: %s" % (worst, w["detail"]), "detected_in": w["detected_in"],
                "runs": runs, "config_diff": len(classes) > 1})
    if len(classes) > 1:
        out["py_rs_diff"] = True
    return out


# ------------------------------------------------------------------ summary
def summarize(results):
    s = {"mutants": len(results), "by_kind": {}, "by_class": {}, "unexpected": [], "py_rs_diff": [], "crash": [],
         "wrong_but_verified": [], "trust_limitations": [], "versions": G2M.versions()}
    for r in results:
        k = s["by_kind"].setdefault(r["kind"], {"mutants": 0})
        k["mutants"] += 1
        k[r["class"]] = k.get(r["class"], 0) + 1
        s["by_class"][r["class"]] = s["by_class"].get(r["class"], 0) + 1
        if r["class"] != r["expect"]:
            s["unexpected"].append({"id": r["id"], "kind": r["kind"], "desc": r["desc"], "expect": r["expect"],
                                    "got": r["class"], "detail": r.get("detail")})
        if r["py_rs_diff"]:
            s["py_rs_diff"].append({"id": r["id"], "desc": r["desc"],
                                    "py": r["verdicts"]["py"]["verdict"], "rs": r["verdicts"]["rs"]["verdict"],
                                    "runs": dict((k, v["class"]) for k, v in r.get("runs", {}).items())})
        if r["class"] == "crash":
            s["crash"].append({"id": r["id"], "desc": r["desc"], "detail": r.get("detail")})
        if r["class"] == WV:
            s["wrong_but_verified"].append({"id": r["id"], "kind": r["kind"], "desc": r["desc"], "detail": r.get("detail")})
        if r["class"] == UT:
            s["trust_limitations"].append({"id": r["id"], "desc": r["desc"], "detail": r.get("detail")})
    findings = [x for x in s["wrong_but_verified"] if x["kind"] in ("pruv", "ownership")]
    s["findings"] = len(findings)
    s["line"] = ("G6 mutants: %d total (%s); classes: %s; unexpected vs. expectation: %d; wrong_but_verified findings "
                 "(pruv/ownership): %d; crashes: %d; py/rs diffs: %d"
                 % (len(results), ", ".join("%s %d" % (k, v["mutants"]) for k, v in sorted(s["by_kind"].items())),
                    ", ".join("%s %d" % (k, s["by_class"].get(k, 0)) for k in CLASSES),
                    len(s["unexpected"]), len(findings), len(s["crash"]), len(s["py_rs_diff"])))
    return s


def print_table(results):
    print("%-4s %-9s %-15s %-4s %-22s %s" % ("id", "kind", "family", "pid", "class", "detail"))
    for r in results:
        flag = "" if r["class"] == r["expect"] else "  [expected %s]" % r["expect"]
        print("%-4s %-9s %-15s %-4s %-22s %s%s" % (r["id"], r["kind"], r["family"], r["pid"], r["class"],
                                                  (r.get("detail") or "")[:70], flag))


# ------------------------------------------------------------------ self-test and main
def counts():
    c = {"pruv": 0, "foreign": 0, "ownership": 0}
    for it in ITEMS:
        c[it["kind"]] += 1
    return c


def self_test():
    bad = 0
    for it in ITEMS:
        try:
            text = materialize(it)
            if it["old"] is not None and text == ref_text(it["pid"]):
                raise ValueError("mutant equals the reference")
            if it["liar"] and not os.path.exists(os.path.join(ADAPTER_DIR, it["liar"] + ".rs")):
                raise ValueError("liar file missing: %s.rs" % it["liar"])
        except (ValueError, OSError) as e:
            bad += 1
            print("FAIL %s %s: %s" % (it["id"], it["desc"], e))
    c = counts()
    floor = {"pruv": 30, "foreign": 20, "ownership": 10}
    for k, n in floor.items():
        if c[k] < n:
            bad += 1
            print("FAIL kind %s has %d mutants, need %d" % (k, c[k], n))
    liars = sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(ADAPTER_DIR, "g6q_liar*.rs")))
    unused = [l for l in liars if l not in [it["liar"] for it in ITEMS]]
    if unused:
        print("note: liar files without a mutant: %s" % unused)
    print("catalogue: %d mutants %s, %d liar adapters" % (len(ITEMS), c, len(liars)))
    print("self-test:", "fail %d" % bad if bad else "all pass")
    sys.exit(1 if bad else 0)


def main():
    args = sys.argv[1:]
    if "--self-test" in args:
        self_test()
    if "--list" in args:
        for it in ITEMS:
            print("%s %-9s %-15s %s  %s" % (it["id"], it["kind"], it["family"], it["pid"], it["desc"]))
        sys.exit(0)
    jobs_n, only, kind = 4, None, None
    for o in ("--jobs", "--only", "--kind"):
        if o in args:
            i = args.index(o)
            v = args[i + 1]
            del args[i:i + 2]
            if o == "--jobs":
                jobs_n = int(v)
            elif o == "--only":
                only = v
            else:
                kind = v
    if any(a.startswith("-") for a in args):
        sys.exit("usage: mutate_ops.py [--self-test] [--list] [--jobs N] [--only ID|TEXT] [--kind K] [OUT.json]")
    out = args[0] if args else os.path.join(HERE, "results", "mutants.json")
    items = [it for it in ITEMS if (not kind or it["kind"] == kind) and (not only or only in it["desc"] or only == it["id"])]

    work = tempfile.mkdtemp(prefix="g6m_")
    try:
        rlibs = {}
        rl, err = G.build_rlib(G.ADAPTER_SRC, os.path.join(work, "rlib_correct"))
        if err:
            print("correct adapter does not build:\n" + err)
            sys.exit(1)
        rlibs["correct"] = rl
        for name in sorted(set(it["liar"] for it in items if it["liar"])):
            rl, err = G.build_rlib(os.path.join(ADAPTER_DIR, name + ".rs"), os.path.join(work, "rlib_" + name))
            if err:
                print("liar adapter %s does not build:\n%s" % (name, err))
                sys.exit(1)
            rlibs[name] = rl
        print("mutants: %d" % len(items), flush=True)

        def run(it):
            try:
                return classify_item(it, work, rlibs)
            except Exception as e:       # a failure of the harness itself is recorded, not hidden
                return {"id": it["id"], "kind": it["kind"], "family": it["family"], "pid": it["pid"], "desc": it["desc"],
                        "expect": it["expect"], "class": "crash", "detail": "harness error: %r" % (e,),
                        "py_rs_diff": False, "verdicts": {"py": {"verdict": "-"}, "rs": {"verdict": "-"}}}

        with ThreadPoolExecutor(jobs_n) as ex:
            results = list(ex.map(run, items))
    finally:
        shutil.rmtree(work, ignore_errors=True)

    summary = summarize(results)
    od = os.path.dirname(os.path.abspath(out))
    if not os.path.isdir(od):
        os.makedirs(od)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "items": results}, fh, indent=1, ensure_ascii=False)
    print_table(results)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("versions", "line")}, ensure_ascii=False, indent=1))
    print(summary["line"])
    if summary["findings"] or summary["crash"] or (len(results) < 60 and not (only or kind)):
        sys.exit(1)


if __name__ == "__main__":
    main()
