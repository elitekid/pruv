#!/usr/bin/env python3
"""Pruv 컴파일러 차분 퍼징용 프로그램 생성기 (표준 라이브러리만, Python 3.9).

    generate_case(seed, index) -> dict      결정적 (random.Random(f"{seed}:{index}"))
    candidate_inputs(case, rng, n) -> list  인자 목록 n개 (requires 경계 근처 편향)

    python bench/fuzz/generate.py --seed S --count N --out DIR   # .pruv 파일로 눈으로 확인

생성 규칙: 매개변수는 불변, `let mut` 지역만 재대입, 모든 경로가 `return e;`로 끝남,
while에는 decreases(와 invariant), 이항식은 항상 괄호, 음수 리터럴은 `(-5)`.
기존 재료는 부수효과 없음. 새 계열(약 20%: arrfill/copy/effects/branches/nested/quant/helpers)은
`! io, alloc` 효과, 지역 배열, assert, 중첩 반복, bool 매개변수(params 타입 "bool"), 보조 함수를 쓴다.
새 계열(약 30%: twoarr/arrret/option/optparam/struct)은 배열 매개변수 2개, `-> [i64] ! alloc`,
Option/Result 반환·매개변수(params 타입 "Option<i64>"/"Result<i64>", 입력은 {"tag": "Some", "v": n} 형태 dict),
최상위 struct/enum 을 쓴다 (f 의 매개변수·반환에 약 70%, 나머지는 안쪽 지역·보조 함수).
구조체 틀은 requires 에도 구조체 리터럴·열거형·Option/Result ==/!= 를 넣고, 가끔 빈 구조체(`Unit {}`)·
Result 필드·열거형 필드를 쓴다. `tap(v) ! io` 로 평가 순서·단일 평가·두 필드 오버플로 순서를 관측하는 변형도 있다.
"""
import argparse
import copy
import os
import random
import sys

# 이미 보고한 컴파일러 결함을 피하는 생성 선택(run.py --avoid-known 이 채운다).
# "fz01": 인덱스 대입 `b[e1] = e2` 에서 e1·e2 가 모두 효과 있는 호출이면 평가 순서가 모드마다 다르다
#         (tests/runtime/fz01_index_assign_order). 피할 때는 값을 지역에 먼저 묶는다.
AVOID = set()

I64_MIN = -(1 << 63)
I64_MAX = (1 << 63) - 1
BOUNDS = [10, 1000, 1000000, 2147483648]
EXTREMES = [I64_MIN, I64_MAX, I64_MIN + 1, I64_MAX - 1, 1 << 31, -(1 << 31),
            1 << 32, -(1 << 32), 1 << 62, -(1 << 62), (1 << 31) - 1, 1 << 40]
SMALL_CONSTS = [0, 1, 2, 3, 5, 7, 10, 100, 1000, -1, -2, -5, -100]
CMPS = ["<", "<=", ">", ">=", "==", "!="]


def lit(n):
    """Pruv 리터럴: 음수는 (-5) 형태."""
    return str(n) if n >= 0 else "(-%d)" % (-n)


# ---------------------------------------------------------------- 컨텍스트 / 힌트

class Ctx:
    def __init__(self, rng):
        self.rng = rng
        self.ints = []        # i64 매개변수 이름
        self.arr = None       # 배열 매개변수 이름 ("a") 또는 None
        self.params = []      # [[이름, "i64"|"array"], ...] 선언 순서
        self.requires = []
        self.ensures = []
        self.ret = "i64"
        self.helper = None    # fn g 소스 또는 None
        self.undef_idx = None
        self.effects = []     # f 의 효과 목록 (["io", "alloc"] 중 정확히 쓰는 것)
        self.after = False    # True 면 보조 함수를 f 뒤에 둔다 (앞방향 호출)
        self.types = None     # 최상위 struct/enum 선언 소스 또는 None (맨 앞에 둔다)
        self.type_info = None  # {"structs": {이름: [[필드, 타입], ...]}, "enums": {이름: {변이: [[필드, 타입], ...]}}}
        # idx: 배열 경계 근처 인덱스 매개변수 / div: 0·음수 편향 제수 / neg: 음수 편향
        # wide: i64 극단 편향 / exact: {이름: [정확한 경계값]} / empty: 빈 배열 편향
        # exact_val: {이름: [값, ...]} 구조체·열거형·Option/Result 매개변수용 정확한 값 (입력 JSON 형태)
        self.hints = {"ints": {}, "arrays": {}, "consts": [3, 5, 10, 100], "rel": [], "pick": [],
                      "idx": [], "div": [], "neg": [], "wide": [], "exact": {}, "empty": False}


def hint_int(ctx, name):
    return ctx.hints["ints"].setdefault(name, {"lo": None, "hi": None, "cap": None})


def hint_arr(ctx, name):
    return ctx.hints["arrays"].setdefault(name, {"minlen": 0, "maxlen": 8, "elem": None, "sorted": False})


def set_int(ctx, name, lo=None, hi=None, cap=None):
    h = hint_int(ctx, name)
    if lo is not None:
        h["lo"] = lo if h["lo"] is None else max(h["lo"], lo)
    if hi is not None:
        h["hi"] = hi if h["hi"] is None else min(h["hi"], hi)
    if cap is not None:
        h["cap"] = cap


def set_arr(ctx, name, maxlen=None, minlen=None, elem=None, sorted_=False):
    h = hint_arr(ctx, name)
    if maxlen is not None:
        h["maxlen"] = min(h["maxlen"], maxlen)
    if minlen:
        h["minlen"] = max(h["minlen"], minlen)
    if elem is not None:
        if h["elem"] is None:
            h["elem"] = [elem[0], elem[1]]
        else:
            h["elem"] = [max(h["elem"][0], elem[0]), min(h["elem"][1], elem[1])]
    if sorted_:
        h["sorted"] = True


def declare(ctx, ints, arr, shuffle=True):
    params = [[n, "i64"] for n in ints]
    if arr:
        params.append(["a", "array"])
    if shuffle and ctx.rng.random() < 0.5:
        ctx.rng.shuffle(params)
    ctx.params = params
    ctx.ints = list(ints)
    ctx.arr = "a" if arr else None
    for n in ints:
        hint_int(ctx, n)
    if arr:
        hint_arr(ctx, "a")


# ---------------------------------------------------------------- 식 생성

def atom(rng, vars_, arr):
    r = rng.random()
    if vars_ and r < 0.55:
        return rng.choice(vars_)
    if arr and r < 0.68:
        return "len(%s)" % arr
    return lit(rng.choice(SMALL_CONSTS))


def expr(rng, vars_, arr, depth, helper=False):
    if depth <= 0 or rng.random() < 0.25:
        return atom(rng, vars_, arr)
    r = rng.random()
    if helper and r < 0.12:
        return "g(%s, %s)" % (expr(rng, vars_, arr, 1), expr(rng, vars_, arr, 1))
    if r < 0.22:
        return "(-%s)" % expr(rng, vars_, arr, depth - 1)
    op = rng.choice(["+", "+", "+", "-", "-", "-", "*", "*", "/", "%"])
    left = expr(rng, vars_, arr, depth - 1, helper)
    if op in ("/", "%"):
        if rng.random() < 0.6:
            right = str(rng.choice([1, 2, 3, 7, 10]))
        else:
            right = expr(rng, vars_, arr, depth - 1)
    else:
        right = expr(rng, vars_, arr, depth - 1, helper)
    return "(%s %s %s)" % (left, op, right)


def cond(rng, vars_, arr, depth=1):
    r = rng.random()
    if depth > 0 and r < 0.25:
        return "(%s %s %s)" % (cond(rng, vars_, arr, depth - 1), rng.choice(["&&", "||"]),
                               cond(rng, vars_, arr, depth - 1))
    if depth > 0 and r < 0.32:
        return "(!%s)" % cond(rng, vars_, arr, depth - 1)
    return "(%s %s %s)" % (expr(rng, vars_, arr, 1), rng.choice(CMPS), expr(rng, vars_, arr, 1))


def index_expr(rng, vars_, arr):
    r = rng.random()
    if vars_ and r < 0.4:
        return rng.choice(vars_)
    if vars_ and r < 0.6:
        return "(%s + %s)" % (rng.choice(vars_), lit(rng.choice([1, -1, 2])))
    if r < 0.8:
        return "(len(%s) - 1)" % arr
    return lit(rng.choice([0, 1, 2, 3]))


# ---------------------------------------------------------------- requires 재료

def req_bound_int(ctx):
    rng = ctx.rng
    x = rng.choice(ctx.ints)
    B = rng.choice(BOUNDS)
    f = rng.random()
    if f < 0.6:
        ctx.requires.append("(%s <= %s) && (%s <= %d)" % (lit(-B), x, x, B))
        set_int(ctx, x, lo=-B, hi=B)
    elif f < 0.8:
        ctx.requires.append("(0 <= %s) && (%s <= %d)" % (x, x, B))
        set_int(ctx, x, lo=0, hi=B)
    else:
        ctx.requires.append("%s <= %d" % (x, B))
        set_int(ctx, x, hi=B)


def req_len_le(ctx):
    N = ctx.rng.choice([0, 1, 2, 3, 4, 6, 8, 100, 1000000, 1000000])
    ctx.requires.append("len(a) <= %d" % N)
    set_arr(ctx, "a", maxlen=N)


def req_len_ge(ctx):
    k = ctx.rng.choice([1, 1, 2, 3])
    ctx.requires.append("len(a) >= %d" % k)
    set_arr(ctx, "a", minlen=k)


def req_elem(ctx):
    rng = ctx.rng
    if rng.random() < 0.3:
        ctx.requires.append("forall k in 0..len(a): a[k] >= 0")
        set_arr(ctx, "a", elem=(0, 1000))
    else:
        B = rng.choice(BOUNDS)
        ctx.requires.append("forall k in 0..len(a): ((%s <= a[k]) && (a[k] <= %d))" % (lit(-B), B))
        set_arr(ctx, "a", elem=(-B, B))


def req_rel(ctx):
    x, y = ctx.rng.sample(ctx.ints, 2)
    ctx.requires.append("(%s < %s)" % (x, y))
    ctx.hints["rel"].append([x, y])


def req_guard_idx(ctx):
    rng = ctx.rng
    x = rng.choice(ctx.ints)
    c = rng.choice([">", ">=", "<", "!="])
    k = rng.choice([0, 1, 5])
    test = "(a[%s] %s %d)" % (x, c, k)
    if rng.random() < 0.8:
        ctx.requires.append("(0 <= %s) && (%s < len(a)) && %s" % (x, x, test))
    else:
        ctx.requires.append(test)  # 무방비: 검증기는 contract_domain으로 거절해야 함
    set_int(ctx, x, lo=-1, hi=8)
    ctx.hints["idx"].append(x)


def req_div(ctx):
    rng = ctx.rng
    if len(ctx.ints) >= 2 and rng.random() < 0.8:
        x, y = rng.sample(ctx.ints, 2)
        if rng.random() < 0.75:
            ctx.requires.append("(%s != 0) && ((%s / %s) > 2)" % (y, x, y))
        else:
            ctx.requires.append("((%s / %s) > 2)" % (x, y))
    else:
        x = rng.choice(ctx.ints)
        ctx.requires.append("((%s / 3) > 1)" % x)


def req_mod(ctx):
    rng = ctx.rng
    x = rng.choice(ctx.ints)
    m = rng.choice([2, 3, 5])
    ctx.requires.append("((%s %% %d) == %d)" % (x, m, rng.randrange(m)))
    ctx.hints["consts"].append(m)


def req_sum(ctx):
    K = ctx.rng.choice([0, 10, 100, 1000])
    ctx.requires.append("(sum(k in 0..len(a): a[k]) %s %d)" % (ctx.rng.choice(["<=", ">="]), K))
    ctx.hints["consts"].append(K)


def req_count(ctx):
    rng = ctx.rng
    if ctx.ints and rng.random() < 0.5:
        x = rng.choice(ctx.ints)
        ctx.requires.append("(count(k in 0..len(a): (a[k] < %s)) >= 1)" % x)
    else:
        ctx.requires.append("(count(k in 0..len(a): (a[k] > 0)) <= 2)")


def req_max(ctx):
    rng = ctx.rng
    fn = rng.choice(["max", "min"])
    test = "(max(k in 0..len(a): a[k]) < 50)" if fn == "max" else "(min(k in 0..len(a): a[k]) > (-50))"
    if rng.random() < 0.7:
        ctx.requires.append("(len(a) >= 1) && %s" % test)
        set_arr(ctx, "a", minlen=1)
    else:
        ctx.requires.append(test)  # 무방비 max/min: contract_domain 기대
    ctx.hints["consts"].append(50)


def req_exists(ctx):
    x = ctx.rng.choice(ctx.ints)
    ctx.requires.append("exists k in 0..len(a): a[k] == %s" % x)
    ctx.hints["pick"].append([x, "a"])


SORTED_FORMS = [
    # (가중치, 텍스트) — 앞 둘은 O(n) 검사 형태, 나머지는 일반 검사여야 하는 근접 변형
    (3, "forall i in 0..len(a): forall j in i..len(a): a[i] <= a[j]"),
    (3, "forall i in 0..len(a): forall j in (i + 1)..len(a): a[i] <= a[j]"),
    (1, "forall i in 0..len(a): forall j in (i + 2)..len(a): a[i] <= a[j]"),
    (1, "forall i in 0..len(a): forall j in i..(len(a) - 1): a[i] <= a[j]"),
    (1, "forall i in 0..len(a): forall j in (i + 1)..len(a): a[i] < a[j]"),
]


def req_sorted(ctx):
    ws = [w for w, _ in SORTED_FORMS]
    ctx.requires.append(ctx.rng.choices([t for _, t in SORTED_FORMS], weights=ws)[0])
    set_arr(ctx, "a", sorted_=True)


def req_impl(ctx):
    rng = ctx.rng
    opts = []
    if ctx.ints:
        x = rng.choice(ctx.ints)
        opts.append("((%s > 0) ==> (%s < 100))" % (x, x))
    if ctx.arr:
        opts.append("((len(a) > 0) ==> (a[0] >= 0))")
    if ctx.ints and ctx.arr:
        x = rng.choice(ctx.ints)
        opts.append("(((0 <= %s) && (%s < len(a))) ==> (a[%s] >= 0))" % (x, x, x))
        opts.append("((%s >= 0) ==> (%s < len(a)))" % (x, x))
    ctx.requires.append(rng.choice(opts))


# (함수, 정수 필요, 정수 2개 필요, 배열 필요)
REQ_TABLE = [
    (req_bound_int, True, False, False), (req_bound_int, True, False, False),
    (req_len_le, False, False, True), (req_len_ge, False, False, True),
    (req_elem, False, False, True), (req_rel, True, True, False),
    (req_guard_idx, True, False, True), (req_div, True, False, False),
    (req_mod, True, False, False), (req_sum, False, False, True),
    (req_count, False, False, True), (req_max, False, False, True),
    (req_exists, True, False, True), (req_sorted, False, False, True),
    (req_impl, False, False, False),
]


def add_requires(ctx, count):
    cands = []
    for fn, ni, n2, na in REQ_TABLE:
        if ni and not ctx.ints:
            continue
        if n2 and len(ctx.ints) < 2:
            continue
        if na and not ctx.arr:
            continue
        if fn is req_impl and not (ctx.ints or ctx.arr):
            continue
        cands.append(fn)
    for _ in range(count):
        if cands:
            ctx.rng.choice(cands)(ctx)


def add_ensures(ctx, pure_expr=None, p=0.6):
    rng = ctx.rng
    if rng.random() >= p:
        return
    for _ in range(rng.choice([1, 1, 2])):
        opts = []
        if ctx.ret == "bool":
            if pure_expr:
                opts += ["result == %s" % pure_expr] * 3
            if ctx.ints:
                opts.append("(result ==> (%s >= %s))" % (rng.choice(ctx.ints), lit(rng.choice([0, 1, -5]))))
                opts.append("((!result) || (%s <= %d))" % (rng.choice(ctx.ints), rng.choice([10, 1000])))
            opts.append("(result || (!result))")
        else:
            K = rng.choice([0, 1, 10, 1000, 1000000, 2147483648])
            opts += ["(result >= %s)" % lit(-K), "(result <= %d)" % K]
            if ctx.ints:
                opts += ["(result >= %s)" % rng.choice(ctx.ints), "(result <= %s)" % rng.choice(ctx.ints)]
            if ctx.arr:
                opts.append("(result <= len(a))")
            if pure_expr:
                opts += ["result == %s" % pure_expr] * 3
        ctx.ensures.append(rng.choice(opts))


# ---------------------------------------------------------------- 보조 함수 g

def make_helper(rng, force=None, info=None):
    v = rng.randrange(4)
    if force is not None:
        v = force
    B = rng.choice([1000, 1000000])
    if v == 0:
        req = ["(0 <= p) && (p <= %d)" % B, "(0 <= q) && (q <= %d)" % B]
        body, ens = "(p + q)", [rng.choice(["result == (p + q)", "result >= p"])]
    elif v == 1:
        req = ["q > 0", "p >= 0"]
        body, ens = "(p / q)", [rng.choice(["result >= 0", "result <= p"])]
    elif v == 2:
        req = []
        body, ens = "(p - q)", ["result == (p - q)"]
    else:
        req = ["p < q"] + (["(0 <= p) && (q <= %d)" % B] if rng.random() < 0.6 else [])
        body, ens = "(q - p)", ["result > 0"]
    if rng.random() < 0.15:
        ens = ["result >= (-5)"]  # 거짓일 수 있음
    if info is not None:
        info["req"] = list(req)
        info["B"] = B
    lines = ["fn g(p: i64, q: i64) -> i64"]
    lines += ["  requires " + r for r in req]
    lines += ["  ensures " + e for e in ens]
    lines += ["{", "  return %s;" % body, "}"]
    return "\n".join(lines)


# ---------------------------------------------------------------- 본문: pure / straight

def body_pure(ctx):
    rng = ctx.rng
    if ctx.ret == "bool":
        E = cond(rng, ctx.ints, ctx.arr, 1)
    else:
        E = expr(rng, ctx.ints, ctx.arr, 3)
    add_ensures(ctx, pure_expr=E)
    return ["  return %s;" % E]


def body_straight(ctx):
    rng = ctx.rng
    arr = ctx.arr
    vars_ = list(ctx.ints)
    helper = ctx.helper is not None
    lines = []
    muts = []
    for j in range(rng.randint(1, 3)):
        name = "v%d" % j
        lines.append("  let mut %s: i64 = %s;" % (name, expr(rng, vars_, arr, 2, helper)))
        vars_.append(name)
        muts.append(name)
    for _ in range(rng.randint(1, 4)):
        t = rng.random()
        m = rng.choice(muts)
        if t < 0.30:
            lines.append("  %s = %s;" % (m, expr(rng, vars_, arr, 2, helper)))
        elif t < 0.55:
            lines.append("  if %s {" % cond(rng, vars_, arr, 1))
            lines.append("    %s = %s;" % (m, expr(rng, vars_, arr, 2, helper)))
            if rng.random() < 0.6:
                lines.append("  } else {")
                lines.append("    %s = %s;" % (rng.choice(muts), expr(rng, vars_, arr, 2, helper)))
            lines.append("  }")
        elif arr and t < 0.78:
            e = index_expr(rng, vars_, arr)
            lines.append("  if ((0 <= %s) && (%s < len(%s))) {" % (e, e, arr))
            lines.append("    %s = (%s + %s[%s]);" % (m, m, arr, e) if rng.random() < 0.6
                         else "    %s = %s[%s];" % (m, arr, e))
            if rng.random() < 0.4:
                lines.append("  } else {")
                lines.append("    %s = %s;" % (m, expr(rng, vars_, arr, 1)))
            lines.append("  }")
        elif arr and t < 0.88:
            e = index_expr(rng, vars_, arr)  # 무방비 인덱스
            lines.append("  %s = (%s + %s[%s]);" % (m, m, arr, e))
        else:
            lines.append("  %s = %s;" % (m, expr(rng, vars_, arr, 2, helper)))
    if ctx.ret == "bool":
        lines.append("  return %s;" % cond(rng, vars_, arr, 1))
    else:
        if rng.random() < 0.3:
            lines.append("  if %s {" % cond(rng, vars_, arr, 1))
            lines.append("    return %s;" % expr(rng, vars_, arr, 2, helper))
            lines.append("  }")
        lines.append("  return %s;" % expr(rng, vars_, arr, 2, helper))
    add_ensures(ctx)
    return lines


# ---------------------------------------------------------------- 반복문 틀

def loop_text(parts, indent="  "):
    out = [indent + "while " + parts["cond"]]
    for inv in parts["invs"]:
        out.append(indent + "  invariant " + inv)
    out.append(indent + "  decreases " + parts["decr"])
    out.append(indent + "{")
    for b in parts["body"] + parts["step"]:
        out.append(indent + "  " + b)
    out.append(indent + "}")
    return out


def mutate(ctx, parts, extra=None):
    """근접 실패(near-miss) 프로그램을 만들기 위한 변이. extra: {이름: 함수(parts)}."""
    rng = ctx.rng
    ops = {}
    if parts["invs"]:
        ops["drop_inv"] = lambda p: p["invs"].pop(rng.randrange(len(p["invs"])))
        def strict(p):
            s = p["invs"][0]
            k = s.rfind("<=")
            if k >= 0:
                p["invs"][0] = s[:k] + "<" + s[k + 2:]
        ops["inv_strict"] = strict
    if "i < len(a)" in parts["cond"]:
        ops["cond_le"] = lambda p: p.__setitem__("cond", p["cond"].replace("i < len(a)", "i <= len(a)"))
    if "m > 0" in parts["cond"]:
        ops["cond_ge"] = lambda p: p.__setitem__("cond", p["cond"].replace("m > 0", "m >= 0"))
    ops["step2"] = lambda p: p.__setitem__(
        "step", [s.replace("+ 1", "+ 2").replace("- 1", "- 2") for s in p["step"]])
    ops["decr_bad"] = lambda p: p.__setitem__("decr", p["decr_bad"])
    if extra:
        ops.update(extra)
    name = rng.choice(sorted(ops))
    ops[name](parts)
    return name


def finish_template(ctx, pre, parts, post, extra_mut=None, p_mut=0.35):
    if ctx.rng.random() < p_mut:
        mutate(ctx, parts, extra_mut)
    if ctx.rng.random() < 0.3:
        add_requires(ctx, 1)
    return pre + loop_text(parts) + post


def tmpl_sum(ctx):
    rng = ctx.rng
    B = rng.choice([10, 1000, 1000000, 1000000000])
    N = rng.choice([8, 1000, 1000000])
    declare(ctx, ["x"] if rng.random() < 0.25 else [], True)
    if rng.random() < 0.9:
        ctx.requires.append("len(a) <= %d" % N)
        set_arr(ctx, "a", maxlen=N)
    if rng.random() < 0.9:
        ctx.requires.append("forall k in 0..len(a): ((%s <= a[k]) && (a[k] <= %d))" % (lit(-B), B))
        set_arr(ctx, "a", elem=(-B, B))
    invs = ["(0 <= i) && (i <= len(a))", "(s >= (%s * i)) && (s <= (%d * i))" % (lit(-B), B)]
    if rng.random() < 0.7:
        invs.append("s == sum(k in 0..i: a[k])")
        ctx.ensures.append("result == sum(k in 0..len(a): a[k])")
    if rng.random() < 0.25:
        ctx.ensures.append("(result >= %s)" % lit(-(B * rng.choice([1, 8, N]))))
    parts = {"cond": "(i < len(a))", "invs": invs, "decr": "(len(a) - i)", "decr_bad": "len(a)",
             "body": ["s = (s + a[i]);"], "step": ["i = (i + 1);"]}
    return finish_template(ctx, ["  let mut s: i64 = 0;", "  let mut i: i64 = 0;"], parts, ["  return s;"])


def tmpl_count(ctx):
    rng = ctx.rng
    declare(ctx, ["x"], True)
    if rng.random() < 0.4:
        ctx.hints["pick"].append(["x", "a"])
    invs = ["(0 <= i) && (i <= len(a))", "c == count(k in 0..i: (a[k] < x))", "(0 <= c) && (c <= i)"]
    if rng.random() < 0.85:
        ctx.ensures.append("result == count(k in 0..len(a): (a[k] < x))")
    if rng.random() < 0.4:
        ctx.ensures.append("(0 <= result) && (result <= len(a))")
    parts = {"cond": "(i < len(a))", "invs": invs, "decr": "(len(a) - i)", "decr_bad": "len(a)",
             "body": ["if (a[i] < x) {", "  c = (c + 1);", "}"], "step": ["i = (i + 1);"]}
    extra = {"cmp_swap": lambda p: p.__setitem__("body", ["if (a[i] <= x) {", "  c = (c + 1);", "}"])}
    return finish_template(ctx, ["  let mut c: i64 = 0;", "  let mut i: i64 = 0;"], parts, ["  return c;"], extra)


def tmpl_maxscan(ctx):
    rng = ctx.rng
    declare(ctx, ["x"] if rng.random() < 0.25 else [], True)
    if rng.random() < 0.9:
        ctx.requires.append("len(a) >= 1")
        set_arr(ctx, "a", minlen=1)
    invs = ["(1 <= i) && (i <= len(a))", "m == max(k in 0..i: a[k])"]
    if rng.random() < 0.85:
        ctx.ensures.append("result == max(k in 0..len(a): a[k])")
    parts = {"cond": "(i < len(a))", "invs": invs, "decr": "(len(a) - i)", "decr_bad": "len(a)",
             "body": ["if (a[i] > m) {", "  m = a[i];", "}"], "step": ["i = (i + 1);"]}
    extra = {"cmp_flip": lambda p: p.__setitem__("body", ["if (a[i] < m) {", "  m = a[i];", "}"])}
    return finish_template(ctx, ["  let mut m: i64 = a[0];", "  let mut i: i64 = 1;"], parts, ["  return m;"], extra)


def tmpl_search(ctx):
    rng = ctx.rng
    declare(ctx, ["x"], True)
    if rng.random() < 0.6:
        ctx.hints["pick"].append(["x", "a"])
    invs = ["(0 <= i) && (i <= len(a))"]
    if rng.random() < 0.6:
        invs.append("forall k in 0..i: (a[k] != x)")
    if rng.random() < 0.9:
        ctx.ensures.append("(result == (-1)) || ((0 <= result) && (result < len(a)) && (a[result] == x))")
    parts = {"cond": "(i < len(a))", "invs": invs, "decr": "(len(a) - i)", "decr_bad": "len(a)",
             "body": ["if (a[i] == x) {", "  return i;", "}"], "step": ["i = (i + 1);"]}
    extra = {"ret_off": lambda p: p.__setitem__("body", ["if (a[i] == x) {", "  return (i + 1);", "}"])}
    return finish_template(ctx, ["  let mut i: i64 = 0;"], parts, ["  return (-1);"], extra)


def tmpl_countdown(ctx):
    rng = ctx.rng
    c = rng.choice([1, 2, 3])
    declare(ctx, ["n"], False)
    B = rng.choice([10, 1000, 3000])
    set_int(ctx, "n", cap=3000)  # 반복 횟수를 제한해 바이너리가 오래 돌지 않게
    f = rng.random()
    if f < 0.6:
        ctx.requires.append("(0 <= n) && (n <= %d)" % B)
        set_int(ctx, "n", lo=0, hi=B)
    elif f < 0.8:
        ctx.requires.append("0 <= n")
        set_int(ctx, "n", lo=0)
    elif f < 0.9:
        ctx.requires.append("n <= %d" % B)
        set_int(ctx, "n", hi=B)
    invs = ["(0 <= m) && (m <= n)", "s == (%d * (n - m))" % c]
    if rng.random() < 0.7:
        ctx.ensures.append("result == (%d * n)" % c)
    parts = {"cond": "(m > 0)", "invs": invs, "decr": "m", "decr_bad": "n",
             "body": ["s = (s + %d);" % c], "step": ["m = (m - 1);"]}
    return finish_template(ctx, ["  let mut m: i64 = n;", "  let mut s: i64 = 0;"], parts, ["  return s;"])


def tmpl_range(ctx):
    rng = ctx.rng
    declare(ctx, ["x"] if rng.random() < 0.25 else [], True)
    if rng.random() < 0.9:
        ctx.requires.append("len(a) >= 1")
        set_arr(ctx, "a", minlen=1)
    if rng.random() < 0.9:
        req_sorted(ctx)
    if rng.random() < 0.85:
        B = rng.choice([1000, 1000000, 2147483648])
        ctx.requires.append("forall k in 0..len(a): ((%s <= a[k]) && (a[k] <= %d))" % (lit(-B), B))
        set_arr(ctx, "a", elem=(-B, B))
    if rng.random() < 0.5:
        ret = "(a[(len(a) - 1)] - a[0])"
    else:
        ret = "(a[0] - a[(len(a) - 1)])"
    ctx.ensures.append(rng.choice(["result >= 0", "result >= 0", "result <= 0"]))
    if rng.random() < 0.3:
        add_requires(ctx, 1)
    return ["  return %s;" % ret]


TEMPLATES = [tmpl_sum, tmpl_count, tmpl_maxscan, tmpl_search, tmpl_countdown, tmpl_range]

I64_MIN_EXPR = "((-9223372036854775807) - 1)"   # 계약 리터럴은 수학적이지만 음수는 이렇게 쓴다


# ---------------------------------------------------------------- 새 재료 1: requires 미정의 (undef)

def undef_req(ctx, kind, guarded):
    """부분 계약 연산이 든 requires 줄 목록. guarded=False면 방어가 뒤에 있거나 없거나 순서가 바뀐다."""
    rng = ctx.rng
    x = rng.choice(ctx.ints)
    if kind == "idx":
        c = rng.choice([">", ">=", "<", "!="])
        k = rng.choice([0, 1, 5])
        test = "(a[%s] %s %d)" % (x, c, k)
        full = "(0 <= %s) && (%s < len(a))" % (x, x)
        ctx.hints["idx"].append(x)
        if guarded:
            ctx.undef_idx = (x, c, k)
            return [full + " && " + test]
        f = rng.randrange(3)
        if f == 0:
            return [test + " && " + full]
        if f == 1:
            return ["(%s < len(a)) && %s" % (x, test)]
        return [test, full]
    if kind == "div":
        x, y = rng.sample(ctx.ints, 2)
        if rng.random() < 0.7:
            t = "((%s / %s) > 2)" % (x, y)
        else:
            t = "((%s %% %s) == 1)" % (x, y)
        guard = "(%s != 0)" % y
        ctx.hints["div"].append(y)
        ctx.hints["neg"] += [x, y]
        if guarded:
            return [guard + " && " + t]
        f = rng.randrange(3)
        return [[t + " && " + guard], [t], [t, guard]][f]
    if kind == "max":
        if rng.random() < 0.5:
            t = "(max(k in 0..len(a): a[k]) < 50)"
        else:
            t = "(min(k in 0..len(a): a[k]) > (-50))"
        guard = "(len(a) >= 1)"
        ctx.hints["empty"] = True
        ctx.hints["consts"].append(50)
        if guarded:
            return [guard + " && " + t]
        f = rng.randrange(3)
        return [[t + " && " + guard], [t], [t, guard]][f]
    # forall / exists: 0..x 가 len(a)를 넘을 수 있다
    if kind == "forall":
        q = "forall k in 0..%s: (a[k] >= 0)" % x
    else:
        q = "exists k in 0..%s: (a[k] == 0)" % x
    guard = "%s <= len(a)" % x
    ctx.hints["idx"].append(x)
    ctx.hints["empty"] = True
    if guarded:
        return [guard, q]
    f = rng.randrange(3)
    return [[q], [q, guard], [q]][f]


def tmpl_undef(ctx):
    rng = ctx.rng
    has_arr = rng.random() < 0.8
    n_int = 2 if (not has_arr or rng.random() < 0.4) else 1
    declare(ctx, ["x", "y"][:n_int], has_arr)
    kinds = []
    if has_arr:
        kinds += ["idx", "idx", "max", "forall", "exists"]
    if n_int >= 2:
        kinds += ["div", "div"]
    guarded = rng.random() < 0.45
    chosen = [rng.choice(kinds)]
    if rng.random() < 0.25:
        chosen.append(rng.choice(kinds))
    for k in chosen:
        ctx.requires += undef_req(ctx, k, guarded)
    if ctx.undef_idx and len(chosen) == 1 and rng.random() < 0.5:
        x, c, k = ctx.undef_idx
        ctx.ensures.append("(result %s %d)" % (c, k))
        return ["  return a[%s];" % x]
    if rng.random() < 0.3:
        return body_pure(ctx)
    return body_straight(ctx)


# ---------------------------------------------------------------- 새 재료 2: i128 를 넘는 비선형 계약

def tmpl_wide(ctx):
    rng = ctx.rng
    two = rng.random() < 0.6
    declare(ctx, ["x", "y"] if two else ["x"], False)
    if two:
        e = rng.choice(["((x * y) * x)", "((x * y) * y)"])
        B = rng.choice([100000, 1 << 40])
    else:
        e = "x"
        for _ in range(4):
            e = "(%s * x)" % e
        B = rng.choice([1000, 100000])
    prod = "(%s != %d)" % (e, rng.choice([7, 11]))
    bounds = ["(%s <= %s) && (%s <= %d)" % (lit(-B), n, n, B) for n in ctx.ints]
    m = rng.random()
    if m < 0.4:
        ctx.requires.append(prod)
        ctx.hints["wide"] += ctx.ints
        bounded = False
    elif m < 0.7:
        ctx.requires += bounds + [prod]
        for n in ctx.ints:
            set_int(ctx, n, lo=-B, hi=B)
        bounded = True
    else:
        ctx.requires += [prod] + bounds   # 경계가 곱 뒤에 있어 곱이 먼저 미정의가 될 수 있다
        ctx.hints["wide"] += ctx.ints
        for n in ctx.ints:
            set_int(ctx, n, lo=-B, hi=B)
        bounded = True
    if bounded:
        if two:
            ctx.ensures.append("result == (x + y)")
            return ["  return (x + y);"]
        ctx.ensures.append("result == (x + 1)")
        return ["  return (x + 1);"]
    if rng.random() < 0.5:
        ctx.ensures.append("result == 1")
        return ["  return 1;"]
    ctx.ensures.append("result >= 0")
    return ["  if (x < 0) {", "    return 0;", "  }", "  return 1;"]


# ---------------------------------------------------------------- 새 재료 3: 유클리드 계약 나눗셈/나머지

def tmpl_euclid(ctx):
    rng = ctx.rng
    declare(ctx, ["x", "y"], False)
    ctx.hints["neg"] += ["x", "y"]
    ctx.hints["div"].append("y")
    v = rng.randrange(4)
    if v == 0:
        r = rng.choice([0, 1, 1, 1, 2, -1])
        ctx.requires.append("(y != 0) && ((x %% y) == %s)" % lit(r))
        ctx.ensures.append("result == (x % y)")
        return ["  return %s;" % lit(r)]
    if v == 1:
        ctx.requires.append("y != 0")
        ctx.ensures.append("(((x >= 0) && (y > 0)) ==> (result == (x / y)))")
        g = "((x >= 0) && (y > 0))" if rng.random() < 0.75 else "(y > 0)"
        return ["  if %s {" % g, "    return (x / y);", "  }", "  return 0;"]
    if v == 2:
        ctx.requires.append("(%s <= x) && (x <= 1000000)" % lit(-1000000))
        set_int(ctx, "x", lo=-1000000, hi=1000000)
        if rng.random() < 0.5:
            ctx.ensures.append("result == (x / 3)")
            if rng.random() < 0.25:
                neg = "((x - 2) / 3)"
            else:
                neg = "((x - (((x % 3) + 3) % 3)) / 3)"
            return ["  if (x >= 0) {", "    return (x / 3);", "  }", "  return %s;" % neg]
        ctx.ensures.append("result == (x % 3)")
        return ["  if (x >= 0) {", "    return (x % 3);", "  }", "  return (((x % 3) + 3) % 3);"]
    ctx.requires.append("y > 0")
    ctx.ensures.append("((0 <= result) && (result < y))")
    c = "(r < 0)" if rng.random() < 0.8 else "(r <= 0)"
    return ["  let mut r: i64 = (x % y);", "  if %s {" % c, "    r = (r + y);", "  }", "  return r;"]


# ---------------------------------------------------------------- 새 재료 4: 정렬 전제

def tmpl_sorted(ctx):
    rng = ctx.rng
    declare(ctx, ["x"] if rng.random() < 0.2 else [], True)
    first = rng.random() < 0.5
    sorted_req = []
    saved = ctx.requires
    ctx.requires = sorted_req
    req_sorted(ctx)
    ctx.requires = saved
    others = []
    simple = rng.random() < 0.5
    if simple and rng.random() < 0.9:
        others.append("len(a) >= 1")
        set_arr(ctx, "a", minlen=1)
    if rng.random() < 0.9:
        B = rng.choice([1000, 1000000, 2147483648])
        others.append("forall k in 0..len(a): ((%s <= a[k]) && (a[k] <= %d))" % (lit(-B), B))
        set_arr(ctx, "a", elem=(-B, B))
    ctx.requires += (sorted_req + others) if first else (others + sorted_req)
    ctx.ensures.append(rng.choice(["result >= 0", "result >= 0", "result <= 0"]))
    if simple:
        if rng.random() < 0.5:
            return ["  return (a[(len(a) - 1)] - a[0]);"]
        return ["  return (a[0] - a[(len(a) - 1)]);"]
    return ["  if (len(a) >= 2) {", "    return (a[1] - a[0]);", "  }", "  return 0;"]


# ---------------------------------------------------------------- 새 재료 5: i64 경계 산술

def tmpl_bound(ctx):
    rng = ctx.rng
    near = rng.random() < 0.45
    v = rng.randrange(5)
    if v == 4:
        declare(ctx, ["x", "y"], False)
        H = 4611686018427387903 + (1 if near else 0)
        ctx.requires.append("(0 <= x) && (x <= %d)" % H)
        ctx.requires.append("(0 <= y) && (y <= %d)" % H)
        for n in ("x", "y"):
            set_int(ctx, n, lo=0, hi=H)
            ctx.hints["exact"][n] = [0, H, H - 1, 4611686018427387903]
        ctx.ensures.append("result >= x")
        return ["  return (x + y);"]
    declare(ctx, ["x"], False)
    if v == 0:
        H = 9223372036854775806 + (1 if near else 0)
        ctx.requires.append("(0 <= x) && (x <= %d)" % H)
        set_int(ctx, "x", lo=0, hi=H)
        ctx.hints["exact"]["x"] = [0, H, H - 1, 9223372036854775806]
        ctx.ensures.append(rng.choice(["result == (x + 1)", "result > x"]))
        return ["  return (x + 1);"]
    if v == 1:
        B = 3037000499 + (1 if near else 0)
        if near and rng.random() < 0.5:
            lo_b = 3037000499
        else:
            lo_b = B
        ctx.requires.append("(%s <= x) && (x <= %d)" % (lit(-lo_b), B))
        set_int(ctx, "x", lo=-lo_b, hi=B)
        ctx.hints["exact"]["x"] = [-lo_b, B, 3037000499, -3037000499, 3037000500, -3037000500]
        ctx.ensures.append("result >= 0")
        return ["  return (x * x);"]
    if v == 2:
        op = ">=" if near else ">"
        ctx.requires.append("x %s %s" % (op, I64_MIN_EXPR))
        ctx.hints["exact"]["x"] = [I64_MIN, I64_MIN + 1, I64_MAX, 0, -1]
        ctx.ensures.append("result == (0 - x)")
        return ["  return (-x);"]
    lo_e = I64_MIN_EXPR if near else "(-9223372036854775807)"
    ctx.requires.append("%s <= x" % lo_e)
    ctx.hints["exact"]["x"] = [I64_MIN, I64_MIN + 1, I64_MIN + 2, I64_MAX, 0, 1]
    ctx.ensures.append("result == (x - 1)")
    return ["  return (x - 1);"]


# ---------------------------------------------------------------- 새 재료 6: 코드 나눗셈/나머지 방어

def tmpl_divguard(ctx):
    rng = ctx.rng
    declare(ctx, ["x", "y"], False)
    ctx.hints["div"].append("y")
    ctx.hints["neg"] += ["x", "y"]
    op = rng.choice(["/", "%"])
    e = "(x %s y)" % op
    r = rng.random()
    if r < 0.40:
        if rng.random() < 0.6:
            ctx.ensures.append("result >= 0")
        return ["  if ((y > 0) && (x >= 0)) {", "    return %s;" % e, "  }", "  return 0;"]
    if r < 0.55:
        return ["  if (x >= 0) {", "    return %s;" % e, "  }", "  return 0;"]
    if r < 0.67:
        return ["  if (y != 0) {", "    return %s;" % e, "  }", "  return 0;"]
    if r < 0.85:
        ctx.requires.append("y >= 1")
        return ["  return %s;" % e]
    return ["  return %s;" % e]


# ---------------------------------------------------------------- 새 재료 7: 호출 전제가 일부 입력에서만 성립

def tmpl_call(ctx):
    rng = ctx.rng
    declare(ctx, ["x", "y"], False)
    v = rng.choice([0, 1, 3])
    info = {}
    ctx.helper = make_helper(rng, v, info)
    B = info["B"]
    clauses = [c.replace("p", "x").replace("q", "y") for c in info["req"]]
    if rng.random() < 0.4:
        idxs = [i for i, c in enumerate(clauses) if " > 0" in c or " < " in c]
        if idxs and rng.random() < 0.6:
            i = rng.choice(idxs)
            clauses[i] = clauses[i].replace(" > 0", " >= 0").replace(" < ", " <= ")
        elif clauses:
            clauses.pop(rng.randrange(len(clauses)))
    if v == 3:
        ctx.hints["rel"].append(["x", "y"])
    ex = [0, 1, -1, 2]
    if v in (0, 3):
        ex += [B, B + 1, B - 1, B + 2]
    for n in ("x", "y"):
        ctx.hints["exact"][n] = list(ex)
    if rng.random() < 0.5:
        ctx.requires += clauses
        body = ["  return g(x, y);"]
    else:
        if clauses:
            cnd = "(" + " && ".join("(%s)" % c for c in clauses) + ")"
        else:
            cnd = "(x >= 0)"
        body = ["  if %s {" % cnd, "    return g(x, y);", "  }", "  return 0;"]
    if rng.random() < 0.5:
        ctx.ensures.append("result >= 0")
    return body


# ---------------------------------------------------------------- 새 계열: 지역 배열 / 효과 / assert / 중첩 반복 /
# bool / 양화 ensures / 보조 함수 (감사에서 빠졌던 기능)

def declare2(ctx, ints, arr, bools):
    """declare + bool 매개변수. 매개변수 타입: "i64" | "array" | "bool"."""
    params = [[n, "i64"] for n in ints]
    if arr:
        params.append(["a", "array"])
    params += [[n, "bool"] for n in bools]
    if ctx.rng.random() < 0.5:
        ctx.rng.shuffle(params)
    ctx.params = params
    ctx.ints = list(ints)
    ctx.arr = "a" if arr else None
    for n in ints:
        hint_int(ctx, n)
    if arr:
        hint_arr(ctx, "a")


def maybe_mutate(ctx, loops, extras, p=0.3):
    if ctx.rng.random() < p:
        mutate(ctx, ctx.rng.choice(loops), extras)


def cond_lt_le(p):
    p["cond"] = p["cond"].replace(" < ", " <= ", 1)


def idx_off(var, arr):
    """본문의 arr[var] 쓰기를 한 칸 밀어 index_oob 근접 실패를 만든다."""
    def f(p):
        p["body"] = [s.replace("%s[%s]" % (arr, var), "%s[(%s + 1)]" % (arr, var)) for s in p["body"]]
    return f


def bound_elem(ctx, B):
    ctx.requires.append("forall k in 0..len(a): ((%s <= a[k]) && (a[k] <= %d))" % (lit(-B), B))
    set_arr(ctx, "a", elem=(-B, B))


# -- 1) 지역 배열: alloc 로 채우기

def tmpl_arrfill(ctx):
    rng = ctx.rng
    ctx.effects = ["alloc"]
    src = rng.choice(["len", "len", "const", "param"])
    val = rng.choice(["mod", "dbl", "src"]) if src == "len" else rng.choice(["mod", "dbl"])
    c = rng.choice([1, 2, 5])
    if src == "len":
        declare2(ctx, [], True, [])
        N = "len(a)"
        if rng.random() < 0.4:
            M = rng.choice([8, 100, 1000000])
            ctx.requires.append("len(a) <= %d" % M)
            set_arr(ctx, "a", maxlen=M)
        if val == "src" and rng.random() < 0.9:
            bound_elem(ctx, rng.choice([1000, 1000000]))
    elif src == "const":
        N = str(rng.choice([0, 1, 3, 5, 8]))
        if rng.random() < 0.5:
            declare2(ctx, [], True, [])
        else:
            declare2(ctx, ["x"], False, [])
    else:
        declare2(ctx, ["n"], rng.random() < 0.3, [])
        N = "n"
        set_int(ctx, "n", cap=100)
        f = rng.random()
        if f < 0.8:
            ctx.requires.append("(0 <= n) && (n <= 100)")
            set_int(ctx, "n", lo=0, hi=100)
        elif f < 0.9:
            ctx.requires.append("n <= 100")          # 음수 n: alloc 전제를 증명 못 함
            set_int(ctx, "n", hi=100)
        else:
            ctx.requires.append("0 <= n")            # 상한 없음: alloc 전제를 증명 못 함
            set_int(ctx, "n", lo=0)
    if val == "mod":
        V, spec = "(i % 7)", "forall k in 0..i: ((0 <= b[k]) && (b[k] <= 6))"
    elif val == "dbl":
        V, spec = "(i * 2)", "forall k in 0..i: (b[k] == (k * 2))"
    else:
        V, spec = "(a[i] + %d)" % c, "forall k in 0..i: (b[k] == (a[k] + %d))" % c
    eps = ["len", "elem", "elem"]
    if val == "mod":
        eps += ["sum", "sum"]
    if src == "len":
        eps.append("last")
    ep = rng.choice(eps)
    use_spec = rng.random() < (0.92 if ep in ("sum", "elem") else 0.6)
    if ep == "last" and rng.random() < 0.85:
        ctx.requires.append("len(a) >= 1")
        set_arr(ctx, "a", minlen=1)
    pre = ["  let mut b: [i64] = alloc(%s, %s);" % (N, lit(rng.choice([0, 0, 1, -1]))), "  let mut i: i64 = 0;"]
    if rng.random() < 0.2:
        pre.insert(1, "  assert (len(b) == %s);" % N)
    invs = ["(0 <= i) && (i <= %s)" % N, "len(b) == %s" % N]
    if use_spec:
        invs.append(spec)
    p1 = {"cond": "(i < %s)" % N, "invs": invs, "decr": "(%s - i)" % N, "decr_bad": N,
          "body": ["b[i] = %s;" % V], "step": ["i = (i + 1);"]}
    loops = [p1]
    post = []
    if rng.random() < 0.25:
        post.append("  assert %s;" % (rng.choice(["(len(b) == %s)" % N, "(i == %s)" % N]) if rng.random() < 0.85
                                       else rng.choice(["(len(b) > %s)" % N, "(i < %s)" % N])))
    if ep == "len":
        post.append("  return len(b);")
        if rng.random() < 0.8:
            ctx.ensures.append("result == %s" % N)
    elif ep in ("elem", "last"):
        if ep == "elem":
            post += ["  if (len(b) > 0) {", "    return b[0];", "  }", "  return 0;"]
        else:
            post.append("  return b[(len(b) - 1)];")
        if use_spec:
            if val == "mod":
                ctx.ensures.append("(0 <= result) && (result <= 6)")
            elif val == "dbl":
                ctx.ensures.append("result == 0" if ep == "elem" else "result == ((len(a) - 1) * 2)")
            elif ep == "elem":
                ctx.ensures.append("((len(a) > 0) ==> (result == (a[0] + %d)))" % c)
            else:
                ctx.ensures.append("result == (a[(len(a) - 1)] + %d)" % c)
    else:
        sums = rng.random() < 0.5
        invs2 = ["(0 <= j) && (j <= len(b))", "(0 <= t) && (t <= (6 * j))"]
        if sums:
            invs2.append("t == sum(k in 0..j: b[k])")
        # ensures 는 매개변수만 볼 수 있다(지역 b 금지): len(b) == N 이므로 N 으로 쓴다
        ctx.ensures.append("(0 <= result) && (result <= (6 * %s))" % N)
        p2 = {"cond": "(j < len(b))", "invs": invs2, "decr": "(len(b) - j)", "decr_bad": "len(b)",
              "body": ["t = (t + b[j]);"], "step": ["j = (j + 1);"]}
        loops.append(p2)
    extras = {"idx_off": idx_off("i", "b"), "cond_le_n": cond_lt_le}
    maybe_mutate(ctx, loops, extras, 0.3)
    lines = pre + loop_text(p1)
    if ep == "sum":
        lines += post
        lines += ["  let mut t: i64 = 0;", "  let mut j: i64 = 0;"] + loop_text(loops[1]) + ["  return t;"]
    else:
        lines += post
    return lines


# -- 1) 지역 배열: copy

def tmpl_copy(ctx):
    rng = ctx.rng
    ctx.effects = ["alloc"]
    declare2(ctx, [], True, [])
    if rng.random() < 0.88:
        ctx.requires.append("len(a) >= 1")
        set_arr(ctx, "a", minlen=1)
    mode = rng.choice(["set", "set", "zero"])
    if mode == "set" and rng.random() < 0.88:
        bound_elem(ctx, rng.choice([1000, 1000000]))
    pre = ["  let mut c: [i64] = copy(a);"]
    if rng.random() < 0.25:
        pre.append("  assert %s;" % ("(len(c) == len(a))" if rng.random() < 0.8 else "(len(c) > len(a))"))
    if mode == "set":
        V = rng.choice(["7", "len(a)", "(-3)", "0"])
        idx = "0" if rng.random() < 0.9 else "len(c)"
        pre.append("  c[%s] = %s;" % (idx, V))
        ctx.ensures.append("result == (%s + a[0])" % V)
        return pre + ["  return (c[0] + a[0]);"]
    invs = ["(0 <= i) && (i <= len(c))", "len(c) == len(a)"]
    if rng.random() < 0.9:
        invs.append("forall k in 0..i: (c[k] == 0)")
    p1 = {"cond": "(i < len(c))", "invs": invs, "decr": "(len(c) - i)", "decr_bad": "len(c)",
          "body": ["c[i] = 0;"], "step": ["i = (i + 1);"]}
    maybe_mutate(ctx, [p1], {"idx_off": idx_off("i", "c"), "cond_le_n": cond_lt_le}, 0.3)
    ctx.ensures.append("result == a[0]")
    return pre + ["  let mut i: i64 = 0;"] + loop_text(p1) + ["  return (c[0] + a[0]);"]


# -- 2) 효과와 평가 순서

def tmpl_effects(ctx):
    rng = ctx.rng
    use_arr = rng.random() < 0.75
    use_flag = rng.random() < 0.4
    use_x = rng.random() < 0.5
    has_a = rng.random() < 0.3
    if not (use_x or use_flag or has_a):
        use_x = True
    declare2(ctx, ["x"] if use_x else [], has_a, ["flag"] if use_flag else [])
    if use_x and rng.random() < 0.85:
        ctx.requires.append("(0 <= x) && (x <= 1000)")
        set_int(ctx, "x", lo=0, hi=1000)
    if rng.random() < 0.15:
        ctx.ret = "bool"
    ctx.effects = ["io", "alloc"] if use_arr else ["io"]
    N = rng.choice([2, 3, 4])
    H = {}
    for name in ("ia", "ib"):
        H[name] = [rng.choice(["const", "id"]), rng.randrange(N)]
    for name in ("va", "vb"):
        H[name] = [rng.choice(["const", "id"]), rng.randrange(10)]
    if rng.random() < 0.1:
        H[rng.choice(["ia", "ib"])][1] = N          # 근접 실패: 인덱스 도우미가 N 을 돌려준다
    weak = set()
    if rng.random() < 0.06:
        weak.add(rng.choice(["ia", "ib"]))          # ensures 없음: 호출쪽이 인덱스를 증명 못 함
    used = []
    uses = {"sub": False, "note": False}

    def call(name):
        if name not in used:
            used.append(name)
        kind, v = H[name]
        return "%s()" % name if kind == "const" else "%s(%d)" % (name, v)

    def IX():
        return call(rng.choice(["ia", "ib"]))

    def VA():
        return call(rng.choice(["va", "vb"]))

    L = []
    locs = []
    if use_arr:
        L.append("  let mut b: [i64] = alloc(%d, 0);" % N)
    opts = ["let_sum", "let_arg", "note", "print_i", "print_b"]
    if use_arr:
        opts += ["set1", "set1", "set2", "set2", "read_print", "let_read"]
    if use_flag:
        opts += ["if_flag", "print_flag"]
    if use_x:
        opts.append("print_x")
    for _ in range(rng.randint(2, 5)):
        o = rng.choice(opts)
        if o in ("set1", "set2") and "fz01" in AVOID:
            nm = "r%d" % len(locs)
            rhs = VA() if o == "set1" else "(%s + %s)" % (VA(), VA())
            L.append("  let %s: i64 = %s;" % (nm, rhs))
            locs.append(nm)
            L.append("  b[%s] = %s;" % (IX(), nm))
        elif o == "set1":
            L.append("  b[%s] = %s;" % (IX(), VA()))
        elif o == "set2":
            L.append("  b[%s] = (%s + %s);" % (IX(), VA(), VA()))
        elif o == "read_print":
            L.append("  print(b[%s]);" % IX())
        elif o == "let_read":
            nm = "r%d" % len(locs)
            L.append("  let %s: i64 = b[%s];" % (nm, IX()))
            locs.append(nm)
        elif o == "let_sum":
            nm = "r%d" % len(locs)
            L.append("  let %s: i64 = (%s + %s);" % (nm, VA(), VA()))
            locs.append(nm)
        elif o == "let_arg":
            nm = "r%d" % len(locs)
            uses["sub"] = True
            L.append("  let %s: i64 = sub(%s, %s);" % (nm, VA(), VA()))
            locs.append(nm)
        elif o == "note":
            uses["note"] = True
            if rng.random() < 0.6:
                L.append("  note(%s);" % VA())
            else:
                L.append("  note(%d);" % rng.randrange(10))
        elif o == "print_i":
            if rng.random() < 0.5:
                L.append("  print(%s);" % VA())
            else:
                L.append("  print((%s + 1));" % VA())
        elif o == "print_b":
            if rng.random() < 0.7:
                L.append("  print((%s > %d));" % (VA(), rng.randrange(10)))
            else:
                L.append("  print(%s);" % rng.choice(["true", "false"]))
        elif o == "print_flag":
            f = rng.random()
            if f < 0.4:
                L.append("  print(flag);")
            else:
                L.append("  print((flag %s (%s > 3)));" % ("==" if f < 0.7 else "!=", VA()))
        elif o == "print_x":
            L.append("  print(x);")
        else:  # if_flag
            L.append("  if flag {")
            L.append("    print(%d);" % rng.randrange(10))
            if use_arr and rng.random() < 0.6:
                if "fz01" in AVOID:
                    L.append("    b[%s] = %d;" % (IX(), rng.randrange(10)))
                else:
                    L.append("    b[%s] = %s;" % (IX(), VA()))
            L.append("  } else {")
            uses["note"] = True
            L.append("    note(%s);" % VA())
            L.append("  }")
    if ctx.ret == "bool":
        ch = ["va"]
        if use_flag:
            ch.append("flag")
        if locs:
            ch.append("loc")
        c = rng.choice(ch)
        if c == "va":
            ret = "(%s > 3)" % VA()
        elif c == "flag":
            ret = "(flag != (%s > 3))" % VA()
        else:
            ret = "(%s > 3)" % rng.choice(locs)
        L.append("  return %s;" % ret)
    else:
        ch = ["va"]
        if use_arr:
            ch += ["bix", "bsum"]
        if locs:
            ch.append("loc")
        if use_x:
            ch.append("x")
        c = rng.choice(ch)
        if c == "va":
            ret = VA()
        elif c == "bix":
            ret = "b[%s]" % IX()
        elif c == "bsum":
            ret = "(b[%s] + %s)" % (IX(), VA())
        elif c == "loc":
            ret = rng.choice(locs)
        else:
            ret = "(x + %s)" % VA()
        if use_flag and rng.random() < 0.3:
            L += ["  if flag {", "    return %s;" % ret, "  }", "  return %s;" % VA()]
        else:
            L.append("  return %s;" % ret)
        if rng.random() < 0.5:
            ctx.ensures.append("result >= 0")
        if rng.random() < 0.3:
            ctx.ensures.append("result <= 2000")
    texts = []
    for name in ("ia", "ib", "va", "vb"):
        if name not in used:
            continue
        kind, v = H[name]
        ident = "k" if kind == "id" else str(v)
        out = ["fn %s(%s) -> i64 ! io" % (name, "k: i64" if kind == "id" else "")]
        if name not in weak:
            out.append("  ensures result == %s" % ident)
        out += ["{", "  print(%s);" % (ident if kind == "id" else rng.choice([1, 2, 3, 5, 8, 13, 21]))]
        if rng.random() < 0.2:
            out.append("  print(%s);" % ("(k > 2)" if kind == "id" else rng.choice(["true", "false"])))
        out += ["  return %s;" % ident, "}"]
        texts.append("\n".join(out))
    if uses["sub"]:
        texts.append("\n".join(["fn sub(p: i64, q: i64) -> i64", "  requires (0 <= p) && (p <= 100)",
                                "  requires (0 <= q) && (q <= 100)", "  ensures result == (p - q)",
                                "{", "  return (p - q);", "}"]))
    if uses["note"]:
        texts.append("\n".join(["fn note(k: i64) -> () ! io", "{", "  print(k);", "}"]))
    rng.shuffle(texts)
    ctx.helper = "\n\n".join(texts) if texts else None
    ctx.after = rng.random() < 0.3
    return L


# -- 3,5,6) assert / else if / 중첩 if / 블록 지역 / bool

def tmpl_branches(ctx):
    rng = ctx.rng
    bools = ["flag", "flag2"][:rng.choice([1, 1, 2])]
    use_arr = rng.random() < 0.2
    declare2(ctx, ["x"], use_arr, bools)
    if rng.random() < 0.88:
        ctx.requires.append("(0 <= x) && (x <= 1000)")
        set_int(ctx, "x", lo=0, hi=1000)
    ctx.ret = "bool" if rng.random() < 0.25 else "i64"
    vals = ["x", "(x + 1)", "(x * 2)", "(x / 2)", "(x % 7)", "(1000 - x)", "0", "1", "7"]
    if use_arr:
        vals.append("len(a)")
    lines = []
    has_big = rng.random() < 0.7
    if has_big:
        lines.append("  let big: bool = (x > 100);")
    if rng.random() < 0.5:
        lines.append("  let base: i64 = (x % 10);")
        vals.append("base")
    conds = ["(x > 10)", "((x % 2) == 0)", "(x < 500)"]
    for b in bools:
        conds += [b, "(!%s)" % b, "(%s || (x < 5))" % b, "(%s != false)" % b]
        if has_big:
            conds += ["(%s == big)" % b, "(%s && big)" % b]
    if has_big:
        conds += ["big", "(big == true)"]
    names = ["t", "u", "w"]

    def V(scope):
        return rng.choice(vals + scope)

    def stmts(depth, used):
        out = []
        scope = list(used)
        if rng.random() < 0.45:
            nm = [n for n in names if n not in used][0]
            out.append("let %s: i64 = %s;" % (nm, V(scope)))
            scope.append(nm)
        if depth > 0 and rng.random() < 0.6:
            out.append("if %s {" % rng.choice(conds))
            out += ["  " + s for s in stmts(depth - 1, scope)]
            for _ in range(rng.choice([0, 1, 2])):
                out.append("} else if %s {" % rng.choice(conds))
                out += ["  " + s for s in stmts(depth - 1, scope)]
            if rng.random() < 0.8:
                out.append("} else {")
                out += ["  " + s for s in stmts(depth - 1, scope)]
            out.append("}")
        elif rng.random() < 0.5:
            out.append("r = %s;" % V(scope))
        else:
            out.append("r = (%s + %s);" % (V(scope), V(scope)))
        return out

    lines.append("  let mut r: i64 = 0;")
    lines += ["  " + s for s in stmts(2, [])]
    if rng.random() < 0.55:
        tr = ["(r >= 0)", "(r <= 5000)", "((r + 1) > r)", "(%s || (!%s))" % (bools[0], bools[0])]
        fl = ["(r > 0)", "(r < 1000)", "(r == x)", "(r != 0)"]
        if has_big:
            tr.append("(big || (x <= 100))")
            fl.append("(big && %s)" % bools[0])
        lines.append("  assert %s;" % rng.choice(tr if rng.random() < 0.85 else fl))
    if ctx.ret == "bool":
        lines.append("  return %s;" % rng.choice(["(r > 10)", "(r >= x)", "(%s == (r > x))" % bools[0],
                                                 "(%s != (r > 10))" % bools[-1]]))
        if rng.random() < 0.5:
            ctx.ensures.append("(result || (!result))")
    else:
        if rng.random() < 0.3:
            lines += ["  if %s {" % rng.choice(conds), "    return %s;" % rng.choice(vals), "  }"]
        lines.append("  return %s;" % rng.choice(["r", "r", "(r + 1)"]))
        if rng.random() < 0.6:
            ctx.ensures.append("result >= 0")
        if rng.random() < 0.3:
            ctx.ensures.append("result <= 8000")
    return lines


# -- 4) 중첩 반복 / 연속 반복

def tmpl_nested(ctx):
    rng = ctx.rng
    v = rng.choice(["pairs", "tri", "arrpairs", "seq"])
    if v == "seq":
        declare2(ctx, ["n"], False, [])
        set_int(ctx, "n", cap=3000)
        if rng.random() < 0.9:
            ctx.requires.append("(0 <= n) && (n <= 1000)")
            set_int(ctx, "n", lo=0, hi=1000)
        p1 = {"cond": "(i < n)", "invs": ["(0 <= i) && (i <= n)", "s == (2 * i)"], "decr": "(n - i)",
              "decr_bad": "n", "body": ["s = (s + 2);"], "step": ["i = (i + 1);"]}
        p2 = {"cond": "(m > 0)", "invs": ["(0 <= m) && (m <= n)", "t == (3 * (n - m))"], "decr": "m",
              "decr_bad": "n", "body": ["t = (t + 3);"], "step": ["m = (m - 1);"]}
        maybe_mutate(ctx, [p1, p2], {"cond_le_n": cond_lt_le}, 0.3)
        lines = ["  let mut s: i64 = 0;", "  let mut i: i64 = 0;"] + loop_text(p1)
        if rng.random() < 0.4:
            lines.append("  assert %s;" % ("(s == (2 * n))" if rng.random() < 0.8 else "(s > n)"))
        lines += ["  let mut t: i64 = 0;", "  let mut m: i64 = n;"] + loop_text(p2)
        if rng.random() < 0.3:
            lines.append("  assert (t == (3 * n));")
        ctx.ensures.append("result == (5 * n)")
        return lines + ["  return (s + t);"]
    pre = ["  let mut c: i64 = 0;", "  let mut i: i64 = 0;"]
    if v == "arrpairs":
        declare2(ctx, [], True, [])
        set_arr(ctx, "a", maxlen=8)
        if rng.random() < 0.92:
            ctx.requires.append("len(a) <= 8")
        inner = {"cond": "(j < len(a))", "invs": ["(0 <= j) && (j <= len(a))", "(0 <= c) && (c <= ((8 * i) + j))"],
                 "decr": "(len(a) - j)", "decr_bad": "len(a)",
                 "body": ["if (a[i] == a[j]) {", "  c = (c + 1);", "}"]}
        outer = {"cond": "(i < len(a))", "invs": ["(0 <= i) && (i <= len(a))", "(0 <= c) && (c <= (8 * i))"],
                 "decr": "(len(a) - i)", "decr_bad": "len(a)"}
        ctx.ensures.append("(0 <= result) && (result <= 64)")
        ret = "c"
    else:
        declare2(ctx, ["n"], False, [])
        set_int(ctx, "n", cap=100)
        if rng.random() < 0.92:
            ctx.requires.append("(0 <= n) && (n <= 100)")
            set_int(ctx, "n", lo=0, hi=100)
        if v == "pairs":
            body = ["c = (c + 1);"] if rng.random() < 0.5 else ["if (j < i) {", "  c = (c + 1);", "}"]
            inner = {"cond": "(j < n)", "invs": ["(0 <= j) && (j <= n)", "(0 <= c) && (c <= ((100 * i) + j))"],
                     "decr": "(n - j)", "decr_bad": "n", "body": body}
            outer = {"cond": "(i < n)", "invs": ["(0 <= i) && (i <= n)", "(0 <= c) && (c <= (100 * i))"],
                     "decr": "(n - i)", "decr_bad": "n"}
            ctx.ensures.append("(0 <= result) && (result <= %d)" % (9999 if rng.random() < 0.1 else 10000))
            ret = "c"
        else:
            pre = ["  let mut s: i64 = 0;", "  let mut i: i64 = 0;"]
            inner = {"cond": "(j < i)", "invs": ["(0 <= j) && (j <= i)", "(0 <= s) && (s <= ((10000 * i) + (100 * j)))"],
                     "decr": "(i - j)", "decr_bad": "i", "body": ["s = (s + j);"]}
            outer = {"cond": "(i < n)", "invs": ["(0 <= i) && (i <= n)", "(0 <= s) && (s <= (10000 * i))"],
                     "decr": "(n - i)", "decr_bad": "n"}
            ctx.ensures.append("(0 <= result) && (result <= 1000000)")
            ret = "s"
    inner["step"] = ["j = (j + 1);"]
    outer["step"] = ["i = (i + 1);"]
    if rng.random() < 0.15:
        mutate(ctx, inner, {"cond_le_n": cond_lt_le})
    outer["body"] = ["let mut j: i64 = 0;"] + loop_text(inner, "")
    if rng.random() < 0.12:
        mutate(ctx, outer, {"cond_le_n": cond_lt_le})
    return pre + loop_text(outer) + ["  return %s;" % ret]


# -- 7) exists / forall / min / max / ==> 를 쓰는 ensures

def tmpl_quant(ctx):
    rng = ctx.rng
    v = rng.choice(["flag", "flag", "minmax", "minmax", "impl"])
    if v == "flag":
        declare2(ctx, ["x"], True, [])
        ctx.ret = "bool"
        if rng.random() < 0.5:
            ctx.hints["pick"].append(["x", "a"])
        P = rng.choice(["(a[%s] == x)", "(a[%s] > x)", "(a[%s] >= 0)", "(a[%s] != x)"])
        Pk, Pi = P % "k", P % "i"
        if rng.random() < 0.5:
            var, init, q = "found", "false", "exists k in 0..%s: " + Pk
            body = ["if %s {" % Pi, "  found = true;", "}"] if rng.random() < 0.5 else ["found = (found || %s);" % Pi]
            wrong = ["found = %s;" % Pi]
            extra = ["(result ==> (len(a) > 0))", "((!result) ==> (forall k in 0..len(a): (!%s)))" % Pk]
        else:
            var, init, q = "ok", "true", "forall k in 0..%s: " + Pk
            body = ["if (!%s) {" % Pi, "  ok = false;", "}"] if rng.random() < 0.5 else ["ok = (ok && %s);" % Pi]
            wrong = ["ok = %s;" % Pi]
            extra = ["((len(a) == 0) ==> result)", "((!result) ==> (exists k in 0..len(a): (!%s)))" % Pk]
        ctx.ensures.append("result == (%s)" % (q % "len(a)"))
        if rng.random() < 0.35:
            ctx.ensures.append(rng.choice(extra))
        p1 = {"cond": "(i < len(a))",
              "invs": ["(0 <= i) && (i <= len(a))", "%s == (%s)" % (var, q % "i")],
              "decr": "(len(a) - i)", "decr_bad": "len(a)", "body": body, "step": ["i = (i + 1);"]}
        maybe_mutate(ctx, [p1], {"overwrite": lambda p: p.__setitem__("body", wrong)}, 0.3)
        return (["  let mut %s: bool = %s;" % (var, init), "  let mut i: i64 = 0;"] + loop_text(p1)
                + ["  return %s;" % var])
    if v == "minmax":
        declare2(ctx, [], True, [])
        if rng.random() < 0.92:
            ctx.requires.append("len(a) >= 1")
            set_arr(ctx, "a", minlen=1)
        fn = rng.choice(["max", "min"])
        cmp_, le, ge = (">", "<=", ">=") if fn == "max" else ("<", ">=", "<=")
        if rng.random() < 0.5:
            inv2 = "m == %s(k in 0..i: a[k])" % fn
            ctx.ensures.append("result == %s(k in 0..len(a): a[k])" % fn)
            if rng.random() < 0.4:
                ctx.ensures.append("(result %s a[0])" % ge)
            if rng.random() < 0.4:
                ctx.ensures.append("((len(a) >= 2) ==> (result %s a[1]))" % ge)
        else:
            inv2 = "(forall k in 0..i: (a[k] %s m)) && (exists k in 0..i: (a[k] == m))" % le
            ctx.ensures.append("(forall k in 0..len(a): (a[k] %s result))" % le)
            ctx.ensures.append("(exists k in 0..len(a): (a[k] == result))")
        flip = "<" if cmp_ == ">" else ">"
        p1 = {"cond": "(i < len(a))", "invs": ["(1 <= i) && (i <= len(a))", inv2],
              "decr": "(len(a) - i)", "decr_bad": "len(a)",
              "body": ["if (a[i] %s m) {" % cmp_, "  m = a[i];", "}"], "step": ["i = (i + 1);"]}
        maybe_mutate(ctx, [p1], {"cmp_flip": lambda p: p.__setitem__(
            "body", ["if (a[i] %s m) {" % flip, "  m = a[i];", "}"])}, 0.3)
        return ["  let mut m: i64 = a[0];", "  let mut i: i64 = 1;"] + loop_text(p1) + ["  return m;"]
    declare2(ctx, ["x"], False, ["flag"])
    if rng.random() < 0.9:
        ctx.requires.append("((-1000) <= x) && (x <= 1000)")
        set_int(ctx, "x", lo=-1000, hi=1000)
    ctx.ensures.append("(flag ==> (result == %s))" % ("(x + 1)" if rng.random() < 0.1 else "x"))
    ctx.ensures.append("((!flag) ==> (result == (0 - x)))")
    if rng.random() < 0.5:
        ctx.ensures.append(rng.choice(["exists k in (-1)..2: (result == (k * x))",
                                       "forall k in 0..2: (result >= (-1000))"]))
    return ["  if flag {", "    return x;", "  }", "  return (-x);"]


# -- 8) 반복문 있는 보조 함수 + 그것을 부르는 두 번째 보조 함수 (앞방향 호출 포함)

def tmpl_helpers(ctx):
    rng = ctx.rng
    alloc = rng.random() < 0.3
    C = rng.choice([2, 3, 5])
    B = 100 if alloc else 1000
    flag = rng.random() < 0.4
    declare2(ctx, ["n"], False, ["flag"] if flag else [])
    set_int(ctx, "n", cap=B)
    req = "(0 <= n) && (n <= %d)" % B
    if rng.random() < 0.92:
        ctx.requires.append(req)
        set_int(ctx, "n", lo=0, hi=B)
    eff = " ! alloc" if alloc else ""
    if alloc:
        p1 = {"cond": "(i < n)", "invs": ["(0 <= i) && (i <= n)", "len(b) == n", "forall k in 0..i: (b[k] == %d)" % C],
              "decr": "(n - i)", "decr_bad": "n", "body": ["b[i] = %d;" % C], "step": ["i = (i + 1);"]}
        p2 = {"cond": "(j < len(b))", "invs": ["(0 <= j) && (j <= len(b))", "s == (%d * j)" % C],
              "decr": "(len(b) - j)", "decr_bad": "len(b)", "body": ["s = (s + b[j]);"], "step": ["j = (j + 1);"]}
        loops = [p1, p2]
    else:
        p1 = {"cond": "(i < n)", "invs": ["(0 <= i) && (i <= n)", "s == (%d * i)" % C],
              "decr": "(n - i)", "decr_bad": "n", "body": ["s = (s + %d);" % C], "step": ["i = (i + 1);"]}
        loops = [p1]
    maybe_mutate(ctx, loops, {"idx_off": idx_off("i", "b"), "cond_le_n": cond_lt_le}, 0.25)
    if alloc:
        lp_body = (["  let mut b: [i64] = alloc(n, 0);", "  let mut i: i64 = 0;"] + loop_text(p1)
                   + ["  let mut s: i64 = 0;", "  let mut j: i64 = 0;"] + loop_text(p2) + ["  return s;"])
    else:
        lp_body = ["  let mut s: i64 = 0;", "  let mut i: i64 = 0;"] + loop_text(p1) + ["  return s;"]
    lp_ens = "result == (%d * n)" % (C if rng.random() >= 0.08 else C + 1)
    lp = "\n".join(["fn lp(n: i64) -> i64" + eff, "  requires " + req, "  ensures " + lp_ens, "{"]
                   + lp_body + ["}"])
    if rng.random() < 0.5:
        lp2_body = ["  return (lp(n) + lp(n));"]
    else:
        lp2_body = ["  let r1: i64 = lp(n);", "  let r2: i64 = lp(n);", "  return (r1 + r2);"]
    lp2 = "\n".join(["fn lp2(n: i64) -> i64" + eff, "  requires " + req, "  ensures result == (%d * n)" % (2 * C),
                     "{"] + lp2_body + ["}"])
    arg = rng.choices(["n", "(n / 2)", "(n % 10)", "(n + 1)"], weights=[3, 2, 2, 1])[0]
    if flag:
        ctx.ensures.append("(flag ==> (result == (%d * %s)))" % (2 * C, arg))
        ctx.ensures.append("((!flag) ==> (result == (%d * %s)))" % (C, arg))
        body = ["  if flag {", "    return lp2(%s);" % arg, "  }", "  return lp(%s);" % arg]
    else:
        ctx.ensures.append("result == (%d * %s)" % (2 * C, arg))
        body = ["  return lp2(%s);" % arg]
    if alloc:
        ctx.effects = ["alloc"]
    texts = [lp2, lp] if rng.random() < 0.5 else [lp, lp2]
    ctx.helper = "\n\n".join(texts)
    ctx.after = rng.random() < 0.4
    return body


# ---------------------------------------------------------------- 새 계열 2: 배열 2개 / 배열 반환 /
# Option·Result 반환·매개변수 / 구조체·열거형. params 타입: "i64"|"bool"|"array"|"Option<i64>"|"Result<i64>"

def declare_list(ctx, params, shuffle=True):
    """매개변수 목록 [[이름, 타입], ...] 을 설정한다. 배열 이름은 a, b."""
    params = [list(p) for p in params]
    if shuffle and ctx.rng.random() < 0.5:
        ctx.rng.shuffle(params)
    ctx.params = params
    ctx.ints = [n for n, t in params if t == "i64"]
    ctx.arr = "a" if any(n == "a" and t == "array" for n, t in params) else None
    for n, t in params:
        if t == "array":
            hint_arr(ctx, n)
        elif t != "bool":
            hint_int(ctx, n)      # 구조체·열거형 인자도 같은 힌트를 쓴다(안의 i64 필드 모두에 적용)


def bnd(ctx, name, B):
    ctx.requires.append("(%s <= %s) && (%s <= %d)" % (lit(-B), name, name, B))
    set_int(ctx, name, lo=-B, hi=B)


def elem_bound(ctx, arr, B):
    ctx.requires.append("forall k in 0..len(%s): ((%s <= %s[k]) && (%s[k] <= %d))" % (arr, lit(-B), arr, arr, B))
    set_arr(ctx, arr, elem=(-B, B))


def maybe_bad_ensures(ctx, p=0.08):
    """마지막 `result == E` ensures 를 `result == (E + 1)` 로 어긋나게 한다 (거절돼야 함)."""
    if ctx.ensures and ctx.rng.random() < p and ctx.ensures[-1].startswith("result == "):
        ctx.ensures[-1] = "result == (%s + 1)" % ctx.ensures[-1][len("result == "):]


# -- 1) 배열 매개변수 2개

def tmpl_twoarr(ctx):
    rng = ctx.rng
    v = rng.choice(["elem", "elem", "short", "dot", "dot", "cmp", "cmp"])
    declare_list(ctx, [["a", "array"], ["b", "array"]])
    ctx.hints["samelen"] = [["a", "b"]]
    op = rng.choice(["+", "-"])
    lenreq = None
    if v in ("elem", "dot"):
        lenreq = "len(a) == len(b)"
    elif v == "cmp":
        lenreq = rng.choice(["len(a) == len(b)", "len(a) == len(b)", "len(a) <= len(b)"])
    if lenreq and rng.random() < 0.82:       # 가끔 길이 조건을 뺀다: 거절돼야 함
        ctx.requires.append(lenreq)
    if v == "dot":
        B = rng.choice([10, 1000, 30000])
    else:
        B = rng.choice([1000, 1000000])
    if v in ("elem", "short", "dot") and rng.random() < 0.93:
        elem_bound(ctx, "a", B)
        elem_bound(ctx, "b", B)
    extras = {"cond_le_n": cond_lt_le}
    if v in ("elem", "short"):
        ctx.ret = "[i64]"
        ctx.effects = ["alloc"]
        spec = "(r[k] == (a[k] %s b[k]))" % op
        if v == "elem":
            n = "len(a)"
            pre = ["  let mut r: [i64] = alloc(len(a), 0);", "  let mut i: i64 = 0;"]
            head = "len(result) == len(a)"
        else:
            n = "n"
            pre = ["  let mut n: i64 = len(a);", "  if (len(b) < n) {", "    n = len(b);", "  }",
                   "  let mut r: [i64] = alloc(n, 0);", "  let mut i: i64 = 0;"]
            head = "(len(result) <= len(a)) && (len(result) <= len(b))"
        invs = ["(0 <= i) && (i <= %s)" % n, "len(r) == %s" % n]
        if rng.random() < 0.92:
            invs.append("forall k in 0..i: " + spec)
        fa = "forall k in 0..len(result): (result[k] == (a[k] %s b[k]))" % op
        if rng.random() < 0.2:
            ctx.ensures += [head, fa]
        else:
            ctx.ensures.append("(%s) && (%s)" % (head, fa))
        other = "-" if op == "+" else "+"
        extras["idx_off"] = idx_off("i", "r")
        extras["op_swap"] = lambda p: p.__setitem__(
            "body", [s.replace(" %s " % op, " %s " % other) for s in p["body"]])
        parts = {"cond": "(i < %s)" % n, "invs": invs, "decr": "(%s - i)" % n, "decr_bad": n,
                 "body": ["r[i] = (a[i] %s b[i]);" % op], "step": ["i = (i + 1);"]}
        return finish_template(ctx, pre, parts, ["  return r;"], extras)
    if v == "dot":
        if rng.random() < 0.9:
            ctx.requires.append("len(a) <= 1000")
        X = B * B
        invs = ["(0 <= i) && (i <= len(a))", "(s >= (%s * i)) && (s <= (%d * i))" % (lit(-X), X)]
        if rng.random() < 0.6:
            invs.append("s == sum(k in 0..i: (a[k] * b[k]))")
            ctx.ensures.append("result == sum(k in 0..len(a): (a[k] * b[k]))")
        if rng.random() < 0.4:
            ctx.ensures.append("(result <= (%d * len(a)))" % X)
        parts = {"cond": "(i < len(a))", "invs": invs, "decr": "(len(a) - i)", "decr_bad": "len(a)",
                 "body": ["s = (s + (a[i] * b[i]));"], "step": ["i = (i + 1);"]}
        return finish_template(ctx, ["  let mut s: i64 = 0;", "  let mut i: i64 = 0;"], parts, ["  return s;"], extras)
    rel = rng.choice(["<", "==", ">"])
    invs = ["(0 <= i) && (i <= len(a))", "c == count(k in 0..i: (a[k] %s b[k]))" % rel, "(0 <= c) && (c <= i)"]
    if rng.random() < 0.85:
        ctx.ensures.append("result == count(k in 0..len(a): (a[k] %s b[k]))" % rel)
    if rng.random() < 0.4:
        ctx.ensures.append("(0 <= result) && (result <= len(a))")
    extras["cmp_swap"] = lambda p: p.__setitem__("body", ["if (a[i] <= b[i]) {", "  c = (c + 1);", "}"])
    parts = {"cond": "(i < len(a))", "invs": invs, "decr": "(len(a) - i)", "decr_bad": "len(a)",
             "body": ["if (a[i] %s b[i]) {" % rel, "  c = (c + 1);", "}"], "step": ["i = (i + 1);"]}
    return finish_template(ctx, ["  let mut c: i64 = 0;", "  let mut i: i64 = 0;"], parts, ["  return c;"], extras)


# -- 2) 배열 반환 `-> [i64] ! alloc`

G_ALLOC = "\n".join(["fn g(b: [i64]) -> [i64] ! alloc", "  ensures len(result) == len(b)", "{",
                     "  return alloc(len(b), 0);", "}"])
G_COPY = "\n".join(["fn g(b: [i64]) -> [i64] ! alloc",
                    "  ensures (len(result) == len(b)) && (forall k in 0..len(b): (result[k] == b[k]))", "{",
                    "  return copy(b);", "}"])


def tmpl_arrret(ctx):
    rng = ctx.rng
    ctx.ret = "[i64]"
    ctx.effects = ["alloc"]
    use_c = rng.random() < 0.5
    declare_list(ctx, [["a", "array"]] + ([["c", "i64"]] if use_c else []))
    C = "c" if use_c else lit(rng.choice([1, 2, 5, -3, 0]))
    B = rng.choice([1000, 1000000])
    if rng.random() < 0.93:
        elem_bound(ctx, "a", B)
    if use_c and rng.random() < 0.93:
        bnd(ctx, "c", B)
    pre = ["  let mut b: [i64] = %s;" % rng.choice(["copy(a)", "copy(a)", "alloc(len(a), 0)"])]
    if rng.random() < 0.2:
        pre.append("  assert (len(b) == len(a));")
    mode = rng.choice(["none", "none", "pre_copy", "pre_alloc", "pre_helper", "in_copy", "in_helper"])
    body = ["b[i] = (a[i] + %s);" % C]
    if mode == "pre_copy":
        pre.append("  b = copy(b);")
    elif mode == "pre_alloc":
        pre.append("  b = alloc(len(a), %s);" % lit(rng.choice([0, 1, -1, 7])))
    elif mode == "pre_helper":
        pre.append("  b = g(b);")
        ctx.helper, ctx.after = G_ALLOC, rng.random() < 0.4
    elif mode == "in_copy":
        body.append("b = copy(b);")
    elif mode == "in_helper":
        body.append("b = g(b);")
        ctx.helper, ctx.after = G_COPY, rng.random() < 0.4
    pre.append("  let mut i: i64 = 0;")
    invs = ["(0 <= i) && (i <= len(a))", "len(b) == len(a)"]
    if rng.random() < 0.95:
        invs.append("forall k in 0..i: (b[k] == (a[k] + %s))" % C)
    fa = "forall k in 0..len(result): (result[k] == (a[k] + %s))" % C
    if rng.random() < 0.2:
        ctx.ensures += ["len(result) == len(a)", fa]
    else:
        ctx.ensures.append("(len(result) == len(a)) && (%s)" % fa)
    parts = {"cond": "(i < len(a))", "invs": invs, "decr": "(len(a) - i)", "decr_bad": "len(a)",
             "body": body, "step": ["i = (i + 1);"]}
    extras = {"idx_off": idx_off("i", "b"), "cond_le_n": cond_lt_le,
              "val_off": lambda p: p.__setitem__("body", ["b[i] = ((a[i] + %s) + 1);" % C] + p["body"][1:])}
    return finish_template(ctx, pre, parts, ["  return b;"], extras)


# -- 3) Option / Result 반환

# 평가 순서·단일 평가를 io 출력으로 관측하는 보조 함수 (이름 tap 은 다른 보조 함수와 겹치지 않는다)
TAP_FN = "\n".join(["fn tap(v: i64) -> i64 ! io", "  ensures result == v", "{", "  print(v);", "  return v;", "}"])


def tmpl_option_tap(ctx, res):
    """Some(..)/Ok(..) 인자, match 대상 식, 호출 인자에 tap(io)을 넣어 평가 순서·단일 평가를 관측한다."""
    rng = ctx.rng
    B = rng.choice([1000, 100000])
    declare_list(ctx, [["x", "i64"]])
    bnd(ctx, "x", B)
    ctx.effects = ["io"]
    ctx.ret = "i64"
    T = "Result<i64>" if res else "Option<i64>"
    mk = (lambda e: "Ok(%s)" % e) if res else (lambda e: "Some(%s)" % e)
    arm_s = "Ok(w)" if res else "Some(w)"
    arm_n, none_v = ("Err(c)", "c") if res else ("None", "0")
    v = rng.choice(["match", "match", "arg", "two"])
    helper = [TAP_FN]
    if v == "match":        # match g(tap(x)) {..}: tap 은 정확히 한 번만 평가돼야 한다
        g = ["fn g(v: i64) -> %s" % T]
        if res:
            g += ["  ensures (v > 0) ==> (is_ok(result) && (ok_val(result) == v))",
                  "  ensures (v <= 0) ==> ((!is_ok(result)) && (err_val(result) == 4))", "{",
                  "  if (v > 0) {", "    return Ok(v);", "  }", "  return Err(4);", "}"]
        else:
            g += ["  ensures (v > 0) ==> (is_some(result) && (some_val(result) == v))",
                  "  ensures (v <= 0) ==> (!is_some(result))", "{",
                  "  if (v > 0) {", "    return Some(v);", "  }", "  return None;", "}"]
        helper.append("\n".join(g))
        ctx.ensures += ["((x > 0) ==> (result == (x + 1)))", "((x <= 0) ==> (result == %s))" % ("4" if res else "0")]
        body = ["  match g(tap(x)) {", "    %s => { return (w + 1); }" % arm_s, "    %s => { return %s; }" % (arm_n, none_v), "  }"]
    elif v == "arg":        # 호출 인자 안의 Some(tap(x))
        h = ["fn h(o: %s) -> i64" % T,      # w + 1 이 넘치지 않게 경계를 둔다(없으면 늘 거절)
             "  requires %s(o) ==> (%s(o) <= 1000000)" % (("is_ok", "ok_val") if res else ("is_some", "some_val"))]
        if res:
            h += ["  ensures is_ok(o) ==> (result == (ok_val(o) + 1))", "  ensures (!is_ok(o)) ==> (result == err_val(o))"]
        else:
            h += ["  ensures is_some(o) ==> (result == (some_val(o) + 1))", "  ensures (!is_some(o)) ==> (result == 0)"]
        h += ["{", "  match o {", "    %s => { return (w + 1); }" % arm_s, "    %s => { return %s; }" % (arm_n, none_v), "  }", "}"]
        helper.append("\n".join(h))
        ctx.ensures.append("result == (x + 1)")
        if rng.random() < 0.5:
            body = ["  return h(%s);" % mk("tap(x)")]
        else:
            body = ["  let o: %s = %s;" % (T, mk("tap(x)")), "  return h(o);"]
    else:                   # 한 생성자 안의 두 tap: 왼쪽부터
        ctx.ensures.append("result == (x + 2)")
        arm = "Ok(w)" if res else "Some(w)"
        body = ["  let o: %s = %s;" % (T, mk("(tap(x) + tap(2))")), "  match o {", "    %s => { return w; }" % arm,
                "    %s => { return %s; }" % (arm_n, none_v), "  }"]
    ctx.helper = "\n\n".join(helper)
    ctx.after = rng.random() < 0.4
    return body


def tmpl_option(ctx):
    rng = ctx.rng
    if rng.random() < 0.25:
        return tmpl_option_tap(ctx, rng.random() < 0.45)
    v = rng.choice(["find", "find", "div", "div", "mfind", "mdiv"])
    res = rng.random() < 0.45
    is_, val = ("is_ok", "ok_val") if res else ("is_some", "some_val")
    if v in ("find", "mfind"):
        declare_list(ctx, [["a", "array"], ["x", "i64"]])
        if rng.random() < 0.6:
            ctx.hints["pick"].append(["x", "a"])
    else:
        declare_list(ctx, [["x", "i64"], ["y", "i64"]])
        ctx.hints["div"].append("y")
        ctx.hints["neg"] += ["x", "y"]
    if v == "find":
        ctx.ret = "Result<i64>" if res else "Option<i64>"
        code = rng.choice([1, 2, 7])
        found, miss = ("Ok(i)", "Err(%d)" % code) if res else ("Some(i)", "None")
        invs = ["(0 <= i) && (i <= len(a))"]
        if rng.random() < 0.9:
            invs.append("forall k in 0..i: (a[k] != x)")
        if rng.random() < 0.08:
            ctx.ensures.append("(%s(result) || (%s(result) >= 0))" % (is_, val))   # 무방비 *_val: 거절돼야 함
        else:
            ctx.ensures.append("(%s(result) ==> ((0 <= %s(result)) && (%s(result) < len(a)) && (a[%s(result)] == x)))"
                               % (is_, val, val, val))
        none_c = "(forall k in 0..len(a): (a[k] != x))"
        if res:
            ctx.ensures.append("((!is_ok(result)) ==> ((err_val(result) == %d) && %s))" % (code, none_c))
        elif rng.random() < 0.9:
            ctx.ensures.append("((!is_some(result)) ==> %s)" % none_c)
        parts = {"cond": "(i < len(a))", "invs": invs, "decr": "(len(a) - i)", "decr_bad": "len(a)",
                 "body": ["if (a[i] == x) {", "  return %s;" % found, "}"], "step": ["i = (i + 1);"]}
        extras = {"ret_off": lambda p: p.__setitem__(
            "body", ["if (a[i] == x) {", "  return %s;" % found.replace("(i)", "((i + 1))"), "}"])}
        return finish_template(ctx, ["  let mut i: i64 = 0;"], parts, ["  return %s;" % miss], extras)
    if v == "div":
        ctx.ret = "Result<i64>" if res else "Option<i64>"
        nonneg = rng.random() < 0.4
        if nonneg:
            ctx.requires.append("0 <= x")
            set_int(ctx, "x", lo=0)
        bad1, bad2 = ("Err(1)", "Err(2)") if res else ("None", "None")
        L = []
        if rng.random() >= 0.1:              # 가끔 y 검사를 뺀다: 거절돼야 함
            L += ["  if (y <= 0) {", "    return %s;" % bad1, "  }"]
        if not nonneg:
            L += ["  if (x < 0) {", "    return %s;" % bad2, "  }"]
        L.append("  return %s;" % ("Ok((x / y))" if res else "Some((x / y))"))
        if rng.random() < 0.08:
            ctx.ensures.append("(%s(result) || (%s(result) >= 0))" % (is_, val))   # 무방비 *_val: 거절돼야 함
        else:
            ctx.ensures.append("(%s(result) ==> ((y > 0) && (%s(result) == (x / y))))" % (is_, val))
        if res:
            if nonneg and rng.random() < 0.9:
                ctx.ensures.append("((!is_ok(result)) ==> (err_val(result) == 1))")
            else:
                ctx.ensures.append("((!is_ok(result)) ==> ((err_val(result) == 1) || (err_val(result) == 2)))")
        else:
            ctx.ensures.append("((!is_some(result)) ==> ((y <= 0)%s))" % ("" if nonneg else " || (x < 0)"))
        return L
    # 보조 함수가 Option/Result 를 돌려주고 f 가 match 로 푼다
    if v == "mfind":
        found, miss = ("Ok(i)", "Err(3)") if res else ("Some(i)", "None")
        gp = {"cond": "(i < len(a))", "invs": ["(0 <= i) && (i <= len(a))"], "decr": "(len(a) - i)",
              "body": ["if (a[i] == x) {", "  return %s;" % found, "}"], "step": ["i = (i + 1);"]}
        g = ["fn g(a: [i64], x: i64) -> %s" % ("Result<i64>" if res else "Option<i64>"),
             "  ensures %s(result) ==> ((0 <= %s(result)) && (%s(result) < len(a)))"
             % (is_, val, val) if rng.random() >= 0.08 else
             "  ensures %s(result) ==> (%s(result) >= 0)" % (is_, val), "{", "  let mut i: i64 = 0;"]
        g += loop_text(gp) + ["  return %s;" % miss, "}"]
        call = "g(a, x)"
        some_e = rng.choice(["v", "v", "(v + 1)"])
        none_e = rng.choice(["(-1)", "0", "(-5)"])
        ctx.ensures.append("(result >= (-5)) && (result <= len(a))")
    else:
        g = ["fn g(x: i64, y: i64) -> %s" % ("Result<i64>" if res else "Option<i64>"),
             "  ensures %s(result) ==> (%s(result) >= 0)" % (is_, val)]
        if res:
            g.append("  ensures (!is_ok(result)) ==> ((err_val(result) >= 1) && (err_val(result) <= 2))")
        bad1, bad2 = ("Err(1)", "Err(2)") if res else ("None", "None")
        g += ["{", "  if (y <= 0) {", "    return %s;" % bad1, "  }", "  if (x < 0) {", "    return %s;" % bad2, "  }",
              "  return %s;" % ("Ok((x / y))" if res else "Some((x / y))"), "}"]
        call = "g(x, y)"
        some_e = "v"
        none_e = rng.choice(["c", "(0 - c)", "c"]) if res else "0"
        ctx.ensures.append("result >= 0" if none_e != "(0 - c)" else "result >= (-2)")
    ctx.ret = "i64"
    ctx.helper = "\n".join(g)
    ctx.after = rng.random() < 0.4
    arm_some = "Ok(v)" if res else "Some(v)"
    arm_none = "Err(c)" if res else "None"
    style = rng.choice(["direct", "let", "assign"])
    lines = []
    scrut = call
    if style == "let":
        lines.append("  let o: %s = %s;" % ("Result<i64>" if res else "Option<i64>", call))
        scrut = "o"
    if style == "assign":
        lines.append("  let mut t: i64 = 0;")
        sa, na = "t = %s;" % some_e, "t = %s;" % none_e
    else:
        sa, na = "return %s;" % some_e, "return %s;" % none_e
    lines += ["  match %s {" % scrut, "    %s => { %s }" % (arm_some, sa), "    %s => { %s }" % (arm_none, na), "  }"]
    if style == "assign":
        lines.append("  return t;")
    return lines


# -- 4) Option / Result 매개변수

def tmpl_optparam(ctx):
    rng = ctx.rng
    res = rng.random() < 0.5
    with_x = rng.random() < 0.45
    B = rng.choice([1000, 1000000])
    pn = "r" if res else "o"
    declare_list(ctx, [[pn, "Result<i64>" if res else "Option<i64>"]] + ([["x", "i64"]] if with_x else []))
    is_, val = ("is_ok", "ok_val") if res else ("is_some", "some_val")
    V = "%s(%s)" % (val, pn)
    set_int(ctx, pn, lo=0, hi=B)
    form = rng.choices(["guard", "strict", "unguarded", "order"], weights=[60, 15, 12, 13])[0]
    if form == "guard":
        ctx.requires.append("%s(%s) ==> ((0 <= %s) && (%s <= %d))" % (is_, pn, V, V, B))
    elif form == "strict":
        ctx.requires.append("(%s(%s)) && (1 <= %s) && (%s <= %d)" % (is_, pn, V, V, B))
    elif form == "unguarded":
        ctx.requires.append("(0 <= %s) && (%s <= %d)" % (V, V, B))      # None/Err 이면 requires undefined
    else:
        ctx.requires.append("(0 <= %s) && (%s <= %d) && %s(%s)" % (V, V, B, is_, pn))
    if res:
        ctx.hints["errs"] = {pn: {"lo": -B, "hi": B}}
        if rng.random() < 0.92:
            ctx.requires.append("(!is_ok(r)) ==> ((%s <= err_val(r)) && (err_val(r) <= %d))" % (lit(-B), B))
    if with_x:
        bnd(ctx, "x", B)
    if rng.random() < 0.5:      # Option/Result 비교 재료 (실행 시 requires 검사가 값 비교를 한다)
        k = rng.choice([0, 1, 3, B])
        if res:
            r, ex = rng.choice([
                ("%s != Ok(%d)" % (pn, k), [{"tag": "Ok", "v": k}, {"tag": "Err", "v": k}]),
                ("(%s == Ok(3)) || (is_ok(%s) == false)" % (pn, pn), [{"tag": "Ok", "v": 3}, {"tag": "Ok", "v": k}]),
                ("%s != Err(%d)" % (pn, k), [{"tag": "Err", "v": k}, {"tag": "Ok", "v": k}])])
        else:
            kx = "x" if with_x and rng.random() < 0.4 else str(k)
            r, ex = rng.choice([
                ("%s != Some(%s)" % (pn, kx), [{"tag": "Some", "v": k}, {"tag": "None"}]),
                ("(!is_some(%s)) || (%s != Some(%s))" % (pn, pn, kx), [{"tag": "Some", "v": k}, {"tag": "None"}])])
        if rng.random() < 0.5:
            ctx.requires.insert(0, r)
        else:
            ctx.requires.append(r)
        ctx.hints["exact_val"] = {pn: ex}
    if res:
        errs = ["0", "c", "(c + 1)"] + (["x", "(c + x)"] if with_x else [])
        none_e = rng.choice(errs)
        none_ens = none_e.replace("c", "err_val(r)")
    else:
        none_e = rng.choice(["0", "(-1)"] + (["x", "(0 - x)"] if with_x else []))
        none_ens = none_e
    some_e = rng.choice(["v", "(v + 1)"] + (["(v + x)", "(x - v)"] if with_x else []))
    some_ens = some_e.replace("v", V)
    if rng.random() < 0.7:
        ctx.ensures.append("(%s(%s) ==> (result == %s))" % (is_, pn, some_ens))
    if rng.random() < 0.7:
        ctx.ensures.append("((!%s(%s)) ==> (result == %s))" % (is_, pn, none_ens))
    arm_some = "Ok(v)" if res else "Some(v)"
    arm_none = "Err(c)" if res else "None"
    if rng.random() < 0.5:
        return ["  match %s {" % pn, "    %s => { return %s; }" % (arm_some, some_e),
                "    %s => { return %s; }" % (arm_none, none_e), "  }"]
    return ["  let mut t: i64 = 0;", "  match %s {" % pn, "    %s => { t = %s; }" % (arm_some, some_e),
            "    %s => { t = %s; }" % (arm_none, none_e), "  }", "  return t;"]


# -- 5) 구조체 / 열거형 (f 의 매개변수·반환에 약 70%, 나머지는 안쪽 지역·보조 함수에서만 쓴다)

TAP_SCENARIOS = ["tlit", "tenum", "tsome", "tmatch", "tcall", "tover"]


def tmpl_struct(ctx):
    rng = ctx.rng
    P = rng.choice(["Point", "Pair", "Spot"])
    Q = rng.choice(["Frame", "Panel", "Holder"])
    E = rng.choice(["Event", "Shape", "Msg"])
    M = "Mode"                  # 구조체 안 열거형 필드용 (E 는 P 를 품으므로 재귀를 피해 따로 둔다)
    has_ok = rng.random() < 0.35
    has_opt = rng.random() < 0.3
    has_res = rng.random() < 0.1      # Result<i64> 필드 res
    has_ef = rng.random() < 0.1       # 열거형 필드 m: Mode
    has_unit = rng.random() < 0.1     # 빈 구조체 필드 u: Unit
    pv = rng.choice([("Hit", "Fail"), ("Hit", "Fail"), ("Hit",), ("Fail",)])
    B = rng.choice([1000, 100000, 1000000])
    if rng.random() < 0.7:      # 70%는 f 가 구조체·열거형을 인자·반환으로 다룬다
        sc = rng.choice(["pval", "pret", "qval", "eval", "eret", "emix"])
    elif rng.random() < 0.7:    # 나머지 30% 중 약 70%는 io 로 평가 순서를 관측하는 변형 (전체의 약 21%)
        sc = rng.choice(TAP_SCENARIOS)
    else:
        sc = rng.choice(["lit", "mut", "copy", "nested", "loopf", "loopa", "mk", "shift", "chain", "chain",
                         "ematch", "optf"])
    if sc in ("optf", "tsome"):
        has_opt = True
    quiet = {"opt": "None", "res": "Err(1)", "m": "%s::Off" % M}     # tap 변형: 필드 기본값이 tap 을 되풀이하지 않게
    tinfo = {"structs": {}, "enums": {}}
    bound_reqs = []             # [(requires 문장, 매개변수 이름)] 변이로 하나 뺄 수 있는 경계 계약

    def plit(xe, ye, opt=None, ok=None, res=None, m=None):
        """구조체 리터럴: 필드는 항상 선언 순서 (x, y, ok, opt, res, m, u)."""
        f = ["x: %s" % xe, "y: %s" % ye]
        if has_ok:
            f.append("ok: %s" % (ok or "true"))
        if has_opt:
            f.append("opt: %s" % (opt or "Some(%s)" % xe))
        if has_res:
            f.append("res: %s" % (res or "Ok(%s)" % xe))
        if has_ef:
            f.append("m: %s" % (m or "%s::On(%s)" % (M, xe)))
        if has_unit:
            f.append("u: Unit {}")
        return "%s { %s }" % (P, ", ".join(f))

    def iv(e, var):
        return "is_variant(%s, %s::%s)" % (e, E, var)

    def vf(e, var, fld):
        return "variant_field(%s, %s::%s, %s)" % (e, E, var, fld)

    def arms():
        out = ["    %s::Empty => { return 0; }" % E]
        if "Hit" in pv:
            out += ["    %s::Hit(pt, ok) => {" % E, "      if ok {", "        return pt.x;", "      }",
                    "      return pt.y;", "    }"]
        if "Fail" in pv:
            out.append("    %s::Fail(code) => { return code; }" % E)
        return out

    def types_text(want_q, want_e):
        out = []
        if has_unit:
            out += ["struct Unit {}", ""]
            tinfo["structs"]["Unit"] = []
        if has_ef:
            out += ["enum %s {" % M, "  Off,", "  On(level: i64),", "}", ""]
            tinfo["enums"][M] = {"Off": [], "On": [["level", "i64"]]}
        out += ["struct %s {" % P, "  x: i64,", "  y: i64,"]
        pf = [["x", "i64"], ["y", "i64"]]
        if has_ok:
            out.append("  ok: bool,")
            pf.append(["ok", "bool"])
        if has_opt:
            out.append("  opt: Option<i64>,")
            pf.append(["opt", "Option<i64>"])
        if has_res:
            out.append("  res: Result<i64>,")
            pf.append(["res", "Result<i64>"])
        if has_ef:
            out.append("  m: %s," % M)
            pf.append(["m", M])
        if has_unit:
            out.append("  u: Unit,")
            pf.append(["u", "Unit"])
        out.append("}")
        tinfo["structs"][P] = pf
        if want_q:
            out += ["", "struct %s {" % Q, "  p: %s," % P, "  n: i64,", "}"]
            tinfo["structs"][Q] = [["p", P], ["n", "i64"]]
        if want_e:
            out += ["", "enum %s {" % E, "  Empty,"]
            ev = {"Empty": []}
            if "Hit" in pv:
                out.append("  Hit(pt: %s, ok: bool)," % P)
                ev["Hit"] = [["pt", P], ["ok", "bool"]]
            if "Fail" in pv:
                out.append("  Fail(code: i64),")
                ev["Fail"] = [["code", "i64"]]
            out.append("}")
            tinfo["enums"][E] = ev
        return "\n".join(out)

    hit, fail = "Hit" in pv, "Fail" in pv

    def ibound(ex, name):
        """i64 식 ex 를 [-B, B] 로 묶는 requires 하나 (name: 힌트를 거는 매개변수)."""
        r = "(%s <= %s) && (%s <= %d)" % (lit(-B), ex, ex, B)
        ctx.requires.append(r)
        bound_reqs.append((r, name))
        set_int(ctx, name, lo=-B, hi=B)

    def obound(ex, name):
        """Option<i64> 식 ex 의 값을 묶는다. some_val 은 is_some 으로 가드한다."""
        inner = "(%s <= some_val(%s)) && (some_val(%s) <= %d)" % (lit(-B), ex, ex, B)
        if rng.random() < 0.5:
            r = "(!is_some(%s)) || (%s)" % (ex, inner)
        else:
            r = "is_some(%s) ==> (%s)" % (ex, inner)
        ctx.requires.append(r)
        bound_reqs.append((r, name))
        set_int(ctx, name, lo=-B, hi=B)

    def pbound(path, name):
        ibound("%s.x" % path, name)
        ibound("%s.y" % path, name)
        if has_opt:
            obound("%s.opt" % path, name)

    def ebound(name):
        """열거형 매개변수 name 의 페이로드 경계. 가드된 variant_field, 가끔 Fail 쪽을 무방비로 둔다."""
        set_int(ctx, name, lo=-B, hi=B)
        if hit:
            pt = vf(name, "Hit", "pt")
            for fld in ("x", "y"):
                r = "(!%s) || ((%s <= %s.%s) && (%s.%s <= %d))" % (iv(name, "Hit"), lit(-B), pt, fld, pt, fld, B)
                ctx.requires.append(r)
                bound_reqs.append((r, name))
            if has_opt:
                inner = "(%s <= some_val(%s.opt)) && (some_val(%s.opt) <= %d)" % (lit(-B), pt, pt, B)
                r = "(!%s) || (!is_some(%s.opt)) || (%s)" % (iv(name, "Hit"), pt, inner)
                ctx.requires.append(r)
                bound_reqs.append((r, name))
        if fail:
            c = vf(name, "Fail", "code")
            inner = "(%s <= %s) && (%s <= %d)" % (lit(-B), c, c, B)
            if rng.random() < 0.08:
                r = inner                        # 무방비 variant_field: 거절돼야 함 (안전 모드에선 requires undefined)
            else:
                r = "(!%s) || (%s)" % (iv(name, "Fail"), inner)
            ctx.requires.append(r)
            bound_reqs.append((r, name))

    def drop_bound(p=0.12):
        """경계 계약 하나를 뺀다: 오버플로가 증명되지 않아 거절돼야 함(입력 힌트도 푼다)."""
        if bound_reqs and rng.random() < p:
            r, name = rng.choice(bound_reqs)
            ctx.requires.remove(r)
            h = hint_int(ctx, name)
            h["lo"] = h["hi"] = None

    def bump_ens(old, new):
        """ensures 중 old 를 포함한 첫 문장을 어긋나게 한다."""
        for i, s in enumerate(ctx.ensures):
            if old in s:
                ctx.ensures[i] = s.replace(old, new, 1)
                return

    def x_bound(name="x"):
        if rng.random() < 0.93:
            bnd(ctx, name, B)
        else:
            set_int(ctx, name, lo=-B, hi=B)      # 무방비: 오버플로를 증명 못 해 거절돼야 함

    pending_exact = []          # [(매개변수 이름, 값 만드는 함수)] types_text 뒤에 풀어 hints["exact_val"] 로 넣는다

    def zero(ty):
        """타입 ty 의 영(0) 값 (입력 JSON 형태). types_text 뒤에만 부른다."""
        if ty == "i64":
            return 0
        if ty == "bool":
            return True
        if ty == "Option<i64>":
            return {"tag": "Some", "v": 0}
        if ty == "Result<i64>":
            return {"tag": "Ok", "v": 0}
        if ty in tinfo["structs"]:
            return {"struct": ty, "fields": {fn: zero(ft) for fn, ft in tinfo["structs"][ty]}}
        first = list(tinfo["enums"][ty].keys())[0]
        return {"enum": ty, "variant": first, "fields": {fn: zero(ft) for fn, ft in tinfo["enums"][ty][first]}}

    def evar(var, **kw):
        """열거형 E 의 변이 값 (필드 이름 -> 값; 안 준 필드는 영값)."""
        return {"enum": E, "variant": var,
                "fields": {fn: kw.get(fn, zero(ft)) for fn, ft in tinfo["enums"][E][var]}}

    def cmp_req(p=None, v=None, pparam=None, e=None, eparam=None, p_prob=0.6):
        """requires 에 구조체 리터럴·열거형 ==/!= 비교를 하나 더한다 (실행 시 requires 검사는 i128 로 계산한다).
        p: 구조체 경로(예 "p", "q.p"), v: 곱할 i64 식, pparam: p 가 매개변수 이름 그대로면 그 이름,
        e: 열거형 매개변수 이름. 입력이 이 조건을 만족·위반하는 값 둘 다 나오게 exact_val 힌트도 건다."""
        if rng.random() >= p_prob:
            return
        opts = []
        if p:
            cp = dict(opt="%s.opt" % p, ok="%s.ok" % p, res="%s.res" % p, m="%s.m" % p)
            sq = rng.choice(["(%s * %s)" % (v, v), "(%s * %s)" % (v, v), "((%s * %s) * %s)" % (v, v, v)])
            opts.append(("%s != %s" % (p, plit(sq, "0", **cp)), "p0"))     # 곱이 i64 를 넘을 수 있다 (계약 산술)
            opts.append(("(%s.x == %s.y) ==> (%s == %s)" % (p, p, p, plit("%s.y" % p, "%s.x" % p, **cp)), None))
        if e:
            opts.append(("%s != %s::Empty" % (e, E), "e0"))
            if fail:
                opts.append(("(!%s) || (%s != %s::Fail(0))" % (iv(e, "Fail"), e, E), "e1"))
            if hit:
                sq = "(%s * %s)" % (v, v) if v else "1"
                lp = plit(sq, "0", opt="None", res="Err(0)", m="%s::Off" % M)
                opts.append(("%s != %s::Hit(%s, false)" % (e, E, lp), "e2"))
        r, tag = rng.choice(opts)
        if rng.random() < 0.5:
            ctx.requires.insert(0, r)
        else:
            ctx.requires.append(r)
        if tag == "p0" and pparam:
            # 영값 (x=0, y=0): 비교와 정확히 같아 위반; x=1 인 값은 만족
            pending_exact.append((pparam, lambda: [zero(P), dict(zero(P), fields=dict(zero(P)["fields"], x=1))]))
        if tag in ("e0", "e1", "e2") and eparam:
            pending_exact.append((eparam, lambda: [evar("Empty"), evar("Fail", code=0) if fail else evar("Empty"),
                                                   evar("Hit", ok=False) if hit else evar("Empty")]))

    want_q = want_e = False
    if sc == "lit":
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        op = rng.choice(["+", "-"])
        ye = rng.choice(["(x + 1)", "x", "0", "(x * 2)"])
        ctx.ensures.append("result == (x %s %s)" % (op, ye))
        body = ["  let p: %s = %s;" % (P, plit("x", ye)), "  return (p.x %s p.y);" % op]
    elif sc == "mut":
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        k, m = rng.choice([1, 2, 3, 5]), rng.choice([2, 3])
        ctx.ensures.append("result == ((x + %d) * %d)" % (k, 1 + m))
        body = ["  let mut p: %s = %s;" % (P, plit("x", "0")), "  p.x = (p.x + %d);" % k,
                "  p.y = (p.x * %d);" % m, "  return (p.x + p.y);"]
    elif sc == "copy":
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        K = rng.choice([9, 0, -4, 1000])
        op = rng.choice(["+", "-"])
        ctx.ensures.append("result == (x %s %s)" % (op, lit(K)))
        body = ["  let p: %s = %s;" % (P, plit("x", "2")), "  let mut q: %s = p;" % P, "  q.x = %s;" % lit(K),
                "  return (p.x %s q.x);" % op]
    elif sc == "nested":
        want_q = True
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        k = rng.choice([1, 5, 8])
        ctx.ensures.append("result == ((3 * x) + %d)" % (k + 2))
        body = ["  let mut q: %s = %s { p: %s, n: 2 };" % (Q, Q, plit("x", "1")), "  let old: %s = q;" % Q,
                "  q.p.x = (q.p.x + %d);" % k, "  q.n = (q.n + old.p.x);",
                "  return ((q.p.x + old.p.x) + q.n);"]
    elif sc == "loopf":
        declare_list(ctx, [["n", "i64"]])
        set_int(ctx, "n", cap=100)
        if rng.random() < 0.92:
            ctx.requires.append("(0 <= n) && (n <= 100)")
            set_int(ctx, "n", lo=0, hi=100)
        invs = ["(0 <= i) && (i <= n)", "p.x == i", "p.y == 7"]
        ctx.ensures.append("result == (n + 7)")
        parts = {"cond": "(i < n)", "invs": invs, "decr": "(n - i)", "decr_bad": "n",
                 "body": ["p.x = (p.x + 1);"], "step": ["i = (i + 1);"]}
        extras = {"cond_le_n": cond_lt_le,
                  "wrong_step": lambda p: p.__setitem__("body", ["p.x = (p.x + 2);"])}
        pre = ["  let mut p: %s = %s;" % (P, plit("0", "7")), "  let mut i: i64 = 0;"]
        body = finish_template(ctx, pre, parts, ["  return (p.x + p.y);"], extras)
    elif sc == "loopa":
        declare_list(ctx, [["a", "array"]])
        if rng.random() < 0.93:
            elem_bound(ctx, "a", B)
        if rng.random() < 0.93:
            ctx.requires.append("len(a) <= 1000")
            set_arr(ctx, "a", maxlen=1000)
        invs = ["(0 <= i) && (i <= len(a))", "(s.x >= (%s * i)) && (s.x <= (%d * i))" % (lit(-B), B), "s.y == 7"]
        if rng.random() < 0.7:
            invs.append("s.x == sum(k in 0..i: a[k])")
            ctx.ensures.append("result == (sum(k in 0..len(a): a[k]) + 7)")
        else:
            ctx.ensures.append("result >= (7 - (%d * len(a)))" % B)
        parts = {"cond": "(i < len(a))", "invs": invs, "decr": "(len(a) - i)", "decr_bad": "len(a)",
                 "body": ["s.x = (s.x + a[i]);"], "step": ["i = (i + 1);"]}
        pre = ["  let mut s: %s = %s;" % (P, plit("0", "7")), "  let mut i: i64 = 0;"]
        body = finish_template(ctx, pre, parts, ["  return (s.x + s.y);"], {"cond_le_n": cond_lt_le})
    elif sc == "mk":
        declare_list(ctx, [["x", "i64"], ["y", "i64"]])
        x_bound("x")
        x_bound("y")
        g = ["fn mk(x: i64, y: i64) -> %s" % P, "  ensures result.x == x", "  ensures result.y == y"]
        if rng.random() < 0.6:
            g.append("  ensures result == %s" % plit("x", "y"))      # 필드가 더 있으면 모두 선언 순서대로
        if has_opt and rng.random() < 0.7:
            g.append("  ensures is_some(result.opt) && (some_val(result.opt) == x)")
        if len(g) > 2 and rng.random() < 0.1:
            g.pop(rng.randrange(1, len(g)))      # 계약을 줄이면 호출쪽 증명이 깨질 수 있다
        g += ["{", "  return %s;" % plit("x", "y"), "}"]
        ctx.helper, ctx.after = "\n".join(g), rng.random() < 0.4
        ctx.ensures.append("result == (x + y)")
        body = ["  let p: %s = mk(x, y);" % P, "  return (p.x + p.y);"]
    elif sc == "shift":
        declare_list(ctx, [["x", "i64"]])
        B = rng.choice([1000, 100000])
        x_bound()
        D = rng.choice([3, 100, -7, 1000000])
        if rng.random() < 0.1:
            D = 2000000                          # 보조 함수 requires 위반: 거절돼야 함
        g = ["fn shift(p: %s, dx: i64) -> %s" % (P, P),
             "  requires ((-1000000) <= p.x) && (p.x <= 1000000)",
             "  requires ((-1000000) <= dx) && (dx <= 1000000)",
             "  ensures result.x == (p.x + dx)", "  ensures result.y == p.y", "{",
             "  let mut q: %s = p;" % P, "  q.x = (q.x + dx);", "  return q;", "}"]
        ctx.helper, ctx.after = "\n".join(g), rng.random() < 0.4
        body = ["  let p: %s = %s;" % (P, plit("x", "1")), "  let r: %s = shift(p, %s);" % (P, lit(D))]
        if rng.random() < 0.4:      # 호출 뒤 호출자의 원래 값 p 를 다시 쓴다 (호출 너머 복사)
            ctx.ensures.append("result == (((x + %s) + x) + 1)" % lit(D))
            body.append("  return ((r.x + p.x) + r.y);")
        else:
            ctx.ensures.append("result == ((x + %s) + 1)" % lit(D))
            body.append("  return (r.x + r.y);")
    elif sc == "chain":
        want_e = True
        declare_list(ctx, [["x", "i64"]])
        ctx.requires.append("(0 <= x) && (x <= %d)" % B)
        set_int(ctx, "x", lo=0, hi=B)
        hit, fail = "Hit" in pv, "Fail" in pv
        A = "%s::Hit(%s, true)" % (E, plit("x", "1")) if hit else "%s::Fail(x)" % E
        Bv = "%s::Fail(x)" % E if fail else "%s::Empty" % E
        wens = []
        if hit:
            wens.append("((x > 0) ==> (%s && (%s.x == x) && (%s.y == 1)))"
                        % (iv("result", "Hit"), vf("result", "Hit", "pt"), vf("result", "Hit", "pt")))
        else:
            wens.append("((x > 0) ==> (%s && (%s == x)))" % (iv("result", "Fail"), vf("result", "Fail", "code")))
        if fail:
            wens.append("((x <= 0) ==> (%s && (%s == x)))" % (iv("result", "Fail"), vf("result", "Fail", "code")))
        else:
            wens.append("((x <= 0) ==> %s)" % iv("result", "Empty"))
        if rng.random() < 0.1:
            wens.pop(rng.randrange(len(wens)))   # 계약 하나 빼기: 호출쪽 requires 증명이 깨질 수 있다
        wrap = ["fn wrap(x: i64) -> %s" % E] + ["  ensures " + w for w in wens]
        wrap += ["{", "  if (x > 0) {", "    return %s;" % A, "  }", "  return %s;" % Bv, "}"]
        sreq = []
        if hit:
            sreq.append("(!%s) || ((%s.x >= 0) && (%s.y >= 0))"
                        % (iv("e", "Hit"), vf("e", "Hit", "pt"), vf("e", "Hit", "pt")))
        if fail:
            if rng.random() < 0.1:
                sreq.append("%s >= 0" % vf("e", "Fail", "code"))        # 무방비: variant_domain 기대
            else:
                sreq.append("(!%s) || (%s >= 0)" % (iv("e", "Fail"), vf("e", "Fail", "code")))
        score = ["fn score(e: %s) -> i64" % E] + ["  requires " + r for r in sreq] + ["  ensures result >= 0", "{",
                 "  match e {"] + arms() + ["  }", "}"]
        texts = ["\n".join(wrap), "\n".join(score)]
        rng.shuffle(texts)
        ctx.helper, ctx.after = "\n\n".join(texts), rng.random() < 0.4
        ctx.ensures.append("result >= 0")
        if rng.random() < 0.5:
            ctx.ensures.append("result <= %d" % B)
        if rng.random() < 0.5:
            body = ["  let e: %s = wrap(x);" % E, "  return score(e);"]
        else:
            body = ["  return score(wrap(x));"]
    elif sc == "ematch":
        want_e = True
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        hit, fail = "Hit" in pv, "Fail" in pv
        A = "%s::Hit(%s, true)" % (E, plit("x", "1")) if hit else "%s::Fail(x)" % E
        Bv = "%s::Fail(x)" % E if fail else "%s::Empty" % E
        ctx.ensures.append("(%s <= result) && (result <= %d)" % (lit(-B), B))
        body = ["  let mut e: %s = %s::Empty;" % (E, E), "  if (x > 0) {", "    e = %s;" % A, "  } else {",
                "    e = %s;" % Bv, "  }", "  match e {"] + arms() + ["  }"]
    elif sc == "pval":      # f(p: P) -> i64
        extra_u = has_unit and rng.random() < 0.5      # 빈 구조체를 f 인자로도 받는다
        declare_list(ctx, [["p", P]] + ([["u", "Unit"]] if extra_u else []))
        pbound("p", "p")
        drop_bound()
        cmp_req(p="p", v="p.y", pparam="p")
        form = rng.choice(["sum", "sum", "diff", "ok", "opt"] if has_ok or has_opt else ["sum", "sum", "diff"])
        if form == "ok" and not has_ok:
            form = "sum"
        if form == "opt" and not has_opt:
            form = "sum"
        if form in ("sum", "diff"):
            op = "+" if form == "sum" else "-"
            ctx.ensures.append("result == (p.x %s p.y)" % op)
            body = ["  return (p.x %s p.y);" % op]
        elif form == "ok":
            ctx.ensures.append("(p.ok ==> (result == (p.x - p.y))) && ((!p.ok) ==> (result == (p.x + p.y)))")
            body = ["  if p.ok {", "    return (p.x - p.y);", "  }", "  return (p.x + p.y);"]
        else:
            ctx.ensures.append("(is_some(p.opt) ==> (result == (some_val(p.opt) + p.x))) && "
                               "((!is_some(p.opt)) ==> (result == p.y))")
            body = ["  match p.opt {", "    Some(v) => { return (v + p.x); }", "    None => { return p.y; }", "  }"]
    elif sc == "pret":      # f(p: P, dx: i64) -> P
        declare_list(ctx, [["p", P], ["dx", "i64"]])
        pbound("p", "p")
        x_bound("dx")
        drop_bound()
        cmp_req(p="p", v="dx", pparam="p")
        ctx.ret = P
        v = rng.choice(["add", "add", "swap", "fresh"])
        okf = has_ok and v != "swap" and rng.random() < 0.4      # ok 필드도 바꾼다
        okx = "(dx > 0)" if okf else "p.ok"
        if v == "swap":
            ctx.ensures += ["result.x == p.y", "result.y == (p.x + dx)"]
            body = ["  let mut q: %s = p;" % P, "  q.x = p.y;", "  q.y = (p.x + dx);", "  return q;"]
        else:
            ctx.ensures += ["result.x == (p.x + dx)", "result.y == p.y"]
            if okf:
                ctx.ensures.append("result.ok == (dx > 0)")
            if rng.random() < 0.4:
                ctx.ensures.append("result == %s" % plit("(p.x + dx)", "p.y", opt="p.opt", ok=okx))
            if v == "add":
                body = ["  let mut q: %s = p;" % P, "  q.x = (q.x + dx);"]
                if okf:
                    body.append("  q.ok = (dx > 0);")
                body.append("  return q;")
            else:
                body = ["  return %s;" % plit("(p.x + dx)", "p.y", opt="p.opt", ok=okx)]
        if rng.random() < 0.1:
            bump_ens("result.x == (p.x + dx)", "result.x == ((p.x + dx) + 1)")    # 어긋난 ensures: 거절돼야 함
    elif sc == "qval":      # f(q: Q) -> Q 또는 i64, 중첩 필드 대입
        want_q = True
        declare_list(ctx, [["q", Q]])
        pbound("q.p", "q")
        ibound("q.n", "q")
        drop_bound()
        cmp_req(p="q.p", v="q.n")
        if rng.random() < 0.5:
            ctx.ret = Q
            ctx.ensures += ["result.p.x == (q.p.x + q.n)", "result.p.y == q.p.y", "result.n == (q.n + 1)"]
            body = ["  let mut r: %s = q;" % Q, "  r.p.x = (r.p.x + q.n);", "  r.n = (q.n + 1);", "  return r;"]
            if rng.random() < 0.1:
                bump_ens("result.n == (q.n + 1)", "result.n == q.n")
        else:
            ctx.ensures.append("result == ((3 * q.p.x) + q.n)")
            body = ["  let mut r: %s = q;" % Q, "  r.p.x = (r.p.x * 2);", "  return ((r.p.x + q.p.x) + r.n);"]
            maybe_bad_ensures(ctx)
    elif sc == "eval":      # f(e: E) -> i64
        want_e = True
        declare_list(ctx, [["e", E]])
        ebound("e")
        drop_bound(0.08)
        cmp_req(e="e", eparam="e")
        opt_hit = hit and has_opt and rng.random() < 0.6
        fk = rng.choice(["code", "code", "(code + 1)"])
        out = ["    %s::Empty => { return 0; }" % E]
        if hit:
            out += ["    %s::Hit(pt, ok) => {" % E, "      if ok {", "        return pt.x;", "      }"]
            if opt_hit:
                out += ["      match pt.opt {", "        Some(v) => { return (v + pt.y); }",
                        "        None => { return pt.y; }", "      }"]
            else:
                out.append("      return pt.y;")
            out.append("    }")
        if fail:
            out.append("    %s::Fail(code) => { return %s; }" % (E, fk))
        body = ["  match e {"] + out + ["  }"]
        ctx.ensures.append("(%s <= result) && (result <= %d)" % (lit(-2 * B), 2 * B))
        if rng.random() < 0.6:
            ctx.ensures.append("%s ==> (result == 0)" % iv("e", "Empty"))
        if fail and rng.random() < 0.7:
            ctx.ensures.append("%s ==> (result == %s)" % (iv("e", "Fail"), fk.replace("code", vf("e", "Fail", "code"))))
        if hit and not opt_hit and rng.random() < 0.7:
            ctx.ensures.append("(%s && %s) ==> (result == %s.x)"
                               % (iv("e", "Hit"), vf("e", "Hit", "ok"), vf("e", "Hit", "pt")))
        if any("(result == 0)" in s for s in ctx.ensures) and rng.random() < 0.08:    # 대상이 있을 때만
            bump_ens("(result == 0)", "(result == 1)")
    elif sc == "eret":      # f(x: i64) -> E, 분기로 변이를 고른다
        want_e = True
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        ctx.ret = E
        okx = "(x > 10)"
        if hit:
            A = "%s::Hit(%s, %s)" % (E, plit("x", "1"), okx)
            aens = "((x > 0) ==> (%s && (%s.x == x) && (%s.y == 1) && (%s == %s)))" % (
                iv("result", "Hit"), vf("result", "Hit", "pt"), vf("result", "Hit", "pt"),
                vf("result", "Hit", "ok"), okx)
        else:
            A = "%s::Fail(x)" % E
            aens = "((x > 0) ==> (%s && (%s == x)))" % (iv("result", "Fail"), vf("result", "Fail", "code"))
        if fail:
            Bv = "%s::Fail((0 - x))" % E
            bens = "((x < 0) ==> (%s && (%s == (0 - x))))" % (iv("result", "Fail"), vf("result", "Fail", "code"))
        else:
            Bv = "%s::Empty" % E
            bens = "((x < 0) ==> %s)" % iv("result", "Empty")
        zens = "((x == 0) ==> (result == %s::Empty))" % E if rng.random() < 0.3 else "((x == 0) ==> %s)" % iv("result", "Empty")
        ctx.ensures += [aens, bens, zens]
        if rng.random() < 0.1:      # 어긋난 ensures: 실제로 문장이 바뀌는 것만 고른다
            muts = []
            for i in range(3):
                s = ctx.ensures[i]
                t = s.replace("== x", "== (x + 1)", 1).replace("== (0 - x)", "== x", 1)
                if t == s and s.startswith("((x == 0) ==> "):
                    t = s.replace("==> ", "==> !", 1)       # x == 0 인데 Empty 가 아니라고 주장
                if t != s:
                    muts.append((i, t))
            if muts:
                i, t = rng.choice(muts)
                ctx.ensures[i] = t
        body = ["  if (x > 0) {", "    return %s;" % A, "  }", "  if (x < 0) {", "    return %s;" % Bv, "  }",
                "  return %s::Empty;" % E]
    elif sc == "emix":      # f(e: E, p: P) -> E
        want_e = True
        declare_list(ctx, [["e", E], ["p", P]])
        ebound("e")
        pbound("p", "p")
        drop_bound(0.1)
        if rng.random() < 0.5:
            cmp_req(p="p", v="p.x", pparam="p", p_prob=1.0)
        else:
            cmp_req(e="e", v="p.x", eparam="e", p_prob=1.0)
        ctx.ret = E
        wrong = rng.random() < 0.08
        out = []
        if hit:
            out.append("    %s::Empty => { return %s::Hit(p, true); }" % (E, E))
            ctx.ensures.append("%s ==> (%s && (%s == p))" % (iv("e", "Empty"), iv("result", "Hit"), vf("result", "Hit", "pt")))
            out += ["    %s::Hit(pt, ok) => {" % E, "      let mut r: %s = pt;" % P, "      r.x = (pt.x + p.x);",
                    "      return %s::Hit(r, ok);" % E, "    }"]
            ctx.ensures.append("%s ==> (%s && (%s.x == (%s.x + p.x)) && (%s == %s))" % (
                iv("e", "Hit"), iv("result", "Hit"), vf("result", "Hit", "pt"), vf("e", "Hit", "pt"),
                vf("result", "Hit", "ok"), vf("e", "Hit", "ok")))
        else:
            out.append("    %s::Empty => { return %s::Fail(p.x); }" % (E, E))
            ctx.ensures.append("%s ==> (%s && (%s == p.x))" % (iv("e", "Empty"), iv("result", "Fail"), vf("result", "Fail", "code")))
        if fail:
            out.append("    %s::Fail(code) => { return %s::Fail((code + p.y)); }" % (E, E))
            fe = "(%s + p.y)" % vf("e", "Fail", "code")
            if wrong:
                fe = "(%s + 1)" % fe
            ctx.ensures.append("%s ==> (%s && (%s == %s))" % (iv("e", "Fail"), iv("result", "Fail"), vf("result", "Fail", "code"), fe))
        body = ["  match e {"] + out + ["  }"]
    elif sc == "tlit":      # 구조체 리터럴 필드 평가 순서: 왼쪽부터 (tap 출력 순서가 비교된다)
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        ctx.effects = ["io"]
        ctx.helper, ctx.after = TAP_FN, rng.random() < 0.4
        xe, ye, ens = rng.choice([("tap(x)", "tap((x + 1))", "((x + x) + 1)"), ("tap(x)", "tap(2)", "(x + 2)"),
                                  ("(tap(x) + 1)", "tap(x)", "((x + 1) + x)")])
        ctx.ensures.append("result == %s" % ens)
        body = ["  let p: %s = %s;" % (P, plit(xe, ye, **quiet)), "  return (p.x + p.y);"]
    elif sc == "tenum":     # 열거형 생성 인자의 tap, 가끔 match 대상 pick(..) 가 e 를 한 번만 평가
        want_e = True
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        ctx.effects = ["io"]
        A = "%s::Hit(%s, true)" % (E, plit("tap(x)", "1", **quiet)) if hit and (not fail or rng.random() < 0.5) \
            else "%s::Fail(tap(x))" % E
        ctx.ensures.append("result == x")
        texts = [TAP_FN]
        if rng.random() < 0.5:
            texts.append("\n".join(["fn pick(e: %s) -> %s ! io" % (E, E), "  ensures result == e", "{", "  print(3);",
                                    "  return e;", "}"]))
            body = ["  let e: %s = %s;" % (E, A), "  match pick(e) {"] + arms() + ["  }"]
        else:
            body = ["  let e: %s = %s;" % (E, A), "  match e {"] + arms() + ["  }"]
        ctx.helper, ctx.after = "\n\n".join(texts), rng.random() < 0.4
    elif sc == "tsome":     # Option 필드 Some(tap(x))
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        ctx.effects = ["io"]
        ctx.helper, ctx.after = TAP_FN, rng.random() < 0.4
        ctx.ensures.append("result == (x + 1)")
        body = ["  let p: %s = %s;" % (P, plit("x", "1", opt="Some(tap(x))", res="Err(1)", m="%s::Off" % M)),
                "  match p.opt {", "    Some(v) => { return (v + p.y); }", "    None => { return 0; }", "  }"]
    elif sc == "tmatch":    # match g(tap(x)): 대상 식은 한 번만 평가
        want_e = True
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        ctx.effects = ["io"]
        if fail:
            g = ["fn g(v: i64) -> %s" % E,
                 "  ensures (v > 0) ==> (%s && (%s == v))" % (iv("result", "Fail"), vf("result", "Fail", "code")),
                 "  ensures (v <= 0) ==> %s" % iv("result", "Empty"), "{",
                 "  if (v > 0) {", "    return %s::Fail(v);" % E, "  }", "  return %s::Empty;" % E, "}"]
        else:
            g = ["fn g(v: i64) -> %s" % E,
                 "  ensures (v > 0) ==> (%s && (%s.x == v) && (%s.y == 1) && %s)"     # ok·y 도 알려야 f 가 증명된다
                 % (iv("result", "Hit"), vf("result", "Hit", "pt"), vf("result", "Hit", "pt"), vf("result", "Hit", "ok")),
                 "  ensures (v <= 0) ==> %s" % iv("result", "Empty"), "{",
                 "  if (v > 0) {", "    return %s::Hit(%s, true);" % (E, plit("v", "1", **quiet)), "  }",
                 "  return %s::Empty;" % E, "}"]
        ctx.helper, ctx.after = TAP_FN + "\n\n" + "\n".join(g), rng.random() < 0.4
        ctx.ensures += ["((x > 0) ==> (result == x))", "((x <= 0) ==> (result == 0))"]
        body = ["  match g(tap(x)) {"] + arms() + ["  }"]
    elif sc == "tcall":     # 호출 인자: 구조체 리터럴 안의 tap 이 뒤 인자 tap 보다 먼저
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        ctx.effects = ["io"]
        g = ["fn addx(p: %s, k: i64) -> i64" % P,       # sum 은 집계 키워드라 쓰지 않는다
             "  requires ((-1000000) <= p.x) && (p.x <= 1000000)", "  requires ((-1000000) <= k) && (k <= 1000000)",
             "  ensures result == (p.x + k)", "{", "  return (p.x + k);", "}"]
        ctx.helper, ctx.after = TAP_FN + "\n\n" + "\n".join(g), rng.random() < 0.4
        ctx.ensures.append("result == (x + 2)")
        body = ["  return addx(%s, tap(2));" % plit("tap(x)", "1", **quiet)]
    elif sc == "tover":     # 서로 다른 연산이 오버플로하는 두 필드: 왼쪽 필드 오류가 먼저 나는지 관측
        a, b, c, d = "a", "b", "c", "d"
        declare_list(ctx, [[n, "i64"] for n in (a, b, c, d)])
        mode = rng.choices(["ok", "both", "right", "left"], weights=[45, 25, 15, 15])[0]   # right/left: 그쪽만 넘칠 수 있다
        B = rng.choice([1000, 1000000])
        use_tap = rng.random() < 0.5
        for n in (a, b):
            if mode in ("ok", "right"):
                bnd(ctx, n, B)
        for n in (c, d):
            if mode in ("ok", "left"):
                bnd(ctx, n, B)
        ex = {}
        if mode in ("both", "left"):        # 왼쪽(a + b) 이 넘치기 쉬운 값
            ex[a], ex[b] = [I64_MAX, I64_MAX - 1], [I64_MAX, 1, 2, 1 << 62]
        if mode in ("both", "right"):       # 오른쪽(c * d) 이 넘치기 쉬운 값
            ex[c], ex[d] = [1 << 40, I64_MAX, 3037000500], [1 << 40, 2, I64_MAX, 3037000500]
        ctx.hints["exact"] = ex
        ctx.hints["wide"] = [n for n in (a, b, c, d) if n in ex]
        if use_tap:
            ctx.effects = ["io"]
            ctx.helper, ctx.after = TAP_FN, rng.random() < 0.4
        lx = "(tap(a) + b)" if use_tap else "(a + b)"
        ly = "(tap(c) * d)" if use_tap else "(c * d)"
        ctx.ensures.append("result == ((a + b) + (c * d))")
        body = ["  let p: %s = %s;" % (P, plit(lx, ly, **quiet)), "  return (p.x + p.y);"]
    else:  # optf: Option/Result/열거형 필드
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        none = rng.random() < 0.3
        form = rng.choice(["opt"] + (["res"] if has_res else []) + (["mode"] if has_ef else []))
        ctx.ensures.append("result == 0" if none else "result == (x + 1)")
        if form == "opt":
            body = ["  let p: %s = %s;" % (P, plit("x", "1", "None" if none else None)), "  match p.opt {",
                    "    Some(v) => { return (v + p.y); }", "    None => { return 0; }", "  }"]
        elif form == "res":
            body = ["  let p: %s = %s;" % (P, plit("x", "1", res="Err(5)" if none else None)), "  match p.res {",
                    "    Ok(v) => { return (v + p.y); }", "    Err(c) => { return 0; }", "  }"]
        else:
            body = ["  let p: %s = %s;" % (P, plit("x", "1", m="%s::Off" % M if none else None)), "  match p.m {",
                    "    %s::Off => { return 0; }" % M, "    %s::On(l) => { return (l + p.y); }" % M, "  }"]
    ctx.types = types_text(want_q or sc in ("nested",), want_e)
    ctx.type_info = tinfo
    if pending_exact:
        ctx.hints["exact_val"] = {n: fn() for n, fn in pending_exact}
    if sc not in ("loopf", "loopa", "pret", "qval", "eval", "eret", "emix"):
        maybe_bad_ensures(ctx)
    return body


FAMILY_SHARE = 0.50      # 기존 계열 20% + 새 계열(배열 2개·배열 반환·Option/Result·구조체) 30%
FAMILY = [("arrfill", tmpl_arrfill, 17), ("copy", tmpl_copy, 8), ("effects", tmpl_effects, 22),
          ("branches", tmpl_branches, 17), ("nested", tmpl_nested, 13), ("quant", tmpl_quant, 12),
          ("helpers", tmpl_helpers, 11),
          ("twoarr", tmpl_twoarr, 28), ("arrret", tmpl_arrret, 34), ("option", tmpl_option, 32),
          ("optparam", tmpl_optparam, 20), ("struct", tmpl_struct, 60)]


# ---------------------------------------------------------------- 케이스 조립

def render(ctx, body):
    tymap = {"array": "[i64]", "bool": "bool", "Option<i64>": "Option<i64>", "Result<i64>": "Result<i64>"}
    sig = ", ".join("%s: %s" % (n, tymap.get(t, "i64" if t == "i64" else t)) for n, t in ctx.params)   # 구조체·열거형은 타입 이름 그대로
    head = "fn f(%s) -> %s" % (sig, ctx.ret)
    if ctx.effects:
        head += " ! " + ", ".join(ctx.effects)
    out = [head]
    out += ["  requires " + r for r in ctx.requires]
    out += ["  ensures " + e for e in ctx.ensures]
    out.append("{")
    out += body
    out.append("}")
    fsrc = "\n".join(out)
    if ctx.helper:
        fsrc = (fsrc + "\n\n" + ctx.helper) if ctx.after else (ctx.helper + "\n\n" + fsrc)
    if ctx.types:
        fsrc = ctx.types + "\n\n" + fsrc
    return fsrc + "\n"


def generate_case(seed, index):
    rng = random.Random("%s:%s" % (seed, index))
    ctx = Ctx(rng)
    r = rng.random()
    if r < FAMILY_SHARE:
        kind, fn, _w = rng.choices(FAMILY, weights=[w for _, _, w in FAMILY])[0]
        body = fn(ctx)
        src = render(ctx, body)
        case = {"name": "c%s_%s" % (seed, index), "src": src, "entry": "f", "params": ctx.params,
                "ret": ctx.ret, "kind": kind, "input_hints": ctx.hints}
        ti = ctx.type_info
        if ti and any(t in ti["structs"] or t in ti["enums"] for t in [ctx.ret] + [t for _, t in ctx.params]):
            case["types"] = ti       # f 의 인자·반환에 구조체/열거형이 있을 때만 넣는다
        return case
    r = (r - FAMILY_SHARE) / (1.0 - FAMILY_SHARE)   # 기존 재료는 남은 몫을 기존 비율대로 나눠 가진다
    new_kinds = [(0.20, "pure"), (0.35, "undef"), (0.38, "wide"), (0.44, "euclid"),
                 (0.50, "sorted"), (0.57, "bound"), (0.63, "divguard"), (0.69, "call")]
    kind = None
    if r < 0.07:
        kind = "pure"
    elif r < 0.20:
        kind = "straight"
    else:
        for lim, name in new_kinds[1:]:
            if r < lim:
                kind = name
                break
    if kind is None:
        kind = rng.choice(["sum", "count", "maxscan", "search", "countdown", "range"])
    if kind in ("pure", "straight"):
        has_arr = rng.random() < 0.45
        if has_arr:
            n_int = rng.choice([0, 1, 1, 2]) if rng.random() < 0.1 else rng.choice([1, 1, 2])
        else:
            n_int = rng.choice([1, 1, 2, 2, 3])
        declare(ctx, ["x", "y", "z"][:n_int], has_arr)
        add_requires(ctx, rng.choice([0, 1, 1, 2, 2, 3]))
        if rng.random() < 0.15:
            ctx.ret = "bool"
        if kind == "straight" and ctx.ret == "i64" and rng.random() < 0.3:
            ctx.helper = make_helper(rng)
        body = body_pure(ctx) if kind == "pure" else body_straight(ctx)
    else:
        body = {"sum": tmpl_sum, "count": tmpl_count, "maxscan": tmpl_maxscan, "search": tmpl_search,
                "countdown": tmpl_countdown, "range": tmpl_range, "undef": tmpl_undef,
                "wide": tmpl_wide, "euclid": tmpl_euclid, "sorted": tmpl_sorted,
                "bound": tmpl_bound, "divguard": tmpl_divguard, "call": tmpl_call}[kind](ctx)
    src = render(ctx, body)
    return {"name": "c%s_%s" % (seed, index), "src": src, "entry": "f", "params": ctx.params,
            "ret": ctx.ret, "kind": kind, "input_hints": ctx.hints}


# ---------------------------------------------------------------- 입력 생성

def pick_in_range(rng, lo, hi):
    if lo > hi:
        lo, hi = hi, lo
    c = [lo, hi, min(hi, lo + 1), max(lo, hi - 1), rng.randint(lo, hi), rng.randint(lo, hi)]
    if lo <= 0 <= hi:
        c.append(0)
    return rng.choice(c)


def pick_int(rng, h, consts):
    lo, hi, cap = h.get("lo"), h.get("hi"), h.get("cap")
    m = rng.random()
    edges = [b for b in (lo, hi) if b is not None]
    if m < 0.22:
        v = rng.randint(-5, 5)
    elif m < 0.50 and edges:
        v = rng.choice(edges) + rng.choice([-2, -1, 0, 0, 1, 2])
    elif m < 0.60:
        v = rng.choice([0, 1, -1, 2])
    elif m < 0.70 and consts:
        v = rng.choice(consts) + rng.choice([-1, 0, 1])
    elif m < 0.78:
        v = rng.choice(EXTREMES)
    elif m < 0.90 and lo is not None and hi is not None and lo <= hi:
        v = rng.randint(lo, hi)
    else:
        v = rng.randint(-2000, 2000)
    v = max(I64_MIN, min(I64_MAX, v))
    if cap is not None and v > cap:
        v = rng.randint(0, cap)
    return v


def gen_array(rng, h, consts):
    maxlen = min(h.get("maxlen", 8), 8)
    minlen = min(h.get("minlen", 0), 8)
    lo = min(minlen, maxlen)
    hi = max(lo, maxlen)
    if rng.random() < 0.85:
        n = rng.choice([lo, hi, rng.randint(lo, hi), rng.randint(lo, hi)])
    else:
        n = rng.randint(0, 8)
    if h.get("sorted") and rng.random() < 0.3:
        short = [m for m in (0, 1, 2) if lo <= m <= hi]
        if short:
            n = rng.choice(short)
    elem = h.get("elem")
    ih = {"lo": elem[0], "hi": elem[1]} if elem else {}
    out = []
    for _ in range(n):
        if elem and elem[0] <= elem[1] and rng.random() < 0.85:
            out.append(pick_in_range(rng, elem[0], elem[1]))
        else:
            out.append(pick_int(rng, ih, consts))
    if h.get("sorted") and rng.random() < 0.85:
        out.sort()
        m = rng.random()
        if len(out) >= 2 and m < 0.2:        # 인접 교환 한 번
            j = rng.randrange(len(out) - 1)
            out[j], out[j + 1] = out[j + 1], out[j]
        elif len(out) >= 2 and m < 0.4:      # 같은 이웃
            j = rng.randrange(len(out) - 1)
            out[j + 1] = out[j]
    return out


WIDE = [I64_MAX, I64_MIN, I64_MAX - 1, I64_MIN + 1, 1 << 62, -(1 << 62), 3037000499, 3037000500,
        -3037000499, 1 << 32, -(1 << 32), 1 << 40, -(1 << 40), 1 << 43, 1 << 26, -(1 << 26),
        7, -7, 0, 1, -1]


def bias_inputs(rng, h, vals):
    """undef/나눗셈/경계 재료용 입력 편향 (vals 를 제자리에서 바꾼다)."""
    if h.get("empty") and "a" in vals and rng.random() < 0.25:
        vals["a"] = []
    for x in h.get("idx", []):
        n = len(vals.get("a", []))
        if x in vals and rng.random() < 0.6:
            vals[x] = rng.choice([-1, n, n + 1, n - 1, 0, n + 2, n, -1])
    for y in h.get("div", []):
        r = rng.random()
        if y in vals:
            if r < 0.3:
                vals[y] = 0
            elif r < 0.5:
                vals[y] = rng.choice([-1, -2, -3, -7])
    for x in h.get("neg", []):
        if x in vals and rng.random() < 0.4:
            v = rng.choice([-1, -2, -3, -5, -7, -100, -1000, -999999])
            lo = h.get("ints", {}).get(x, {}).get("lo")
            if lo is None or v >= lo:
                vals[x] = v
    for x in h.get("wide", []):
        if x in vals and rng.random() < 0.5:
            vals[x] = rng.choice(WIDE)
    for x, lst in h.get("exact", {}).items():
        if x in vals and lst and rng.random() < 0.45:
            vals[x] = max(I64_MIN, min(I64_MAX, rng.choice(lst)))
    # exact_val: 구조체·열거형·Option/Result 매개변수에 계약 비교와 정확히 같거나 다른 값을 넣는다
    for x, lst in h.get("exact_val", {}).items():
        if x in vals and lst and rng.random() < 0.3:
            vals[x] = copy.deepcopy(rng.choice(lst))


def gen_opt(rng, h, consts):
    """Option<i64> 인자: {"tag": "Some", "v": n} 또는 {"tag": "None"}."""
    if rng.random() < 0.4:
        return {"tag": "None"}
    return {"tag": "Some", "v": pick_int(rng, h, consts)}


def gen_res(rng, h, eh, consts):
    """Result<i64> 인자: {"tag": "Ok", "v": n} 또는 {"tag": "Err", "v": code}. eh: 오류 코드 힌트."""
    if rng.random() < 0.55:
        return {"tag": "Ok", "v": pick_int(rng, h, consts)}
    if rng.random() < 0.5:
        return {"tag": "Err", "v": rng.choice([-2, -1, 0, 1, 2, 3])}
    return {"tag": "Err", "v": pick_int(rng, eh, consts)}


def gen_value(rng, ty, types, h, consts, eh=None, strict=False):
    """타입 문자열 ty 의 입력 값을 case["types"] 로 재귀 생성한다.
    구조체 {"struct": 이름, "fields": {...}}, 열거형 {"enum": 이름, "variant": 변이, "fields": {...}} (필드는 선언 순서).
    h: i64 힌트(lo/hi/cap). strict 면 힌트 범위 안의 값만 고른다(계약을 만족하는 입력을 늘린다)."""
    structs, enums = types.get("structs", {}), types.get("enums", {})
    if ty == "bool":
        return rng.choice([True, False])
    if ty == "Option<i64>":
        if strict and h.get("lo") is not None and h.get("hi") is not None:
            if rng.random() < 0.4:
                return {"tag": "None"}
            return {"tag": "Some", "v": pick_in_range(rng, h["lo"], h["hi"])}
        return gen_opt(rng, h, consts)
    if ty == "Result<i64>":
        return gen_res(rng, h, eh or {}, consts)
    if ty in structs:
        return {"struct": ty, "fields": {fn: gen_value(rng, ft, types, h, consts, eh, strict) for fn, ft in structs[ty]}}
    if ty in enums:
        var = rng.choice(list(enums[ty].keys()))      # 변이는 고르게
        return {"enum": ty, "variant": var,
                "fields": {fn: gen_value(rng, ft, types, h, consts, eh, strict) for fn, ft in enums[ty][var]}}
    if strict and h.get("lo") is not None and h.get("hi") is not None:
        return pick_in_range(rng, h["lo"], h["hi"])
    return pick_int(rng, h, consts)


def fit_len(rng, arr, n, h, consts):
    """배열 arr 을 길이 n 으로 자르거나 늘린다 (두 배열 길이 같음 경계 시험)."""
    arr = list(arr)
    if len(arr) > n:
        return arr[:n]
    elem = h.get("elem")
    while len(arr) < n:
        if elem and elem[0] <= elem[1]:
            arr.append(pick_in_range(rng, elem[0], elem[1]))
        else:
            arr.append(pick_int(rng, {}, consts))
    return arr


def candidate_inputs(case, rng, n):
    h = case["input_hints"]
    consts = h.get("consts", [])
    out = []
    types = case.get("types") or {}
    named = set(types.get("structs", {})) | set(types.get("enums", {}))
    for _ in range(n):
        vals = {}
        strict = rng.random() < 0.75      # 구조체·열거형 값 하나 전체를 힌트 범위 안에 둘지
        for name, ty in case["params"]:
            if ty == "array":
                vals[name] = gen_array(rng, h["arrays"].get(name, {}), consts)
        for x, y in h.get("samelen", []):
            if x in vals and y in vals and rng.random() < 0.55:
                vals[y] = fit_len(rng, vals[y], len(vals[x]), h["arrays"].get(y, {}), consts)
        for name, ty in case["params"]:
            if ty in named:
                vals[name] = gen_value(rng, ty, types, h["ints"].get(name, {}), consts, strict=strict)
            elif ty == "bool":
                vals[name] = rng.choice([True, False])
            elif ty == "Option<i64>":
                vals[name] = gen_opt(rng, h["ints"].get(name, {}), consts)
            elif ty == "Result<i64>":
                vals[name] = gen_res(rng, h["ints"].get(name, {}), h.get("errs", {}).get(name, {}), consts)
            elif ty != "array":
                vals[name] = pick_int(rng, h["ints"].get(name, {}), consts)
        for x, arr in h.get("pick", []):
            if vals.get(arr) and rng.random() < 0.5:
                vals[x] = rng.choice(vals[arr])
        for x, y in h.get("rel", []):
            if rng.random() < 0.6 and vals[x] >= vals[y]:
                vals[x], vals[y] = vals[y], vals[x]
                if vals[x] == vals[y]:
                    if vals[y] < I64_MAX:
                        vals[y] += 1
                    else:
                        vals[x] -= 1
        bias_inputs(rng, h, vals)
        out.append([vals[name] for name, _ in case["params"]])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pruv 퍼징 프로그램 생성 (.pruv 파일로 저장)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--out", default="bench/fuzz/out/generated")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    for i in range(a.count):
        case = generate_case(a.seed, i)
        with open(os.path.join(a.out, case["name"] + ".pruv"), "w") as fh:
            fh.write(case["src"])
    print("wrote %d files to %s" % (a.count, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
