#!/usr/bin/env python3
"""Vow 컴파일러 차분 퍼징용 프로그램 생성기 (표준 라이브러리만, Python 3.9).

    generate_case(seed, index) -> dict      결정적 (random.Random(f"{seed}:{index}"))
    candidate_inputs(case, rng, n) -> list  인자 목록 n개 (requires 경계 근처 편향)

    python bench/fuzz/generate.py --seed S --count N --out DIR   # .vow 파일로 눈으로 확인

생성 규칙: 매개변수는 불변, `let mut` 지역만 재대입, 모든 경로가 `return e;`로 끝남,
while에는 decreases(와 invariant), 이항식은 항상 괄호, 음수 리터럴은 `(-5)`.
기존 재료는 부수효과 없음. 새 계열(약 20%: arrfill/copy/effects/branches/nested/quant/helpers)은
`! io, alloc` 효과, 지역 배열, assert, 중첩 반복, bool 매개변수(params 타입 "bool"), 보조 함수를 쓴다.
"""
import argparse
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
    """Vow 리터럴: 음수는 (-5) 형태."""
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
        # idx: 배열 경계 근처 인덱스 매개변수 / div: 0·음수 편향 제수 / neg: 음수 편향
        # wide: i64 극단 편향 / exact: {이름: [정확한 경계값]} / empty: 빈 배열 편향
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


FAMILY_SHARE = 0.20
FAMILY = [("arrfill", tmpl_arrfill, 17), ("copy", tmpl_copy, 8), ("effects", tmpl_effects, 22),
          ("branches", tmpl_branches, 17), ("nested", tmpl_nested, 13), ("quant", tmpl_quant, 12),
          ("helpers", tmpl_helpers, 11)]


# ---------------------------------------------------------------- 케이스 조립

def render(ctx, body):
    tymap = {"array": "[i64]", "bool": "bool"}
    sig = ", ".join("%s: %s" % (n, tymap.get(t, "i64")) for n, t in ctx.params)
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
    return fsrc + "\n"


def generate_case(seed, index):
    rng = random.Random("%s:%s" % (seed, index))
    ctx = Ctx(rng)
    r = rng.random()
    if r < FAMILY_SHARE:
        kind, fn, _w = rng.choices(FAMILY, weights=[w for _, _, w in FAMILY])[0]
        body = fn(ctx)
        src = render(ctx, body)
        return {"name": "c%s_%s" % (seed, index), "src": src, "entry": "f", "params": ctx.params,
                "ret": ctx.ret, "kind": kind, "input_hints": ctx.hints}
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


def candidate_inputs(case, rng, n):
    h = case["input_hints"]
    consts = h.get("consts", [])
    out = []
    for _ in range(n):
        vals = {}
        for name, ty in case["params"]:
            if ty == "array":
                vals[name] = gen_array(rng, h["arrays"].get(name, {}), consts)
        for name, ty in case["params"]:
            if ty == "bool":
                vals[name] = rng.choice([True, False])
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
    ap = argparse.ArgumentParser(description="Vow 퍼징 프로그램 생성 (.vow 파일로 저장)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--out", default="bench/fuzz/out/generated")
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    for i in range(a.count):
        case = generate_case(a.seed, i)
        with open(os.path.join(a.out, case["name"] + ".vow"), "w") as fh:
            fh.write(case["src"])
    print("wrote %d files to %s" % (a.count, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
