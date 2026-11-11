# -*- coding: utf-8 -*-
"""G3 (generics) mutation test.

  python bench/g3/mutate_ops.py [OUT.json] [--jobs N] [--infer] [--kind ref|proof|example] [--only SUBSTR]
  python bench/g3/mutate_ops.py --self-test        (operators on fixed lines, no compiler)

Sources: bench/g3/solutions/ref/q*.pruv ("ref"), tests/g3/proof/*.pruv ("proof"), examples/g3_*.pruv ("example").
A source that is not accepted by both compilers is skipped (reported as baseline_rejected).

Operator families (the six of docs/G3_SPEC.md 7.8; existing G2/base operator lists are not touched):
  type_subst     a type argument at a call/constructor `::<..>` is swapped with its neighbour or i64<->bool
  field_swap     struct field access `.f` becomes `.g` (other field of the same struct); or the values of two
                 consecutive field initializers are exchanged
  wrong_payload  `return v;` returns another payload/parameter of the function, or the default 0 / false
  guard_delete   a `requires` (or a conjunct of it) that mentions len(..)/is_some(..) is deleted; an `if` guard
                 mentioning them becomes true or loses a conjunct
  false_ensures  `==` <-> `!=` in an ensures atom (consequent only, no `||` lines); or `.f` <-> `.g` in an ensures
  bound_loss     `T: Element` becomes `T` on a fn header (the bound is lost while T is still used as [T] or forwarded)

Verification verdicts of each mutant: py and rs compiler (plain verify mode, rust backend; --infer adds the
`--infer` runs). Independent classification (the verifier is never consulted):
  1. `rs --no-verify` must accept the mutant (type check only); otherwise "not_compilable" (excluded), except
     bound_loss whose truth is by rule.
  2. false_ensures, bound_loss, requires deletion: RULE
       eq_flip         the flipped atom contradicts the verified original (consequent of a verified ensures) -> incorrect
       ens field_swap  incorrect when the function has no `requires` and the swapped atom is not (up to == symmetry)
                       another ensures atom of the same function; else unclassified
       bound_loss      incorrect when the function (after the change) still writes [T], or forwards T at an
                       argument position whose callee parameter is `: Element` (the program violates SPEC 6c)
       requires delete incorrect when the removed part mentions len(X), the body indexes X[<literal>] or
                       X[len(X) - k], no other requires mentions len(X) and no code line tests len(X)
  3. the other families: EXECUTION
       ref      the mutant (--no-verify, rust backend) runs the concrete wrapper tests of run.py incl. the
                requires-violation probes; wrong -> incorrect, ok -> not_incorrect
       example  the mutant's stdout and exit code are compared with the original program's; different -> incorrect
       proof    no main to execute -> unclassified
"incorrectly verified" = truth incorrect and some verifier run accepted. "not rejected" = truth incorrect and some run
is not a clean rejection (accepted, undecided, crash).
Exit code 1 if any incorrect mutant is accepted or crashes were seen.
"""
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G2M = _load("g2_mutate_ops", os.path.join(ROOT, "bench", "g2", "mutate_ops.py"))   # verify/classify helpers only
G = _load("g3_run", os.path.join(HERE, "run.py"))

GUARD_WORDS = ("len(", "is_some(")
IF_RE = re.compile(r"^(\s*(?:\}\s*else\s+)?if\s+)(.+?)(\s*\{)\s*$")
ACCESS_RE = re.compile(r"(?<=[\w\)\]])\.([A-Za-z_]\w*)\b(?!\s*\()")
EQ_RE = re.compile(r"(?<![=!<>])==(?![=>])")
NE_RE = re.compile(r"!=(?!=)")
CONTRACT_RE = re.compile(r"^\s*(requires|ensures|invariant|decreases)\b")
RETURN_RE = re.compile(r"\breturn\s+(\w+)\s*;")


# ------------------------------------------------------------------ source model
class Src:
    def __init__(s, path, kind):
        s.path, s.kind = path, kind
        s.name = os.path.splitext(os.path.basename(path))[0]
        s.text = open(path, encoding="utf-8").read()
        s.lines = s.text.split("\n")
        s.structs = {}
        for m in re.finditer(r"\bstruct\s+(\w+)\s*(?:<[^>{]*>)?\s*\{([^}]*)\}", s.text):
            s.structs[m.group(1)] = re.findall(r"(\w+)\s*:", m.group(2))
        starts = [i for i, l in enumerate(s.lines) if re.match(r"\s*fn\s+\w+", l)]
        s.spans = [(a, starts[k + 1] if k + 1 < len(starts) else len(s.lines)) for k, a in enumerate(starts)]
        s.owner = [None] * len(s.lines)
        for k, (a, b) in enumerate(s.spans):
            for i in range(a, b):
                s.owner[i] = k
        s.tparams = {}   # fn name -> list of type parameter declarations ("T: Element", "U")
        for l in s.lines:
            m = re.match(r"\s*fn\s+(\w+)\s*<([^<>()]*)>", l)
            if m:
                s.tparams[m.group(1)] = [p.strip() for p in m.group(2).split(",")]

    def span_lines(s, i):
        k = s.owner[i]
        return None if k is None else range(*s.spans[k])

    def idents(s, i):
        """Parameters and match payload variables of the function containing line i."""
        r = s.span_lines(i)
        names = []
        head = " ".join(s.lines[x] for x in r)
        head = head.split("{")[0]
        if "(" in head:
            names += re.findall(r"[(,]\s*(\w+)\s*:", head[head.index("("):])
        for x in r:
            names += re.findall(r"\b[A-Z]\w*\(\s*(\w+)\s*\)\s*=>", s.lines[x])
        return list(dict.fromkeys(names))


def split_commas(s):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "<([":
            depth += 1
        elif ch in ">)]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def targs(line):
    """[(start, end, [args])] of every `::<..>` in the line."""
    out = []
    for m in re.finditer(r"::<", line):
        j, depth = m.end(), 1
        while j < len(line) and depth:
            depth += {"<": 1, ">": -1}.get(line[j], 0)
            j += 1
        if depth == 0:
            out.append((m.end(), j - 1, split_commas(line[m.end():j - 1])))
    return out


# ------------------------------------------------------------------ operators: (variant, {line index: new text}, meta)
def op_type_subst(src, i):
    line, res = src.lines[i], []
    for s, e, args in targs(line):
        alts = []
        for k in range(len(args) - 1):
            if args[k] != args[k + 1]:
                alts.append(args[:k] + [args[k + 1], args[k]] + args[k + 2:])
        for k, a in enumerate(args):
            if a in ("i64", "bool"):
                alts.append(args[:k] + [("bool" if a == "i64" else "i64")] + args[k + 1:])
        for alt in alts:
            res.append(("targ", {i: line[:s] + ", ".join(alt) + line[e:]}, {}))
    return res


def op_field_swap(src, i):
    line, res = src.lines[i], []
    if src.owner[i] is None or CONTRACT_RE.match(line):
        return res
    for m in ACCESS_RE.finditer(line):
        for fields in src.structs.values():
            if m.group(1) in fields:
                for g in fields:
                    if g != m.group(1):
                        res.append(("access", {i: line[:m.start(1)] + g + line[m.end(1):]}, {}))
    br = re.search(r"\{(.*)\}", line)
    if br and "::<" in line[:br.start()]:
        pairs = [re.match(r"(\w+)\s*:\s*(.*)$", p) for p in split_commas(br.group(1))]
        if len(pairs) >= 2 and all(pairs):
            for k in range(len(pairs) - 1):
                vals = [p.group(2) for p in pairs]
                vals[k], vals[k + 1] = vals[k + 1], vals[k]
                body = ", ".join("%s: %s" % (p.group(1), v) for p, v in zip(pairs, vals))
                res.append(("literal", {i: line[:br.start(1)] + " " + body + " " + line[br.end(1):]}, {}))
    FIELD = re.compile(r"^(\s*)(\w+):\s*(.*?)(,?)\s*$")
    if i + 1 < len(src.lines) and src.owner[i + 1] == src.owner[i]:
        a, b = FIELD.match(line), FIELD.match(src.lines[i + 1])
        if a and b and a.group(2) != b.group(2) and a.group(3) != b.group(3):
            res.append(("literal", {i: "%s%s: %s%s" % (a.group(1), a.group(2), b.group(3), a.group(4)),
                                    i + 1: "%s%s: %s%s" % (b.group(1), b.group(2), a.group(3), b.group(4))}, {}))
    return res


def op_wrong_payload(src, i):
    line, res = src.lines[i], []
    if src.owner[i] is None or CONTRACT_RE.match(line):
        return res
    names = src.idents(i)
    for m in RETURN_RE.finditer(line):
        if m.group(1) in names:
            for w in [n for n in names if n != m.group(1)] + ["0", "false"]:
                res.append(("return", {i: line[:m.start(1)] + w + line[m.end(1):]}, {}))
    return res


def _has_guard(s):
    return any(w in s for w in GUARD_WORDS)


def op_guard_delete(src, i):
    line, res = src.lines[i], []
    m = re.match(r"^(\s*)requires\s+(.*)$", line)
    if m and _has_guard(m.group(2)):
        expr = m.group(2)
        spans = G2M.split_top(expr, 0, len(expr), "&&")
        if len(spans) == 1:
            res.append(("requires_delete", {i: m.group(1) + "// guard deleted"}, {"dropped": expr}))
        else:
            for a, b in spans:
                if _has_guard(expr[a:b]):
                    rest = " && ".join(expr[c:d].strip() for c, d in spans if (c, d) != (a, b))
                    res.append(("requires_drop", {i: m.group(1) + "requires " + rest}, {"dropped": expr[a:b]}))
        return res
    m = IF_RE.match(line)
    if m and _has_guard(m.group(2)):
        cond = m.group(2)
        res.append(("if_true", {i: m.group(1) + "true" + m.group(3)}, {}))
        spans = G2M.split_top(cond, 0, len(cond), "&&")
        if len(spans) > 1:
            for a, b in spans:
                if _has_guard(cond[a:b]):
                    rest = " && ".join(cond[c:d].strip() for c, d in spans if (c, d) != (a, b))
                    res.append(("if_drop", {i: m.group(1) + rest + m.group(3)}, {}))
    return res


def op_false_ensures(src, i):
    line, res = src.lines[i], []
    m = re.match(r"^(\s*ensures\s+)(.*)$", line)
    if not m or src.owner[i] is None:
        return res
    expr = m.group(2)
    if "||" in expr:
        return res
    arrow = expr.find("==>")
    start = arrow + 3 if arrow >= 0 else 0
    for rx, rep in ((EQ_RE, "!="), (NE_RE, "==")):
        for e in rx.finditer(expr):
            if e.start() >= start:
                res.append(("eq_flip", {i: m.group(1) + expr[:e.start()] + rep + expr[e.end():]}, {}))
    for a in ACCESS_RE.finditer(expr):
        for fields in src.structs.values():
            if a.group(1) in fields:
                for g in fields:
                    if g != a.group(1):
                        res.append(("field_swap", {i: m.group(1) + expr[:a.start(1)] + g + expr[a.end(1):]}, {}))
    return res


def op_bound_loss(src, i):
    line, res = src.lines[i], []
    if not re.match(r"\s*fn\s+\w+\s*<", line):
        return res
    for m in re.finditer(r"\b(\w+)\s*:\s*Element\b", line):
        res.append(("bound_drop", {i: line[:m.start()] + m.group(1) + line[m.end():]}, {"param": m.group(1)}))
    return res


OPS = [("type_subst", op_type_subst), ("field_swap", op_field_swap), ("wrong_payload", op_wrong_payload),
       ("guard_delete", op_guard_delete), ("false_ensures", op_false_ensures), ("bound_loss", op_bound_loss)]


def make_mutants(src):
    """[{line, from, to, text, ops: ["family:variant"], family, variant, meta, i}]; identical texts are merged."""
    seen, out = {}, []
    for i, line in enumerate(src.lines):
        if line.strip().startswith("//"):
            continue
        for fam, op in OPS:
            for variant, changes, meta in op(src, i):
                lines = list(src.lines)
                for k, v in changes.items():
                    lines[k] = v
                text = "\n".join(lines)
                if text == src.text:
                    continue
                tag = "%s:%s" % (fam, variant)
                if text in seen:
                    if tag not in seen[text]["ops"]:
                        seen[text]["ops"].append(tag)
                    continue
                it = {"line": i + 1, "from": line.strip(), "to": changes[i].strip(), "text": text, "ops": [tag],
                      "family": fam, "variant": variant, "meta": meta, "i": i}
                seen[text] = it
                out.append(it)
    return out


# ------------------------------------------------------------------ independent classification
def _norm_atom(s):
    s = re.sub(r"\s+", "", s)
    if s.count("==") == 1 and "==>" not in s and "!=" not in s:
        s = "==".join(sorted(s.split("==")))
    return s


def rule_truth(src, it):
    fam, variant, i = it["family"], it["variant"], it["i"]
    lines = it["text"].split("\n")
    span = src.span_lines(i)
    if span is None:
        return "unclassified", "outside a function"
    if fam == "false_ensures":
        if variant == "eq_flip":
            return "incorrect", "negated atom of a verified ensures"
        if any(CONTRACT_RE.match(lines[x]) and lines[x].strip().startswith("requires") for x in span):
            return "unclassified", "function has requires"
        new = _norm_atom(re.sub(r"^\s*ensures\s+", "", lines[i]))
        sides = new.split("==") if new.count("==") == 1 and "==>" not in new else None
        if sides and sides[0] == sides[1]:
            return "not_incorrect", "the swap made a tautology (x == x): weaker, still true"
        if any(_norm_atom(re.sub(r"^\s*ensures\s+", "", lines[x])) == new
               for x in span if x != i and lines[x].strip().startswith("ensures")):
            return "unclassified", "equals another ensures atom"
        return "incorrect", "swapped fields claim a different value"
    if fam == "bound_loss":
        t, body = it["meta"]["param"], "\n".join(lines[x] for x in span)
        if re.search(r"\[\s*%s\s*\]" % re.escape(t), body):
            return "incorrect", "[%s] without Element bound" % t
        for callee, args in ((m.group(1), a) for m in re.finditer(r"(\w+)::<", body) for _, _, a in targs(body[m.start():])[:1]):
            decl = src.tparams.get(callee, [])
            for k, a in enumerate(args):
                if a == t and k < len(decl) and decl[k].endswith("Element"):
                    return "incorrect", "%s forwarded to Element parameter of %s" % (t, callee)
        return "unclassified", "bound not needed"
    if variant.startswith("requires"):
        dropped = it["meta"]["dropped"]
        rest_req = " ".join(lines[x] for x in span if lines[x].strip().startswith("requires"))
        code = [lines[x] for x in span if not CONTRACT_RE.match(lines[x]) and not lines[x].strip().startswith("fn ")]
        for x in re.findall(r"len\((\w+)\)", dropped):
            idx = r"\b%s\[\s*(\d+|len\(%s\)\s*-\s*\d+)\s*\]" % (x, x)
            if (any(re.search(idx, c) for c in code) and ("len(%s)" % x) not in rest_req
                    and not any(("len(%s)" % x) in c for c in code)):
                return "incorrect", "body indexes %s without any len guard" % x
        return "unclassified", "deleted guard not needed by the body"
    return "unclassified", "no rule"


def run_program(path, work):
    """Compile with rs --no-verify (rust backend) and rustc, run. {"st": ok|not_compilable|crash|timeout, "rc", "out"}"""
    rs = os.path.join(work, "prog.rs")
    p, err, _ = G2M.run_compiler("rs", path, rs, ["--no-verify"])
    if p is None:
        return {"st": "crash", "detail": err}
    v, code = G2M.classify(p.returncode, p.stdout)
    if v != "accepted":
        return {"st": "not_compilable" if v == "rejected" else "crash", "detail": code}
    exe = os.path.join(work, "prog")
    c = subprocess.run([G.G2.RUSTC, "-C", "opt-level=0", "--edition", "2021", "-A", "warnings", rs, "-o", exe],
                       capture_output=True, encoding="utf-8", errors="replace")
    if c.returncode != 0:
        return {"st": "crash", "detail": "rustc: " + c.stderr[-200:]}
    try:
        r = subprocess.run([exe], capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    except subprocess.TimeoutExpired:
        return {"st": "timeout"}
    return {"st": "ok", "rc": r.returncode, "out": r.stdout}


def truth(src, it, path, baseline):
    d = tempfile.mkdtemp(prefix="g3t_")
    try:
        fam = it["family"]
        if fam == "bound_loss":                        # SPEC 6c violation: judged by rule, compile check not used
            t, why = rule_truth(src, it)
            return {"truth": t, "method": "rule", "detail": why}
        rs = os.path.join(d, "x.rs")
        p, err, _ = G2M.run_compiler("rs", path, rs, ["--no-verify"])
        if p is None:
            return {"truth": "crash", "method": "-", "detail": err}
        v, code = G2M.classify(p.returncode, p.stdout)
        if v == "rejected":
            return {"truth": "not_compilable", "method": "-", "detail": code}
        if v != "accepted":
            return {"truth": "crash", "method": "-", "detail": "compiler %s %s" % (v, code)}
        if fam == "false_ensures" or it["variant"].startswith("requires"):
            t, why = rule_truth(src, it)
            return {"truth": t, "method": "rule", "detail": why}
        if src.kind == "proof":
            return {"truth": "unclassified", "method": "-", "detail": "no main to execute"}
        if src.kind == "ref":
            r = G.build_and_run(rs, src.name, d, probes=True, opt="-O0")
            st = r["status"]
            if st == "ok":
                return {"truth": "not_incorrect", "method": "execution", "detail": "passes %s tests" % r["tests_total"]}
            if st in ("wrong", "timeout"):
                return {"truth": "incorrect", "method": "execution", "detail": r.get("first_failure", st)}
            return {"truth": "crash", "method": "execution", "detail": r.get("compile_error", st)[:300]}
        if not baseline or baseline["st"] != "ok":
            return {"truth": "unclassified", "method": "-", "detail": "original program not runnable"}
        span = src.span_lines(it["i"])
        if span is None or not any(it["text"].split("\n")[x].strip().startswith("ensures") for x in span):
            # the mutated function states no ensures (main's prints, helpers without a contract): a behavior change
            # there is not something verification can reject, so it is not counted as an incorrectly verified mutant
            return {"truth": "out_of_contract", "method": "-", "detail": "mutated function has no ensures"}
        r = run_program(path, d)
        if r["st"] == "not_compilable":
            return {"truth": "not_compilable", "method": "-", "detail": r.get("detail")}
        if r["st"] == "crash":
            return {"truth": "crash", "method": "execution", "detail": r.get("detail")}
        if r["st"] == "timeout" or (r["rc"], r["out"]) != (baseline["rc"], baseline["out"]):
            return {"truth": "incorrect", "method": "execution",
                    "detail": "output %r rc %s vs %r rc %s" % (r.get("out", "timeout")[:60], r.get("rc"),
                                                              baseline["out"][:60], baseline["rc"])}
        return {"truth": "not_incorrect", "method": "execution", "detail": "same output"}
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ------------------------------------------------------------------ summary
def summarize(items, runs, skipped):
    keys = [G2M.key(c, inf) for c, inf in runs]
    inc = [it for it in items if it["truth"]["truth"] == "incorrect"]

    def brief(it):
        return {"src": it["src"], "line": it["line"], "from": it["from"], "to": it["to"], "ops": it["ops"]}

    s = {"command": " ".join(sys.argv[1:]), "versions": G2M.versions(), "mutants": len(items),
         "baseline_rejected": skipped}
    s["truth_counts"] = {}
    for it in items:
        s["truth_counts"][it["truth"]["truth"]] = s["truth_counts"].get(it["truth"]["truth"], 0) + 1
    s["incorrect"] = len(inc)
    s["incorrect_by_method"] = {m: sum(1 for it in inc if it["truth"]["method"] == m) for m in ("execution", "rule")}
    s["by_family"] = {}
    for it in items:
        row = s["by_family"].setdefault(it["family"], {"mutants": 0, "incorrect": 0, "rejected_incorrect": 0})
        row["mutants"] += 1
        if it["truth"]["truth"] == "incorrect":
            row["incorrect"] += 1
            row["rejected_incorrect"] += all(it[k]["verdict"] == "rejected" for k in keys)
    s["by_kind"] = {}
    for it in inc:
        s["by_kind"][it["kind"]] = s["by_kind"].get(it["kind"], 0) + 1
    s["incorrectly_verified"] = [dict(brief(it), runs=[k for k in keys if it[k]["verdict"] == "accepted"])
                                 for it in inc if any(it[k]["verdict"] == "accepted" for k in keys)]
    s["not_rejected"] = [dict(brief(it), verdicts={k: it[k]["verdict"] for k in keys})
                         for it in inc if any(it[k]["verdict"] != "rejected" for k in keys)]
    s["crash"] = [dict(brief(it), truth_crash=it["truth"]["truth"] == "crash",
                       runs=[k for k in keys if it[k]["verdict"] == "crash"])
                  for it in items if it["truth"]["truth"] == "crash" or any(it[k]["verdict"] == "crash" for k in keys)]
    s["py_rs_verdict_diff"] = [dict(brief(it), mode=m, py=it["py_" + m]["verdict"], rs=it["rs_" + m]["verdict"])
                               for it in items for m in ("plain", "infer")
                               if "py_" + m in it and it["py_" + m]["verdict"] != it["rs_" + m]["verdict"]]
    s["accepted_not_incorrect"] = sum(1 for it in items if it["truth"]["truth"] == "not_incorrect"
                                      and any(it[k]["verdict"] == "accepted" for k in keys))
    s["line"] = ("G3 mutants: %d total, %d independently classified incorrect (%d by execution, %d by rule), "
                 "incorrectly verified: %d, not cleanly rejected: %d, crashes: %d, py/rs diffs: %d"
                 % (len(items), len(inc), s["incorrect_by_method"]["execution"], s["incorrect_by_method"]["rule"],
                    len(s["incorrectly_verified"]), len(s["not_rejected"]), len(s["crash"]),
                    len(s["py_rs_verdict_diff"])))
    return s


# ------------------------------------------------------------------ self-test
def self_test():
    d = tempfile.mkdtemp(prefix="g3st_")
    p = os.path.join(d, "t.pruv")
    open(p, "w").write("""struct Pair<A, B> {
  first: A,
  second: B
}
fn f<T: Element>(a: [T], d: T) -> T
  requires len(a) > 0
  ensures result == a[0]
{
  let z: T = a[0];
  match o {
    Some(v) => { return v; }
  }
  let q: Pair<bool, i64> = swap::<i64, bool>(p);
  return q.first;
}
""")
    src = Src(p, "proof")
    ms = make_mutants(src)
    want = [("type_subst", "swap::<bool, i64>"), ("type_subst", "swap::<bool, bool>"), ("field_swap", "q.second"),
            ("wrong_payload", "return d;"), ("wrong_payload", "return 0;"), ("guard_delete", "// guard deleted"),
            ("false_ensures", "result != a[0]"), ("bound_loss", "fn f<T>")]
    bad = 0
    for fam, frag in want:
        ok = any(m["family"] == fam and frag in m["to"] for m in ms)
        bad += not ok
        print("%s %-14s %s" % ("ok  " if ok else "FAIL", fam, frag))
    t = [m for m in ms if m["family"] == "bound_loss"][0]
    r = rule_truth(src, t)
    bad += r[0] != "incorrect"
    print("%s bound_loss rule %r" % ("ok  " if r[0] == "incorrect" else "FAIL", r))
    g = [m for m in ms if m["variant"] == "requires_delete"][0]
    r = rule_truth(src, g)
    bad += r[0] != "incorrect"
    print("%s requires rule %r" % ("ok  " if r[0] == "incorrect" else "FAIL", r))
    shutil.rmtree(d, ignore_errors=True)
    print("self-test:", "fail %d" % bad if bad else "all pass")
    sys.exit(1 if bad else 0)


# ------------------------------------------------------------------ main
def main():
    args = sys.argv[1:]
    if "--self-test" in args:
        self_test()
    jobs_n, infer, kinds, only = 6, False, ("ref", "proof", "example"), None
    for o in ("--jobs", "--kind", "--only"):
        if o in args:
            i = args.index(o)
            v = args[i + 1]
            del args[i:i + 2]
            if o == "--jobs":
                jobs_n = int(v)
            elif o == "--kind":
                kinds = (v,)
            else:
                only = v
    if "--infer" in args:
        args.remove("--infer")
        infer = True
    out = args[0] if args else os.path.join(HERE, "results", "mutants.json")
    runs = [(c, False) for c in ("py", "rs")] + ([(c, True) for c in ("py", "rs")] if infer else [])

    files = []
    if "ref" in kinds:
        files += [(f, "ref") for f in sorted(glob.glob(os.path.join(HERE, "solutions", "ref", "q*.pruv")))]
    if "proof" in kinds:
        files += [(f, "proof") for f in sorted(glob.glob(os.path.join(ROOT, "tests", "g3", "proof", "*.pruv")))]
    if "example" in kinds:
        files += [(f, "example") for f in sorted(glob.glob(os.path.join(ROOT, "examples", "g3_*.pruv")))]
    if only:
        files = [f for f in files if only in f[0]]

    work = tempfile.mkdtemp(prefix="g3m_")
    items, skipped, srcs, baselines = [], [], {}, {}
    try:
        def base_check(fk):
            f, kind = fk
            ok = all(G2M.verify(c, f, False)["verdict"] == "accepted" for c in ("py", "rs"))
            bl = None
            if ok and kind == "example":
                d = tempfile.mkdtemp(prefix="g3b_", dir=work)
                bl = run_program(f, d)
            return fk, ok, bl

        with ThreadPoolExecutor(jobs_n) as ex:
            for (f, kind), ok, bl in ex.map(base_check, files):
                rel = os.path.relpath(f, ROOT)
                if not ok:
                    skipped.append(rel)
                    continue
                src = Src(f, kind)
                srcs[rel], baselines[rel] = src, bl
                for n, m in enumerate(make_mutants(src)):
                    p = os.path.join(work, "%s_%03d.pruv" % (src.name, n))
                    with open(p, "w", encoding="utf-8") as fh:
                        fh.write(m["text"])
                    m.update(src=rel, kind=kind, file=p)
                    items.append(m)
        print("sources: %d (baseline rejected: %d), mutants: %d" % (len(srcs), len(skipped), len(items)), flush=True)

        def run_v(t):
            i, c, inf = t
            return t, G2M.verify(c, items[i]["file"], inf)

        def run_t(i):
            it = items[i]
            return i, truth(srcs[it["src"]], it, it["file"], baselines[it["src"]])

        with ThreadPoolExecutor(jobs_n) as ex:
            tf = [ex.submit(run_t, i) for i in range(len(items))]
            vf = [ex.submit(run_v, (i, c, inf)) for i in range(len(items)) for c, inf in runs]
            for fu in vf:
                (i, c, inf), r = fu.result()
                items[i][G2M.key(c, inf)] = r
            for fu in tf:
                i, r = fu.result()
                items[i]["truth"] = r
    finally:
        shutil.rmtree(work, ignore_errors=True)

    for it in items:
        for k in ("file", "text", "meta", "i"):
            it.pop(k, None)
    summary = summarize(items, runs, skipped)
    od = os.path.dirname(os.path.abspath(out))
    if not os.path.isdir(od):
        os.makedirs(od)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "items": items}, fh, indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("versions", "line")}, ensure_ascii=False, indent=1))
    print(summary["line"])
    if summary["incorrectly_verified"] or summary["crash"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
