#!/usr/bin/env python3
"""Runner for the Python-implementation <-> Rust-implementation cross-check tools (runs them one after
another via sys.executable, no shell).

Usage:
    python tests/m3_all.py [--only NAME[,NAME]] [--skip NAME[,NAME]] [--quick]
                           [--rs-dir DIR] [--log-dir DIR] [--timeout SEC]

Stages (in order): parse, check, trace, trace_infer, llvm, rust, compilers, standalone, abi, abi_v2, abi_bool, abi_utf8
  parse      tests/diff_parse.py --mode parse   (pruv-parse-dump)
  check      tests/diff_parse.py --mode check   (pruv-check-dump)
  trace      tests/diff_trace.py                (pruv-trace-dump)
  trace_infer tests/diff_trace.py --flags=--infer (invariant inference search, down to the final query)
  llvm       tests/diff_llvm.py                 (pruv-llvm-dump)
  rust       tests/diff_rust.py                 (pruv-rust-dump)
  compilers  tests/diff_compilers.py --b rs --backend both (pruvc)
  standalone tests/standalone/run.py            (pruvc)
  abi        tests/abi/check_generated.py       (pruvc)
  abi_v2     tests/abi/check_runtime_v2.py      (pruvc; runtime v2 link: 6 success/failure cases)
  abi_bool   tests/abi/check_bool_repr.py       (pruvc; [bool] raw ABI representation check pruv_check_bool)
  abi_utf8   tests/abi/check_utf8_repr.py       (pruvc; str raw ABI UTF-8 check pruv_check_utf8)

Options:
  --only/--skip  comma-separated stage names (if both are given, skip is subtracted from only)
  --quick        small inputs: --fuzz-count 20 for parse/check/llvm/rust, --fuzz-count 5 for trace/trace_infer
                 (diff_compilers, standalone, abi, abi_v2 have no such option and run unchanged)
  --rs-dir       Rust binary directory (default pruvc-rs/target/release; relative paths are relative to the repo root)
  --log-dir      directory for the per-stage NAME.log (stdout+stderr, written as the stage runs)
                 (default tempfile.mkdtemp; relative paths are relative to the repo root)
  --timeout SEC  per-stage time limit (default 1800 s). On expiry the process is killed, reported as "timeout", and counted as a failure

Stage result status: ok / FAIL (exit code != 0) / missing (no binary) / timeout (time limit exceeded)

Exit codes: 0 = every stage that ran is ok, 1 = at least one FAIL/missing/timeout (including a tool exit code != 0;
  diff_compilers' 3 "unimplemented" also counts as a failure), 2 = usage error (unknown stage name, etc.).
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ".exe" if os.name == "nt" else ""

# (name, script, binary name, path option name, fixed options, extra options for --quick)
STAGES = [
    ("parse", "tests/diff_parse.py", "pruv-parse-dump", "--rs-path", ["--mode", "parse"], ["--fuzz-count", "20"]),
    ("check", "tests/diff_parse.py", "pruv-check-dump", "--rs-path", ["--mode", "check"], ["--fuzz-count", "20"]),
    ("trace", "tests/diff_trace.py", "pruv-trace-dump", "--rs-path", [], ["--fuzz-count", "5"]),
    ("trace_infer", "tests/diff_trace.py", "pruv-trace-dump", "--rs-path", ["--flags=--infer"], ["--fuzz-count", "5"]),
    ("llvm", "tests/diff_llvm.py", "pruv-llvm-dump", "--rs-path", [], ["--fuzz-count", "20"]),
    ("rust", "tests/diff_rust.py", "pruv-rust-dump", "--rs-path", [], ["--fuzz-count", "20"]),
    ("compilers", "tests/diff_compilers.py", "pruvc", "--b-path", ["--b", "rs", "--backend", "both"], []),
    ("standalone", "tests/standalone/run.py", "pruvc", "--rs-path", [], []),
    ("abi", "tests/abi/check_generated.py", "pruvc", "--pruvc", [], []),
    ("abi_v2", "tests/abi/check_runtime_v2.py", "pruvc", "--pruvc", [], []),
    ("abi_bool", "tests/abi/check_bool_repr.py", "pruvc", "--pruvc", [], []),
    ("abi_utf8", "tests/abi/check_utf8_repr.py", "pruvc", "--pruvc", [], []),
]
NAMES = [s[0] for s in STAGES]


def split_names(text, ap, opt):
    out = [t.strip() for t in text.split(",") if t.strip()]
    bad = [t for t in out if t not in NAMES]
    if bad:
        ap.error("%s: unknown stage %s (valid: %s)" % (opt, ",".join(bad), " ".join(NAMES)))
    return out


# Start each stage in its own process group so that on timeout or Ctrl-C the grandchildren (pruvc, rustc, executables) are killed too.
if os.name == "nt":
    GROUP_KW = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
else:
    GROUP_KW = {"start_new_session": True}


def kill_tree(proc):
    """Kill proc and its descendants, then wait for it."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.kill()
    except OSError:
        pass
    proc.wait()


def read_tail(path, limit=64 * 1024):
    """Read the tail of a log file (at most limit bytes) as a string."""
    try:
        with open(str(path), "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - limit))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def last_line(text):
    for ln in reversed(text.splitlines()):
        if ln.strip():
            return ln.strip()
    return ""


def main(argv):
    ap = argparse.ArgumentParser(description="Run the Python<->Rust cross-check tools as a batch")
    ap.add_argument("--only", default=None, help="comma-separated stage list: " + " ".join(NAMES))
    ap.add_argument("--skip", default=None, help="comma-separated list of stages to skip")
    ap.add_argument("--quick", action="store_true", help="small inputs (--fuzz-count 20, 5 for trace)")
    ap.add_argument("--rs-dir", default="pruvc-rs/target/release", help="Rust binary directory")
    ap.add_argument("--log-dir", default=None, help="per-stage log directory (relative paths are relative to the repo root; default: a temp directory)")
    ap.add_argument("--timeout", type=float, default=1800, help="per-stage time limit (seconds, default 1800)")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code not in (0, None) else 0

    only = split_names(args.only, ap, "--only") if args.only is not None else list(NAMES)
    skip = set(split_names(args.skip, ap, "--skip")) if args.skip else set()
    selected = [s for s in STAGES if s[0] in only and s[0] not in skip]
    if not selected:
        ap.error("no stages to run")

    rs_dir = Path(args.rs_dir)
    if not rs_dir.is_absolute():
        rs_dir = ROOT / rs_dir
    if args.log_dir:
        log_dir = Path(args.log_dir)
        if not log_dir.is_absolute():
            log_dir = ROOT / log_dir
        log_dir.mkdir(parents=True, exist_ok=True)
    else:
        log_dir = Path(tempfile.mkdtemp(prefix="m3_all_"))

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    results = []  # (name, status, secs, last)
    for name, script, binname, path_opt, fixed, quick in selected:
        binpath = rs_dir / (binname + EXE)
        if not binpath.is_file():
            msg = "binary not found: %s" % binpath
            print("[%s] missing - %s" % (name, msg), flush=True)
            (log_dir / (name + ".log")).write_text(msg + "\n", encoding="utf-8")
            results.append((name, "missing", 0.0, msg))
            continue
        cmd = [sys.executable, str(ROOT / script)] + fixed + [path_opt, str(binpath)]
        if args.quick:
            cmd += quick
        print("[%s] start: %s" % (name, " ".join(cmd[1:])), flush=True)
        t0 = time.time()
        log_path = log_dir / (name + ".log")
        timed_out = False
        code = -1
        # Output is not collected in memory; it streams straight to the log file (the log survives Ctrl-C)
        with open(str(log_path), "wb") as logf:
            try:
                proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=logf, **GROUP_KW,
                                        stderr=subprocess.STDOUT)
            except OSError as e:
                proc = None
                logf.write(("failed to start: %s\n" % e).encode("utf-8"))
            if proc is not None:
                try:
                    code = proc.wait(timeout=args.timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    kill_tree(proc)
                    proc.wait()
                    code = -1
                    logf.flush()
                    logf.write(("\n[m3_all] timeout: exceeded %s s, process killed\n"
                                % args.timeout).encode("utf-8"))
                except BaseException:
                    kill_tree(proc)
                    proc.wait()
                    raise
        secs = time.time() - t0
        if timed_out:
            status = "timeout"
        else:
            status = "ok" if code == 0 else "FAIL"
        results.append((name, status, secs, last_line(read_tail(log_path))))
        print("[%s] done: %s (exit code %d, %.1f s)" % (name, status, code, secs), flush=True)
        if status != "ok":
            # CI keeps only stdout: show the end of the failing stage's log so the cause is visible there
            tail = read_tail(log_path, 12 * 1024).splitlines()[-120:]
            print("[%s] --- last %d log lines ---\n%s\n[%s] --- end of log ---" % (name, len(tail), "\n".join(tail), name),
                  flush=True)

    print("", flush=True)
    rows = [("stage", "result", "sec", "last line")]
    rows += [(n, st, "%.1f" % sec, ll) for n, st, sec, ll in results]
    w = [max(len(r[i]) for r in rows) for i in range(3)]
    for r in rows:
        print("%s | %s | %s | %s" % (r[0].ljust(w[0]), r[1].ljust(w[1]), r[2].rjust(w[2]), r[3]))
    print("log directory: %s" % log_dir, flush=True)
    return 0 if all(r[1] == "ok" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
