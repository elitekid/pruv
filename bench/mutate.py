"""Mutation test: inject small bugs into code lines of Vow solutions.
For each mutant: (1) does Vow's verifier reject it?  (2) does the same code, compiled to
Rust without verification (what rustc alone would accept), fail the tests?"""
import json, os, re, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "harness"))
import run as H

SRC = sys.argv[1]; OUT = sys.argv[2]
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
    vp = os.path.join(d, pid + ".vow"); rs = os.path.join(d, pid + ".rs")
    open(vp, "w").write(text)
    v = subprocess.run([H.PY, H.VOWC, vp, "-o", rs], capture_output=True, text=True)
    errs = [json.loads(l) for l in v.stdout.splitlines() if l.startswith("{")]
    vow_ok = v.returncode == 0
    stage = None if vow_ok else errs[0].get("stage", str(errs[0])) if errs else "crash"
    n = subprocess.run([H.PY, H.VOWC, vp, "-o", rs, "--no-verify"], capture_output=True, text=True)
    if n.returncode != 0:
        tests = "not_compilable"
    else:
        r = H.build_and_run(rs, pid, d, noperf=True)
        tests = "pass" if r["status"] == "ok" else r["status"]
    return {"pid": pid, "line": ln, "from": old, "to": new, "vow": "accepted" if vow_ok else "rejected",
            "vow_stage": stage, "vow_code": (errs[0].get("code") if errs else ("crash:" + v.stderr.strip().splitlines()[-1][:150] if v.stderr.strip() else None)), "tests": tests,
            "first_failure": None}


jobs = []
for f in sorted(os.listdir(SRC)):
    if f.endswith(".vow"):
        t = open(os.path.join(SRC, f)).read()
        for ln, old, new, mt in mutants(t):
            jobs.append((f[:-4], ln, old, new, mt))
print("mutants:", len(jobs), flush=True)
with ThreadPoolExecutor(6) as ex:
    res = list(ex.map(one, jobs))
json.dump(res, open(OUT, "w"), indent=1)
