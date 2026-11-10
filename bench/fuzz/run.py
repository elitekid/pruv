#!/usr/bin/env python3
"""Pruv 컴파일러 차분 퍼징 실행기 (표준 라이브러리만, Python 3.9).

    python bench/fuzz/run.py [--seed 1] [--programs 100] [--inputs 8] [--max-candidates 400]
                             [--rejected-sample 30] [--jobs N] [--batch 25] [--out DIR] [--keep-work]
    python bench/fuzz/run.py --replay DIR_OR_PRUVFILE
    (모든 형태에 [--compiler py|rs] [--compiler-path PATH] 사용 가능, tests/compiler_driver.py; 기본 rs)

약속: 검증기가 받아들인 프로그램(pruvc 기본 모드 exit 0)은 requires를 만족하는 모든 입력에서
범위 밖 인덱스/오버플로 없이 ensures가 성립하고 출력이 오라클과 같다. 모드마다 자기 오라클과 비교한다
(증명 모드는 mode="proof", 안전 모드는 mode="safe"). 기대 결과가 같은 모드끼리는 stdout, 종료 코드,
`pruv: ...` 줄이 정확히 같고, rust-X == llvm-X 는 항상 같다. 증명·안전 모드는 안쪽 호출의 실행 requires가
i128 한계에 닿을 때처럼 오라클 결과가 다르면 정당하게 달라질 수 있다.
검증된 프로그램의 실행 requires 검사는 정의역 밖(`requires undefined`)에 닿지 않는다(i128 한계만 예외).

빌드: macOS는 새 실행 파일의 첫 실행마다 약 0.33초를 직렬로 쓰므로, 프로그램 --batch개를 한 실행
파일(백엔드마다 1개, 증명·안전 모듈을 함께)에 묶는다. LLVM 모듈은 `pruv_abi_` 기호에 고유 접두사를
붙인 사본으로 링크하고 `pruv_host_*`의 #[no_mangle]은 첫 모듈에만 둔다.
"""
import argparse
import concurrent.futures as cf
import json
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import generate  # noqa: E402
import oracle  # noqa: E402

CPU_FLAG = "-mcpu=native" if platform.machine().lower() in ("arm64", "aarch64") else "-march=native"
sys.path.append(os.path.join(ROOT, "tests"))
import compiler_driver as CD  # noqa: E402

DRIVER = None  # compiler under test (--compiler/--compiler-path); set in main(), None -> rs
RUSTC = shutil.which("rustc") or os.path.expanduser("~/.cargo/bin/rustc")
CLANG = shutil.which("clang") or "/usr/bin/clang"
RUNTIME_C = os.path.join(ROOT, "pruvc/runtime.c")

I64_MIN = -(1 << 63)
TIMEOUT_RC = -999
FAULT_KINDS = {"oob", "overflow", "div_domain", "requires_violated", "requires_undefined"}
MODES = [("rust-proof", "rust", False), ("rust-safe", "rust", True),
         ("llvm-proof", "llvm", False), ("llvm-safe", "llvm", True)]
SAFE_MODES = [m for m in MODES if m[2]]


# ---------------------------------------------------------------- 하위 프로세스

def run_cmd(cmd, timeout):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return TIMEOUT_RC, "", "timeout after %ss" % timeout


def parse_diags(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict):
                out.append(d)
    return out


def driver():
    global DRIVER
    if DRIVER is None:
        DRIVER = CD.default_driver()
    return DRIVER


def write(path, text):
    with open(path, "w") as fh:
        fh.write(text)


def build_runtime(work):
    rt_o = os.path.join(work, "runtime.o")
    rc, so, se = run_cmd([CLANG, "-O2", CPU_FLAG, "-std=c11", "-DPRUV_RUST_ALLOCATOR",
                          "-c", RUNTIME_C, "-o", rt_o], 300)
    if rc != 0:
        raise RuntimeError("clang (runtime.c) 실패: " + se[-400:])
    return rt_o


# ---------------------------------------------------------------- 드라이버

def rust_int(v):
    if v == I64_MIN:
        return "i64::MIN"
    if v < 0:
        return "(%di64)" % v
    return "%di64" % v


def deep_copy_arg(v):
    """인자 복사: 배열(list)과 모든 dict(Option/Result, 구조체, 열거형)를 재귀로 복사한다."""
    if isinstance(v, list):
        return list(v)
    if isinstance(v, dict):
        return dict((k, deep_copy_arg(x)) for k, x in v.items())
    return v


def rust_option_result(ty, v):
    """Option/Result dict({"tag": "Some", "v": 3} 등) -> Rust 리터럴, black_box 로 감싸 상수 접힘을 막는다."""
    tag = v.get("tag") if isinstance(v, dict) else None
    if ty == "Option<i64>":
        if tag == "None":
            lit = "None"
        elif tag == "Some":
            lit = "Some(%s)" % rust_int(v["v"])
        else:
            raise ValueError("Option<i64> 인자 형식이 아님: %r" % (v,))
        return "std::hint::black_box::<Option<i64>>(%s)" % lit
    if tag not in ("Ok", "Err"):
        raise ValueError("Result<i64> 인자 형식이 아님: %r" % (v,))
    return "std::hint::black_box::<Result<i64, i64>>(%s(%s))" % (tag, rust_int(v["v"]))


def rust_value(mod, v):
    """값 dict 를 Rust 식으로(재귀). 구조체/열거형 경로는 `<mod>::` 접두어(Rust·LLVM 모두 생성 모듈 최상단에
    pub 타입이 있다: pruvc/codegen.py emit_public_types, llvmgen 도 같은 함수를 쓴다)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return rust_int(v)
    if isinstance(v, dict):
        if "struct" in v:
            if not v["fields"]:
                return "%s::%s {}" % (mod, v["struct"])
            return "%s::%s { %s }" % (mod, v["struct"], ", ".join(
                "%s: %s" % (f, rust_value(mod, x)) for f, x in v["fields"].items()))
        if "enum" in v:
            if not v["fields"]:
                return "%s::%s::%s" % (mod, v["enum"], v["variant"])
            return "%s::%s::%s(%s)" % (mod, v["enum"], v["variant"],
                                       ", ".join(rust_value(mod, x) for x in v["fields"].values()))
        tag = v.get("tag")
        if tag == "None":
            return "None"
        if tag in ("Some", "Ok", "Err"):
            return "%s(%s)" % (tag, rust_value(mod, v["v"]))
    raise ValueError("값 형식을 모름: %r" % (v,))


def batch_driver_source(specs):
    """specs: [(모듈 이름, 생성된 .rs 절대 경로, params, inputs, 시작 id)] -> main.rs 문자열.
    argv[1] = 평탄한 실행 id. 각 (프로그램, 모드, 입력)에 id가 하나씩 배정된다.
    params 타입 문자열: "i64", "bool", "array", "Option<i64>", "Result<i64>", 그 밖은 사용자 타입 이름
    (구조체/열거형 값 dict 를 `<모듈>::Point { .. }` 식으로 만든다). 출력은 모두 `{:?}`."""
    L = ['#![allow(dead_code, unused_imports)]']
    for modname, gen_rs, params, inputs, start in specs:
        L.append('#[path = "%s"] mod %s;' % (gen_rs, modname))
    L += ['fn main() {',
          '    let k: usize = std::env::args().nth(1).unwrap().parse().unwrap();', '    match k {']
    for modname, gen_rs, params, inputs, start in specs:
        for idx, args in enumerate(inputs):
            decl, parts = [], []
            for j, ((name, ty), v) in enumerate(zip(params, args)):
                if ty == "array":
                    decl.append("let a%d: Vec<i64> = vec![%s];" % (j, ", ".join(rust_int(e) for e in v)))
                    parts.append("&a%d" % j)
                elif ty == "bool":
                    parts.append("std::hint::black_box(%s)" % ("true" if v else "false"))
                elif ty in ("Option<i64>", "Result<i64>"):
                    parts.append(rust_option_result(ty, v))
                elif ty == "i64":
                    parts.append("std::hint::black_box(%s)" % rust_int(v))
                elif isinstance(v, dict) and ("struct" in v or "enum" in v):
                    parts.append("std::hint::black_box(%s)" % rust_value(modname, v))
                else:
                    raise ValueError("지원하지 않는 매개변수 타입: %r" % (ty,))
            L.append('        %d => { %s println!("{:?}", %s::f(%s)); }'
                     % (start + idx, " ".join(decl), modname, ", ".join(parts)))
    L += ["        _ => {}", "    }", "}"]
    return "\n".join(L) + "\n"


def signature_from_src(src):
    # 반환형: i64 / bool / [i64] / () / Option<i64> / Result<i64> / 사용자 타입 (꺾쇠·대괄호 허용)
    m = re.search(r"fn\s+f\s*\(([^)]*)\)\s*->\s*(\[\s*i64\s*\]|\(\s*\)|\w+(?:\s*<[^<>]*>)?)", src)
    if not m:
        raise ValueError("fn f(...) -> T 시그니처를 찾지 못함")
    params = []
    for p in [s.strip() for s in m.group(1).split(",") if s.strip()]:
        name, ty = [t.strip() for t in p.split(":", 1)]
        ty = re.sub(r"\s+", "", ty)
        params.append([name, "array" if ty.startswith("[") else ty])
    return params, re.sub(r"\s+", "", m.group(2))


# ---------------------------------------------------------------- 1~2단계: 생성 + 검증

def phase_a(case, work):
    rec = {"name": case["name"], "src": case["src"], "params": case["params"], "ret": case["ret"],
           "case": case, "failures": [], "logs": {}, "status": None, "codes": []}
    d = os.path.join(work, case["name"])
    os.makedirs(d, exist_ok=True)
    rec["dir"] = d
    pruv = os.path.join(d, "case.pruv")
    write(pruv, case["src"])
    rec["pruv"] = pruv
    try:
        rec["prog"] = oracle.parse_program(case["src"])
    except oracle.OracleUnsupported as e:
        rec["status"], rec["detail"] = "oracle_unsupported", str(e)
        return rec
    except Exception as e:  # OracleParseError 포함
        rec["status"], rec["detail"] = "oracle_parse_error", "%s: %s" % (type(e).__name__, e)
        return rec
    rec["nv_rs"] = os.path.join(d, "rust_safe_gen.rs")
    rec["ver_rs"] = os.path.join(d, "rust_proof_gen.rs")
    # pruvc 한 번 호출이 Rust 출력과 LLVM 출력(.ll + bindings)을 함께 만든다 (--also-llvm).
    # 재사용된 작업 폴더의 옛 파일을 집어 쓰지 않도록 호출 전에 출력 경로를 먼저 지운다.
    llvm_paths = {}
    for lname in ("llvm-safe", "llvm-proof"):
        llvm_paths[lname] = (os.path.join(d, lname + ".ll"), os.path.join(d, lname + "_gen.rs"))
    rec["llvm_files"] = {}

    def clear_outputs(paths):
        for p in paths:
            if os.path.exists(p):
                os.remove(p)

    sll, srs = llvm_paths["llvm-safe"]
    clear_outputs([rec["nv_rs"], sll, srs])
    rc, so, se = run_cmd(driver().argv(pruv, rec["nv_rs"], ["--no-verify", "--also-llvm", sll, srs], "rust"), 120)
    if rc == 0:
        rec["llvm_files"]["llvm-safe"] = (sll, srs)
    rec["logs"]["no-verify"] = "exit %d\n%s%s" % (rc, so, se)
    if rc == TIMEOUT_RC:
        rec["status"] = "failed"
        rec["failures"].append({"kind": "timeout", "detail": "pruvc --no-verify (rust+llvm) exit %d: %s"
                                                          % (rc, (so + se).strip()[-400:])})
        return rec
    if rc not in (0, 1):  # 음수(신호/크래시), 2(사용법), 3(내부 오류) 등은 모두 실패
        rec["status"] = "failed"
        rec["failures"].append({"kind": "internal_error", "detail": "pruvc --no-verify (rust+llvm) exit %d: %s"
                                                          % (rc, (so + se).strip()[-400:])})
        return rec
    if rc == 1:
        diags = parse_diags(so) + parse_diags(se)
        stages = set(x.get("stage") for x in diags)
        if diags and stages <= {"parse", "type", "effect"}:
            rec["status"] = "generator_invalid"
        else:
            rec["status"] = "failed"
            rec["failures"].append({"kind": "internal_error",
                                    "detail": "pruvc --no-verify exit 1, 진단 stage=%s"
                                              % (sorted(str(s) for s in stages) or "없음")})
        return rec
    pll, prs = llvm_paths["llvm-proof"]
    clear_outputs([rec["ver_rs"], pll, prs])
    rc, so, se = run_cmd(driver().argv(pruv, rec["ver_rs"], ["--also-llvm", pll, prs], "rust"), 120)
    rec["logs"]["verify"] = "exit %d\n%s%s" % (rc, so, se)
    if rc == 0:
        rec["status"] = "verified"
        rec["llvm_files"]["llvm-proof"] = (pll, prs)
    elif rc == 1:
        rec["status"] = "rejected"
        diags = parse_diags(so) + parse_diags(se)
        rec["codes"] = sorted(set("%s:%s" % (x.get("stage"), x.get("code")) for x in diags)) or ["unknown"]
        if any(x.get("stage") == "internal" for x in diags):
            rec["failures"].append({"kind": "internal_error", "detail": "verifier error JSON with stage internal"})
    else:
        rec["status"] = "failed"
        rec["failures"].append({"kind": "timeout" if rc == TIMEOUT_RC else "internal_error",
                                "detail": "pruvc (verify, rust+llvm) exit %d: %s"
                                          % (rc, (so + se).strip()[-400:])})
    return rec


# ---------------------------------------------------------------- 3~4단계: 입력 선택 + clang 준비 + 빌드

def safe_check(prog, args):
    try:
        return oracle.check_requires(prog, "f", [deep_copy_arg(a) for a in args])
    except Exception:
        return "error"


def choose_inputs(rec, args, fixed=None):
    prog = rec["prog"]
    rec["input_errors"] = 0
    if fixed is not None:
        inputs = fixed
    else:
        rng = random.Random("%s:%s:inputs" % (args.seed, rec["name"]))
        cands = generate.candidate_inputs(rec["case"], rng, 300)
        ok_l, bad_l, seen = [], [], set()
        n_err, n_cand = 0, 0
        for a in cands:
            key = json.dumps(a, sort_keys=True)   # Option/Result dict 도 같은 키
            if key in seen:
                continue
            seen.add(key)
            n_cand += 1
            st = safe_check(prog, a)
            if st == "error":
                n_err += 1      # 조용히 버리지 않고 센다
                continue
            (ok_l if st == "ok" else bad_l).append(a)
        rec["input_errors"] = n_err
        if n_cand and n_err == n_cand:
            rec["failures"].append({"kind": "harness_error",
                                    "detail": "입력 후보 %d개 전부 requires 검사에서 예외(error)" % n_cand})
        n_ok = max(1, args.inputs * 3 // 4)
        n_bad = max(0, args.inputs - n_ok)
        sel_ok, sel_bad = ok_l[:n_ok], bad_l[:n_bad]
        if len(sel_ok) < n_ok:
            sel_bad = bad_l[:n_bad + (n_ok - len(sel_ok))]
        elif len(sel_bad) < n_bad:
            sel_ok = ok_l[:n_ok + (n_bad - len(sel_bad))]
        inputs = sel_ok + sel_bad
        if not inputs and not any(f.get("kind") == "harness_error" for f in rec["failures"]):
            rec["failures"].append({"kind": "harness_error", "detail": "고른 입력이 0개 (후보 %d개, error %d개)"
                                    % (n_cand, n_err)})
    rec["inputs"] = inputs
    rec["req"] = [safe_check(prog, a) for a in inputs]
    rec["input_errors"] += sum(1 for r in rec["req"] if r == "error")
    rec["oracle_safe"] = [oracle_run(prog, a, "safe") for a in inputs]
    if rec["status"] == "verified":
        rec["oracle_proof"] = [oracle_run(prog, a, "proof") for a in inputs]
    rec["oracle"] = rec["oracle_safe"]  # 호환용: 안전 모드 결과


def oracle_run(prog, a, mode):
    """오라클 한 번 실행. mode 인자를 모르는 옛 오라클이면 mode 없이 부른다."""
    def fresh():
        return [deep_copy_arg(v) for v in a]
    try:
        try:
            return oracle.run(prog, "f", fresh(), mode=mode)
        except TypeError:
            return oracle.run(prog, "f", fresh())
    except Exception as e:
        return {"kind": "oracle_error", "value": None, "detail": repr(e),
                "output": [], "contract_failures": []}


NO_MANGLE_RE = re.compile(r"^[ \t]*#\[no_mangle\][ \t]*\n", re.M)


def prep_llvm(rec, mode, rt_o):
    """phase_a 가 pruvc --also-llvm 로 만든 .ll/bindings(rec['llvm_files'][name])를 읽어
    심볼을 고유하게 바꾼 .ll 사본 -> clang .o. pruvc 는 여기서 부르지 않는다.
    -> (art 또는 None, 실패 종류 또는 None, 오류 문장 또는 None). 원본 .ll/.rs는 rec['dir']에 그대로 둔다.
    건전성: proof 모드 산출물은 rec['status'] == 'verified' 일 때만 쓴다."""
    name, backend, safe = mode
    d = rec["dir"]
    tag = "p%dl%d" % (rec["idx"], 1 if safe else 0)
    if not safe and rec["status"] != "verified":
        return None, "harness_error", "%s: proof 모드인데 status=%s (verified 아님)" % (name, rec["status"])
    files = rec.get("llvm_files", {}).get(name)
    if not files or not os.path.exists(files[0]) or not os.path.exists(files[1]):
        return None, "harness_error", ("%s: phase_a 가 만든 LLVM 출력 없음 (llvm_files=%s)"
                                       % (name, files))
    ll, gen = files
    with open(ll) as fh:
        ll_text = fh.read()
    with open(gen) as fh:
        rs_text = fh.read()
    n_ll = ll_text.count("@pruv_abi_")
    n_rs = rs_text.count("pruv_abi_")
    if n_ll < 1 or n_rs < 1:
        return None, "harness_error", ("%s: 심볼 재작성 대상 없음 (.ll @pruv_abi_ %d개, bindings pruv_abi_ %d개)"
                                       % (name, n_ll, n_rs))
    rw_ll = os.path.join(d, name + "_rw.ll")
    write(rw_ll, ll_text.replace("@pruv_abi_", "@pruv_abi_%s_" % tag))
    rs_new = rs_text.replace("pruv_abi_", "pruv_abi_%s_" % tag)
    if rs_new.count("pruv_abi_%s_" % tag) != n_rs:
        return None, "harness_error", "%s: bindings 재작성 개수 불일치" % name
    gen_o = os.path.join(d, name + "_gen.o")
    rc, so, se = run_cmd([CLANG, "-O2", CPU_FLAG, "-Wno-override-module", "-c", rw_ll, "-o", gen_o], 300)
    if rc != 0:
        return None, "build_error", "clang (gen.ll) exit %d: %s" % (rc, se[-600:])
    return {"o": gen_o, "rs": rs_new, "tag": tag}, None, None


def phase_b(rec, args, rt_o, fixed=None):
    choose_inputs(rec, args, fixed)
    modes = MODES if rec["status"] == "verified" else SAFE_MODES
    rec["modes"] = modes
    arts = {}
    rec["bins"], rec["ids"], rec["build_errors"] = {}, {}, {}
    for mode in modes:
        name, backend, safe = mode
        if backend == "rust":
            arts[name] = {"gen": rec["nv_rs"] if safe else rec["ver_rs"]}
            continue
        art, kind, err = prep_llvm(rec, mode, rt_o)
        if art is not None:
            arts[name] = art
        elif kind == "harness_error":
            rec["failures"].append({"kind": "harness_error", "mode": name, "detail": err})
        else:
            rec["build_errors"][name] = err
            rec["failures"].append({"kind": "build_error", "mode": name, "detail": err})
    rec["arts"] = arts  # 입력 선택까지 끝난 뒤에만 존재 -> 배치 빌드 대상
    return rec


def build_binary(recs, backend, label, work, rt_o, only_mode=None):
    """recs의 (프로그램, 모드) 모듈을 한 실행 파일로. -> (exe 또는 None, 오류 문장 또는 None).
    만들 모듈이 없으면 (None, None). 성공하면 rec['bins'][모드], rec['ids'][모드]를 채운다."""
    entries, links = [], []
    for rec in recs:
        for mode in rec["modes"]:
            name, be, safe = mode
            if be != backend or name not in rec["arts"] or (only_mode and name != only_mode):
                continue
            art = rec["arts"][name]
            if backend == "rust":
                modname = "p%d_%s" % (rec["idx"], "safe" if safe else "proof")
                gen = art["gen"]
            else:
                modname = "p%d_l%s" % (rec["idx"], "safe" if safe else "proof")
                gen = os.path.join(rec["dir"], "%s_%s_bind.rs" % (name, label))
                # pruv_host_* 의 #[no_mangle]은 바이너리의 첫 LLVM 모듈에만 둔다
                write(gen, art["rs"] if not entries else NO_MANGLE_RE.sub("", art["rs"]))
                links.append(art["o"])
            entries.append((rec, name, modname, os.path.abspath(gen)))
    if not entries:
        return None, None
    specs, ids, nid = [], [], 0
    for rec, name, modname, gen in entries:
        n = len(rec["inputs"])
        specs.append((modname, gen, rec["params"], rec["inputs"], nid))
        ids.append(list(range(nid, nid + n)))
        nid += n
    main = os.path.join(work, "%s_main.rs" % label)
    write(main, batch_driver_source(specs))
    exe = os.path.join(work, "%s_bin" % label)
    link = []
    if backend == "llvm":
        for o in links:
            link += ["-C", "link-arg=" + o]
        link += ["-C", "link-arg=" + rt_o]
    rc, so, se = run_cmd([RUSTC, "-O", "--edition", "2021", main, "-o", exe] + link, 600)
    if rc != 0:
        return None, "rustc exit %d: %s" % (rc, se[-800:])
    for (rec, name, modname, gen), idl in zip(entries, ids):
        rec["bins"][name] = exe
        rec["ids"][name] = idl
    return exe, None


def build_group(recs, backend, label, work, rt_o):
    """배치 하나(백엔드 하나)를 빌드. 실패하면 프로그램별로 다시 빌드해 실패한 프로그램만 build_error.
    -> 만든 실행 파일 수"""
    exe, err = build_binary(recs, backend, label, work, rt_o)
    if exe is None and err is None:
        return 0
    if err is None:
        return 1
    if len(recs) > 1:
        return sum(build_group([r], backend, "%s_p%d" % (label, r["idx"]), work, rt_o) for r in recs)
    # 프로그램 하나: 증명·안전 모듈을 따로 빌드해 실패한 모드만 build_error 로 남긴다
    rec, n = recs[0], 0
    for mode in rec["modes"]:
        name = mode[0]
        if mode[1] != backend or name not in rec["arts"]:
            continue
        exe1, err1 = build_binary([rec], backend, "%s_%s" % (label, name), work, rt_o, only_mode=name)
        if err1 is None:
            n += 1 if exe1 else 0
        else:
            rec["build_errors"][name] = err1
            rec["failures"].append({"kind": "build_error", "mode": name, "detail": err1})
    return n


def build_group_safe(recs, backend, label, work, rt_o):
    try:
        return build_group(recs, backend, label, work, rt_o)
    except Exception:
        msg = traceback.format_exc()[-1500:]
        for rec in recs:
            rec["failures"].append({"kind": "harness_error", "detail": msg})
        return 0


def build_all(progs, args, work, rt_o):
    """준비된 프로그램을 --batch개씩 묶어 배치마다 rust 1개 + llvm 1개 실행 파일을 병렬 빌드. -> 실행 파일 수"""
    ready = [r for r in progs if "arts" in r]
    size = max(1, args.batch)
    total = 0
    with cf.ThreadPoolExecutor(args.jobs) as ex:
        futs = []
        for bi, i in enumerate(range(0, len(ready), size)):
            chunk = ready[i:i + size]
            for backend in ("rust", "llvm"):
                futs.append(ex.submit(build_group_safe, chunk, backend, "b%d_%s" % (bi, backend), work, rt_o))
        for f in cf.as_completed(futs):
            total += f.result()
    return total


# ---------------------------------------------------------------- 5단계: 실행

def run_one(exe, rid):
    rc, so, se = run_cmd([exe, str(rid)], 10)
    pruv_line = ""
    for line in se.splitlines():
        if line.startswith("pruv: "):
            pruv_line = line
            break
    return {"exit": rc, "stdout": so, "pruv": pruv_line}


def run_all(progs, jobs):
    """모든 (프로그램, 모드, 입력)을 id로 한 번씩 병렬 실행해 rec['runs'][모드][k]에 채운다."""
    tasks = []
    for rec in progs:
        rec["runs"] = {}
        for mode in rec.get("modes", []):
            name = mode[0]
            if name in rec.get("bins", {}):
                rec["runs"][name] = [None] * len(rec["inputs"])
                for k, rid in enumerate(rec["ids"][name]):
                    tasks.append((rec, name, k, rec["bins"][name], rid))
    done = 0
    with cf.ThreadPoolExecutor(jobs) as ex:
        futs = {ex.submit(run_one, exe, rid): (rec, name, k) for rec, name, k, exe, rid in tasks}
        for f in cf.as_completed(futs):
            rec, name, k = futs[f]
            try:
                rec["runs"][name][k] = f.result()
            except Exception:
                rec["failures"].append({"kind": "harness_error", "detail": traceback.format_exc()[-1500:]})
                rec["runs"][name][k] = {"exit": -998, "stdout": "", "pruv": ""}
            done += 1
            if done % 500 == 0:
                print("[실행] %d/%d" % (done, len(tasks)), flush=True)


# ---------------------------------------------------------------- 6단계: 검사

def expected_stdout(o):
    lines = ["%s\n" % str(l).rstrip("\n") for l in (o.get("output") or [])]
    lines.append(oracle.format_value(o.get("value")) + "\n")
    return "".join(lines)


def fault_stdout(o):
    """오류 직전까지 오라클이 찍은 줄들 (없으면 빈 문자열)."""
    return "".join("%s\n" % str(l).rstrip("\n") for l in (o.get("output") or []))


def outcome_key(o):
    """오라클 결과가 같은지 비교하는 키: (kind, value, output, detail 접두어)."""
    kind = o.get("kind")
    pre = None
    if kind in FAULT_KINDS:
        try:
            pre = oracle.expected_stderr_prefix(o)
        except Exception:
            pre = None
    return (kind, repr(o.get("value")), tuple(str(l) for l in (o.get("output") or [])), pre)


def mode_oracle(rec, m, k):
    """모드 m의 기대 결과: 증명 모드는 oracle_proof, 안전 모드는 oracle_safe."""
    key = "oracle_proof" if m.endswith("-proof") else "oracle_safe"
    lst = rec.get(key) or rec["oracle"]
    return lst[k]


def check(rec):
    """실패 목록을 돌려주고, 끝까지 비교하지 못한(oracle limit) 수는 rec['incomplete']에 쓴다."""
    fails = []
    incomplete = 0
    modes = list(rec["runs"])
    verified = rec["status"] == "verified"
    for k, args in enumerate(rec["inputs"]):
        runs = {m: rec["runs"][m][k] for m in modes}
        orc = {m: mode_oracle(rec, m, k) for m in modes}
        sigs = {m: (runs[m]["exit"], runs[m]["stdout"], runs[m]["pruv"]) for m in modes}
        # 1) 건전성: limit 건너뛰기보다 먼저 (limit 결과도 contract_failures를 가질 수 있다)
        if verified:
            op = (rec.get("oracle_proof") or rec["oracle"])[k]
            pk = op.get("kind")
            if pk == "requires_undefined" and "i128" not in str(op.get("detail")):
                # 명세 A: 정의역이 증명됐으니 requires undefined 는 i128 넘침·반복 예산으로만 날 수 있다
                fails.append({"kind": "unsound", "input": k,
                              "detail": "검증됨인데 requires 가 정의역 밖에서 평가됨: %s" % op.get("detail")})
            elif rec["req"][k] == "ok" and (pk in FAULT_KINDS or op.get("contract_failures")):
                fails.append({"kind": "unsound", "input": k,
                              "detail": "검증됨 + requires 만족인데 oracle(proof)=%s (%s) contract_failures=%s"
                                        % (pk, op.get("detail"), op.get("contract_failures"))})
        # 2) 오라클 예외 (같은 결과 객체는 한 번만)
        seen_err = set()
        for m in modes:
            if orc[m].get("kind") == "oracle_error" and id(orc[m]) not in seen_err:
                seen_err.add(id(orc[m]))
                fails.append({"kind": "oracle_error", "input": k, "mode": m, "detail": orc[m].get("detail")})
        # 3) 모드 일치: 기대 결과가 같은 모드끼리는 정확히 같아야 하고, rust-X == llvm-X 는 항상 같아야 한다
        groups = {}
        for m in modes:
            # limit 은 확정 결과가 아니다: 같은 limit 이라도 실제 실행은 모드마다 정당하게 다를 수 있다
            if orc[m].get("kind") not in ("oracle_error", "limit"):
                groups.setdefault(outcome_key(orc[m]), []).append(m)
        pairs = set()
        for g in groups.values():
            for i in range(len(g)):
                for j in range(i + 1, len(g)):
                    pairs.add((g[i], g[j]))
        for x in ("proof", "safe"):
            if "rust-" + x in runs and "llvm-" + x in runs:
                pairs.add(("rust-" + x, "llvm-" + x))
        bad = set()
        for a, b in sorted(pairs):
            if TIMEOUT_RC in (runs[a]["exit"], runs[b]["exit"]):
                continue  # 시간 초과는 run_timeout / incomplete 로 따로 센다
            if sigs[a] != sigs[b]:
                bad.update((a, b))
        if bad:
            fails.append({"kind": "mode_mismatch", "input": k,
                          "detail": "; ".join("%s=%r" % (m, sigs[m]) for m in modes if m in bad)})
        # 4) 모드별 오라클 비교
        for m in modes:
            o = orc[m]
            okind = o.get("kind")
            run = runs[m]
            if okind == "oracle_error":
                continue
            if okind == "limit":
                incomplete += 1  # 실행이 시간 초과였든 아니든 끝까지 비교하지 못함
                continue
            if run["exit"] == TIMEOUT_RC:
                fails.append({"kind": "run_timeout", "input": k, "mode": m, "detail": "10초 초과"})
                continue
            if okind == "ok":
                want = expected_stdout(o)
                if run["exit"] != 0 or run["stdout"] != want or run["pruv"] != "":
                    fails.append({"kind": "oracle_mismatch", "input": k, "mode": m,
                                  "detail": "oracle ok %r; got exit %d stdout %r pruv %r"
                                            % (want, run["exit"], run["stdout"], run["pruv"])})
            elif okind in FAULT_KINDS:
                pre = oracle.expected_stderr_prefix(o)
                want = fault_stdout(o)
                if run["exit"] != 101 or (pre is not None and not run["pruv"].startswith(pre)) \
                        or run["stdout"] != want:
                    fails.append({"kind": "oracle_mismatch", "input": k, "mode": m,
                                  "detail": "oracle %s (%s) -> want exit 101 + %r + stdout %r; got exit %d stdout %r pruv %r"
                                            % (okind, o.get("detail"), pre, want, run["exit"],
                                               run["stdout"], run["pruv"])})
    rec["incomplete"] = incomplete
    return fails


# ---------------------------------------------------------------- 저장 / 출력

def short(v, n=60):
    s = json.dumps(v, default=str)
    return s if len(s) <= n else s[:n - 3] + "..."


def rec_results(rec):
    rows = []
    for k, args in enumerate(rec.get("inputs", [])):
        rows.append({"index": k, "args": args, "check_requires": rec.get("req", [None] * (k + 1))[k],
                     "oracle": rec["oracle"][k] if k < len(rec.get("oracle", [])) else None,
                     "oracle_proof": rec["oracle_proof"][k] if k < len(rec.get("oracle_proof", [])) else None,
                     "modes": {m: rec["runs"][m][k] for m in rec.get("runs", {})}})
    return rows


def save_failure(out_dir, rec, kind, items):
    d = os.path.join(out_dir, "failures", "%s_%s" % (kind, rec["name"]))
    os.makedirs(d, exist_ok=True)
    write(os.path.join(d, "case.pruv"), rec["src"])
    write(os.path.join(d, "inputs.json"), json.dumps(rec.get("inputs", []), indent=1))
    write(os.path.join(d, "results.json"), json.dumps(
        {"name": rec["name"], "status": rec["status"], "params": rec["params"], "ret": rec["ret"],
         "failures": items, "build_errors": rec.get("build_errors", {}), "inputs": rec_results(rec)},
        indent=1, default=str))
    write(os.path.join(d, "pruvc_output.txt"),
          "".join("== %s ==\n%s\n" % (k, v) for k, v in rec["logs"].items()))
    # 이 프로그램 자신의 (재작성하지 않은) 생성 파일
    try:
        gd = os.path.join(d, "gen")
        os.makedirs(gd, exist_ok=True)
        for fn in sorted(os.listdir(rec["dir"])):
            if fn.endswith((".rs", ".ll")) and not fn.endswith(("_rw.ll", "_bind.rs")):
                shutil.copy(os.path.join(rec["dir"], fn), os.path.join(gd, fn))
    except Exception:
        pass


def print_table(rec):
    modes = list(rec.get("runs", {}))
    print("프로그램 %s: 상태=%s 코드=%s" % (rec["name"], rec["status"], ",".join(rec.get("codes", [])) or "-"))
    for m, e in rec.get("build_errors", {}).items():
        print("  빌드 실패 %s: %s" % (m, e[:200].replace("\n", " ")))
    print("  %-3s %-34s %-28s %s" % ("#", "인자 (requires)", "oracle", " | ".join(modes)))
    for k, args in enumerate(rec.get("inputs", [])):
        o = rec["oracle"][k]
        osum = "%s %s" % (o.get("kind"), o.get("value") if o.get("kind") == "ok" else (o.get("detail") or ""))
        cells = []
        for m in modes:
            r = rec["runs"][m][k]
            cells.append("%s/%s" % (r["exit"], (r["stdout"].strip() or r["pruv"])[:40]))
        print("  %-3d %-34s %-28s %s" % (k, "%s (%s)" % (short(args, 26), rec["req"][k]), osum[:28], " | ".join(cells)))


def guard(fn, rec, *a):
    """작업 스레드 예외를 하네스 실패로 기록."""
    try:
        return fn(rec, *a)
    except Exception:
        rec["failures"].append({"kind": "harness_error", "detail": traceback.format_exc()[-1500:]})
        return rec


# ---------------------------------------------------------------- 재실행

def replay(path, args):
    if os.path.isdir(path):
        pruv = os.path.join(path, "case.pruv")
        if not os.path.exists(pruv):
            cand = sorted(f for f in os.listdir(path) if f.endswith(".pruv"))
            if not cand:
                print(".pruv 파일이 없습니다: " + path)
                return 2
            pruv = os.path.join(path, cand[0])
    else:
        pruv = path
    base = os.path.dirname(os.path.abspath(pruv))
    inp = os.path.join(base, "inputs.json")
    if not os.path.exists(inp):
        alt = os.path.splitext(pruv)[0] + ".inputs.json"
        inp = alt if os.path.exists(alt) else None
    if inp is None:
        print("inputs.json을 찾지 못했습니다: " + base)
        return 2
    src = open(pruv).read()
    inputs = json.load(open(inp))
    params, ret = signature_from_src(src)
    case = {"name": "replay_" + os.path.splitext(os.path.basename(pruv))[0], "src": src, "entry": "f",
            "params": params, "ret": ret, "input_hints": {}}
    work = tempfile.mkdtemp(prefix="pruvfuzz_replay_%s_" % driver().name)
    try:
        rt_o = build_runtime(work)
        rec = phase_a(case, work)
        if "prog" not in rec or rec["status"] not in ("verified", "rejected"):
            print("상태=%s %s %s" % (rec["status"], rec.get("detail", ""), rec["failures"]))
            return 1
        rec["idx"] = 0
        guard(phase_b, rec, args, rt_o, inputs)
        build_all([rec], args, work, rt_o)  # 크기 1 배치, 본 실행과 같은 경로
        run_all([rec], args.jobs)
        if "runs" in rec:
            rec["failures"] += check(rec)
        if "oracle" in rec:
            print_table(rec)
        for f in rec["failures"]:
            print("실패 [%s] 입력=%s 모드=%s: %s" % (f["kind"], f.get("input", "-"), f.get("mode", "-"),
                                                 str(f["detail"])[:400]))
        print("끝까지 비교하지 못함(oracle limit) %d건" % rec.get("incomplete", 0))
        print("실패 %d건" % len(rec["failures"]))
        return 1 if rec["failures"] else 0
    finally:
        if args.keep_work:
            print("작업 폴더: " + work)
        else:
            shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- 본 실행

def main():
    ap = argparse.ArgumentParser(description="Pruv 차분 퍼징")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--programs", type=int, default=100)
    ap.add_argument("--inputs", type=int, default=8)
    ap.add_argument("--max-candidates", type=int, default=400)
    ap.add_argument("--rejected-sample", type=int, default=30)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--out", default=None)
    ap.add_argument("--batch", type=int, default=25, help="실행 파일 하나에 묶을 프로그램 수")
    ap.add_argument("--avoid-known", default="",
                    help="쉼표로 구분한 이미 보고한 결함 id (예: fz01). 생성기가 그 형태를 만들지 않는다")
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--replay", default=None)
    CD.add_args(ap)
    args = ap.parse_args()
    global DRIVER
    DRIVER = CD.from_args(args)
    generate.AVOID.update(x.strip() for x in args.avoid_known.split(",") if x.strip())
    if args.replay:
        return replay(args.replay, args)
    # 컴파일러별 결과·작업 폴더: py 의 기본 경로(out/<seed>)는 그대로, rs 는 out/<seed>_rs
    out_dir = args.out or os.path.join(HERE, "out", str(args.seed) + ("" if DRIVER.name == "py" else "_" + DRIVER.name))
    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="pruvfuzz_%s_" % DRIVER.name)
    t0 = time.time()
    counts = {"candidates": 0, "generator_invalid": 0, "oracle_unsupported": 0, "oracle_parse_error": 0,
              "verified": 0, "rejected": 0, "rejected_built": 0, "failed_in_phase_a": 0}
    rej_codes = {}
    fail_kinds = {}
    failed_cases = []
    invalid_saved = 0
    try:
        rt_o = build_runtime(work)
        # --- 1~2단계
        verified, rejected_all = [], []
        def candidate(i):
            """후보 i 하나를 생성하고 phase_a까지 돌린다. 예외는 하네스 실패로 기록."""
            case = None
            try:
                case = generate.generate_case(args.seed, i)
                rec = phase_a(case, work)
            except Exception:
                rec = {"name": (case or {}).get("name", "cand_%d" % i), "src": (case or {}).get("src", ""),
                       "params": (case or {}).get("params", []), "ret": (case or {}).get("ret"),
                       "failures": [{"kind": "harness_error", "detail": traceback.format_exc()[-1500:]}],
                       "logs": {}, "status": "failed", "codes": []}
            rec["cand_idx"] = i
            return rec

        def handle(rec):
            nonlocal invalid_saved
            counts["candidates"] += 1
            st = rec["status"]
            if st in ("oracle_unsupported", "oracle_parse_error", "generator_invalid"):
                counts[st] += 1
                if st == "generator_invalid" and invalid_saved < 10:
                    invalid_saved += 1
                    gd = os.path.join(out_dir, "generator_invalid")
                    os.makedirs(gd, exist_ok=True)
                    write(os.path.join(gd, rec["name"] + ".pruv"), rec["src"])
                    write(os.path.join(gd, rec["name"] + ".txt"), rec["logs"].get("no-verify", ""))
            elif st == "failed":
                counts["failed_in_phase_a"] += 1
            elif st == "verified":
                counts["verified"] += 1
                verified.append(rec)
            elif st == "rejected":
                counts["rejected"] += 1
                for c in rec["codes"]:
                    rej_codes[c] = rej_codes.get(c, 0) + 1
                rejected_all.append(rec)
            if rec["failures"]:  # 1~2단계에서 생긴 실패(내부 오류, 시간 초과)는 바로 저장
                _record_failures(out_dir, [rec], fail_kinds, failed_cases)
            if counts["candidates"] % 20 == 0:
                print("[생성/검증] 후보 %d, 통과 %d, 거절 %d, 생성기 오류 %d"
                      % (counts["candidates"], counts["verified"], counts["rejected"],
                         counts["generator_invalid"] + counts["oracle_unsupported"]
                         + counts["oracle_parse_error"]), flush=True)

        # 스트리밍: 최대 jobs*2개를 진행 중으로 두고, 하나 끝날 때마다 다음 후보를 낸다.
        # 충분히 모이거나 --max-candidates에 닿으면 제출만 멈추고, 낸 후보의 결과는 모두 거둔다.
        nxt, cap = 0, max(args.jobs * 2, 2)
        pending = set()
        with cf.ThreadPoolExecutor(args.jobs) as ex:
            while True:
                while len(pending) < cap and nxt < args.max_candidates and len(verified) < args.programs:
                    pending.add(ex.submit(candidate, nxt))
                    nxt += 1
                if not pending:
                    break
                done_set, _ = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
                for f in done_set:
                    pending.discard(f)
                    handle(f.result())
        # 완료 순서와 무관하게 재현되도록 후보 번호순으로 정렬; 초과 통과분은 빌드하지 않는다
        verified.sort(key=lambda r: r["cand_idx"])
        rejected_all.sort(key=lambda r: r["cand_idx"])
        verified = verified[:args.programs]
        programs_short = len(verified) < args.programs
        if programs_short:
            print("경고: 검증 통과 프로그램이 %d개뿐입니다 (요청 %d개, 후보 %d개)"
                  % (len(verified), args.programs, counts["candidates"]), flush=True)
        t1 = time.time()
        sample = rejected_all[:args.rejected_sample]
        counts["rejected_built"] = len(sample)
        progs = verified + sample
        # --- 3~4단계 (입력 선택 + clang 준비, 이어서 배치 빌드; pruvc 는 phase_a 에서 이미 끝남)
        for i, r in enumerate(progs):
            r["idx"] = i
        done = 0
        with cf.ThreadPoolExecutor(args.jobs) as ex:
            futs = [ex.submit(guard, phase_b, r, args, rt_o) for r in progs]
            for f in cf.as_completed(futs):
                f.result()
                done += 1
                if done % 20 == 0:
                    print("[준비] %d/%d" % (done, len(progs)), flush=True)
        binaries_built = build_all(progs, args, work, rt_o)
        print("[빌드] 실행 파일 %d개" % binaries_built, flush=True)
        t2 = time.time()
        # --- 5단계 (실행)
        run_all(progs, args.jobs)
        t3 = time.time()
        # --- 6단계 (검사) + 저장
        inputs_run = 0
        outcome_counts = {}
        incomplete_total = 0
        input_errors_total = 0
        no_sat = []
        for rec in progs:
            if "runs" in rec:
                try:
                    rec["failures"] += check(rec)
                except Exception:
                    rec["failures"].append({"kind": "harness_error", "detail": traceback.format_exc()[-1500:]})
                incomplete_total += rec.get("incomplete", 0)
            if "req" in rec and not any(r == "ok" for r in rec["req"]):
                no_sat.append(rec["name"])
            inputs_run += len(rec.get("inputs", []))
            input_errors_total += rec.get("input_errors", 0)
            if "runs" in rec:
                for k, o in enumerate(rec.get("oracle", [])):
                    key = "%s/req_%s/%s" % (rec["status"], rec["req"][k], o.get("kind"))
                    outcome_counts[key] = outcome_counts.get(key, 0) + 1
            if rec["failures"]:
                _record_failures(out_dir, [rec], fail_kinds, failed_cases)
        t4 = time.time()
        summary = {
            "seed": args.seed, "programs_requested": args.programs, "inputs_per_program": args.inputs,
            "candidates": counts["candidates"], "generator_invalid": counts["generator_invalid"],
            "oracle_unsupported": counts["oracle_unsupported"], "oracle_parse_error": counts["oracle_parse_error"],
            "failed_in_phase_a": counts["failed_in_phase_a"],
            "verified": counts["verified"], "verified_used": len(verified), "programs_short": programs_short,
            "incomplete": incomplete_total, "input_errors": input_errors_total,
            "no_sat_inputs": {"count": len(no_sat), "names": no_sat[:20]},
            "rejected": counts["rejected"],
            "rejected_by_code": rej_codes, "rejected_built_safe_modes": counts["rejected_built"],
            "inputs_run": inputs_run, "oracle_outcomes": dict(sorted(outcome_counts.items())),
            "binaries_built": binaries_built, "batch": args.batch,
            "executions": sum(len(r.get("inputs", [])) * len(r.get("runs", {})) for r in progs),
            "failures_by_kind": fail_kinds, "failed_cases": sorted(set(failed_cases)),
            "timings_s": {"generate_verify": round(t1 - t0, 2), "build": round(t2 - t1, 2),
                          "run": round(t3 - t2, 2), "check_save": round(t4 - t3, 2),
                          "total": round(t4 - t0, 2), "wall": round(time.time() - t0, 2)},
        }
        write(os.path.join(out_dir, "summary.json"), json.dumps(summary, indent=2))
        print("---- 요약 ----")
        print("후보 %d (생성기 오류 %d, 오라클 미지원 %d) -> 통과 %d / 거절 %d %s"
              % (summary["candidates"], summary["generator_invalid"],
                 summary["oracle_unsupported"] + summary["oracle_parse_error"],
                 summary["verified"], summary["rejected"], json.dumps(rej_codes)))
        print("실행한 입력 %d (프로세스 실행 %d), 소요 %.1fs (생성+검증 %.1f, 빌드 %.1f, 실행 %.1f)"
              % (inputs_run, summary["executions"], summary["timings_s"]["total"],
                 summary["timings_s"]["generate_verify"], summary["timings_s"]["build"],
                 summary["timings_s"]["run"]))
        print("입력 결과(상태/requires/oracle): " + json.dumps(summary["oracle_outcomes"]))
        print("끝까지 비교하지 못함(oracle limit, 실패도 통과도 아님): %d건" % summary["incomplete"])
        print("requires 만족 입력이 하나도 없는 프로그램: %d개 %s"
              % (summary["no_sat_inputs"]["count"], json.dumps(summary["no_sat_inputs"]["names"])))
        if programs_short:
            print("경고: 검증 통과 프로그램 %d개 < 요청 %d개 (programs_short)"
                  % (summary["verified_used"], args.programs))
        print("실패: %s" % (json.dumps(fail_kinds) if fail_kinds else "없음"))
        print("결과: " + out_dir)
        return 1 if fail_kinds else 0
    finally:
        if args.keep_work:
            print("작업 폴더: " + work)
        else:
            shutil.rmtree(work, ignore_errors=True)


def _record_failures(out_dir, recs, fail_kinds, failed_cases):
    for rec in recs:
        by_kind = {}
        for f in rec["failures"]:
            by_kind.setdefault(f["kind"], []).append(f)
        for kind, items in by_kind.items():
            fail_kinds[kind] = fail_kinds.get(kind, 0) + len(items)
            failed_cases.append(rec["name"])
            save_failure(out_dir, rec, kind, items)
        rec["failures"] = []  # 중복 저장 방지


if __name__ == "__main__":
    sys.exit(main())
