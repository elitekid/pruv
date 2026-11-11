# -*- coding: utf-8 -*-
"""G2 Q2 실행 측정 (docs/G2_Q2_IMPL.md 3·4절).
python bench/g2/measure_run.py arrays  OUT.json [--reps 5] [--compiler rs|py]
python bench/g2/measure_run.py strings OUT.json [--reps 7] [--sizes 1000000,8000000] [--compiler rs|py]
arrays : perf/arr_*.pruv 를 두 뒷단의 단독 실행 파일로 빌드해 R회 실행(벽시계·최대 상주 메모리·출력 확인).
         rust 뒷단 = 생성 Rust 를 mod 로 담은 한 줄 main 을 rustc, llvm 뒷단 = `pruvc --emit exe`(rs 판만 지원).
strings: perf/str_ops.pruv 를 두 뒷단으로 만들어 Rust 드라이버(run.py TEMPLATE 방식)에서 함수 호출 시간을 잰다.
실패(컴파일 오류·틀린 값)가 하나라도 있으면 끝에 종료 코드 1."""
import json, os, re, statistics, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run as g2run  # noqa: E402

PERF = os.path.join(HERE, "perf")
ARR = {"i64": ("arr_i64", "10000000"), "u8": ("arr_u8", "10000000"),
       "bool": ("arr_bool", "10000000"), "empty": ("arr_empty", "0")}
FAILED = []


def fail(msg):
    FAILED.append(msg)
    print("FAIL: " + msg)


def compile_errors(c):
    """compile_pruv 결과의 오류 줄들(JSON 오류가 있으면 그것, 없으면 stderr 끝)."""
    lines = [json.dumps(e, ensure_ascii=False)[:400] for e in c["errors"][:5]]
    return lines or [c["stderr"][-400:]]


def run_rustc(main_rs, exe, extra):
    r = subprocess.run([g2run.RUSTC, "-O", "--edition", "2021", "-C", "target-cpu=native", main_rs, "-o", exe] + extra,
                       capture_output=True, encoding="utf-8", errors="replace")
    return None if r.returncode == 0 else r.stderr[-1500:].splitlines()


def sub_dir(work, name):
    d = os.path.join(work, name)
    os.makedirs(d, exist_ok=True)
    return d


def med(v):
    return statistics.median(v) if v else None


# ---------------------------------------------------------------- arrays
def build_arr(compiler, backend, stem, work):
    """단독 실행 파일을 만든다. (exe, None) 또는 (None, 오류 줄 목록)."""
    src = os.path.join(PERF, stem + ".pruv")
    d = sub_dir(work, backend)
    exe = os.path.join(d, stem + "_bin")
    if backend == "rust":
        c = g2run.compile_pruv(compiler, src, d, "rust")
        if c["rc"] != 0:
            return None, compile_errors(c)
        main_rs = os.path.join(d, stem + "_main.rs")
        with open(main_rs, "w", encoding="utf-8") as f:
            f.write('#![allow(dead_code, unused_imports)]\n#[path = "%s"] mod sol;\nfn main() { sol::main(); }\n'
                    % c["rs"])
        err = run_rustc(main_rs, exe, [])
        return (None, err) if err else (exe, None)
    if compiler != "rs":
        return None, ["llvm 단독 실행 파일(--emit exe)은 Rust 판 pruvc(--compiler rs)만 지원"]
    r = subprocess.run([g2run.PRUVC_RS, src, "--emit", "exe", "-o", exe, "-mcpu=native"],
                       capture_output=True, encoding="utf-8", errors="replace", timeout=600)
    if r.returncode != 0:
        return None, ((r.stdout + r.stderr)[-1500:]).splitlines()
    return exe, None


def time_once(exe):
    flag = "-l" if sys.platform == "darwin" else "-v"
    cmd = ["/usr/bin/time", flag, exe] if os.path.exists("/usr/bin/time") else [exe]
    t0 = time.perf_counter()
    r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=600)
    dt = time.perf_counter() - t0
    rss = None
    for line in r.stderr.splitlines():
        m = re.match(r"^\s*(\d+)\s+maximum resident set size", line)
        if m:
            rss = int(m.group(1))  # macOS: 바이트
        m = re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", line)
        if m:
            rss = int(m.group(1)) * 1024
    return dt, rss, r.stdout.strip(), r.returncode


def cmd_arrays(out, reps, compiler):
    work = tempfile.mkdtemp(prefix="pruvperf_")
    print("work dir:", work)
    res = {"meta": {"reps": reps, "compiler": compiler, "platform": sys.platform, "work": work},
           "backends": {}, "ratios": {}}
    for backend in ("rust", "llvm"):
        bres = res["backends"][backend] = {}
        for key, (stem, want) in ARR.items():
            exe, err = build_arr(compiler, backend, stem, work)
            if err:
                bres[key] = {"compile_error": err}
                fail("arrays %s %s: %s" % (backend, stem, " | ".join(err)[:300]))
                continue
            times, rsss, outs, ok = [], [], [], True
            for _ in range(reps):
                dt, rss, o, rc = time_once(exe)
                times.append(dt); outs.append(o)
                if rss is not None:
                    rsss.append(rss)
                if rc != 0 or o != want:
                    ok = False
            bres[key] = {"times": times, "median_s": med(times), "rss": rsss, "median_rss_bytes": med(rsss),
                         "stdout": outs, "expected": want, "output_ok": ok}
            if not ok:
                fail("arrays %s %s: output %r (expected %s)" % (backend, stem, outs[:2], want))
            print("%-5s %-9s median %.3fs rss %s ok=%s" % (backend, stem, med(times), med(rsss), ok))
        rt = {}
        for k in ("u8", "bool"):
            a, b = bres.get(k, {}), bres.get("i64", {})
            for field, name in (("median_s", "time"), ("median_rss_bytes", "rss")):
                if a.get(field) and b.get(field):
                    rt["%s_over_i64_%s" % (k, name)] = a[field] / b[field]
        if bres.get("empty", {}).get("median_s") is not None:
            rt["empty_median_s"] = bres["empty"]["median_s"]
            rt["empty_median_rss_bytes"] = bres["empty"].get("median_rss_bytes")
        res["ratios"][backend] = rt
    return res


# ---------------------------------------------------------------- strings
DRIVER = r'''
#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::hint::black_box;
use std::time::Instant;
@RAW_DECL@

fn build(b: usize) -> String {
    let unit = "abcde\u{e9}\u{4e2d}"; // 10 바이트: ASCII 5 + 다중 바이트 5
    let mut s = String::with_capacity(b);
    while s.len() + unit.len() <= b { s.push_str(unit); }
    while s.len() < b { s.push('a'); }
    s
}

fn bench<F: FnMut() -> i64>(name: &str, bytes: usize, reps: usize, want: i64, mut f: F) {
    black_box(f());
    let mut t: Vec<u128> = Vec::new();
    let mut last = 0i64;
    for _ in 0..reps {
        let st = Instant::now();
        last = black_box(f());
        t.push(st.elapsed().as_nanos());
    }
    t.sort();
    println!("M {} {} {} {}", name, bytes, t[t.len() / 2], last);
    println!("CHECK {} {} {}", name, bytes, if last == want { "ok" } else { "bad" });
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let reps: usize = args[1].parse().unwrap();
    for sz in args[2].split(',') {
        let b: usize = sz.parse().unwrap();
        let s = build(b);
        assert!(s.len() == b);
        let v: Vec<u8> = s.as_bytes().to_vec();
        let mut lo = b / 4; while !s.is_char_boundary(lo) { lo += 1; }
        let mut hi = 3 * b / 4; while !s.is_char_boundary(hi) { hi += 1; }
        println!("INFO {} {} {}", b, lo, hi);
        let hi_cnt = s.bytes().filter(|&x| x >= 128).count() as i64;
        let bl = b as i64;
        bench("scan_str", b, reps, hi_cnt, || { let r: i64 = sol::scan_str(black_box(&s)); r });
        bench("scan_u8", b, reps, hi_cnt, || { let r: i64 = sol::scan_u8(black_box(&v)); r });
        bench("mid", b, reps, (hi - lo) as i64, || {
            let t = sol::mid(black_box(&s), black_box(lo as i64), black_box(hi as i64)); black_box(&t); t.len() as i64 });
        bench("dup", b, reps, bl, || { let t = sol::dup(black_box(&s)); black_box(&t); t.len() as i64 });
        bench("blen", b, reps, bl, || { let r: i64 = sol::blen(black_box(&s)); r });
        bench("blen_u8", b, reps, bl, || { let r: i64 = sol::blen_u8(black_box(&v)); r });
        @RAW_BENCH@
    }
}
'''


def build_str_driver(compiler, backend, work):
    src = os.path.join(PERF, "str_ops.pruv")
    d = sub_dir(work, "str_" + backend)
    c = g2run.compile_pruv(compiler, src, d, backend)
    if c["rc"] != 0:
        return None, compile_errors(c)
    extra = []
    if backend == "llvm":
        extra, err = g2run.build_llvm_objects(os.path.abspath(c["ll"]), "str_ops", d)
        if err:
            return None, err.splitlines()[-8:]
    main_rs = os.path.join(d, "driver_main.rs")
    with open(main_rs, "w", encoding="utf-8") as f:
        raw = backend == "llvm"
        f.write(DRIVER.replace("@SOL@", c["rs"])
                .replace("@RAW_DECL@", 'extern "C" { fn pruv_abi_blen(p: *const u8, n: i64) -> i64; }' if raw else "")
                .replace("@RAW_BENCH@", 'bench("blen_raw", b, reps, bl, || { let r: i64 = unsafe { '
                         'pruv_abi_blen(black_box(s.as_ptr()), black_box(s.len() as i64)) }; r });' if raw else ""))
    exe = os.path.join(d, "driver_bin")
    err = run_rustc(main_rs, exe, extra)
    return (None, err) if err else (exe, None)


def parse_driver(text):
    """M/CHECK/INFO 줄 -> {size: {"info": (lo, hi), "fn": {name: {...}}}}"""
    sizes = {}
    for line in text.splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == "INFO":
            sizes.setdefault(int(p[1]), {"fn": {}})["info"] = [int(p[2]), int(p[3])]
        elif p[0] == "M":
            e = sizes.setdefault(int(p[2]), {"fn": {}})["fn"].setdefault(p[1], {})
            e["median_ns"] = int(p[3]); e["result"] = int(p[4]); e["ns_per_byte"] = int(p[3]) / int(p[2])
        elif p[0] == "CHECK":
            sizes.setdefault(int(p[2]), {"fn": {}})["fn"].setdefault(p[1], {})["check"] = p[3]
    return sizes


def derive(b, sz):
    f, d = sz["fn"], {}
    g = lambda n: f.get(n, {}).get("median_ns")
    # The typed &str binding (`__typed`) does not re-check UTF-8; only the raw C entry does (G2_SPEC 5.4).
    # llvm: raw entry pruv_abi_blen (checks UTF-8) minus typed blen = cost of pruv_check_utf8.
    if g("blen_raw") is not None and g("blen") is not None:
        d["utf8_check_ns_per_byte"] = (g("blen_raw") - g("blen")) / b
    if g("scan_str") and g("scan_u8"):
        d["scan_str_vs_u8"] = g("scan_str") / g("scan_u8")
    lo, hi = sz.get("info", [0, 0])
    # mid/dup include the allocation and, on llvm, the binding's UTF-8 check of the returned str.
    if g("mid") is not None and hi > lo:
        d["substr_ns_per_copied_byte"] = g("mid") / (hi - lo)
    if g("dup") is not None:
        d["copy_ns_per_byte"] = g("dup") / b
    return d


def cmd_strings(out, reps, sizes, compiler):
    work = tempfile.mkdtemp(prefix="pruvperf_")
    print("work dir:", work)
    res = {"meta": {"reps": reps, "sizes": sizes, "compiler": compiler, "platform": sys.platform, "work": work},
           "backends": {}}
    for backend in ("rust", "llvm"):
        exe, err = build_str_driver(compiler, backend, work)
        if err:
            res["backends"][backend] = {"compile_error": err}
            fail("strings %s: %s" % (backend, " | ".join(err)[:300]))
            continue
        try:
            r = subprocess.run([exe, str(reps), ",".join(str(s) for s in sizes)], capture_output=True,
                               encoding="utf-8", errors="replace", timeout=1800)
        except subprocess.TimeoutExpired:
            res["backends"][backend] = {"error": "timeout"}
            fail("strings %s: driver timeout" % backend)
            continue
        parsed = parse_driver(r.stdout)
        if r.returncode != 0:
            fail("strings %s: driver exit %d %s" % (backend, r.returncode, r.stderr[-200:]))
        bres = {}
        for b, sz in sorted(parsed.items()):
            sz["derived"] = derive(b, sz)
            for n, e in sz["fn"].items():
                if e.get("check") != "ok":
                    fail("strings %s %s B=%d: check %s" % (backend, n, b, e.get("check")))
            bres[str(b)] = sz
            print("%-5s B=%-9d %s" % (backend, b, json.dumps(sz["derived"])))
        if not bres:
            fail("strings %s: driver printed no measurements" % backend)
        res["backends"][backend] = bres
    return res


def main():
    args = sys.argv[1:]
    opts = {"--reps": None, "--sizes": "1000000,8000000", "--compiler": "rs"}
    for o in opts:
        if o in args:
            i = args.index(o)
            if i + 1 >= len(args):
                print(__doc__); sys.exit(2)
            opts[o] = args[i + 1]
            del args[i:i + 2]
    if len(args) != 2 or args[0] not in ("arrays", "strings") or opts["--compiler"] not in ("rs", "py"):
        print(__doc__); sys.exit(2)
    mode, outp = args
    reps = int(opts["--reps"] or (5 if mode == "arrays" else 7))
    if mode == "arrays":
        res = cmd_arrays(outp, reps, opts["--compiler"])
    else:
        res = cmd_strings(outp, reps, [int(x) for x in opts["--sizes"].split(",")], opts["--compiler"])
    res["failures"] = FAILED
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print("wrote %s; failures: %d" % (outp, len(FAILED)))
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
