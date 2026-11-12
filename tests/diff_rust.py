#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare, byte for byte, the output (Rust source) of the canonical Python gen_rust and Rust pruv-rust-dump.

  python tests/diff_rust.py [--rs-path PATH] [--only GROUP,...] [--seeds 41,56,57]
                            [--fuzz-count 200] [--mutations 3] [--save-dir DIR]
                            [--modes VT,Vt,vT,vt,B]

Groups: must_reject examples runtime bench g9 edge fuzz mutate
  g9 = tests/g9/frontend/*.pruv (until batch A2 both compilers must agree on the downstream guard diagnostic).
  edge = tests/check_edge/ok_*.pruv plus all of tests/check_edge/*.pruv (deduplicated).
Modes (case = input x mode): the first letter V/v = verified on/off, the second letter T/t = trust_callers on/off.
  Vt=(True,False) VT=(True,True) vt=(False,False) vT=(False,True), default budget 1<<30.
  B = only for inputs that have a contract_budget in the runtime json or a --contract-budget value in flags (including flags_matrix),
      one more run with that budget at (V=True,T=False). The default for --modes is all of them (Vt,VT,vt,vT,B).
Expected line = json.dumps(obj, sort_keys=True, ensure_ascii=False), obj =
  {"rs":..} | {"error":{..}} | {"internal":msg} | {"adapter_error":"decode"}.
  RecursionError -> py_recursion (excluded from comparison). Rust: one call per 200 files for each (mode, budget)
  (`pruv-rust-dump [--no-verify] [--trust-callers] --budget N FILE...`).
  Exit code != 0, timeout, line-count mismatch, or no trailing newline -> the whole batch is rs_crash.
Exit codes: 0 = diff and crash (py_crash, rs_crash) are all 0, 1 = anything else, 2 = bad arguments / binary missing.
Uses only the Python 3.9 standard library.
"""
import argparse
import collections
import glob
import json
import os
import random
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "pruvc"))

from vast import PruvError  # noqa: E402
from vparser import parse  # noqa: E402
from check import check  # noqa: E402
from codegen import gen_rust  # noqa: E402
from typeinfo import g9_unimplemented_error  # noqa: E402

BATCH = 200
RS_TIMEOUT = 300
MAX_SHOWN = 10
DEFAULT_BUDGET = 1 << 30
STATUSES = ("same", "diff", "py_recursion", "py_crash", "rs_crash")

GROUP_DIRS = [
    ("must_reject", "tests/must_reject"),
    ("examples", "examples"),
    ("runtime", "tests/runtime"),
    ("bench", "bench/solutions/pruv_agg"),
    ("g9", "tests/g9/frontend"),
]
CHECK_EDGE_DIR = "tests/check_edge"
ALL_GROUPS = ["must_reject", "examples", "runtime", "bench", "g9", "edge", "fuzz", "mutate"]

# (label, verified, trust_callers). B is handled separately.
MODE_TABLE = collections.OrderedDict([
    ("Vt", (True, False)),
    ("VT", (True, True)),
    ("vt", (False, False)),
    ("vT", (False, True)),
])
BUDGET_MODE = "B"
ALL_MODES = list(MODE_TABLE) + [BUDGET_MODE]

FRAGMENTS = [
    "-", "--", "_", "1_", "9223372036854775808", "99999999999999999999999999999999",
    "(", ")", "{", "}", ";", ",", "::", "..", "==>", "=>", "->", "!", "&", "|", "#", "\"", "'",
    "é", "한", "😀", "\t", "\n", "\x0c", "\x00",
    "fn", "let", "match", "struct", "enum", "pruv_x", "a__b", "type", "_", "Some(", "None",
    "Foo::", "is_variant(", "sum(", "forall",
]


class Case(object):
    __slots__ = ("group", "name", "path", "mode", "verified", "trust", "budget", "py", "rs", "status", "note")

    def __init__(self, group, name, path, mode, verified, trust, budget):
        self.group, self.name, self.path = group, name, path
        self.mode, self.verified, self.trust, self.budget = mode, verified, trust, budget
        self.py = None      # bytes (no newline)
        self.rs = None
        self.status = None
        self.note = ""


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def safe(name):
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", name)[:80]


def list_dir(sub):
    return sorted(glob.glob(os.path.join(ROOT, *sub.split("/")) + os.sep + "*.pruv"))


def list_edge():
    d = os.path.join(ROOT, *CHECK_EDGE_DIR.split("/"))
    seen, out = set(), []
    for pat in ("ok_*.pruv", "*.pruv"):
        for p in sorted(glob.glob(os.path.join(d, pat))):
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out


def parse_seed(tok):
    return int(tok) if re.fullmatch(r"-?[0-9]+", tok) else tok


def parse_modes(text):
    out = []
    for tok in re.split(r"[,\s]+", text.strip()):
        if not tok:
            continue
        if tok.lower() in ("b", "budget"):
            m = BUDGET_MODE
        elif re.fullmatch(r"[VvTt]{2}", tok) and tok[0] in "Vv" and tok[1] in "Tt":
            m = ("V" if tok[0] == "V" else "v") + ("T" if tok[1] == "T" else "t")
        else:
            return None
        if m not in out:
            out.append(m)
    return out or None


def runtime_budgets(path):
    """List of budget values from a runtime input's json (deduplicated, order kept). [] if there are none."""
    j = os.path.splitext(path)[0] + ".json"
    vals = []
    try:
        with open(j, encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, ValueError):
        return vals

    def add(v):
        try:
            v = int(v)
        except (TypeError, ValueError):
            return
        if v not in vals:
            vals.append(v)

    if "contract_budget" in spec:
        add(spec["contract_budget"])
    rows = [spec.get("flags") or []] + [r for r in (spec.get("flags_matrix") or []) if isinstance(r, list)]
    for fl in rows:
        if not isinstance(fl, list):
            continue
        for i, f in enumerate(fl):
            if isinstance(f, str):
                if f == "--contract-budget" and i + 1 < len(fl):
                    add(fl[i + 1])
                elif f.startswith("--contract-budget="):
                    add(f.split("=", 1)[1])
    return vals


def mutate_text(text, rng):
    n = len(text)
    op = rng.randrange(4)
    if op == 0 and n:
        cnt = rng.randint(1, 3)
        pos = rng.randrange(n)
        return text[:pos] + text[pos + cnt:]
    if op == 2 and n >= 2:
        a, b, c = sorted(rng.randint(0, n) for _ in range(3))
        return text[:a] + text[b:c] + text[a:b] + text[c:]
    if op == 3 and n:
        return text[:rng.randrange(n)]
    pos = rng.randint(0, n)
    return text[:pos] + rng.choice(FRAGMENTS) + text[pos:]


def build_inputs(selected, args, tmp):
    """-> (group -> [(name, path, [budget...])], notes)"""
    notes = []
    per = collections.OrderedDict((g, []) for g in ALL_GROUPS)
    base = []
    for g, sub in GROUP_DIRS:
        files = list_dir(sub)
        if not files:
            notes.append("warning: no *.pruv in %s (%s)" % (g, sub))
        for p in files:
            base.append((rel(p), p))
            if g in selected:
                per[g].append((rel(p), p, runtime_budgets(p) if g == "runtime" else []))
    edge = list_edge()
    if not edge:
        notes.append("warning: no *.pruv in edge (%s)" % CHECK_EDGE_DIR)
    for p in edge:
        base.append((rel(p), p))
        if "edge" in selected:
            per["edge"].append((rel(p), p, []))
    if "fuzz" in selected:
        d = os.path.join(tmp, "fuzz")
        os.makedirs(d)
        sys.path.insert(0, os.path.join(ROOT, "bench", "fuzz"))
        try:
            import generate
        except Exception as e:   # noqa: BLE001
            print("error: could not load the fuzzer generator: %s: %s" % (type(e).__name__, e), file=sys.stderr)
            raise SystemExit(2)
        skipped = 0
        for seed in args.seeds:
            for idx in range(args.fuzz_count):
                try:
                    data = generate.generate_case(seed, idx)["src"].encode("utf-8")
                except Exception:   # noqa: BLE001
                    skipped += 1
                    continue
                p = os.path.join(d, "s%s_%05d.pruv" % (safe(str(seed)), idx))
                with open(p, "wb") as fh:
                    fh.write(data)
                per["fuzz"].append(("fuzz:%s:%d" % (seed, idx), p, []))
        notes.append("fuzz: %d indexes skipped due to generator exceptions (seeds=%s, count=%d)" % (
            skipped, ",".join(str(s) for s in args.seeds), args.fuzz_count))
    if "mutate" in selected:
        d = os.path.join(tmp, "mutate")
        os.makedirs(d)
        n = 0
        for r, p in base:
            with open(p, "rb") as fh:
                text = fh.read().decode("utf-8", "replace")
            for k in range(args.mutations):
                rng = random.Random("%s:%s:%d" % ("mut", r, k))
                q = os.path.join(d, "m%05d.pruv" % n)
                n += 1
                with open(q, "wb") as fh:
                    fh.write(mutate_text(text, rng).encode("utf-8"))
                per["mutate"].append(("%s#%d" % (r, k), q, []))
    return per, notes


def make_cases(group, inputs, modes):
    cases = []
    for name, path, budgets in inputs:
        for m in modes:
            if m == BUDGET_MODE:
                for b in budgets:
                    cases.append(Case(group, name, path, "B%d" % b, True, False, b))
            else:
                v, t = MODE_TABLE[m]
                cases.append(Case(group, name, path, m, v, t, DEFAULT_BUDGET))
    return cases


def dumps(o):
    return json.dumps(o, sort_keys=True, ensure_ascii=False)


def eval_python(c):
    try:
        with open(c.path) as fh:
            src = fh.read()
        prog = parse(src)
        check(prog)
        # G9 A2: the Rust source backend lowers G9 programs (no guard)
        rs_src = gen_rust(prog, verified=c.verified, trust_callers=c.trust, budget=c.budget)
        obj = {"rs": rs_src}
    except UnicodeDecodeError:
        obj = {"adapter_error": "decode"}
    except RecursionError:
        c.status = "py_recursion"
        return
    except PruvError as e:
        obj = {"error": json.loads(e.to_json())}
    except OSError as e:
        c.status, c.note = "py_crash", "OSError: %s" % e
        return
    except Exception as e:   # noqa: BLE001
        obj = {"internal": str(e)}
    try:
        c.py = dumps(obj).encode("utf-8")
    except Exception as e:   # noqa: BLE001  error in the tool itself
        c.status, c.note = "py_crash", "%s: %s" % (type(e).__name__, str(e)[:200])


def run_batch(rs, flags, paths):
    try:
        p = subprocess.run([rs] + flags + paths, capture_output=True, timeout=RS_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "timeout (%d s)" % RS_TIMEOUT
    except OSError as e:
        return None, "failed to start: %s" % e
    tail = p.stderr.decode("utf-8", "replace")[-300:].strip()
    if p.returncode != 0:
        return None, "exit code %d: %s" % (p.returncode, tail)
    out = p.stdout
    if out and not out.endswith(b"\n"):
        return None, "last line has no newline"
    lines = out.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    if len(lines) != len(paths):
        return None, "line count %d != file count %d %s" % (len(lines), len(paths), tail)
    return lines, None


def eval_rust(rs, cases, problems):
    groups = collections.OrderedDict()
    for c in cases:
        if c.status is None:
            groups.setdefault((c.verified, c.trust, c.budget), []).append(c)
    for (v, t, b), lst in groups.items():
        flags = (["--no-verify"] if not v else []) + (["--trust-callers"] if t else []) + ["--budget", str(b)]
        for i in range(0, len(lst), BATCH):
            chunk = lst[i:i + BATCH]
            lines, err = run_batch(rs, flags, [c.path for c in chunk])
            if err is not None:
                for c in chunk:
                    c.status, c.note = "rs_crash", err
                problems.append("%s: mode %s batch %d (%d files, first file %s): %s" % (
                    chunk[0].group, chunk[0].mode, i // BATCH, len(chunk), chunk[0].name, err))
                continue
            for c, line in zip(chunk, lines):
                c.rs = line
                c.status = "same" if line == c.py else "diff"


# ---------------------------------------------------------------------------
# Comparison summary
# ---------------------------------------------------------------------------
def load(line):
    try:
        o = json.loads(line.decode("utf-8"))
        return o if isinstance(o, dict) else None
    except (ValueError, UnicodeDecodeError, RecursionError):
        return None


def text_of(v):
    return v if isinstance(v, str) else dumps(v)


def line_diff(a, b):
    """-> (first differing line number (1-based), list of strings with 3 lines of context on each side)"""
    la, lb = a.split("\n"), b.split("\n")
    n = min(len(la), len(lb))
    i = next((k for k in range(n) if la[k] != lb[k]), n)
    lo, hi = max(0, i - 3), i + 4
    out = ["first differing line: %d (py %d lines, rs %d lines)" % (i + 1, len(la), len(lb))]
    for tag, ls in (("py", la), ("rs", lb)):
        for k in range(lo, min(hi, len(ls))):
            out.append("  %s %5d%s %s" % (tag, k + 1, ">" if k == i else " ", ls[k]))
        if i >= len(ls):
            out.append("  %s (no line %d: end)" % (tag, i + 1))
    return out


def diff_summary(c):
    po, ro = load(c.py), load(c.rs)
    if po is None or ro is None:
        a, b = c.py.decode("utf-8", "replace"), c.rs.decode("utf-8", "replace")
        return ["cannot parse json -> comparing raw lines (py json %s, rs json %s)" % (po is not None, ro is not None)] + line_diff(a, b)
    out = []
    keys = sorted(set(po) | set(ro))
    kinds = []
    for k in keys:
        if k not in po or k not in ro:
            kinds.append("%s present on one side only (py=%s rs=%s)" % (k, k in po, k in ro))
        elif po[k] != ro[k]:
            kinds.append("%s differs" % k)
    out.append("differing fields: " + (", ".join(kinds) if kinds else "(none: serialization order/whitespace difference)"))
    for k in ("rs", "error", "internal", "adapter_error"):
        if k in po and k in ro and po[k] != ro[k]:
            out.append("-- %s --" % k)
            out += line_diff(text_of(po[k]), text_of(ro[k]))
    if not kinds:
        out += line_diff(c.py.decode("utf-8", "replace"), c.rs.decode("utf-8", "replace"))
    return out


def write_bytes(path, data):
    with open(path, "wb") as fh:
        fh.write(data)


def save_case(save_dir, seq, c):
    d = os.path.join(save_dir, c.group, "%04d_%s_%s" % (seq, safe(c.name), safe(c.mode)))
    os.makedirs(d, exist_ok=True)
    with open(c.path, "rb") as fh:
        write_bytes(os.path.join(d, "input.pruv"), fh.read())
    info = ["group: %s" % c.group, "name: %s" % c.name, "mode: %s (verified=%s trust_callers=%s budget=%d)" % (
        c.mode, c.verified, c.trust, c.budget), "status: %s" % c.status]
    for tag, line in (("py", c.py), ("rs", c.rs)):
        o = load(line) if line is not None else None
        if o is None:
            continue
        if isinstance(o.get("rs"), str):
            write_bytes(os.path.join(d, tag + ".rs"), o["rs"].encode("utf-8"))
        else:
            write_bytes(os.path.join(d, tag + ".txt"), line + b"\n")
    if c.status == "diff":
        info += diff_summary(c)
    if c.note:
        info.append("note: " + c.note)
    write_bytes(os.path.join(d, "summary.txt"), ("\n".join(info) + "\n").encode("utf-8"))


# ---------------------------------------------------------------------------
# Coverage
# ---------------------------------------------------------------------------
def coverage(all_cases):
    ok_n = err_n = internal_n = adapter_n = 0
    unchecked = safe_ops = contract = body = reqviol = 0
    for c in all_cases:
        if c.py is None or c.status in ("py_recursion", "py_crash"):
            continue
        o = load(c.py)
        if o is None:
            continue
        if "adapter_error" in o:
            adapter_n += 1
        elif "internal" in o:
            internal_n += 1
        elif "error" in o:
            err_n += 1
        rs_src = o.get("rs")
        if not isinstance(rs_src, str):
            continue
        ok_n += 1
        if c.verified and "get_unchecked" in rs_src:
            unchecked += 1
        if not c.verified and ("pruv_get" in rs_src or "pruv_add" in rs_src):
            safe_ops += 1
        if "pruv_contract__" in rs_src:
            contract += 1
        if "__pruv_body" in rs_src:
            body += 1
        if "pruv: requires violated" in rs_src:
            reqviol += 1
    print("")
    print("== coverage ==")
    print("successful (with rs) cases %d, error cases %d, internal cases %d, decode failures %d" % (ok_n, err_n, internal_n, adapter_n))
    print("get_unchecked cases (verified) %d" % unchecked)
    print("pruv_get/pruv_add cases (safe, verified off) %d" % safe_ops)
    print("pruv_contract__ cases %d" % contract)
    print("__pruv_body cases %d" % body)
    print("'pruv: requires violated' string cases %d" % reqviol)


def default_rs_path():
    base = os.path.join(ROOT, "pruvc-rs", "target", "release", "pruv-rust-dump")
    if not os.path.isfile(base) and os.path.isfile(base + ".exe"):
        return base + ".exe"
    return base


def main(argv):
    ap = argparse.ArgumentParser(prog="diff_rust.py", description="Byte-compare the output of the Python/Rust Rust-source generators")
    ap.add_argument("--rs-path", default=None, help="path to pruv-rust-dump")
    ap.add_argument("--only", default=None, help="group list (comma-separated): " + " ".join(ALL_GROUPS))
    ap.add_argument("--seeds", default="41,56,57", help="fuzzer seed list (comma-separated)")
    ap.add_argument("--fuzz-count", type=int, default=200, help="number of indexes per seed")
    ap.add_argument("--mutations", type=int, default=3, help="number of mutations per file")
    ap.add_argument("--save-dir", default=None, help="directory in which to save differing cases")
    ap.add_argument("--modes", default=None, help="e.g. VT,Vt,vT,vt,B (default: all)")
    args = ap.parse_args(argv)

    args.seeds = [parse_seed(t) for t in args.seeds.split(",") if t.strip() != ""]
    if args.fuzz_count < 0 or args.mutations < 0:
        ap.error("--fuzz-count and --mutations must be >= 0")
    if args.only is None:
        selected = list(ALL_GROUPS)
    else:
        selected = [t.strip() for t in args.only.split(",") if t.strip()]
        bad = [t for t in selected if t not in ALL_GROUPS]
        if bad or not selected:
            ap.error("--only: unknown group %s (valid: %s)" % (bad, " ".join(ALL_GROUPS)))
    if args.modes is None:
        modes = list(ALL_MODES)
    else:
        modes = parse_modes(args.modes)
        if modes is None:
            ap.error("--modes: unknown notation %r (valid: VT Vt vT vt B)" % args.modes)
    rs = os.path.abspath(args.rs_path) if args.rs_path else default_rs_path()
    if not os.path.isfile(rs) or not os.access(rs, os.X_OK):
        print("error: Rust binary not found or not executable: %s\n"
              "  build it first, or pass the pruv-rust-dump path with --rs-path." % rs, file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="diff_rust_") as tmp:
        per, notes = build_inputs(set(selected), args, tmp)
        problems = []
        stats = collections.OrderedDict()
        mode_stats = collections.OrderedDict()
        all_cases, diffs, crashes = [], [], []
        total = collections.Counter()
        for g in ALL_GROUPS:
            if g not in selected:
                continue
            cases = make_cases(g, per[g], modes)
            for c in cases:
                eval_python(c)
            eval_rust(rs, cases, problems)
            st = collections.Counter(c.status for c in cases)
            st["inputs"] = len(per[g])
            st["cases"] = len(cases)
            stats[g] = st
            all_cases.extend(cases)
            for c in cases:
                key = "B" if c.mode.startswith("B") and c.mode != "B" and c.mode[1:].isdigit() else c.mode
                mode_stats.setdefault(key, collections.Counter())[c.status] += 1
                if c.status == "diff":
                    diffs.append(c)
                elif c.status in ("py_crash", "rs_crash"):
                    crashes.append(c)

        saved = 0
        if args.save_dir:
            for c in diffs + [c for c in crashes if c.status == "py_crash"]:
                save_case(args.save_dir, saved, c)
                saved += 1
            if problems:
                os.makedirs(args.save_dir, exist_ok=True)
                write_bytes(os.path.join(args.save_dir, "rs_crash.txt"), ("\n".join(problems) + "\n").encode("utf-8"))

        print("rs: %s" % rs)
        print("modes: %s" % ",".join(modes))
        print("")
        cols = ("inputs", "cases", "same", "diff", "py_recursion", "rs_crash")
        print("%-12s" % "group" + "".join("%14s" % c for c in cols) + "%12s" % "py_crash")
        for g, st in stats.items():
            print("%-12s" % g + "".join("%14d" % st[c] for c in cols) + "%12d" % st["py_crash"])
            total.update(st)
        print("%-12s" % "TOTAL" + "".join("%14d" % total[c] for c in cols) + "%12d" % total["py_crash"])
        print("")
        print("%-12s%10s%10s" % ("mode", "same", "diff"))
        for m, st in mode_stats.items():
            print("%-12s%10d%10d" % (m, st["same"], st["diff"]))
        for n in notes:
            print(n)

        if diffs:
            print("")
            print("== first differing cases (up to %d / %d diff in total) ==" % (MAX_SHOWN, len(diffs)))
            for c in diffs[:MAX_SHOWN]:
                print("[%s] %s  mode %s" % (c.group, c.name, c.mode))
                for ln in diff_summary(c):
                    print("  " + ln)
        pyc = [c for c in crashes if c.status == "py_crash"]
        if pyc:
            print("")
            print("== py_crash (up to 5 / %d in total) ==" % len(pyc))
            for c in pyc[:5]:
                print("[%s] %s %s: %s" % (c.group, c.name, c.mode, c.note))
        if problems:
            print("")
            print("== rs_crash (%d batches, showing up to 5) ==" % len(problems))
            for p in problems[:5]:
                print(p)
        if args.save_dir:
            print("")
            print("saved: %d cases -> %s" % (saved, args.save_dir))

        coverage(all_cases)

    clean = all(total[k] == 0 for k in ("diff", "py_crash", "rs_crash"))
    print("")
    print("result: %s" % ("success (all same)" if clean else "fail"))
    return 0 if clean else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
