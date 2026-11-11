"""0B: Cross-check the obligation trace of the Rust z3 real-obligation prototype (pruv-proof-spike) against the Python reference.

  .venv/bin/python ci/m3/compare_spike.py [--spike PATH]

For each sample, runs Python (tests/diff_py_adapter.py trace) and Rust (pruv-proof-spike NAME) in fresh processes,
and compares obligation order, key (fn,line,col,code), per-attempt SMT-LIB text, and verdict. Python obligations skipped via `seen` are excluded.
Exits 1 if anything differs.
"""
import argparse, difflib, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLES = os.path.join(ROOT, "pruvc-rs/crates/pruv-proof/samples")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spike", default=os.path.join(ROOT, "pruvc-rs/target/release/pruv-proof-spike"))
    a = ap.parse_args()
    names = subprocess.run([a.spike, "--list"], capture_output=True, text=True, check=True).stdout.split()
    if not names:
        print("error: sample list is empty (%s --list)" % a.spike)
        return 2
    total = same_smt = same_verdict = 0
    bad = False
    py_z3 = None  # z3 version on the Python side: taken from the trace result if present, otherwise obtained once via a subprocess
    rs_z3 = None
    for n in names:
        r = json.loads(subprocess.run([a.spike, n], capture_output=True, text=True, check=True).stdout)
        p = json.loads(subprocess.run([sys.executable, os.path.join(ROOT, "tests/diff_py_adapter.py"), "trace",
                                       os.path.join(SAMPLES, n + ".pruv")], capture_output=True, text=True,
                                      check=True).stdout)
        if py_z3 is None:
            py_z3 = p.get("z3_version")
            if not py_z3:
                py_z3 = subprocess.run([sys.executable, "-c", "import z3; print(z3.get_full_version())"],
                                       capture_output=True, text=True, check=True).stdout.strip()
        rs_z3 = r.get("z3_version")
        # The full version string's tail (commit hash) may differ per build: only the numeric version (first token) must match.
        if (rs_z3 or "").split()[:1] != (py_z3 or "").split()[:1]:
            print("z3 version mismatch: py=%r rs=%r (sample %s)" % (py_z3, rs_z3, n))
            bad = True
        po = [o for o in p["obligations"] if not o.get("skipped")]
        ro = r["obligations"]
        s_smt = s_ver = 0
        for i in range(max(len(po), len(ro))):
            x = po[i] if i < len(po) else None
            y = ro[i] if i < len(ro) else None
            key = lambda o: (o["fn"], o["line"], o["col"], o["code"])
            if x is None or y is None or key(x) != key(y):
                print("  %s #%d key differs: py=%s rs=%s" % (n, i, x and key(x), y and key(y)))
                continue
            tx = [t["smt2"] for t in x["attempts"]]; ty = [t["smt2"] for t in y["attempts"]]
            vx = [t["result"] for t in x["attempts"]]; vy = [t["result"] for t in y["attempts"]]
            s_smt += tx == ty; s_ver += vx == vy
            if tx != ty:
                for u, v in zip(tx, ty):
                    if u != v:
                        print("  %s #%d SMT differs:" % (n, i))
                        print("".join(list(difflib.unified_diff(u.splitlines(1), v.splitlines(1), "py", "rs", n=0))[:20]))
                        break
        cnt = max(len(po), len(ro))
        print("%-20s obligations py=%d rs=%d  smt_same=%d verdict_same=%d" % (n, len(po), len(ro), s_smt, s_ver))
        total += cnt; same_smt += s_smt; same_verdict += s_ver
        bad |= not (len(po) == len(ro) == s_smt == s_ver)
    print("TOTAL obligations=%d smt_same=%d verdict_same=%d z3(rs)=%s z3(py)=%s" % (total, same_smt, same_verdict, rs_z3, py_z3))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
