#!/usr/bin/env python3
"""Pruv 컴파일러 두 판(기본 a=py, b=rs)의 차분 대조 (docs/M3_C4_SPEC.md 5절).

    python tests/diff_compilers.py [--b-path P](생략 시 pruvc-rs/target/release/pruvc, Windows는 .exe) [--backend rust|llvm|both]
        [--a py|rs] [--a-path P] [--b py|rs] [--b-path P] [--input FILE ...] [--flag F ...]
        [--only must_reject|examples|runtime|bench] [--jobs N] [--timeout 300] [--save-dir DIR]
    python tests/diff_compilers.py --replay CASE_DIR

같은 입력·플래그·backend 로 두 컴파일러를 입력마다 새 프로세스로 실행(a 다음 b, 한 작업자 안에서 순서대로 ->
동시 실행 프로세스 수는 --jobs(기본 os.cpu_count()) 이하)해 비교한다.
기본 입력: tests/must_reject/*.pruv, examples/*.pruv (default/no-verify/trust-callers),
tests/runtime/*.pruv (.json 의 flags_matrix·flags·contract_budget), bench/solutions/pruv_agg/*.pruv,
그리고 --input FILE (반복 가능, --flag 로 플래그 지정).

비교: 종료 코드 / stdout JSON 줄(개수·순서, stage,line,col,code 는 정확히 같아야 하고 message·fix 도 비교하되
작업 폴더·입력 경로·컴파일러 실행 파일 이름만 정규화) / 생성 파일(.rs, .ll, bindings) 바이트.
CRLF->LF 로만 같은 경우는 같음으로 세되 별도로 센다.

분류: same / diff / a_crash / b_crash / a_timeout / b_timeout / not_implemented
  crash  = 종료 코드 0·1·2 가 아님(3 내부 오류, 신호, 101 panic 등) 또는 실행 실패
  not_implemented = b 가 exit 2 로 'not implemented'·알 수 없는 옵션 류를 내고 a 는 exit 2 가 아닐 때(통과 아님)
  not_implemented 판정: b 의 stderr(stdout 아님)에서 NI_RE(단어 경계)로 찾는다.
  stdout JSON 의 'counterexample' 은 정확 비교에서 빼고 양쪽에 있는지만 비교한다. 값이 다르면 'cex_differs'
  표시만 남기고 diff 로 세지 않는다(5절: 반례 숫자는 바이트 동일을 요구하지 않음).
종료 코드: 0 전부 통과 / 1 diff·crash·timeout·입력 오류가 있음 / 2 --replay 사례 폴더 오류 /
  3 not_implemented 가 1건 이상이고 diff·crash·timeout 은 없음(통과 아님, '미구현 N건, 통과 아님' 출력).
  --allow-unimplemented 를 주면 3 대신 0 (출력 문구는 그대로).
"""
import argparse
import concurrent.futures as cf
import datetime
import glob
import json
import os
import re
import shutil
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import compiler_driver as CD  # noqa: E402

CLASSES = ["same", "diff", "a_crash", "b_crash", "a_timeout", "b_timeout", "not_implemented"]
FAILING = ("diff", "a_crash", "b_crash", "a_timeout", "b_timeout")
REQUIRED_KEYS = ("stage", "line", "col", "code")
COMPARED_TEXT_KEYS = ("message", "fix")
NI_RE = re.compile(r"\b(?:not (?:yet )?(?:implemented|supported)|unimplemented|미구현|unrecognized (?:arguments?|option)"
                   r"|unknown (?:option|argument|flag)|unexpected argument|no such (?:option|flag))\b", re.I)
CEX_KEY = "counterexample"  # 설계 5절: 반례 숫자는 바이트 동일을 요구하지 않음 -> 양쪽에 있는지만 비교
EXAMPLE_MODES = [("default", []), ("no-verify", ["--no-verify"]), ("trust-callers", ["--trust-callers"])]
SRC_T, OUT_T, BIND_T = "@SRC@", "@OUT@", "@BIND@"


# ---------------------------------------------------------------- 입력 목록

def build_cases(args):
    """[{name, src(절대 경로), flags}] (backend 는 나중에 곱한다). 입력 오류는 (cases, errors)."""
    cases, errors = [], []
    only = args.only

    def want(group):
        return only in (None, group)

    if want("must_reject"):
        for f in sorted(glob.glob(os.path.join(ROOT, "tests/must_reject/*.pruv"))):
            cases.append({"name": "must_reject/" + os.path.basename(f), "src": f, "flags": []})
    if want("examples"):
        for f in sorted(glob.glob(os.path.join(ROOT, "examples/*.pruv"))):
            for mode, flags in EXAMPLE_MODES:
                cases.append({"name": "examples/%s [%s]" % (os.path.basename(f), mode), "src": f, "flags": list(flags)})
    if want("runtime"):
        for j in sorted(glob.glob(os.path.join(ROOT, "tests/runtime/*.json"))):
            t = os.path.splitext(os.path.basename(j))[0]
            try:
                with open(j) as fh:
                    spec = json.load(fh)
                src = os.path.join(os.path.dirname(j), t + ".pruv")
                if not os.path.exists(src):
                    raise FileNotFoundError(src)
                budget = spec.get("contract_budget")
                extra = ["--contract-budget", str(budget)] if budget is not None else []
                matrix = spec.get("flags_matrix")
                rows = ([(list(fl), "[%s]" % (" ".join(fl) or "default")) for fl in matrix]
                        if matrix else [(list(spec.get("flags", [])), "")])
            except Exception as e:
                errors.append("runtime/%s: %r" % (t, e))
                continue
            for flags, label in rows:
                cases.append({"name": "runtime/" + t + (" " + label if label else ""), "src": src, "flags": flags + extra})
    if want("bench"):
        for f in sorted(glob.glob(os.path.join(ROOT, "bench/solutions/pruv_agg/*.pruv"))):
            cases.append({"name": "bench/pruv_agg/" + os.path.basename(f), "src": f, "flags": []})
    for f in args.input or []:
        if not os.path.isfile(f):
            errors.append("--input: no such file: %s" % f)
            continue
        cases.append({"name": "input/" + os.path.basename(f), "src": os.path.abspath(f), "flags": list(args.flag or [])})
    return cases, errors


# ---------------------------------------------------------------- 정규화·비교

def norm_replacements(workdir, src, prefix):
    """작업 폴더·입력 경로·컴파일러 실행 파일 이름/경로만 정규화한다."""
    reps = []
    for p, tag in ((workdir, "<WORK>"), (src, "<SRC>")):
        for v in {p, os.path.realpath(p)}:
            reps.append((v, tag))
    for tok in prefix:
        if os.sep in tok or tok.endswith((".py", ".exe")):
            for v in {tok, os.path.realpath(tok)}:
                reps.append((v, "<COMPILER>"))
    reps.sort(key=lambda r: -len(r[0]))
    reps = [r for r in reps if r[0]]
    if prefix and os.path.basename(prefix[-1]):
        # pruvc.py / 바이너리 이름: 단어 경계로만 바꾼다(다른 낱말 속 글자열을 건드리지 않게). 경로 치환 뒤에 적용.
        reps.append((re.compile(r"\b" + re.escape(os.path.basename(prefix[-1])) + r"\b"), "<COMPILER>"))
    return reps


def norm_text(s, reps):
    for old, new in reps:
        s = old.sub(new, s) if isinstance(old, re.Pattern) else s.replace(old, new)
    return s


def parse_stdout(text, reps):
    items = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except ValueError:
            d = None
        items.append(d if isinstance(d, dict) else norm_text(ln, reps))
    return items


def _norm_val(v, reps):
    return norm_text(v, reps) if isinstance(v, str) else v


def compare_stdout(ta, tb, reps_a, reps_b, cex_differs=None):
    """-> 차이 목록. 'counterexample' 은 양쪽 유무만 비교하고, 값이 다르면 cex_differs(list)에 표시만 남긴다."""
    ia, ib = parse_stdout(ta, reps_a), parse_stdout(tb, reps_b)
    out = []
    if len(ia) != len(ib):
        out.append("stdout line count %d vs %d" % (len(ia), len(ib)))
    for i, (x, y) in enumerate(zip(ia, ib)):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                vx, vy = x.get(k, "<absent>"), y.get(k, "<absent>")
                if k == CEX_KEY:
                    if (k in x) != (k in y):
                        out.append("stdout[%d].%s (other): %s vs %s" % (i, k, _short(vx), _short(vy)))
                    elif vx != vy and cex_differs is not None:
                        cex_differs.append(i)
                    continue
                if k not in REQUIRED_KEYS:
                    vx = _norm_val(vx, reps_a)
                    vy = _norm_val(vy, reps_b)
                if vx != vy:
                    kind = "required" if k in REQUIRED_KEYS else ("text" if k in COMPARED_TEXT_KEYS else "other")
                    out.append("stdout[%d].%s (%s): %s vs %s" % (i, k, kind, _short(vx), _short(vy)))
        elif x != y:
            out.append("stdout[%d]: %s vs %s" % (i, _short(x), _short(y)))
    return out


def _short(v, n=120):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, sort_keys=True)
    return repr(s if len(s) <= n else s[:n - 3] + "...")


def read_bytes(p):
    try:
        with open(p, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def first_diff(x, y):
    la = x.decode("utf-8", "replace").splitlines()
    lb = y.decode("utf-8", "replace").splitlines()
    for i in range(max(len(la), len(lb))):
        a = la[i] if i < len(la) else "<eof>"
        b = lb[i] if i < len(lb) else "<eof>"
        if a != b:
            return "line %d: %s vs %s" % (i + 1, _short(a, 80), _short(b, 80))
    return "bytes differ (same lines)"


def compare_files(names, dir_a, dir_b):
    """-> (details, crlf_only). 파일 있음/없음, 바이트 동일. CRLF->LF 로만 같으면 crlf_only."""
    details, crlf = [], False
    for n in names:
        x, y = read_bytes(os.path.join(dir_a, n)), read_bytes(os.path.join(dir_b, n))
        if x is None and y is None:
            continue
        if x is None or y is None:
            details.append("file %s: only written by %s" % (n, "b" if x is None else "a"))
        elif x != y:
            if x.replace(b"\r\n", b"\n") == y.replace(b"\r\n", b"\n"):
                crlf = True
            else:
                details.append("file %s differs (%d vs %d bytes), %s" % (n, len(x), len(y), first_diff(x, y)))
    return details, crlf


def classify(ra, rb, details):
    """a·b 결과와 비교 상세 -> 분류."""
    if ra.timed_out:
        return "a_timeout"
    if ra.kind == "crash":
        return "a_crash"
    if rb.timed_out:
        return "b_timeout"
    if rb.returncode == 2 and ra.returncode != 2 and NI_RE.search(rb.stderr):
        return "not_implemented"
    if rb.kind == "crash":
        return "b_crash"
    return "diff" if details else "same"


# ---------------------------------------------------------------- 한 사례 실행

def out_names(backend):
    return ("out.ll", "bind.rs") if backend == "llvm" else ("out.rs",)


def template_argv(drv, backend, flags):
    """@SRC@/@OUT@/@BIND@ 자리표시자가 든 argv 형판(저장·재실행용)."""
    extra = ["--rust-bindings", BIND_T] if backend == "llvm" else []
    return drv.argv(SRC_T, OUT_T, extra + list(flags), backend)


def fill(tmpl, src, out, bind):
    m = {SRC_T: src, OUT_T: out, BIND_T: bind}
    return [m.get(t, t) for t in tmpl]


def run_pair(spec, tmpl_a, tmpl_b, work, timeout):
    """한 사례를 a 다음 b 로 실행·비교. -> outcome dict (결과 객체와 작업 폴더 포함)."""
    backend = spec["backend"]
    names = out_names(backend)
    sides = {}
    for side, tmpl in (("a", tmpl_a), ("b", tmpl_b)):
        d = os.path.join(work, side)
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "out.ll" if backend == "llvm" else "out.rs")
        bind = os.path.join(d, "bind.rs")
        argv = fill(tmpl, spec["src"], out, bind)
        prefix = tmpl[:tmpl.index(SRC_T)]
        res = CD.run_argv(argv, timeout=timeout)
        sides[side] = {"argv": argv, "res": res, "dir": d, "reps": norm_replacements(d, spec["src"], prefix)}
    ra, rb = sides["a"]["res"], sides["b"]["res"]
    details = []
    if ra.returncode != rb.returncode:
        details.append("exit code %d vs %d" % (ra.returncode, rb.returncode))
    cex = []
    details += compare_stdout(ra.stdout, rb.stdout, sides["a"]["reps"], sides["b"]["reps"], cex)
    fdet, crlf = compare_files(names, sides["a"]["dir"], sides["b"]["dir"])
    details += fdet
    cls = classify(ra, rb, details)
    if cls == "not_implemented":
        details = details or ["b: " + (rb.stderr or rb.stdout).strip()[:200]]
    elif cls.endswith(("crash", "timeout")):
        bad = ra if cls.startswith("a_") else rb
        details = ["%s: exit %s%s %s" % (cls[0], bad.returncode, " (timeout)" if bad.timed_out else "",
                                          (bad.stderr or bad.stdout).strip()[-200:])] + details
    return {"cls": cls, "details": details, "crlf_only": crlf and cls == "same", "sides": sides, "names": names,
            "cex_differs": bool(cex)}


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def save_case(case_dir, spec, tmpl_a, tmpl_b, outcome, versions, case_id):
    os.makedirs(case_dir, exist_ok=True)
    shutil.copyfile(spec["src"], os.path.join(case_dir, "input.pruv"))
    sides = outcome["sides"]
    write_text(os.path.join(case_dir, "argv.json"), json.dumps(
        {"a": sides["a"]["argv"], "b": sides["b"]["argv"], "a_template": tmpl_a, "b_template": tmpl_b}, indent=1))
    write_text(os.path.join(case_dir, "version.json"), json.dumps(versions, indent=1))
    for s in ("a", "b"):
        sd = os.path.join(case_dir, s)
        os.makedirs(sd, exist_ok=True)
        r = sides[s]["res"]
        write_text(os.path.join(sd, "stdout.txt"), r.stdout)
        write_text(os.path.join(sd, "stderr.txt"), r.stderr)
        for n in outcome["names"]:
            p = os.path.join(sides[s]["dir"], n)
            if os.path.exists(p):
                shutil.copyfile(p, os.path.join(sd, n))
    write_text(os.path.join(case_dir, "timing.json"), json.dumps(
        {"a_seconds": round(sides["a"]["res"].elapsed, 3), "b_seconds": round(sides["b"]["res"].elapsed, 3)}, indent=1))
    write_text(os.path.join(case_dir, "case.json"), json.dumps(
        {"id": case_id, "name": spec["name"], "original_src": spec["src"], "flags": spec["flags"],
         "backend": spec["backend"], "classification": outcome["cls"], "details": outcome["details"],
         "cex_differs": outcome.get("cex_differs", False),
         "exit": {"a": sides["a"]["res"].returncode, "b": sides["b"]["res"].returncode}}, indent=1, ensure_ascii=False))


# ---------------------------------------------------------------- 재실행

def replay(case_dir, args):
    try:
        with open(os.path.join(case_dir, "case.json")) as fh:
            meta = json.load(fh)
        with open(os.path.join(case_dir, "argv.json")) as fh:
            argv = json.load(fh)
        with open(os.path.join(case_dir, "version.json")) as fh:
            versions = json.load(fh)
    except (OSError, ValueError) as e:
        print("replay: cannot read case folder %s: %r" % (case_dir, e))
        return 2
    src = os.path.abspath(os.path.join(case_dir, "input.pruv"))
    if not os.path.exists(src):
        print("replay: input.pruv missing in " + case_dir)
        return 2
    spec = {"name": meta["name"], "src": src, "flags": meta["flags"], "backend": meta["backend"]}
    print("replay %s  (saved classification: %s)" % (meta["name"], meta["classification"]))
    for s in ("a", "b"):
        print("  %s: %s" % (s, json.dumps(versions.get(s), ensure_ascii=False)))
    work = tempfile.mkdtemp(prefix="diffc_replay_")
    try:
        oc = run_pair(spec, argv["a_template"], argv["b_template"], work, args.timeout)
        print("result: %s%s%s [%s]" % (oc["cls"], " (CRLF-only)" if oc["crlf_only"] else "",
                                       " (cex_differs)" if oc["cex_differs"] else "", spec["backend"]))
        for d in oc["details"]:
            print("  - " + d)
        for s in ("a", "b"):
            r = oc["sides"][s]["res"]
            print("  %s: exit %s, %.2fs" % (s, r.returncode, r.elapsed))
        if oc["cls"] in FAILING:
            return 1
        if oc["cls"] == "not_implemented":
            print("미구현 1건, 통과 아님")
            return 0 if args.allow_unimplemented else 3
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- 본 실행

def main():
    ap = argparse.ArgumentParser(
        description="Pruv 컴파일러 두 판 차분 대조",
        epilog="종료 코드: 0 = 전부 같음(또는 --allow-unimplemented 와 함께 미구현만 있음); "
               "1 = diff/crash/timeout/입력 오류; 2 = --replay 사례 폴더 오류; "
               "3 = 미구현(not_implemented)만 있고 diff/crash/timeout 은 없음(통과 아님).")
    ap.add_argument("--allow-unimplemented", action="store_true",
                    help="미구현(not_implemented)만 있으면 종료 코드 3 대신 0 (출력의 '미구현 N건, 통과 아님'은 그대로)")
    ap.add_argument("--a", choices=["py", "rs"], default="py")
    ap.add_argument("--a-path", default=None)
    ap.add_argument("--b", choices=["py", "rs"], default="rs")
    ap.add_argument("--b-path", default=None)
    ap.add_argument("--backend", choices=["rust", "llvm", "both"], default="both")
    ap.add_argument("--input", action="append", default=[], metavar="FILE", help="추가 입력(반복 가능)")
    ap.add_argument("--flag", action="append", default=[], help="--input 파일에 줄 컴파일러 플래그(반복 가능)")
    ap.add_argument("--only", choices=["must_reject", "examples", "runtime", "bench"], default=None)
    ap.add_argument("--no-default-inputs", action="store_true", help="기본 입력 없이 --input 만")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--timeout", type=int, default=300, help="컴파일러 프로세스당 초(기본 300)")
    ap.add_argument("--save-dir", default=None, help="실패 사례 폴더 (기본 tests/_diff_fail/<시각>/)")
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--replay", default=None, metavar="CASE_DIR")
    args = ap.parse_args()
    if args.replay:
        return replay(args.replay, args)

    da = CD.make_driver(args.a, args.a_path)
    db = CD.make_driver(args.b, args.b_path)
    versions = {"a": da.version_info(), "b": db.version_info()}
    print("a: %s %s" % (da.name, da.path))
    print("b: %s %s" % (db.name, db.path))

    if args.no_default_inputs:
        args.only = "none"
    cases, errors = build_cases(args)
    backends = ["rust", "llvm"] if args.backend == "both" else [args.backend]
    specs = [dict(c, backend=b) for c in cases for b in backends]
    save_root = args.save_dir or os.path.join(HERE, "_diff_fail", datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    root = tempfile.mkdtemp(prefix="diffc_")
    counts = dict((c, 0) for c in CLASSES)
    per_backend = dict((b, dict((c, 0) for c in CLASSES)) for b in backends)
    crlf_count = 0
    cex_count = 0
    lock = threading.Lock()
    failed_dirs = []

    def job(idx, spec):
        tmpl_a = template_argv(da, spec["backend"], spec["flags"])
        tmpl_b = template_argv(db, spec["backend"], spec["flags"])
        work = os.path.join(root, "%05d" % idx)
        oc = run_pair(spec, tmpl_a, tmpl_b, work, args.timeout)
        case_id = "%05d_%s__%s" % (idx, re.sub(r"[^A-Za-z0-9._-]+", "_", spec["name"]).strip("_"), spec["backend"])
        if oc["cls"] in FAILING:
            cdir = os.path.join(save_root, oc["cls"] + "__" + case_id)
            try:
                save_case(cdir, spec, tmpl_a, tmpl_b, oc, versions, case_id)
                with lock:
                    failed_dirs.append(cdir)
            except OSError as e:
                oc["details"].append("could not save case folder: %r" % e)
        if not args.keep_work:
            shutil.rmtree(work, ignore_errors=True)
        return spec, oc

    try:
        with cf.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            futs = [pool.submit(job, i, s) for i, s in enumerate(specs)]
            for fut in futs:  # 원래 순서대로 출력
                try:
                    spec, oc = fut.result()
                except Exception as e:  # 장치 자체의 오류는 조용히 넘기지 않는다
                    errors.append("harness: %r" % (e,))
                    continue
                counts[oc["cls"]] += 1
                per_backend[spec["backend"]][oc["cls"]] += 1
                if oc["crlf_only"]:
                    crlf_count += 1
                if oc["cex_differs"]:
                    cex_count += 1
                    if oc["cls"] == "same":
                        print("cex_differs %s [%s]  -- counterexample 값이 다름(diff 로 세지 않음)" % (
                            spec["name"], spec["backend"]), flush=True)
                if oc["cls"] != "same":
                    print("%s %s [%s]  -- %s" % (oc["cls"].upper(), spec["name"], spec["backend"],
                                                 "; ".join(oc["details"])[:400]), flush=True)
    finally:
        if args.keep_work:
            print("작업 폴더: " + root)
        else:
            shutil.rmtree(root, ignore_errors=True)

    print("---- 요약 (a=%s, b=%s) ----" % (da.name, db.name))
    print("%-16s %6s" % ("분류", "건수") + "".join(" %8s" % b for b in backends))
    for c in CLASSES:
        print("%-16s %6d" % (c, counts[c]) + "".join(" %8d" % per_backend[b][c] for b in backends))
    print("TOTAL %d" % sum(counts.values()))
    if crlf_count:
        print("CRLF->LF 정규화로만 같음: %d건 (same 에 포함)" % crlf_count)
    if cex_count:
        print("cex_differs: counterexample 값만 다른 사례 %d건 (분류에 영향 없음)" % cex_count)
    for e in errors:
        print("입력/장치 오류: " + e)
    if failed_dirs:
        print("실패 사례 %d건 저장: %s  (재실행: --replay <폴더>)" % (len(failed_dirs), save_root))
    bad = sum(counts[c] for c in FAILING) + len(errors)
    if counts["not_implemented"]:
        print("미구현 %d건, 통과 아님" % counts["not_implemented"])
    if bad:
        return 1
    if counts["not_implemented"] and not args.allow_unimplemented:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
