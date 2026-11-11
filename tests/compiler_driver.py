"""Common driver for invoking the Pruv compiler (Python implementation / Rust implementation).

    import compiler_driver as CD
    CD.add_args(argparse_parser)        # --compiler py|rs (default rs), --compiler-path PATH
    drv = CD.from_args(ns)              # argparse result -> Driver
    drv = CD.from_argv(sys.argv)        # for tools with manual argv parsing: strips both options from argv and returns a Driver
    argv = drv.argv(src, out, flags, backend)
    res = drv.run(argv, timeout=300)    # Result: returncode/stdout/stderr/timed_out/elapsed

Rules
  - Every call passes --backend explicitly.
  - py: [pinned Python, ROOT/pruvc/pruvc.py, src, -o, out, --backend, B, *flags]
        pinned Python = ROOT/.venv/bin/python (.venv/Scripts/python.exe on Windows), else sys.executable.
        --compiler-path, if given, overrides the pruvc.py location.
  - The default is rs (the Rust implementation is canonical). The Python implementation is the cross-check reference; pick it with --compiler py.
  - rs: [binary, src, -o, out, --backend, B, *flags]; the binary is given with --compiler-path,
        otherwise PRUVC_RS_DEFAULT (ROOT/pruvc-rs/target/release/pruvc, .exe on Windows).
        If the binary is missing or not executable, exit with an error and build instructions (never silently fall back to py).
        Build: cd pruvc-rs && cargo build --release --locked
  - No shell string concatenation (argv lists only).
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
TIMEOUT_RC = -999  # Result.returncode on timeout (not a real exit code)
SPAWN_FAIL_RC = -998  # when the process could not be started


def pinned_python():
    """Pinned Python: .venv (Scripts/python.exe on Windows), else the current interpreter."""
    if os.name == "nt":
        cand = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    else:
        cand = os.path.join(ROOT, ".venv", "bin", "python")
    return cand if os.path.exists(cand) else sys.executable


class Result:
    """Result of one compiler run. Uses the same field names as subprocess.CompletedProcess."""

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
        """ok(0) / reject(1) / usage(2) / timeout / crash(3, killed by signal, any other code, failure to start)."""
        if self.timed_out:
            return "timeout"
        if self.spawn_error:
            return "crash"
        return {0: "ok", 1: "reject", 2: "usage"}.get(self.returncode, "crash")

    @property
    def crashed(self):
        return self.kind in ("crash", "timeout")

    def raise_if_timeout(self):
        """Helper for older call sites that relied on subprocess.TimeoutExpired."""
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
    """Run an argv list (no shell) in a new process. A timeout sets timed_out=True; a failure to start sets spawn_error=True."""
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
        self.path = path          # py: pruvc.py path, rs: binary path
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
        """Only prepend the launch prefix to an already-built argument list (first element is the input file)."""
        return self.prefix() + [str(a) for a in args]

    # ---- run ----
    def run(self, argv, timeout=300, cwd=None):
        return run_argv(argv, timeout, cwd)

    # ---- version info ----
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
    """Strip --compiler X / --compiler=X / --compiler-path P / --compiler-path=P from argv (a list) in
    place and return a Driver. For tools that parse sys.argv manually."""
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
