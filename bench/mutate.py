"""Mutation test: inject small bugs into code lines of Pruv solutions.
For each mutant: (1) does Pruv's verifier reject it?  (2) does the same code, compiled to
Rust without verification (what rustc alone would accept), fail the tests?
crash = 종료 코드 0·1·2 밖(exit 3·101 panic 등)·신호 종료·실행 실패·시간 초과(이전엔 exit 3만)"""
import json, os, re, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness"))
import run as H
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))
import compiler_driver as CD

# --compiler py|rs / --compiler-path PATH: take them off argv, hand the Driver to the harness module
# so H.build_and_run and every compiler call here share one selection.
DRIVER = CD.from_argv(sys.argv)
H.DRIVER = DRIVER
SRC = sys.argv[1]; OUT = sys.argv[2]
BACKEND = "rust"
if "--backend" in sys.argv:
    _bi = sys.argv.index("--backend")
    BACKEND = sys.argv[_bi + 1] if _bi + 1 < len(sys.argv) else ""
    if BACKEND not in ("rust", "llvm"):
        print("usage: mutate.py <src> <out> [--backend rust|llvm] [--compiler py|rs] [--compiler-path PATH]")
        sys.exit(2)
LLVM = BACKEND == "llvm"
OPS = [(r"<=", "<"), (r"(?<![<=!>])<(?!=)", "<="), (r">=", ">"), (r"(?<![-=>])>(?!=)", ">="),
       (r"==", "!="), (r"!=", "=="), (r"\+ 1\b", "+ 2"), (r"\+ 1\b", ""), (r"- 1\b", "+ 1"), (r"- 1\b", ""),
       (r"(?<=[\w)\]] )\+(?= )", "-"), (r"(?<=[\w)\]] )-(?= )", "+"), (r"= 0;", "= 1;"), (r"= 1;", "= 0;"),
       (r"(?<=[\w)\]] )\*(?= )", "+")]
SKIP = re.compile(r"^\s*(requires|ensures|invariant|decreases|fn |//)")


def mutants(text):
    lines = text.split("\n")
    for li, line in enumerate(lines):
        if SKIP.match(line):
            continue
        for pat, rep in OPS:
            for m in re.finditer(pat, line):
                new = line[:m.start()] + rep + line[m.end():]
                if new == line:
                    continue
                yield li + 1, line.strip(), new.strip(), "\n".join(lines[:li] + [new] + lines[li + 1:])


def one(job):
    pid, ln, old, new, text = job
    d = tempfile.mkdtemp(prefix="mut_")
    vp = os.path.join(d, pid + ".pruv"); rs = os.path.join(d, pid + ".rs")
    ll = os.path.join(d, pid + ".ll")
    open(vp, "w").write(text)
    drv = H.get_driver()
    if LLVM:
        out_path, extra = ll, ["--rust-bindings", rs]
    else:
        out_path, extra = rs, []
    v = drv.run(drv.argv(vp, out_path, extra, BACKEND), timeout=None)  # no time limit (as before)
    errs = [json.loads(l) for l in v.stdout.splitlines() if l.startswith("{")]
    pruv_ok = v.returncode == 0
    stage = None if pruv_ok else errs[0].get("stage", str(errs[0])) if errs else "crash"
    n = drv.run(drv.argv(vp, out_path, extra + ["--no-verify"], BACKEND), timeout=None)
    if n.crashed:  # exit 3, signal, timeout (not a rejection, exit 1/2)
        tests = "crash"
    elif n.returncode != 0:
        tests = "not_compilable"
    else:
        r = H.build_and_run(rs, pid, d, noperf=True, llvm_path=ll if LLVM else None)
        tests = "pass" if r["status"] == "ok" else r["status"]
    pruv_crash = (not pruv_ok) and (stage in ("internal", "crash") or v.crashed)
    return {"pid": pid, "line": ln, "from": old, "to": new,
            "pruv": "accepted" if pruv_ok else ("crash" if pruv_crash else "rejected"),
            "pruv_stage": stage, "pruv_code": (errs[0].get("code") if errs else ("crash:" + v.stderr.strip().splitlines()[-1][:150] if v.stderr.strip() else None)), "tests": tests,
            "first_failure": None}


jobs = []
for f in sorted(os.listdir(SRC)):
    if f.endswith(".pruv"):
        t = open(os.path.join(SRC, f)).read()
        for ln, old, new, mt in mutants(t):
            jobs.append((os.path.splitext(f)[0], ln, old, new, mt))
print("mutants:", len(jobs), flush=True)
with ThreadPoolExecutor(6) as ex:
    res = list(ex.map(one, jobs))
json.dump(res, open(OUT, "w"), indent=1)
