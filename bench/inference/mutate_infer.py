# -*- coding: utf-8 -*-
"""건전성 회귀 측정: bench/mutate.py 와 같은 변이를 만들어 검증기만 돌리고,
--infer 없음과 --infer 켬의 판정을 두 판(py·rs)에서 비교한다.

새 통과 = 추론 없음에서 거부(rejected)인데 --infer 에서 통과(accepted)한 변이.
변이 규칙(OPS·SKIP·mutants)은 bench/mutate.py 소스에서 그대로 가져온다(사본 없음).

사용: mutate_infer.py OUT.json SRC_DIR [SRC_DIR ...] [--jobs N] [--backend rust|llvm]
"""
import ast, json, os, subprocess, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PY = os.path.join(ROOT, ".venv", "bin", "python")
COMPILERS = {
    "py": [PY, os.path.join(ROOT, "pruvc", "pruvc.py")],
    "rs": [os.path.join(ROOT, "pruvc-rs", "target", "release", "pruvc")],
}


def load_mutants():
    src = open(os.path.join(ROOT, "bench", "mutate.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in ("OPS", "SKIP") for t in n.targets))
            or (isinstance(n, ast.FunctionDef) and n.name == "mutants")]
    ns = {"re": __import__("re")}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "mutate.py", "exec"), ns)
    return ns["mutants"]


def verify(comp, path, backend, infer):
    d = tempfile.mkdtemp(prefix="mi_")
    argv = COMPILERS[comp] + [path, "-o", os.path.join(d, "out"), "--backend", backend]
    if infer:
        argv.append("--infer")
    t0 = time.time()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        return {"verdict": "timeout", "code": None, "sec": round(time.time() - t0, 2)}
    errs = [json.loads(l) for l in p.stdout.splitlines() if l.startswith("{")]
    if p.returncode == 0:
        v = "accepted"
    elif p.returncode in (1, 2):
        v = "rejected"
    else:
        v = "crash"
    return {"verdict": v, "code": errs[0].get("code") if errs else None, "sec": round(time.time() - t0, 2)}


def main():
    args = sys.argv[1:]
    jobs_n, backend = 6, "rust"
    if "--jobs" in args:
        i = args.index("--jobs"); jobs_n = int(args[i + 1]); del args[i:i + 2]
    if "--backend" in args:
        i = args.index("--backend"); backend = args[i + 1]; del args[i:i + 2]
    out, dirs = args[0], args[1:]
    mutants = load_mutants()
    work = tempfile.mkdtemp(prefix="mi_src_")
    items = []
    for d in dirs:
        tag = os.path.basename(os.path.normpath(d))
        for f in sorted(os.listdir(d)):
            if not f.endswith(".pruv"):
                continue
            pid = os.path.splitext(f)[0]
            for n, (ln, old, new, text) in enumerate(mutants(open(os.path.join(d, f), encoding="utf-8").read())):
                p = os.path.join(work, "%s_%s_%03d.pruv" % (tag, pid, n))
                open(p, "w", encoding="utf-8").write(text)
                items.append({"set": tag, "pid": pid, "line": ln, "from": old, "to": new, "file": p})
    print("mutants:", len(items), flush=True)
    tasks = [(i, c, inf) for i in range(len(items)) for c in ("py", "rs") for inf in (False, True)]

    def run(t):
        i, c, inf = t
        return t, verify(c, items[i]["file"], backend, inf)

    with ThreadPoolExecutor(jobs_n) as ex:
        for (i, c, inf), r in ex.map(run, tasks):
            items[i]["%s_%s" % (c, "infer" if inf else "plain")] = r
    summary = {}
    for c in ("py", "rs"):
        new_pass = [it for it in items
                    if it[c + "_plain"]["verdict"] != "accepted" and it[c + "_infer"]["verdict"] == "accepted"]
        lost = [it for it in items
                if it[c + "_plain"]["verdict"] == "accepted" and it[c + "_infer"]["verdict"] != "accepted"]
        summary[c] = {
            "plain_accepted": sum(it[c + "_plain"]["verdict"] == "accepted" for it in items),
            "infer_accepted": sum(it[c + "_infer"]["verdict"] == "accepted" for it in items),
            "new_pass": [(it["set"], it["pid"], it["line"], it["to"]) for it in new_pass],
            "lost_pass": [(it["set"], it["pid"], it["line"], it["to"]) for it in lost],
            "crash_or_timeout": sum(it[c + k]["verdict"] in ("crash", "timeout") for it in items for k in ("_plain", "_infer")),
        }
    diff = [(it["set"], it["pid"], it["line"]) for it in items
            if any(it["py" + k]["verdict"] != it["rs" + k]["verdict"] for k in ("_plain", "_infer"))]
    summary["py_rs_verdict_diff"] = diff
    for it in items:
        it.pop("file")
    json.dump({"summary": summary, "items": items}, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
