# -*- coding: utf-8 -*-
"""Soundness regression measurement: generate the same mutants as bench/mutate.py, compile them (verification + code generation),
and compare the verdicts without --infer and with --infer on both implementations (py, rs).

Verdicts:
  accepted  = exit 0
  rejected  = exit 1, the stage of the first error JSON on stdout is not internal, and the code is not an undecided code
  undecided = exit 1 and the code is inference_timeout or verify_unknown (verdicts that can change with load)
  crash     = anything else (exit 2 usage error, exit 1 without JSON, exit 3 or signal, timeout, failure to run)
New pass = not accepted without inference but accepted with it.
Undecided results are re-run with --retry, one at a time. If still undecided they stay in the result as is (not counted as rejected).
Exit code 1 if there is any crash.

The backend (--backend) is a stage after verification, so it does not affect verdicts (it counts the same verdict twice; it is not independent evidence).
The mutation rules (OPS, SKIP, mutants) are taken directly from the bench/mutate.py source (no copy).

Usage: mutate_infer.py OUT.json SRC_DIR [SRC_DIR ...] [--jobs N] [--backend rust|llvm] [--retry]
"""
import ast, hashlib, json, os, shutil, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, ".venv", "bin", "python")
RS_BIN = os.path.join(ROOT, "pruvc-rs", "target", "release", "pruvc")
COMPILERS = {
    "py": [PY, os.path.join(ROOT, "pruvc", "pruvc.py")],
    "rs": [RS_BIN],
}
UNDECIDED_CODES = ("inference_timeout", "verify_unknown")
RUNS = [(c, inf) for c in ("py", "rs") for inf in (False, True)]


def load_mutants():
    src = open(os.path.join(ROOT, "bench", "mutate.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in ("OPS", "SKIP") for t in n.targets))
            or (isinstance(n, ast.FunctionDef) and n.name == "mutants")]
    ns = {"re": __import__("re")}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "mutate.py", "exec"), ns)
    return ns["mutants"]


def classify(rc, stdout):
    errs = []
    for l in stdout.splitlines():
        if l.startswith("{"):
            try:
                errs.append(json.loads(l))
            except ValueError:
                pass
    code = errs[0].get("code") if errs else None
    if rc == 0:
        return "accepted", code
    if rc == 1 and errs:
        if errs[0].get("stage") == "internal":
            return "crash", code
        # undecided only if every error is an undecided code (rejected if any is a real rejection)
        und = all(e.get("code") in UNDECIDED_CODES for e in errs)
        return ("undecided" if und else "rejected"), code
    return "crash", code


def verify(comp, path, backend, infer):
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="mi_") as d:
        argv = COMPILERS[comp] + [path, "-o", os.path.join(d, "out"), "--backend", backend]
        if infer:
            argv.append("--infer")
        try:
            p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        except subprocess.TimeoutExpired:
            return {"verdict": "crash", "code": "timeout", "sec": round(time.time() - t0, 2)}
        except OSError as e:
            return {"verdict": "crash", "code": "spawn: %s" % e, "sec": round(time.time() - t0, 2)}
        v, code = classify(p.returncode, p.stdout)
        r = {"verdict": v, "code": code, "sec": round(time.time() - t0, 2)}
        if v == "crash":
            r["rc"] = p.returncode
            r["stderr_tail"] = p.stderr.strip()[-300:]
        return r


def key(c, inf):
    return "%s_%s" % (c, "infer" if inf else "plain")


def versions():
    head = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", ROOT, "status", "--porcelain", "--", "pruvc", "pruvc-rs/crates",
                                 "pruvc-rs/Cargo.lock"],
                                capture_output=True, text=True).stdout.strip())
    sha = hashlib.sha256(open(RS_BIN, "rb").read()).hexdigest() if os.path.exists(RS_BIN) else None
    z3py = subprocess.run([PY, "-c", "import z3; print(z3.get_version_string())"], capture_output=True,
                          text=True).stdout.strip()
    lock = open(os.path.join(ROOT, "pruvc-rs", "Cargo.lock"), encoding="utf-8").read()
    z3src = None
    if 'name = "z3-src"' in lock:
        z3src = lock.split('name = "z3-src"', 1)[1].split("version = ", 1)[1].split("\n", 1)[0].strip('"')
    return {"git_head": head, "z3_python": z3py, "z3_src_crate": z3src, "compiler_sources_dirty": dirty, "rs_binary_sha256": sha,
            "rs_binary_mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(RS_BIN)))
            if sha else None}


def main():
    args = sys.argv[1:]
    jobs_n, backend, retry = 6, "rust", False
    if "--jobs" in args:
        i = args.index("--jobs"); jobs_n = int(args[i + 1]); del args[i:i + 2]
    if "--backend" in args:
        i = args.index("--backend"); backend = args[i + 1]; del args[i:i + 2]
    if "--retry" in args:
        args.remove("--retry"); retry = True
    out, dirs = args[0], args[1:]
    tags = [os.path.basename(os.path.normpath(d)) for d in dirs]
    if len(set(tags)) != len(tags):
        sys.exit("input folder names (basename) collide: %s" % tags)
    mutants = load_mutants()
    work = tempfile.mkdtemp(prefix="mi_src_")
    try:
        items = []
        for d, tag in zip(dirs, tags):
            for f in sorted(os.listdir(d)):
                if not f.endswith(".pruv"):
                    continue
                pid = os.path.splitext(f)[0]
                for n, (ln, old, new, text) in enumerate(mutants(open(os.path.join(d, f), encoding="utf-8").read())):
                    p = os.path.join(work, "%s_%s_%03d.pruv" % (tag, pid, n))
                    open(p, "w", encoding="utf-8").write(text)
                    items.append({"set": tag, "pid": pid, "line": ln, "from": old, "to": new, "file": p})
        print("mutants:", len(items), flush=True)

        def run(t):
            i, c, inf = t
            return t, verify(c, items[i]["file"], backend, inf)

        tasks = [(i, c, inf) for i in range(len(items)) for c, inf in RUNS]
        with ThreadPoolExecutor(jobs_n) as ex:
            for (i, c, inf), r in ex.map(run, tasks):
                items[i][key(c, inf)] = r
        retried = 0
        if retry:
            again = [(i, c, inf) for i in range(len(items)) for c, inf in RUNS
                     if items[i][key(c, inf)]["verdict"] == "undecided"]
            retried = len(again)
            for t in again:  # one at a time
                (i, c, inf), r = run(t)
                r["first"] = items[i][key(c, inf)]
                items[i][key(c, inf)] = r
    finally:
        shutil.rmtree(work, ignore_errors=True)

    def count(c, k, v):
        return sum(it[key(c, k)]["verdict"] == v for it in items)

    summary = {"command": " ".join(sys.argv[1:]), "versions": versions(), "retried_undecided": retried}
    for c in ("py", "rs"):
        summary[c] = {
            "plain": {v: count(c, False, v) for v in ("accepted", "rejected", "undecided", "crash")},
            "infer": {v: count(c, True, v) for v in ("accepted", "rejected", "undecided", "crash")},
            "new_pass": [(it["set"], it["pid"], it["line"], it["to"]) for it in items
                         if it[key(c, False)]["verdict"] != "accepted" and it[key(c, True)]["verdict"] == "accepted"],
            "lost_pass": [(it["set"], it["pid"], it["line"], it["to"]) for it in items
                          if it[key(c, False)]["verdict"] == "accepted" and it[key(c, True)]["verdict"] != "accepted"],
            "undecided": [(it["set"], it["pid"], it["line"], it["to"], k) for it in items for k in ("plain", "infer")
                          if it["%s_%s" % (c, k)]["verdict"] == "undecided"],
        }
    summary["py_rs_verdict_diff"] = [(it["set"], it["pid"], it["line"], k) for it in items for k in ("plain", "infer")
                                     if it["py_" + k]["verdict"] != it["rs_" + k]["verdict"]]
    for it in items:
        it.pop("file")
    json.dump({"summary": summary, "items": items}, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if any(it[key(c, k)]["verdict"] == "crash" for it in items for c, k in RUNS):
        sys.exit(1)


if __name__ == "__main__":
    main()
