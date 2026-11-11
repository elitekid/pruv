# -*- coding: utf-8 -*-
"""건전성 회귀 측정: bench/mutate.py 와 같은 변이를 만들어 컴파일(검증+코드 생성)을 돌리고,
--infer 없음과 --infer 켬의 판정을 두 판(py·rs)에서 비교한다.

판정:
  accepted  = 종료 0
  rejected  = 종료 1 이고 stdout 첫 오류 JSON 의 stage 가 internal 이 아니며 code 가 미결 코드가 아님
  undecided = 종료 1 이고 code 가 inference_timeout·verify_unknown (부하에 따라 바뀔 수 있는 판정)
  crash     = 그 밖(종료 2 사용법 오류, JSON 없는 종료 1, 종료 3·신호, 시간 초과, 실행 실패)
새 통과 = 없음에서 accepted 가 아닌데 켬에서 accepted.
미결은 --retry 로 병렬 1개로 다시 돌린다. 그래도 미결이면 결과에 그대로 남긴다(거부로 세지 않음).
crash 가 하나라도 있으면 종료 코드 1.

뒷단(--backend)은 검증 뒤 단계라 판정에 영향이 없다(같은 판정을 두 번 세는 것이지 독립 증거가 아님).
변이 규칙(OPS·SKIP·mutants)은 bench/mutate.py 소스에서 그대로 가져온다(사본 없음).

사용: mutate_infer.py OUT.json SRC_DIR [SRC_DIR ...] [--jobs N] [--backend rust|llvm] [--retry]
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
        # 오류가 모두 미결 코드일 때만 미결(하나라도 진짜 거부가 있으면 거부)
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
        sys.exit("입력 폴더 이름(basename)이 겹친다: %s" % tags)
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
            for t in again:  # 병렬 1개
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
