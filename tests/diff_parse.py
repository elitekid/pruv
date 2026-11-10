#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Python 정본 파서와 Rust pruv-parse-dump 의 parse 결과를 바이트 단위로 비교한다.

  python tests/diff_parse.py [--mode parse|check] [--rs-path PATH] [--seeds 41,56,57]
                             [--fuzz-count 200] [--mutations 6] [--save-dir DIR]
                             [--only GROUP[,GROUP...]]

그룹: must_reject examples runtime bench edge bytes fuzz mutate
--mode parse(기본): 기대 줄 = diff_py_adapter.dumps(parse_result(FILE)), Rust = pruv-parse-dump,
  edge = tests/parse_edge.
--mode check: 기대 줄 = diff_py_adapter.dumps(check_result(FILE)), Rust = pruv-check-dump,
  edge = tests/check_edge (mutate 원본에도 들어간다), coverage 는 check 용(45개 오류 code 등).
기대 줄 = diff_py_adapter.dumps(parse_result(FILE)) (같은 프로세스에서 직접 부른다).
  UnicodeDecodeError -> {"adapter_error": "decode"}, RecursionError -> 비교 제외(py_recursion),
  그 밖의 예외 -> py_crash(실패).
Rust: 파일 200개씩 `pruv-parse-dump FILE...` 한 번(셸 없음, timeout 300). 줄 수 불일치·종료 코드≠0·
  시간 초과·마지막 줄 개행 없음이면 그 묶음 전체가 rs_crash.
종료 코드: 0 = 모두 same 이고 coverage 통과, 1 = 그 외, 2 = 인자/바이너리 없음.
Python 3.9 표준 라이브러리만 쓴다.
"""
import argparse
import collections
import glob
import json
import locale
import os
import random
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import diff_py_adapter as A  # noqa: E402  (모듈 import 때 ../pruvc 가 sys.path 에 들어간다)

BATCH = 200
RS_TIMEOUT = 300
MAX_SHOWN = 10
CONTEXT = 60
REQUIRED_CODES = ("bad_char", "bad_int", "reserved_name", "unsupported_type", "syntax")
QUANT_KINDS = ("forall", "exists", "sum", "count", "max", "min")   # 직렬화에서 Quant 의 kind 가 이 값으로 덮인다

GROUP_DIRS = [
    ("must_reject", "tests/must_reject"),
    ("examples", "examples"),
    ("runtime", "tests/runtime"),
    ("bench", "bench/solutions/pruv_agg"),
    ("edge", "tests/parse_edge"),
]
CHECK_EDGE_DIR = "tests/check_edge"
PARSE_EDGE_DIR = "tests/parse_edge"
ALL_GROUPS = [g for g, _ in GROUP_DIRS] + ["bytes", "fuzz", "mutate"]
CHECK_CODES = (
    "arity array_alias call_in_contract contract_only dup_field dup_fn dup_param dup_type dup_variant "
    "effect_in_contract empty_enum eq_type field_name field_type immutable int_range match_arity "
    "match_arms match_type missing_effect missing_return name_collision not_array not_enum not_struct "
    "print_type recursion recursive_type reserved result_scope return_type shadow struct_fields "
    "type_mismatch type_name unit_let unit_param unknown_field unknown_fn unknown_name unknown_type "
    "unknown_variant unused_value useless_expr variant_name").split()
CHECK_TY_BUILTIN = ("i64", "bool", "unit", "array", "option", "result")


def group_dirs(mode):
    if mode == "check":
        return [(g, CHECK_EDGE_DIR if g == "edge" else d) for g, d in GROUP_DIRS]
    return GROUP_DIRS
STATUSES = ("same", "diff", "py_recursion", "py_crash", "rs_crash")

# ---------------------------------------------------------------------------
# mutate 조각 (순서 고정: 결정성)
# ---------------------------------------------------------------------------
FRAGMENTS = [
    "-", "--", "_", "1_", "9223372036854775808", "99999999999999999999999999999999",
    "(", ")", "{", "}", ";", ",", "::", "..", "==>", "=>", "->", "!", "&", "|", "#", "\"", "'",
    "é", "한", "😀", "​", "\t", "\n", "\x0c", "\x00",
    "fn", "let", "match", "struct", "enum", "pruv_x", "a__b", "type", "_", "Some(", "None",
    "Foo::", "is_variant(", "sum(", "forall",
]

# ---------------------------------------------------------------------------
# 바이트 경계 입력 (이름, bytes)
# ---------------------------------------------------------------------------
OK_FN = b"fn f() -> i64 {\n  return 1;\n}\n"


def _u(s):
    return s.encode("utf-8")


# Python repr(%r) 의 출력 가능/이스케이프 판정과 유니코드 버전 차이를 건드리는 문자들
REPR_CODEPOINTS = [
    0x01, 0x1f, 0x7f, 0x80, 0x85, 0x9f, 0xa0, 0xad, 0xff, 0x100, 0x301, 0x378, 0x600, 0x61c,
    0x1680, 0x180e, 0x2000, 0x200b, 0x200e, 0x2028, 0x2029, 0x202f, 0x2060, 0x2065, 0x20bf,
    0x2e5d, 0x2ffc, 0x3000, 0x3040, 0x4e00, 0xac00, 0xd7a3, 0xd7a4, 0xe000, 0xf8ff, 0xfdd0,
    0xfeff, 0xfff9, 0xfffc, 0xfffd, 0xfffe, 0xffff, 0x10000, 0x1c89, 0x1d173, 0x1e4d0, 0x1f1e6,
    0x1f600, 0x1fa89, 0x1fae8, 0x20000, 0x2ebf0, 0x31350, 0xe0001, 0xe0020, 0xe0100, 0xf0000,
    0x10fffd, 0x10ffff,
]


def _build_byte_cases():
    cases = [
        # 줄끝: open().read() 의 universal newlines 가 \r\n, \r 을 \n 으로 바꾼다
        ("crlf_ok", b"fn f() -> i64 {\r\n  return 1;\r\n}\r\n"),
        ("cr_only_ok", b"fn f() -> i64 {\r  return 1;\r}\r"),
        ("crlf_error_line2", b"fn f() -> i64 {\r\n  return 1 $;\r\n}\r\n"),
        ("cr_only_error_line2", b"fn f() -> i64 {\r  return 1 $;\r}\r"),
        ("mixed_eol_error", b"fn f() -> i64 {\n\r\n\r  return 1\r\n  $\n}\n"),
        ("cr_cr_lf_error", b"fn f() -> i64 {\r\r\n  return 1 $;\n}\n"),
        ("crlf_after_comment", b"// a\r\nfn f() -> i64 { return 1 $; }\r\n"),
        ("cr_after_comment_eof", b"// c\r"),
        ("crlf_only", b"\r\n\r\n"),
        # BOM
        ("bom_start", b"\xef\xbb\xbf" + OK_FN),
        ("bom_middle", OK_FN + b"\xef\xbb\xbf" + OK_FN),
        ("bom_only", b"\xef\xbb\xbf"),
        # 잘못된 UTF-8 -> {"adapter_error": "decode"}
        ("invalid_utf8_ff", OK_FN + b"\xff\n"),
        ("invalid_utf8_continuation", b"// \x80\n" + OK_FN),
        ("invalid_utf8_truncated", b"// \xe2\x82\n" + OK_FN),
        ("invalid_utf8_overlong", b"fn f() -> i64 { return 1; } \xc0\xaf\n"),
        ("invalid_utf8_surrogate", b"// \xed\xa0\x80\n" + OK_FN),
        ("invalid_utf8_above_max", b"\xf4\x90\x80\x80"),
        ("invalid_utf8_at_eof", OK_FN + b"\xe2\x82"),
        # 제어 문자
        ("nul_middle", b"fn f() -> i64 {\x00  return 1;\n}\n"),
        ("nul_in_comment", b"// a\x00b\n" + OK_FN),
        ("nul_at_eof", OK_FN + b"\x00"),
        ("vt_0b", b"fn f() -> i64 {\x0b return 1; }\n"),
        ("ff_0c", b"fn f() -> i64 {\x0c return 1; }\n"),
        ("vt_ff_in_comment", b"// a\x0bb\x0cc\n" + OK_FN),
        ("ctrl_01", b"fn f() -> i64 { return 1\x01; }\n"),
        ("del_7f", b"fn f() -> i64 { return 1\x7f; }\n"),
        ("nbsp", _u("fn f() -> i64 { return 1; }\n")),
        ("ideographic_space", _u("fn f() -> i64 { return　1; }\n")),
        ("fullwidth_digit", _u("fn f() -> i64 { return １; }\n")),
        ("u2028_in_comment", _u("// a b $\nfn f() -> i64 { return 1 $; }\n")),
        # 탭
        ("tab_then_error", b"fn f() -> i64 {\n\t\treturn 1 $;\n}\n"),
        ("tab_mixed_syntax_error", b"fn f() -> i64 {\n\t  \treturn 1 2;\n}\n"),
        ("tab_in_comment", b"// a\tb\t\nfn f() -> i64 { return 1 2; }\n"),
        # 비ASCII 주석과 열 번호 (주석은 줄 끝까지라 같은 줄 오류는 파일 끝(eof)뿐이다)
        ("comment_hangul_next_line_error", _u("// 한글 주석\nfn f() -> i64 { return 1 $; }\n")),
        ("comment_emoji_next_line_error", _u("// 😀😀 emoji\nfn f() -> i64 { return 1 $; }\n")),
        ("comment_combining_next_line_error", _u("// éé\nfn f() -> i64 { return 1 $; }\n")),
        ("comment_hangul_eof_unclosed", _u("fn f() -> i64 { // 한글")),
        ("comment_emoji_eof_unclosed", _u("fn f() -> i64 { // 😀😀😀")),
        ("comment_combining_eof_unclosed", _u("fn f() -> i64 { // éé")),
        ("hangul_badchar_after_ascii", _u("fn f() -> i64 { return 한; }\n")),
        ("emoji_badchar_after_hangul_line", _u("// 한글한글\nfn f() -> i64 { return 😀; }\n")),
        ("combining_badchar", _u("fn f() -> i64 { return 1́; }\n")),
        ("hangul_comment_then_trailing_error", _u("fn f() -> i64 { return 1; } // 한글\n$\n")),
        # 빈 입력과 끝 처리
        ("empty", b""),
        ("whitespace_only", b"   \n\t\n  "),
        ("only_newlines", b"\n\n\n"),
        ("comment_only_no_eol", b"// only a comment"),
        ("comment_only_eol", b"// c\n"),
        ("single_slash", b"/"),
        # 아주 긴 줄
        ("long_line_error_10k", b"fn f() -> i64 { return 1;" + b" " * 10000 + b"$ }\n"),
        ("long_comment_then_error", b"// " + b"x" * 10000 + b"\nfn f() -> i64 { return 1 $; }\n"),
        ("long_hangul_comment_then_error", _u("// " + "한" * 10000 + "\n$\n")),
        ("long_ident_100", b"fn " + b"a" * 100 + b"() -> i64 { return 1; }\n"),
        ("int_100_digits", b"fn f() -> i64 { return " + b"9" * 100 + b"; }\n"),
        # 깊은 중첩 (정본이 RecursionError 면 py_recursion 으로 센다)
        ("paren_nest_2000", b"fn f() -> i64 { return " + b"(" * 2000 + b"1" + b")" * 2000 + b"; }\n"),
        ("paren_nest_60", b"fn f() -> i64 { return " + b"(" * 60 + b"1" + b")" * 60 + b"; }\n"),
        ("unary_minus_3000_int", b"fn f() -> i64 { return " + b"-" * 3000 + b"5; }\n"),
        ("unary_minus_200_int", b"fn f() -> i64 { return " + b"-" * 200 + b"5; }\n"),
        ("unary_minus_201_int", b"fn f() -> i64 { return " + b"-" * 201 + b"5; }\n"),
        ("unary_bang_300_var", b"fn f() -> bool { return " + b"!" * 300 + b"x; }\n"),
        ("binary_chain_300", b"fn f() -> i64 { return 1" + b" + 1" * 300 + b"; }\n"),
        ("if_nest_100", b"fn f() -> () {\n" + b"if true {\n" * 100 + b"}\n" * 100 + b"}\n"),
        ("else_if_chain_100", b"fn f() -> () {\nif true { }" + b" else if true { }" * 100 + b"\n}\n"),
    ]
    for cp in REPR_CODEPOINTS:
        cases.append(("badchar_U%04X" % cp, _u("fn f() -> i64 { return 1 %s; }\n" % chr(cp))))
    return cases


BYTE_CASES = _build_byte_cases()


# ---------------------------------------------------------------------------
# 입력 모으기
# ---------------------------------------------------------------------------
class Case(object):
    __slots__ = ("group", "name", "path", "py", "rs", "status", "note")

    def __init__(self, group, name, path):
        self.group, self.name, self.path = group, name, path
        self.py = None      # 기대 줄(bytes, 개행 없음)
        self.rs = None      # Rust 줄(bytes, 개행 없음)
        self.status = None  # None(미판정) 또는 STATUSES 중 하나
        self.note = ""


def rel(path):
    return os.path.relpath(path, ROOT).replace(os.sep, "/")


def list_dir(sub):
    return sorted(glob.glob(os.path.join(ROOT, *sub.split("/")) + os.sep + "*.pruv"))


def safe(name):
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", name)[:80]


def mutate_text(text, rng):
    """한 번의 변형. rng 사용 순서가 고정이라 결정적이다."""
    n = len(text)
    op = rng.randrange(4)
    if op == 0 and n:                       # 임의 위치 문자 1~3개 삭제
        cnt = rng.randint(1, 3)
        pos = rng.randrange(n)
        return text[:pos] + text[pos + cnt:]
    if op == 2 and n >= 2:                  # 두 토막 맞바꾸기
        a, b, c = sorted(rng.randint(0, n) for _ in range(3))
        return text[:a] + text[b:c] + text[a:b] + text[c:]
    if op == 3 and n:                       # 임의 위치에서 자르기
        return text[:rng.randrange(n)]
    pos = rng.randint(0, n)                 # 조각 삽입 (op==1, 그리고 위 분기가 못 쓰는 경우)
    return text[:pos] + rng.choice(FRAGMENTS) + text[pos:]


def parse_seed(tok):
    return int(tok) if re.fullmatch(r"-?[0-9]+", tok) else tok


def build_cases(selected, args, tmp):
    """-> (그룹별 Case 목록 dict, 보고용 부가 정보 list)"""
    notes = []
    base = []   # (rel, path) 변형 원본: must_reject·examples·runtime·bench·edge
    per_group = collections.OrderedDict((g, []) for g in ALL_GROUPS)
    for g, sub in group_dirs(args.mode):
        files = list_dir(sub)
        if not files:
            notes.append("경고: %s 에 *.pruv 가 없다(%s)" % (g, sub))
        for p in files:
            base.append((rel(p), p))
            if g in selected:
                per_group[g].append(Case(g, rel(p), p))
    if args.mode == "check":   # check 모드의 mutate 원본에는 parse 경계 입력도 더한다
        for p in list_dir(PARSE_EDGE_DIR):
            base.append((rel(p), p))
    if "bytes" in selected:
        d = os.path.join(tmp, "bytes")
        os.makedirs(d)
        for i, (name, data) in enumerate(BYTE_CASES):
            p = os.path.join(d, "%03d_%s.pruv" % (i, safe(name)))
            with open(p, "wb") as fh:
                fh.write(data)
            per_group["bytes"].append(Case("bytes", name, p))
    if "fuzz" in selected:
        d = os.path.join(tmp, "fuzz")
        os.makedirs(d)
        sys.path.insert(0, os.path.join(ROOT, "bench", "fuzz"))
        try:
            import generate
        except Exception as e:   # noqa: BLE001
            print("오류: 퍼저 생성기를 불러오지 못했다: %s: %s" % (type(e).__name__, e), file=sys.stderr)
            raise SystemExit(2)
        skipped = 0
        for seed in args.seeds:
            for idx in range(args.fuzz_count):
                try:
                    src = generate.generate_case(seed, idx)["src"]
                    data = src.encode("utf-8")
                except Exception:   # noqa: BLE001  생성기 예외는 건너뛰고 수를 센다
                    skipped += 1
                    continue
                p = os.path.join(d, "s%s_%05d.pruv" % (safe(str(seed)), idx))
                with open(p, "wb") as fh:
                    fh.write(data)
                per_group["fuzz"].append(Case("fuzz", "fuzz:%s:%d" % (seed, idx), p))
        notes.append("fuzz: 생성기 예외로 건너뛴 index %d개 (seeds=%s, count=%d)" % (
            skipped, ",".join(str(s) for s in args.seeds), args.fuzz_count))
    if "mutate" in selected:
        d = os.path.join(tmp, "mutate")
        os.makedirs(d)
        n = 0
        for r, p in base:
            with open(p, "rb") as fh:
                text = fh.read().decode("utf-8", "replace")
            for k in range(args.mutations):
                rng = random.Random("%s:%s:%d" % ("mut", r, k))
                out = mutate_text(text, rng)
                q = os.path.join(d, "m%05d.pruv" % n)
                n += 1
                with open(q, "wb") as fh:
                    fh.write(out.encode("utf-8"))
                per_group["mutate"].append(Case("mutate", "%s#%d" % (r, k), q))
    return per_group, notes


# ---------------------------------------------------------------------------
# 평가
# ---------------------------------------------------------------------------
def eval_python(case, fn=None):
    fn = fn or A.parse_result
    try:
        case.py = A.dumps(fn(case.path)).encode("utf-8")
    except UnicodeDecodeError:
        case.py = A.dumps({"adapter_error": "decode"}).encode("utf-8")
    except RecursionError:
        case.status = "py_recursion"
    except OSError:
        case.py = A.dumps({"adapter_error": "io"}).encode("utf-8")
    except Exception as e:   # noqa: BLE001
        case.status = "py_crash"
        case.note = "%s: %s" % (type(e).__name__, str(e)[:200])


def run_batch(rs, paths):
    """-> (줄 목록 | None, 오류 문장 | None)"""
    try:
        p = subprocess.run([rs] + paths, capture_output=True, timeout=RS_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "시간 초과(%d초)" % RS_TIMEOUT
    except OSError as e:
        return None, "실행 실패: %s" % e
    tail = p.stderr.decode("utf-8", "replace")[-300:].strip()
    if p.returncode != 0:
        return None, "종료 코드 %d: %s" % (p.returncode, tail)
    out = p.stdout
    if out and not out.endswith(b"\n"):
        return None, "마지막 줄에 개행이 없다"
    lines = out.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    if len(lines) != len(paths):
        return None, "줄 수 %d != 파일 수 %d %s" % (len(lines), len(paths), tail)
    return lines, None


def eval_rust(rs, cases, problems):
    todo = [c for c in cases if c.status is None]
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        lines, err = run_batch(rs, [c.path for c in chunk])
        if err is not None:
            for c in chunk:
                c.status, c.note = "rs_crash", err
            problems.append("%s: 묶음 %d (%d개, 첫 파일 %s): %s" % (
                chunk[0].group, i // BATCH, len(chunk), chunk[0].name, err))
            continue
        for c, line in zip(chunk, lines):
            c.rs = line
            c.status = "same" if line == c.py else "diff"


def first_diff(a, b):
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def diff_detail(case):
    a = case.py.decode("utf-8", "replace")
    b = case.rs.decode("utf-8", "replace")
    i = first_diff(a, b)
    lo, hi = max(0, i - CONTEXT), i + CONTEXT
    return i, a[lo:hi], b[lo:hi], len(a), len(b)


# ---------------------------------------------------------------------------
# 저장
# ---------------------------------------------------------------------------
def write_bytes(path, data):
    with open(path, "wb") as fh:
        fh.write(data)


def save_case(save_dir, seq, case):
    d = os.path.join(save_dir, case.group, "%04d_%s" % (seq, safe(case.name)))
    os.makedirs(d, exist_ok=True)
    with open(case.path, "rb") as fh:
        write_bytes(os.path.join(d, "input.pruv"), fh.read())
    info = ["group: %s" % case.group, "name: %s" % case.name, "status: %s" % case.status]
    if case.py is not None:
        write_bytes(os.path.join(d, "py.json"), case.py + b"\n")
    if case.rs is not None:
        write_bytes(os.path.join(d, "rs.json"), case.rs + b"\n")
    if case.status == "diff":
        i, a, b, la, lb = diff_detail(case)
        info += ["first differing char index: %d (py len %d, rs len %d)" % (i, la, lb),
                 "py: " + a, "rs: " + b]
    if case.note:
        info.append("note: " + case.note)
    write_bytes(os.path.join(d, "diff.txt"), ("\n".join(info) + "\n").encode("utf-8"))


# ---------------------------------------------------------------------------
# coverage
# ---------------------------------------------------------------------------
def collect_kinds(obj, kinds, intlits, unary_ops):
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            k = o.get("kind")
            if isinstance(k, str):
                if k in QUANT_KINDS and "lo" in o and "hi" in o:
                    k = "Quant"
                kinds.add(k)
                if k == "IntLit":
                    intlits.add(o.get("value"))
                elif k == "Unary":
                    unary_ops.add(o.get("op"))
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)


def message_head(msg):
    head = re.split(r"['\"]", msg, 1)[0].strip()
    return head or "<따옴표로 시작>"


def coverage(all_cases, enforce):
    expected = set(A.NODE_FIELDS)
    kinds, codes, heads = set(), collections.Counter(), collections.Counter()
    edge_ints, fold_ok = set(), None
    for c in all_cases:
        if c.py is None or c.status in ("py_recursion", "py_crash"):
            continue
        try:
            obj = json.loads(c.py.decode("utf-8"))
        except (ValueError, RecursionError):
            continue
        if "adapter_error" in obj:
            continue
        ints, unary_ops = set(), set()
        collect_kinds(obj, kinds, ints, unary_ops)
        err = obj.get("error")
        if err:
            codes[err.get("code")] += 1
            heads[(err.get("code"), message_head(err.get("message", "")))] += 1
        if c.group == "edge":
            edge_ints |= ints
            if c.name.endswith("/int_double_neg.pruv"):
                fold_ok = ("5" in ints) and ("-" not in unary_ops)
    missing_kinds = sorted(expected - kinds)
    missing_codes = [x for x in REQUIRED_CODES if x not in codes]
    print("")
    print("== 대응 범위(coverage) ==")
    print("노드 kind: %d/%d 종 나옴" % (len(expected & kinds), len(expected)))
    print("  안 나온 kind: %s" % (", ".join(missing_kinds) if missing_kinds else "없음"))
    extra = sorted(kinds - expected)
    if extra:
        print("  vast 33 노드 밖의 kind 값: %s" % ", ".join(extra))
    print("parse 오류 code: %s" % (", ".join("%s=%d" % kv for kv in sorted(codes.items())) or "없음"))
    print("  빠진 필수 code: %s" % (", ".join(missing_codes) if missing_codes else "없음"))
    print("오류 message 앞머리 형태: %d종" % len(heads))
    for (code, head), n in sorted(heads.items(), key=lambda kv: (-kv[1], kv[0])):
        print("  %-18s %-48s %d" % (code, head, n))
    print("edge 묶음 IntLit 확인:")

    def big(v, neg):
        return v is not None and v.startswith("-") == neg and len(v.lstrip("-")) > 20
    checks = [
        ("9223372036854775807", "9223372036854775807" in edge_ints),
        ("-9223372036854775808", "-9223372036854775808" in edge_ints),
        ("20자리 넘는 큰 수", any(big(v, False) for v in edge_ints)),
        ("음수 큰 수", any(big(v, True) for v in edge_ints)),
        ("'--' 접기(int_double_neg.pruv: IntLit 5, Unary - 없음)", bool(fold_ok)),
    ]
    for label, ok in checks:
        print("  %-52s %s" % (label, "있음" if ok else "없음"))
    ok = not missing_kinds and not missing_codes
    if not enforce:
        print("coverage 판정: --only 로 일부 그룹만 돌려 판정에서 제외(참고용)")
        return True
    print("coverage 판정: %s" % ("통과" if ok else "실패"))
    return ok


# ---------------------------------------------------------------------------
def collect_ty(obj, tys):
    """식 노드의 ty 값(문자열)을 모은다"""
    stack = [obj]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            if isinstance(o.get("kind"), str) and isinstance(o.get("ty"), str):
                tys.add(o["ty"])
            stack.extend(o.values())
        elif isinstance(o, list):
            stack.extend(o)


def coverage_check(all_cases, enforce):
    tys, codes, stages = set(), collections.Counter(), collections.Counter()
    ok_n = tt_n = tt2_n = adapter_n = 0
    crash = collections.Counter()
    for c in all_cases:
        if c.status == "py_crash":
            crash[c.note[:160]] += 1
            continue
        if c.py is None or c.status == "py_recursion":
            continue
        try:
            obj = json.loads(c.py.decode("utf-8"))
        except (ValueError, RecursionError):
            continue
        if "adapter_error" in obj:
            adapter_n += 1
            continue
        err = obj.get("error")
        if err:
            codes[err.get("code")] += 1
            stages[err.get("stage")] += 1
            continue
        ok_n += 1
        collect_ty(obj.get("program"), tys)
        tt = obj.get("type_table")
        if tt is not None:
            tt_n += 1
            if len(tt.get("entries", [])) >= 2:
                tt2_n += 1
    user_tys = sorted(t for t in tys if t not in CHECK_TY_BUILTIN)
    ty_missing = [t for t in CHECK_TY_BUILTIN if t not in tys]
    if not user_tys:
        ty_missing.append("사용자 타입")
    missing_codes = [x for x in CHECK_CODES if x not in codes]
    print("")
    print("== 대응 범위(coverage, check) ==")
    print("성공 결과 %d개 (type_table 있음 %d, entries 2개 이상 %d), 해독/읽기 실패 %d개" % (
        ok_n, tt_n, tt2_n, adapter_n))
    print("ty 값 종류: %s" % (", ".join(sorted(tys)) or "없음"))
    print("  내장 ty %d/%d, 사용자 타입 %d종(%s)" % (
        len([t for t in CHECK_TY_BUILTIN if t in tys]), len(CHECK_TY_BUILTIN), len(user_tys),
        ", ".join(user_tys[:8])))
    print("  안 나온 ty 종류: %s" % (", ".join(ty_missing) if ty_missing else "없음"))
    print("오류 code %d종, 오류 %d건: %s" % (
        len(codes), sum(codes.values()), ", ".join("%s=%d" % kv for kv in sorted(codes.items())) or "없음"))
    print("오류 stage: type=%d effect=%d 그 밖=%d" % (
        stages["type"], stages["effect"],
        sum(v for k, v in stages.items() if k not in ("type", "effect"))))
    extra = sorted(set(codes) - set(CHECK_CODES))
    if extra:
        print("  기대 45개 밖의 code: %s" % ", ".join(str(x) for x in extra))
    print("  빠진 필수 code(%d/%d 중): %s" % (
        len(missing_codes), len(CHECK_CODES), ", ".join(missing_codes) if missing_codes else "없음"))
    ncrash = sum(crash.values())
    print("py_crash(RecursionError 제외): %d건" % ncrash)
    for note, n in crash.most_common(10):
        print("  %4d  %s" % (n, note))
    ok = not missing_codes
    if not enforce:
        print("coverage 판정: --only 로 일부 그룹만 돌려 판정에서 제외(참고용)")
        return True
    print("coverage 판정: %s" % ("통과" if ok else "실패"))
    return ok


def default_rs_path(mode="parse"):
    name = "pruv-check-dump" if mode == "check" else "pruv-parse-dump"
    base = os.path.join(ROOT, "pruvc-rs", "target", "release", name)
    if not os.path.isfile(base) and os.path.isfile(base + ".exe"):
        return base + ".exe"
    return base


def main(argv):
    ap = argparse.ArgumentParser(prog="diff_parse.py", description="Python/Rust parse 결과 바이트 비교")
    ap.add_argument("--mode", choices=("parse", "check"), default="parse",
                    help="parse(기본): pruv-parse-dump 와 비교, check: pruv-check-dump 와 비교")
    ap.add_argument("--rs-path", default=None, help="Rust 바이너리 경로(mode 에 따라 pruv-parse-dump / pruv-check-dump)")
    ap.add_argument("--seeds", default="41,56,57", help="퍼저 seed 목록(쉼표)")
    ap.add_argument("--fuzz-count", type=int, default=200, help="seed 마다 index 수")
    ap.add_argument("--mutations", type=int, default=6, help="파일마다 변형 수")
    ap.add_argument("--save-dir", default=None, help="다른 사례를 저장할 폴더")
    ap.add_argument("--only", default=None, help="한 그룹 또는 쉼표 목록: " + " ".join(ALL_GROUPS))
    args = ap.parse_args(argv)

    args.seeds = [parse_seed(t) for t in args.seeds.split(",") if t.strip() != ""]
    if args.fuzz_count < 0 or args.mutations < 0:
        ap.error("--fuzz-count, --mutations 는 0 이상이어야 한다")
    if args.only is None:
        selected = list(ALL_GROUPS)
    else:
        selected = [t.strip() for t in args.only.split(",") if t.strip()]
        bad = [t for t in selected if t not in ALL_GROUPS]
        if bad or not selected:
            ap.error("--only: 알 수 없는 그룹 %s (가능: %s)" % (bad, " ".join(ALL_GROUPS)))
    rs = os.path.abspath(args.rs_path) if args.rs_path else default_rs_path(args.mode)
    if not os.path.isfile(rs) or not os.access(rs, os.X_OK):
        print("오류: Rust 바이너리를 찾을 수 없거나 실행할 수 없다: %s\n"
              "  먼저 빌드하거나 --rs-path 로 pruv-%s-dump 경로를 준다." % (rs, args.mode), file=sys.stderr)
        return 2
    enc = (locale.getpreferredencoding(False) or "").lower().replace("-", "").replace("_", "")
    if enc != "utf8":
        print("경고: 기본 인코딩이 %s 다. 정본 read_source 가 이를 쓰므로 PYTHONUTF8=1 로 돌리는 편이 안전하다." %
              enc, file=sys.stderr)

    with tempfile.TemporaryDirectory(prefix="diff_parse_") as tmp:
        per_group, notes = build_cases(set(selected), args, tmp)
        problems = []
        stats = collections.OrderedDict()
        all_cases = []
        diffs, crashes = [], []
        for g in ALL_GROUPS:
            if g not in selected:
                continue
            cases = per_group[g]
            py_fn = A.check_result if args.mode == "check" else A.parse_result
            for c in cases:
                eval_python(c, py_fn)
            eval_rust(rs, cases, problems)
            stats[g] = collections.Counter(c.status for c in cases)
            stats[g]["inputs"] = len(cases)
            all_cases.extend(cases)
            for c in cases:
                if c.status == "diff":
                    diffs.append(c)
                elif c.status in ("py_crash", "rs_crash"):
                    crashes.append(c)

        saved = 0
        if args.save_dir:
            seq = 0
            for c in diffs + [c for c in crashes if c.status == "py_crash"]:
                save_case(args.save_dir, seq, c)
                seq += 1
            saved = seq
            if problems:
                os.makedirs(args.save_dir, exist_ok=True)
                write_bytes(os.path.join(args.save_dir, "rs_crash.txt"), ("\n".join(problems) + "\n").encode("utf-8"))

        print("rs: %s" % rs)
        print("")
        cols = ("inputs",) + STATUSES
        print("%-12s" % "group" + "".join("%14s" % c for c in cols))
        total = collections.Counter()
        for g, st in stats.items():
            print("%-12s" % g + "".join("%14d" % st[c] for c in cols))
            total.update(st)
        print("%-12s" % "TOTAL" + "".join("%14d" % total[c] for c in cols))
        for n in notes:
            print(n)

        if diffs:
            print("")
            print("== 처음 다른 사례 (최대 %d개 / 전체 diff %d) ==" % (MAX_SHOWN, len(diffs)))
            for c in diffs[:MAX_SHOWN]:
                i, a, b, la, lb = diff_detail(c)
                print("[%s] %s  (첫 차이 문자 위치 %d, py 길이 %d, rs 길이 %d)" % (c.group, c.name, i, la, lb))
                print("  py: " + a)
                print("  rs: " + b)
        pyc = [c for c in crashes if c.status == "py_crash"]
        if pyc:
            print("")
            print("== py_crash (최대 5개 / 전체 %d) ==" % len(pyc))
            for c in pyc[:5]:
                print("[%s] %s: %s" % (c.group, c.name, c.note))
        if problems:
            print("")
            print("== rs_crash (묶음 %d개, 최대 5개 표시) ==" % len(problems))
            for p in problems[:5]:
                print(p)
        if args.save_dir:
            print("")
            print("저장: 사례 %d개 -> %s" % (saved, args.save_dir))

        cov_fn = coverage_check if args.mode == "check" else coverage
        cov_ok = cov_fn(all_cases, enforce=(args.only is None))

    clean = all(total[k] == 0 for k in ("diff", "py_crash", "rs_crash"))
    ok = clean and cov_ok
    print("")
    print("결과: %s" % ("성공(모두 same, coverage 통과)" if ok else "실패"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
