#!/usr/bin/env python3
"""Python 판 <-> Rust 판 대조 도구 묶음 실행기 (셸 없이 sys.executable 로 차례 실행).

사용:
    python tests/m3_all.py [--only NAME[,NAME]] [--skip NAME[,NAME]] [--quick]
                           [--rs-dir DIR] [--log-dir DIR] [--timeout SEC]

단계(순서대로): parse, check, trace, trace_infer, llvm, rust, compilers, standalone, abi, abi_v2, abi_bool
  parse      tests/diff_parse.py --mode parse   (pruv-parse-dump)
  check      tests/diff_parse.py --mode check   (pruv-check-dump)
  trace      tests/diff_trace.py                (pruv-trace-dump)
  trace_infer tests/diff_trace.py --flags=--infer (불변식 추론 탐색·최종 질의까지)
  llvm       tests/diff_llvm.py                 (pruv-llvm-dump)
  rust       tests/diff_rust.py                 (pruv-rust-dump)
  compilers  tests/diff_compilers.py --b rs --backend both (pruvc)
  standalone tests/standalone/run.py            (pruvc)
  abi        tests/abi/check_generated.py       (pruvc)
  abi_v2     tests/abi/check_runtime_v2.py      (pruvc; 런타임 v2 링크 성공·실패 6경우)
  abi_bool   tests/abi/check_bool_repr.py       (pruvc; [bool] raw ABI 표현 검사 pruv_check_bool)

옵션:
  --only/--skip  단계 이름 쉼표 목록(둘 다 주면 only 에서 skip 을 뺌)
  --quick        작은 입력: parse/check/llvm/rust 는 --fuzz-count 20, trace·trace_infer 는 --fuzz-count 5
                 (diff_compilers·standalone·abi·abi_v2 는 해당 옵션이 없어 그대로)
  --rs-dir       Rust 바이너리 폴더(기본 pruvc-rs/target/release, 상대 경로는 저장소 루트 기준)
  --log-dir      단계별 NAME.log(stdout+stderr, 실행 중 바로 기록) 저장 폴더
                 (기본 tempfile.mkdtemp, 상대 경로는 저장소 루트 기준)
  --timeout SEC  단계당 제한 시간(기본 1800초). 넘으면 프로세스를 죽이고 "timeout" 으로 표시, 실패로 셈

단계 결과 상태: ok / FAIL(종료 코드≠0) / missing(바이너리 없음) / timeout(제한 시간 초과)

종료 코드: 0 = 실행한 단계 전부 ok, 1 = 하나라도 FAIL/missing/timeout(도구 종료 코드≠0 포함,
  diff_compilers 의 3 '미구현' 도 실패로 셈), 2 = 사용 오류(알 수 없는 단계 이름 등).
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

# (이름, 스크립트, 바이너리 이름, 경로 옵션 이름, 고정 옵션, quick 때 추가 옵션)
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
]
NAMES = [s[0] for s in STAGES]


def split_names(text, ap, opt):
    out = [t.strip() for t in text.split(",") if t.strip()]
    bad = [t for t in out if t not in NAMES]
    if bad:
        ap.error("%s: 알 수 없는 단계 %s (가능: %s)" % (opt, ",".join(bad), " ".join(NAMES)))
    return out


# 단계마다 새 프로세스 묶음으로 띄워, 시간 초과·Ctrl-C 때 손자(pruvc·rustc·실행 파일)까지 함께 끝낸다.
if os.name == "nt":
    GROUP_KW = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
else:
    GROUP_KW = {"start_new_session": True}


def kill_tree(proc):
    """proc 와 그 자손을 끝내고 기다린다."""
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
    """로그 파일 끝부분(최대 limit 바이트)을 문자열로 읽는다."""
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
    ap = argparse.ArgumentParser(description="Python<->Rust 대조 도구 묶음 실행")
    ap.add_argument("--only", default=None, help="단계 쉼표 목록: " + " ".join(NAMES))
    ap.add_argument("--skip", default=None, help="뺄 단계 쉼표 목록")
    ap.add_argument("--quick", action="store_true", help="작은 입력(--fuzz-count 20, trace 는 5)")
    ap.add_argument("--rs-dir", default="pruvc-rs/target/release", help="Rust 바이너리 폴더")
    ap.add_argument("--log-dir", default=None, help="단계별 로그 폴더(상대 경로는 저장소 루트 기준, 기본 임시 폴더)")
    ap.add_argument("--timeout", type=float, default=1800, help="단계당 제한 시간(초, 기본 1800)")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code not in (0, None) else 0

    only = split_names(args.only, ap, "--only") if args.only is not None else list(NAMES)
    skip = set(split_names(args.skip, ap, "--skip")) if args.skip else set()
    selected = [s for s in STAGES if s[0] in only and s[0] not in skip]
    if not selected:
        ap.error("실행할 단계가 없음")

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
            msg = "바이너리 없음: %s" % binpath
            print("[%s] missing - %s" % (name, msg), flush=True)
            (log_dir / (name + ".log")).write_text(msg + "\n", encoding="utf-8")
            results.append((name, "missing", 0.0, msg))
            continue
        cmd = [sys.executable, str(ROOT / script)] + fixed + [path_opt, str(binpath)]
        if args.quick:
            cmd += quick
        print("[%s] 시작: %s" % (name, " ".join(cmd[1:])), flush=True)
        t0 = time.time()
        log_path = log_dir / (name + ".log")
        timed_out = False
        code = -1
        # 출력은 메모리에 모으지 않고 로그 파일로 바로 흘린다(Ctrl-C 때도 로그가 남음)
        with open(str(log_path), "wb") as logf:
            try:
                proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=logf, **GROUP_KW,
                                        stderr=subprocess.STDOUT)
            except OSError as e:
                proc = None
                logf.write(("실행 실패: %s\n" % e).encode("utf-8"))
            if proc is not None:
                try:
                    code = proc.wait(timeout=args.timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    kill_tree(proc)
                    proc.wait()
                    code = -1
                    logf.flush()
                    logf.write(("\n[m3_all] timeout: %s초 초과, 프로세스를 종료함\n"
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
        print("[%s] 끝: %s (종료 코드 %d, %.1f초)" % (name, status, code, secs), flush=True)

    print("", flush=True)
    rows = [("단계", "결과", "초", "마지막 줄")]
    rows += [(n, st, "%.1f" % sec, ll) for n, st, sec, ll in results]
    w = [max(len(r[i]) for r in rows) for i in range(3)]
    for r in rows:
        print("%s | %s | %s | %s" % (r[0].ljust(w[0]), r[1].ljust(w[1]), r[2].rjust(w[2]), r[3]))
    print("로그 폴더: %s" % log_dir, flush=True)
    return 0 if all(r[1] == "ok" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
