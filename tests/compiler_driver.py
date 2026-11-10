"""Pruv 컴파일러(Python 판 / Rust 판) 호출 공통 드라이버.

    import compiler_driver as CD
    CD.add_args(argparse_parser)        # --compiler py|rs (기본 rs), --compiler-path PATH
    drv = CD.from_args(ns)              # argparse 결과 -> Driver
    drv = CD.from_argv(sys.argv)        # 수동 argv 파싱 도구용: 두 옵션을 argv 에서 떼어 내고 Driver 반환
    argv = drv.argv(src, out, flags, backend)
    res = drv.run(argv, timeout=300)    # Result: returncode/stdout/stderr/timed_out/elapsed

규칙
  - 모든 호출은 --backend 를 명시한다.
  - py: [고정 Python, ROOT/pruvc/pruvc.py, src, -o, out, --backend, B, *flags]
        고정 Python = ROOT/.venv/bin/python (Windows 는 .venv/Scripts/python.exe), 없으면 sys.executable.
        --compiler-path 를 주면 pruvc.py 위치 재정의로 쓴다.
  - 기본은 rs(Rust 판이 정본). Python 판은 대조 기준이며 --compiler py 로 고른다.
  - rs: [바이너리, src, -o, out, --backend, B, *flags]; 바이너리는 --compiler-path 로 주고,
        없으면 PRUVC_RS_DEFAULT(ROOT/pruvc-rs/target/release/pruvc, Windows 는 .exe).
        바이너리가 없거나 실행 불가면 빌드 안내와 함께 오류로 종료한다(조용히 py 로 넘어가지 않는다).
        빌드: cd pruvc-rs && cargo build --release --locked
  - 셸 문자열 결합 없음(argv 목록만).
"""
import argparse
import hashlib
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PRUVC_PY = os.path.join(ROOT, "pruvc", "pruvc.py")
PRUVC_RS_DEFAULT = os.path.join(ROOT, "pruvc-rs", "target", "release",
                                "pruvc.exe" if os.name == "nt" else "pruvc")
TIMEOUT_RC = -999  # 시간 초과 때 Result.returncode (실제 종료 코드가 아니다)
SPAWN_FAIL_RC = -998  # 프로세스를 띄우지 못했을 때


def pinned_python():
    """고정 Python: .venv (Windows 는 Scripts/python.exe), 없으면 현재 인터프리터."""
    if os.name == "nt":
        cand = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    else:
        cand = os.path.join(ROOT, ".venv", "bin", "python")
    return cand if os.path.exists(cand) else sys.executable


class Result:
    """한 번의 컴파일러 실행 결과. subprocess.CompletedProcess 와 같은 필드 이름을 쓴다."""

    def __init__(self, argv, returncode, stdout, stderr, timed_out=False, elapsed=0.0, spawn_error=False):
        self.args = argv
        self.argv = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.timed_out = timed_out
        self.spawn_error = spawn_error
        self.elapsed = elapsed

    @property
    def kind(self):
        """ok(0) / reject(1) / usage(2) / timeout / crash(3, 신호 종료, 그 밖의 코드, 실행 실패)."""
        if self.timed_out:
            return "timeout"
        if self.spawn_error:
            return "crash"
        return {0: "ok", 1: "reject", 2: "usage"}.get(self.returncode, "crash")

    @property
    def crashed(self):
        return self.kind in ("crash", "timeout")

    def raise_if_timeout(self):
        """옛 호출부가 subprocess.TimeoutExpired 에 기대던 곳을 위한 도우미."""
        if self.timed_out:
            raise subprocess.TimeoutExpired(self.argv, self.elapsed)
        return self


def _text(v):
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", errors="replace")
    return v


def _sha256(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError as e:
        return "unreadable: %s" % e


def run_argv(argv, timeout=300, cwd=None):
    """argv 목록(셸 없음)을 새 프로세스로 실행. 시간 초과는 timed_out=True, 실행 실패는 spawn_error=True."""
    t0 = time.time()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, cwd=cwd)
        return Result(argv, p.returncode, p.stdout, p.stderr, False, time.time() - t0)
    except subprocess.TimeoutExpired as e:
        return Result(argv, TIMEOUT_RC, _text(e.stdout),
                      _text(e.stderr) + "timeout after %ss" % timeout, True, time.time() - t0)
    except OSError as e:
        return Result(argv, SPAWN_FAIL_RC, "", "cannot execute %r: %s" % (argv[0], e),
                      False, time.time() - t0, spawn_error=True)


class Driver:
    def __init__(self, kind, path):
        self.kind = kind          # "py" | "rs"
        self.path = path          # py: pruvc.py 경로, rs: 바이너리 경로
        self.name = kind
        self.python = pinned_python() if kind == "py" else None
        self._version = None

    # ---- argv ----
    def prefix(self):
        return [self.python, self.path] if self.kind == "py" else [self.path]

    def argv(self, src, out, flags=(), backend="rust"):
        if backend not in ("rust", "llvm"):
            raise ValueError("backend must be rust|llvm: %r" % (backend,))
        return self.prefix() + [str(src), "-o", str(out), "--backend", backend] + [str(f) for f in flags]

    def argv_raw(self, args):
        """이미 만들어진 인자 목록(첫 원소가 입력 파일) 앞에 실행 접두부만 붙인다."""
        return self.prefix() + [str(a) for a in args]

    # ---- 실행 ----
    def run(self, argv, timeout=300, cwd=None):
        return run_argv(argv, timeout, cwd)

    # ---- 버전 정보 ----
    def version_info(self):
        if self._version is None:
            info = {"compiler": self.kind, "path": os.path.abspath(self.path),
                    "argv_prefix": self.prefix(), "sha256": _sha256(self.path)}
            if self.kind == "py":
                info["python"] = self.python
                r = self.run([self.python, "-c", "import sys; print(sys.version.split()[0])"], timeout=30)
                info["python_version"] = r.stdout.strip() if r.returncode == 0 else "unknown"
            else:
                r = self.run([self.path, "--version"], timeout=30)
                info["version_exit"] = r.returncode
                info["version_output"] = (r.stdout + r.stderr).strip()[:300]
            self._version = info
        return self._version


def _fail(msg):
    sys.stderr.write("compiler_driver: %s\n" % msg)
    raise SystemExit(2)


def make_driver(kind, path=None):
    if kind not in ("py", "rs"):
        _fail("--compiler must be py or rs, got %r" % (kind,))
    if kind == "py":
        p = os.path.abspath(path) if path else PRUVC_PY
        if not os.path.isfile(p):
            _fail("pruvc.py not found: %s" % p)
        return Driver("py", p)
    p = os.path.abspath(path) if path else PRUVC_RS_DEFAULT
    if not os.path.isfile(p):
        _fail("Rust compiler binary not found: %s\n"
              "  build it: cd pruvc-rs && cargo build --release --locked\n"
              "  or pass --compiler-path PATH, or use the Python version with --compiler py "
              "(no silent fallback to py)" % p)
    if not os.access(p, os.X_OK):
        _fail("Rust compiler binary is not executable: %s" % p)
    return Driver("rs", p)


def add_args(parser):
    parser.add_argument("--compiler", choices=["py", "rs"], default="rs",
                        help="compiler under test (default rs)")
    parser.add_argument("--compiler-path", default=None, metavar="PATH",
                        help="rs: compiler binary (default pruvc-rs/target/release/pruvc); "
                             "py: override pruvc.py location")
    return parser


def from_args(ns):
    return make_driver(getattr(ns, "compiler", "rs"), getattr(ns, "compiler_path", None))


def from_argv(argv):
    """--compiler X / --compiler=X / --compiler-path P / --compiler-path=P 를 argv(리스트)에서 제자리로
    떼어 내고 Driver 를 반환한다. 수동 sys.argv 파싱을 쓰는 도구용."""
    kind, path, rest, i = "rs", None, [], 0
    while i < len(argv):
        a = argv[i]
        if a in ("--compiler", "--compiler-path"):
            if i + 1 >= len(argv):
                _fail("%s needs a value" % a)
            if a == "--compiler":
                kind = argv[i + 1]
            else:
                path = argv[i + 1]
            i += 2
            continue
        if a.startswith("--compiler="):
            kind = a.split("=", 1)[1]
        elif a.startswith("--compiler-path="):
            path = a.split("=", 1)[1]
        else:
            rest.append(a)
        i += 1
    argv[:] = rest
    return make_driver(kind, path)


def default_driver():
    return make_driver("rs", None)
