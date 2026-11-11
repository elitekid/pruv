"""Test-only adapter for the Python Pruv compiler (outside the public CLI contract).

  diff_py_adapter.py parse FILE
  diff_py_adapter.py check FILE
  diff_py_adapter.py trace FILE [--no-verify] [--trust-callers] [--contract-budget N] [--infer]
  diff_py_adapter.py snapshot --out DIR [--inputs manifest|all] [--python PATH]
  diff_py_adapter.py seeds --out DIR [--inputs manifest|all] [--python PATH]
  diff_py_adapter.py _all FILE [flags]      (internal: parse+check+trace in ONE process)

Only --no-verify, --trust-callers, --contract-budget N, --infer are known trace options; anything else
-> stderr "diff_py_adapter: unknown option(s): ..." and exit code 2.
--infer (STAGE1 B2, docs/STAGE1_B_INFER.md): options {"infer": true, "no_verify": ...}; verification runs with template
invariant inference, so the exploration queries (phase "inference", round r, cand set) and the final
queries are all in "obligations"; the top-level key "inference" holds the per-loop report records (the
--show-inferred lines, same objects). Without --infer there is no "inference" key.

Trace schema "pruv-trace-v2" (one JSON object):
  schema, options {"infer": bool, "no_verify": bool} (no_verify true iff --no-verify; with it obligations is [],
  there is no timeout_ms, and with --infer inference is []; --trust-callers/--contract-budget are not recorded), errors [error dicts], obligations [...], timeout_ms (only if verification ran),
  inference (only with --infer: list of per-loop report records)
  obligation: seq, fn, line, col, code, attempts [...], phase ("verification"|...), round (int|null),
              cand (null|candidate id), and "skipped": true only when the (line,col,code[,extra]) key was
              already reported (then attempts is empty)
  attempt:    lemmas (bool: aggregate lemmas included), smt2 (exact text sent: set-option lines + sexpr),
              result ("sat"|"unsat"|"unknown"|"error"), status ("proved"|"not_proved"|"timeout"|
              "resource_unknown"|"error"), timeout_ms, rlimit (int|null), seed (int|null),
              reason_unknown (str|null)
Recording is done by verify.TraceRecorder (official query boundary in verify.py), no monkey patching.

All JSON is written with sort_keys=True, ensure_ascii=False, UTF-8, to stdout / files.
AST test schema "pruv-ast-v1": integers are decimal strings, None is null, list order is kept.
A language error is reported as {"schema":..., "error": {...}} with exit code 0; any adapter
failure (unknown node, internal bug) is an uncaught exception, i.e. a non-zero exit.
Only the standard library and the repository's pruvc modules are imported.
"""
import argparse
import concurrent.futures
import dataclasses
import glob
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SELF = os.path.abspath(__file__)
sys.path.insert(0, os.path.join(ROOT, "pruvc"))

import vast  # noqa: E402
from vast import PruvError  # noqa: E402
from vparser import parse as pruv_parse  # noqa: E402
import check as check_mod  # noqa: E402
from typeinfo import format_type  # noqa: E402
from foreign import g6_unimplemented_error  # noqa: E402

AST_SCHEMA = "pruv-ast-v1"
PROCESS_TIMEOUT = 300

# ---------------------------------------------------------------------------
# AST schema v1: every concrete node of vast.py with its fields (excluding line/col).
# A mismatch with vast.py (new/removed/changed node) raises at first use.
# ---------------------------------------------------------------------------
NODE_FIELDS = {
    # expressions
    "IntLit": ("value", "ty"),
    "BoolLit": ("value", "ty"),
    "StrLit": ("value", "ty"),   # G2 B0: value = UTF-8 bytes, serialized as lowercase hex
    "Var": ("name", "ty"),
    "Unary": ("op", "operand", "ty"),
    "Binary": ("op", "left", "right", "ty"),
    "Call": ("name", "args", "ty"),
    "Index": ("array", "index", "ty"),
    "Ctor": ("name", "arg", "ty"),
    "Quant": ("kind", "var", "lo", "hi", "body", "ty"),
    "StructLit": ("name", "fields", "ty"),
    "EnumCtor": ("enum_name", "variant", "args", "ty"),
    "FieldAccess": ("base", "field", "ty"),
    "IsVariant": ("value", "enum_name", "variant", "ty"),
    "VariantField": ("value", "enum_name", "variant", "field", "ty"),
    "Move": ("name", "ty"),      # G6 A0: `move name`
    # declarations and helper nodes
    "FieldDecl": ("name", "type"),
    "VariantDecl": ("name", "fields"),
    "StructDecl": ("name", "fields"),
    "EnumDecl": ("name", "variants"),
    "FieldInit": ("name", "value"),
    "MatchArm": ("enum_name", "ctor", "binders", "body"),
    "Param": ("name", "type"),
    "Function": ("name", "params", "ret", "effects", "requires", "ensures", "body"),
    "Program": ("functions", "types"),
    # statements
    "Let": ("name", "mutable", "type", "value"),
    "Assign": ("name", "value"),
    "IndexAssign": ("name", "index", "value"),
    "If": ("cond", "then", "els"),
    "While": ("cond", "invariants", "decreases", "body"),
    "Return": ("value",),
    "Assert": ("cond",),
    "ExprStmt": ("expr",),
    "FieldAssign": ("name", "fields", "value"),
    "Match": ("scrutinee", "arms"),
}
# STAGE1 A (refinement types). New node and optional keys: an optional key is written ONLY when its value
# is not None, so the dump of an input without refinements is byte-identical to before.
#   Refinement: shape "scalar"|"array", base (written base type name), lo/hi (decimal strings or null),
#               maxlen (decimal string or null); line/col = first token of the annotated type
#   Param.refine, Let.refine, Function.ret_refine: a Refinement node
#   Assert.origin_code / origin_what: set only on assertions synthesized by refine.py (check dump only)
#   IndexAssign.elem_refine: [lo, hi, origin_what] (decimal strings), only on a store into a refined array
#               with an element range (check dump only)
NODE_FIELDS["Refinement"] = ("shape", "base", "lo", "hi", "maxlen")
OPTIONAL_FIELDS = {
    "Param": ("refine",),
    "Function": ("ret_refine",),
    "Let": ("refine",),
    "Assert": ("origin_code", "origin_what"),
    "IndexAssign": ("elem_refine",),
}
# abstract bases / value types of vast.py that are not nodes
_NON_NODES = {"Type", "Expr", "Stmt", "TypeDecl"}
_checked = []


def _verify_schema():
    if _checked:
        return
    actual = {}
    for name, obj in vars(vast).items():
        if isinstance(obj, type) and dataclasses.is_dataclass(obj) and obj.__module__ == vast.__name__ \
                and name not in _NON_NODES:
            actual[name] = tuple(f.name for f in dataclasses.fields(obj) if f.name not in ("line", "col"))
    if set(actual) != set(NODE_FIELDS):
        raise RuntimeError("vast.py nodes differ from adapter schema: only in vast=%s only in adapter=%s" % (
            sorted(set(actual) - set(NODE_FIELDS)), sorted(set(NODE_FIELDS) - set(actual))))
    for name, flds in actual.items():
        want = tuple(NODE_FIELDS[name]) + tuple(OPTIONAL_FIELDS.get(name, ()))
        if set(flds) != set(want):
            raise RuntimeError("fields of %s differ: vast=%s adapter=%s" % (name, flds, want))
    _checked.append(True)


def tyname(t):
    """a Type as printed in the dumps: a legacy type keeps its internal name (as before G3); a structured type
    (type arguments or a bound parameter) uses the shared A0 source formatting, e.g. "Pair<i64, bool>", "[T]", "T"."""
    if t.args or t.owner is not None:
        return format_type(t)
    return t.name


# G3 A1: optional extras, written ONLY when present, so the dump of a program without G3 syntax is byte-identical
#   tparams (Function / StructDecl / EnumDecl): list of {"kind": "TypeParam", line, col, name, bound (string|null)}
#   targs (Call / StructLit / EnumCtor / Ctor): the explicit type arguments as written (list of type strings)
#   inst  (same four nodes, check dump only): {"decl", "args", "subst": [{"index": "i", "owner", "type"}]}
#   enum_ty (IsVariant / VariantField, check dump only): the instantiated enum type, only when it has type arguments
def _g3_extras(v, out):
    tps = getattr(v, "tparams", ())
    if tps:
        out["tparams"] = [{"kind": "TypeParam", "line": str(tp.line), "col": str(tp.col), "name": tp.name,
                           "bound": tp.bound} for tp in tps]
    ta = getattr(v, "targs", None)
    if ta is not None:
        out["targs"] = [tyname(t) for t in ta]
    inst = getattr(v, "inst", None)
    if inst is not None:
        out["inst"] = {"decl": inst["decl"], "args": [tyname(t) for t in inst["args"]],
                       "subst": [{"index": str(i), "owner": o, "type": tyname(t)}
                                 for (o, i), t in inst["subst"].items()]}
    et = getattr(v, "enum_ty", None)
    if et is not None and et.args:
        out["enum_ty"] = tyname(et)
    # G6 A0, written only when present: Param.take (true) and Function.foreign
    # ({"path", "line", "col"} of the path string token; the body is [])
    if getattr(v, "take", False):
        out["take"] = True
    fo = getattr(v, "foreign", None)
    if fo is not None:
        out["foreign"] = {"path": fo["path"], "line": str(fo["line"]), "col": str(fo["col"])}


def ser(v):
    """serialize one value (node, Type, list, scalar); unknown things raise"""
    if v is None or isinstance(v, (str, bool)):
        return v
    if isinstance(v, int):
        return str(v)
    if isinstance(v, bytes):
        return v.hex()   # G2 B0: StrLit.value, lowercase hex (empty -> "")
    if isinstance(v, list):
        return [ser(x) for x in v]
    if isinstance(v, vast.Type):
        return tyname(v)
    name = type(v).__name__
    if name not in NODE_FIELDS or not dataclasses.is_dataclass(v):
        raise RuntimeError("adapter: unknown AST value %r (%s)" % (v, name))
    out = {"kind": name}
    if hasattr(v, "line"):
        out["line"] = ser(v.line)
        out["col"] = ser(v.col)
    for f in NODE_FIELDS[name]:
        out[f] = ser(getattr(v, f))
    for f in OPTIONAL_FIELDS.get(name, ()):
        x = getattr(v, f)
        if x is not None:
            out[f] = ser(x)
    _g3_extras(v, out)
    return out


def err_dict(e):
    return json.loads(e.to_json())


def internal_err(e):
    return {"stage": "internal", "line": 0, "col": 0, "code": "internal_error", "message": str(e), "fix": ""}


def read_source(path):
    return open(path, encoding="utf-8").read()   # same as pruvc.compile_file


# ---------------------------------------------------------------------------
# parse / check
# ---------------------------------------------------------------------------
def parse_result(path):
    _verify_schema()
    try:
        prog = pruv_parse(read_source(path))
    except PruvError as e:
        return {"schema": AST_SCHEMA, "error": err_dict(e)}
    return {"schema": AST_SCHEMA, "program": ser(prog)}


def type_table_json(tt):
    out = []
    for d in tt.order:
        out.append({"name": d.name, "kind": "struct" if isinstance(d, vast.StructDecl) else "enum",
                    "deps": tt._deps(d)})
    return {"order": [x["name"] for x in out], "entries": out}


def check_result(path, externs=()):
    """typed AST: the checker stores each expression's type in the `ty` attribute (Expr.ty)
    externs: --rust-extern crate names (G6)"""
    _verify_schema()
    try:
        prog = pruv_parse(read_source(path))
        c = check_mod.Checker(prog, externs)
        c.run()
    except PruvError as e:
        return {"schema": AST_SCHEMA, "error": err_dict(e)}
    return {"schema": AST_SCHEMA, "program": ser(prog), "type_table": type_table_json(c.tt)}


# ---------------------------------------------------------------------------
# trace
# ---------------------------------------------------------------------------
def trace_result(path, verify_on=True, infer=False, externs=()):
    errors = []
    rec = None
    out = {"schema": "pruv-trace-v2", "options": {"infer": bool(infer), "no_verify": not verify_on},
           "errors": errors, "obligations": []}
    rep = None
    if infer:
        rep = []
        out["inference"] = rep
    try:
        prog = pruv_parse(read_source(path))
        check_mod.check(prog, externs)
        # G6 A1: no guard here; G6 programs get real traces (G6_SPEC 11.1)
        if verify_on:
            import verify
            rec = verify.TraceRecorder()
            out["obligations"] = rec.obligations
            out["timeout_ms"] = verify.TIMEOUT_MS
            if infer:
                errs = verify.verify_program(prog, rec=rec, infer=True, report=rep)
            else:
                errs = verify.verify_program(prog, rec=rec)
            errors.extend(err_dict(e) for e in errs)
    except PruvError as e:
        errors.append(err_dict(e))
    except Exception as e:   # like pruvc.main: compiler-internal failure
        errors.append(internal_err(e))
    return out


# ---------------------------------------------------------------------------
# helpers: python selection, hashing, subprocess
# ---------------------------------------------------------------------------
def pick_python(explicit=None):
    """default sys.executable; PRUV_PYTHON or --python override; the literal 'venv' selects
    ROOT/.venv/bin/python or ROOT/.venv/Scripts/python.exe (Windows) when present"""
    want = explicit or os.environ.get("PRUV_PYTHON")
    if want and want != "venv":
        return want
    if want == "venv":
        for rel in (".venv/bin/python", ".venv/Scripts/python.exe"):
            p = os.path.join(ROOT, rel)
            if os.path.exists(p):
                return p
    return sys.executable


def dumps(o, indent=None):
    return json.dumps(o, sort_keys=True, ensure_ascii=False, indent=indent)


def emit(o):
    sys.stdout.buffer.write((dumps(o) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    with open(p, "rb") as fh:
        return sha256_bytes(fh.read())


def run_child(argv, env=None):
    """argv list only (no shell). Returns (status, parsed_json_or_None, info)"""
    try:
        p = subprocess.run(argv, capture_output=True, timeout=PROCESS_TIMEOUT, env=env)
    except subprocess.TimeoutExpired:
        return "process_timeout", None, {}
    info = {"returncode": p.returncode}
    if p.returncode != 0:
        info["stderr_tail"] = p.stderr.decode("utf-8", "replace")[-400:]
        return "process_error", None, info
    try:
        return "ok", json.loads(p.stdout.decode("utf-8")), info
    except ValueError:
        info["stderr_tail"] = "unparseable stdout: " + p.stdout.decode("utf-8", "replace")[:200]
        return "process_error", None, info


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------
def _rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, "/")


def _tag(flags):
    if not flags:
        return "default"
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", "-".join(f.lstrip("-") for f in flags))


def discover(mode):
    """[(relative path, flags list)] in a fixed order"""
    items = []
    for sub in ("tests/must_reject", "examples"):
        for p in sorted(glob.glob(os.path.join(ROOT, sub, "*.pruv"))):
            items.append((_rel(p), []))
    for p in sorted(glob.glob(os.path.join(ROOT, "tests/runtime/*.pruv"))):
        spec, jf = {}, os.path.splitext(p)[0] + ".json"
        if os.path.exists(jf):
            with open(jf, encoding="utf-8") as fh:
                spec = json.load(fh)
        rows = spec.get("flags_matrix") or [[]]
        for row in rows:
            if isinstance(row, dict):
                row = row.get("flags", [])
            flags = [str(x) for x in row]
            if "contract_budget" in spec:
                flags = flags + ["--contract-budget", str(spec["contract_budget"])]
            items.append((_rel(p), flags))
    for p in sorted(glob.glob(os.path.join(ROOT, "bench/solutions/pruv_agg/*.pruv"))):
        items.append((_rel(p), []))
    if mode == "all":
        have = set(r for r, _ in items)
        for top in ("tests", "bench"):
            for dp, dns, fns in os.walk(os.path.join(ROOT, top)):
                dns.sort()
                for fn in sorted(fns):
                    if fn.endswith(".pruv"):
                        r = _rel(os.path.join(dp, fn))
                        if r not in have:
                            have.add(r)
                            items.append((r, []))
    return items


def _out_name(rel, flags, used):
    base = rel.replace("/", "__") + "." + _tag(flags)
    name, i = base, 2
    while name in used:
        name = "%s_%d" % (base, i)
        i += 1
    used.add(name)
    return name + ".json"


def snapshot_one(py, rel, flags):
    argv = [py, SELF, "_all", os.path.join(ROOT, *rel.split("/"))] + list(flags)
    status, data, info = run_child(argv)
    res = {"input": rel, "flags": list(flags), "status": status}
    if status == "ok":
        res.update(data)
    else:
        res.update(info)
    return res


def cmd_snapshot(out_dir, mode, py):
    os.makedirs(out_dir, exist_ok=True)
    items = discover(mode)
    used, names = set(), []
    for rel, flags in items:
        names.append(_out_name(rel, flags, used))
    workers = max(1, os.cpu_count() or 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda it: snapshot_one(py, it[0], it[1]), items))   # input order
    entries = []
    for (rel, flags), name, res in zip(items, names, results):
        data = (dumps(res, indent=1) + "\n").encode("utf-8")
        with open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(data)
        entries.append({"path": rel, "flags": flags,
                        "input_sha256": sha256_file(os.path.join(ROOT, *rel.split("/"))),
                        "result_file": name, "result_sha256": sha256_bytes(data), "status": res["status"]})
    try:
        import z3
        z3v = z3.get_full_version()
    except Exception as e:
        z3v = "unavailable: %s" % e
    body = {"schema": "pruv-snapshot-v1", "inputs_mode": mode, "python": sys.version, "z3": z3v,
            "child_python": py, "pythonhashseed": os.environ.get("PYTHONHASHSEED"), "inputs": entries}
    body["manifest_sha256"] = sha256_bytes(dumps(body).encode("utf-8"))
    with open(os.path.join(out_dir, "manifest.json"), "wb") as fh:
        fh.write((dumps(body, indent=1) + "\n").encode("utf-8"))
    bad = [e for e in entries if e["status"] != "ok"]
    print("snapshot: %d inputs, %d not ok (process_timeout/process_error) -> %s" % (len(entries), len(bad), out_dir))
    return 0


# ---------------------------------------------------------------------------
# seeds
# ---------------------------------------------------------------------------
def _digest(res):
    tr = res.get("trace") or {}
    errs = [[e.get("stage"), e.get("line"), e.get("col"), e.get("code"), e.get("message")]
            for e in tr.get("errors", [])]
    keys = [[o["seq"], o["fn"], o["line"], o["col"], o["code"], bool(o.get("skipped"))]
            for o in tr.get("obligations", [])]
    smt = [[a["smt2"] for a in o["attempts"]] for o in tr.get("obligations", [])]
    rs = [[a["result"] for a in o["attempts"]] for o in tr.get("obligations", [])]
    return {"status": res.get("status"), "ast": [res.get("parse"), res.get("check")],
            "errors": errs, "keys": keys, "smt2": smt, "results": rs}


def _classify(a, b):
    """set of difference kinds between two result digests"""
    kinds = set()
    for k in ("status", "ast", "errors", "keys"):
        if a[k] != b[k]:
            kinds.add(k)
    if a["smt2"] != b["smt2"]:
        kinds.add("smt2")
    if a["results"] != b["results"]:
        kinds.add("result")
    return kinds


def cmd_seeds(out_dir, mode, py):
    os.makedirs(out_dir, exist_ok=True)
    seeds = ["0", "1", "2", "random"]
    for v in seeds:
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = v
        argv = [py, SELF, "snapshot", "--out", os.path.join(out_dir, "seed_" + v),
                "--inputs", mode, "--python", py]
        p = subprocess.run(argv, env=env, capture_output=True)   # no shell; snapshot has its own timeouts
        if p.returncode != 0:
            sys.stderr.write(p.stderr.decode("utf-8", "replace"))
            raise SystemExit("seeds: snapshot for PYTHONHASHSEED=%s failed (exit %d)" % (v, p.returncode))

    def load(v):
        d = os.path.join(out_dir, "seed_" + v)
        with open(os.path.join(d, "manifest.json"), encoding="utf-8") as fh:
            man = json.load(fh)
        out = {}
        for e in man["inputs"]:
            with open(os.path.join(d, e["result_file"]), encoding="utf-8") as fh:
                out[e["result_file"]] = _digest(json.load(fh))
        return out

    loaded = dict((v, load(v)) for v in seeds)
    base = loaded[seeds[0]]
    differing, per_input = [], {}
    smt2_only = result_only = 0
    for name in sorted(base):
        diffs = {}
        for v in seeds[1:]:
            other = loaded[v].get(name)
            kinds = {"missing"} if other is None else _classify(base[name], other)
            if kinds:
                diffs[v] = sorted(kinds)
        if diffs:
            differing.append(name)
            per_input[name] = diffs
            allk = set(k for ks in diffs.values() for k in ks)
            if allk == {"smt2"}:
                smt2_only += 1
            elif allk == {"result"}:
                result_only += 1
    for v in seeds[1:]:
        for name in sorted(set(loaded[v]) - set(base)):
            differing.append(name)
            per_input[name] = {v: ["extra"]}
    report = {"seeds": seeds, "baseline": seeds[0], "inputs": len(base), "identical": len(base) - len(
        [n for n in differing if n in base]), "different": differing, "differences": per_input,
        "smt2_only": smt2_only, "result_only": result_only,
        "note": "result differences may come from the 8 s solver timeout (load/timing), counted separately"}
    with open(os.path.join(out_dir, "seeds_report.json"), "wb") as fh:
        fh.write((dumps(report, indent=1) + "\n").encode("utf-8"))
    print("seeds: inputs=%d identical=%d different=%d smt2_only=%d result_only=%d" % (
        report["inputs"], report["identical"], len(differing), smt2_only, result_only))
    for n in differing:
        print("  differs: %s %s" % (n, per_input[n]))
    return 1 if differing else 0


# ---------------------------------------------------------------------------
def _extern_names(a):
    return tuple(x.partition("=")[0] for x in getattr(a, "rust_extern", []))


def main(argv):
    ap = argparse.ArgumentParser(prog="diff_py_adapter.py", allow_abbrev=False)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("parse", "check", "trace", "_all"):
        p = sub.add_parser(n, allow_abbrev=False)
        p.add_argument("file")
        if n in ("check", "trace", "_all"):
            p.add_argument("--rust-extern", action="append", default=[])   # G6: NAME=PATH, only NAME is used
        if n in ("trace", "_all"):
            # the only known trace options; trust-callers / contract-budget do not change the proof
            p.add_argument("--no-verify", action="store_true")
            p.add_argument("--trust-callers", action="store_true")
            p.add_argument("--contract-budget", default=None)
            p.add_argument("--infer", action="store_true")
    for n in ("snapshot", "seeds"):
        p = sub.add_parser(n)
        p.add_argument("--out", required=True)
        p.add_argument("--inputs", choices=["manifest", "all"], default="manifest")
        p.add_argument("--python", default=None)
    a, extra = ap.parse_known_args(argv)
    if a.cmd in ("parse", "check"):
        if extra:
            ap.error("unexpected arguments: %s" % extra)
        emit(parse_result(a.file) if a.cmd == "parse" else check_result(a.file, _extern_names(a)))
        return 0
    if a.cmd in ("trace", "_all"):
        if extra:
            sys.stderr.write("diff_py_adapter: unknown option(s): %s\n" % " ".join(extra))
            return 2
        ext = _extern_names(a)
        if a.cmd == "trace":
            emit(trace_result(a.file, not a.no_verify, a.infer, ext))
        else:
            emit({"schema": "pruv-snapshot-item-v1", "parse": parse_result(a.file),
                  "check": check_result(a.file, ext), "trace": trace_result(a.file, not a.no_verify, a.infer, ext)})
        return 0
    if extra:
        ap.error("unexpected arguments: %s" % extra)
    py = pick_python(a.python)
    if a.cmd == "snapshot":
        return cmd_snapshot(a.out, a.inputs, py)
    return cmd_seeds(a.out, a.inputs, py)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
