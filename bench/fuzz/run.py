#!/usr/bin/env python3
"""Differential fuzzing runner for the Pruv compiler (standard library only, Python 3.9).

    python bench/fuzz/run.py [--seed 1] [--programs 100] [--inputs 8] [--max-candidates 400]
                             [--rejected-sample 30] [--jobs N] [--batch 25] [--out DIR] [--keep-work]
    python bench/fuzz/run.py --g2 [--seed 41] [--programs 200] [--rejected-sample 30]   (G2 mode, see README)
    python bench/fuzz/run.py --g3 [--seed 41] [--programs 100] [--g3-safe-only 20] [--inputs 8]   (G3 mode, see README)
    python bench/fuzz/run.py --g6 [--seed 41] [--programs 100] [--g6-safe-only 20] [--inputs 8]   (G6 mode, see README)
    python bench/fuzz/run.py --g9 [--seed 41] [--programs 100] [--g9-safe-only 20] [--inputs 8]   (G9 mode, see README)
    python bench/fuzz/run.py --g4 [--seed 41] [--programs 30] [--inputs 8]   (G4 mode: multi-file module programs, see README)
    python bench/fuzz/run.py --g5 [--seed 41] [--programs 30] [--inputs 8]   (G5 mode: inout parameters, see README)
    python bench/fuzz/run.py --replay DIR_OR_PRUVFILE   (a G4/G5 program folder with root.pruv works too)
    (every form accepts [--compiler py|rs] [--compiler-path PATH], see tests/compiler_driver.py; default rs)

Promise: a program the verifier accepted (pruvc default mode, exit 0) satisfies ensures on every input that
satisfies requires, with no out-of-range index or overflow, and its output equals the oracle's. Each mode is
compared with its own oracle (proof mode uses mode="proof", safe mode uses mode="safe"). Modes with the same
expected outcome have exactly the same stdout, exit code, and `pruv: ...` line, and rust-X == llvm-X always holds.
Proof and safe modes may legitimately differ when the oracle results differ, for example when the run-time
requires of an inner call reaches the i128 limit.
The run-time requires check of a verified program never reaches outside the domain (`requires undefined`); the only exception is the i128 limit.

Build: on macOS the first run of each new executable costs about 0.33 s serially, so --batch programs are bundled
into one executable (one per backend, with the proof and safe modules together). LLVM modules are linked as copies
with a unique prefix on the `pruv_abi_` symbols, and the #[no_mangle] of `pruv_host_*` stays only on the first module.
"""
import argparse
import concurrent.futures as cf
import hashlib
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
FAULT_KINDS = {"cost_exceeded", "oob", "overflow", "div_domain", "requires_violated", "requires_undefined",
               "elem_range", "slice_range", "slice_cut",   # the last three are G2 (only the oracle emits them; existing paths unchanged)
               "foreign_requires", "foreign_undefined"}    # G6: `pruv: foreign requires violated:` / `pruv: foreign contract undefined:`
MODES = [("rust-proof", "rust", False), ("rust-safe", "rust", True),
         ("llvm-proof", "llvm", False), ("llvm-safe", "llvm", True)]
SAFE_MODES = [m for m in MODES if m[2]]


# ---------------------------------------------------------------- subprocesses

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
    with open(path, "w", encoding="utf-8") as fh:      # G6 sources contain multibyte string literals
        fh.write(text)


def write_tree(base, files):
    """G4: write a multi-file program ({relative path with '/': source}) below `base`."""
    for rel, text in files.items():
        path = os.path.join(base, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write(path, text)


def read_tree(base):
    """G4: every .pruv file below `base` -> {relative path with '/': source} (generated .rs/.ll files are ignored)."""
    files = {}
    for dp, _dn, fns in os.walk(base):
        for fn in fns:
            if fn.endswith(".pruv"):
                p = os.path.join(dp, fn)
                with open(p, encoding="utf-8") as fh:
                    files[os.path.relpath(p, base).replace(os.sep, "/")] = fh.read()
    return files


def is_tree(case):
    """G4/G5/G7 programs are directories (root.pruv + module files)."""
    return bool(case.get("g4") or case.get("g5") or case.get("g7"))


def save_program(dir_, rec, name=None):
    """Save the source of rec below dir_: a G4/G5 program as a directory tree <name>/..., any other as <name>.pruv."""
    name = name or rec["name"]
    case = rec.get("case") or {}
    if is_tree(case):
        write_tree(os.path.join(dir_, name), case["files"])
    else:
        write(os.path.join(dir_, name + ".pruv"), rec["src"])


def build_runtime(work):
    rt_o = os.path.join(work, "runtime.o")
    rc, so, se = run_cmd([CLANG, "-O2", CPU_FLAG, "-std=c11", "-DPRUV_RUST_ALLOCATOR",
                          "-c", RUNTIME_C, "-o", rt_o], 300)
    if rc != 0:
        raise RuntimeError("clang (runtime.c) failed: " + se[-400:])
    return rt_o


# ---------------------------------------------------------------- driver

def rust_int(v):
    if v == I64_MIN:
        return "i64::MIN"
    if v < 0:
        return "(%di64)" % v
    return "%di64" % v


def deep_copy_arg(v):
    """Argument copy: recursively copies arrays (list) and every dict (Option/Result, struct, enum)."""
    if isinstance(v, list):
        return list(v)
    if isinstance(v, dict):
        return dict((k, deep_copy_arg(x)) for k, x in v.items())
    return v


def rust_option_result(ty, v):
    """Option/Result dict (e.g. {"tag": "Some", "v": 3}) -> Rust literal, wrapped in black_box to prevent constant folding."""
    tag = v.get("tag") if isinstance(v, dict) else None
    elem = "bool" if ty.endswith("<bool>") else "i64"      # G3: Option<bool> / Result<bool> (the Err code stays i64)

    def payload(x):
        if elem == "bool":
            if not isinstance(x, bool):
                raise ValueError("not a bool payload: %r" % (x,))
            return "true" if x else "false"
        return rust_int(x)

    if ty.startswith("Option<"):
        if tag == "None":
            lit = "None"
        elif tag == "Some":
            lit = "Some(%s)" % payload(v["v"])
        else:
            raise ValueError("not an %s argument form: %r" % (ty, v))
        return "std::hint::black_box::<Option<%s>>(%s)" % (elem, lit)
    if tag not in ("Ok", "Err"):
        raise ValueError("not a %s argument form: %r" % (ty, v))
    return "std::hint::black_box::<Result<%s, i64>>(%s(%s))" % (
        elem, tag, payload(v["v"]) if tag == "Ok" else rust_int(v["v"]))


def rust_value(mod, v):
    """Value dict -> Rust expression (recursive). Struct/enum paths get the `<mod>::` prefix (for both Rust and LLVM the
    pub types sit at the top of the generated module: pruvc/codegen.py emit_public_types, which llvmgen also uses)."""
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
    raise ValueError("unknown value form: %r" % (v,))


def rust_str_lit(s):
    """G2: Python str -> Rust string literal. Characters in 0x20..=0x7E other than `"` and `\\` are kept, the rest become \\u{lowercase hex}."""
    out = []
    for ch in s:
        o = ord(ch)
        if 0x20 <= o <= 0x7E and ch not in '"\\':
            out.append(ch)
        else:
            out.append("\\u{%x}" % o)
    return '"%s"' % "".join(out)


def batch_driver_source(specs):
    """specs: [(module name, absolute path of the generated .rs, params, inputs, start id[, return type])] -> main.rs string.
    argv[1] = flat run id. One id is assigned to each (program, mode, input).
    params type strings: "i64", "bool", "array", "array_u8", "array_bool", "str", "Option<i64>", "Result<i64>",
    anything else is a user type name (struct/enum value dicts are built as `<module>::Point { .. }`).
    Output uses `{:?}`; if the return type is "str", `{:?}` of `.as_bytes()` (list of byte integers, G2_Q1_IMPL 5.0)."""
    L = ['#![allow(dead_code, unused_imports)]']
    for spec in specs:
        modname, gen_rs = spec[0], spec[1]
        L.append('#[path = "%s"] mod %s;' % (gen_rs, modname))
    L += ['fn main() {',
          '    let k: usize = std::env::args().nth(1).unwrap().parse().unwrap();', '    match k {']
    for spec in specs:
        modname, gen_rs, params, inputs, start = spec[:5]
        ret = spec[5] if len(spec) > 5 else None
        for idx, args in enumerate(inputs):
            decl, parts = [], []
            for j, ((name, ty), v) in enumerate(zip(params, args)):
                if ty == "array":
                    decl.append("let a%d: Vec<i64> = vec![%s];" % (j, ", ".join(rust_int(e) for e in v)))
                    parts.append("&a%d" % j)
                elif ty == "array_u8":
                    decl.append("let a%d: Vec<u8> = vec![%s];" % (j, ", ".join("%d" % e for e in v)))
                    parts.append("&a%d" % j)
                elif ty == "array_bool":
                    decl.append("let a%d: Vec<bool> = vec![%s];"
                                % (j, ", ".join("true" if e else "false" for e in v)))
                    parts.append("&a%d" % j)
                elif ty == "str":
                    decl.append("let a%d: &str = %s;" % (j, rust_str_lit(v)))
                    parts.append("a%d" % j)
                elif ty == "bool":
                    parts.append("std::hint::black_box(%s)" % ("true" if v else "false"))
                elif ty in ("Option<i64>", "Result<i64>", "Option<bool>", "Result<bool>"):
                    parts.append(rust_option_result(ty, v))
                elif ty == "i64":
                    parts.append("std::hint::black_box(%s)" % rust_int(v))
                elif isinstance(v, dict) and ("struct" in v or "enum" in v):
                    parts.append("std::hint::black_box(%s)" % rust_value(modname, v))
                else:
                    raise ValueError("unsupported parameter type: %r" % (ty,))
            if ret == "str":
                L.append('        %d => { %s println!("{:?}", %s::f(%s).as_bytes()); }'
                         % (start + idx, " ".join(decl), modname, ", ".join(parts)))
            else:
                L.append('        %d => { %s println!("{:?}", %s::f(%s)); }'
                         % (start + idx, " ".join(decl), modname, ", ".join(parts)))
    L += ["        _ => {}", "    }", "}"]
    return "\n".join(L) + "\n"


def _sig_type(ty):
    """Source type string (whitespace removed) -> fuzzer type string. [i64] stays "array" as a parameter, as before."""
    if ty == "[u8]":
        return "array_u8"
    if ty == "[bool]":
        return "array_bool"
    return "array" if ty.startswith("[") else ty


def signature_from_src(src):
    # return type: i64 / bool / [i64] / [u8] / [bool] / str / () / Option<i64> / Result<i64> / user type (angle and square brackets allowed)
    m = re.search(r"fn\s+f\s*\(([^)]*)\)\s*->\s*(\[\s*(?:i64|u8|bool)\s*\]|\(\s*\)|\w+(?:\s*<[^<>]*>)?)", src)
    if not m:
        raise ValueError("could not find a fn f(...) -> T signature")
    params = []
    for p in [s.strip() for s in m.group(1).split(",") if s.strip()]:
        name, ty = [t.strip() for t in p.split(":", 1)]
        ty = re.sub(r"\s+", "", ty)
        params.append([name, _sig_type(ty)])
    ret = re.sub(r"\s+", "", m.group(2))
    if ret in ("[u8]", "[bool]"):
        ret = _sig_type(ret)    # keep the existing "[i64]" notation as is
    return params, ret


# ---------------------------------------------------------------- phases 1-2: generate + verify

def phase_a(case, work):
    rec = {"name": case["name"], "src": case["src"], "params": case["params"], "ret": case["ret"],
           "case": case, "failures": [], "logs": {}, "status": None, "codes": []}
    d = os.path.join(work, case["name"])
    os.makedirs(d, exist_ok=True)
    rec["dir"] = d
    if is_tree(case):
        # G4/G5: the program is a directory (root.pruv + module files); the compiler is invoked on <dir>/root.pruv
        write_tree(d, case["files"])
        pruv = os.path.join(d, "root.pruv")
    else:
        pruv = os.path.join(d, "case.pruv")
        write(pruv, case["src"])
    rec["pruv"] = pruv
    try:
        rec["prog"] = oracle.parse_modules(case["files"]) if is_tree(case) else oracle.parse_program(case["src"])
    except oracle.OracleUnsupported as e:
        rec["status"], rec["detail"] = "oracle_unsupported", str(e)
        return rec
    except Exception as e:  # includes OracleParseError
        rec["status"], rec["detail"] = "oracle_parse_error", "%s: %s" % (type(e).__name__, e)
        return rec
    rec["nv_rs"] = os.path.join(d, "rust_safe_gen.rs")
    rec["ver_rs"] = os.path.join(d, "rust_proof_gen.rs")
    # One pruvc invocation produces both the Rust output and the LLVM output (.ll + bindings) (--also-llvm).
    # Output paths are removed before the call so stale files in a reused work folder are not picked up.
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
    if rc not in (0, 1):  # negative (signal/crash), 2 (usage), 3 (internal error), etc. are all failures
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
                                    "detail": "pruvc --no-verify exit 1, diagnostic stage=%s"
                                              % (sorted(str(s) for s in stages) or "none")})
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


# ---------------------------------------------------------------- phases 3-4: input selection + clang preparation + build

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
        prefix = ("g5:" if getattr(args, "g5", False) else "g4:" if getattr(args, "g4", False)
                  else "g9:" if getattr(args, "g9", False)
                  else "g6:" if getattr(args, "g6", False)
                  else "g3:" if getattr(args, "g3", False) else ("g2:" if getattr(args, "g2", False) else ""))
        # G4 twins (two programs that differ only in one callee body) share `input_key`, hence get the same inputs
        rng = random.Random(prefix + "%s:%s:inputs" % (args.seed, (rec["case"].get("input_key") or rec["name"])))
        cands = generate.candidate_inputs(rec["case"], rng, 300)
        ok_l, bad_l, seen = [], [], set()
        n_err, n_cand = 0, 0
        for a in cands:
            key = json.dumps(a, sort_keys=True)   # Option/Result dicts get the same key
            if key in seen:
                continue
            seen.add(key)
            n_cand += 1
            st = safe_check(prog, a)
            if st == "error":
                n_err += 1      # counted rather than silently dropped
                continue
            (ok_l if st == "ok" else bad_l).append(a)
        rec["input_errors"] = n_err
        if n_cand and n_err == n_cand:
            rec["failures"].append({"kind": "harness_error",
                                    "detail": "all %d input candidates raised an exception (error) in the requires check" % n_cand})
        n_ok = max(1, args.inputs * 3 // 4)
        n_bad = max(0, args.inputs - n_ok)
        sel_ok, sel_bad = ok_l[:n_ok], bad_l[:n_bad]
        if len(sel_ok) < n_ok:
            sel_bad = bad_l[:n_bad + (n_ok - len(sel_ok))]
        elif len(sel_bad) < n_bad:
            sel_ok = ok_l[:n_ok + (n_bad - len(sel_bad))]
        inputs = sel_ok + sel_bad
        if not inputs and not any(f.get("kind") == "harness_error" for f in rec["failures"]):
            rec["failures"].append({"kind": "harness_error", "detail": "0 inputs selected (%d candidates, %d errors)"
                                    % (n_cand, n_err)})
    rec["inputs"] = inputs
    rec["req"] = [safe_check(prog, a) for a in inputs]
    rec["input_errors"] += sum(1 for r in rec["req"] if r == "error")
    rec["oracle_safe"] = [oracle_run(prog, a, "safe") for a in inputs]
    if rec["status"] == "verified":
        rec["oracle_proof"] = [oracle_run(prog, a, "proof") for a in inputs]
    rec["oracle"] = rec["oracle_safe"]  # for compatibility: the safe-mode results


def oracle_run(prog, a, mode):
    """Run the oracle once. With an old oracle that does not know the mode argument, call it without mode."""
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
# G6 bindings also carry the shim's own #[no_mangle] adapters, which every module needs: strip only the pruv_host_* ones
NO_MANGLE_HOST_RE = re.compile(r'^[ \t]*#\[no_mangle\][ \t]*\n(?=[ \t]*pub extern "C" fn pruv_host_)', re.M)


def g6_rename(ll_text, rs_text, tag):
    """G6: the generated bindings contain `mod pruv_g6_shim` with #[no_mangle] adapters `pruv_g6_v1_<helper>` and the bridge marker
    `pruv_g6_bridge_v1`; the .ll declares/calls them. Several modules end up in one executable (proof+safe of a program, other
    programs), so every module gets its own copy of these symbols, the same way `pruv_abi_` is made unique.
    -> (new .ll text, new bindings text, number of renamed occurrences in the .ll)"""
    def sub(t):
        return t.replace("pruv_g6_v1_", "pruv_g6_v1_%s_" % tag).replace("pruv_g6_bridge_v1", "pruv_g6_bridge_v1_%s" % tag)
    return sub(ll_text), sub(rs_text), ll_text.count("pruv_g6_v1_") + ll_text.count("pruv_g6_bridge_v1")


def prep_llvm(rec, mode, rt_o):
    """Read the .ll/bindings (rec['llvm_files'][name]) that phase_a produced with pruvc --also-llvm,
    make a .ll copy with uniquified symbols -> clang .o. pruvc is not called here.
    G2 symbols: the only thing rewritten is the `pruv_abi_` prefix. `pruv_abi_<f>__typed` (str/[bool] parameters) shares
    that prefix, so the .ll definitions, bindings externs, and calls change together. `pruv_check_utf8`/`pruv_check_bool`/
    `pruv_copy_v2`/`pruv_str_boundary`/`pruv_runtime_rust_allocator_v2` are defined by the shared runtime.o
    (-DPRUV_RUST_ALLOCATOR), so they are not rewritten. repr(C) structs such as `Pruv__Str` live inside a per-module
    `mod`, so they do not collide.
    -> (art or None, failure kind or None, error message or None). The original .ll/.rs stay untouched in rec['dir'].
    Soundness: proof-mode artifacts are used only when rec['status'] == 'verified'."""
    name, backend, safe = mode
    d = rec["dir"]
    tag = "p%dl%d" % (rec["idx"], 1 if safe else 0)
    if not safe and rec["status"] != "verified":
        return None, "harness_error", "%s: proof mode but status=%s (not verified)" % (name, rec["status"])
    files = rec.get("llvm_files", {}).get(name)
    if not files or not os.path.exists(files[0]) or not os.path.exists(files[1]):
        return None, "harness_error", ("%s: no LLVM output produced by phase_a (llvm_files=%s)"
                                       % (name, files))
    ll, gen = files
    with open(ll) as fh:
        ll_text = fh.read()
    with open(gen) as fh:
        rs_text = fh.read()
    n_ll = ll_text.count("@pruv_abi_")
    n_rs = rs_text.count("pruv_abi_")
    if n_ll < 1 or n_rs < 1:
        return None, "harness_error", ("%s: nothing to rewrite (.ll @pruv_abi_ count %d, bindings pruv_abi_ count %d)"
                                       % (name, n_ll, n_rs))
    rw_ll = os.path.join(d, name + "_rw.ll")
    ll_new = ll_text.replace("@pruv_abi_", "@pruv_abi_%s_" % tag)
    rs_new = rs_text.replace("pruv_abi_", "pruv_abi_%s_" % tag)
    if rs_new.count("pruv_abi_%s_" % tag) != n_rs:
        return None, "harness_error", "%s: bindings rewrite count mismatch" % name
    if (rec.get("case") or {}).get("g6"):
        ll_new, rs_new, n_g6 = g6_rename(ll_new, rs_new, tag)
        if n_g6 and rs_new.count("pruv_g6_v1_%s_" % tag) + rs_new.count("pruv_g6_bridge_v1_%s" % tag) < 1:
            return None, "harness_error", "%s: G6 shim symbols not found in the bindings (.ll references %d)" % (name, n_g6)
    if (rec.get("case") or {}).get("g7") or (rec.get("case") or {}).get("s5"):
        ll_new = ll_new.replace("pruv_g7_v1_run", "pruv_g7_v1_run_" + tag)
        rs_new = rs_new.replace("pruv_g7_v1_run", "pruv_g7_v1_run_" + tag)
    write(rw_ll, ll_new)
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
    rec["arts"] = arts  # exists only after input selection is done -> target of the batch build
    return rec


def build_binary(recs, backend, label, work, rt_o, only_mode=None):
    """Build the (program, mode) modules of recs into one executable. -> (exe or None, error message or None).
    (None, None) if there is no module to build. On success, fills rec['bins'][mode] and rec['ids'][mode]."""
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
                # the #[no_mangle] of pruv_host_* stays only on the first LLVM module of the binary
                strip = NO_MANGLE_HOST_RE if any((rec.get("case") or {}).get(k) for k in ("g6", "g7", "s5")) else NO_MANGLE_RE
                write(gen, art["rs"] if not entries else strip.sub("", art["rs"]))
                links.append(art["o"])
            entries.append((rec, name, modname, os.path.abspath(gen)))
    if not entries:
        return None, None
    specs, ids, nid = [], [], 0
    for rec, name, modname, gen in entries:
        n = len(rec["inputs"])
        specs.append((modname, gen, rec["params"], rec["inputs"], nid, rec.get("ret")))
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
    """Build one batch (one backend). On failure, rebuild per program so only the failing programs get build_error.
    -> number of executables built"""
    exe, err = build_binary(recs, backend, label, work, rt_o)
    if exe is None and err is None:
        return 0
    if err is None:
        return 1
    if len(recs) > 1:
        return sum(build_group([r], backend, "%s_p%d" % (label, r["idx"]), work, rt_o) for r in recs)
    # single program: build the proof and safe modules separately and keep build_error only for the failing mode
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
    """Bundle the prepared programs --batch at a time and build one rust and one llvm executable per batch in parallel. -> number of executables"""
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


# ---------------------------------------------------------------- phase 5: run

def run_one(exe, rid):
    rc, so, se = run_cmd([exe, str(rid)], 10)
    pruv_line = ""
    for line in se.splitlines():
        if line.startswith("pruv: "):
            pruv_line = line
            break
    return {"exit": rc, "stdout": so, "pruv": pruv_line}


def run_repeated(exe, rid):
    first = run_one(exe, rid)
    second = run_one(exe, rid)
    return first, second


def run_all(progs, jobs):
    """Run every (program, mode, input) by id; G7 also records a second execution."""
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
        futs = {ex.submit(run_repeated if rec.get("case", {}).get("g7") else run_one, exe, rid): (rec, name, k) for rec, name, k, exe, rid in tasks}
        for f in cf.as_completed(futs):
            rec, name, k = futs[f]
            try:
                result = f.result()
                if rec.get("case", {}).get("g7"):
                    result, repeat = result
                    rec.setdefault("repeats", {}).setdefault(name, {})[k] = repeat
                    if repeat != result:
                        rec["failures"].append({"kind": "repeat_mismatch", "input": k, "mode": name,
                                                "first": result, "repeat": repeat})
                rec["runs"][name][k] = result
            except Exception:
                rec["failures"].append({"kind": "harness_error", "detail": traceback.format_exc()[-1500:]})
                rec["runs"][name][k] = {"exit": -998, "stdout": "", "pruv": ""}
            done += 1
            if done % 500 == 0:
                print("[run] %d/%d" % (done, len(tasks)), flush=True)


# ---------------------------------------------------------------- phase 6: check

def expected_stdout(o):
    lines = ["%s\n" % str(l).rstrip("\n") for l in (o.get("output") or [])]
    lines.append(oracle.format_value(o.get("value")) + "\n")
    return "".join(lines)


def fault_stdout(o):
    """Lines the oracle printed up to the fault (empty string if none)."""
    return "".join("%s\n" % str(l).rstrip("\n") for l in (o.get("output") or []))


def outcome_key(o):
    """Key for comparing whether oracle results are the same: (kind, value, output, detail prefix)."""
    kind = o.get("kind")
    pre = None
    if kind in FAULT_KINDS:
        try:
            pre = oracle.expected_stderr_prefix(o)
        except Exception:
            pre = None
    return (kind, repr(o.get("value")), tuple(str(l) for l in (o.get("output") or [])), pre)


def stderr_prefix(o, g3=False):
    """Expected start of the `pruv: ` line. In G3 mode the callee name of `requires violated` is not compared, because
    the run-time name of a generic instance (a mangled pruv_g3_f_... name) is compiler-defined."""
    pre = oracle.expected_stderr_prefix(o)
    if g3 and pre and pre.startswith("pruv: requires violated: "):
        # a specialized generic callee reports its instance name (pruv_g3_f_<len>_<name>_<args>), so only the
        # message kind is compared; which clause failed is still checked through the oracle's exit code and stdout
        pre = "pruv: requires violated: "
    return pre


def mode_oracle(rec, m, k):
    """Expected result of mode m: oracle_proof for proof modes, oracle_safe for safe modes."""
    key = "oracle_proof" if m.endswith("-proof") else "oracle_safe"
    lst = rec.get(key) or rec["oracle"]
    return lst[k]


def check(rec):
    """Return the failure list; the count of comparisons that could not be completed (oracle limit) goes into rec['incomplete']."""
    fails = []
    incomplete = 0
    modes = list(rec["runs"])
    verified = rec["status"] == "verified"
    # G4 compares only the message kind of `requires violated` (the callee name in a module program is source-qualified)
    g3 = bool((rec.get("case") or {}).get("g3") or (rec.get("case") or {}).get("g4") or (rec.get("case") or {}).get("g5"))
    for k, args in enumerate(rec["inputs"]):
        runs = {m: rec["runs"][m][k] for m in modes}
        orc = {m: mode_oracle(rec, m, k) for m in modes}
        sigs = {m: (runs[m]["exit"], runs[m]["stdout"], runs[m]["pruv"]) for m in modes}
        # 1) soundness: before skipping limit (a limit result can also carry contract_failures)
        if verified:
            op = (rec.get("oracle_proof") or rec["oracle"])[k]
            pk = op.get("kind")
            if pk == "requires_undefined" and "i128" not in str(op.get("detail")):
                # Spec A: the domain was proven, so requires undefined can arise only from i128 overflow or the iteration budget
                fails.append({"kind": "unsound", "input": k,
                              "detail": "verified but requires was evaluated outside its domain: %s" % op.get("detail")})
            elif rec["req"][k] == "ok" and (pk in FAULT_KINDS or op.get("contract_failures")):
                fails.append({"kind": "unsound", "input": k,
                              "detail": "verified + requires satisfied but oracle(proof)=%s (%s) contract_failures=%s"
                                        % (pk, op.get("detail"), op.get("contract_failures"))})
        # 2) oracle exceptions (the same result object only once)
        seen_err = set()
        for m in modes:
            if orc[m].get("kind") == "oracle_error" and id(orc[m]) not in seen_err:
                seen_err.add(id(orc[m]))
                fails.append({"kind": "oracle_error", "input": k, "mode": m, "detail": orc[m].get("detail")})
        # 3) mode agreement: modes with the same expected outcome must match exactly, and rust-X == llvm-X must always match
        groups = {}
        for m in modes:
            # limit is not a definitive result: even with the same limit, actual runs may legitimately differ per mode
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
                continue  # timeouts are counted separately as run_timeout / incomplete
            if sigs[a] != sigs[b]:
                bad.update((a, b))
        if bad:
            fails.append({"kind": "mode_mismatch", "input": k,
                          "detail": "; ".join("%s=%r" % (m, sigs[m]) for m in modes if m in bad)})
        # 4) per-mode oracle comparison
        for m in modes:
            o = orc[m]
            okind = o.get("kind")
            run = runs[m]
            if okind == "oracle_error":
                continue
            if okind == "limit":
                incomplete += 1  # whether or not the run timed out, the comparison could not be completed
                continue
            if run["exit"] == TIMEOUT_RC:
                fails.append({"kind": "run_timeout", "input": k, "mode": m, "detail": "exceeded 10 s"})
                continue
            if okind == "ok":
                want = expected_stdout(o)
                if run["exit"] != 0 or run["stdout"] != want or run["pruv"] != "":
                    fails.append({"kind": "oracle_mismatch", "input": k, "mode": m,
                                  "detail": "oracle ok %r; got exit %d stdout %r pruv %r"
                                            % (want, run["exit"], run["stdout"], run["pruv"])})
            elif okind in FAULT_KINDS:
                pre = stderr_prefix(o, g3)
                want = fault_stdout(o)
                if run["exit"] != 101 or (pre is not None and not run["pruv"].startswith(pre)) \
                        or run["stdout"] != want:
                    fails.append({"kind": "oracle_mismatch", "input": k, "mode": m,
                                  "detail": "oracle %s (%s) -> want exit 101 + %r + stdout %r; got exit %d stdout %r pruv %r"
                                            % (okind, o.get("detail"), pre, want, run["exit"],
                                               run["stdout"], run["pruv"])})
    rec["incomplete"] = incomplete
    return fails


# ---------------------------------------------------------------- save / print

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
    if is_tree(rec.get("case") or {}):
        write_tree(d, rec["case"]["files"])       # G4/G5: the whole program (root.pruv + modules), `--replay <this folder>` works
    else:
        write(os.path.join(d, "case.pruv"), rec["src"])
    write(os.path.join(d, "inputs.json"), json.dumps(rec.get("inputs", []), indent=1))
    res = {"name": rec["name"], "status": rec["status"], "params": rec["params"], "ret": rec["ret"],
           "failures": items, "build_errors": rec.get("build_errors", {}), "inputs": rec_results(rec)}
    if (rec.get("case") or {}).get("g7"):
        res["g7"] = True
        res["g7_features"] = rec["case"]["g7_features"] if "g7_features" in rec["case"] else []
        res["repeats"] = rec.get("repeats", {})
    if (rec.get("case") or {}).get("g2"):   # g2 cases only (results.json of existing cases is unchanged)
        res["g2"] = True
        res["g2_features"] = rec["case"].get("g2_features", [])
    if (rec.get("case") or {}).get("g3"):   # g3 cases only
        res["g3"] = True
        res["g3_features"] = rec["case"].get("g3_features", [])
        res["g3_unproved_by_design"] = bool(rec["case"].get("g3_bad"))
        res["g3_mutation"] = rec["case"].get("g3_mutation")
    if (rec.get("case") or {}).get("g6"):   # g6 cases only
        res["g6"] = True
        res["g6_features"] = rec["case"].get("g6_features", [])
        res["g6_unproved_by_design"] = bool(rec["case"].get("g6_bad"))
        res["g6_mutation"] = rec["case"].get("g6_mutation")
    if (rec.get("case") or {}).get("g9"):   # g9 cases only
        res["g9"] = True
        res["g9_features"] = rec["case"].get("g9_features", [])
        res["g9_unproved_by_design"] = bool(rec["case"].get("g9_bad"))
        res["g9_mutation"] = rec["case"].get("g9_mutation")
    if (rec.get("case") or {}).get("g4"):   # g4 cases only
        res["g4"] = True
        res["g4_features"] = rec["case"].get("g4_features", [])
        res["g4_twin"] = rec["case"].get("g4_twin")
        res["g4_variant"] = rec["case"].get("g4_variant")
    if (rec.get("case") or {}).get("g5"):   # g5 cases only: features, twin info and the exact replay command
        res["g5"] = True
        res["g5_features"] = rec["case"].get("g5_features", [])
        res["g5_twin"] = rec["case"].get("g5_twin")
        res["g5_variant"] = rec["case"].get("g5_variant")
        res["replay"] = "python bench/fuzz/run.py --replay %s --compiler %s" % (
            os.path.relpath(d, ROOT) if d.startswith(ROOT) else d, DRIVER.name if DRIVER is not None else "rs")
    write(os.path.join(d, "results.json"), json.dumps(res, indent=1, default=str))
    write(os.path.join(d, "pruvc_output.txt"),
          "".join("== %s ==\n%s\n" % (k, v) for k, v in rec["logs"].items()))
    # this program's own generated files (not rewritten)
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
    print("program %s: status=%s codes=%s" % (rec["name"], rec["status"], ",".join(rec.get("codes", [])) or "-"))
    for m, e in rec.get("build_errors", {}).items():
        print("  build failed %s: %s" % (m, e[:200].replace("\n", " ")))
    print("  %-3s %-34s %-28s %s" % ("#", "args (requires)", "oracle", " | ".join(modes)))
    for k, args in enumerate(rec.get("inputs", [])):
        o = rec["oracle"][k]
        osum = "%s %s" % (o.get("kind"), o.get("value") if o.get("kind") == "ok" else (o.get("detail") or ""))
        cells = []
        for m in modes:
            r = rec["runs"][m][k]
            cells.append("%s/%s" % (r["exit"], (r["stdout"].strip() or r["pruv"])[:40]))
        print("  %-3d %-34s %-28s %s" % (k, "%s (%s)" % (short(args, 26), rec["req"][k]), osum[:28], " | ".join(cells)))


def guard(fn, rec, *a):
    """Record a worker-thread exception as a harness failure."""
    try:
        return fn(rec, *a)
    except Exception:
        rec["failures"].append({"kind": "harness_error", "detail": traceback.format_exc()[-1500:]})
        return rec


# ---------------------------------------------------------------- replay

def replay(path, args):
    if os.path.isdir(path):
        pruv = os.path.join(path, "case.pruv")
        if os.path.exists(os.path.join(path, "root.pruv")):
            pruv = os.path.join(path, "root.pruv")      # G4 program directory
        elif not os.path.exists(pruv):
            cand = sorted(f for f in os.listdir(path) if f.endswith(".pruv"))
            if not cand:
                print("no .pruv file found: " + path)
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
        print("could not find inputs.json: " + base)
        return 2
    with open(pruv, encoding="utf-8") as fh:
        src = fh.read()
    with open(inp, encoding="utf-8") as fh:
        inputs = json.load(fh)
    params, ret = signature_from_src(src)
    case = {"name": "replay_" + os.path.splitext(os.path.basename(pruv))[0], "src": src, "entry": "f",
            "params": params, "ret": ret, "input_hints": {}}
    if os.path.basename(pruv) == "root.pruv":
        case["g4"] = True   # G4 program (saved by --g4): all module files next to root.pruv, see phase_a / oracle.parse_modules
        case["files"] = read_tree(base)
        if any(re.search(r"\binout\s+\w+\s*:", t) for t in case["files"].values()):
            case["g5"] = True   # G5 program (saved by --g5): inout parameters, same program-directory handling as G4
    if src.startswith("// g7 fuzz case") or args.g7:
        case["g7"] = True
        case.setdefault("files", {"root.pruv": src})
    if "::<" in src:
        case["g3"] = True   # generic program: the run-time callee name of a generic instance is not compared strictly
    if re.search(r"\b(vec_new|map_new|string_new)\b|\btrusted\s+rust\s+fn\b", src):
        case["g6"] = True   # G6 program: collections / trusted Rust calls (shim symbols are renamed per module, see prep_llvm)
    if src.startswith("// g9 fuzz case"):
        case["g9"] = True   # G9 program (saved by --g9): the oracle needs a deeper Python recursion limit, see g9_prepare_process
        g9_prepare_process()
    if any(t in ("array_u8", "array_bool", "str") for t in [p[1] for p in params] + [ret]):
        case["g2"] = True   # G2 types (the driver only looks at the params/ret strings); g2_features is left empty if the saved copy has none
        case["g2_features"] = []
    work = tempfile.mkdtemp(prefix="pruvfuzz_replay_%s_" % driver().name)
    try:
        rt_o = build_runtime(work)
        rec = phase_a(case, work)
        if "prog" not in rec or rec["status"] not in ("verified", "rejected"):
            print("status=%s %s %s" % (rec["status"], rec.get("detail", ""), rec["failures"]))
            return 1
        rec["idx"] = 0
        guard(phase_b, rec, args, rt_o, inputs)
        build_all([rec], args, work, rt_o)  # batch of size 1, same path as the main run
        run_all([rec], args.jobs)
        if "runs" in rec:
            rec["failures"] += check(rec)
        if "oracle" in rec:
            print_table(rec)
        for f in rec["failures"]:
            print("failure [%s] input=%s mode=%s: %s" % (f["kind"], f.get("input", "-"), f.get("mode", "-"),
                                                     str(f["detail"])[:400]))
        print("comparisons not completed (oracle limit): %d" % rec.get("incomplete", 0))
        print("failures: %d" % len(rec["failures"]))
        return 1 if rec["failures"] else 0
    finally:
        if args.keep_work:
            print("work folder: " + work)
        else:
            shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- G3 helpers

def g3_unproved(r):
    """A rejected program that the generator built to be unproved (dropped requires, false ensures, wrong fragment, ...)."""
    return bool((r.get("case") or {}).get("g3_bad"))


def g6_unproved(r):
    """A rejected program that the G6 generator built to be unproved (dropped requires, false ensures, body mutation, ...)."""
    return bool((r.get("case") or {}).get("g6_bad"))


def g9_unproved(r):
    """A rejected program that the G9 generator built to be unproved (false ensures, wrong decreases/phase, wrong return or base
    case, missing base case, dropped helper contract)."""
    return bool((r.get("case") or {}).get("g9_bad"))


def g9_prepare_process():
    """G9 oracle runs recursive Pruv programs as nested Python calls (about 10 frames per Pruv call). The generators bound the
    depth (a few dozen calls), so a moderate recursion limit and a large stack for the worker threads are enough; a RecursionError
    would be reported as an oracle_error (never as a pass)."""
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 8000))
    try:
        import threading
        threading.stack_size(128 * 1024 * 1024)
    except (ValueError, RuntimeError):
        pass


def g4_twin_check(progs):
    """G4 contract-preserving body replacement: the two programs of a twin pair (same g4_twin key, variants 0 and 1) differ
    only in one callee body that satisfies the same functional contract, so for every common mode and input they must give the
    identical (exit code, stdout, `pruv:` line). A mismatch is recorded as `twin_mismatch` on the variant-1 program.
    -> number of pairs that were compared (pairs with a missing or failed half are skipped and not counted)."""
    groups = {}
    for r in progs:
        key = (r.get("case") or {}).get("g4_twin") or (r.get("case") or {}).get("g5_twin")      # G5 twins use the same check
        if key and r.get("runs"):
            groups.setdefault(key, []).append(r)
    compared = 0
    for _key, lst in sorted(groups.items()):
        if len(lst) != 2:
            continue
        a, b = sorted(lst, key=lambda r: r["case"].get("g4_variant", r["case"].get("g5_variant")))
        if a["inputs"] != b["inputs"]:
            b["failures"].append({"kind": "harness_error", "detail": "twin programs %s/%s got different inputs"
                                                                     % (a["name"], b["name"])})
            continue
        common = [m for m in a["runs"] if m in b["runs"]]
        if not common:
            continue
        compared += 1
        for m in common:
            for k in range(len(a["inputs"])):
                ra, rb = a["runs"][m][k], b["runs"][m][k]
                if ra is None or rb is None or TIMEOUT_RC in (ra["exit"], rb["exit"]):
                    continue
                sa = (ra["exit"], ra["stdout"], ra["pruv"])
                sb = (rb["exit"], rb["stdout"], rb["pruv"])
                if sa != sb:
                    b["failures"].append({"kind": "twin_mismatch", "input": k, "mode": m,
                                          "detail": "%s=%r vs %s=%r" % (a["name"], sa, b["name"], sb)})
    return compared


# G5: feature tags (docs/G5_SPEC.md section 14 item 2) that at least one counted verified program of every run must carry;
# the twin tag is checked through the number of twin pairs that were really compared
G5_REQUIRED = ["type_i64", "type_u8", "type_bool", "generic_instance", "repeated_reborrow", "nested_reborrow",
               "multi_owner", "loop", "recursion", "module_call", "old_contract"]
G5_INFER_MIN = 10           # --infer must be exercised on at least this many programs per seed
G5_INFER_PROBED = 12        # programs probed (a few spare: a probe that fails does not count)


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


def infer_probe(rec):
    """G5 `--infer` probe of a verified program (docs/G5_SPEC.md 5.3, section 14 item 3).
    (1) The program as generated, with its explicit loop invariants: `--infer` must still verify it (explicit invariants are
        always checked; inference may not break a valid program). The emitted Rust is compared with the plain verified Rust.
    (2) A copy with every `invariant` line removed: inference may or may not rediscover them (a rejection is fine), but an
        accepted copy must emit the same Rust as the explicit program (invariants are erased), otherwise it is reported.
    Exit codes other than 0/1 and timeouts are failures. -> result dict (failures are appended to rec["failures"])."""
    res = {"name": rec["name"], "exit": None, "same_rust": None, "stripped_exit": None, "stripped_same_rust": None}
    ref = _read_text(rec["ver_rs"])
    out = os.path.join(rec["dir"], "infer_gen.rs")
    if os.path.exists(out):
        os.remove(out)
    rc, so, se = run_cmd(driver().argv(rec["pruv"], out, ["--infer"], "rust"), 120)
    res["exit"] = rc
    if rc == 0:
        got = _read_text(out)
        res["same_rust"] = None if ref is None or got is None else got == ref
    else:
        rec["failures"].append({"kind": "timeout" if rc == TIMEOUT_RC else "infer_failure",
                                "detail": "--infer on the verified program: exit %d: %s" % (rc, (so + se).strip()[-400:])})
    if rec["case"].get("g5_has_invariant"):
        sd = os.path.join(rec["dir"], "noinv")
        write_tree(sd, generate.g5_strip_invariants(rec["case"]["files"]))
        sout = os.path.join(sd, "infer_gen.rs")
        rc2, so2, se2 = run_cmd(driver().argv(os.path.join(sd, "root.pruv"), sout, ["--infer"], "rust"), 120)
        res["stripped_exit"] = rc2
        if rc2 == 0:
            got = _read_text(sout)
            res["stripped_same_rust"] = None if ref is None or got is None else got == ref
        elif rc2 != 1:
            rec["failures"].append({"kind": "timeout" if rc2 == TIMEOUT_RC else "infer_failure",
                                    "detail": "--infer on the invariant-free copy: exit %d: %s"
                                              % (rc2, (so2 + se2).strip()[-400:])})
    return res


def g5_infer_all(recs, jobs):
    out = []
    with cf.ThreadPoolExecutor(jobs) as ex:
        futs = [(r, ex.submit(infer_probe, r)) for r in recs]
        for r, f in futs:
            try:
                out.append(f.result())
            except Exception:
                r["failures"].append({"kind": "harness_error", "detail": traceback.format_exc()[-1500:]})
                out.append({"name": r["name"], "exit": None, "error": True})
    return out


def g3_ran(r, names):
    runs = r.get("runs") or {}
    return all(n in runs and runs[n] and all(x is not None and x["exit"] not in (TIMEOUT_RC, -998) for x in runs[n])
               for n in names)


def g3_counted(r, verified_prog, min_inputs, key="g3"):
    """Counting condition of the G3 gate (same shape as the G2 one): a g3 case, at least `min_inputs` inputs, every run result
    present (no timeout, no harness exception), and for a verified program at least one input that satisfies requires and
    that the proof-mode oracle compared to the end (not `limit`, not an oracle error). Crashes, timeouts, unknowns and
    unsupported oracle cases are therefore never counted as success. (`key="g6"`: the same condition for G6 cases.)"""
    if not (r.get("case") or {}).get(key) or len(r.get("inputs", [])) < min_inputs:
        return False
    if not g3_ran(r, [m[0] for m in SAFE_MODES]):
        return False
    if r.get("failures"):
        return False
    if verified_prog:
        if not g3_ran(r, [m[0] for m in MODES]):
            return False
        ops = r.get("oracle_proof") or []
        return any(q == "ok" and o.get("kind") not in ("limit", "oracle_error") for q, o in zip(r.get("req", []), ops))
    return any(o.get("kind") not in ("limit", "oracle_error") for o in r.get("oracle_safe", []))


def g3_comparisons(progs):
    """Number of (program, mode, input) executions that were really compared with the oracle, and the number that were not
    (timeout, harness exception, oracle limit, oracle error)."""
    done = skipped = 0
    for r in progs:
        for m, lst in (r.get("runs") or {}).items():
            for k, run in enumerate(lst):
                o = mode_oracle(r, m, k) if k < len(r.get("oracle", [])) else {"kind": "oracle_error"}
                if run is None or run["exit"] in (TIMEOUT_RC, -998) or o.get("kind") in ("limit", "oracle_error"):
                    skipped += 1
                else:
                    done += 1
    return done, skipped


def g3_digests(progs):
    """Hashes of what every program did (status + exit code + stdout [+ pruv line] per mode and input). Runs of two compilers
    on the same seed generate the same programs and inputs, so equal digests mean the compilers behaved identically."""
    full, quiet = hashlib.sha256(), hashlib.sha256()
    for r in sorted(progs, key=lambda x: x["name"]):
        head = ("%s|%s\n" % (r["name"], r["status"])).encode()
        full.update(head)
        quiet.update(head)
        for m in sorted(r.get("runs") or {}):
            for k, run in enumerate(r["runs"][m]):
                if run is None:
                    continue
                full.update(("%s|%d|%s|%r|%r\n" % (m, k, run["exit"], run["stdout"], run["pruv"])).encode())
                quiet.update(("%s|%d|%s|%r\n" % (m, k, run["exit"], run["stdout"])).encode())
    return full.hexdigest(), quiet.hexdigest()


def run_seeds(args):
    """--seeds 41,56,57: run this script once per seed (child processes) with every other option unchanged.
    Each child writes its own summary; the exit code is 1 if any child failed."""
    raw, base, i = sys.argv[1:], [], 0
    while i < len(raw):
        a = raw[i]
        if a in ("--seeds", "--seed", "--out"):
            i += 2
        elif a.startswith(("--seeds=", "--seed=", "--out=")):
            i += 1
        else:
            base.append(a)
            i += 1
    rc = 0
    for s in [x.strip() for x in args.seeds.split(",") if x.strip()]:
        cmd = [sys.executable, os.path.abspath(__file__)] + base + ["--seed", s]
        if args.out:
            cmd += ["--out", os.path.join(args.out, s)]
        print("==== seed %s ====" % s, flush=True)
        if subprocess.call(cmd) != 0:
            rc = 1
    return rc


# ---------------------------------------------------------------- main run

def run_s5(args):
    """Stage 5 gate: finite candidates, no replacement/padding, persisted replay inputs."""
    start = time.time()
    out = args.out or os.path.join(HERE, "results_s5")
    os.makedirs(out, exist_ok=True)
    cases = []
    if args.replay:
        with open(os.path.join(args.replay, "case.json")) as fh:
            cases = [json.load(fh)]
    else:
        for i in range(args.programs or 30):
            case = generate.generate_s5_case(args.seed, i)
            case["fixed_inputs"] = generate.s5_inputs(args.seed, i, args.inputs)
            cases.append(case)
            if case["twin_src"]:
                twin = dict(case, name=case["name"] + "_minus_one",
                            src=case["twin_src"], s5_twin=True, twin_src=None)
                cases.append(twin)
    originals = [c for c in cases if not c["s5_twin"]]
    twins = [c for c in cases if c["s5_twin"]]
    summary = {"s5": True, "seed": args.seed, "compiler": DRIVER.name,
               "programs_generated": len(originals), "programs_verified": 0,
               "programs_rejected": 0, "twins_generated": len(twins),
               "twins_rejected": 0, "twins_accepted": 0,
               "comparisons_target": sum(len(c["fixed_inputs"]) * (2 if c["s5_twin"] else 4) for c in cases),
               "comparisons_completed": 0, "mismatches": 0, "oracle_gaps": 0,
               "safe_panics_expected": 0, "safe_panics_observed": 0,
               "original_safe_panics": 0, "failures": [], "programs": []}
    # All transient sources, compiler outputs and temp files stay in the work folder.
    with tempfile.TemporaryDirectory(prefix=".s5-work-", dir=HERE) as work:
        old_tmp = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = work
        try:
            with cf.ThreadPoolExecutor(max(1, args.jobs)) as ex:
                records = list(ex.map(lambda c: phase_a(c, work), cases))
            try:
                rt_o = build_runtime(work)
            except Exception as exc:
                rt_o = None
                summary["failures"].append({"kind": "runtime_build", "detail": str(exc)})
            for i, rec in enumerate(records):
                rec["idx"] = i
                twin = rec["case"]["s5_twin"]
                status = rec["status"]
                if twin:
                    if status == "verified":
                        summary["twins_accepted"] += 1
                        rec["failures"].append({"kind": "twin_wrongly_verified"})
                    elif status == "rejected" and "verify:cost_bound" in rec["codes"]:
                        summary["twins_rejected"] += 1
                    else:
                        rec["failures"].append({"kind": "twin_wrong_rejection", "codes": rec["codes"]})
                elif status == "verified":
                    summary["programs_verified"] += 1
                else:
                    summary["programs_rejected"] += int(status == "rejected")
                    rec["failures"].append({"kind": "original_not_verified", "status": status})
                if status in ("verified", "rejected"):
                    choose_inputs(rec, args, rec["case"]["fixed_inputs"])
                    if twin:
                        # Even a wrongly verified twin is run only with runtime checks.
                        rec["status"] = "rejected"
                    if rt_o:
                        phase_b(rec, args, rt_o, rec["case"]["fixed_inputs"])
                    rec["status"] = status
                else:
                    summary["oracle_gaps"] += int(status.startswith("oracle_"))
            if rt_o:
                build_all(records, args, work, rt_o)
                run_all(records, args.jobs)
            for rec in records:
                for mode, rows in rec.get("runs", {}).items():
                    for k, actual in enumerate(rows):
                        expected = mode_oracle(rec, mode, k)
                        if expected["kind"] not in ("ok", "cost_exceeded"):
                            summary["oracle_gaps"] += 1
                            rec["failures"].append({"kind": "oracle_gap", "mode": mode, "input": k,
                                                    "detail": expected})
                            continue
                        safe = mode.endswith("-safe")
                        panic = actual["exit"] == 101 and actual["pruv"].startswith("pruv: cost exceeded")
                        summary["safe_panics_observed"] += int(safe and panic)
                        summary["original_safe_panics"] += int(safe and panic and not rec["case"]["s5_twin"])
                        if actual["exit"] in (TIMEOUT_RC, -998):
                            rec["failures"].append({"kind": "run_incomplete", "mode": mode, "input": k})
                            continue
                        summary["comparisons_completed"] += 1
                        ok = expected["kind"] == "ok"
                        matches = (actual["exit"] == (0 if ok else 101)
                                   and actual["stdout"] == (expected_stdout(expected) if ok else fault_stdout(expected))
                                   and (not actual["pruv"] if ok else panic))
                        if not matches:
                            summary["mismatches"] += 1
                            rec["failures"].append({"kind": "oracle_mismatch", "mode": mode, "input": k,
                                                    "expected": expected, "actual": actual})
                for expected in rec.get("oracle_safe", []):
                    summary["safe_panics_expected"] += 2 * int(expected["kind"] == "cost_exceeded")
                    if not rec["case"]["s5_twin"] and (expected["kind"] != "ok" or expected["contract_failures"]):
                        rec["failures"].append({"kind": "generator_or_oracle_invalid", "detail": expected})
                row = {"name": rec["name"], "family": rec["case"]["kind"], "twin": rec["case"]["s5_twin"],
                       "status": rec["status"], "codes": rec["codes"]}
                summary["programs"].append(row)
                if rec["failures"]:
                    dest = os.path.join(out, "repro", DRIVER.name + "_" + rec["name"])
                    os.makedirs(dest, exist_ok=True)
                    write(os.path.join(dest, "case.pruv"), rec["src"])
                    write(os.path.join(dest, "case.json"), json.dumps(rec["case"], indent=2))
                    write(os.path.join(dest, "results.json"), json.dumps(
                        {"failures": rec["failures"], "inputs": rec_results(rec), "logs": rec["logs"]}, indent=2))
                    summary["failures"].append({"program": rec["name"], "reproducer": os.path.relpath(dest, ROOT),
                                                "kinds": [f["kind"] for f in rec["failures"]]})
        finally:
            if old_tmp is None:
                os.environ.pop("TMPDIR", None)
            else:
                os.environ["TMPDIR"] = old_tmp
    summary["incomplete"] = summary["comparisons_target"] - summary["comparisons_completed"]
    summary["elapsed_seconds"] = round(time.time() - start, 3)
    path = os.path.join(out, ("replay_" if args.replay else "") + "%s_%s.json" % (args.seed, DRIVER.name))
    write(path, json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "programs"}, indent=2))
    return int(bool(summary["failures"] or summary["incomplete"]))


def main():
    ap = argparse.ArgumentParser(description="Pruv differential fuzzing")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--programs", type=int, default=None, help="default 100 (30 with --g4/--g5)")
    ap.add_argument("--inputs", type=int, default=8)
    ap.add_argument("--max-candidates", type=int, default=400)
    ap.add_argument("--rejected-sample", type=int, default=30)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    ap.add_argument("--out", default=None)
    ap.add_argument("--batch", type=int, default=25, help="number of programs to bundle into one executable")
    ap.add_argument("--avoid-known", default="",
                    help="comma-separated ids of defects already reported (e.g. fz01); the generator will not produce that shape")
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--replay", default=None)
    ap.add_argument("--g2", action="store_true",
                    help="G2 mode: generate only u8/bool array and str templates, output folder ends in _g2, gate (g2_shortfall) applies")
    ap.add_argument("--g3", action="store_true",
                    help="G3 mode: generic programs (explicit type arguments, [T], Option/Result/Pair/Choice instances), "
                         "output folder ends in _g3, gate (g3_shortfall) applies; --rejected-sample is not used")
    ap.add_argument("--g3-safe-only", type=int, default=20,
                    help="G3 mode: number of deliberately unproved programs that must be built and run in safe mode only")
    ap.add_argument("--g6", action="store_true",
                    help="G6 mode: trusted Rust calls (std::cmp::min/max) and Vec/HashMap/String programs (take/move, catalog "
                         "operations); output folder out/g6_<seed>[_rs], gate (g6_shortfall) applies; --rejected-sample is not used")
    ap.add_argument("--g6-safe-only", type=int, default=20,
                    help="G6 mode: number of deliberately unproved programs that must be built and run in safe mode only")
    ap.add_argument("--g9", action="store_true",
                    help="G9 mode: recursion (direct, mutual, phase measures), recursive types (bounded trees/lists, token cursor "
                         "descent) and buffer fields (clone isolation, field replacement); output folder out/g9_<seed>[_rs], "
                         "gate (g9_shortfall) applies; --rejected-sample is not used")
    ap.add_argument("--g9-safe-only", type=int, default=20,
                    help="G9 mode: number of deliberately unproved programs that must be built and run in safe mode only")
    ap.add_argument("--g4", action="store_true",
                    help="G4 mode: multi-module programs (a directory per program: root.pruv + 1-4 module files, some nested "
                         "a/b.pruv), host entry `pub fn f` in the root, contract-preserving body-replacement twins; output "
                         "folder out/g4_<seed>[_rs], gate (g4_shortfall) applies, every program is meant to verify; "
                         "--rejected-sample is not used")
    ap.add_argument("--g5", action="store_true",
                    help="G5 mode: inout-parameter programs (directory per program: root.pruv + optional module files, host "
                         "entry `pub fn f` copies its input and calls inout helpers), contract-preserving body-replacement "
                         "twins, --infer probe on >= 10 programs; output folder out/g5_<seed>[_rs], gates (g5_shortfall, "
                         "g5_comparison_shortfall, g5_infer_shortfall) apply, every program is meant to verify; "
                         "--rejected-sample is not used")
    ap.add_argument("--seeds", default=None,
                    help="comma-separated seeds (e.g. 41,56,57): one run per seed with the other options unchanged; "
                         "with --out each seed gets the subfolder OUT/<seed>")
    CD.add_args(ap)
    ap.add_argument("--g7", action="store_true", help="G7 parallel calls; twice per input, four modes")
    ap.add_argument("--s5", action="store_true", help="Stage 5 cost differential gate")
    args = ap.parse_args()
    if args.s5 and any((args.g2, args.g3, args.g4, args.g5, args.g6, args.g7, args.g9)):
        ap.error("--s5 is a separate mode")
    if args.s5 and (args.inputs < 1 or args.jobs < 1 or (args.programs is not None and args.programs < 1)):
        ap.error("--s5 requires positive --programs, --inputs and --jobs")
    if args.g7 and any((args.g2, args.g3, args.g4, args.g5, args.g6, args.g9)):
        ap.error("--g7 is a separate mode")
    if args.seeds:
        return run_seeds(args)
    global DRIVER
    DRIVER = CD.from_args(args)
    if args.s5:
        return run_s5(args)
    generate.AVOID.update(x.strip() for x in args.avoid_known.split(",") if x.strip())
    if args.g3 and args.g2:
        ap.error("--g2 and --g3 are separate modes")
    if args.g6 and (args.g2 or args.g3):
        ap.error("--g6 is a separate mode (not combinable with --g2/--g3)")
    if args.g9 and (args.g2 or args.g3 or args.g6):
        ap.error("--g9 is a separate mode (not combinable with --g2/--g3/--g6)")
    if args.g4 and (args.g2 or args.g3 or args.g6 or args.g9):
        ap.error("--g4 is a separate mode (not combinable with --g2/--g3/--g6/--g9)")
    if args.g5 and (args.g2 or args.g3 or args.g6 or args.g9 or args.g4):
        ap.error("--g5 is a separate mode (not combinable with --g2/--g3/--g6/--g9/--g4)")
    if args.programs is None:
        args.programs = 30 if (args.g4 or args.g5 or args.g7) else 100
    if args.g3 or args.g6 or args.g9 or args.g4 or args.g5:
        args.inputs = max(args.inputs, 8)    # exit criterion: at least eight concrete inputs per accepted program
    if args.g9:
        g9_prepare_process()
    if args.replay:
        return replay(args.replay, args)
    # per-compiler result/work folders: the py default path (out/<seed>) is unchanged, rs uses out/<seed>_rs;
    # G6: out/g6_<seed> (py), out/g6_<seed>_rs (rs); G9: out/g9_<seed>[_rs]
    if args.g7:
        args.max_candidates = args.programs
    out_dir = args.out or os.path.join(HERE, "out", ("g7_" if args.g7 else "g5_" if args.g5 else "g4_" if args.g4 else "g9_" if args.g9
                                                     else "g6_" if args.g6 else "")
                                       + str(args.seed)
                                       + ("" if DRIVER.name == "py" else "_" + DRIVER.name)
                                       + ("_g2" if args.g2 else "") + ("_g3" if args.g3 else ""))
    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="pruvfuzz_%s_" % DRIVER.name)
    t0 = time.time()
    counts = {"candidates": 0, "generator_invalid": 0, "oracle_unsupported": 0, "oracle_parse_error": 0,
              "verified": 0, "rejected": 0, "rejected_built": 0, "failed_in_phase_a": 0}
    rej_codes = {}
    fail_kinds = {}
    failed_cases = []
    invalid_saved = 0
    oracle_gap_saved = [0]      # G3: number of oracle-unsupported programs saved so far
    try:
        rt_o = build_runtime(work)
        # --- phases 1-2
        verified, rejected_all = [], []
        def candidate(i):
            """Generate candidate i and run it through phase_a. Exceptions are recorded as harness failures."""
            case = None
            try:
                if args.g7:
                    case = generate.generate_case(args.seed, i, g7=True)
                elif args.g5:
                    case = generate.generate_case(args.seed, i, g5=True)
                elif args.g4:
                    case = generate.generate_case(args.seed, i, g4=True)
                elif args.g9:
                    case = generate.generate_case(args.seed, i, g9=True)
                elif args.g6:
                    case = generate.generate_case(args.seed, i, g6=True)
                elif args.g3:
                    case = generate.generate_case(args.seed, i, g3=True)
                else:
                    case = generate.generate_case(args.seed, i, g2=True) if args.g2 else generate.generate_case(args.seed, i)
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
            if args.g7 and st in ("rejected", "oracle_unsupported", "oracle_parse_error", "generator_invalid"):
                save_failure(out_dir, rec, st, [{"kind": st, "detail": rec.get("detail", ""),
                                               "codes": rec.get("codes", [])}])
            if st in ("oracle_unsupported", "oracle_parse_error", "generator_invalid"):
                counts[st] += 1
                if (args.g3 or args.g6 or args.g9 or args.g4 or args.g5) and st != "generator_invalid" and oracle_gap_saved[0] < 10:
                    # an oracle that cannot evaluate a generated program is a gap in the oracle, never a success
                    oracle_gap_saved[0] += 1
                    gd = os.path.join(out_dir, "oracle_gap")
                    os.makedirs(gd, exist_ok=True)
                    save_program(gd, rec)       # G4: a folder <name>/ with the whole program
                    write(os.path.join(gd, rec["name"] + ".txt"), "%s: %s\n" % (st, rec.get("detail", "")))
                if st == "generator_invalid" and invalid_saved < 10:
                    invalid_saved += 1
                    gd = os.path.join(out_dir, "generator_invalid")
                    os.makedirs(gd, exist_ok=True)
                    save_program(gd, rec)
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
            if rec["failures"]:  # failures from phases 1-2 (internal error, timeout) are saved right away
                _record_failures(out_dir, [rec], fail_kinds, failed_cases)
            if counts["candidates"] % 20 == 0:
                print("[generate/verify] candidates %d, pass %d, reject %d, generator errors %d"
                      % (counts["candidates"], counts["verified"], counts["rejected"],
                         counts["generator_invalid"] + counts["oracle_unsupported"]
                         + counts["oracle_parse_error"]), flush=True)

        # Streaming: keep at most jobs*2 in flight and submit the next candidate whenever one finishes.
        # Once enough are collected or --max-candidates is reached, stop submitting but collect the results of every candidate already submitted.
        # G2 mode collects an extra 10% (+5 for rejected) to cover programs dropped by the counting condition (existing path unchanged)
        # G3 mode does the same and additionally keeps generating until enough deliberately unproved programs were rejected
        want_programs = args.programs + (args.programs // 10 if (args.g2 or args.g3 or args.g6 or args.g9 or args.g4
                                                                  or args.g5) else 0)
        want_rejected = args.rejected_sample + (5 if args.g2 else 0)
        if args.g3:
            want_rejected = args.g3_safe_only + 5
        if args.g6:
            want_rejected = args.g6_safe_only + 5
        if args.g9:
            want_rejected = args.g9_safe_only + 5

        def need_more():
            if len(verified) < want_programs:
                return True
            if args.g9:
                return sum(1 for r in rejected_all if g9_unproved(r)) < want_rejected
            if args.g6:
                return sum(1 for r in rejected_all if g6_unproved(r)) < want_rejected
            return args.g3 and sum(1 for r in rejected_all if g3_unproved(r)) < want_rejected

        nxt, cap = 0, max(args.jobs * 2, 2)
        pending = set()
        with cf.ThreadPoolExecutor(args.jobs) as ex:
            while True:
                while len(pending) < cap and nxt < args.max_candidates and need_more():
                    pending.add(ex.submit(candidate, nxt))
                    nxt += 1
                if not pending:
                    break
                done_set, _ = cf.wait(pending, return_when=cf.FIRST_COMPLETED)
                for f in done_set:
                    pending.discard(f)
                    handle(f.result())
        # sort by candidate number so results reproduce regardless of completion order; surplus passing programs are not built
        verified.sort(key=lambda r: r["cand_idx"])
        rejected_all.sort(key=lambda r: r["cand_idx"])
        verified = verified[:want_programs]
        programs_short = len(verified) < args.programs
        if programs_short:
            print("warning: only %d verified programs (requested %d, candidates %d)"
                  % (len(verified), args.programs, counts["candidates"]), flush=True)
        t1 = time.time()
        if args.g3:
            # deliberately unproved programs first; a few rejected programs that were meant to verify ride along (safe modes only)
            unproved = [r for r in rejected_all if g3_unproved(r)]
            unexpected = [r for r in rejected_all if not g3_unproved(r)]
            sample = unproved[:want_rejected] + unexpected[:10]
        elif args.g4 or args.g5 or args.g7:
            # every G4/G5 program is meant to verify: a few rejected ones ride along (safe modes only) so the oracle and the
            # compilers are still compared on them; they are reported as unexpected rejects (G5: never counted as completed)
            sample = rejected_all[:10]
        elif args.g9:
            # same as G6: deliberately unproved programs first, a few rejected "meant to verify" ones ride along (safe modes only)
            unproved = [r for r in rejected_all if g9_unproved(r)]
            unexpected = [r for r in rejected_all if not g9_unproved(r)]
            sample = unproved[:want_rejected] + unexpected[:10]
        elif args.g6:
            # same as G3: deliberately unproved programs first, a few rejected "meant to verify" ones ride along (safe modes only)
            unproved = [r for r in rejected_all if g6_unproved(r)]
            unexpected = [r for r in rejected_all if not g6_unproved(r)]
            sample = unproved[:want_rejected] + unexpected[:10]
        else:
            sample = rejected_all[:want_rejected]
        counts["rejected_built"] = len(sample)
        progs = verified + sample
        # --- phases 3-4 (input selection + clang preparation, then batch build; pruvc already finished in phase_a)
        for i, r in enumerate(progs):
            r["idx"] = i
        done = 0
        with cf.ThreadPoolExecutor(args.jobs) as ex:
            futs = [ex.submit(guard, phase_b, r, args, rt_o) for r in progs]
            for f in cf.as_completed(futs):
                f.result()
                done += 1
                if done % 20 == 0:
                    print("[prepare] %d/%d" % (done, len(progs)), flush=True)
        binaries_built = build_all(progs, args, work, rt_o)
        print("[build] %d executables" % binaries_built, flush=True)
        t2 = time.time()
        # --- phase 5 (run)
        run_all(progs, args.jobs)
        t3 = time.time()
        # --- G5: --infer probe of the first verified programs (failures are recorded on the program and saved below)
        infer_results = g5_infer_all(verified[:G5_INFER_PROBED], args.jobs) if args.g5 else []
        # --- phase 6 (check) + save
        inputs_run = 0
        outcome_counts = {}
        incomplete_total = 0
        input_errors_total = 0
        no_sat = []
        twin_pairs = g4_twin_check(progs) if (args.g4 or args.g5) else 0     # adds twin_mismatch failures before the loop below saves them
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
        if args.g7:
            completed, skipped = g3_comparisons(verified)
            target = args.programs * args.inputs * 4
            feats = {}
            for r in verified:
                for feature in r["case"]["g7_features"]:
                    feats[feature] = feats.get(feature, 0) + 1
            summary.update({
                "g7": True, "compiler": DRIVER.name, "g7_generated": counts["candidates"],
                "g7_verified": counts["verified"], "g7_rejected": counts["rejected"],
                "g7_comparisons_completed": completed, "g7_comparisons_target": target,
                "g7_incomplete": target - completed, "g7_executions_not_compared": skipped,
                "g7_features_verified": feats,
                "g7_mismatches": {k: fail_kinds.get(k, 0) for k in
                                  ("oracle_mismatch", "mode_mismatch", "repeat_mismatch")},
                "g7_oracle_gaps": counts["oracle_unsupported"] + counts["oracle_parse_error"],
                "g7_repeats": sum(len(v) for r in progs for v in r.get("repeats", {}).values()),
            })
            if completed < target:
                fail_kinds["g7_comparison_shortfall"] = target - completed
            if counts["rejected"]:
                fail_kinds["g7_unexpected_reject"] = counts["rejected"]
            for kind in ("generator_invalid", "oracle_unsupported", "oracle_parse_error"):
                if counts[kind]:
                    fail_kinds["g7_" + kind] = counts[kind]
        if args.g2:
            # Keys are added only in G2 mode. The pass count includes only verified programs (verified_used) and rejected ones built and run in safe modes.
            # Counting condition (decision 11, G2_SPEC 8.3): a g2 case, at least --inputs inputs, all safe-mode run results present,
            # and for verified programs at least one input that satisfies requires and that the oracle compared to the end (not limit).
            def _ran(r, names):
                runs = r.get("runs") or {}
                return all(n in runs and runs[n] and all(x is not None and x["exit"] not in (TIMEOUT_RC, -998) for x in runs[n]) for n in names)

            def _counted(r, verified_prog):
                if not (r.get("case") or {}).get("g2") or len(r.get("inputs", [])) < args.inputs:
                    return False
                if not _ran(r, [m[0] for m in SAFE_MODES]):
                    return False
                if verified_prog:
                    if not _ran(r, [m[0] for m in MODES]):
                        return False
                    ops = r.get("oracle_proof") or []
                    return any(q == "ok" and o.get("kind") != "limit" for q, o in zip(r.get("req", []), ops))
                return True

            g2_ver = [r for r in verified if _counted(r, True)]
            feat = {}
            for r in g2_ver:
                for t in (r["case"].get("g2_features") or []):
                    feat[t] = feat.get(t, 0) + 1
            g2_rej_built = sum(1 for r in sample if _counted(r, False))
            ipp = [len(r.get("inputs", [])) for r in progs]
            summary["g2"] = True
            summary["g2_verified"] = len(g2_ver)
            summary["g2_rejected_built_safe_modes"] = g2_rej_built
            summary["g2_features_verified"] = dict(sorted(feat.items()))
            summary["g2_inputs_per_program_min"] = min(ipp) if ipp else 0
            summary["g2_short_inputs"] = sum(1 for n in ipp if n < args.inputs)
            if summary["g2_verified"] < args.programs or g2_rej_built < args.rejected_sample:
                miss_v = max(0, args.programs - summary["g2_verified"])
                miss_r = max(0, args.rejected_sample - g2_rej_built)
                fail_kinds["g2_shortfall"] = miss_v + miss_r   # total number of missing programs
                summary["g2_shortfall"] = {"verified_missing": miss_v, "rejected_built_missing": miss_r}
        if args.g3:
            # Keys are added only in G3 mode. Per seed: generated, verified, safe-only, executions compared, failures.
            failed_set = set(failed_cases)
            g3_ver = [r for r in verified if r["name"] not in failed_set and g3_counted(r, True, args.inputs)]
            g3_safe = [r for r in sample if g3_unproved(r) and r["name"] not in failed_set
                       and g3_counted(r, False, args.inputs)]
            unexpected_rej = [r for r in rejected_all if not g3_unproved(r)]
            feat = {}
            for r in g3_ver:
                for t in (r["case"].get("g3_features") or []):
                    feat[t] = feat.get(t, 0) + 1
            kinds = {}
            for r in g3_ver:
                kinds[r["case"].get("kind")] = kinds.get(r["case"].get("kind"), 0) + 1
            cmp_done, cmp_skipped = g3_comparisons(progs)
            dig_full, dig_quiet = g3_digests(progs)
            ipp = [len(r.get("inputs", [])) for r in progs]
            summary["g3"] = True
            summary["compiler"] = DRIVER.name
            summary["g3_generated"] = counts["candidates"]
            summary["g3_verified"] = len(g3_ver)
            summary["g3_safe_only"] = len(g3_safe)
            summary["g3_executions_compared"] = cmp_done
            summary["g3_executions_not_compared"] = cmp_skipped
            summary["g3_failures"] = sum(fail_kinds.values())
            summary["g3_kinds_verified"] = dict(sorted(kinds.items()))
            summary["g3_features_verified"] = dict(sorted(feat.items()))
            summary["g3_inputs_per_program_min"] = min(ipp) if ipp else 0
            summary["g3_unproved_by_design_verified_anyway"] = sum(1 for r in verified if g3_unproved(r))
            # names and defect labels, so a verified "defect" can be reviewed (a defect can be harmless, e.g. a
            # dropped requires that the body never needed)
            summary["g3_unproved_by_design_verified_names"] = [
                (r.get("name"), (r.get("case") or {}).get("g3_defect") or (r.get("case") or {}).get("kind"))
                for r in verified if g3_unproved(r)]
            summary["g3_unexpected_rejects"] = {
                "count": len(unexpected_rej), "names": [r["name"] for r in unexpected_rej[:20]],
                "codes": sorted(set(c for r in unexpected_rej for c in r.get("codes", [])))}
            summary["g3_digest"] = dig_full
            summary["g3_digest_exit_stdout"] = dig_quiet
            # programs that were meant to verify but did not: keep a few with the verifier output for the generator author
            ud = os.path.join(out_dir, "unexpected_rejects")
            for r in unexpected_rej[:10]:
                os.makedirs(ud, exist_ok=True)
                write(os.path.join(ud, r["name"] + ".pruv"), r["src"])
                write(os.path.join(ud, r["name"] + ".txt"), r["logs"].get("verify", ""))
            # the generator must produce well-typed programs and the oracle must be able to run them
            if counts["generator_invalid"]:
                fail_kinds["g3_generator_invalid"] = counts["generator_invalid"]
            if counts["oracle_unsupported"] + counts["oracle_parse_error"]:
                fail_kinds["g3_oracle_gap"] = counts["oracle_unsupported"] + counts["oracle_parse_error"]
            if summary["g3_verified"] < args.programs or summary["g3_safe_only"] < args.g3_safe_only:
                miss_v = max(0, args.programs - summary["g3_verified"])
                miss_s = max(0, args.g3_safe_only - summary["g3_safe_only"])
                fail_kinds["g3_shortfall"] = miss_v + miss_s
                summary["g3_shortfall"] = {"verified_missing": miss_v, "safe_only_missing": miss_s}
            summary["g3_failures"] = sum(fail_kinds.values())
        if args.g6:
            # Keys are added only in G6 mode (same shape as the G3 ones, prefix g6_).
            failed_set = set(failed_cases)
            g6_ver = [r for r in verified if r["name"] not in failed_set and g3_counted(r, True, args.inputs, "g6")]
            g6_safe = [r for r in sample if g6_unproved(r) and r["name"] not in failed_set
                       and g3_counted(r, False, args.inputs, "g6")]
            unexpected_rej = [r for r in rejected_all if not g6_unproved(r)]
            feat = {}
            for r in g6_ver:
                for t in (r["case"].get("g6_features") or []):
                    feat[t] = feat.get(t, 0) + 1
            kinds = {}
            for r in g6_ver:
                kinds[r["case"].get("kind")] = kinds.get(r["case"].get("kind"), 0) + 1
            cmp_done, cmp_skipped = g3_comparisons(progs)
            dig_full, dig_quiet = g3_digests(progs)
            ipp = [len(r.get("inputs", [])) for r in progs]
            # run-time `pruv: foreign requires violated:` paths that the oracle expects (vec_get / string_byte out of range),
            # counted per (program, input) in the safe oracle and in the proof oracle of verified programs
            fr_safe = sum(1 for r in progs for o in (r.get("oracle_safe") or []) if o.get("kind") == "foreign_requires")
            fr_proof = sum(1 for r in progs for o in (r.get("oracle_proof") or []) if o.get("kind") == "foreign_requires")
            summary["g6"] = True
            summary["compiler"] = DRIVER.name
            summary["g6_generated"] = counts["candidates"]
            summary["g6_verified"] = len(g6_ver)
            summary["g6_safe_only"] = len(g6_safe)
            summary["g6_executions_compared"] = cmp_done
            summary["g6_executions_not_compared"] = cmp_skipped
            summary["g6_failures"] = sum(fail_kinds.values())
            summary["g6_kinds_verified"] = dict(sorted(kinds.items()))
            summary["g6_features_verified"] = dict(sorted(feat.items()))
            summary["g6_inputs_per_program_min"] = min(ipp) if ipp else 0
            summary["g6_foreign_requires_inputs"] = {"safe_oracle": fr_safe, "proof_oracle": fr_proof}
            summary["g6_unproved_by_design_verified_anyway"] = sum(1 for r in verified if g6_unproved(r))
            summary["g6_unproved_by_design_verified_names"] = [
                (r.get("name"), (r.get("case") or {}).get("g6_mutation") or (r.get("case") or {}).get("kind"))
                for r in verified if g6_unproved(r)]
            summary["g6_unexpected_rejects"] = {
                "count": len(unexpected_rej), "names": [r["name"] for r in unexpected_rej[:20]],
                "codes": sorted(set(c for r in unexpected_rej for c in r.get("codes", [])))}
            summary["g6_digest"] = dig_full
            summary["g6_digest_exit_stdout"] = dig_quiet
            ud = os.path.join(out_dir, "unexpected_rejects")
            for r in unexpected_rej[:10]:
                os.makedirs(ud, exist_ok=True)
                write(os.path.join(ud, r["name"] + ".pruv"), r["src"])
                write(os.path.join(ud, r["name"] + ".txt"), r["logs"].get("verify", ""))
            # the generator must produce well-typed programs and the oracle must be able to run them
            if counts["generator_invalid"]:
                fail_kinds["g6_generator_invalid"] = counts["generator_invalid"]
            if counts["oracle_unsupported"] + counts["oracle_parse_error"]:
                fail_kinds["g6_oracle_gap"] = counts["oracle_unsupported"] + counts["oracle_parse_error"]
            if summary["g6_verified"] < args.programs or summary["g6_safe_only"] < args.g6_safe_only:
                miss_v = max(0, args.programs - summary["g6_verified"])
                miss_s = max(0, args.g6_safe_only - summary["g6_safe_only"])
                fail_kinds["g6_shortfall"] = miss_v + miss_s
                summary["g6_shortfall"] = {"verified_missing": miss_v, "safe_only_missing": miss_s}
            summary["g6_failures"] = sum(fail_kinds.values())
        if args.g9:
            # Keys are added only in G9 mode (same shape as the G6 ones, prefix g9_). A timeout (verifier, build or run) is a
            # failure kind of its own and never counts as a pass: g3_counted() rejects every program with a timed-out run.
            failed_set = set(failed_cases)
            g9_ver = [r for r in verified if r["name"] not in failed_set and g3_counted(r, True, args.inputs, "g9")]
            g9_safe = [r for r in sample if g9_unproved(r) and r["name"] not in failed_set
                       and g3_counted(r, False, args.inputs, "g9")]
            unexpected_rej = [r for r in rejected_all if not g9_unproved(r)]
            feat = {}
            for r in g9_ver:
                for t in (r["case"].get("g9_features") or []):
                    feat[t] = feat.get(t, 0) + 1
            kinds = {}
            for r in g9_ver:
                kinds[r["case"].get("kind")] = kinds.get(r["case"].get("kind"), 0) + 1
            cmp_done, cmp_skipped = g3_comparisons(progs)
            dig_full, dig_quiet = g3_digests(progs)
            ipp = [len(r.get("inputs", [])) for r in progs]
            summary["g9"] = True
            summary["compiler"] = DRIVER.name
            summary["g9_generated"] = counts["candidates"]
            summary["g9_verified"] = len(g9_ver)
            summary["g9_safe_only"] = len(g9_safe)
            summary["g9_executions_compared"] = cmp_done
            summary["g9_executions_not_compared"] = cmp_skipped
            summary["g9_kinds_verified"] = dict(sorted(kinds.items()))
            summary["g9_features_verified"] = dict(sorted(feat.items()))
            summary["g9_inputs_per_program_min"] = min(ipp) if ipp else 0
            # rust-X != llvm-X or proof != safe where the oracle says they agree (mode_mismatch), a run that differs from the
            # oracle (oracle_mismatch), a verified program the oracle's proof mode faults on or whose ensures it violates (unsound)
            summary["g9_mismatches"] = {"backend_or_mode_mismatch": fail_kinds.get("mode_mismatch", 0),
                                        "oracle_mismatch": fail_kinds.get("oracle_mismatch", 0),
                                        "unsound": fail_kinds.get("unsound", 0)}
            summary["g9_timeouts"] = {k: v for k, v in sorted(fail_kinds.items()) if "timeout" in k}
            summary["g9_unproved_by_design_verified_anyway"] = sum(1 for r in verified if g9_unproved(r))
            summary["g9_unproved_by_design_verified_names"] = [
                (r.get("name"), (r.get("case") or {}).get("g9_mutation") or (r.get("case") or {}).get("kind"))
                for r in verified if g9_unproved(r)]
            summary["g9_unexpected_rejects"] = {
                "count": len(unexpected_rej), "names": [r["name"] for r in unexpected_rej[:20]],
                "codes": sorted(set(c for r in unexpected_rej for c in r.get("codes", [])))}
            summary["g9_digest"] = dig_full
            summary["g9_digest_exit_stdout"] = dig_quiet
            ud = os.path.join(out_dir, "unexpected_rejects")
            for r in unexpected_rej[:10]:
                os.makedirs(ud, exist_ok=True)
                write(os.path.join(ud, r["name"] + ".pruv"), r["src"])
                write(os.path.join(ud, r["name"] + ".txt"), r["logs"].get("verify", ""))
            # the generator must produce well-typed programs and the oracle must be able to run them
            if counts["generator_invalid"]:
                fail_kinds["g9_generator_invalid"] = counts["generator_invalid"]
            if counts["oracle_unsupported"] + counts["oracle_parse_error"]:
                fail_kinds["g9_oracle_gap"] = counts["oracle_unsupported"] + counts["oracle_parse_error"]
            if summary["g9_verified"] < args.programs or summary["g9_safe_only"] < args.g9_safe_only:
                miss_v = max(0, args.programs - summary["g9_verified"])
                miss_s = max(0, args.g9_safe_only - summary["g9_safe_only"])
                fail_kinds["g9_shortfall"] = miss_v + miss_s
                summary["g9_shortfall"] = {"verified_missing": miss_v, "safe_only_missing": miss_s}
            summary["g9_failures"] = sum(fail_kinds.values())
        if args.g4:
            # Keys are added only in G4 mode (same shape as the G9 ones, prefix g4_). Every G4 program is meant to verify, so a
            # rejected program is an "unexpected reject" (reported, saved as a program folder, never a pass).
            failed_set = set(failed_cases)
            g4_ver = [r for r in verified if r["name"] not in failed_set and g3_counted(r, True, args.inputs, "g4")]
            unexpected_rej = list(rejected_all)
            feat = {}
            for r in g4_ver:
                for t in (r["case"].get("g4_features") or []):
                    feat[t] = feat.get(t, 0) + 1
            kinds = {}
            for r in g4_ver:
                kinds[r["case"].get("kind")] = kinds.get(r["case"].get("kind"), 0) + 1
            cmp_done, cmp_skipped = g3_comparisons(progs)
            dig_full, dig_quiet = g3_digests(progs)
            ipp = [len(r.get("inputs", [])) for r in progs]
            summary["g4"] = True
            summary["compiler"] = DRIVER.name
            summary["g4_generated"] = counts["candidates"]
            summary["g4_verified"] = len(g4_ver)
            summary["g4_executions_compared"] = cmp_done
            summary["g4_executions_not_compared"] = cmp_skipped
            summary["g4_kinds_verified"] = dict(sorted(kinds.items()))
            summary["g4_features_verified"] = dict(sorted(feat.items()))
            summary["g4_inputs_per_program_min"] = min(ipp) if ipp else 0
            summary["g4_twin_pairs_compared"] = twin_pairs
            # rust-X != llvm-X or proof != safe where the oracle says they agree (mode_mismatch), a run that differs from the
            # oracle (oracle_mismatch), a verified program the oracle's proof mode faults on or whose ensures it violates
            # (unsound), twins (identical but for one contract-preserving callee body) that behave differently (twin_mismatch)
            summary["g4_mismatches"] = {"backend_or_mode_mismatch": fail_kinds.get("mode_mismatch", 0),
                                        "oracle_mismatch": fail_kinds.get("oracle_mismatch", 0),
                                        "unsound": fail_kinds.get("unsound", 0),
                                        "twin_mismatch": fail_kinds.get("twin_mismatch", 0)}
            summary["g4_timeouts"] = {k: v for k, v in sorted(fail_kinds.items()) if "timeout" in k}
            summary["g4_unexpected_rejects"] = {
                "count": len(unexpected_rej), "names": [r["name"] for r in unexpected_rej[:20]],
                "codes": sorted(set(c for r in unexpected_rej for c in r.get("codes", [])))}
            summary["g4_digest"] = dig_full
            summary["g4_digest_exit_stdout"] = dig_quiet
            ud = os.path.join(out_dir, "unexpected_rejects")
            for r in unexpected_rej[:10]:
                os.makedirs(ud, exist_ok=True)
                save_program(ud, r)
                write(os.path.join(ud, r["name"] + ".txt"), r["logs"].get("verify", ""))
            # the generator must produce well-typed programs and the oracle must be able to run them
            if counts["generator_invalid"]:
                fail_kinds["g4_generator_invalid"] = counts["generator_invalid"]
            if counts["oracle_unsupported"] + counts["oracle_parse_error"]:
                fail_kinds["g4_oracle_gap"] = counts["oracle_unsupported"] + counts["oracle_parse_error"]
            if summary["g4_verified"] < args.programs:
                fail_kinds["g4_shortfall"] = args.programs - summary["g4_verified"]
                summary["g4_shortfall"] = {"verified_missing": args.programs - summary["g4_verified"]}
            summary["g4_failures"] = sum(fail_kinds.values())
        g5_detail = None
        if args.g5:
            # Keys are added only in G5 mode (prefix g5_). Every G5 program is meant to verify, so a rejected program is an
            # "unexpected reject" (reported, saved as a program folder). Completed comparisons (g5_comparisons_completed) are
            # counted ONLY on counted verified programs without a recorded failure: oracle gaps, rejected programs, oracle
            # limits/errors, timeouts and harness exceptions never contribute.
            failed_set = set(failed_cases)
            g5_ver = [r for r in verified if r["name"] not in failed_set and g3_counted(r, True, args.inputs, "g5")]
            unexpected_rej = list(rejected_all)
            feat = {}
            per_prog = []
            completed = 0
            for r in g5_ver:
                for t in (r["case"].get("g5_features") or []):
                    feat[t] = feat.get(t, 0) + 1
                done_r, _skip_r = g3_comparisons([r])
                completed += done_r
                per_prog.append({"name": r["name"], "kind": r["case"].get("kind"),
                                 "features": r["case"].get("g5_features", []), "inputs": len(r.get("inputs", [])),
                                 "comparisons_completed": done_r, "twin": r["case"].get("g5_twin"),
                                 "oracle_inout_calls": sum(o.get("inout_calls", 0) for o in (r.get("oracle_proof") or []))})
            kinds = {}
            for r in g5_ver:
                kinds[r["case"].get("kind")] = kinds.get(r["case"].get("kind"), 0) + 1
            cmp_done, cmp_skipped = g3_comparisons(progs)
            dig_full, dig_quiet = g3_digests(progs)
            src_dig = hashlib.sha256()
            for r in sorted(g5_ver, key=lambda x: x["name"]):
                src_dig.update(json.dumps([r["name"], r["case"]["files"]], sort_keys=True).encode())
            ipp = [len(r.get("inputs", [])) for r in progs]
            target = args.programs * args.inputs * len(MODES)
            miss_feat = [t for t in G5_REQUIRED if not feat.get(t)]
            if twin_pairs == 0:
                miss_feat.append("body_replacement_twin")
            inf_ok = [x for x in infer_results if x.get("exit") == 0]
            inf_strip = [x for x in infer_results if x.get("stripped_exit") is not None]
            summary["g5"] = True
            summary["compiler"] = DRIVER.name
            summary["g5_seed"] = args.seed
            summary["g5_generated"] = counts["candidates"]
            summary["g5_verified"] = len(g5_ver)
            summary["g5_executions_compared"] = cmp_done
            summary["g5_executions_not_compared"] = cmp_skipped
            summary["g5_comparisons_completed"] = completed
            summary["g5_comparisons_target"] = target
            summary["g5_kinds_verified"] = dict(sorted(kinds.items()))
            summary["g5_features_verified"] = dict(sorted(feat.items()))
            summary["g5_features_missing"] = miss_feat
            summary["g5_program_features"] = dict((p["name"], p["features"]) for p in per_prog)
            summary["g5_inputs_per_program_min"] = min(ipp) if ipp else 0
            summary["g5_twin_pairs_compared"] = twin_pairs
            summary["g5_mismatches"] = {"backend_or_mode_mismatch": fail_kinds.get("mode_mismatch", 0),
                                        "oracle_mismatch": fail_kinds.get("oracle_mismatch", 0),
                                        "unsound": fail_kinds.get("unsound", 0),
                                        "twin_mismatch": fail_kinds.get("twin_mismatch", 0)}
            summary["g5_timeouts"] = {k: v for k, v in sorted(fail_kinds.items()) if "timeout" in k}
            summary["g5_unexpected_rejects"] = {
                "count": len(unexpected_rej), "names": [r["name"] for r in unexpected_rej[:20]],
                "codes": sorted(set(c for r in unexpected_rej for c in r.get("codes", [])))}
            summary["g5_oracle_gaps"] = counts["oracle_unsupported"] + counts["oracle_parse_error"]
            summary["g5_infer"] = {
                "programs_probed": len(infer_results), "verified_with_infer": len(inf_ok),
                "same_rust_as_explicit": sum(1 for x in inf_ok if x.get("same_rust")),
                "stripped_probed": len(inf_strip),
                "stripped_verified": sum(1 for x in inf_strip if x.get("stripped_exit") == 0),
                "stripped_rejected": sum(1 for x in inf_strip if x.get("stripped_exit") == 1),
                "stripped_rust_differs": [x["name"] for x in inf_strip if x.get("stripped_same_rust") is False],
                "minimum": G5_INFER_MIN}
            summary["g5_program_digest"] = src_dig.hexdigest()
            summary["g5_digest"] = dig_full
            summary["g5_digest_exit_stdout"] = dig_quiet
            ud = os.path.join(out_dir, "unexpected_rejects")
            for r in unexpected_rej[:10]:
                os.makedirs(ud, exist_ok=True)
                save_program(ud, r)
                write(os.path.join(ud, r["name"] + ".txt"), r["logs"].get("verify", ""))
            # the generator must produce well-typed programs and the oracle must be able to run them
            if counts["generator_invalid"]:
                fail_kinds["g5_generator_invalid"] = counts["generator_invalid"]
            if counts["oracle_unsupported"] + counts["oracle_parse_error"]:
                fail_kinds["g5_oracle_gap"] = counts["oracle_unsupported"] + counts["oracle_parse_error"]
            shortfall = {}
            if summary["g5_verified"] < args.programs:
                shortfall["verified_missing"] = args.programs - summary["g5_verified"]
                fail_kinds["g5_shortfall"] = shortfall["verified_missing"]
            if completed < target:
                shortfall["comparisons_missing"] = target - completed
                fail_kinds["g5_comparison_shortfall"] = target - completed
            if len(inf_ok) < G5_INFER_MIN:
                shortfall["infer_programs_missing"] = G5_INFER_MIN - len(inf_ok)
                fail_kinds["g5_infer_shortfall"] = G5_INFER_MIN - len(inf_ok)
            if miss_feat:
                shortfall["features_missing"] = miss_feat
                fail_kinds["g5_feature_shortfall"] = len(miss_feat)
            summary["g5_shortfall"] = shortfall
            summary["g5_failures"] = sum(fail_kinds.values())
            # saved failures + the command that replays each of them
            saved = []
            fdir = os.path.join(out_dir, "failures")
            if os.path.isdir(fdir):
                for nm in sorted(os.listdir(fdir)):
                    p = os.path.join(fdir, nm)
                    saved.append({"dir": p, "replay": "python bench/fuzz/run.py --replay %s --compiler %s" % (p, DRIVER.name)})
            summary["g5_saved_failures"] = saved
            g5_detail = {"seed": args.seed, "compiler": DRIVER.name, "programs_requested": args.programs,
                         "inputs_per_program": args.inputs, "comparisons_completed": completed,
                         "comparisons_target": target, "shortfall": shortfall,
                         "feature_counts": summary["g5_features_verified"], "programs": per_prog,
                         "infer": summary["g5_infer"], "infer_per_program": infer_results,
                         "failures_by_kind": fail_kinds, "saved_failures": saved,
                         "unexpected_rejects": summary["g5_unexpected_rejects"],
                         "replay_commands": [s["replay"] for s in saved]}
        write(os.path.join(out_dir, "summary.json"), json.dumps(summary, indent=2))
        if g5_detail is not None:
            write(os.path.join(out_dir, "g5_results.json"), json.dumps(g5_detail, indent=2, default=str))
        print("---- summary ----")
        print("candidates %d (generator errors %d, oracle unsupported %d) -> pass %d / reject %d %s"
              % (summary["candidates"], summary["generator_invalid"],
                 summary["oracle_unsupported"] + summary["oracle_parse_error"],
                 summary["verified"], summary["rejected"], json.dumps(rej_codes)))
        print("inputs run %d (process executions %d), elapsed %.1fs (generate+verify %.1f, build %.1f, run %.1f)"
              % (inputs_run, summary["executions"], summary["timings_s"]["total"],
                 summary["timings_s"]["generate_verify"], summary["timings_s"]["build"],
                 summary["timings_s"]["run"]))
        print("input outcomes (status/requires/oracle): " + json.dumps(summary["oracle_outcomes"]))
        print("comparisons not completed (oracle limit, neither failure nor pass): %d" % summary["incomplete"])
        print("programs with no input satisfying requires: %d %s"
              % (summary["no_sat_inputs"]["count"], json.dumps(summary["no_sat_inputs"]["names"])))
        if programs_short:
            print("warning: verified programs %d < requested %d (programs_short)"
                  % (summary["verified_used"], args.programs))
        if args.g2:
            print("G2: verified %d (requested %d), rejected safe-mode builds %d (requested %d), min inputs per program %d, programs short of inputs %d, tags %s"
                  % (summary["g2_verified"], args.programs, summary["g2_rejected_built_safe_modes"],
                     args.rejected_sample, summary["g2_inputs_per_program_min"], summary["g2_short_inputs"],
                     json.dumps(summary["g2_features_verified"])))
        if args.g3:
            print("G3 seed %d (%s): generated %d, verified %d (requested %d), safe-only %d (requested %d), "
                  "executions compared %d (not compared %d), failures %d, min inputs per program %d"
                  % (args.seed, summary["compiler"], summary["g3_generated"], summary["g3_verified"], args.programs,
                     summary["g3_safe_only"], args.g3_safe_only, summary["g3_executions_compared"],
                     summary["g3_executions_not_compared"], summary["g3_failures"], summary["g3_inputs_per_program_min"]))
            print("G3 kinds %s" % json.dumps(summary["g3_kinds_verified"]))
            print("G3 features %s" % json.dumps(summary["g3_features_verified"]))
            print("G3 programs meant to verify but rejected: %d %s; meant to be unproved but verified: %d"
                  % (summary["g3_unexpected_rejects"]["count"], json.dumps(summary["g3_unexpected_rejects"]["codes"]),
                     summary["g3_unproved_by_design_verified_anyway"]))
            print("G3 digest %s (exit+stdout only %s)" % (summary["g3_digest"][:16], summary["g3_digest_exit_stdout"][:16]))
        if args.g6:
            print("G6 seed %d (%s): generated %d, verified %d (requested %d), safe-only %d (requested %d), "
                  "executions compared %d (not compared %d), failures %d, min inputs per program %d"
                  % (args.seed, summary["compiler"], summary["g6_generated"], summary["g6_verified"], args.programs,
                     summary["g6_safe_only"], args.g6_safe_only, summary["g6_executions_compared"],
                     summary["g6_executions_not_compared"], summary["g6_failures"], summary["g6_inputs_per_program_min"]))
            print("G6 kinds %s" % json.dumps(summary["g6_kinds_verified"]))
            print("G6 features %s" % json.dumps(summary["g6_features_verified"]))
            print("G6 foreign-requires runtime failures expected by the oracle: %s"
                  % json.dumps(summary["g6_foreign_requires_inputs"]))
            print("G6 programs meant to verify but rejected: %d %s; meant to be unproved but verified: %d"
                  % (summary["g6_unexpected_rejects"]["count"], json.dumps(summary["g6_unexpected_rejects"]["codes"]),
                     summary["g6_unproved_by_design_verified_anyway"]))
            print("G6 digest %s (exit+stdout only %s)" % (summary["g6_digest"][:16], summary["g6_digest_exit_stdout"][:16]))
        if args.g9:
            print("G9 seed %d (%s): generated %d, verified %d (requested %d), safe-only %d (requested %d), "
                  "executions compared %d (not compared %d), failures %d, min inputs per program %d"
                  % (args.seed, summary["compiler"], summary["g9_generated"], summary["g9_verified"], args.programs,
                     summary["g9_safe_only"], args.g9_safe_only, summary["g9_executions_compared"],
                     summary["g9_executions_not_compared"], summary["g9_failures"], summary["g9_inputs_per_program_min"]))
            print("G9 kinds %s" % json.dumps(summary["g9_kinds_verified"]))
            print("G9 features %s" % json.dumps(summary["g9_features_verified"]))
            print("G9 mismatches %s, timeouts %s" % (json.dumps(summary["g9_mismatches"]), json.dumps(summary["g9_timeouts"])))
            print("G9 programs meant to verify but rejected: %d %s; meant to be unproved but verified: %d"
                  % (summary["g9_unexpected_rejects"]["count"], json.dumps(summary["g9_unexpected_rejects"]["codes"]),
                     summary["g9_unproved_by_design_verified_anyway"]))
            print("G9 digest %s (exit+stdout only %s)" % (summary["g9_digest"][:16], summary["g9_digest_exit_stdout"][:16]))
        if args.g4:
            print("G4 seed %d (%s): generated %d, verified %d (requested %d), "
                  "executions compared %d (not compared %d), failures %d, min inputs per program %d"
                  % (args.seed, summary["compiler"], summary["g4_generated"], summary["g4_verified"], args.programs,
                     summary["g4_executions_compared"], summary["g4_executions_not_compared"], summary["g4_failures"],
                     summary["g4_inputs_per_program_min"]))
            print("G4 kinds %s" % json.dumps(summary["g4_kinds_verified"]))
            print("G4 features %s" % json.dumps(summary["g4_features_verified"]))
            print("G4 mismatches %s, twin pairs compared %d, timeouts %s"
                  % (json.dumps(summary["g4_mismatches"]), summary["g4_twin_pairs_compared"],
                     json.dumps(summary["g4_timeouts"])))
            print("G4 programs meant to verify but rejected: %d %s"
                  % (summary["g4_unexpected_rejects"]["count"], json.dumps(summary["g4_unexpected_rejects"]["codes"])))
            print("G4 digest %s (exit+stdout only %s)" % (summary["g4_digest"][:16], summary["g4_digest_exit_stdout"][:16]))
        if args.g5:
            print("G5 seed %d (%s): generated %d, verified %d (requested %d), comparisons completed %d (target %d; "
                  "executions compared %d, not compared %d), failures %d, min inputs per program %d"
                  % (args.seed, summary["compiler"], summary["g5_generated"], summary["g5_verified"], args.programs,
                     summary["g5_comparisons_completed"], summary["g5_comparisons_target"],
                     summary["g5_executions_compared"], summary["g5_executions_not_compared"], summary["g5_failures"],
                     summary["g5_inputs_per_program_min"]))
            print("G5 kinds %s" % json.dumps(summary["g5_kinds_verified"]))
            print("G5 features %s (missing %s)" % (json.dumps(summary["g5_features_verified"]),
                                                   json.dumps(summary["g5_features_missing"])))
            print("G5 mismatches %s, twin pairs compared %d, timeouts %s"
                  % (json.dumps(summary["g5_mismatches"]), summary["g5_twin_pairs_compared"],
                     json.dumps(summary["g5_timeouts"])))
            print("G5 infer %s" % json.dumps(dict((k, v) for k, v in summary["g5_infer"].items()
                                                  if k != "stripped_rust_differs")))
            if summary["g5_infer"]["stripped_rust_differs"]:
                print("G5 infer: invariant-free copies whose Rust differs from the explicit program: %s"
                      % json.dumps(summary["g5_infer"]["stripped_rust_differs"]))
            print("G5 programs meant to verify but rejected: %d %s; oracle gaps: %d"
                  % (summary["g5_unexpected_rejects"]["count"], json.dumps(summary["g5_unexpected_rejects"]["codes"]),
                     summary["g5_oracle_gaps"]))
            print("G5 shortfall %s" % json.dumps(summary["g5_shortfall"]))
            for s in summary["g5_saved_failures"][:20]:
                print("G5 replay: " + s["replay"])
            print("G5 digest %s (exit+stdout only %s), program digest %s"
                  % (summary["g5_digest"][:16], summary["g5_digest_exit_stdout"][:16], summary["g5_program_digest"][:16]))
        if args.g7:
            print("G7 comparisons %d/%d, repeats %d, mismatches %s, oracle gaps %d"
                  % (summary["g7_comparisons_completed"], summary["g7_comparisons_target"],
                     summary["g7_repeats"], json.dumps(summary["g7_mismatches"]), summary["g7_oracle_gaps"]))
        print("failures: %s" % (json.dumps(fail_kinds) if fail_kinds else "none"))
        print("results: " + out_dir)
        return 1 if fail_kinds else 0
    finally:
        if args.keep_work:
            print("work folder: " + work)
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
        rec["failures"] = []  # prevent duplicate saving


if __name__ == "__main__":
    sys.exit(main())
