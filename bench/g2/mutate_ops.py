# -*- coding: utf-8 -*-
"""G2 전용 변이 시험: G2 변이 연산(G2_OPS)과 bench/mutate.py 의 기본 연산(base)으로 변이를 만들고,
(1) 검증 4번(컴파일러 py·rs × --infer 없음·켬, 뒷단 rust)의 판정과
(2) 진실 판정(rs 컴파일러 --no-verify rust 뒷단 → run.build_and_run 으로 참조 시험 실행)을 낸다.
명세: docs/G2_Q1_IMPL.md 3절.

사용:
  mutate_ops.py OUT.json [SRC_DIR] [--jobs N] [--retry] [--only qNN ...]
  mutate_ops.py --self-test        (연산만 고정 줄에 시험, 컴파일러 호출 없음)
  SRC_DIR 기본값은 bench/g2/solutions/ref_pruv. 결과는 보통 bench/g2/results/ 에 둔다.

변이 연산(계약 줄 SKIP 은 건드리지 않음):
  byte_const_pm1  정수 토큰 127·128·191·192·255·256 을 +1·-1
  guard_true/false  `if 조건 {`·`} else if 조건 {` 의 조건을 true/false 로 (while 은 아님)
  len_pm1         len(X) 를 (len(X) + 1)/(len(X) - 1)
  substr_pm1      substr(s, lo, hi) 의 lo·hi 를 각각 (.. + 1)/(.. - 1)
  boundary_drop   is_char_boundary(..) 를 true, !is_char_boundary(..) 를 false
  conj_drop       while/if 조건의 최상위 && 쪽을 하나씩만 남김
  base            bench/mutate.py 의 OPS 를 ast 로 읽어 적용(사본 없음)
같은 결과 텍스트는 하나로 합치고 ops 이름 목록을 남긴다.

검증 판정(mutate_infer.py classify 와 같음):
  accepted(종료 0) / rejected / undecided(inference_timeout·verify_unknown 뿐) / crash
  (종료 0·1 밖, JSON 없는 1, stage internal, 시간 초과 600초, 실행 실패). --retry 는 undecided 를 직렬로 한 번 더.
진실 판정: ok → true_mutant, wrong·timeout → false_mutant, Pruv --no-verify 거부 → not_compilable,
  컴파일러 crash·생성 Rust 의 rustc 실패(코드 생성 결함 후보) → crash.

관문(G2_SPEC 8.3): false_accepted(거짓 변이인데 4번 중 하나라도 accepted)=0, crash=0, py·rs 판정 차이=0.
종료 코드: false_accepted 나 crash 가 있으면 1, 아니면 0. 참 변이의 통과는 수만 센다.
"""
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY = os.path.join(ROOT, ".venv", "bin", "python")
RS_BIN = os.path.join(ROOT, "pruvc-rs", "target", "release", "pruvc")
COMPILERS = {
    "py": [PY, os.path.join(ROOT, "pruvc", "pruvc.py")],
    "rs": [RS_BIN],
}
UNDECIDED_CODES = ("inference_timeout", "verify_unknown")
RUNS = [(c, inf) for c in ("py", "rs") for inf in (False, True)]
DEFAULT_SRC = os.path.join(HERE, "solutions", "ref_pruv")


# ---------------------------------------------------------------- 연산 도우미
def match_paren(s, open_idx):
    """s[open_idx] == '(' 의 짝 ')' 위치. 없으면 -1."""
    depth = 0
    for i in range(open_idx, len(s)):
        ch = s[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def split_top(s, start, end, sep):
    """s[start:end] 를 괄호·대괄호 깊이 0 에서 sep(문자열) 으로 나눈 (a, b) 구간 목록."""
    spans = []
    depth = 0
    seg = start
    i = start
    n = len(sep)
    while i < end:
        ch = s[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        elif depth == 0 and s.startswith(sep, i):
            spans.append((seg, i))
            i += n
            seg = i
            continue
        i += 1
    spans.append((seg, end))
    return spans


def find_calls(line, name):
    """name(...) 호출들의 (이름 시작, 여는 괄호, 닫는 괄호) 위치."""
    out = []
    for m in re.finditer(r"(?<![\w.])%s\s*\(" % re.escape(name), line):
        op = m.end() - 1
        cl = match_paren(line, op)
        if cl >= 0:
            out.append((m.start(), op, cl))
    return out


# ---------------------------------------------------------------- G2 연산
BYTE_RE = re.compile(r"(?<![\w.])(127|128|191|192|255|256)(?![\w.])")


def op_byte_const_pm1(line):
    res = []
    for m in BYTE_RE.finditer(line):
        v = int(m.group(1))
        for d in (1, -1):
            res.append(line[:m.start()] + str(v + d) + line[m.end():])
    return [r for r in res if r != line]


IF_RE = re.compile(r"^(\s*(?:\}\s*else\s+)?if\s+)(.+?)(\s*\{)\s*$")


def _guard(line, rep):
    m = IF_RE.match(line)
    if not m or m.group(2).strip() == rep:
        return []
    r = m.group(1) + rep + m.group(3)
    return [r] if r != line else []


def op_guard_true(line):
    return _guard(line, "true")


def op_guard_false(line):
    return _guard(line, "false")


def op_len_pm1(line):
    res = []
    for st, op, cl in find_calls(line, "len"):
        call = line[st:cl + 1]
        for d in ("+", "-"):
            res.append(line[:st] + "(%s %s 1)" % (call, d) + line[cl + 1:])
    return [r for r in res if r != line]


def op_substr_pm1(line):
    res = []
    for st, op, cl in find_calls(line, "substr"):
        spans = split_top(line, op + 1, cl, ",")
        if len(spans) != 3:
            continue
        for idx in (1, 2):  # lo, hi
            a, b = spans[idx]
            raw = line[a:b]
            body = raw.strip()
            if not body:
                continue
            lead = raw[:len(raw) - len(raw.lstrip())]
            trail = raw[len(raw.rstrip()):]
            for d in ("+", "-"):
                res.append(line[:a] + lead + "(%s %s 1)" % (body, d) + trail + line[b:])
    return [r for r in res if r != line]


def op_boundary_drop(line):
    res = []
    for st, op, cl in find_calls(line, "is_char_boundary"):
        pre = line[:st].rstrip()
        if pre.endswith("!"):
            res.append(pre[:-1] + "false" + line[cl + 1:])
        else:
            res.append(line[:st] + "true" + line[cl + 1:])
    return [r for r in res if r != line]


COND_RE = re.compile(r"^(\s*(?:\}\s*else\s+)?(?:while|if)\s+)(.*?)(\s*\{\s*)?$")


def op_conj_drop(line):
    m = COND_RE.match(line)
    if not m:
        return []
    cond = m.group(2)
    spans = split_top(cond, 0, len(cond), "&&")
    if len(spans) < 2:
        return []
    tail = m.group(3) or ""
    res = []
    for a, b in spans:
        part = cond[a:b].strip()
        if part:
            res.append(m.group(1) + part + tail)
    return [r for r in res if r != line]


G2_OPS = [
    ("byte_const_pm1", op_byte_const_pm1),
    ("guard_true", op_guard_true),
    ("guard_false", op_guard_false),
    ("len_pm1", op_len_pm1),
    ("substr_pm1", op_substr_pm1),
    ("boundary_drop", op_boundary_drop),
    ("conj_drop", op_conj_drop),
]


# ---------------------------------------------------------------- base 연산(mutate.py 에서 ast 로)
def load_base():
    src = open(os.path.join(ROOT, "bench", "mutate.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if isinstance(n, ast.Assign) and any(getattr(t, "id", None) in ("OPS", "SKIP") for t in n.targets)]
    ns = {"re": re}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "mutate.py", "exec"), ns)
    return ns["OPS"], ns["SKIP"]


def base_line_mutants(line, ops):
    """mutate.py mutants() 와 같은 방식: 각 패턴의 각 일치를 한 줄에 치환."""
    res = []
    for pat, rep in ops:
        for m in re.finditer(pat, line):
            new = line[:m.start()] + rep + line[m.end():]
            if new != line:
                res.append(new)
    return res


def make_mutants(text, base_ops, skip):
    """[(줄 번호, 원래 줄, 바뀐 줄, 전체 텍스트, ops 이름 목록)] 같은 결과는 합침."""
    lines = text.split("\n")
    out = []
    for li, line in enumerate(lines):
        if skip.match(line):
            continue
        seen = {}
        order = []
        cands = [("base", base_line_mutants(line, base_ops))] + [(n, f(line)) for n, f in G2_OPS]
        for name, news in cands:
            for new in news:
                if new == line:
                    continue
                if new not in seen:
                    seen[new] = []
                    order.append(new)
                if name not in seen[new]:
                    seen[new].append(name)
        for new in order:
            out.append((li + 1, line.strip(), new.strip(), "\n".join(lines[:li] + [new] + lines[li + 1:]), seen[new]))
    return out


# ---------------------------------------------------------------- 판정
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
        und = all(e.get("code") in UNDECIDED_CODES for e in errs)
        return ("undecided" if und else "rejected"), code
    return "crash", code


def run_compiler(comp, path, out, extra):
    argv = COMPILERS[comp] + [path, "-o", out, "--backend", "rust"] + list(extra)
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        return None, "timeout", None
    except OSError as e:
        return None, "spawn: %s" % e, None
    return p, None, None


def verify(comp, path, infer):
    t0 = time.time()
    d = tempfile.mkdtemp(prefix="g2m_")
    try:
        p, err, _ = run_compiler(comp, path, os.path.join(d, "out.rs"), ["--infer"] if infer else [])
        sec = round(time.time() - t0, 2)
        if p is None:
            return {"verdict": "crash", "code": err, "sec": sec}
        v, code = classify(p.returncode, p.stdout)
        r = {"verdict": v, "code": code, "sec": sec}
        if v == "crash":
            r["rc"] = p.returncode
            r["stderr_tail"] = p.stderr.strip()[-300:]
        return r
    finally:
        shutil.rmtree(d, ignore_errors=True)


def truth(G, path, pid):
    """rs 컴파일러 --no-verify rust 뒷단 → G.build_and_run."""
    d = tempfile.mkdtemp(prefix="g2t_")
    try:
        rs = os.path.join(d, pid + "_gen.rs")
        p, err, _ = run_compiler("rs", path, rs, ["--no-verify"])
        base = {"status": None, "tests_passed": None, "tests_total": None, "first_failure": None}
        if p is None:
            base.update(truth="crash", status=err)
            return base
        v, code = classify(p.returncode, p.stdout)
        if v == "crash":
            base.update(truth="crash", status="compiler_crash rc=%s %s" % (p.returncode, p.stderr.strip()[-200:]))
            return base
        if v != "accepted":
            base.update(truth="not_compilable", status="pruv_rejected:%s" % code)
            return base
        try:
            r = G.build_and_run(rs, pid, d)
        except Exception as e:  # 채점기 자체 실패는 crash 로 기록
            base.update(truth="crash", status="grader_error: %s" % e)
            return base
        st = r.get("status")
        base.update(status=st, tests_passed=r.get("tests_passed"), tests_total=r.get("tests_total"),
                    first_failure=r.get("first_failure"))
        if st == "ok":
            base["truth"] = "true_mutant"
        elif st in ("wrong", "timeout"):
            base["truth"] = "false_mutant"
        elif st == "compile_error":
            base["truth"] = "crash"   # Pruv 가 받은 코드를 rustc 가 못 받음 = 코드 생성 결함 후보(관문에 넣음)
        else:
            base["truth"] = "crash"
        return base
    finally:
        shutil.rmtree(d, ignore_errors=True)


def key(c, inf):
    return "%s_%s" % (c, "infer" if inf else "plain")


def versions():
    def sh(argv):
        try:
            return subprocess.run(argv, capture_output=True, text=True).stdout.strip()
        except OSError:
            return ""
    head = sh(["git", "-C", ROOT, "rev-parse", "HEAD"])
    dirty = bool(sh(["git", "-C", ROOT, "status", "--porcelain", "--", "pruvc", "pruvc-rs/crates",
                     "pruvc-rs/Cargo.lock"]))
    sha = hashlib.sha256(open(RS_BIN, "rb").read()).hexdigest() if os.path.exists(RS_BIN) else None
    z3py = sh([PY, "-c", "import z3; print(z3.get_version_string())"])
    z3src = None
    lp = os.path.join(ROOT, "pruvc-rs", "Cargo.lock")
    if os.path.exists(lp):
        lock = open(lp, encoding="utf-8").read()
        if 'name = "z3-src"' in lock:
            z3src = lock.split('name = "z3-src"', 1)[1].split("version = ", 1)[1].split("\n", 1)[0].strip('"')
    return {"git_head": head, "z3_python": z3py, "z3_src_crate": z3src, "compiler_sources_dirty": dirty,
            "rs_binary_sha256": sha,
            "rs_binary_mtime": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(RS_BIN)))
            if sha else None}


# ---------------------------------------------------------------- 요약
def build_table(items, groups_of):
    tab = {}
    for it in items:
        t = it["truth"]["truth"]
        for g in groups_of(it):
            cell = tab.setdefault(g, {}).setdefault(t, {"n": 0})
            cell["n"] += 1
            for c, inf in RUNS:
                k = key(c, inf)
                v = it[k]["verdict"]
                cell.setdefault(k, {})
                cell[k][v] = cell[k].get(v, 0) + 1
    return tab


def summarize(items, retried):
    def accepted_runs(it):
        return [key(c, inf) for c, inf in RUNS if it[key(c, inf)]["verdict"] == "accepted"]

    def brief(it):
        return {"pid": it["pid"], "line": it["line"], "from": it["from"], "to": it["to"], "ops": it["ops"]}

    s = {"command": " ".join(sys.argv[1:]), "versions": versions(), "retried_undecided": retried,
         "mutants": len(items)}
    s["truth_counts"] = {}
    for it in items:
        t = it["truth"]["truth"]
        s["truth_counts"][t] = s["truth_counts"].get(t, 0) + 1
    s["by_op"] = build_table(items, lambda it: it["ops"])
    s["by_problem"] = build_table(items, lambda it: [it["pid"]])
    s["false_accepted"] = [dict(brief(it), runs=accepted_runs(it)) for it in items
                           if it["truth"]["truth"] == "false_mutant" and accepted_runs(it)]
    s["true_accepted"] = sum(1 for it in items if it["truth"]["truth"] == "true_mutant" and accepted_runs(it))
    s["crash"] = [dict(brief(it), runs=[key(c, inf) for c, inf in RUNS if it[key(c, inf)]["verdict"] == "crash"],
                       truth_crash=it["truth"]["truth"] == "crash")
                  for it in items
                  if it["truth"]["truth"] == "crash" or any(it[key(c, inf)]["verdict"] == "crash" for c, inf in RUNS)]
    s["py_rs_verdict_diff"] = [dict(brief(it), mode=k, py=it["py_" + k]["verdict"], rs=it["rs_" + k]["verdict"])
                               for it in items for k in ("plain", "infer")
                               if it["py_" + k]["verdict"] != it["rs_" + k]["verdict"]]
    s["undecided"] = [dict(brief(it), run=key(c, inf)) for it in items for c, inf in RUNS
                      if it[key(c, inf)]["verdict"] == "undecided"]
    s["truth_rustc_compile_error"] = [brief(it) for it in items if it["truth"].get("status") == "compile_error"]
    return s


# ---------------------------------------------------------------- self-test
SELF_TESTS = [
    ("  if v > 255 {", {
        "byte_const_pm1": ["  if v > 256 {", "  if v > 254 {"],
        "guard_true": ["  if true {"],
        "guard_false": ["  if false {"],
    }),
    ("  } else if x < 128 {", {
        "byte_const_pm1": ["  } else if x < 129 {", "  } else if x < 127 {"],
        "guard_true": ["  } else if true {"],
        "guard_false": ["  } else if false {"],
    }),
    ("    let t: str = substr(s, i + 1, len(s));", {
        "len_pm1": ["    let t: str = substr(s, i + 1, (len(s) + 1));",
                    "    let t: str = substr(s, i + 1, (len(s) - 1));"],
        "substr_pm1": ["    let t: str = substr(s, (i + 1 + 1), len(s));",
                       "    let t: str = substr(s, (i + 1 - 1), len(s));",
                       "    let t: str = substr(s, i + 1, (len(s) + 1));",
                       "    let t: str = substr(s, i + 1, (len(s) - 1));"],
    }),
    ("  while j < len(s) && !is_char_boundary(s, j)", {
        "len_pm1": ["  while j < (len(s) + 1) && !is_char_boundary(s, j)",
                   "  while j < (len(s) - 1) && !is_char_boundary(s, j)"],
        "boundary_drop": ["  while j < len(s) && false"],
        "conj_drop": ["  while j < len(s)", "  while !is_char_boundary(s, j)"],
    }),
    ("  if is_char_boundary(s, k) {", {
        "guard_true": ["  if true {"],
        "guard_false": ["  if false {"],
        "boundary_drop": ["  if true {"],
    }),
    ("    out[k] = 255;", {
        "byte_const_pm1": ["    out[k] = 256;", "    out[k] = 254;"],
    }),
    ("    out[k] = 1255;", {}),
    ("  while (a && b) && c {", {
        "conj_drop": ["  while (a && b) {", "  while c {"],
    }),
]


def self_test():
    bad = 0
    for line, expect in SELF_TESTS:
        for name, f in G2_OPS:
            got = f(line)
            want = expect.get(name, [])
            ok = got == want
            if not ok:
                bad += 1
            print("%s %-15s %r" % ("ok  " if ok else "FAIL", name, line))
            if not ok:
                print("     기대: %r" % (want,))
                print("     결과: %r" % (got,))
    # 연산 이름 7개
    names = [n for n, _ in G2_OPS]
    want_names = ["byte_const_pm1", "guard_true", "guard_false", "len_pm1", "substr_pm1", "boundary_drop", "conj_drop"]
    if names != want_names:
        bad += 1
        print("FAIL G2_OPS 이름: %r" % names)
    # base: ast 로 읽은 OPS 가 mutate.py 와 같이 동작
    ops, skip = load_base()
    got = base_line_mutants("  x = a + 1;", ops)
    if "  x = a + 2;" not in got or not skip.match("  requires x > 0"):
        bad += 1
        print("FAIL base 연산 읽기: %r" % got)
    else:
        print("ok   base (mutate.py OPS/SKIP ast 로 읽음)")
    print("self-test:", "실패 %d" % bad if bad else "전부 통과")
    sys.exit(1 if bad else 0)


# ---------------------------------------------------------------- main
def main():
    args = sys.argv[1:]
    if "--self-test" in args:
        self_test()
    jobs_n, retry, only = 6, False, []
    if "--jobs" in args:
        i = args.index("--jobs")
        jobs_n = int(args[i + 1])
        del args[i:i + 2]
    if "--retry" in args:
        args.remove("--retry")
        retry = True
    if "--only" in args:
        i = args.index("--only")
        j = i + 1
        while j < len(args) and re.match(r"^q\d\d$", args[j]):
            only.append(args[j])
            j += 1
        del args[i:j]
    if not args or len(args) > 2:
        print("usage: mutate_ops.py OUT.json [SRC_DIR] [--jobs N] [--retry] [--only qNN ...] | --self-test")
        sys.exit(2)
    out = args[0]
    src_dir = args[1] if len(args) > 1 else DEFAULT_SRC

    sys.path.insert(0, HERE)
    import run as G  # 같은 폴더의 채점기(명세 2.3 인터페이스만 사용)

    base_ops, skip = load_base()
    work = tempfile.mkdtemp(prefix="g2m_src_")
    try:
        items = []
        for f in sorted(os.listdir(src_dir)):
            if not f.endswith(".pruv"):
                continue
            pid = os.path.splitext(f)[0]
            if pid not in G.P or (only and pid not in only):
                continue
            text = open(os.path.join(src_dir, f), encoding="utf-8").read()
            for n, (ln, old, new, mtext, ops) in enumerate(make_mutants(text, base_ops, skip)):
                p = os.path.join(work, "%s_%03d.pruv" % (pid, n))
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(mtext)
                items.append({"pid": pid, "line": ln, "from": old, "to": new, "ops": ops, "file": p})
        print("mutants:", len(items), flush=True)

        def run_v(t):
            i, c, inf = t
            return t, verify(c, items[i]["file"], inf)

        def run_t(i):
            return i, truth(G, items[i]["file"], items[i]["pid"])

        with ThreadPoolExecutor(jobs_n) as ex:
            tfut = [ex.submit(run_t, i) for i in range(len(items))]
            vfut = [ex.submit(run_v, (i, c, inf)) for i in range(len(items)) for c, inf in RUNS]
            for fu in vfut:
                (i, c, inf), r = fu.result()
                items[i][key(c, inf)] = r
            for fu in tfut:
                i, r = fu.result()
                items[i]["truth"] = r
        retried = 0
        if retry:
            again = [(i, c, inf) for i in range(len(items)) for c, inf in RUNS
                     if items[i][key(c, inf)]["verdict"] == "undecided"]
            retried = len(again)
            for t in again:
                (i, c, inf), r = run_v(t)
                r["first"] = items[i][key(c, inf)]
                items[i][key(c, inf)] = r
    finally:
        shutil.rmtree(work, ignore_errors=True)

    for it in items:
        it.pop("file")
    summary = summarize(items, retried)
    outdir = os.path.dirname(os.path.abspath(out))
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"summary": summary, "items": items}, fh, indent=1, ensure_ascii=False)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if summary["false_accepted"] or summary["crash"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
