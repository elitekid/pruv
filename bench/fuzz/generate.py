#!/usr/bin/env python3
"""Program generator for differential fuzzing of the Pruv compiler (standard library only, Python 3.9).

    generate_case(seed, index) -> dict      deterministic (random.Random(f"{seed}:{index}"))
    candidate_inputs(case, rng, n) -> list  n argument lists (biased near the requires boundaries)

    python bench/fuzz/generate.py --seed S --count N --out DIR   # write .pruv files for visual inspection

Generation rules: parameters are immutable, only `let mut` locals are reassigned, every path ends in `return e;`,
while loops carry decreases (and invariant), binary expressions are always parenthesized, negative literals are `(-5)`.
The original ingredients have no side effects. The new family (about 20%: arrfill/copy/effects/branches/nested/quant/helpers)
uses the `! io, alloc` effects, local arrays, assert, nested loops, bool parameters (params type "bool"), and helper functions.
The new family (about 30%: twoarr/arrret/option/optparam/struct) uses two array parameters, `-> [i64] ! alloc`,
Option/Result returns and parameters (params type "Option<i64>"/"Result<i64>", inputs are dicts of the form {"tag": "Some", "v": n}),
and top-level struct/enum (about 70% in the parameters/return of f, the rest in inner locals and helper functions).
The struct template also puts struct literals, enums, and Option/Result ==/!= into requires, and occasionally uses an empty struct (`Unit {}`),
Result fields, and enum fields. There is also a variant that observes evaluation order, single evaluation, and two-field overflow order via `tap(v) ! io`.

G2 mode (generate_case(.., g2=True)), G3 mode (generate_case(.., g3=True), generics, see the G3 block and bench/fuzz/README.md) and
G6 mode (generate_case(.., g6=True), trusted Rust calls and Vec/HashMap/String, see the G6 block) and
G9 mode (generate_case(.., g9=True), recursion / recursive types / buffer fields, see the G9 block) and
G4 mode (generate_case(.., g4=True), multi-file module programs, see the G4 block; the case carries `files`) and
G5 mode (generate_case(.., g5=True), inout parameters, see the G5 block; the case carries `files`) use their own
rng streams and templates; without them the output for a given seed is unchanged.
"""
import argparse
import copy
import os
import random
import sys

# Generation choices that avoid already-reported compiler defects (filled in by run.py --avoid-known).
# "fz01": in an index assignment `b[e1] = e2`, if e1 and e2 are both calls with effects, the evaluation order differs per mode
#         (tests/runtime/fz01_index_assign_order). To avoid it, bind the value to a local first.
AVOID = set()

I64_MIN = -(1 << 63)
I64_MAX = (1 << 63) - 1
BOUNDS = [10, 1000, 1000000, 2147483648]
EXTREMES = [I64_MIN, I64_MAX, I64_MIN + 1, I64_MAX - 1, 1 << 31, -(1 << 31),
            1 << 32, -(1 << 32), 1 << 62, -(1 << 62), (1 << 31) - 1, 1 << 40]
SMALL_CONSTS = [0, 1, 2, 3, 5, 7, 10, 100, 1000, -1, -2, -5, -100]
CMPS = ["<", "<=", ">", ">=", "==", "!="]


def lit(n):
    """Pruv literal: negatives take the (-5) form."""
    return str(n) if n >= 0 else "(-%d)" % (-n)


# ---------------------------------------------------------------- context / hints

class Ctx:
    def __init__(self, rng):
        self.rng = rng
        self.ints = []        # names of i64 parameters
        self.arr = None       # name of the array parameter ("a") or None
        self.params = []      # [[name, "i64"|"array"], ...] in declaration order
        self.requires = []
        self.ensures = []
        self.ret = "i64"
        self.helper = None    # source of fn g, or None
        self.undef_idx = None
        self.effects = []     # effects of f (exactly those of ["io", "alloc"] that it uses)
        self.after = False    # if True, put the helper function after f (forward call)
        self.types = None     # source of top-level struct/enum declarations, or None (placed first)
        self.type_info = None  # {"structs": {name: [[field, type], ...]}, "enums": {name: {variant: [[field, type], ...]}}}
        # idx: index parameters near array bounds / div: divisors biased to 0 and negatives / neg: negative bias
        # wide: i64 extremes bias / exact: {name: [exact boundary values]} / empty: empty-array bias
        # exact_val: {name: [value, ...]} exact values for struct/enum/Option/Result parameters (input JSON form)
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


# ---------------------------------------------------------------- expression generation

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


# ---------------------------------------------------------------- requires ingredients

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
        ctx.requires.append(test)  # unguarded: the verifier must reject with contract_domain
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
        ctx.requires.append(test)  # unguarded max/min: expect contract_domain
    ctx.hints["consts"].append(50)


def req_exists(ctx):
    x = ctx.rng.choice(ctx.ints)
    ctx.requires.append("exists k in 0..len(a): a[k] == %s" % x)
    ctx.hints["pick"].append([x, "a"])


SORTED_FORMS = [
    # (weight, text) — the first two are O(n) check forms, the rest are near-miss variants that must pass as ordinary checks
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


# (function, needs an integer, needs two integers, needs an array)
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


# ---------------------------------------------------------------- helper function g

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
        ens = ["result >= (-5)"]  # may be false
    if info is not None:
        info["req"] = list(req)
        info["B"] = B
    lines = ["fn g(p: i64, q: i64) -> i64"]
    lines += ["  requires " + r for r in req]
    lines += ["  ensures " + e for e in ens]
    lines += ["{", "  return %s;" % body, "}"]
    return "\n".join(lines)


# ---------------------------------------------------------------- body: pure / straight

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
            e = index_expr(rng, vars_, arr)  # unguarded index
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


# ---------------------------------------------------------------- loop templates

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
    """Mutation used to build near-miss programs. extra: {name: function(parts)}."""
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
    set_int(ctx, "n", cap=3000)  # cap the iteration count so the binary does not run for long
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

I64_MIN_EXPR = "((-9223372036854775807) - 1)"   # contract literals are mathematical, but negatives are written this way


# ---------------------------------------------------------------- new ingredient 1: requires undefined (undef)

def undef_req(ctx, kind, guarded):
    """List of requires lines containing partial contract operations. With guarded=False the guard is placed later, missing, or in a different order."""
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
    # forall / exists: 0..x can exceed len(a)
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


# ---------------------------------------------------------------- new ingredient 2: nonlinear contracts exceeding i128

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
        ctx.requires += [prod] + bounds   # the bounds come after the product, so the product can become undefined first
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


# ---------------------------------------------------------------- new ingredient 3: Euclidean contract division/remainder

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


# ---------------------------------------------------------------- new ingredient 4: sortedness precondition

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


# ---------------------------------------------------------------- new ingredient 5: i64 boundary arithmetic

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


# ---------------------------------------------------------------- new ingredient 6: guards for code division/remainder

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


# ---------------------------------------------------------------- new ingredient 7: call precondition holds only for some inputs

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


# ---------------------------------------------------------------- new family: local arrays / effects / assert / nested loops /
# bool / quantified ensures / helper functions (features missed in the audit)

def declare2(ctx, ints, arr, bools):
    """declare + bool parameters. Parameter types: "i64" | "array" | "bool"."""
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
    """Shift the arr[var] writes in the body by one slot to make an index_oob near miss."""
    def f(p):
        p["body"] = [s.replace("%s[%s]" % (arr, var), "%s[(%s + 1)]" % (arr, var)) for s in p["body"]]
    return f


def bound_elem(ctx, B):
    ctx.requires.append("forall k in 0..len(a): ((%s <= a[k]) && (a[k] <= %d))" % (lit(-B), B))
    set_arr(ctx, "a", elem=(-B, B))


# -- 1) local array: fill with alloc

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
            ctx.requires.append("n <= 100")          # negative n: the alloc precondition cannot be proven
            set_int(ctx, "n", hi=100)
        else:
            ctx.requires.append("0 <= n")            # no upper bound: the alloc precondition cannot be proven
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
        # ensures can only see parameters (no local b): since len(b) == N, write it as N
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


# -- 1) local array: copy

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


# -- 2) effects and evaluation order

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
        H[rng.choice(["ia", "ib"])][1] = N          # near miss: the index helper returns N
    weak = set()
    if rng.random() < 0.06:
        weak.add(rng.choice(["ia", "ib"]))          # no ensures: the caller cannot prove the index
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


# -- 3,5,6) assert / else if / nested if / block locals / bool

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


# -- 4) nested loops / consecutive loops

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


# -- 7) ensures using exists / forall / min / max / ==>

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


# -- 8) helper function with a loop + a second helper function calling it (including forward calls)

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


# ---------------------------------------------------------------- new family 2: two arrays / array return /
# Option/Result return and parameters / struct/enum. params types: "i64"|"bool"|"array"|"Option<i64>"|"Result<i64>"

def declare_list(ctx, params, shuffle=True):
    """Set the parameter list [[name, type], ...]. Array names are a, b."""
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
            hint_int(ctx, n)      # struct/enum arguments use the same hint (applied to all i64 fields inside)


def bnd(ctx, name, B):
    ctx.requires.append("(%s <= %s) && (%s <= %d)" % (lit(-B), name, name, B))
    set_int(ctx, name, lo=-B, hi=B)


def elem_bound(ctx, arr, B):
    ctx.requires.append("forall k in 0..len(%s): ((%s <= %s[k]) && (%s[k] <= %d))" % (arr, lit(-B), arr, arr, B))
    set_arr(ctx, arr, elem=(-B, B))


def maybe_bad_ensures(ctx, p=0.08):
    """Skew the last `result == E` ensures into `result == (E + 1)` (must be rejected)."""
    if ctx.ensures and ctx.rng.random() < p and ctx.ensures[-1].startswith("result == "):
        ctx.ensures[-1] = "result == (%s + 1)" % ctx.ensures[-1][len("result == "):]


# -- 1) two array parameters

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
    if lenreq and rng.random() < 0.82:       # occasionally drop the length condition: must be rejected
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


# -- 2) array return `-> [i64] ! alloc`

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


# -- 3) Option / Result return

# helper function that observes evaluation order and single evaluation through io output (the name tap does not collide with other helpers)
TAP_FN = "\n".join(["fn tap(v: i64) -> i64 ! io", "  ensures result == v", "{", "  print(v);", "  return v;", "}"])


def tmpl_option_tap(ctx, res):
    """Put tap(io) into Some(..)/Ok(..) arguments, match scrutinee expressions, and call arguments to observe evaluation order and single evaluation."""
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
    if v == "match":        # match g(tap(x)) {..}: tap must be evaluated exactly once
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
    elif v == "arg":        # Some(tap(x)) inside a call argument
        h = ["fn h(o: %s) -> i64" % T,      # put a bound so w + 1 does not overflow (always rejected without it)
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
    else:                   # two taps in one constructor: from the left
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
            ctx.ensures.append("(%s(result) || (%s(result) >= 0))" % (is_, val))   # unguarded *_val: must be rejected
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
        if rng.random() >= 0.1:              # occasionally drop the y check: must be rejected
            L += ["  if (y <= 0) {", "    return %s;" % bad1, "  }"]
        if not nonneg:
            L += ["  if (x < 0) {", "    return %s;" % bad2, "  }"]
        L.append("  return %s;" % ("Ok((x / y))" if res else "Some((x / y))"))
        if rng.random() < 0.08:
            ctx.ensures.append("(%s(result) || (%s(result) >= 0))" % (is_, val))   # unguarded *_val: must be rejected
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
    # the helper function returns an Option/Result and f unpacks it with match
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


# -- 4) Option / Result parameters

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
        ctx.requires.append("(0 <= %s) && (%s <= %d)" % (V, V, B))      # requires undefined for None/Err
    else:
        ctx.requires.append("(0 <= %s) && (%s <= %d) && %s(%s)" % (V, V, B, is_, pn))
    if res:
        ctx.hints["errs"] = {pn: {"lo": -B, "hi": B}}
        if rng.random() < 0.92:
            ctx.requires.append("(!is_ok(r)) ==> ((%s <= err_val(r)) && (err_val(r) <= %d))" % (lit(-B), B))
    if with_x:
        bnd(ctx, "x", B)
    if rng.random() < 0.5:      # Option/Result comparison ingredient (the run-time requires check performs the value comparison)
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


# -- 5) struct / enum (about 70% in the parameters/return of f, the rest only in inner locals and helper functions)

TAP_SCENARIOS = ["tlit", "tenum", "tsome", "tmatch", "tcall", "tover"]


def tmpl_struct(ctx):
    rng = ctx.rng
    P = rng.choice(["Point", "Pair", "Spot"])
    Q = rng.choice(["Frame", "Panel", "Holder"])
    E = rng.choice(["Event", "Shape", "Msg"])
    M = "Mode"                  # for the enum field inside the struct (E contains P, so keep this separate to avoid recursion)
    has_ok = rng.random() < 0.35
    has_opt = rng.random() < 0.3
    has_res = rng.random() < 0.1      # Result<i64> field res
    has_ef = rng.random() < 0.1       # enum field m: Mode
    has_unit = rng.random() < 0.1     # empty struct field u: Unit
    pv = rng.choice([("Hit", "Fail"), ("Hit", "Fail"), ("Hit",), ("Fail",)])
    B = rng.choice([1000, 100000, 1000000])
    if rng.random() < 0.7:      # 70%: f handles structs/enums as arguments/returns
        sc = rng.choice(["pval", "pret", "qval", "eval", "eret", "emix"])
    elif rng.random() < 0.7:    # about 70% of the remaining 30% are variants that observe evaluation order via io (about 21% overall)
        sc = rng.choice(TAP_SCENARIOS)
    else:
        sc = rng.choice(["lit", "mut", "copy", "nested", "loopf", "loopa", "mk", "shift", "chain", "chain",
                         "ematch", "optf"])
    if sc in ("optf", "tsome"):
        has_opt = True
    quiet = {"opt": "None", "res": "Err(1)", "m": "%s::Off" % M}     # tap variants: so that field defaults do not repeat tap
    tinfo = {"structs": {}, "enums": {}}
    bound_reqs = []             # [(requires clause, parameter name)] bound contracts of which one can be dropped by mutation

    def plit(xe, ye, opt=None, ok=None, res=None, m=None):
        """Struct literal: fields are always in declaration order (x, y, ok, opt, res, m, u)."""
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
        """One requires that bounds the i64 expression ex to [-B, B] (name: the parameter the hint is attached to)."""
        r = "(%s <= %s) && (%s <= %d)" % (lit(-B), ex, ex, B)
        ctx.requires.append(r)
        bound_reqs.append((r, name))
        set_int(ctx, name, lo=-B, hi=B)

    def obound(ex, name):
        """Bound the value of the Option<i64> expression ex. some_val is guarded with is_some."""
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
        """Payload bound of the enum parameter name. Uses a guarded variant_field, and occasionally leaves the Fail side unguarded."""
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
                r = inner                        # unguarded variant_field: must be rejected (requires undefined in safe mode)
            else:
                r = "(!%s) || (%s)" % (iv(name, "Fail"), inner)
            ctx.requires.append(r)
            bound_reqs.append((r, name))

    def drop_bound(p=0.12):
        """Drop one bound contract: overflow can no longer be proven, so it must be rejected (the input hint is released too)."""
        if bound_reqs and rng.random() < p:
            r, name = rng.choice(bound_reqs)
            ctx.requires.remove(r)
            h = hint_int(ctx, name)
            h["lo"] = h["hi"] = None

    def bump_ens(old, new):
        """Skew the first ensures clause that contains old."""
        for i, s in enumerate(ctx.ensures):
            if old in s:
                ctx.ensures[i] = s.replace(old, new, 1)
                return

    def x_bound(name="x"):
        if rng.random() < 0.93:
            bnd(ctx, name, B)
        else:
            set_int(ctx, name, lo=-B, hi=B)      # unguarded: overflow cannot be proven, so it must be rejected

    pending_exact = []          # [(parameter name, value-building function)] resolved after types_text and put into hints["exact_val"]

    def zero(ty):
        """Zero value of type ty (input JSON form). Call only after types_text."""
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
        """Variant value of enum E (field name -> value; fields not given get the zero value)."""
        return {"enum": E, "variant": var,
                "fields": {fn: kw.get(fn, zero(ft)) for fn, ft in tinfo["enums"][E][var]}}

    def cmp_req(p=None, v=None, pparam=None, e=None, eparam=None, p_prob=0.6):
        """Add one more struct literal / enum ==/!= comparison to requires (the run-time requires check computes in i128).
        p: struct path (e.g. "p", "q.p"), v: i64 expression to multiply by, pparam: the name of p if p is exactly a parameter name,
        e: enum parameter name. Also attaches an exact_val hint so inputs both satisfy and violate this condition."""
        if rng.random() >= p_prob:
            return
        opts = []
        if p:
            cp = dict(opt="%s.opt" % p, ok="%s.ok" % p, res="%s.res" % p, m="%s.m" % p)
            sq = rng.choice(["(%s * %s)" % (v, v), "(%s * %s)" % (v, v), "((%s * %s) * %s)" % (v, v, v)])
            opts.append(("%s != %s" % (p, plit(sq, "0", **cp)), "p0"))     # the product can exceed i64 (contract arithmetic)
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
            # zero value (x=0, y=0): exactly equal to the comparison, so it violates; a value with x=1 satisfies
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
            g.append("  ensures result == %s" % plit("x", "y"))      # if there are more fields, all in declaration order
        if has_opt and rng.random() < 0.7:
            g.append("  ensures is_some(result.opt) && (some_val(result.opt) == x)")
        if len(g) > 2 and rng.random() < 0.1:
            g.pop(rng.randrange(1, len(g)))      # shrinking the contract can break the caller-side proof
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
            D = 2000000                          # helper function requires violated: must be rejected
        g = ["fn shift(p: %s, dx: i64) -> %s" % (P, P),
             "  requires ((-1000000) <= p.x) && (p.x <= 1000000)",
             "  requires ((-1000000) <= dx) && (dx <= 1000000)",
             "  ensures result.x == (p.x + dx)", "  ensures result.y == p.y", "{",
             "  let mut q: %s = p;" % P, "  q.x = (q.x + dx);", "  return q;", "}"]
        ctx.helper, ctx.after = "\n".join(g), rng.random() < 0.4
        body = ["  let p: %s = %s;" % (P, plit("x", "1")), "  let r: %s = shift(p, %s);" % (P, lit(D))]
        if rng.random() < 0.4:      # reuse the caller's original value p after the call (copy across the call)
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
            wens.pop(rng.randrange(len(wens)))   # drop one contract: the caller-side requires proof can break
        wrap = ["fn wrap(x: i64) -> %s" % E] + ["  ensures " + w for w in wens]
        wrap += ["{", "  if (x > 0) {", "    return %s;" % A, "  }", "  return %s;" % Bv, "}"]
        sreq = []
        if hit:
            sreq.append("(!%s) || ((%s.x >= 0) && (%s.y >= 0))"
                        % (iv("e", "Hit"), vf("e", "Hit", "pt"), vf("e", "Hit", "pt")))
        if fail:
            if rng.random() < 0.1:
                sreq.append("%s >= 0" % vf("e", "Fail", "code"))        # unguarded: expect variant_domain
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
        extra_u = has_unit and rng.random() < 0.5      # f also takes the empty struct as an argument
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
        okf = has_ok and v != "swap" and rng.random() < 0.4      # also change the ok field
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
            bump_ens("result.x == (p.x + dx)", "result.x == ((p.x + dx) + 1)")    # skewed ensures: must be rejected
    elif sc == "qval":      # f(q: Q) -> Q or i64, nested field assignment
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
        if any("(result == 0)" in s for s in ctx.ensures) and rng.random() < 0.08:    # only when there is a target
            bump_ens("(result == 0)", "(result == 1)")
    elif sc == "eret":      # f(x: i64) -> E, a branch picks the variant
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
        if rng.random() < 0.1:      # skewed ensures: pick only those where the clause actually changes
            muts = []
            for i in range(3):
                s = ctx.ensures[i]
                t = s.replace("== x", "== (x + 1)", 1).replace("== (0 - x)", "== x", 1)
                if t == s and s.startswith("((x == 0) ==> "):
                    t = s.replace("==> ", "==> !", 1)       # claims it is not Empty although x == 0
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
    elif sc == "tlit":      # struct literal field evaluation order: from the left (the tap output order is compared)
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        ctx.effects = ["io"]
        ctx.helper, ctx.after = TAP_FN, rng.random() < 0.4
        xe, ye, ens = rng.choice([("tap(x)", "tap((x + 1))", "((x + x) + 1)"), ("tap(x)", "tap(2)", "(x + 2)"),
                                  ("(tap(x) + 1)", "tap(x)", "((x + 1) + x)")])
        ctx.ensures.append("result == %s" % ens)
        body = ["  let p: %s = %s;" % (P, plit(xe, ye, **quiet)), "  return (p.x + p.y);"]
    elif sc == "tenum":     # tap in enum constructor arguments; occasionally the match scrutinee pick(..) evaluates e only once
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
    elif sc == "tsome":     # Option field Some(tap(x))
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        ctx.effects = ["io"]
        ctx.helper, ctx.after = TAP_FN, rng.random() < 0.4
        ctx.ensures.append("result == (x + 1)")
        body = ["  let p: %s = %s;" % (P, plit("x", "1", opt="Some(tap(x))", res="Err(1)", m="%s::Off" % M)),
                "  match p.opt {", "    Some(v) => { return (v + p.y); }", "    None => { return 0; }", "  }"]
    elif sc == "tmatch":    # match g(tap(x)): the scrutinee expression is evaluated only once
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
                 "  ensures (v > 0) ==> (%s && (%s.x == v) && (%s.y == 1) && %s)"     # ok and y must be stated too for f to be proven
                 % (iv("result", "Hit"), vf("result", "Hit", "pt"), vf("result", "Hit", "pt"), vf("result", "Hit", "ok")),
                 "  ensures (v <= 0) ==> %s" % iv("result", "Empty"), "{",
                 "  if (v > 0) {", "    return %s::Hit(%s, true);" % (E, plit("v", "1", **quiet)), "  }",
                 "  return %s::Empty;" % E, "}"]
        ctx.helper, ctx.after = TAP_FN + "\n\n" + "\n".join(g), rng.random() < 0.4
        ctx.ensures += ["((x > 0) ==> (result == x))", "((x <= 0) ==> (result == 0))"]
        body = ["  match g(tap(x)) {"] + arms() + ["  }"]
    elif sc == "tcall":     # call arguments: the tap inside the struct literal comes before the later argument's tap
        declare_list(ctx, [["x", "i64"]])
        x_bound()
        ctx.effects = ["io"]
        g = ["fn addx(p: %s, k: i64) -> i64" % P,       # sum is an aggregate keyword, so it is not used
             "  requires ((-1000000) <= p.x) && (p.x <= 1000000)", "  requires ((-1000000) <= k) && (k <= 1000000)",
             "  ensures result == (p.x + k)", "{", "  return (p.x + k);", "}"]
        ctx.helper, ctx.after = TAP_FN + "\n\n" + "\n".join(g), rng.random() < 0.4
        ctx.ensures.append("result == (x + 2)")
        body = ["  return addx(%s, tap(2));" % plit("tap(x)", "1", **quiet)]
    elif sc == "tover":     # two fields overflowing through different operations: observe whether the left field's error comes first
        a, b, c, d = "a", "b", "c", "d"
        declare_list(ctx, [[n, "i64"] for n in (a, b, c, d)])
        mode = rng.choices(["ok", "both", "right", "left"], weights=[45, 25, 15, 15])[0]   # right/left: only that side can overflow
        B = rng.choice([1000, 1000000])
        use_tap = rng.random() < 0.5
        for n in (a, b):
            if mode in ("ok", "right"):
                bnd(ctx, n, B)
        for n in (c, d):
            if mode in ("ok", "left"):
                bnd(ctx, n, B)
        ex = {}
        if mode in ("both", "left"):        # values where the left side (a + b) overflows easily
            ex[a], ex[b] = [I64_MAX, I64_MAX - 1], [I64_MAX, 1, 2, 1 << 62]
        if mode in ("both", "right"):       # values where the right side (c * d) overflows easily
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
    else:  # optf: Option/Result/enum fields
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


FAMILY_SHARE = 0.50      # existing family 20% + new family (two arrays, array return, Option/Result, struct) 30%
FAMILY = [("arrfill", tmpl_arrfill, 17), ("copy", tmpl_copy, 8), ("effects", tmpl_effects, 22),
          ("branches", tmpl_branches, 17), ("nested", tmpl_nested, 13), ("quant", tmpl_quant, 12),
          ("helpers", tmpl_helpers, 11),
          ("twoarr", tmpl_twoarr, 28), ("arrret", tmpl_arrret, 34), ("option", tmpl_option, 32),
          ("optparam", tmpl_optparam, 20), ("struct", tmpl_struct, 60)]


# ---------------------------------------------------------------- G2 mode (--g2)
# Programs that use typed-element arrays [u8], [bool] and UTF-8 strings (str). Completely separate from the existing FAMILY and ingredients
# (only generate_case(seed, index, g2=True) uses this block, and it also creates its own rng).

G2_BAD_RATE = 0.3
G2_LIM = 1000000
G2_SPECIAL_BYTES = [0, 1, 127, 128, 191, 192, 254, 255]
G2_ESC = {'"': '\\"', "\\": "\\\\", "\n": "\\n", "\r": "\\r", "\t": "\\t", "\0": "\\0"}
G2_TYMAP = {"i64": "i64", "array": "[i64]", "array_u8": "[u8]", "array_bool": "[bool]", "str": "str", "bool": "bool"}


def g2_esc(s):
    """Pruv string literal escaping (only \\\" \\\\ \\n \\r \\t \\0). Other characters are kept as is."""
    return "".join(G2_ESC.get(c, c) for c in s)


def g2_char(rng):
    """ASCII 1/2 (printable characters + \\0 \\n \\t \\r \" \\), 2-, 3-, and 4-byte characters 1/6 each (surrogates excluded)."""
    r = rng.random()
    if r < 0.5:
        if rng.random() < 0.7:
            return chr(rng.randint(0x20, 0x7E))
        return rng.choice(["\0", "\n", "\t", "\r", '"', "\\", '"', "\\"])
    if r < 0.5 + 1 / 6.0:
        return chr(rng.randint(0x80, 0x7FF))
    if r < 0.5 + 2 / 6.0:
        c = rng.randint(0x800, 0xFFFF)
        if 0xD800 <= c <= 0xDFFF:
            c = 0xE000 + (c - 0xD800)
        return chr(c)
    return chr(rng.randint(0x10000, 0x10FFFF))


def g2_multibyte_char(rng):
    return rng.choice([chr(rng.randint(0x80, 0x7FF)), chr(rng.randint(0x800, 0xD7FF)),
                       chr(rng.randint(0xE000, 0xFFFF)), chr(rng.randint(0x10000, 0x10FFFF))])


def g2_lit_text(rng, need_multi=False):
    n = rng.randint(1, 6)
    cs = [g2_char(rng) for _ in range(n)]
    if need_multi and not any(ord(c) >= 0x80 for c in cs):
        cs[rng.randrange(n)] = g2_multibyte_char(rng)
    return "".join(cs)


def g2_offsets(text):
    """List of byte offsets where each character starts (the total length at the end)."""
    out, o = [], 0
    for c in text:
        out.append(o)
        o += len(c.encode("utf-8"))
    out.append(o)
    return out


def g2_hints():
    h = {"ints": {}, "arrays": {}, "consts": [3, 5, 10, 100], "rel": [], "pick": [], "idx": [], "div": [],
         "neg": [], "wide": [], "exact": {}, "empty": False}
    h["g2rel"] = {}       # {integer parameter: name of the parameter whose length it follows, or a constant length}
    h["g2small"] = {}     # {integer parameter: small upper bound to pick often}
    h["g2order"] = []     # [(x, y)] occasionally arranged so that x <= y
    return h


def g2_int_hint(h, name, lo=None, hi=None):
    h["ints"][name] = {"lo": lo, "hi": hi, "cap": None}


def g2_fn(params, ret, effects, requires, ensures, body):
    sig = ", ".join("%s: %s" % (n, G2_TYMAP[t]) for n, t in params)
    head = "fn f(%s) -> %s" % (sig, G2_TYMAP[ret])
    if effects:
        head += " ! " + ", ".join(effects)
    out = [head] + ["  requires " + r for r in requires] + ["  ensures " + e for e in ensures] + ["{"] + body + ["}"]
    return "\n".join(out)


def g2_loop(bound, invs, body, bad=False, ivar="i"):
    """`let mut i: i64 = 0;` + while i < bound.  If bad, the end value is +1 (read out of index range)."""
    hi = ("%s + 1" % bound) if bad else bound
    out = ["  let mut %s: i64 = 0;" % ivar, "  while %s < %s" % (ivar, hi),
           "    invariant 0 <= %s && %s <= %s" % (ivar, ivar, hi)]
    out += ["    invariant " + x for x in invs]
    out += ["    decreases %s - %s" % (hi, ivar), "  {"]
    out += ["    " + l for l in body]
    out += ["    %s = %s + 1;" % (ivar, ivar), "  }"]
    return out


def g2_case_parts(src, params, ret, hints, feats):
    return {"src": src + "\n", "params": params, "ret": ret, "hints": hints, "feats": feats}


# 1) [i64] -> [u8] clamping loop store (q01 shape)
def g2_clamp(rng):
    lo = rng.choice([0, 0, 0, 5, 16])
    hi = rng.choice([255, 255, 200, 100, 127])
    bad = rng.random() < G2_BAD_RATE
    body = ["  let mut out: [u8] = alloc(len(a), %d);" % rng.choice([0, 0, lo])]
    inner = ["let x: i64 = a[i];"]
    if bad:
        inner += ["if x < %d {" % lo, "  out[i] = %d;" % lo, "} else {", "  out[i] = x;", "}"]
    else:
        inner += ["if x < %d {" % lo, "  out[i] = %d;" % lo, "} else if x > %d {" % hi, "  out[i] = %d;" % hi,
                  "} else {", "  out[i] = x;", "}"]
    body += g2_loop("len(a)", ["len(out) == len(a)"], inner)
    body.append("  return out;")
    src = g2_fn([["a", "array"]], "array_u8", ["alloc"], ["len(a) <= %d" % G2_LIM], ["len(result) == len(a)"], body)
    h = g2_hints()
    return g2_case_parts(src, [["a", "array"]], "array_u8", h, ["alloc_u8", "ret_u8", "store_u8", "u8"])


# 2) [u8] parameter scan (sum, max, count)
def g2_u8_scan(rng):
    mode = rng.choice(["sum", "max", "count"])
    bad = rng.random() < G2_BAD_RATE
    reqs = ["len(a) <= %d" % G2_LIM]
    if mode == "sum":
        pre = ["  let mut t: i64 = 0;"]
        invs = ["0 <= t && t <= %d * i" % (254 if bad else 255)]
        inner = ["t = t + a[i];"]
        ens, ret = ["0 <= result && result <= 255 * len(a)"], "t"
    elif mode == "max":
        pre = ["  let mut m: i64 = 0;"]
        invs = ["0 <= m && m <= 255"]
        inner = ["let v: i64 = a[i];", "if v > m {", "  m = v;", "}"]
        ens, ret = ["0 <= result && result <= %d" % (254 if bad else 255)], "m"
    else:
        T = rng.choice([1, 128, 200, 255, 0])
        pre = ["  let mut c: i64 = 0;"]
        invs = ["0 <= c && c <= i"]
        inner = ["if a[i] %s %d {" % (rng.choice([">=", "==", "<"]), T), "  c = c + 1;", "}"]
        ens, ret = ["0 <= result && result %s len(a)" % ("<" if bad else "<=")], "c"
    body = pre + g2_loop("len(a)", invs, inner) + ["  return %s;" % ret]
    src = g2_fn([["a", "array_u8"]], "i64", [], reqs, ens, body)
    return g2_case_parts(src, [["a", "array_u8"]], "i64", g2_hints(), ["u8"])


# 3) [u8] copy, then element update (+d saturating) and return
def g2_copy_update(rng):
    use_d = rng.random() < 0.6
    D = rng.choice([1, 7, 100, 255, 300, -1, -50, -255, 0])
    bad = rng.random() < G2_BAD_RATE
    reqs, params = [], [["a", "array_u8"]]
    h = g2_hints()
    if use_d:
        params.append(["d", "i64"])
        reqs.append("-255 <= d && d <= 255")
        g2_int_hint(h, "d", -255, 255)
        E = "d"
    else:
        E = lit(D)
    reqs.append("len(a) <= %d" % G2_LIM)
    drop = None
    if bad:
        drop = rng.choice(["lo", "hi"]) if use_d else ("hi" if D >= 0 else "lo")
        if not use_d and D == 0:
            drop = "hi"
        if not use_d and D >= 0:
            drop = "hi"
    inner = ["let v: i64 = a[i] + %s;" % E]
    if drop == "hi":
        inner += ["if v < 0 {", "  out[i] = 0;", "} else {", "  out[i] = v;", "}"]
    elif drop == "lo":
        inner += ["if v > 255 {", "  out[i] = 255;", "} else {", "  out[i] = v;", "}"]
    else:
        inner += ["if v < 0 {", "  out[i] = 0;", "} else if v > 255 {", "  out[i] = 255;", "} else {",
                  "  out[i] = v;", "}"]
    body = ["  let mut out: [u8] = copy(a);"] + g2_loop("len(a)", ["len(out) == len(a)"], inner) + ["  return out;"]
    src = g2_fn(params, "array_u8", ["alloc"], reqs, ["len(result) == len(a)"], body)
    return g2_case_parts(src, params, "array_u8", h, ["ret_u8", "store_u8", "u8"])


# 4) build a [u8] with alloc and return it
def g2_alloc_u8(rng):
    mode = rng.choice(["direct", "fill", "calc"])
    bad = rng.random() < G2_BAD_RATE
    V = rng.choice([0, 1, 63, 127, 128, 255])
    reqs = ["0 <= n && n <= %d" % G2_LIM]
    h = g2_hints()
    g2_int_hint(h, "n", 0, G2_LIM)
    h["g2small"]["n"] = 8
    feats = ["alloc_u8", "ret_u8", "u8"]
    init = 256 if (bad and mode != "fill") else V
    if mode == "direct":
        body = ["  return alloc(n, %d);" % init]
    else:
        W = 256 if (bad and mode == "fill") else rng.choice([0, 9, 128, 255])
        body = ["  let mut out: [u8] = alloc(n, %d);" % init]
        if mode == "fill":
            inner = ["out[i] = %d;" % W]
        else:
            C = rng.choice([0, 1, 3, 100])
            inner = ["let x: i64 = i + %d;" % C, "if x > 255 {", "  out[i] = 255;", "} else {", "  out[i] = x;", "}"]
        body += g2_loop("n", ["len(out) == n"], inner) + ["  return out;"]
        feats.append("store_u8")
    src = g2_fn([["n", "i64"]], "array_u8", ["alloc"], reqs, ["len(result) == n"], body)
    return g2_case_parts(src, [["n", "i64"]], "array_u8", h, feats)


# 5) [bool] parameter aggregation (count, longest run)
def g2_bool_agg(rng):
    mode = rng.choice(["count", "count", "run"])
    bad = rng.random() < 0.25
    reqs = ["len(a) <= %d" % G2_LIM]
    if mode == "count":
        cond = rng.choice(["a[i]", "!a[i]", "a[i] == true"])
        pre = ["  let mut c: i64 = 0;"]
        invs = [] if bad else ["0 <= c && c <= i"]
        inner = ["if %s {" % cond, "  c = c + 1;", "}"]
        ens, ret = ["0 <= result && result <= len(a)"], "c"
        if bad:
            invs = ["0 <= c"]
    else:
        pre = ["  let mut best: i64 = 0;", "  let mut cur: i64 = 0;"]
        invs = ["0 <= cur && cur <= i", "0 <= best && best <= i"]
        if bad:
            invs = ["0 <= cur", "0 <= best && best <= i"]
        inner = ["if a[i] {", "  cur = cur + 1;", "  if cur > best {", "    best = cur;", "  }", "} else {",
                 "  cur = 0;", "}"]
        ens, ret = ["0 <= result && result <= len(a)"], "best"
    body = pre + g2_loop("len(a)", invs, inner) + ["  return %s;" % ret]
    src = g2_fn([["a", "array_bool"]], "i64", [], reqs, ens, body)
    return g2_case_parts(src, [["a", "array_bool"]], "i64", g2_hints(), ["bool_arr"])


# 6) build a [bool] and return it
def g2_bool_build(rng):
    ty = rng.choice(["array", "array_u8"])
    T = rng.choice([0, 1, 100, 128, 255]) if ty == "array_u8" else rng.choice([0, 5, -3, 100])
    bad = rng.random() < G2_BAD_RATE
    idx = "i + 1" if bad else "i"
    init = rng.choice(["false", "true"])
    inner = ["if a[i] > %s {" % lit(T), "  out[%s] = %s;" % (idx, "true" if init == "false" else "false"), "}"]
    body = ["  let mut out: [bool] = alloc(len(a), %s);" % init]
    body += g2_loop("len(a)", ["len(out) == len(a)"], inner) + ["  return out;"]
    src = g2_fn([["a", ty]], "array_bool", ["alloc"], ["len(a) <= %d" % G2_LIM], ["len(result) == len(a)"], body)
    feats = ["alloc_bool", "bool_arr", "ret_bool"] + (["u8"] if ty == "array_u8" else [])
    return g2_case_parts(src, [["a", ty]], "array_bool", g2_hints(), feats)


# 7) str parameter byte scan (count of a given byte, character count, first position)
def g2_str_scan(rng):
    mode = rng.choice(["count_ge", "count_eq", "chars", "find"])
    bad = rng.random() < G2_BAD_RATE
    reqs = ["len(s) <= %d" % G2_LIM]
    if mode == "find":
        X = rng.choice([0, 10, 34, 92, 97, 128, 195, 240])
        inner = ["if s[i] == %d {" % X, "  return i;", "}"]
        body = g2_loop("len(s)", [], inner, bad=bad)
        body = body + ["  return (-1);"]
        ens = ["-1 <= result && result < len(s)"]
    else:
        pre = ["  let mut c: i64 = 0;"]
        if mode == "count_ge":
            inner = ["let b: i64 = s[i];", "if b >= %d {" % rng.choice([128, 192, 65]), "  c = c + 1;", "}"]
        elif mode == "count_eq":
            inner = ["let b: i64 = s[i];", "if b == %d {" % rng.choice([0, 10, 34, 92, 195, 97]), "  c = c + 1;", "}"]
        else:
            inner = ["let b: i64 = s[i];", "if b < 128 {", "  c = c + 1;", "} else if b > 191 {", "  c = c + 1;", "}"]
        body = pre + g2_loop("len(s)", ["0 <= c && c <= i"], inner, bad=bad) + ["  return c;"]
        ens = ["0 <= result && result <= len(s)"]
    src = g2_fn([["s", "str"]], "i64", [], reqs, ens, body)
    return g2_case_parts(src, [["s", "str"]], "i64", g2_hints(), ["str"])


# 8) str boundary substring (substr after a guard, or a loop advancing to the next boundary)
def g2_str_substr(rng):
    mode = rng.choice(["guard", "guard_tail", "two", "prefix", "skip"])
    bad = rng.random() < G2_BAD_RATE
    h = g2_hints()
    feats = ["boundary", "ret_str", "str", "substr"]
    if mode in ("guard", "guard_tail"):
        reqs = ["0 <= i && i <= len(s)"]
        g2_int_hint(h, "i", 0, None)
        h["g2rel"]["i"] = "s"
        if mode == "guard":
            sub = "substr(s, 0, i)"
            badsub = "substr(s, 0, i + 1)"
        else:
            sub = "substr(s, i, len(s))"
            badsub = "substr(s, i, len(s) + 1)"
        if bad and rng.random() < 0.5:
            body = ["  return %s;" % sub]
        else:
            use = badsub if bad else sub
            body = ["  if is_char_boundary(s, i) {", "    return %s;" % use, "  } else {", "    return copy(s);", "  }"]
        params = [["s", "str"], ["i", "i64"]]
        ens = []
    elif mode == "two":
        reqs = ["0 <= lo && lo <= hi && hi <= len(s)"]
        for x in ("lo", "hi"):
            g2_int_hint(h, x, 0, None)
            h["g2rel"][x] = "s"
        h["g2order"].append(("lo", "hi"))
        if bad and rng.random() < 0.5:
            body = ["  return substr(s, lo, hi);"]
        else:
            body = ["  if is_char_boundary(s, lo) && is_char_boundary(s, hi) {",
                    "    return substr(s, lo, %s);" % ("hi + 1" if bad else "hi"),
                    "  } else {", "    return copy(s);", "  }"]
        params = [["s", "str"], ["lo", "i64"], ["hi", "i64"]]
        ens = []
    else:
        reqs = ["0 <= k && k <= %d" % G2_LIM, "len(s) <= %d" % G2_LIM]
        g2_int_hint(h, "k", 0, G2_LIM)
        h["g2small"]["k"] = 6
        outer_inv = ["0 <= c && c <= k"]
        if not bad:
            outer_inv.append("is_char_boundary(s, i)")
        body = ["  let mut i: i64 = 0;", "  let mut c: i64 = 0;", "  while i < len(s) && c < k",
                "    invariant 0 <= i && i <= len(s)"] + ["    invariant " + x for x in outer_inv]
        body += ["    decreases len(s) - i", "  {", "    let mut j: i64 = i + 1;",
                 "    while j < len(s) && !is_char_boundary(s, j)",
                 "      invariant i < j && j <= len(s)", "      decreases len(s) - j", "    {",
                 "      j = j + 1;", "    }", "    i = j;", "    c = c + 1;", "  }"]
        body.append("  return substr(s, 0, i);" if mode == "prefix" else "  return substr(s, i, len(s));")
        params = [["s", "str"], ["k", "i64"]]
        ens = ["len(result) <= len(s)"]
    src = g2_fn(params, "str", ["alloc"], reqs, ens, body)
    return g2_case_parts(src, params, "str", h, feats)


# 9) string literal inside code
def g2_literal(rng):
    mode = rng.choice(["byte", "len_add", "cut", "cut"])
    h = g2_hints()
    if mode == "cut":
        text = g2_lit_text(rng, need_multi=True)
        offs = g2_offsets(text)
        starts = [offs[j] for j, c in enumerate(text) if len(c.encode("utf-8")) >= 2]
        B = rng.choice(starts)
        bad = rng.random() < G2_BAD_RATE
        L = g2_esc(text)
        N = offs[-1]
        body = ['  let s: str = "%s";' % L, "  if is_char_boundary(s, k) {", "    return substr(s, 0, k);",
                "  } else {", "    return substr(s, 0, %d);" % (B + 1 if bad else B), "  }"]
        src = g2_fn([["k", "i64"]], "str", ["alloc"], ['0 <= k && k <= len("%s")' % L], [], body)
        g2_int_hint(h, "k", 0, N)
        h["g2rel"]["k"] = N
        return g2_case_parts(src, [["k", "i64"]], "str", h, ["boundary", "lit", "ret_str", "str", "substr"])
    text = g2_lit_text(rng)
    L = g2_esc(text)
    N = len(text.encode("utf-8"))
    if mode == "byte":
        body = ['  let s: str = "%s";' % L, "  assert len(s) == %d;" % N, "  return s[k];"]
        src = g2_fn([["k", "i64"]], "i64", ["alloc"], ['0 <= k && k < len("%s")' % L], [], body)
        g2_int_hint(h, "k", 0, N - 1)
        h["g2rel"]["k"] = N
    else:
        body = ['  let s: str = "%s";' % L, "  assert len(s) == %d;" % N, "  return len(s) + k;"]
        src = g2_fn([["k", "i64"]], "i64", ["alloc"], ["0 <= k && k <= 1000"], ['result == len("%s") + k' % L], body)
        g2_int_hint(h, "k", 0, 1000)
        h["g2small"]["k"] = 6
    return g2_case_parts(src, [["k", "i64"]], "i64", h, ["lit", "str"])


# 10) str -> [u8] byte copy
def g2_str_to_u8(rng):
    mode = rng.choice(["copy", "upper", "mask"])
    bad = rng.random() < G2_BAD_RATE
    if mode == "copy":
        inner = ["out[i] = %s;" % ("s[i] + 1" if bad else "s[i]")]
    elif mode == "upper":
        inner = ["let v: i64 = s[i];", "if v >= 97 && v <= 122 {", "  out[i] = %s;" % ("v + 200" if bad else "v - 32"),
                 "} else {", "  out[i] = v;", "}"]
    else:
        inner = ["let v: i64 = s[i];", "if v < 128 {", "  out[i] = v;", "} else {", "  out[i] = %s;" % ("v" if not bad else "v + 1"),
                 "}"]
        if not bad:
            inner[4] = "  out[i] = 63;"
    body = ["  let mut out: [u8] = alloc(len(s), 0);"] + g2_loop("len(s)", ["len(out) == len(s)"], inner) + ["  return out;"]
    src = g2_fn([["s", "str"]], "array_u8", ["alloc"], ["len(s) <= %d" % G2_LIM], ["len(result) == len(s)"], body)
    return g2_case_parts(src, [["s", "str"]], "array_u8", g2_hints(),
                         ["alloc_u8", "ret_u8", "store_u8", "str", "u8"])


# 11) a function with requires is_char_boundary(s, i) and its call
def g2_requires_boundary(rng):
    h = g2_hints()
    g2_int_hint(h, "i", 0, None)
    h["g2rel"]["i"] = "s"
    sub = rng.choice(["substr(s, 0, i)", "substr(s, i, len(s))"])
    helper = g2_fn([["s", "str"], ["i", "i64"]], "str", ["alloc"],
                   ["0 <= i && i <= len(s) && is_char_boundary(s, i)"], [], ["  return %s;" % sub]).replace("fn f(", "fn cut(", 1)
    body = ["  if is_char_boundary(s, i) {", "    return cut(s, i);", "  } else {", "    return copy(s);", "  }"]
    main_ = g2_fn([["s", "str"], ["i", "i64"]], "str", ["alloc"], ["0 <= i && i <= len(s)"], [], body)
    src = helper + "\n\n" + main_
    return g2_case_parts(src, [["s", "str"], ["i", "i64"]], "str", h, ["boundary", "ret_str", "str", "substr"])


G2_TEMPLATES = [("clamp", g2_clamp), ("u8scan", g2_u8_scan), ("copyupd", g2_copy_update),
                ("allocu8", g2_alloc_u8), ("boolagg", g2_bool_agg), ("boolbuild", g2_bool_build),
                ("strscan", g2_str_scan), ("substr", g2_str_substr), ("literal", g2_literal),
                ("str2u8", g2_str_to_u8), ("reqbound", g2_requires_boundary)]


def generate_g2_case(seed, index):
    rng = random.Random("g2:%s:%s" % (seed, index))
    kind, fn = rng.choice(G2_TEMPLATES)
    p = fn(rng)
    return {"name": "c%s_%s" % (seed, index), "src": p["src"], "entry": "f", "params": p["params"],
            "ret": p["ret"], "kind": "g2_" + kind, "input_hints": p["hints"],
            "g2": True, "g2_features": sorted(set(p["feats"]))}


def g2_str_value(rng, maxn=8):
    return "".join(g2_char(rng) for _ in range(rng.randint(0, maxn)))


def g2_u8_value(rng):
    return [rng.choice(G2_SPECIAL_BYTES) if rng.random() < 0.5 else rng.randint(0, 255)
            for _ in range(rng.randint(0, 8))]


def g2_bool_value(rng):
    mode = rng.random()
    n = rng.randint(0, 8)
    if mode < 0.15:
        return [True] * n
    if mode < 0.3:
        return [False] * n
    return [rng.random() < 0.5 for _ in range(n)]


def g2_seq_len(v):
    return len(v.encode("utf-8")) if isinstance(v, str) else len(v)


def g2_int_value(rng, h, name, vals):
    hh = h["ints"].get(name, {})
    lo, hi = hh.get("lo"), hh.get("hi")
    rel = h["g2rel"].get(name)
    small = h["g2small"].get(name)
    if rel is not None:
        L = rel if isinstance(rel, int) else g2_seq_len(vals[rel])
        r = rng.random()
        if r < 0.8:
            v = rng.choice([0, L, rng.randint(0, L), rng.randint(0, L), max(0, L - 1)])
        elif r < 0.9:
            v = L + rng.choice([1, 1, 2, 5])
        else:
            v = rng.choice([-1, -1, -2, -7])
        if (lo is not None or hi is not None) and rng.random() < 0.85:
            if lo is not None:
                v = max(v, lo)
            if hi is not None:
                v = min(v, hi)
        return v
    if small is not None:
        a = 0 if lo is None else max(lo, 0)
        b = small if hi is None else min(hi, small)
        if rng.random() < 0.85 and a <= b:
            return rng.randint(a, b)
        return pick_int(rng, hh, h["consts"])
    if lo is not None and hi is not None and rng.random() < 0.85:
        return pick_in_range(rng, lo, hi)
    return pick_int(rng, hh, h["consts"])


def g2_candidate_inputs(case, rng, n):
    h = case["input_hints"]
    out = []
    for _ in range(n):
        vals = {}
        for name, ty in case["params"]:
            if ty == "array":
                vals[name] = gen_array(rng, h["arrays"].get(name, {}), h["consts"])
            elif ty == "array_u8":
                vals[name] = g2_u8_value(rng)
            elif ty == "array_bool":
                vals[name] = g2_bool_value(rng)
            elif ty == "str":
                vals[name] = g2_str_value(rng)
        for name, ty in case["params"]:
            if ty == "i64":
                vals[name] = g2_int_value(rng, h, name, vals)
        for x, y in h.get("g2order", []):
            if x in vals and y in vals and vals[x] > vals[y] and rng.random() < 0.7:
                vals[x], vals[y] = vals[y], vals[x]
        out.append([vals[name] for name, _ in case["params"]])
    return out


# ---------------------------------------------------------------- G3 mode (--g3)
# Generics (docs/G3_SPEC.md 7.8, SPEC.md 6c). Only generate_case(seed, index, g3=True) uses this block; it creates its own rng
# ("g3:<seed>:<index>"), so the streams of the existing modes (and of --g2) are untouched.
#
# A G3 case is built from generic *fragments* (verified library functions such as `first<T: Element>`, `get_or<T>`,
# `swap<A, B>`, `rev<T: Element>`; see G3_FRAGS) plus one concrete entry `fn f(..)`, which is what the harness executes.
# Generic functions are not exported (SPEC 6c), so `f` is a non-generic wrapper that calls instances at i64 and bool
# with explicit type arguments. Values that cross the `f` boundary are limited to i64, bool, [i64], [bool], Option<i64|bool>
# and Result<i64|bool>; generic structs/enums (Pair, Choice, Tagged) and Option<Pair<..>> live inside the body only, because
# the Rust names of struct instances are compiler-mangled (`pruv_g3_t_4_Pair_2_i_b`) and not part of the contract.
#
# About G3_BAD_SHARE of the cases are *deliberately unproved but well-typed*: one requires clause is dropped, a false
# ensures is added, a loop invariant is dropped, or a fragment gets a wrong body (wrong payload, missing guard). They are
# expected to be rejected by the verifier and are then only run in safe mode; if the verifier accepts one anyway it is
# treated like any verified program (checked against the oracle in proof mode).

G3_BAD_SHARE = 0.30

G3_TYPES = ("Pair", "Choice", "Tagged")     # fragments that are type declarations (placed first)

G3_FRAGS = {
    "Pair": "struct Pair<A, B> {\n  first: A,\n  second: B\n}",
    "Choice": "enum Choice<A, B> {\n  Left(value: A),\n  Right(value: B)\n}",
    "Tagged": "struct Tagged<T> {\n  tag: i64,\n  value: T\n}",
    "id": "fn id<T>(x: T) -> T\n  ensures result == x\n{\n  return x;\n}",
    "wrap": ("fn wrap<T>(x: T) -> Option<T>\n  ensures is_some(result) && some_val(result) == x\n"
             "{\n  return Some::<T>(x);\n}"),
    "get_or": ("fn get_or<T>(o: Option<T>, d: T) -> T\n  ensures is_some(o) ==> result == some_val(o)\n"
               "  ensures !is_some(o) ==> result == d\n{\n  match o {\n    Some(v) => { return v; }\n"
               "    None => { return d; }\n  }\n}"),
    "forward": ("fn forward<U>(x: U) -> Option<U>\n  ensures is_some(result) && some_val(result) == x\n"
                "{\n  return wrap::<U>(id::<U>(x));\n}"),
    "wrap_twice": ("fn wrap_twice<T>(x: T) -> Option<Option<T>>\n"
                   "  ensures is_some(result) && is_some(some_val(result)) && some_val(some_val(result)) == x\n"
                   "{\n  let inner: Option<T> = wrap::<T>(x);\n  return Some::<Option<T>>(inner);\n}"),
    "result_or": ("fn result_or<T>(r: Result<T>, d: T) -> T\n  ensures is_ok(r) ==> result == ok_val(r)\n"
                  "  ensures !is_ok(r) ==> result == d\n{\n  match r {\n    Ok(v) => { return v; }\n"
                  "    Err(c) => { return d; }\n  }\n}"),
    "fail": ("fn fail<T>(code: i64) -> Result<T>\n  ensures !is_ok(result) && err_val(result) == code\n"
             "{\n  return Err::<T>(code);\n}"),
    "to_result": ("fn to_result<T>(o: Option<T>, code: i64) -> Result<T>\n"
                  "  ensures is_some(o) ==> is_ok(result) && ok_val(result) == some_val(o)\n"
                  "  ensures !is_some(o) ==> !is_ok(result) && err_val(result) == code\n"
                  "{\n  match o {\n    Some(v) => { return Ok::<T>(v); }\n    None => { return Err::<T>(code); }\n  }\n}"),
    "first": ("fn first<T: Element>(a: [T]) -> T\n  requires len(a) > 0\n  ensures result == a[0]\n"
              "{\n  return a[0];\n}"),
    "last": ("fn last<T: Element>(a: [T]) -> T\n  requires len(a) > 0\n  ensures result == a[len(a) - 1]\n"
             "{\n  return a[len(a) - 1];\n}"),
    "len_of": "fn len_of<T: Element>(a: [T]) -> i64\n  ensures result == len(a)\n{\n  return len(a);\n}",
    "set_first": ("fn set_first<T: Element>(a: [T], v: T) -> [T] ! alloc\n  requires len(a) > 0\n"
                  "  ensures len(result) == len(a)\n  ensures result[0] == v\n"
                  "{\n  let mut out: [T] = copy(a);\n  out[0] = v;\n  return out;\n}"),
    "swap_ends": ("fn swap_ends<T: Element>(a: [T]) -> [T] ! alloc\n  requires len(a) >= 2\n"
                  "  ensures len(result) == len(a)\n  ensures result[0] == a[len(a) - 1]\n"
                  "  ensures result[len(a) - 1] == a[0]\n"
                  "{\n  let mut out: [T] = copy(a);\n  let n: i64 = len(a);\n  let x: T = a[0];\n"
                  "  let y: T = a[n - 1];\n  out[0] = y;\n  out[n - 1] = x;\n  return out;\n}"),
    "copy_all": ("fn copy_all<T: Element>(a: [T]) -> [T] ! alloc\n  ensures len(result) == len(a)\n"
                 "  ensures forall k in 0..len(a): result[k] == a[k]\n{\n  let out: [T] = copy(a);\n  return out;\n}"),
    "copy_loop": ("fn copy_loop<T: Element>(a: [T]) -> [T] ! alloc\n  ensures len(result) == len(a)\n"
                  "  ensures forall k in 0..len(a): result[k] == a[k]\n{\n  let mut out: [T] = copy(a);\n"
                  "  let mut i: i64 = 0;\n  while i < len(a)\n    invariant 0 <= i && i <= len(a)\n"
                  "    invariant len(out) == len(a)\n    invariant forall j in 0..len(a): out[j] == a[j]\n"
                  "    decreases len(a) - i\n  {\n    out[i] = a[i];\n    i = i + 1;\n  }\n  return out;\n}"),
    "rev": ("fn rev<T: Element>(a: [T]) -> [T] ! alloc\n  ensures len(result) == len(a)\n"
            "  ensures forall k in 0..len(a): result[k] == a[len(a) - 1 - k]\n"
            "{\n  let mut out: [T] = copy(a);\n  let mut i: i64 = 0;\n  while i < len(a)\n"
            "    invariant 0 <= i && i <= len(a)\n    invariant len(out) == len(a)\n"
            "    invariant forall j in 0..i: out[j] == a[len(a) - 1 - j]\n    decreases len(a) - i\n"
            "  {\n    out[i] = a[len(a) - 1 - i];\n    i = i + 1;\n  }\n  return out;\n}"),
    "repeat": ("fn repeat<T: Element>(n: i64, value: T) -> [T] ! alloc\n  requires 0 <= n && n <= 100\n"
               "  ensures len(result) == n\n  ensures forall k in 0..n: result[k] == value\n"
               "{\n  let out: [T] = alloc(n, value);\n  return out;\n}"),
    "fill_loop": ("fn fill_loop<T: Element>(n: i64, v: T) -> [T] ! alloc\n  requires 0 <= n && n <= 100\n"
                  "  ensures len(result) == n\n  ensures forall k in 0..n: result[k] == v\n"
                  "{\n  let mut out: [T] = alloc(n, v);\n  let mut i: i64 = 0;\n  while i < n\n"
                  "    invariant 0 <= i && i <= n\n    invariant len(out) == n\n"
                  "    invariant forall j in 0..n: out[j] == v\n    decreases n - i\n"
                  "  {\n    out[i] = v;\n    i = i + 1;\n  }\n  return out;\n}"),
    "mk_pair": ("fn mk_pair<A, B>(a: A, b: B) -> Pair<A, B>\n  ensures result.first == a\n  ensures result.second == b\n"
                "{\n  return Pair::<A, B> { first: a, second: b };\n}"),
    "swap": ("fn swap<A, B>(p: Pair<A, B>) -> Pair<B, A>\n  ensures result.first == p.second\n"
             "  ensures result.second == p.first\n"
             "{\n  return Pair::<B, A> {\n    first: p.second,\n    second: p.first\n  };\n}"),
    "fst": "fn fst<A, B>(p: Pair<A, B>) -> A\n  ensures result == p.first\n{\n  return p.first;\n}",
    "snd": "fn snd<A, B>(p: Pair<A, B>) -> B\n  ensures result == p.second\n{\n  return p.second;\n}",
    "set_pair_first": ("fn set_pair_first<A, B>(p: Pair<A, B>, v: A) -> Pair<A, B>\n  ensures result.first == v\n"
                       "  ensures result.second == p.second\n"
                       "{\n  let mut q: Pair<A, B> = p;\n  q.first = v;\n  return q;\n}"),
    "pick_by": ("fn pick_by<A, B>(flag: bool, a: A, a2: A, b: B) -> Pair<A, B>\n  ensures flag ==> result.first == a\n"
                "  ensures !flag ==> result.first == a2\n  ensures result.second == b\n"
                "{\n  let mut chosen: A = a2;\n  if flag {\n    chosen = a;\n  }\n"
                "  return Pair::<A, B> { first: chosen, second: b };\n}"),
    "left_or": ("fn left_or<A, B>(c: Choice<A, B>, d: A) -> A\n"
                "  ensures is_variant(c, Choice::Left) ==> result == variant_field(c, Choice::Left, value)\n"
                "  ensures !is_variant(c, Choice::Left) ==> result == d\n"
                "{\n  match c {\n    Choice::Left(x) => { return x; }\n    Choice::Right(y) => { return d; }\n  }\n}"),
    "flip": ("fn flip<A, B>(c: Choice<A, B>) -> Choice<B, A>\n"
             "  ensures is_variant(result, Choice::Right) == is_variant(c, Choice::Left)\n"
             "{\n  match c {\n    Choice::Left(x) => { return Choice::<B, A>::Right(x); }\n"
             "    Choice::Right(y) => { return Choice::<B, A>::Left(y); }\n  }\n}"),
    "bump_tag": ("fn bump_tag<T>(t: Tagged<T>) -> Tagged<T>\n  requires -1000 < t.tag && t.tag < 1000\n"
                 "  ensures result.tag == t.tag + 1\n  ensures result.value == t.value\n"
                 "{\n  return Tagged::<T> { tag: t.tag + 1, value: t.value };\n}"),
    "retag": ("fn retag<T>(t: Tagged<T>, tag: i64) -> Tagged<T>\n  ensures result.value == t.value\n"
              "  ensures result.tag == tag\n{\n  return Tagged::<T> { tag: tag, value: t.value };\n}"),
}

# Fragments that need other fragments (type declarations or callees).
G3_DEPS = {"forward": ["wrap", "id"], "wrap_twice": ["wrap"], "mk_pair": ["Pair"], "swap": ["Pair"], "fst": ["Pair"],
           "snd": ["Pair"], "set_pair_first": ["Pair"], "pick_by": ["Pair"], "left_or": ["Choice"],
           "flip": ["Choice"], "bump_tag": ["Tagged"], "retag": ["Tagged"]}

# Defective versions of a fragment: well-typed, but the verifier must not prove the fragment's own contract.
G3_BAD_FRAGS = {
    "first": G3_FRAGS["first"].replace("  requires len(a) > 0\n", ""),                            # deleted bounds guard
    "last": G3_FRAGS["last"].replace("return a[len(a) - 1];", "return a[0];"),                    # wrong element
    "get_or": G3_FRAGS["get_or"].replace("Some(v) => { return v; }", "Some(v) => { return d; }"),  # wrong active payload
    "left_or": G3_FRAGS["left_or"].replace("Choice::Left(x) => { return x; }", "Choice::Left(x) => { return d; }"),
    "set_first": G3_FRAGS["set_first"].replace("out[0] = v;", "out[len(a) - 1] = v;"),            # store at the wrong index
    "swap_ends": G3_FRAGS["swap_ends"].replace("out[0] = y;", "out[0] = x;"),
    "copy_loop": G3_FRAGS["copy_loop"].replace("    invariant forall j in 0..len(a): out[j] == a[j]\n", ""),
    "rev": G3_FRAGS["rev"].replace("out[i] = a[len(a) - 1 - i];", "out[i] = a[len(a) - i];"),      # index out of range at i == 0
    "fill_loop": G3_FRAGS["fill_loop"].replace("    invariant forall j in 0..n: out[j] == v\n", ""),
    "repeat": G3_FRAGS["repeat"].replace("alloc(n, value)", "alloc(n + 1, value)"),               # wrong length
    "bump_tag": G3_FRAGS["bump_tag"].replace("tag: t.tag + 1", "tag: t.tag + 2"),
}

# fragments that can be added to a program without being called (an unused definition is still type-checked and proved)
G3_UNUSED = ["id", "wrap", "get_or", "first", "last", "copy_all", "len_of", "result_or", "fail", "swap", "fst", "mk_pair"]


class G3P(object):
    """Parts of one G3 case under construction."""

    def __init__(self, rng, bad):
        self.rng, self.bad = rng, bad
        self.frags = []        # fragment names used (dependencies are added when rendering)
        self.frag_bad = []     # [(fragment, defective text)] offered to the defect step
        self.frag_text = {}    # fragment -> replacement text (set by the defect step)
        self.params = []       # [[name, type tag]]: "i64" "bool" "array" "array_bool" "Option<i64|bool>" "Result<i64|bool>"
        self.ret = "i64"
        self.effects = []
        self.requires = []
        self.ensures = []
        self.false_ens = []    # contract clauses that are false (offered to the defect step)
        self.body = []
        self.hints = {"ranges": {}, "minlen": {}}
        self.feats = set()
        self.mutation = None

    def use(self, *names):
        for n in names:
            if n not in self.frags:
                self.frags.append(n)
            if n in G3_BAD_FRAGS and all(n != b[0] for b in self.frag_bad):
                self.frag_bad.append((n, G3_BAD_FRAGS[n]))


def g3_ty(tag):
    """Type tag -> source text."""
    return {"array": "[i64]", "array_bool": "[bool]"}.get(tag, tag)


def g3_elem(rng):
    return rng.choice(["i64", "i64", "bool"])


def g3_arr(X):
    return "array" if X == "i64" else "array_bool"


# -- scenarios: each fills in params/ret/effects/requires/ensures/false_ens/body/hints/feats of a G3P

def g3_sc_ident(P):
    rng = P.rng
    X = g3_elem(rng)
    P.params = [["x", X]]
    P.ret = X
    P.use("id")
    P.feats.update(["generic_fn", "ident"])
    v = rng.randrange(5 if X == "i64" else 4)
    P.ensures = ["result == x"]
    P.false_ens = ["result != x"]
    if v == 0:
        P.body = ["  let y: %s = id::<%s>(x);" % (X, X), "  return y;"]
    elif v == 1:
        P.body = ["  return id::<%s>(id::<%s>(x));" % (X, X)]
        P.feats.add("nested_call")
    elif v == 2:
        P.use("wrap", "get_or")
        P.body = ["  let o: Option<%s> = wrap::<%s>(x);" % (X, X), "  return get_or::<%s>(o, x);" % X]
        P.feats.update(["option", "guarded_payload"])
    elif v == 3:
        P.use("wrap", "get_or")
        P.body = ["  let o: Option<%s> = wrap::<%s>(x);" % (X, X),
                  "  let w: Option<Option<%s>> = wrap::<Option<%s>>(o);" % (X, X),
                  "  let inner: Option<%s> = get_or::<Option<%s>>(w, None::<%s>);" % (X, X, X),
                  "  return get_or::<%s>(inner, x);" % X]
        P.feats.update(["option", "nested_option", "nested_call", "guarded_payload"])
    else:
        K = rng.choice([1, 2, 5, 10])
        P.requires = ["-1000000 <= x && x <= 1000000"]
        P.hints["ranges"]["x"] = (-1000000, 1000000)
        P.ensures = ["result == x + %d" % K]
        P.false_ens = ["result == x"]
        P.body = ["  let y: i64 = id::<i64>(x);", "  return y + %d;" % K]
        P.feats.add("bounded_int")


def g3_sc_optfallback(P):
    rng = P.rng
    X = g3_elem(rng)
    P.ret = X
    P.feats.update(["generic_fn", "option", "guarded_payload"])
    v = rng.randrange(4)
    if v in (0, 1):
        P.use("get_or")
        P.params = [["o", "Option<%s>" % X], ["d", X]]
        P.ensures = ["is_some(o) ==> result == some_val(o)", "!is_some(o) ==> result == d"]
        P.false_ens = ["result == d", "is_some(o) ==> result != some_val(o)"]
        if v == 0:
            P.body = ["  return get_or::<%s>(o, d);" % X]
        else:
            P.use("wrap")
            P.body = ["  let w: Option<Option<%s>> = wrap::<Option<%s>>(o);" % (X, X),
                      "  let inner: Option<%s> = get_or::<Option<%s>>(w, None::<%s>);" % (X, X, X),
                      "  return get_or::<%s>(inner, d);" % X]
            P.feats.update(["nested_option", "nested_call"])
    elif v == 2:
        P.use("result_or")
        P.params = [["r", "Result<%s>" % X], ["d", X]]
        P.ensures = ["is_ok(r) ==> result == ok_val(r)", "!is_ok(r) ==> result == d"]
        P.false_ens = ["result == d"]
        P.body = ["  return result_or::<%s>(r, d);" % X]
        P.feats.add("result")
    else:
        P.use("to_result", "result_or")
        P.params = [["o", "Option<%s>" % X], ["code", "i64"], ["d", X]]
        P.ensures = ["is_some(o) ==> result == some_val(o)", "!is_some(o) ==> result == d"]
        P.false_ens = ["result == d"]
        P.body = ["  let r: Result<%s> = to_result::<%s>(o, code);" % (X, X), "  return result_or::<%s>(r, d);" % X]
        P.feats.update(["result", "nested_call"])


def g3_sc_optret(P):
    rng = P.rng
    X = g3_elem(rng)
    P.feats.update(["generic_fn", "option_ret"])
    v = rng.randrange(4)
    if v in (0, 1):
        P.params = [["x", X]]
        P.ret = "Option<%s>" % X
        P.use("wrap" if v == 0 else "forward")
        P.body = ["  return %s::<%s>(x);" % ("wrap" if v == 0 else "forward", X)]
        P.ensures = ["is_some(result) && some_val(result) == x"]
        P.false_ens = ["!is_some(result)"]
        if v == 1:
            P.feats.add("nested_call")
    elif v == 2:
        P.use("to_result")
        P.params = [["o", "Option<%s>" % X], ["code", "i64"]]
        P.ret = "Result<%s>" % X
        P.body = ["  return to_result::<%s>(o, code);" % X]
        P.ensures = ["is_some(o) ==> is_ok(result) && ok_val(result) == some_val(o)",
                     "!is_some(o) ==> !is_ok(result) && err_val(result) == code"]
        P.false_ens = ["is_ok(result)"]
        P.feats.update(["result", "guarded_payload"])
    else:
        P.use("fail")
        P.params = [["code", "i64"]]
        P.ret = "Result<%s>" % X
        P.body = ["  return fail::<%s>(code);" % X]
        P.ensures = ["!is_ok(result) && err_val(result) == code"]
        P.false_ens = ["is_ok(result)"]
        P.feats.add("result")


def g3_sc_arrfirst(P):
    rng = P.rng
    X = g3_elem(rng)
    P.params = [["a", g3_arr(X)]]
    P.ret = X
    P.requires = ["len(a) > 0"]
    P.hints["minlen"]["a"] = 1
    P.feats.update(["generic_fn", "array_T"])
    v = rng.randrange(5)
    if v == 0:
        P.use("first")
        P.body = ["  return first::<%s>(a);" % X]
        P.ensures = ["result == a[0]"]
        P.false_ens = ["result != a[0]"]
    elif v == 1:
        P.use("last")
        P.body = ["  return last::<%s>(a);" % X]
        P.ensures = ["result == a[len(a) - 1]"]
        P.false_ens = ["result != a[len(a) - 1]"]
    elif v == 2:
        P.use("copy_all", "first")
        P.effects = ["alloc"]
        P.body = ["  let c: [%s] = copy_all::<%s>(a);" % (X, X), "  return first::<%s>(c);" % X]
        P.ensures = ["result == a[0]"]
        P.false_ens = ["result != a[0]"]
        P.feats.update(["copy", "nested_call"])
    elif v == 3:
        P.use("set_first", "first")
        P.params.append(["v", X])
        P.effects = ["alloc"]
        P.body = ["  let c: [%s] = set_first::<%s>(a, v);" % (X, X), "  return first::<%s>(c);" % X]
        P.ensures = ["result == v"]
        P.false_ens = ["result != v"]
        P.feats.update(["store", "nested_call"])
    else:
        P.use("rev", "first")
        P.effects = ["alloc"]
        P.body = ["  let c: [%s] = rev::<%s>(a);" % (X, X), "  return first::<%s>(c);" % X]
        P.ensures = ["result == a[len(a) - 1]"]
        P.false_ens = ["result != a[len(a) - 1]"]
        P.feats.update(["loop_invariant", "forall", "nested_call"])


def g3_sc_dual(P):
    """One wrapper that calls the i64 and the bool instance of the same generic function."""
    rng = P.rng
    P.params = [["a", "array"], ["b", "array_bool"]]
    P.ret = "i64"
    P.hints["minlen"].update({"a": 1, "b": 1})
    P.feats.update(["generic_fn", "array_T", "dual_instance"])
    if rng.random() < 0.5:
        P.use("first")
        P.requires = ["len(a) > 0", "len(b) > 0"]
        P.body = ["  let x: i64 = first::<i64>(a);", "  let y: bool = first::<bool>(b);",
                  "  if y {", "    return x;", "  }", "  return 0;"]
        P.ensures = ["b[0] ==> result == a[0]", "!b[0] ==> result == 0"]
        P.false_ens = ["result == a[0]"]
    else:
        P.use("len_of")
        P.body = ["  return len_of::<i64>(a) + len_of::<bool>(b);"]
        P.ensures = ["result == len(a) + len(b)"]
        P.false_ens = ["result == len(a)"]
        P.hints["minlen"] = {}


def g3_sc_arrays(P):
    """[T] copies / stores / allocation behind a concrete wrapper, bounded forall in the contract, loops with invariants."""
    rng = P.rng
    X = g3_elem(rng)
    at = g3_arr(X)
    P.ret = at
    P.effects = ["alloc"]
    P.feats.update(["generic_fn", "array_T", "alloc"])
    v = rng.choice(["set_first", "swap_ends", "copy_all", "copy_loop", "rev", "repeat", "fill_loop"])
    if v in ("repeat", "fill_loop"):
        P.use(v)
        P.params = [["n", "i64"], ["v", X]]
        P.requires = ["0 <= n && n <= 100"]
        P.hints["ranges"]["n"] = (0, 100)
        P.body = ["  return %s::<%s>(n, v);" % (v, X)]
        P.ensures = ["len(result) == n", "forall k in 0..n: result[k] == v"]
        P.false_ens = ["len(result) == n + 1"]
        P.feats.add("forall")
        if v == "fill_loop":
            P.feats.add("loop_invariant")
        return
    P.use(v)
    P.params = [["a", at]]
    if v == "set_first":
        P.params.append(["v", X])
        P.requires = ["len(a) > 0"]
        P.hints["minlen"]["a"] = 1
        P.body = ["  return set_first::<%s>(a, v);" % X]
        P.ensures = ["len(result) == len(a)", "result[0] == v"]
        P.false_ens = ["result[0] != v"]
        P.feats.add("store")
        return
    if v == "swap_ends":
        P.requires = ["len(a) >= 2"]
        P.hints["minlen"]["a"] = 2
        P.body = ["  return swap_ends::<%s>(a);" % X]
        P.ensures = ["len(result) == len(a)", "result[0] == a[len(a) - 1]", "result[len(a) - 1] == a[0]"]
        P.false_ens = ["result[0] == a[0]"]
        P.feats.add("store")
        return
    P.body = ["  return %s::<%s>(a);" % (v, X)]
    P.ensures = ["len(result) == len(a)"]
    if v == "rev":
        P.ensures.append("forall k in 0..len(a): result[k] == a[len(a) - 1 - k]")
    else:
        P.ensures.append("forall k in 0..len(a): result[k] == a[k]")
    P.false_ens = ["len(result) == len(a) + 1"]
    P.feats.update(["forall", "copy"])
    if v in ("copy_loop", "rev"):
        P.feats.add("loop_invariant")


def g3_sc_loopcount(P):
    """Concrete loop with invariants that reads the length through a generic instance."""
    rng = P.rng
    use_bool = rng.random() < 0.5
    cnt = rng.random() < 0.4
    X = "bool" if use_bool else "i64"
    P.use("len_of")
    P.params = [["a", g3_arr(X)]] + ([] if use_bool else [["x", "i64"]])
    P.ret = "i64"
    test = "a[i]" if use_bool else "a[i] == x"
    in_contract = "a[k] == true" if use_bool else "a[k] == x"
    invs = ["0 <= i && i <= n", "n == len(a)", "0 <= c && c <= i"]
    P.ensures = ["0 <= result && result <= len(a)"]
    if cnt:
        invs.append("c == count(k in 0..i: %s)" % in_contract)
        P.ensures.append("result == count(k in 0..len(a): %s)" % in_contract)
        P.feats.add("count")
    P.false_ens = ["result == len(a)"]
    P.body = ["  let n: i64 = len_of::<%s>(a);" % X, "  let mut c: i64 = 0;", "  let mut i: i64 = 0;",
              "  while i < n"] + ["    invariant " + e for e in invs] + \
             ["    decreases n - i", "  {", "    if %s {" % test, "      c = c + 1;", "    }", "    i = i + 1;", "  }",
              "  return c;"]
    P.feats.update(["generic_fn", "loop_invariant", "array_T"])


def g3_sc_pairs(P):
    rng = P.rng
    A, B = rng.choice([("i64", "bool"), ("bool", "i64"), ("i64", "i64"), ("bool", "bool")])
    PT = "Pair<%s, %s>" % (A, B)
    mk = "Pair::<%s, %s> { first: a, second: b }" % (A, B)
    P.feats.update(["generic_fn", "pair"])
    P.use("Pair")
    v = rng.randrange(6)
    if v in (0, 1):
        P.use("mk_pair", "swap", "snd" if v == 0 else "fst")
        P.params = [["a", A], ["b", B]]
        P.ret = A if v == 0 else B
        P.body = ["  let p: %s = mk_pair::<%s, %s>(a, b);" % (PT, A, B),
                  "  let q: Pair<%s, %s> = swap::<%s, %s>(p);" % (B, A, A, B),
                  ("  return snd::<%s, %s>(q);" if v == 0 else "  return fst::<%s, %s>(q);") % (B, A)]
        P.ensures = ["result == %s" % ("a" if v == 0 else "b")]
        P.false_ens = ["result != %s" % ("a" if v == 0 else "b")]
        P.feats.add("nested_call")
    elif v == 2:
        P.use("swap")
        P.params = [["a", A], ["b", B]]
        P.ret = B
        P.body = ["  let p: %s = %s;" % (PT, mk),
                  "  let q: Pair<%s, %s> = swap::<%s, %s>(p);" % (B, A, A, B),
                  "  let r: %s = swap::<%s, %s>(q);" % (PT, B, A),
                  "  return r.second;"]
        P.ensures = ["result == b"]
        P.false_ens = ["result != b"]
        P.feats.add("nested_call")
    elif v == 3:
        P.use("wrap", "get_or")
        P.params = [["a", A], ["b", B], ["d", A]]
        P.ret = A
        P.body = ["  let p: %s = %s;" % (PT, mk),
                  "  let o: Option<%s> = wrap::<%s>(p);" % (PT, PT),
                  "  let dflt: %s = Pair::<%s, %s> { first: d, second: b };" % (PT, A, B),
                  "  let q: %s = get_or::<%s>(o, dflt);" % (PT, PT),
                  "  return q.first;"]
        P.ensures = ["result == a"]
        P.false_ens = ["result != a"]
        P.feats.update(["option", "option_pair", "guarded_payload", "nested_call"])
    elif v == 4:
        P.use("mk_pair", "set_pair_first")
        P.params = [["a", A], ["b", B], ["v", A]]
        first = rng.random() < 0.5
        P.ret = A if first else B
        P.body = ["  let p: %s = mk_pair::<%s, %s>(a, b);" % (PT, A, B),
                  "  let q: %s = set_pair_first::<%s, %s>(p, v);" % (PT, A, B),
                  "  return q.first;" if first else "  return q.second;"]
        P.ensures = ["result == v" if first else "result == b"]
        P.false_ens = ["result != v" if first else "result != b"]
        P.feats.update(["struct_update", "nested_call"])
    else:
        P.use("pick_by")
        P.params = [["flag", "bool"], ["a", A], ["a2", A], ["b", B]]
        first = rng.random() < 0.6
        P.ret = A if first else B
        P.body = ["  let p: %s = pick_by::<%s, %s>(flag, a, a2, b);" % (PT, A, B),
                  "  return p.first;" if first else "  return p.second;"]
        if first:
            P.ensures = ["flag ==> result == a", "!flag ==> result == a2"]
            P.false_ens = ["result == a"]
        else:
            P.ensures = ["result == b"]
            P.false_ens = ["result != b"]


def g3_sc_choice(P):
    rng = P.rng
    P.use("Choice")
    P.feats.update(["generic_fn", "choice"])
    if rng.random() < 0.6:
        P.use("left_or")
        P.params = [["t", "bool"], ["x", "i64"], ["y", "bool"], ["d", "i64"]]
        P.ret = "i64"
        P.body = ["  if t {", "    let c: Choice<i64, bool> = Choice::<i64, bool>::Left(x);",
                  "    return left_or::<i64, bool>(c, d);", "  }",
                  "  let e: Choice<i64, bool> = Choice::<i64, bool>::Right(y);",
                  "  return left_or::<i64, bool>(e, d);"]
        P.ensures = ["t ==> result == x", "!t ==> result == d"]
        P.false_ens = ["result == x"]
        P.feats.add("guarded_payload")
    else:
        P.use("flip")
        P.params = [["t", "bool"], ["x", "i64"], ["y", "bool"]]
        P.ret = "bool"
        P.body = ["  if t {", "    let c: Choice<i64, bool> = Choice::<i64, bool>::Left(x);",
                  "    let g: Choice<bool, i64> = flip::<i64, bool>(c);", "    match g {",
                  "      Choice::Left(p) => { return false; }", "      Choice::Right(q) => { return true; }",
                  "    }", "  }",
                  "  let e: Choice<i64, bool> = Choice::<i64, bool>::Right(y);",
                  "  let h: Choice<bool, i64> = flip::<i64, bool>(e);", "  match h {",
                  "    Choice::Left(r) => { return false; }", "    Choice::Right(s) => { return true; }", "  }"]
        P.ensures = ["result == t"]
        P.false_ens = ["result != t"]
        P.feats.update(["match", "nested_call"])


def g3_sc_tagged(P):
    rng = P.rng
    X = g3_elem(rng)
    P.use("Tagged")
    P.feats.update(["generic_fn", "tagged", "bounded_int"])
    mk = "Tagged::<%s> { tag: t, value: v }" % X
    v = rng.randrange(3)
    P.params = [["t", "i64"], ["v", X]]
    if v == 2:
        P.use("retag")
        P.params.append(["k", "i64"])
        P.ret = "i64"
        P.body = ["  let a: Tagged<%s> = %s;" % (X, mk),
                  "  let c: Tagged<%s> = retag::<%s>(a, k);" % (X, X), "  return c.tag;"]
        P.ensures = ["result == k"]
        P.false_ens = ["result == t"]
        return
    P.use("bump_tag")
    P.requires = ["-1000 < t && t < 1000"]
    P.hints["ranges"]["t"] = (-1000, 1000)
    P.body = ["  let a: Tagged<%s> = %s;" % (X, mk), "  let b: Tagged<%s> = bump_tag::<%s>(a);" % (X, X)]
    if v == 0:
        P.ret = "i64"
        P.body.append("  return b.tag;")
        P.ensures = ["result == t + 1"]
        P.false_ens = ["result == t"]
    else:
        P.use("retag")
        P.ret = X
        P.body += ["  let c: Tagged<%s> = retag::<%s>(b, 0);" % (X, X), "  return c.value;"]
        P.ensures = ["result == v"]
        P.false_ens = ["result != v"]
        P.feats.add("nested_call")


def g3_sc_forward(P):
    rng = P.rng
    X = g3_elem(rng)
    P.params = [["x", X]]
    P.ret = X
    P.feats.update(["generic_fn", "option", "nested_call", "match"])
    P.ensures = ["result == x"]
    P.false_ens = ["result != x"]
    if rng.random() < 0.6:
        P.use("forward")
        P.body = ["  let o: Option<%s> = forward::<%s>(x);" % (X, X), "  match o {",
                  "    Some(w) => { return w; }", "    None => { return x; }", "  }"]
    else:
        P.use("wrap_twice")
        P.body = ["  let oo: Option<Option<%s>> = wrap_twice::<%s>(x);" % (X, X), "  match oo {",
                  "    Some(o) => {", "      match o {", "        Some(w) => { return w; }",
                  "        None => { return x; }", "      }", "    }", "    None => { return x; }", "  }"]
        P.feats.add("nested_option")


G3_SCENARIOS = [("ident", g3_sc_ident, 1.0), ("optfallback", g3_sc_optfallback, 2.0), ("optret", g3_sc_optret, 1.5),
                ("arrfirst", g3_sc_arrfirst, 2.0), ("dual", g3_sc_dual, 1.0), ("arrays", g3_sc_arrays, 3.0),
                ("loopcount", g3_sc_loopcount, 1.5), ("pairs", g3_sc_pairs, 3.0), ("choice", g3_sc_choice, 1.0),
                ("tagged", g3_sc_tagged, 1.0), ("forward", g3_sc_forward, 1.0)]


def g3_pad(P):
    """Make sure the input space has at least 8 distinct points: a parameter list made only of bool/Option<bool> gets an
    extra (unused) i64 parameter."""
    large = [t for _n, t in P.params if t in ("i64", "array", "array_bool", "Option<i64>") or t.startswith("Result<")]
    if not large:
        P.params.append(["pad", "i64"])


def g3_defect(P):
    """Turn the case into a deliberately unproved (but well-typed) one."""
    rng = P.rng
    kinds = []
    if P.requires:
        kinds.append("drop_requires")
    if P.false_ens:
        kinds.append("false_ensures")
    if P.frag_bad:
        kinds.append("bad_fragment")
    if any(l.strip().startswith("invariant ") for l in P.body):
        kinds.append("drop_invariant")
    k = rng.choice(kinds)
    if k == "drop_requires":
        P.requires.pop(rng.randrange(len(P.requires)))
    elif k == "false_ensures":
        P.ensures.append(rng.choice(P.false_ens))
    elif k == "bad_fragment":
        name, text = rng.choice(P.frag_bad)
        P.frag_text[name] = text
        k += ":" + name
    else:
        idx = [i for i, l in enumerate(P.body) if l.strip().startswith("invariant ")]
        del P.body[rng.choice(idx)]
    P.mutation = k


def g3_render(P, kind):
    rng = P.rng
    names = []

    def add(n):
        for d in G3_DEPS.get(n, []):
            add(d)
        if n not in names:
            names.append(n)

    for n in P.frags:
        add(n)
    types = [n for n in names if n in G3_TYPES]
    fns = [n for n in names if n not in G3_TYPES]
    if rng.random() < 0.3:
        rng.shuffle(fns)
    parts = ["// g3 fuzz case: %s%s" % (kind, " (defect: %s)" % P.mutation if P.mutation else "")]
    parts += [P.frag_text.get(n, G3_FRAGS[n]) for n in types + fns]
    head = "fn f(%s) -> %s" % (", ".join("%s: %s" % (n, g3_ty(t)) for n, t in P.params), g3_ty(P.ret))
    if P.effects:
        head += " ! " + ", ".join(P.effects)
    out = [head] + ["  requires " + r for r in P.requires] + ["  ensures " + e for e in P.ensures] + ["{"] + P.body + ["}"]
    parts.append("\n".join(out))
    return "\n\n".join(parts) + "\n"


def generate_g3_case(seed, index):
    rng = random.Random("g3:%s:%s" % (seed, index))
    bad = rng.random() < G3_BAD_SHARE
    P = G3P(rng, bad)
    kind, fn, _w = rng.choices(G3_SCENARIOS, weights=[w for _k, _f, w in G3_SCENARIOS])[0]
    fn(P)
    g3_pad(P)
    if rng.random() < 0.25:
        P.use(rng.choice(G3_UNUSED))
    if bad:
        g3_defect(P)
        P.hints["violate"] = 0.3      # unproved cases: reach the unguarded paths in safe mode more often
    src = g3_render(P, kind)
    ret = {"array": "[i64]"}.get(P.ret, P.ret)
    return {"name": "c%s_%s" % (seed, index), "src": src, "entry": "f", "params": P.params, "ret": ret,
            "kind": "g3_" + kind, "input_hints": P.hints, "g3": True, "g3_bad": bad, "g3_mutation": P.mutation,
            "g3_features": sorted(P.feats)}


def g3_int_value(rng, rg):
    r = rng.random()
    if rg is not None:
        lo, hi = rg
        if r < 0.12:
            return rng.choice([lo, hi])
        if r < 0.18:
            return rng.choice([lo - 1, hi + 1])          # just outside the requires range
        if r < 0.55:
            a, b = max(lo, -6), min(hi, 9)
            if a <= b:
                return rng.randint(a, b)
        return rng.randint(lo, hi)
    if r < 0.06:
        return rng.choice(EXTREMES)
    if r < 0.5:
        return rng.randint(-5, 9)
    return rng.choice([0, 1, -1, 2, 3, 7, 10, 100, -100, 1000, 123456, -987654])


def g3_value(rng, tag, name, h):
    if tag == "i64":
        return g3_int_value(rng, h["ranges"].get(name))
    if tag == "bool":
        return rng.random() < 0.5
    if tag in ("array", "array_bool"):
        lo = h["minlen"].get(name, 0)
        n = rng.choice([0, 1, 1, 2, 3, 3, 4, 5, 6, 8])
        n = rng.randint(0, max(0, lo - 1)) if rng.random() < h.get("violate", 0.08) else max(n, lo)
        if tag == "array":
            return [g3_int_value(rng, None) for _ in range(n)]
        m = rng.random()
        if m < 0.15:
            return [True] * n
        if m < 0.3:
            return [False] * n
        return [rng.random() < 0.5 for _ in range(n)]
    if tag.startswith("Option<"):
        if rng.random() < 0.3:
            return {"tag": "None"}
        return {"tag": "Some", "v": rng.random() < 0.5 if tag == "Option<bool>" else g3_int_value(rng, None)}
    if tag.startswith("Result<"):
        if rng.random() < 0.65:
            return {"tag": "Ok", "v": rng.random() < 0.5 if tag == "Result<bool>" else g3_int_value(rng, None)}
        return {"tag": "Err", "v": rng.choice([-1, 0, 1, 2, 7, -7, 100])}
    raise ValueError("unknown G3 parameter type %r" % (tag,))


def g3_candidate_inputs(case, rng, n):
    h = case["input_hints"]
    return [[g3_value(rng, tag, name, h) for name, tag in case["params"]] for _ in range(n)]


# ---------------------------------------------------------------- G6 mode (--g6)
# Trusted Rust calls and standard collections (docs/G6_SPEC.md 10-13, SPEC.md 6d). Only generate_case(seed, index, g6=True) uses
# this block; it creates its own rng ("g6:<seed>:<index>"), so the streams of every other mode are untouched.
#
# A G6 case is a few fixed *fragments* (G6_FRAGS: `trusted rust fn rust_min/rust_max`, private collection helpers such as
# `grow`, `fill`, `bump`, `put` with `take` parameters and exact Vec/HashMap contracts) plus one public entry `fn f(..)`
# whose parameters are i64 / bool / [i64] / str and whose result is i64 / bool / str. Collection-bearing functions are private
# (G6_SPEC 3.2), so everything that crosses the f boundary is an existing public type. The collections are restricted to
# what the LLVM backend supports (G6_SPEC 13.1): Vec<i64|bool>, HashMap<i64|bool, i64|bool>, String; private helpers only
# use `len(..)` in `requires` (no v[i]/map_lookup there: LLVM run-time requires cannot evaluate them, 13.1).
#
# Ownership (10.4) holds by construction: every consuming argument is `move x` or a fresh call result, a binding is never used
# after a move, every branch/loop leaves the same bindings live (moves are reassigned right away, or the path returns), no
# unused call statement. About G6_BAD_SHARE of the cases are deliberately unproved but well-typed (dropped requires, false
# ensures, dropped invariant, or a body mutation such as an unguarded vec_get); they run in the two safe modes only and show
# the `pruv: foreign requires violated:` path at run time.

G6_BAD_SHARE = 0.30

# string pieces: ASCII and multibyte UTF-8 (written with \u escapes so this file stays ASCII); no quote/backslash/control chars
G6_LITS = ["ab", "hello, ", "-", "Z", "x y", "é", "ññ", "→", "a→b", "日本",
           "日本語", "\U0001F600", "x\U0001F600y", "héllo", "ünï→", "ß∑"]
G6_STR_POOL = ["", "", "a", "ab", "hello", "x y", "é", "nï→", "日本語", "\U0001F600", "z\U0001F600z",
               "0123456789", "Pruv"]

G6_FRAGS = {
    "rust_min": ("trusted rust fn rust_min(a: i64, b: i64) -> i64\n  ensures result <= a && result <= b\n"
                 "  ensures result == a || result == b\n  = \"::std::cmp::min\";"),
    "rust_max": ("trusted rust fn rust_max(a: i64, b: i64) -> i64\n  ensures result >= a && result >= b\n"
                 "  ensures result == a || result == b\n  = \"::std::cmp::max\";"),
    "keep": ("fn keep(take v: Vec<i64>) -> Vec<i64>\n  ensures len(result) == len(v)\n"
             "  ensures forall i in 0..len(v): result[i] == v[i]\n{\n  return move v;\n}"),
    "grow": ("fn grow(take v: Vec<i64>, x: i64) -> Vec<i64> ! alloc\n  requires len(v) < 1000\n"
             "  ensures len(result) == len(v) + 1\n  ensures result[len(v)] == x\n"
             "  ensures forall i in 0..len(v): result[i] == v[i]\n{\n  return vec_push::<i64>(move v, x);\n}"),
    "grow_twice": ("fn grow_twice(take v: Vec<i64>, x: i64) -> Vec<i64> ! alloc\n  requires len(v) < 900\n"
                   "  requires -1000 <= x && x <= 1000\n  ensures len(result) == len(v) + 2\n{\n"
                   "  let w: Vec<i64> = grow(move v, x);\n  return grow(move w, x + 1);\n}"),
    "fill": ("fn fill(take v: Vec<i64>, n: i64, x: i64) -> Vec<i64> ! alloc\n  requires 0 <= n && n <= 20\n"
             "  requires len(v) <= 100\n  ensures len(result) == len(v) + n\n{\n"
             "  let n0: i64 = len(v);\n  let mut w: Vec<i64> = move v;\n  let mut i: i64 = 0;\n  while i < n\n"
             "    invariant 0 <= i && i <= n\n    invariant len(w) == n0 + i\n    decreases n - i\n  {\n"
             "    w = vec_push::<i64>(move w, x);\n    i = i + 1;\n  }\n  return move w;\n}"),
    "bump": ("fn bump(take m: HashMap<i64, i64>, k: i64) -> HashMap<i64, i64> ! alloc\n  requires len(m) < 1000000\n"
             "  ensures len(result) <= len(m) + 1\n{\n"
             "  let c: Option<i64> = map_get::<i64, i64>(m, k);\n  match c {\n    Some(n) => {\n      if n < 1000000 {\n"
             "        return map_insert::<i64, i64>(move m, k, n + 1);\n      }\n      return move m;\n    }\n"
             "    None => { return map_insert::<i64, i64>(move m, k, 1); }\n  }\n}"),
    "count_of": ("fn count_of(m: HashMap<i64, i64>, k: i64) -> i64 {\n  let c: Option<i64> = map_get::<i64, i64>(m, k);\n"
                 "  match c {\n    Some(n) => { return n; }\n    None => { return 0; }\n  }\n}"),
    "put": ("fn put(take m: HashMap<i64, i64>, k: i64, x: i64) -> HashMap<i64, i64> ! alloc\n  requires len(m) < 1000000\n"
            "  ensures map_updated::<i64, i64>(result, m, k, x)\n{\n  return map_insert::<i64, i64>(move m, k, x);\n}"),
}
G6_DEPS = {"grow_twice": ["grow"]}


def g6_blen(s):
    """byte length of a string literal's UTF-8 encoding"""
    return len(s.encode("utf-8"))


class G6P(object):
    """Parts of one G6 case under construction."""

    def __init__(self, rng):
        self.rng = rng
        self.frags = []        # fragment names used (dependencies are added when rendering)
        self.params = []       # [[name, tag]]: "i64" "bool" "array" "str"
        self.ret = "i64"       # "i64" "bool" "str"
        self.effects = []
        self.requires = []
        self.ensures = []
        self.false_ens = []    # contract clauses that are false (offered to the defect step)
        self.body = []         # body lines (every line unique enough for exact-match mutations)
        self.muts = []         # [(old line, new line or None (delete), label)] well-typed body mutations
        self.hints = {"ranges": {}, "maxlen": {}, "elem": {}, "maxstr": {}}
        self.feats = set()
        self.mutation = None

    def use(self, *names):
        for n in names:
            if n not in self.frags:
                self.frags.append(n)


def g6_sum_expr(const, names):
    """'7 + len(a) + len(b)' (the constant is left out when 0)"""
    terms = ([str(const)] if const else []) + ["len(%s)" % n for n in names]
    return " + ".join(terms)


def g6_ladder(q, keys, vals, default, paren):
    """Exact contract of `map_get(m, q)` after inserting (keys[i], vals[i]) in order (later inserts win): one implication
    per insert, then the missing-key case. `paren` wraps values that are comparisons."""
    out = []
    n = len(keys)
    for i in range(n - 1, -1, -1):
        conds = ["%s != %s" % (q, keys[j]) for j in range(i + 1, n)] + ["%s == %s" % (q, keys[i])]
        out.append("%s ==> result == %s" % (" && ".join(conds), "(%s)" % vals[i] if paren else vals[i]))
    out.append("%s ==> result == %s" % (" && ".join("%s != %s" % (q, k) for k in keys), default))
    return out


# -- scenarios: each fills in params/ret/effects/requires/ensures/false_ens/body/muts/hints/feats of a G6P

def g6_sc_vecfill(P):
    """Vec built in a loop with invariants (len(v) == i, element facts), read back with vec_get."""
    rng = P.rng
    P.effects = ["alloc"]
    P.params = [["a", "array"]]
    P.hints["maxlen"]["a"] = 20
    P.feats.update(["vec", "loop_push", "vec_get", "move_reassign"])
    if rng.random() < 0.25:
        P.feats.add("vec_bool")
        T = lit(rng.randint(-3, 5))
        P.requires = ["len(a) <= 20"]
        P.body = [
            "  let mut v: Vec<bool> = vec_new::<bool>();",
            "  let mut i: i64 = 0;",
            "  while i < len(a)",
            "    invariant 0 <= i && i <= len(a)",
            "    invariant len(v) == i",
            "    invariant forall k in 0..i: v[k] == (a[k] > %s)" % T,
            "    decreases len(a) - i",
            "  {",
            "    v = vec_push::<bool>(move v, a[i] > %s);" % T,
            "    i = i + 1;",
            "  }",
        ]
        if rng.random() < 0.5:
            P.feats.add("count_loop")
            P.body += [
                "  let mut c: i64 = 0;",
                "  let mut j: i64 = 0;",
                "  while j < len(v)",
                "    invariant 0 <= j && j <= len(v)",
                "    invariant 0 <= c && c <= j",
                "    decreases len(v) - j",
                "  {",
                "    if vec_get::<bool>(v, j) {",
                "      c = c + 1;",
                "    }",
                "    j = j + 1;",
                "  }",
                "  return c;",
            ]
            P.ensures = ["0 <= result && result <= len(a)"]
            P.false_ens = ["result >= 1"]
            P.muts = [("    if vec_get::<bool>(v, j) {", "    if vec_get::<bool>(v, j + 1) {", "oob_get")]
        else:
            P.ret = "bool"
            P.body += [
                "  if len(v) == 0 {",
                "    return false;",
                "  }",
                "  return vec_get::<bool>(v, 0);",
            ]
            P.ensures = ["len(a) > 0 ==> result == (a[0] > %s)" % T]
            P.false_ens = ["result"]
            P.muts = [("  return vec_get::<bool>(v, 0);", "  return vec_get::<bool>(v, 1);", "oob_get")]
        return
    C = rng.randint(1, 9)
    B = 1000 + C
    P.requires = ["len(a) <= 20", "forall k in 0..len(a): 0 <= a[k] && a[k] <= 1000"]
    P.hints["elem"]["a"] = (0, 1000)
    P.body = [
        "  let mut v: Vec<i64> = vec_new::<i64>();",
        "  let mut i: i64 = 0;",
        "  while i < len(a)",
        "    invariant 0 <= i && i <= len(a)",
        "    invariant len(v) == i",
        "    invariant forall k in 0..i: v[k] == a[k] + %d" % C,
        "    invariant forall k in 0..i: 0 <= v[k] && v[k] <= %d" % B,
        "    decreases len(a) - i",
        "  {",
        "    v = vec_push::<i64>(move v, a[i] + %d);" % C,
        "    i = i + 1;",
        "  }",
    ]
    read = rng.choice(["len", "sum", "last", "idx"])
    if read == "len":
        P.body.append("  return len(v);")
        P.ensures = ["result == len(a)"]
        P.false_ens = ["result == len(a) + 1"]
    elif read == "sum":
        P.feats.add("sum_loop")
        P.body += [
            "  let mut s: i64 = 0;",
            "  let mut j: i64 = 0;",
            "  while j < len(v)",
            "    invariant 0 <= j && j <= len(v)",
            "    invariant 0 <= s && s <= %d * j" % B,
            "    decreases len(v) - j",
            "  {",
            "    s = s + vec_get::<i64>(v, j);",
            "    j = j + 1;",
            "  }",
            "  return s;",
        ]
        P.ensures = ["0 <= result && result <= %d * len(a)" % B]
        P.false_ens = ["result >= 1"]
        P.muts = [("    s = s + vec_get::<i64>(v, j);", "    s = s + vec_get::<i64>(v, j + 1);", "oob_get")]
    elif read == "last":
        P.body += [
            "  if len(v) == 0 {",
            "    return 0;",
            "  }",
            "  return vec_get::<i64>(v, len(v) - 1);",
        ]
        P.ensures = ["0 <= result && result <= %d" % B, "len(a) > 0 ==> result == a[len(a) - 1] + %d" % C]
        P.false_ens = ["result == 0"]
        P.muts = [("  return vec_get::<i64>(v, len(v) - 1);", "  return vec_get::<i64>(v, len(v));", "oob_get")]
    else:
        P.feats.add("guarded_index")
        P.params.append(["q", "i64"])
        P.hints["ranges"]["q"] = (-2, 24)
        P.body += [
            "  if 0 <= q && q < len(v) {",
            "    return vec_get::<i64>(v, q);",
            "  }",
            "  return -1;",
        ]
        P.ensures = ["0 <= q && q < len(a) ==> result == a[q] + %d" % C,
                     "!(0 <= q && q < len(a)) ==> result == -1"]
        P.false_ens = ["result >= 0"]
        P.muts = [("  if 0 <= q && q < len(v) {", "  if 0 <= q {", "unguarded_get")]


def g6_sc_vecguard(P):
    """Vec of i * M built up to a parameter n, read at a parameter index behind a bounds guard."""
    rng = P.rng
    M = rng.randint(1, 9)
    P.effects = ["alloc"]
    P.params = [["n", "i64"], ["k", "i64"]]
    P.hints["ranges"]["n"] = (0, 30)
    P.hints["ranges"]["k"] = (-3, 33)
    P.feats.update(["vec", "loop_push", "vec_get", "guarded_index", "move_reassign"])
    P.requires = ["0 <= n && n <= 30"]
    P.ensures = ["0 <= k && k < n ==> result == k * %d" % M, "!(0 <= k && k < n) ==> result == -1"]
    P.false_ens = ["result >= 0"]
    P.body = [
        "  let mut v: Vec<i64> = vec_new::<i64>();",
        "  let mut i: i64 = 0;",
        "  while i < n",
        "    invariant 0 <= i && i <= n",
        "    invariant len(v) == i",
        "    invariant forall j in 0..i: v[j] == j * %d" % M,
        "    decreases n - i",
        "  {",
        "    v = vec_push::<i64>(move v, i * %d);" % M,
        "    i = i + 1;",
        "  }",
        "  if 0 <= k && k < len(v) {",
        "    return vec_get::<i64>(v, k);",
        "  }",
        "  return -1;",
    ]
    P.muts = [("  if 0 <= k && k < len(v) {", "  if 0 <= k {", "unguarded_get")]


def g6_sc_histogram(P):
    """Counting with a taken HashMap<i64, i64> (bump), borrowed map (count_of); duplicate keys are likely."""
    rng = P.rng
    n = rng.randint(2, 4)
    pn = ["a", "b", "c", "d"][:n]
    P.use("bump", "count_of")
    P.effects = ["alloc"]
    P.params = [[x, "i64"] for x in pn] + [["q", "i64"]]
    P.feats.update(["hashmap", "take", "move_reassign", "map_get_match"])
    P.body = ["  let mut m: HashMap<i64, i64> = map_new::<i64, i64>();"]
    for x in pn:
        P.body.append("  m = bump(move m, %s);" % x)
    if rng.random() < 0.5:
        P.body.append("  return len(m);")
        P.ensures = ["1 <= result && result <= %d" % n]
        P.false_ens = ["result == %d" % n]
    else:
        P.body.append("  return count_of(m, q);")
        P.false_ens = ["result == 1"]
    P.muts = [("  m = bump(move m, a);", None, "dropped_bump")]


def g6_sc_mapladder(P):
    """Direct inserts (duplicate keys replace) and a lookup, with the exact contract of the lookup result."""
    rng = P.rng
    K, V = rng.choice([("i64", "i64"), ("i64", "i64"), ("i64", "bool"), ("bool", "i64"), ("bool", "bool")])
    via_put = K == "i64" and V == "i64" and rng.random() < 0.4
    n = rng.randint(2, 4)
    params = []

    def addp(name, ty):
        if all(p[0] != name for p in params):
            params.append([name, ty])

    keys, vals = [], []
    for i in range(n):
        if K == "i64":
            if rng.random() < 0.7:
                addp("abcd"[i], "i64")
                keys.append("abcd"[i])
            else:
                keys.append(str(rng.choice([0, 1, 2, 7])))
        else:
            if rng.random() < 0.5:
                addp("flag", "bool")
                keys.append("flag")
            else:
                keys.append(rng.choice(["true", "false"]))
        if V == "i64":
            if rng.random() < 0.3:
                addp("x", "i64")
                vals.append("x")
            else:
                vals.append(str(rng.randint(0, 99)))
        else:
            ip = [p[0] for p in params if p[1] == "i64"]
            c = rng.random()
            if ip and c < 0.4:
                vals.append("%s > %s" % (rng.choice(ip), lit(rng.randint(-2, 5))))
            elif any(p[0] == "flag" for p in params) and c < 0.6:
                vals.append("flag")
            else:
                vals.append(rng.choice(["true", "false"]))
    params.append(["q", K])
    P.params = params
    P.effects = ["alloc"]
    P.feats.update(["hashmap", "map_get_match", "key_" + K, "val_" + V, "move_reassign"])
    if via_put:
        P.use("put")
        P.feats.update(["take", "map_updated"])
    P.body = ["  let mut m: HashMap<%s, %s> = map_new::<%s, %s>();" % (K, V, K, V)]
    for k_, v_ in zip(keys, vals):
        if via_put:
            P.body.append("  m = put(move m, %s, %s);" % (k_, v_))
        else:
            P.body.append("  m = map_insert::<%s, %s>(move m, %s, %s);" % (K, V, k_, v_))
    if len(set(keys)) < len(keys):
        P.feats.add("duplicate_keys")
    first_insert = P.body[1]
    default = "-1" if V == "i64" else "false"
    if rng.random() < 0.75:
        P.feats.add("missing_key")
        some_line = "    Some(got) => { return got; }"
        P.ret = V
        P.body += [
            "  let r: Option<%s> = map_get::<%s, %s>(m, q);" % (V, K, V),
            "  match r {",
            some_line,
            "    None => { return %s; }" % default,
            "  }",
        ]
        P.ensures = g6_ladder("q", keys, vals, default, V == "bool")
        P.false_ens = ["result >= 0"] if V == "i64" else ["result"]
        if V == "i64":
            P.muts.append((some_line, "    Some(got) => { return got + 1; }", "payload_plus_one"))
    else:
        P.body.append("  return len(m);")
        P.ensures = ["1 <= result && result <= %d" % n]
        P.false_ens = ["result == %d" % n]
    P.muts.append((first_insert, None, "dropped_insert"))


def g6_sc_strbuild(P):
    """String assembled from str parameters and (multibyte) literals; len, string_byte, string_to_str."""
    rng = P.rng
    P.effects = ["alloc"]
    P.feats.update(["string", "string_push_str", "move_reassign"])
    names = ["a", "b"] if rng.random() < 0.5 else ["a"]
    P.params = [[n, "str"] for n in names]
    P.requires = ["len(%s) <= 100" % n for n in names]
    for n in names:
        P.hints["maxstr"][n] = 100
    items = [("par", n) for n in names] + [("lit", rng.choice(G6_LITS)) for _ in range(rng.randint(1, 2))]
    rng.shuffle(items)
    flag = rng.random() < 0.3
    const = 0
    P.body = ["  let mut s: String = string_new();"]
    for kind_, val in items:
        if kind_ == "lit":
            P.body.append('  s = string_push_str(move s, "%s");' % val)
            const += g6_blen(val)
            if g6_blen(val) > len(val):
                P.feats.add("multibyte_literal")
        else:
            P.body.append("  s = string_push_str(move s, %s);" % val)
    cases = [(None, const)]        # [(guard or None, constant part of the final length)]
    if flag:
        P.feats.add("branch_reinit")
        l1, l2 = rng.sample(G6_LITS, 2)
        P.params.append(["flag", "bool"])
        P.body += ["  if flag {", '    s = string_push_str(move s, "%s");' % l1, "  } else {",
                   '    s = string_push_str(move s, "%s");' % l2, "  }"]
        cases = [("flag", const + g6_blen(l1)), ("!flag", const + g6_blen(l2))]
        if any(g6_blen(x) > len(x) for x in (l1, l2)):
            P.feats.add("multibyte_literal")

    def len_ensures(prefix):
        if len(cases) == 1:
            return ["%s == %s" % (prefix, g6_sum_expr(cases[0][1], names))]
        return ["%s ==> %s == %s" % (g, prefix, g6_sum_expr(c, names)) for g, c in cases]

    kinds = ["len", "to_str", "to_str_len", "byte"] + ([] if flag else ["bool"])
    read = rng.choice(kinds)
    if read == "len":
        P.body.append("  return len(s);")
        P.ensures = len_ensures("result")
        P.false_ens = ["result == %s + 1" % g6_sum_expr(const, names)]
    elif read == "to_str":
        P.feats.add("string_to_str")
        P.ret = "str"
        P.body.append("  return string_to_str(s);")
        P.ensures = len_ensures("len(result)")
        P.false_ens = ["len(result) == %s + 1" % g6_sum_expr(const, names)]
    elif read == "to_str_len":
        P.feats.add("string_to_str")
        P.body += ["  let t: str = string_to_str(s);", "  return len(t);"]
        P.ensures = len_ensures("result")
        P.false_ens = ["result == %s + 1" % g6_sum_expr(const, names)]
    elif read == "byte":
        P.feats.add("string_byte")
        P.feats.add("guarded_index")
        P.params.append(["q", "i64"])
        P.hints["ranges"]["q"] = (-2, 40)
        P.body += [
            "  if 0 <= q && q < len(s) {",
            "    return string_byte(s, q);",
            "  }",
            "  return -1;",
        ]
        P.ensures = ["-1 <= result && result <= 255"]
        if not flag and items[0][0] == "par":
            P.feats.add("string_content")
            P.ensures.append("0 <= q && q < len(%s) ==> result == %s[q]" % (items[0][1], items[0][1]))
        P.false_ens = ["result >= 0"]
        P.muts = [("  if 0 <= q && q < len(s) {", "  if 0 <= q {", "unguarded_byte")]
    else:
        K = rng.randint(0, 12)
        P.ret = "bool"
        P.body.append("  return len(s) > %d;" % K)
        P.ensures = ["result == (%s > %d)" % (g6_sum_expr(const, names), K)]
        P.false_ens = ["result"]


def g6_sc_strloop(P):
    """Push a literal (and optionally a str parameter) n times; the length invariant is linear in i."""
    rng = P.rng
    word = rng.choice(G6_LITS)
    L = g6_blen(word)
    withp = rng.random() < 0.4
    P.effects = ["alloc"]
    P.params = [["n", "i64"]]
    P.hints["ranges"]["n"] = (0, 20)
    P.requires = ["0 <= n && n <= 20"]
    P.feats.update(["string", "string_push_str", "loop_push", "move_reassign"])
    if L > len(word):
        P.feats.add("multibyte_literal")
    push = ['    s = string_push_str(move s, "%s");' % word]
    if withp:
        P.params.append(["a", "str"])
        P.requires.append("len(a) <= 10")
        P.hints["maxstr"]["a"] = 10
        push.append("    s = string_push_str(move s, a);")
        inv = ["    invariant %d * i <= len(s)" % L, "    invariant len(s) <= %d * i" % (L + 10)]
        exact = ["%d * n <= %%s && %%s <= %d * n" % (L, L + 10)]
    else:
        inv = ["    invariant len(s) == %d * i" % L]
        exact = ["%%s == %d * n" % L]
    P.body = ["  let mut s: String = string_new();", "  let mut i: i64 = 0;", "  while i < n",
              "    invariant 0 <= i && i <= n"] + inv + ["    decreases n - i", "  {"] + push + ["    i = i + 1;", "  }"]
    read = rng.choice(["len", "to_str", "first"])
    if read == "len":
        P.body.append("  return len(s);")
        P.ensures = [e.replace("%s", "result") for e in exact]
        P.false_ens = ["result == %d * n + 1" % L] if not withp else ["result == %d * n" % L]
    elif read == "to_str":
        P.feats.add("string_to_str")
        P.ret = "str"
        P.body.append("  return string_to_str(s);")
        P.ensures = [e.replace("%s", "len(result)") for e in exact]
        P.false_ens = ["len(result) == %d * n + 1" % L] if not withp else ["len(result) == %d * n" % L]
    else:
        P.feats.update(["string_byte", "guarded_index"])
        P.body += [
            "  if len(s) > 0 {",
            "    return string_byte(s, 0);",
            "  }",
            "  return -1;",
        ]
        P.ensures = ["-1 <= result && result <= 255"]
        P.false_ens = ["result >= 0"]
        P.muts = [("  if len(s) > 0 {", "  if len(s) >= 0 {", "unguarded_byte")]


def g6_sc_take(P):
    """take helpers returning `move` values, a branch that moves and reinitializes, early returns inside a loop."""
    rng = P.rng
    P.effects = ["alloc"]
    P.feats.update(["vec", "take", "move_reassign"])
    which = rng.choice(["branch", "branch", "early", "fill"])
    if which == "branch":
        P.feats.add("branch_reinit")
        P.params = [["x", "i64"], ["y", "i64"], ["flag", "bool"]]
        P.requires = ["-1000 <= x && x <= 1000", "-1000 <= y && y <= 1000"]
        P.hints["ranges"]["x"] = (-1000, 1000)
        P.hints["ranges"]["y"] = (-1000, 1000)
        read = rng.choice(["len", "elem", "last"])
        P.use("grow")
        P.body = ["  let mut v: Vec<i64> = vec_new::<i64>();", "  v = grow(move v, x);"]
        if rng.random() < 0.5:
            P.use("keep")
            P.feats.add("take_returns_move")
            P.body.append("  v = keep(move v);")
        P.body += ["  if flag {", "    let t: Vec<i64> = move v;", "    v = grow(move t, y);", "  } else {"]
        else_len = 2
        if read == "len" and rng.random() < 0.6:
            P.use("grow_twice")
            P.body.append("    v = grow_twice(move v, y);")
            else_len = 3
        else:
            P.body.append("    v = grow(move v, x + y);")
        P.body.append("  }")
        if read == "len":
            P.body.append("  return len(v);")
            P.ensures = ["result == 2"] if else_len == 2 else ["flag ==> result == 2", "!flag ==> result == 3"]
            P.false_ens = ["result == 4"]
        elif read == "elem":
            P.feats.add("vec_get")
            P.body.append("  return vec_get::<i64>(v, 0);")
            P.ensures = ["result == x"]
            P.false_ens = ["result == y"]
        else:
            P.feats.add("vec_get")
            P.body.append("  return vec_get::<i64>(v, len(v) - 1);")
            P.ensures = ["flag ==> result == y", "!flag ==> result == x + y"]
            P.false_ens = ["result == x"]
            P.muts = [("  return vec_get::<i64>(v, len(v) - 1);", "  return vec_get::<i64>(v, len(v));", "oob_get")]
    elif which == "early":
        P.feats.add("early_return")
        P.use("grow")
        P.params = [["a", "array"], ["limit", "i64"]]
        P.requires = ["len(a) <= 20"]
        P.hints["maxlen"]["a"] = 20
        allbelow = rng.random() < 0.5
        P.body = ["  let mut v: Vec<i64> = vec_new::<i64>();", "  let mut i: i64 = 0;", "  while i < len(a)",
                  "    invariant 0 <= i && i <= len(a)", "    invariant len(v) == i"]
        if allbelow:
            P.ret = "bool"
            P.body.append("    invariant forall k in 0..i: a[k] <= limit")
        P.body += ["    decreases len(a) - i", "  {", "    if a[i] > limit {",
                   "      return %s;" % ("false" if allbelow else "len(v)"), "    }",
                   "    v = grow(move v, a[i]);", "    i = i + 1;", "  }",
                   "  return %s;" % ("len(v) == len(a)" if allbelow else "len(v)")]
        if allbelow:
            P.ensures = ["result ==> (len(a) == 0 || a[0] <= limit)"]
            P.false_ens = ["result"]
        else:
            P.ensures = ["0 <= result && result <= len(a)"]
            P.false_ens = ["result == len(a)"]
    else:
        P.use("fill")
        P.params = [["n", "i64"], ["x", "i64"]]
        P.requires = ["0 <= n && n <= 20", "-1000 <= x && x <= 1000"]
        P.hints["ranges"]["n"] = (0, 20)
        P.hints["ranges"]["x"] = (-1000, 1000)
        P.body = ["  let mut v: Vec<i64> = vec_new::<i64>();", "  v = fill(move v, n, x);",
                  "  v = fill(move v, n, x + 1);", "  return len(v);"]
        P.ensures = ["result == 2 * n"]
        P.false_ens = ["result == n"]


def g6_sc_minmax(P):
    """Trusted ::std::cmp::min / max under their exact contracts (also inside a collection loop)."""
    rng = P.rng
    which = rng.choice(["clamp", "clamp", "extreme3", "vecclip"])
    P.feats.add("trusted_call")
    if which == "clamp":
        P.use("rust_min", "rust_max")
        P.params = [["x", "i64"], ["lo", "i64"], ["hi", "i64"]]
        for n in ("x", "lo", "hi"):
            P.hints["ranges"][n] = (-12, 12)
        P.requires = ["lo <= hi"]
        P.ensures = ["lo <= result && result <= hi", "lo <= x && x <= hi ==> result == x"]
        P.false_ens = ["result == x"]
        if rng.random() < 0.5:
            P.body = ["  return rust_min(rust_max(x, lo), hi);"]
        else:
            P.body = ["  return rust_max(rust_min(x, hi), lo);"]
    elif which == "extreme3":
        fn = rng.choice(["rust_min", "rust_max"])
        P.use(fn)
        P.params = [["a", "i64"], ["b", "i64"], ["c", "i64"]]
        for n in ("a", "b", "c"):
            P.hints["ranges"][n] = (-5, 5)
        cmp_ = "<=" if fn == "rust_min" else ">="
        P.ensures = ["result %s a && result %s b && result %s c" % (cmp_, cmp_, cmp_),
                     "result == a || result == b || result == c"]
        P.false_ens = ["result == a"]
        P.body = ["  return %s(a, %s(b, c));" % (fn, fn)]
    else:
        P.use("rust_min", "rust_max")
        P.feats.update(["vec", "loop_push", "vec_get", "move_reassign"])
        P.effects = ["alloc"]
        P.params = [["a", "array"], ["cap", "i64"]]
        P.hints["maxlen"]["a"] = 20
        P.hints["elem"]["a"] = (0, 1000)
        P.hints["ranges"]["cap"] = (0, 1000)
        P.requires = ["len(a) <= 20", "forall k in 0..len(a): 0 <= a[k] && a[k] <= 1000", "0 <= cap && cap <= 1000"]
        P.ensures = ["0 <= result && result <= cap"]
        P.false_ens = ["result >= 1"]
        P.body = [
            "  let mut v: Vec<i64> = vec_new::<i64>();",
            "  let mut i: i64 = 0;",
            "  while i < len(a)",
            "    invariant 0 <= i && i <= len(a)",
            "    invariant len(v) == i",
            "    invariant forall k in 0..i: 0 <= v[k] && v[k] <= cap",
            "    decreases len(a) - i",
            "  {",
            "    v = vec_push::<i64>(move v, rust_min(a[i], cap));",
            "    i = i + 1;",
            "  }",
            "  let mut m: i64 = 0;",
            "  let mut j: i64 = 0;",
            "  while j < len(v)",
            "    invariant 0 <= j && j <= len(v)",
            "    invariant 0 <= m && m <= cap",
            "    decreases len(v) - j",
            "  {",
            "    m = rust_max(m, vec_get::<i64>(v, j));",
            "    j = j + 1;",
            "  }",
            "  return m;",
        ]
        P.muts = [("    m = rust_max(m, vec_get::<i64>(v, j));", "    m = rust_max(m, vec_get::<i64>(v, j + 1));", "oob_get")]


G6_SCENARIOS = [("vecfill", g6_sc_vecfill, 3.0), ("vecguard", g6_sc_vecguard, 1.5), ("histogram", g6_sc_histogram, 1.5),
                ("mapladder", g6_sc_mapladder, 3.0), ("strbuild", g6_sc_strbuild, 3.0), ("strloop", g6_sc_strloop, 1.5),
                ("take", g6_sc_take, 3.0), ("minmax", g6_sc_minmax, 2.0)]


def g6_pad(P):
    """Make sure the input space has at least 8 distinct points: a parameter list made only of bools gets an unused i64."""
    if not [t for _n, t in P.params if t in ("i64", "array", "str")]:
        P.params.append(["pad", "i64"])


def g6_defect(P):
    """Turn the case into a deliberately unproved (but well-typed) one. Returns False if nothing could be broken."""
    rng = P.rng
    kinds = []
    if P.requires:
        kinds.append("drop_requires")
    if P.false_ens:
        kinds.append("false_ensures")
    if P.muts:
        kinds.append("body_mut")
    if any(l.strip().startswith("invariant ") for l in P.body):
        kinds.append("drop_invariant")
    if not kinds:
        return False
    k = rng.choice(kinds)
    if k == "drop_requires":
        P.requires.pop(rng.randrange(len(P.requires)))
    elif k == "false_ensures":
        P.ensures.append(rng.choice(P.false_ens))
    elif k == "body_mut":
        old, new, label = rng.choice(P.muts)
        idx = P.body.index(old)
        if new is None:
            del P.body[idx]
        else:
            P.body[idx] = new
        k += ":" + label
    else:
        idx = [i for i, l in enumerate(P.body) if l.strip().startswith("invariant ")]
        del P.body[rng.choice(idx)]
    P.mutation = k
    return True


def g6_render(P, kind):
    names = []

    def add(n):
        for d in G6_DEPS.get(n, []):
            add(d)
        if n not in names:
            names.append(n)

    for n in P.frags:
        add(n)
    names.sort(key=lambda n: 0 if n.startswith("rust_") else 1)      # trusted declarations first (stable otherwise)
    parts = ["// g6 fuzz case: %s%s" % (kind, " (defect: %s)" % P.mutation if P.mutation else "")]
    parts += [G6_FRAGS[n] for n in names]
    head = "fn f(%s) -> %s" % (", ".join("%s: %s" % (n, {"array": "[i64]"}.get(t, t)) for n, t in P.params), P.ret)
    if P.effects:
        head += " ! " + ", ".join(P.effects)
    out = [head] + ["  requires " + r for r in P.requires] + ["  ensures " + e for e in P.ensures] + ["{"] + P.body + ["}"]
    parts.append("\n".join(out))
    return "\n\n".join(parts) + "\n"


def generate_g6_case(seed, index):
    rng = random.Random("g6:%s:%s" % (seed, index))
    want_bad = rng.random() < G6_BAD_SHARE
    P = G6P(rng)
    kind, fn, _w = rng.choices(G6_SCENARIOS, weights=[w for _k, _f, w in G6_SCENARIOS])[0]
    fn(P)
    g6_pad(P)
    if want_bad and g6_defect(P):
        P.hints["violate"] = 0.3      # unproved cases: reach the unguarded paths and the requires failures more often
    src = g6_render(P, kind)
    ret = {"array": "[i64]"}.get(P.ret, P.ret)
    return {"name": "c%s_%s" % (seed, index), "src": src, "entry": "f", "params": P.params, "ret": ret,
            "kind": "g6_" + kind, "input_hints": P.hints, "g6": True, "g6_bad": P.mutation is not None,
            "g6_mutation": P.mutation, "g6_features": sorted(P.feats)}


def g6_int_value(rng, rg):
    r = rng.random()
    if rg is not None:
        lo, hi = rg
        if r < 0.10:
            return rng.choice([lo, hi])
        if r < 0.15:
            return rng.choice([lo - 1, hi + 1])          # just outside the requires range
        if r < 0.60:
            a, b = max(lo, -4), min(hi, 9)
            if a <= b:
                return rng.randint(a, b)
        return rng.randint(lo, hi)
    if r < 0.04:
        return rng.choice(EXTREMES)
    if r < 0.80:
        return rng.randint(-4, 9)                         # small: map keys collide often
    return rng.choice([0, 1, -1, 2, 3, 7, 10, 20, 25, 100, 1000, -1000, 123456])


def g6_array(rng, name, h):
    mx = h["maxlen"].get(name, 8)
    if rng.random() < h.get("violate", 0.05):
        n = mx + rng.randint(1, 3)                        # longer than `len(a) <= mx`
    else:
        n = rng.choice([x for x in (0, 1, 1, 2, 3, 3, 4, 5, 6, 8, 12, 20) if x <= mx] or [0])
    rg = h["elem"].get(name)
    if rg is None:
        return [g6_int_value(rng, None) for _ in range(n)]
    lo, hi = rg
    if rng.random() < h.get("violate", 0.05):             # some element outside the element-range requires
        return [g6_int_value(rng, rg) for _ in range(n)]
    return [rng.choice([lo, hi, rng.randint(lo, hi), rng.randint(max(lo, -4), min(hi, 9))]) for _ in range(n)]


def g6_str_value(rng, name, h):
    s = "".join(rng.choice(G6_STR_POOL) for _ in range(rng.choice([0, 1, 1, 2, 2, 3])))
    mx = h["maxstr"].get(name)
    if mx is not None:
        if rng.random() < h.get("violate", 0.05):
            return "q" * (mx + rng.randint(1, 5))        # longer than the `len(s) <= mx` requires
        while g6_blen(s) > mx:
            s = s[:-1]                                    # drops whole characters, so the result stays valid
    return s


def g6_value(rng, tag, name, h):
    if tag == "i64":
        return g6_int_value(rng, h["ranges"].get(name))
    if tag == "bool":
        return rng.random() < 0.5
    if tag == "array":
        return g6_array(rng, name, h)
    if tag == "str":
        return g6_str_value(rng, name, h)
    raise ValueError("unknown G6 parameter type %r" % (tag,))


def g6_candidate_inputs(case, rng, n):
    h = case["input_hints"]
    return [[g6_value(rng, tag, name, h) for name, tag in case["params"]] for _ in range(n)]


# ---------------------------------------------------------------- G9 mode (--g9)
# Recursion, recursive types and buffer fields (docs/G9_SPEC.md 15.1, SPEC.md 6e). Only generate_case(seed, index, g9=True)
# uses this block; it creates its own rng ("g9:<seed>:<index>"), so the streams of every other mode are untouched.
#
# A G9 case is a few helper declarations (recursive functions with exactly one `decreases e`, recursive types, structs with
# buffer fields) plus one public entry `fn f(..)` whose parameters are i64 / [i64] and whose result is i64 or bool (recursive
# and buffer-field types never cross the f boundary, SPEC 6e). The program shapes rotate with the candidate index
# (G9_SHAPES): array-cursor recursion, mutual recursion with phase measures, a built linked list, a built tree (and a BST
# built by inserts) walked with `decreases size(t)`, JSON-like token cursor descent, and two clone/field-replacement shapes.
# Every bound that drives recursion depth or tree size is a small constant in f's `requires`, so run time and the oracle's
# Python recursion stay bounded. The contracts are modelled on programs that are known to verify (examples/g9_*.pruv,
# tests/runtime/g9_*.pruv, bench/g9/solutions/ref/*.pruv); the oracle re-checks every ensures at run time as well.
#
# About G9_BAD_SHARE of the cases are deliberately unproved but well-typed and terminating on every input that satisfies
# f's requires: a false ensures, a wrong `decreases` (not decreasing / wrong phase), a wrong return or base case, a missing
# base case (reaches an out-of-range index or a callee `requires` failure, never infinite recursion), a dropped helper
# ensures/requires (stale facts). A missing `decreases` is a type error (recursive_decreases), so it is not generated.
# They run in the two safe modes only (`--no-verify` does not check `decreases`).

G9_BAD_SHARE = 0.30
G9_SHAPES = ["arr", "mutual", "list", "tree", "bst", "tokens", "clone_bag", "clone_other"]
G9_TREE_DECL = "enum Tree { Empty, Node(value: i64, left: Tree, right: Tree) }"


class G9P(object):
    """Parts of one G9 case under construction."""

    def __init__(self, rng):
        self.rng = rng
        self.decls = []        # type declaration blocks
        self.helpers = []      # helper function blocks, in source order (recursive ones carry their own `decreases`)
        self.params = []       # [[name, tag]]: "i64" "array"
        self.ret = "i64"       # "i64" "bool"
        self.effects = []
        self.requires = []
        self.ensures = []
        self.false_ens = []    # contract clauses that are false (offered to the defect step)
        self.body = []
        self.muts = []         # [(old text, new text, label)]: first-occurrence replacements on the rendered program
        self.hints = {"ranges": {}, "maxlen": {}, "minlen": {}, "elem": {}, "tokens": {}}
        self.feats = set()
        self.detail = ""
        self.mutation = None


def g9_lines(*ls):
    return "\n".join(ls)


# -- Tree helpers shared by the tree, bst and clone_other shapes

def g9_t_build(kind, valexpr, leafv):
    leaf = "Tree::Node(%s, Tree::Empty, Tree::Empty)" % leafv
    if kind == "spine":
        ret, size = "Tree::Node(%s, build(d - 1), %s)" % (valexpr, leaf), "4 * d + 1"
    elif kind == "mirror":
        ret, size = "Tree::Node(%s, %s, build(d - 1))" % (valexpr, leaf), "4 * d + 1"
    else:
        ret, size = "Tree::Node(%s, build(d - 1), Tree::Empty)" % valexpr, "2 * d + 1"
    return g9_lines("fn build(d: i64) -> Tree ! alloc", "  requires 0 <= d && d <= 100",
                    "  ensures size(result) == %s" % size, "  decreases d", "{",
                    "  if d == 0 { return Tree::Empty; }", "  return %s;" % ret, "}")


G9_T_NODES = g9_lines(
    "fn tree_nodes(t: Tree) -> i64", "  requires size(t) <= 1000", "  ensures 2 * result + 1 == size(t)",
    "  decreases size(t)", "{", "  match t {", "    Tree::Empty => { return 0; }",
    "    Tree::Node(v, l, r) => { return 1 + tree_nodes(l) + tree_nodes(r); }", "  }", "}")

G9_T_DEPTH = g9_lines(
    "fn tree_depth(t: Tree) -> i64", "  requires size(t) <= 1000", "  ensures result >= 0 && result <= size(t)",
    "  decreases size(t)", "{", "  match t {", "    Tree::Empty => { return 0; }", "    Tree::Node(v, l, r) => {",
    "      let dl: i64 = tree_depth(l);", "      let dr: i64 = tree_depth(r);", "      if dl > dr { return 1 + dl; }",
    "      return 1 + dr;", "    }", "  }", "}")

G9_T_FILL = g9_lines(
    "fn fill(t: Tree, x: i64) -> Tree ! alloc", "  ensures size(result) == size(t)", "  decreases size(t)", "{",
    "  match t {", "    Tree::Empty => { return Tree::Empty; }",
    "    Tree::Node(v, l, r) => { return Tree::Node(x, fill(l, x), fill(r, x)); }", "  }", "}")

G9_T_INSERT = g9_lines(
    "fn insert(t: Tree, x: i64) -> Tree ! alloc", "  ensures size(result) == size(t) + 2", "  decreases size(t)", "{",
    "  match t {", "    Tree::Empty => { return Tree::Node(x, Tree::Empty, Tree::Empty); }", "    Tree::Node(v, l, r) => {",
    "      if x < v { return Tree::Node(v, insert(l, x), r); }", "      return Tree::Node(v, l, insert(r, x));", "    }",
    "  }", "}")


def g9_t_count(op):
    return g9_lines(
        "fn tree_count(t: Tree, x: i64) -> i64", "  requires size(t) <= 1000", "  ensures result >= 0 && result <= size(t)",
        "  decreases size(t)", "{", "  match t {", "    Tree::Empty => { return 0; }", "    Tree::Node(v, l, r) => {",
        "      if v %s x { return 1 + tree_count(l, x) + tree_count(r, x); }" % op,
        "      return tree_count(l, x) + tree_count(r, x);", "    }", "  }", "}")


def g9_t_sum(cl):
    return g9_lines(
        "fn clamp(v: i64) -> i64", "  ensures result >= 0 && result <= %d" % cl, "{", "  if v < 0 { return 0; }",
        "  if v > %d { return %d; }" % (cl, cl), "  return v;", "}", "",
        "fn tree_sum(t: Tree) -> i64", "  requires size(t) <= 1000", "  ensures result >= 0 && result <= %d * size(t)" % cl,
        "  decreases size(t)", "{", "  match t {", "    Tree::Empty => { return 0; }",
        "    Tree::Node(v, l, r) => { return clamp(v) + tree_sum(l) + tree_sum(r); }", "  }", "}")


G9_WALK_DEC = ("  decreases size(t)\n", "  decreases 0\n", "wrong_decreases")
G9_WALK_BOUND = ("  requires size(t) <= 1000\n", "", "dropped_walker_bound")


# -- scenarios: each fills in params/ret/effects/requires/ensures/false_ens/body/decls/helpers/muts/hints/feats of a G9P

def g9_sc_arr(P):
    """Direct recursion over an array cursor (search/count/sum/max) with `decreases len(a) - i`."""
    rng = P.rng
    N = rng.choice([8, 12, 16, 20])
    sub = rng.choice(["sum", "sum", "count", "find", "index", "below", "max"])
    P.detail = sub
    P.params = [["a", "array"]]
    P.hints["maxlen"]["a"] = N
    P.feats.update(["array_cursor", "direct_recursion", "arr_" + sub])
    lenreq = "len(a) <= %d" % N
    dec = ("  decreases len(a) - i\n", "  decreases len(a)\n", "wrong_decreases")
    if sub == "sum":
        H = rng.choice([10, 100, 1000])
        neg = rng.random() < 0.25
        lo = "0 - %d" % H if neg else "0"
        elem = "forall k in 0..len(a): %s <= a[k] && a[k] <= %d" % (lo, H)
        P.hints["elem"]["a"] = (-H if neg else 0, H)
        low_h = ("0 <= result + %d * (len(a) - i)" % H) if neg else "0 <= result"
        low_f = ("0 <= result + %d * len(a)" % H) if neg else "0 <= result"
        P.helpers.append(g9_lines(
            "fn sum_from(a: [i64], i: i64) -> i64", "  requires 0 <= i && i <= len(a)", "  requires " + lenreq,
            "  requires " + elem, "  ensures result == sum(k in i..len(a): a[k])",
            "  ensures %s && result <= %d * (len(a) - i)" % (low_h, H), "  decreases len(a) - i", "{",
            "  if i == len(a) { return 0; }", "  return a[i] + sum_from(a, i + 1);", "}"))
        P.requires = [lenreq, elem]
        P.ensures = ["result == sum(k in 0..len(a): a[k])", "%s && result <= %d * len(a)" % (low_f, H)]
        P.false_ens = ["result == %d * len(a) + 1" % H]
        P.body = ["  return sum_from(a, 0);"]
        P.muts = [("  return a[i] + sum_from(a, i + 1);", "  return a[i] + sum_from(a, i + 1) + 1;", "wrong_return"),
                  ("  if i == len(a) { return 0; }\n", "", "missing_base"), dec,
                  ("  ensures result == sum(k in i..len(a): a[k])\n", "", "weak_helper_ensures")]
    elif sub == "count":
        op = rng.choice([">", ">=", "<", "<=", "=="])
        P.params.append(["t", "i64"])
        P.hints["ranges"]["t"] = (-5, 9)
        P.helpers.append(g9_lines(
            "fn count_from(a: [i64], t: i64, i: i64) -> i64", "  requires 0 <= i && i <= len(a)", "  requires " + lenreq,
            "  ensures result == count(k in i..len(a): a[k] %s t)" % op, "  ensures 0 <= result && result <= len(a) - i",
            "  decreases len(a) - i", "{", "  if i == len(a) { return 0; }",
            "  if a[i] %s t { return 1 + count_from(a, t, i + 1); }" % op, "  return count_from(a, t, i + 1);", "}"))
        P.requires = [lenreq]
        P.ensures = ["result == count(k in 0..len(a): a[k] %s t)" % op, "0 <= result && result <= len(a)"]
        P.false_ens = ["result == len(a) + 1", "result == 0"]
        P.body = ["  return count_from(a, t, 0);"]
        P.muts = [("  if a[i] %s t { return 1 + count_from(a, t, i + 1); }" % op,
                   "  if a[i] %s t { return 2 + count_from(a, t, i + 1); }" % op, "wrong_return"),
                  ("  if i == len(a) { return 0; }\n", "", "missing_base"), dec,
                  ("  ensures result == count(k in i..len(a): a[k] %s t)\n" % op, "", "weak_helper_ensures")]
    elif sub == "find":
        P.ret = "bool"
        P.params.append(["x", "i64"])
        P.hints["ranges"]["x"] = (-5, 9)
        P.helpers.append(g9_lines(
            "fn find_from(a: [i64], i: i64, x: i64) -> bool", "  requires 0 <= i && i <= len(a)", "  requires " + lenreq,
            "  ensures !result ==> forall k in i..len(a): a[k] != x", "  ensures result ==> exists k in i..len(a): a[k] == x",
            "  decreases len(a) - i", "{", "  if i == len(a) { return false; }", "  if a[i] == x { return true; }",
            "  return find_from(a, i + 1, x);", "}"))
        P.requires = [lenreq]
        P.ensures = ["!result ==> forall k in 0..len(a): a[k] != x", "result ==> exists k in 0..len(a): a[k] == x"]
        P.false_ens = ["result", "!result"]
        P.body = ["  return find_from(a, 0, x);"]
        P.muts = [("  if a[i] == x { return true; }", "  if a[i] == x { return false; }", "wrong_return"),
                  ("  if i == len(a) { return false; }\n", "", "missing_base"), dec]
    elif sub == "index":
        P.params.append(["q", "i64"])
        P.hints["ranges"]["q"] = (-5, 9)
        P.helpers.append(g9_lines(
            "fn search_from(a: [i64], q: i64, i: i64) -> i64", "  requires 0 <= i && i <= len(a)", "  requires " + lenreq,
            "  requires forall k in 0..i: a[k] != q", "  ensures result == 0 - 1 || (i <= result && result < len(a))",
            "  ensures result >= 0 ==> a[result] == q && (forall k in 0..result: a[k] != q)",
            "  ensures result < 0 ==> (forall k in 0..len(a): a[k] != q)", "  decreases len(a) - i", "{",
            "  if i == len(a) { return 0 - 1; }", "  if a[i] == q { return i; }", "  return search_from(a, q, i + 1);", "}"))
        P.requires = [lenreq]
        P.ensures = ["result == 0 - 1 || (0 <= result && result < len(a))",
                     "result >= 0 ==> a[result] == q && (forall k in 0..result: a[k] != q)",
                     "result < 0 ==> (forall k in 0..len(a): a[k] != q)"]
        P.false_ens = ["result >= 0", "result < 0"]
        P.body = ["  return search_from(a, q, 0);"]
        P.muts = [("  if a[i] == q { return i; }", "  if a[i] == q { return i + 1; }", "wrong_return"),
                  ("  if i == len(a) { return 0 - 1; }\n", "", "missing_base"), dec,
                  ("  requires forall k in 0..i: a[k] != q\n", "", "dropped_helper_requires")]
    elif sub == "below":
        P.ret = "bool"
        P.params.append(["t", "i64"])
        P.hints["ranges"]["t"] = (-5, 9)
        P.helpers.append(g9_lines(
            "fn all_below_from(a: [i64], t: i64, i: i64) -> bool", "  requires 0 <= i && i <= len(a)", "  requires " + lenreq,
            "  ensures result == (forall k in i..len(a): a[k] < t)", "  decreases len(a) - i", "{",
            "  if i == len(a) { return true; }", "  if a[i] >= t { return false; }", "  return all_below_from(a, t, i + 1);", "}"))
        P.requires = [lenreq]
        P.ensures = ["result == (forall k in 0..len(a): a[k] < t)"]
        P.false_ens = ["result", "!result"]
        P.body = ["  return all_below_from(a, t, 0);"]
        P.muts = [("  if a[i] >= t { return false; }", "  if a[i] > t { return false; }", "wrong_boundary"),
                  ("  if i == len(a) { return true; }\n", "", "missing_base"), dec]
    else:
        P.hints["minlen"]["a"] = 1
        P.helpers.append(g9_lines(
            "fn max_from(a: [i64], i: i64) -> i64", "  requires 0 <= i && i < len(a)", "  requires " + lenreq,
            "  ensures forall k in i..len(a): a[k] <= result", "  ensures exists k in i..len(a): a[k] == result",
            "  decreases len(a) - i", "{", "  if i == len(a) - 1 { return a[i]; }", "  let m: i64 = max_from(a, i + 1);",
            "  if a[i] > m { return a[i]; }", "  return m;", "}"))
        P.requires = ["1 <= len(a)", lenreq]
        P.ensures = ["forall k in 0..len(a): a[k] <= result", "exists k in 0..len(a): a[k] == result"]
        P.false_ens = ["result == a[0]", "result > a[0]"]
        P.body = ["  return max_from(a, 0);"]
        P.muts = [("  if a[i] > m { return a[i]; }", "  if a[i] < m { return a[i]; }", "wrong_return"), dec,
                  ("  if i == len(a) - 1 { return a[i]; }\n", "", "missing_base")]


def g9_sc_mutual(P):
    """Mutual recursion with phase measures (ping/pong), a shared measure (even/odd), or alternating array sums."""
    rng = P.rng
    sub = rng.choice(["pingpong", "pingpong", "evenodd", "altsum"])
    P.detail = sub
    P.feats.update(["mutual_recursion", "mutual_" + sub])
    if sub == "pingpong":
        C, D, B = rng.randint(1, 9), rng.randint(0, 9), rng.choice([10, 20])
        P.feats.add("phase_measure")
        P.helpers.append(g9_lines(
            "fn ping(n: i64) -> i64", "  requires 0 <= n && n <= %d" % B, "  ensures result == %d * n + %d" % (C, D),
            "  decreases 2 * n + 1", "{", "  if n == 0 { return %d; }" % D, "  return pong(n);", "}", "",
            "fn pong(n: i64) -> i64", "  requires 1 <= n && n <= %d" % B, "  ensures result == %d * n + %d" % (C, D),
            "  decreases 2 * n", "{", "  return %d + ping(n - 1);" % C, "}"))
        P.params = [["n", "i64"]]
        P.hints["ranges"]["n"] = (0, B)
        P.requires = ["0 <= n && n <= %d" % B]
        if rng.random() < 0.4:
            P.params.append(["m", "i64"])
            P.hints["ranges"]["m"] = (0, B)
            P.requires.append("0 <= m && m <= %d" % B)
            P.ensures = ["result == %d * n + %d * m + %d" % (C, C, 2 * D)]
            P.false_ens = ["result == %d * n + %d * m + %d" % (C, C, 2 * D + 1)]
            P.body = ["  return ping(n) + ping(m);"]
        else:
            P.ensures = ["result == %d * n + %d" % (C, D)]
            P.false_ens = ["result == %d * n + %d" % (C, D + 1)]
            P.body = ["  return ping(n);"]
        P.muts = [("  decreases 2 * n\n", "  decreases 2 * n + 1\n", "wrong_phase"),
                  ("  return %d + ping(n - 1);" % C, "  return %d + ping(n - 1);" % (C + 1), "wrong_return"),
                  ("  if n == 0 { return %d; }" % D, "  if n == 0 { return %d; }" % (D + 1), "wrong_base"),
                  ("  ensures result == %d * n + %d\n" % (C, D), "", "weak_helper_ensures")]
    elif sub == "evenodd":
        B, K = rng.choice([20, 30]), rng.randint(0, 5)
        which = rng.choice(["even", "odd"])
        P.helpers.append(g9_lines(
            "fn even(n: i64) -> bool", "  requires n >= 0", "  ensures result == (n % 2 == 0)", "  decreases n", "{",
            "  if n == 0 { return true; }", "  return odd(n - 1);", "}", "",
            "fn odd(n: i64) -> bool", "  requires n >= 0", "  ensures result == (n % 2 == 1)", "  decreases n", "{",
            "  if n == 0 { return false; }", "  return even(n - 1);", "}"))
        arg = "n + %d" % K if K else "n"
        P.params = [["n", "i64"]]
        P.ret = "bool"
        P.hints["ranges"]["n"] = (0, B)
        P.requires = ["0 <= n && n <= %d" % B]
        par = 0 if which == "even" else 1
        P.ensures = ["result == ((%s) %% 2 == %d)" % (arg, par)]
        P.false_ens = ["result != ((%s) %% 2 == %d)" % (arg, par)]
        P.body = ["  return %s(%s);" % (which, arg)]
        P.muts = [("  if n == 0 { return true; }", "  if n == 0 { return false; }", "wrong_return"),
                  ("  decreases n\n", "  decreases 0\n", "wrong_decreases"),
                  ("  ensures result == (n % 2 == 0)\n", "", "weak_helper_ensures")]
    else:
        N, H = rng.choice([8, 12, 16, 20]), rng.choice([10, 100, 1000])
        lenreq = "len(a) <= %d" % N
        elem = "forall k in 0..len(a): 0 <= a[k] && a[k] <= %d" % H
        P.feats.update(["phase_measure", "array_cursor"])
        P.helpers.append(g9_lines(
            "fn alt_a(a: [i64], i: i64) -> i64", "  requires 0 <= i && i <= len(a)", "  requires " + lenreq, "  requires " + elem,
            "  ensures 0 <= result && result <= %d * (len(a) - i)" % H, "  decreases 2 * (len(a) - i) + 1", "{",
            "  if i == len(a) { return 0; }", "  return a[i] + alt_b(a, i + 1);", "}", "",
            "fn alt_b(a: [i64], i: i64) -> i64", "  requires 0 <= i && i <= len(a)", "  requires " + lenreq, "  requires " + elem,
            "  ensures 0 <= result && result <= %d * (len(a) - i)" % H, "  decreases 2 * (len(a) - i)", "{",
            "  if i == len(a) { return 0; }", "  return alt_a(a, i + 1);", "}"))
        P.params = [["a", "array"]]
        P.hints["maxlen"]["a"] = N
        P.hints["elem"]["a"] = (0, H)
        P.requires = [lenreq, elem]
        P.ensures = ["0 <= result && result <= %d * len(a)" % (2 * H)]
        P.false_ens = ["result == %d * len(a) + 1" % (2 * H)]
        P.body = ["  return alt_a(a, 0) + alt_b(a, 0);"]
        P.muts = [("  decreases 2 * (len(a) - i)\n", "  decreases 2 * (len(a) - i) + 1\n", "wrong_phase"),
                  ("  return a[i] + alt_b(a, i + 1);", "  return a[i] + a[i] + alt_b(a, i + 1);", "wrong_return"),
                  ("  if i == len(a) { return 0; }\n", "", "missing_base")]


def g9_sc_list(P):
    """A linked list (Node <-> Link) built from a clamped scalar, then walked with decreases size(..)."""
    rng = P.rng
    K, M, V0, CL = rng.choice([8, 12, 16]), rng.randint(1, 9), rng.randint(0, 9), rng.choice([10, 50, 100])
    sub = rng.choice(["len", "sum"])
    P.detail = sub
    P.effects = ["alloc"]
    P.feats.update(["recursive_struct", "linked_list", "size_contract", "mutual_recursion", "build_then_walk", "list_" + sub])
    P.decls = ["struct Node { value: i64, next: Link }\nenum Link { End, More(node: Node) }"]
    P.helpers.append(g9_lines(
        "fn single(v: i64) -> Node ! alloc", "  ensures size(result) == 2 && result.value == v", "{",
        "  return Node { value: v, next: Link::End };", "}", "",
        "fn push(n: Node, v: i64) -> Node ! alloc", "  ensures size(result) == size(n) + 2 && result.value == v", "{",
        "  return Node { value: v, next: Link::More(n) };", "}", "",
        "fn grow(k: i64) -> Node ! alloc", "  requires 0 <= k && k <= 100", "  ensures size(result) == 2 * k + 2",
        "  decreases k", "{", "  if k == 0 { return single(%d); }" % V0, "  let r: Node = grow(k - 1);",
        "  return push(r, k * %d);" % M, "}"))
    P.params = [["k", "i64"]]
    P.hints["ranges"]["k"] = (0, K)
    P.requires = ["0 <= k && k <= %d" % K]
    P.muts = [("  decreases k\n", "  decreases 0\n", "wrong_decreases_builder"),
              ("  if k == 0 { return single(%d); }" % V0, "  if k == 0 { return push(single(%d), 1); }" % V0, "wrong_base")]
    if sub == "len":
        P.helpers.append(g9_lines(
            "fn node_len(n: Node) -> i64", "  requires size(n) <= 1000", "  ensures 2 * result == size(n)",
            "  decreases size(n)", "{", "  return 1 + link_len(n.next);", "}", "",
            "fn link_len(l: Link) -> i64", "  requires size(l) <= 1000", "  ensures 2 * result + 1 == size(l)",
            "  decreases size(l)", "{", "  match l {", "    Link::End => { return 0; }",
            "    Link::More(n) => { return node_len(n); }", "  }", "}"))
        P.ensures = ["result == k + 1"]
        P.false_ens = ["result == k + 2", "result == k"]
        P.body = ["  let g: Node = grow(k);", "  return node_len(g);"]
        P.muts += [("  return 1 + link_len(n.next);", "  return 2 + link_len(n.next);", "wrong_return"),
                   ("  decreases size(n)\n", "  decreases 0\n", "wrong_decreases")]
    else:
        P.helpers.append(g9_lines(
            "fn clamp(v: i64) -> i64", "  ensures result >= 0 && result <= %d" % CL, "{", "  if v < 0 { return 0; }",
            "  if v > %d { return %d; }" % (CL, CL), "  return v;", "}", "",
            "fn node_sum(n: Node) -> i64", "  requires size(n) <= 1000", "  ensures 0 <= result && result <= %d * size(n)" % CL,
            "  decreases size(n)", "{", "  return clamp(n.value) + link_sum(n.next);", "}", "",
            "fn link_sum(l: Link) -> i64", "  requires size(l) <= 1000", "  ensures 0 <= result && result <= %d * size(l)" % CL,
            "  decreases size(l)", "{", "  match l {", "    Link::End => { return 0; }",
            "    Link::More(n) => { return node_sum(n); }", "  }", "}"))
        P.ensures = ["0 <= result && result <= %d * (2 * k + 2)" % CL]
        P.false_ens = ["result == %d * (2 * k + 2) + 1" % CL]
        P.body = ["  let g: Node = grow(k);", "  return node_sum(g);"]
        P.muts += [("  return clamp(n.value) + link_sum(n.next);", "  return clamp(n.value) + 1 + link_sum(n.next);", "wrong_return"),
                   ("  requires size(n) <= 1000\n", "", "dropped_helper_requires"),
                   ("  decreases size(n)\n", "  decreases 0\n", "wrong_decreases")]


def g9_sc_tree(P):
    """A finite tree built from a clamped scalar (spine / mirror / chain), then walked with decreases size(t)."""
    rng = P.rng
    bk = rng.choice(["spine", "mirror", "chain"])
    wk = rng.choice(["nodes", "sum", "count", "depth"])
    D, M, C = rng.choice([6, 8, 10]), rng.randint(1, 9), rng.randint(1, 9)
    valexpr = rng.choice(["d", "d * %d" % M, "d + %d" % C])
    leafv = rng.choice(["d", "d + %d" % C, str(rng.randint(0, 9))])
    sz = "2 * n + 1" if bk == "chain" else "4 * n + 1"
    nn = "n" if bk == "chain" else "2 * n"
    P.detail = bk + "_" + wk
    P.effects = ["alloc"]
    P.feats.update(["recursive_enum", "bounded_tree", "size_contract", "build_then_walk", "build_" + bk, "walk_" + wk])
    P.decls = [G9_TREE_DECL]
    P.helpers.append(g9_t_build(bk, valexpr, leafv))
    P.params = [["n", "i64"]]
    P.hints["ranges"]["n"] = (0, D)
    P.requires = ["0 <= n && n <= %d" % D]
    call = "tree_nodes(t)"
    P.muts = [("  if d == 0 { return Tree::Empty; }", "  if d == 0 { return Tree::Node(0, Tree::Empty, Tree::Empty); }", "wrong_base"),
              ("  decreases d\n", "  decreases 0\n", "wrong_decreases_builder")]
    if wk == "nodes":
        P.helpers.append(G9_T_NODES)
        P.ensures = ["result == %s" % nn]
        P.false_ens = ["result == %s + 1" % nn]
        P.muts += [("{ return 1 + tree_nodes(l) + tree_nodes(r); }", "{ return 2 + tree_nodes(l) + tree_nodes(r); }", "wrong_return"),
                   G9_WALK_DEC, G9_WALK_BOUND]
    elif wk == "sum":
        CL = rng.choice([10, 50, 100])
        P.helpers.append(g9_t_sum(CL))
        call = "tree_sum(t)"
        P.ensures = ["0 <= result && result <= %d * (%s)" % (CL, sz)]
        P.false_ens = ["result == %d * (%s) + 1" % (CL, sz)]
        P.muts += [("{ return clamp(v) + tree_sum(l) + tree_sum(r); }", "{ return clamp(v) + 1 + tree_sum(l) + tree_sum(r); }",
                    "wrong_return"), G9_WALK_DEC, G9_WALK_BOUND]
    elif wk == "count":
        op = rng.choice(["==", ">", "<", ">="])
        P.helpers.append(g9_t_count(op))
        P.params.append(["x", "i64"])
        P.hints["ranges"]["x"] = (-2, 14)
        call = "tree_count(t, x)"
        P.ensures = ["0 <= result && result <= %s" % sz]
        P.false_ens = ["result > %s" % sz, "result == 0"]
        P.muts += [("      if v %s x { return 1 + tree_count(l, x) + tree_count(r, x); }" % op,
                    "      if v %s x { return 2 + tree_count(l, x) + tree_count(r, x); }" % op, "wrong_return"),
                   G9_WALK_DEC, G9_WALK_BOUND]
    else:
        P.helpers.append(G9_T_DEPTH)
        call = "tree_depth(t)"
        P.ensures = ["0 <= result && result <= %s" % sz]
        P.false_ens = ["result > %s" % sz, "result == 0"]
        P.muts += [("      if dl > dr { return 1 + dl; }", "      if dl > dr { return 3 + dl; }", "wrong_return"),
                   G9_WALK_DEC, G9_WALK_BOUND]
    P.body = ["  let t: Tree = build(n);", "  return %s;" % call]


def g9_sc_bst(P):
    """A tree built by 2-4 inserts of scalar inputs (insert adds exactly two constructors), then walked."""
    rng = P.rng
    m = rng.randint(2, 4)
    names = ["a", "b", "c", "d"][:m]
    ops = [names[0]] + [names[i] if rng.random() < 0.8 else str(rng.randint(0, 9)) for i in range(1, m)]
    P.params = [[x, "i64"] for x in names if x in ops]
    P.effects = ["alloc"]
    sub = rng.choice(["nodes", "count"])
    P.detail = sub
    P.feats.update(["recursive_enum", "size_contract", "build_then_walk", "bst_insert", "walk_" + sub])
    P.decls = [G9_TREE_DECL]
    P.helpers.append(G9_T_INSERT)
    P.body = ["  let t0: Tree = Tree::Empty;"]
    for i, o in enumerate(ops, 1):
        P.body.append("  let t%d: Tree = insert(t%d, %s);" % (i, i - 1, o))
    P.muts = [("{ return Tree::Node(x, Tree::Empty, Tree::Empty); }",
               "{ return Tree::Node(x, Tree::Empty, Tree::Node(x, Tree::Empty, Tree::Empty)); }", "wrong_return"),
              ("      if x < v { return Tree::Node(v, insert(l, x), r); }",
               "      if x < v { return Tree::Node(v, insert(l, x), insert(r, x)); }", "duplicated_child"),
              ("  decreases size(t)\n", "  decreases 0\n", "wrong_decreases")]
    if sub == "nodes":
        P.helpers.append(G9_T_NODES)
        P.body.append("  return tree_nodes(t%d);" % m)
        P.ensures = ["result == %d" % m]
        P.false_ens = ["result == %d" % (m + 1)]
        P.muts.append(G9_WALK_BOUND)
    else:
        op = rng.choice([">", "<", "==", ">="])
        P.helpers.append(g9_t_count(op))
        P.params.append(["q", "i64"])
        P.body.append("  return tree_count(t%d, q);" % m)
        P.ensures = ["0 <= result && result <= %d" % (2 * m + 1)]
        P.false_ens = ["result > %d" % (2 * m + 1), "result == 0"]
        P.muts.append(("      if v %s x { return 1 + tree_count(l, x) + tree_count(r, x); }" % op,
                       "      if v %s x { return 2 + tree_count(l, x) + tree_count(r, x); }" % op, "wrong_return"))
        # the tree_count call in f names its argument q: the helper's own parameter stays x


def g9_sc_tokens(P):
    """JSON-like token cursor descent over an [i64] array (mutual recursion, measures 2*(len-i)+1 / +2)."""
    rng = P.rng
    A, O, C = rng.sample([0, 1, 2, 3], 3)
    N = rng.choice([10, 16, 20])
    sub = rng.choice(["is_value", "end"])
    P.detail = sub
    P.feats.update(["token_cursor", "mutual_recursion", "phase_measure", "array_cursor", "tokens_" + sub])
    P.helpers.append(g9_lines(
        "fn value_end(a: [i64], i: i64) -> i64", "  requires 0 <= i && i <= len(a) && len(a) <= %d" % N,
        "  ensures result == 0 - 1 || (i < result && result <= len(a))",
        "  ensures (i < len(a) && a[i] == %d) ==> result == i + 1" % A,
        "  ensures (i == len(a) || (a[i] != %d && a[i] != %d)) ==> result == 0 - 1" % (A, O),
        "  decreases 2 * (len(a) - i) + 1", "{", "  if i == len(a) { return 0 - 1; }", "  if a[i] == %d { return i + 1; }" % A,
        "  if a[i] != %d { return 0 - 1; }" % O, "  return items_end(a, i + 1);", "}", "",
        "fn items_end(a: [i64], j: i64) -> i64", "  requires 0 <= j && j <= len(a) && len(a) <= %d" % N,
        "  ensures result == 0 - 1 || (j < result && result <= len(a))", "  decreases 2 * (len(a) - j) + 2", "{",
        "  if j == len(a) { return 0 - 1; }", "  if a[j] == %d { return j + 1; }" % C, "  let k: i64 = value_end(a, j);",
        "  if k < 0 { return 0 - 1; }", "  return items_end(a, k);", "}"))
    P.params = [["a", "array"]]
    P.hints["maxlen"]["a"] = N
    P.hints["tokens"]["a"] = (A, O, C)
    P.requires = ["len(a) <= %d" % N]
    if sub == "is_value":
        P.ret = "bool"
        P.ensures = ["result ==> len(a) >= 1", "(len(a) == 1 && a[0] == %d) ==> result" % A,
                     "(len(a) >= 1 && a[0] == %d && len(a) != 1) ==> !result" % A]
        P.false_ens = ["result", "!result"]
        P.body = ["  return value_end(a, 0) == len(a);"]
    else:
        P.ensures = ["result == 0 - 1 || (0 < result && result <= len(a))", "(len(a) >= 1 && a[0] == %d) ==> result == 1" % A]
        P.false_ens = ["result == 0 - 1", "result >= 0"]
        P.body = ["  return value_end(a, 0);"]
    P.muts = [("  decreases 2 * (len(a) - j) + 2\n", "  decreases 2 * (len(a) - j) + 1\n", "wrong_phase"),
              ("  decreases 2 * (len(a) - i) + 1\n", "  decreases 0\n", "wrong_decreases"),
              ("  if a[i] == %d { return i + 1; }" % A, "  if a[i] == %d { return i + 2; }" % A, "wrong_return"),
              ("  if i == len(a) { return 0 - 1; }\n", "", "missing_base"),
              ("  if k < 0 { return 0 - 1; }\n", "", "missing_error_check")]


def g9_sc_clone_bag(P):
    """Struct with an [i64] buffer field: clone, change the copy's buffer through a mutable local, read the original."""
    rng = P.rng
    N = rng.choice([8, 12, 20])
    T = rng.randint(0, 9)
    read = rng.choice(["orig_first", "new_first", "orig_tag", "lens", "sum"])
    P.detail = read
    P.effects = ["alloc"]
    P.feats.update(["buffer_field", "clone_isolation", "field_replacement", "clone_" + read])
    P.decls = ["struct Bag { items: [i64], tag: i64 }"]
    P.helpers.append(g9_lines(
        "fn with_first(b: Bag, v: i64) -> Bag ! alloc", "  requires len(b.items) >= 1", "  ensures len(result.items) == len(b.items)",
        "  ensures result.items[0] == v", "{", "  let mut c: Bag = b;", "  let mut arr: [i64] = copy(c.items);", "  arr[0] = v;",
        "  c.items = copy(arr);", "  return c;", "}"))
    P.params = [["a", "array"], ["v", "i64"]]
    P.hints["maxlen"]["a"] = N
    P.hints["minlen"]["a"] = 1
    P.requires = ["1 <= len(a) && len(a) <= %d" % N]
    if read == "sum":
        P.requires.append("-1000000000 <= a[0] && a[0] <= 1000000000 && -1000000000 <= v && v <= 1000000000")
        P.hints["ranges"]["v"] = (-1000, 1000)
        P.hints["elem"]["a"] = (-1000, 1000)
    elif read == "orig_first":
        P.hints["ranges"]["v"] = (-5, 9)
    rexpr, ens, fe = {
        "orig_first": ("b.items[0]", "result == a[0]", "result == v"),
        "new_first": ("c.items[0]", "result == v", "result == a[0] + 1"),
        "orig_tag": ("b.tag", "result == %d" % T, "result == %d" % (T + 1)),
        "lens": ("len(b.items) + len(c.items)", "result == 2 * len(a)", "result == len(a)"),
        "sum": ("b.items[0] + c.items[0]", "result == a[0] + v", "result == a[0]"),
    }[read]
    P.ensures = [ens]
    P.false_ens = [fe]
    P.body = ["  let b: Bag = Bag { items: copy(a), tag: %d };" % T, "  let c: Bag = with_first(b, v);", "  return %s;" % rexpr]
    P.muts = [("  arr[0] = v;", "  arr[0] = v + 1;", "wrong_store"),
              ("  c.items = copy(arr);\n", "", "lost_field_replacement")]
    if read == "orig_first":
        P.muts.append(("  return b.items[0];", "  return c.items[0];", "lost_clone_isolation"))
    elif read == "new_first":
        P.muts.append(("  return c.items[0];", "  return b.items[0];", "stale_field_read"))
    elif read == "sum":
        P.muts.append(("  return b.items[0] + c.items[0];", "  return c.items[0] + c.items[0];", "lost_clone_isolation"))


def g9_sc_clone_other(P):
    """Clone isolation with a [u8] + str struct (field replacement) or with a deep-cloned recursive tree."""
    rng = P.rng
    P.effects = ["alloc"]
    if rng.random() < 0.55:
        read = rng.choice(["orig_first", "new_first", "lens", "sum", "labels"])
        P.detail = "packet_" + read
        P.feats.update(["buffer_field", "u8_field", "str_field", "clone_isolation", "field_replacement", "clone_" + read])
        P.decls = ["struct Packet { bytes: [u8], label: str }"]
        P.helpers.append(g9_lines(
            "fn replaced(p: Packet, v: i64) -> Packet ! alloc", "  requires len(p.bytes) >= 1 && 0 <= v && v <= 255",
            "  ensures len(result.bytes) == len(p.bytes)", "  ensures result.bytes[0] == v", "{", "  let mut q: Packet = p;",
            "  let mut ch: [u8] = copy(q.bytes);", "  ch[0] = v;", "  q.bytes = copy(ch);", "  q.label = copy(\"new\");",
            "  return q;", "}"))
        P.params = [["n", "i64"], ["x", "i64"], ["v", "i64"]]
        for nm, rg in (("n", (1, 8)), ("x", (0, 255)), ("v", (0, 255))):
            P.hints["ranges"][nm] = rg
        P.requires = ["1 <= n && n <= 8", "0 <= x && x <= 255", "0 <= v && v <= 255"]
        rexpr, ens, fe = {
            "orig_first": ("p.bytes[0]", "result == x", "result == v"),
            "new_first": ("q.bytes[0]", "result == v", "result == x"),
            "lens": ("len(p.bytes) + len(q.bytes)", "result == 2 * n", "result == n"),
            "sum": ("p.bytes[0] + q.bytes[0]", "result == x + v", "result == x"),
            "labels": ("len(p.label) + len(q.label)", "result == 5", "result == 4"),
        }[read]
        P.ensures = [ens]
        P.false_ens = [fe]
        P.body = ["  let raw: [u8] = alloc(n, x);", "  let p: Packet = Packet { bytes: copy(raw), label: \"ok\" };",
                  "  let q: Packet = replaced(p, v);", "  return %s;" % rexpr]
        P.muts = [("  ch[0] = v;", "  ch[0] = 0;", "wrong_store"), ("  q.bytes = copy(ch);\n", "", "lost_field_replacement")]
        if read == "orig_first":
            P.muts.append(("  return p.bytes[0];", "  return q.bytes[0];", "lost_clone_isolation"))
        elif read == "new_first":
            P.muts.append(("  return q.bytes[0];", "  return p.bytes[0];", "stale_field_read"))
        return
    D, M = rng.choice([6, 8, 10]), rng.randint(1, 9)
    valexpr = rng.choice(["d", "d * %d" % M, "d + %d" % rng.randint(1, 9)])
    leafv = rng.choice(["d", str(rng.randint(0, 9))])
    read = rng.choice(["nodes_orig", "nodes_clone", "count_orig", "count_clone"])
    P.detail = "tree_" + read
    P.feats.update(["recursive_enum", "size_contract", "deep_clone", "clone_isolation", "clone_" + read])
    P.decls = [G9_TREE_DECL]
    P.helpers += [g9_t_build("spine", valexpr, leafv), G9_T_FILL]
    P.params = [["n", "i64"], ["x", "i64"]]
    P.hints["ranges"]["n"] = (0, D)
    P.hints["ranges"]["x"] = (-2, 14)
    P.requires = ["0 <= n && n <= %d" % D]
    who = "a" if read.endswith("orig") else "c"
    if read.startswith("nodes"):
        P.helpers.append(G9_T_NODES)
        P.ensures = ["result == 2 * n"]
        P.false_ens = ["result == 2 * n + 1"]
        call = "tree_nodes(%s)" % who
    else:
        P.helpers.append(g9_t_count("=="))
        P.ensures = ["0 <= result && result <= 4 * n + 1"]
        P.false_ens = ["result > 4 * n + 1", "result == 0"]
        call = "tree_count(%s, x)" % who
    P.body = ["  let a: Tree = build(n);", "  let mut c: Tree = a;", "  c = fill(c, x);", "  return %s;" % call]
    P.muts = [("{ return Tree::Node(x, fill(l, x), fill(r, x)); }", "{ return Tree::Node(x, fill(l, x), Tree::Empty); }", "wrong_clone_child"),
              ("  if d == 0 { return Tree::Empty; }", "  if d == 0 { return Tree::Node(0, Tree::Empty, Tree::Empty); }", "wrong_base"),
              ("  decreases size(t)\n", "  decreases 0\n", "wrong_decreases")]


G9_SCENARIOS = {"arr": g9_sc_arr, "mutual": g9_sc_mutual, "list": g9_sc_list, "tree": g9_sc_tree, "bst": g9_sc_bst,
                "tokens": g9_sc_tokens, "clone_bag": g9_sc_clone_bag, "clone_other": g9_sc_clone_other}


def g9_render(P, kind, edit=None, mutation=None):
    blocks = list(P.decls) + list(P.helpers)
    sig = ", ".join("%s: %s" % (n, {"array": "[i64]"}.get(t, t)) for n, t in P.params)
    head = "fn f(%s) -> %s" % (sig, P.ret)
    if P.effects:
        head += " ! " + ", ".join(P.effects)
    out = [head] + ["  requires " + r for r in P.requires] + ["  ensures " + e for e in P.ensures] + ["{"] + P.body + ["}"]
    blocks.append("\n".join(out))
    text = "\n\n".join(blocks) + "\n"
    if edit is not None:
        text = text.replace(edit[0], edit[1], 1)
    return "// g9 fuzz case: %s%s\n%s" % (kind, " (defect: %s)" % mutation if mutation else "", text)


def generate_g9_case(seed, index):
    rng = random.Random("g9:%s:%s" % (seed, index))
    shape = G9_SHAPES[index % len(G9_SHAPES)]
    want_bad = rng.random() < G9_BAD_SHARE
    P = G9P(rng)
    G9_SCENARIOS[shape](P)
    kind = "g9_%s_%s" % (shape, P.detail) if P.detail else "g9_" + shape
    edit = None
    if want_bad:
        base = g9_render(P, kind)
        valid = [m for m in P.muts if m[0] in base]
        choices = (["false_ensures"] if P.false_ens else []) + ["body_mut"] * 3 * (1 if valid else 0)
        if choices:
            c = rng.choice(choices)
            if c == "false_ensures":
                P.ensures.append(rng.choice(P.false_ens))
                P.mutation = "false_ensures"
            else:
                edit = rng.choice(valid)
                P.mutation = "body_mut:" + edit[2]
            P.hints["violate"] = 0.3      # unproved cases: reach the requires failures more often
    src = g9_render(P, kind, edit, P.mutation)
    ret = {"array": "[i64]"}.get(P.ret, P.ret)
    return {"name": "c%s_%s" % (seed, index), "src": src, "entry": "f", "params": P.params, "ret": ret,
            "kind": kind, "input_hints": P.hints, "g9": True, "g9_bad": P.mutation is not None,
            "g9_mutation": P.mutation, "g9_features": sorted(P.feats | {"shape_" + shape})}


def g9_tokens(rng, tok, mx):
    """A random nested token sequence (atom / open items* close), then corrupted about half of the time."""
    A, O, C = tok
    out = []

    def val(depth):
        if depth >= 3 or len(out) > mx - 4 or rng.random() < 0.45:
            out.append(A)
            return
        out.append(O)
        for _ in range(rng.choice([0, 1, 1, 2, 3])):
            if len(out) > mx - 4:
                break
            val(depth + 1)
        out.append(C)

    val(0)
    r = rng.random()
    if r < 0.15 and out:
        out.pop()                                        # truncated
    elif r < 0.30 and out:
        out[rng.randrange(len(out))] = rng.choice([A, O, C, 3, 7])
    elif r < 0.40:
        out.append(rng.choice([A, C]))                   # trailing junk
    elif r < 0.48:
        out = [rng.choice([A, O, C]) for _ in range(rng.randint(0, 6))]
    elif r < 0.52:
        out = []
    return out[:mx]


def g9_array(rng, name, h):
    mx = h["maxlen"].get(name, 8)
    mn = h["minlen"].get(name, 0)
    viol = rng.random() < h.get("violate", 0.05)
    tok = h["tokens"].get(name)
    if tok is not None:
        arr = g9_tokens(rng, tok, mx)
        if viol:
            arr = arr + [tok[0]] * (mx + rng.randint(1, 3) - len(arr))       # longer than the `len(a) <= mx` requires
        return arr
    if viol:
        n = mx + rng.randint(1, 3)
    else:
        n = rng.choice([x for x in (0, 1, 1, 2, 3, 3, 4, 5, 6, 8, 10, 12, 16, 20) if mn <= x <= mx] or [mn])
    rg = h["elem"].get(name)
    if rg is None:
        return [rng.randint(-5, 9) if rng.random() < 0.85 else g6_int_value(rng, None) for _ in range(n)]
    lo, hi = rg
    out = [rng.choice([lo, hi, rng.randint(lo, hi), rng.randint(max(lo, -4), min(hi, 9))]) for _ in range(n)]
    if out and rng.random() < h.get("violate", 0.05):
        out[rng.randrange(len(out))] = hi + rng.randint(1, 3)         # one element outside the element-range requires
    return out


def g9_value(rng, tag, name, h):
    if tag == "i64":
        return g6_int_value(rng, h["ranges"].get(name))
    if tag == "bool":
        return rng.random() < 0.5
    if tag == "array":
        return g9_array(rng, name, h)
    raise ValueError("unknown G9 parameter type %r" % (tag,))


def g9_candidate_inputs(case, rng, n):
    h = case["input_hints"]
    return [[g9_value(rng, tag, name, h) for name, tag in case["params"]] for _ in range(n)]


# ---------------------------------------------------------------- G4 (modules)
# A G4 case is a directory-shaped program: `files` maps a relative path to its source, `root.pruv` is the root and
# `mod name;` in P loads P/name.pruv (root: name.pruv). 2-5 modules per program, some with a nested module a/b.pruv.
# The root has one `pub fn f(x: i64, ..) -> i64` (the host entry the harness calls with the inputs), optionally more
# root `pub` scalar helpers (also host entries, callable from child modules as `crate::h(..)`) and private helpers.
# Every program is meant to verify. Variety: private/public helpers, the same leaf function/struct/enum name in several
# modules with different bodies/fields, generic functions called by path (`crate::g::pick::<i64>(..)`), structs and enums
# used by full path (types, literals, patterns), cross-module calls in both directions (the call graph between
# FUNCTIONS is acyclic: a function only calls functions created before it; module-level cycles are allowed), and
# "contract-preserving body replacement" twins: two programs (consecutive candidate indexes 2k, 2k+1) that are identical
# except one callee body, both satisfying the same functional contract; callers must produce identical results.
# Every function has a functional (`result == <affine expression of the parameters>`) or a range contract and every
# call site is built so that the callee's `requires` follow from interval arithmetic over the caller's parameter ranges.

G4_MODS = ["alpha", "beta", "gamma", "calc", "geo", "metrics", "store", "rules", "tools", "codec", "ledger", "shapes"]
G4_FNS = ["helper", "adjust", "combine", "scale", "mix", "bump", "shift", "blend", "step", "fold", "f"]
G4_STRUCTS = ["Pair", "Cell", "Item"]
G4_FIELDS = [("v", "w"), ("left", "right"), ("p", "q"), ("lo", "hi")]
G4_ENUMS = [("Mode", "Low", "High"), ("Kind", "Cold", "Warm"), ("Shape", "Small", "Large")]
G4_GEN_NAMES = ["pick", "id", "first", "repeat", "boxed", "unbox", "Boxed"]

# Expression nodes (tuples): ("int", n) ("var", name, lo, hi) ("loc", name, lo, hi, closed) ("add", a, b) ("sub", a, b)
# ("mul", k, a). `var` is a parameter, `loc` a let-bound call result (closed = its parameters-only form, or None if only a
# range is known).

def g4_range(e):
    k = e[0]
    if k == "int":
        return e[1], e[1]
    if k in ("var", "loc"):
        return e[2], e[3]
    if k == "mul":
        lo, hi = g4_range(e[2])
        a, b = e[1] * lo, e[1] * hi
        return min(a, b), max(a, b)
    (a, b), (c, d) = g4_range(e[1]), g4_range(e[2])
    return (a + c, b + d) if k == "add" else (a - d, b - c)


def g4_flat(e):
    """Parameters-only form of e (locals replaced by their closed forms), or None if some local only has a range."""
    k = e[0]
    if k in ("int", "var"):
        return e
    if k == "loc":
        return e[4]
    if k == "mul":
        x = g4_flat(e[2])
        return None if x is None else ("mul", e[1], x)
    a, b = g4_flat(e[1]), g4_flat(e[2])
    return None if a is None or b is None else (k, a, b)


def g4_subst(e, env):
    """Instantiate a callee's closed form (vars/ints only) with argument nodes."""
    k = e[0]
    if k == "var":
        return env[e[1]]
    if k == "int":
        return e
    if k == "mul":
        return ("mul", e[1], g4_subst(e[2], env))
    return (k, g4_subst(e[1], env), g4_subst(e[2], env))


def g4_text(e, closed=False, top=True):
    k = e[0]
    if k == "int":
        return lit(e[1])
    if k == "var":
        return e[1]
    if k == "loc":
        return g4_text(e[4], True, top) if closed else e[1]
    if k == "mul":
        s = "%s * %s" % (lit(e[1]), g4_text(e[2], closed, False))
    else:
        s = "%s %s %s" % (g4_text(e[1], closed, False), "+" if k == "add" else "-", g4_text(e[2], closed, False))
    return s if top else "(" + s + ")"


def g4_req(name, lo, hi):
    return "%s <= %s && %s <= %s" % (lit(lo), name, name, lit(hi))


def g4_fn_text(name, pub, params, ret, fx, requires, ensures, body):
    """params: [(name, type text)]."""
    head = "%sfn %s(%s) -> %s" % ("pub " if pub else "", name, ", ".join("%s: %s" % p for p in params), ret)
    if fx:
        head += " ! " + ", ".join(sorted(fx))
    return "\n".join([head] + ["  requires " + r for r in requires] + ["  ensures " + e for e in ensures]
                     + ["{"] + body + ["}"])


def g4_range_clause(lo, hi):
    return "%s <= result && result <= %s" % (lit(lo), lit(hi))


class G4Gen(object):
    """Builds one G4 program. All randomness comes from `rng`; `variant` (0/1) only selects the replaced body of a twin."""

    def __init__(self, rng, variant, twin):
        self.rng, self.variant, self.twin = rng, variant, twin
        self.mods = []
        self.blocks, self.used = {}, {}
        self.funcs = []                  # int -> int functions in creation order (the only callable ones)
        self.struct_apis, self.enum_apis, self.gen_api = [], [], None
        self.struct_decl = {}            # module -> (leaf, fields)
        self.fn_names, self.type_names = {}, {}
        self.feats = set()
        self.twin_func = None

    # ---- layout
    def kids(self, path):
        return [m for m in self.mods if len(m) == len(path) + 1 and m[:len(path)] == path]

    def layout(self, n):
        rng = self.rng
        pool = list(G4_MODS)
        rng.shuffle(pool)
        mods = [()]
        want_nested = n >= 3 and rng.random() < 0.65
        ntop = rng.randint(1, min(3, n - 1))
        if want_nested:
            ntop = min(ntop, n - 2)
        for _ in range(ntop):
            mods.append((pool.pop(),))
        while len(mods) < n:
            parent = rng.choice([m for m in mods if 1 <= len(m) <= 2])
            sib = set(m[-1] for m in mods if len(m) == len(parent) + 1 and m[:len(parent)] == parent)
            reuse = [m[-1] for m in mods[1:] if m[-1] not in sib and m[-1] != parent[-1]]
            if reuse and rng.random() < 0.35:
                name = rng.choice(reuse)             # same leaf module name under another parent (a/util, b/util)
            else:
                name = pool.pop()
            mods.append(parent + (name,))
        self.mods = mods
        for m in mods:
            self.blocks[m] = []
        for m in mods:
            self.used[m] = set(c[-1] for c in self.kids(m))
        self.used[()].add("f")
        if any(len(m) >= 2 for m in mods):
            self.feats.add("nested_module")

    # ---- names and paths
    def ref(self, path, name, here, qualify=False):
        if path == here and not qualify:
            return name
        return "::".join(("crate",) + path + (name,))

    def fresh_fn(self, path):
        rng, taken = self.rng, self.used[path]
        pool = [n for n in G4_FNS if n not in taken]
        rep = [n for n in pool if any(n in self.used[m] for m in self.mods if m != path)]
        fresh = [n for n in pool if n not in rep]
        if rep and (not fresh or rng.random() < 0.5):
            n = rng.choice(rep)
        elif fresh:
            n = rng.choice(fresh)
        else:
            n = "fn%d" % len(taken)
        taken.add(n)
        self.fn_names.setdefault(n, set()).add(path)
        return n

    def is_pub(self, path):
        return self.rng.random() < (0.75 if path == () else 0.55)

    def prange(self, big):
        R = self.rng.choice([10000, 100000, 1000000] if big else [100, 1000, 10000])
        return (-R, R) if self.rng.random() < 0.6 else (0, R)

    def make_params(self, n, big):
        return [(nm,) + self.prange(big) for nm in ["x", "y", "z"][:n]]

    def visible(self, path):
        return [f for f in self.funcs if f["pub"] or f["mod"] == path]

    def add_func(self, mod, name, pub, params, closed, out, fx, text):
        self.blocks[mod].append(text)
        self.funcs.append({"mod": mod, "name": name, "pub": pub, "params": params, "closed": closed, "out": out,
                           "fx": frozenset(fx)})
        self.feats.add("pub_fn" if pub else "private_fn")

    def int_fn(self, mod, name, pub, params, closed, out, fx, ens, body):
        text = g4_fn_text(name, pub, [(p[0], "i64") for p in params], "i64", fx,
                          [g4_req(*p) for p in params], ens, body)
        self.add_func(mod, name, pub, params, closed, out, fx, text)

    def contract(self, closed, out):
        ens = []
        if closed is not None:
            ens.append("result == %s" % g4_text(closed, True))
            if self.rng.random() < 0.25:
                ens.append(g4_range_clause(*g4_range(closed)))
        else:
            ens.append(g4_range_clause(*out))
        return ens

    def note_call(self, caller, callee):
        if caller == callee:
            return
        if callee == caller[:len(callee)]:
            self.feats.add("call_to_ancestor")       # child -> parent / root
        elif caller == callee[:len(caller)]:
            self.feats.add("call_to_descendant")     # parent / root -> child
        else:
            self.feats.add("call_sideways")
        self.feats.add("cross_module_call")

    # ---- expression building
    def pick_arg(self, avail, plo, phi):
        """An argument node whose interval lies inside [plo, phi]: a value as is, a shifted value, or a constant."""
        rng = self.rng
        order = list(avail)
        rng.shuffle(order)
        for v in order:
            lo, hi = g4_range(v)
            if plo <= lo and hi <= phi:
                return v
        for v in order:
            lo, hi = g4_range(v)
            if hi - lo <= phi - plo:
                off = plo - lo
                return ("add", v, ("int", off)) if off else v
        return ("int", rng.randint(plo, min(phi, plo + 5)))

    def combine(self, avail, must):
        rng = self.rng
        pool = [a for a in avail if a not in must]
        terms = list(must) + rng.sample(pool, min(len(pool), rng.choice([0, 1, 1, 2])))
        if not terms:
            terms = [rng.choice(avail)]
        node = None
        for v in terms:
            k = rng.choice([1, 1, 1, 2, 3, -1])
            t = v if k == 1 else ("mul", k, v)
            node = t if node is None else (rng.choice(["add", "add", "sub"]), node, t)
        c = rng.choice([0, 0, 1, 2, 5, -3])
        if c:
            node = ("add", node, ("int", c))
        return node

    # ---- function flavors
    def f_compose(self, mod, pub=None, name=None, nparams=None, big=False, force=(), min_calls=0):
        """Calls to earlier functions (any visible module) combined affinely, optionally through an if."""
        rng = self.rng
        name = name or self.fresh_fn(mod)
        pub = self.is_pub(mod) if pub is None else pub
        params = self.make_params(nparams or rng.choice([1, 1, 2, 2, 3]), big)
        avail = [("var",) + p for p in params]
        cands = self.visible(mod)
        todo = list(force)
        if cands:
            for _ in range(max(rng.choice([0, 1, 1, 2, 2, 3]), min_calls - len(todo))):
                todo.append(rng.choice(cands))
        lines, fx, locs = [], set(), []
        for i, callee in enumerate(todo):
            args = [self.pick_arg(avail, plo, phi) for _n, plo, phi in callee["params"]]
            env = dict((pn, a) for (pn, _l, _h), a in zip(callee["params"], args))
            flat = g4_flat(g4_subst(callee["closed"], env)) if callee["closed"] is not None else None
            lo, hi = g4_range(flat) if flat is not None else callee["out"]
            loc = ("loc", "t%d" % (i + 1), lo, hi, flat)
            cname = self.ref(callee["mod"], callee["name"], mod, rng.random() < 0.2)
            lines.append("  let %s: i64 = %s(%s);" % (loc[1], cname, ", ".join(g4_text(a) for a in args)))
            avail.append(loc)
            locs.append(loc)
            fx |= callee["fx"]
            self.note_call(mod, callee["mod"])
        must = locs[:len(force)]
        if rng.random() < 0.25:
            a = rng.choice(avail)
            alo, ahi = g4_range(a)
            thr = rng.randint(alo, ahi)
            e1, e2 = self.combine(avail, must), self.combine(avail, must)
            lines += ["  if %s < %s {" % (g4_text(a), lit(thr)), "    return %s;" % g4_text(e1), "  }",
                      "  return %s;" % g4_text(e2)]
            (l1, h1), (l2, h2) = g4_range(e1), g4_range(e2)
            closed, out = None, (min(l1, l2), max(h1, h2))
            self.feats.add("branch")
        else:
            node = self.combine(avail, must)
            lines.append("  return %s;" % g4_text(node))
            closed = g4_flat(node)
            out = g4_range(closed) if closed is not None else g4_range(node)
        self.int_fn(mod, name, pub, params, closed, out, fx, self.contract(closed, out), lines)

    def f_clamp(self, mod):
        rng = self.rng
        name, pub = self.fresh_fn(mod), self.is_pub(mod)
        p = self.make_params(1, False)
        lo2 = rng.randint(-50, 50)
        hi2 = lo2 + rng.randint(0, 100)
        body = ["  if x < %s {" % lit(lo2), "    return %s;" % lit(lo2), "  }",
                "  if x > %s {" % lit(hi2), "    return %s;" % lit(hi2), "  }", "  return x;"]
        ens = [g4_range_clause(lo2, hi2), "(%s <= x && x <= %s) ==> result == x" % (lit(lo2), lit(hi2))]
        self.int_fn(mod, name, pub, p, None, (lo2, hi2), (), ens, body)

    def f_absdiff(self, mod):
        name, pub = self.fresh_fn(mod), self.is_pub(mod)
        ps = self.make_params(2, False)
        B = max(ps[0][2] - ps[1][1], ps[1][2] - ps[0][1])
        body = ["  if x >= y {", "    return x - y;", "  }", "  return y - x;"]
        ens = ["0 <= result && result <= %s" % lit(B), "x >= y ==> result == x - y"]
        self.int_fn(mod, name, pub, ps, None, (0, B), (), ens, body)

    def f_closed(self, mod, force_pub=False, twin=False):
        """A function with a functional contract and several equivalent bodies (the twin target when twin=True)."""
        rng = self.rng
        name = self.fresh_fn(mod)
        pub = True if force_pub else self.is_pub(mod)
        kind = rng.choice(["affine", "loop"])
        k, c = rng.randint(1, 4), rng.randint(0, 9)
        if kind == "affine":
            params = [("x",) + self.prange(True)]
            closed = ("add", ("mul", k, ("var",) + params[0]), ("int", c))
            alts = [["  return %s;" % g4_text(closed)],
                    ["  let mut r: i64 = %d;" % c] + ["  r = r + x;"] * k + ["  return r;"],
                    ["  if x >= 0 {", "    return %d + (%d * x);" % (c, k), "  }", "  return (%d * x) + %d;" % (k, c)]]
        else:
            N = rng.choice([10, 100, 1000])
            params = [("n", 0, N)]
            closed = ("add", ("mul", k, ("var",) + params[0]), ("int", c))
            alts = [["  return %s;" % g4_text(closed)],
                    ["  let mut s: i64 = %d;" % c, "  let mut i: i64 = 0;", "  while i < n",
                     "    invariant 0 <= i && i <= n", "    invariant s == (%d * i) + %d" % (k, c),
                     "    decreases n - i", "  {", "    s = s + %d;" % k, "    i = i + 1;", "  }", "  return s;"],
                    ["  let mut r: i64 = n;", "  let mut s: i64 = %d;" % c, "  while r > 0",
                     "    invariant 0 <= r && r <= n", "    invariant s == (%d * (n - r)) + %d" % (k, c),
                     "    decreases r", "  {", "    s = s + %d;" % k, "    r = r - 1;", "  }", "  return s;"]]
            self.feats.add("loop")
        other = 1 + rng.randrange(len(alts) - 1)       # drawn in every variant so both twins consume the same stream
        sel = rng.randrange(len(alts))
        is_twin = twin and self.twin
        pick = (0 if self.variant == 0 else other) if is_twin else sel
        self.int_fn(mod, name, pub, params, closed, g4_range(closed), (), self.contract(closed, g4_range(closed)),
                    alts[pick])
        if is_twin:
            self.twin_func = self.funcs[-1]
            self.feats.add("twin_body_replacement")

    def struct_of(self, mod, pub):
        if mod not in self.struct_decl:
            leaf, fields = self.rng.choice(G4_STRUCTS), self.rng.choice(G4_FIELDS)
            self.struct_decl[mod] = (leaf, fields)
            self.type_names.setdefault(leaf, set()).add(mod)
            self.blocks[mod].append("%sstruct %s { %s: i64, %s: i64 }" % ("pub " if pub else "", leaf, fields[0], fields[1]))
        return self.struct_decl[mod]

    def f_struct_local(self, mod):
        """Builds and reads a (possibly private) struct of the module itself."""
        rng = self.rng
        leaf, (f1, f2) = self.struct_of(mod, False)
        name, pub = self.fresh_fn(mod), self.is_pub(mod)
        ps = self.make_params(2, False)
        k = rng.randint(1, 3)
        ty = self.ref(mod, leaf, mod, rng.random() < 0.3 and mod != ())
        if ty != leaf:
            self.feats.add("qualified_literal")
        body = ["  let st: %s = %s { %s: x, %s: y };" % (ty, ty, f1, f2), "  return (%d * st.%s) + st.%s;" % (k, f1, f2)]
        closed = ("add", ("mul", k, ("var",) + ps[0]), ("var",) + ps[1])
        self.int_fn(mod, name, pub, ps, closed, g4_range(closed), (), self.contract(closed, g4_range(closed)), body)

    def setup_struct_api(self, mod):
        rng = self.rng
        if mod in self.struct_decl:
            return
        leaf, (f1, f2) = self.struct_of(mod, True)
        R = rng.choice([1000, 10000, 100000])
        lo = rng.choice([-R, 0])
        k = rng.randint(1, 4)
        mk, rd = self.fresh_fn(mod), self.fresh_fn(mod)
        self.blocks[mod].append(g4_fn_text(
            mk, True, [("a", "i64"), ("b", "i64")], leaf, (), [g4_req("a", lo, R), g4_req("b", lo, R)],
            ["result.%s == a && result.%s == b" % (f1, f2)], ["  return %s { %s: a, %s: b };" % (leaf, f1, f2)]))
        self.blocks[mod].append(g4_fn_text(
            rd, True, [("s0", leaf)], "i64", (), ["%s <= s0.%s && s0.%s <= %d" % (lit(lo), f1, f1, R),
                                                  "%s <= s0.%s && s0.%s <= %d" % (lit(lo), f2, f2, R)],
            ["result == (%d * s0.%s) + s0.%s" % (k, f1, f2)], ["  return (%d * s0.%s) + s0.%s;" % (k, f1, f2)]))
        self.struct_apis.append({"mod": mod, "leaf": leaf, "f1": f1, "f2": f2, "mk": mk, "rd": rd, "k": k,
                                 "lo": lo, "hi": R})

    def f_struct_cross(self, mod):
        rng = self.rng
        api = rng.choice(self.struct_apis)
        name, pub = self.fresh_fn(mod), self.is_pub(mod)
        ps = self.make_params(2, False)
        avail = [("var",) + p for p in ps]
        a, b = self.pick_arg(avail, api["lo"], api["hi"]), self.pick_arg(avail, api["lo"], api["hi"])
        ty = self.ref(api["mod"], api["leaf"], mod, rng.random() < 0.2)
        if rng.random() < 0.4:
            init = "%s { %s: %s, %s: %s }" % (ty, api["f1"], g4_text(a), api["f2"], g4_text(b))
            self.feats.add("qualified_literal")
        else:
            init = "%s(%s, %s)" % (self.ref(api["mod"], api["mk"], mod), g4_text(a), g4_text(b))
        body = ["  let st: %s = %s;" % (ty, init), "  return %s(st);" % self.ref(api["mod"], api["rd"], mod)]
        closed = ("add", ("mul", api["k"], a), b)
        self.note_call(mod, api["mod"])
        self.feats.add("struct_path")
        self.int_fn(mod, name, pub, ps, closed, g4_range(closed), (), self.contract(closed, g4_range(closed)), body)

    def setup_enum_api(self, mod):
        rng = self.rng
        leaf, lowv, highv = rng.choice(G4_ENUMS)
        if leaf in self.used[mod]:
            return
        self.used[mod].add(leaf)
        self.type_names.setdefault(leaf, set()).add(mod)
        R = rng.choice([1000, 10000])
        lo = rng.choice([-R, 0])
        cls = self.fresh_fn(mod)
        self.blocks[mod].append("pub enum %s { %s, %s(amount: i64) }" % (leaf, lowv, highv))
        self.blocks[mod].append(g4_fn_text(
            cls, True, [("x", "i64")], leaf, (), [g4_req("x", lo, R)],
            ["x > 0 ==> is_variant(result, %s::%s)" % (leaf, highv), "x <= 0 ==> is_variant(result, %s::%s)" % (leaf, lowv)],
            ["  if x > 0 {", "    return %s::%s(x);" % (leaf, highv), "  }", "  return %s::%s;" % (leaf, lowv)]))
        self.enum_apis.append({"mod": mod, "leaf": leaf, "low": lowv, "high": highv, "cls": cls, "lo": lo, "hi": R})

    def f_enum_cross(self, mod):
        rng = self.rng
        api = rng.choice(self.enum_apis)
        name, pub = self.fresh_fn(mod), self.is_pub(mod)
        ps = self.make_params(1, False)
        arg = self.pick_arg([("var",) + ps[0]], api["lo"], api["hi"])
        ty = self.ref(api["mod"], api["leaf"], mod, rng.random() < 0.2)
        k1, k2 = rng.randint(-5, 9), rng.randint(-5, 9)
        body = ["  let m0: %s = %s(%s);" % (ty, self.ref(api["mod"], api["cls"], mod), g4_text(arg)),
                "  match m0 {", "    %s::%s => { return %s; }" % (ty, api["low"], lit(k1)),
                "    %s::%s(v0) => { return %s; }" % (ty, api["high"], lit(k2)), "  }"]
        out = (min(k1, k2), max(k1, k2))
        ens = [g4_range_clause(*out)]
        if rng.random() < 0.5:
            ens += ["%s > 0 ==> result == %s" % (g4_text(arg), lit(k2)), "%s <= 0 ==> result == %s" % (g4_text(arg), lit(k1))]
        self.note_call(mod, api["mod"])
        self.feats.add("enum_path")
        self.int_fn(mod, name, pub, ps, None, out, (), ens, body)

    def setup_generic_api(self, mod):
        if any(n in self.used[mod] for n in G4_GEN_NAMES):
            return
        self.used[mod].update(G4_GEN_NAMES)
        self.type_names.setdefault("Boxed", set()).add(mod)
        g = G3_FRAGS
        self.blocks[mod] += [
            "pub struct Boxed<T> {\n  value: T\n}",
            "pub fn pick<T>(flag: bool, a: T, b: T) -> T\n  ensures flag ==> result == a\n  ensures !flag ==> result == b\n"
            "{\n  if flag {\n    return a;\n  }\n  return b;\n}",
            "pub " + g["id"], "pub " + g["first"], "pub " + g["repeat"],
            "pub fn boxed<T>(x: T) -> Boxed<T>\n  ensures result.value == x\n{\n  return Boxed::<T> { value: x };\n}",
            "pub fn unbox<T>(b: Boxed<T>) -> T\n  ensures result == b.value\n{\n  return b.value;\n}"]
        self.gen_api = mod

    def f_generic_use(self, mod):
        rng = self.rng
        G = self.gen_api
        name, pub = self.fresh_fn(mod), self.is_pub(mod)
        ps = self.make_params(rng.choice([1, 2]), False)
        avail = [("var",) + p for p in ps]
        g = lambda n: self.ref(G, n, mod, rng.random() < 0.2)
        sub = rng.choice(["id", "pick", "boxed", "array", "boolid"])
        fx, closed = (), None
        if sub == "id":
            arg = self.combine(avail, [])
            body = ["  let t0: i64 = %s::<i64>(%s);" % (g("id"), g4_text(arg)), "  return t0;"]
            closed, out = g4_flat(arg), g4_range(arg)
        elif sub == "pick":
            a, b = rng.choice(avail), rng.choice(avail)
            body = ["  let c0: bool = %s <= %s;" % (g4_text(a), g4_text(b)),
                    "  let t0: i64 = %s::<i64>(c0, %s, %s);" % (g("pick"), g4_text(a), g4_text(b)), "  return t0;"]
            (l1, h1), (l2, h2) = g4_range(a), g4_range(b)
            out = (min(l1, l2), max(h1, h2))
        elif sub == "boxed":
            arg = self.combine(avail, [])
            bt = self.ref(G, "Boxed", mod, rng.random() < 0.2)
            body = ["  let bx: %s<i64> = %s::<i64>(%s);" % (bt, g("boxed"), g4_text(arg)),
                    "  return %s::<i64>(bx);" % g("unbox")]
            closed, out = g4_flat(arg), g4_range(arg)
        elif sub == "array":
            arg = self.combine(avail, [])
            body = ["  let ar: [i64] = %s::<i64>(3, %s);" % (g("repeat"), g4_text(arg)),
                    "  return %s::<i64>(ar);" % g("first")]
            closed, out, fx = g4_flat(arg), g4_range(arg), ("alloc",)
            self.feats.add("generic_array")
        else:
            arg = self.combine(avail, [])
            k1, k2 = rng.randint(-5, 9), rng.randint(-5, 9)
            body = ["  let c0: bool = %s > 0;" % g4_text(arg), "  let d0: bool = %s::<bool>(c0);" % g("id"),
                    "  if d0 {", "    return %s;" % lit(k1), "  }", "  return %s;" % lit(k2)]
            out = (min(k1, k2), max(k1, k2))
        ens = self.contract(closed, out)
        if sub == "boolid":
            ens = [g4_range_clause(*out), "%s > 0 ==> result == %s" % (g4_text(arg), lit(k1)),
                   "%s <= 0 ==> result == %s" % (g4_text(arg), lit(k2))]
        self.note_call(mod, G)
        self.feats.add("generic_path")
        self.int_fn(mod, name, pub, ps, closed, out, fx, ens, body)

    def random_func(self, mod):
        rng = self.rng
        opts = [("compose", 5), ("clamp", 2), ("absdiff", 2), ("closed", 3), ("local", 2)]
        if self.struct_apis:
            opts.append(("scross", 3))
        if self.enum_apis:
            opts.append(("ecross", 3))
        if self.gen_api is not None:
            opts.append(("gen", 3))
        kind = rng.choices([o[0] for o in opts], weights=[o[1] for o in opts])[0]
        if kind == "compose":
            self.f_compose(mod, big=len(self.funcs) < 4)
        elif kind == "clamp":
            self.f_clamp(mod)
        elif kind == "absdiff":
            self.f_absdiff(mod)
        elif kind == "closed":
            self.f_closed(mod)
        elif kind == "local":
            self.f_struct_local(mod)
        elif kind == "scross":
            self.f_struct_cross(mod)
        elif kind == "ecross":
            self.f_enum_cross(mod)
        else:
            self.f_generic_use(mod)

    # ---- whole program
    def build(self):
        rng = self.rng
        self.layout(rng.choice([2, 3, 3, 4, 4, 5]))
        nonroot = self.mods[1:]
        if rng.random() < 0.7:
            self.setup_struct_api(rng.choice(nonroot))
        if rng.random() < 0.5:
            self.setup_enum_api(rng.choice(nonroot))
        if rng.random() < 0.5:
            self.setup_generic_api(rng.choice(nonroot))
        if rng.random() < 0.7:
            self.f_compose((), big=True)                 # root helper that child modules may call (child -> root)
        if self.twin or rng.random() < 0.3:
            self.f_closed(rng.choice(nonroot), force_pub=True, twin=True)
        order = list(nonroot)
        rng.shuffle(order)
        for m in order:
            for _ in range(rng.choice([1, 1, 2, 2, 3])):
                self.random_func(m)
        if rng.random() < 0.4:
            self.random_func(())
        force = [self.twin_func] if self.twin_func is not None else []
        cross = [f for f in self.funcs if f["mod"] != () and f["pub"] and f is not self.twin_func]
        if cross:
            force.append(rng.choice(cross))
        self.f_compose((), pub=True, name="f", nparams=rng.choice([1, 2, 3]), big=False, force=force, min_calls=2)
        entry = self.funcs[-1]
        for n, ms in sorted(self.fn_names.items()):
            if len(ms) > 1:
                self.feats.add("repeated_fn_name")
        if any(len(ms) > 1 for ms in self.type_names.values()):
            self.feats.add("repeated_type_name")
        return entry

    def files(self):
        out = {}
        for m in self.mods:
            head = "// g4 fuzz module crate%s\n" % "".join("::" + s for s in m)
            decls = "".join("mod %s;\n" % c[-1] for c in self.kids(m))
            out[("/".join(m) + ".pruv") if m else "root.pruv"] = head + decls + "\n" + "\n\n".join(self.blocks[m]) + "\n"
        return out


def generate_g4_case(seed, index):
    base, variant = divmod(index, 2)
    twin = random.Random("g4:%s:%s:twin" % (seed, base)).random() < 0.3
    rng = random.Random("g4:%s:%s:prog" % (seed, base) if twin else "g4:%s:%s:single" % (seed, index))
    G = G4Gen(rng, variant, twin)
    entry = G.build()
    files = G.files()
    nmods = len(G.mods)
    return {"name": "g4c%s_%s" % (seed, index), "src": files["root.pruv"], "files": files, "entry": "f",
            "params": [[p[0], "i64"] for p in entry["params"]], "ret": "i64", "kind": "g4_m%d" % nmods,
            "input_hints": {"ranges": dict((p[0], (p[1], p[2])) for p in entry["params"])},
            "g4": True, "g4_bad": False, "g4_features": sorted(G.feats | {"modules_%d" % nmods}),
            "g4_twin": ("%s_%s" % (seed, base)) if twin else None, "g4_variant": variant,
            "input_key": ("g4in%s_%s" % (seed, base)) if twin else None}


def g4_pick(rng, lo, hi, outside):
    if outside:
        return rng.choice([hi + rng.randint(1, 3), lo - rng.randint(1, 3)])
    c = [lo, hi, min(hi, lo + 1), max(lo, hi - 1), rng.randint(lo, hi), rng.randint(lo, hi),
         rng.randint(max(lo, -5), max(lo, min(hi, 5)))]
    if lo <= 0 <= hi:
        c.append(0)
    return rng.choice(c)


def g4_candidate_inputs(case, rng, n):
    h = case["input_hints"]["ranges"]
    out = []
    for _ in range(n):
        bad = rng.randrange(len(case["params"])) if rng.random() < 0.15 else -1
        out.append([g4_pick(rng, h[name][0], h[name][1], i == bad) for i, (name, _t) in enumerate(case["params"])])
    return out


# ================================================================ G5 (inout parameters, docs/G5_SPEC.md section 14)
# A case is a program directory (root.pruv + optional module files), like G4. The host entry is an ordinary `pub fn f`
# that copies its array inputs into `let mut` owners, calls inout helpers (every helper has an exact content/frame
# contract over old(..)) and returns an array or a scalar; inout functions are never host-visible. Every program is
# meant to verify. The helper shapes are modelled on examples/g5_*.pruv and tests/runtime/g5_r*.pruv. Calls with an
# inout argument are always whole statements (let / expression statement / return), never nested in an expression.
# Function names are never reused as variable or parameter names (the oracle's module flattening renames by identifier).

G5_T = {
    "i64": {"ty": "[i64]", "pt": "array", "vty": "i64", "pv": "i64", "rt": "[i64]", "rs": "i64"},
    "u8": {"ty": "[u8]", "pt": "array_u8", "vty": "i64", "pv": "i64", "rt": "array_u8", "rs": "i64"},
    "bool": {"ty": "[bool]", "pt": "array_bool", "vty": "bool", "pv": "bool", "rt": "array_bool", "rs": "bool"},
}
G5_LIM = {"i64": 1000, "u8": 255}
G5_FRAME = "forall k in 0..len(a): k != i ==> a[k] == old(a)[k]"


def g5_join(*parts):
    return " && ".join(p for p in parts if p)


def g5_vreq(T, names):
    """u8 values are plain i64 parameters that must stay in the byte range."""
    return ["0 <= %s && %s <= 255" % (n, n) for n in names] if T == "u8" else []


def g5_fn(name, params, ret, requires, ensures, body, pub=False, effects="", decreases=None):
    head = "%sfn %s(%s) -> %s" % ("pub " if pub else "", name, params, ret)
    if effects:
        head += " ! " + effects
    out = [head]
    out += ["  requires " + r for r in requires if r]
    out += ["  ensures " + e for e in ensures]
    if decreases:
        out.append("  decreases " + decreases)
    out.append("{")
    out += [("  " + b) if b else b for b in body]
    out.append("}")
    return "\n".join(out)


def g5_host(params, ret, requires, ensures, body, effects="alloc"):
    return g5_fn("f", params, ret, requires, ensures, body, pub=True, effects=effects)


class G5Prog(object):
    """Module tree of one program: blocks per module path (() is the root), `mod x;` declarations, feature tags."""

    def __init__(self):
        self.blocks = {(): []}
        self.kids = {}
        self.feats = set()

    def add(self, text, mod=()):
        self.blocks.setdefault(mod, []).append(text)
        for n in range(len(mod)):
            lst = self.kids.setdefault(mod[:n], [])
            if mod[n] not in lst:
                lst.append(mod[n])
            self.blocks.setdefault(mod[:n + 1], [])

    def feat(self, *names):
        self.feats.update(names)

    def files(self):
        out = {}
        for m in sorted(self.blocks, key=lambda p: (len(p), p)):
            head = "// g5 fuzz module crate%s\n" % "".join("::" + s for s in m)
            decls = "".join("mod %s;\n" % c for c in self.kids.get(m, []))
            out[("/".join(m) + ".pruv") if m else "root.pruv"] = head + decls + "\n" + "\n\n".join(self.blocks[m]) + "\n"
        return out


# ---- inout helper functions (all take the array as `a` unless noted)

def g5_set_at(name, T, alt, pub=False):
    t = G5_T[T]
    body = ["a[i] = v;"] if alt == 0 else ["let t: %s = v;" % t["vty"], "a[i] = t;"]
    return g5_fn(name, "inout a: %s, i: i64, v: %s" % (t["ty"], t["vty"]), "()",
                 [g5_join("0 <= i && i < len(a)", *g5_vreq(T, ["v"]))],
                 ["len(a) == len(old(a))", "a[i] == v", G5_FRAME], body, pub)


def g5_step_at(name, T, alt):
    """bump (+1, i64/u8 below the limit) or flip (bool) one element."""
    t = G5_T[T]
    if T == "bool":
        req, new = "0 <= i && i < len(a)", "!old(a)[i]"
        body = ["a[i] = !a[i];"] if alt == 0 else ["let x: bool = a[i];", "a[i] = !x;"]
    else:
        req, new = "0 <= i && i < len(a) && a[i] < %d" % G5_LIM[T], "old(a)[i] + 1"
        body = ["a[i] = a[i] + 1;"] if alt == 0 else ["let x: i64 = a[i];", "a[i] = x + 1;"]
    return g5_fn(name, "inout a: %s, i: i64" % t["ty"], "()", [req],
                 ["len(a) == len(old(a))", "a[i] == " + new, G5_FRAME], body)


def g5_put_pair(name, T, set_call, pub=False):
    """Nested reborrow: the inout parameter is forwarded twice to an inout callee."""
    t = G5_T[T]
    return g5_fn(name, "inout a: %s, i: i64, v: %s, u: %s" % (t["ty"], t["vty"], t["vty"]), "()",
                 [g5_join("0 <= i && i + 1 < len(a)", *g5_vreq(T, ["v", "u"]))],
                 ["len(a) == len(old(a))", "a[i] == v", "a[i + 1] == u",
                  "forall k in 0..len(a): k != i && k != i + 1 ==> a[k] == old(a)[k]"],
                 ["%s(inout a, i, v);" % set_call, "%s(inout a, i + 1, u);" % set_call], pub)


def g5_fill_all(name, T, set_call, alt):
    t = G5_T[T]
    step = "%s(inout a, i, v);" % set_call if alt == 0 else "a[i] = v;"
    body = ["let n: i64 = len(a);", "let mut i: i64 = 0;", "while i < n",
            "  invariant 0 <= i && i <= n", "  invariant n == len(old(a))",
            "  invariant forall k in 0..i: a[k] == v",
            "  invariant forall k in i..n: a[k] == old(a)[k]",
            "  decreases n - i", "{", "  " + step, "  i = i + 1;", "}"]
    return g5_fn(name, "inout a: %s, v: %s" % (t["ty"], t["vty"]), "()", [g5_join(*g5_vreq(T, ["v"]))],
                 ["len(a) == len(old(a))", "forall k in 0..len(a): a[k] == v"], body)


def g5_step_all(name, T, step_call, alt):
    t = G5_T[T]
    new = "!old(a)[k]" if T == "bool" else "old(a)[k] + 1"
    inline = "a[i] = !a[i];" if T == "bool" else "a[i] = a[i] + 1;"
    step = "%s(inout a, i);" % step_call if alt == 0 else inline
    req = [] if T == "bool" else ["forall k in 0..len(a): a[k] < %d" % G5_LIM[T]]
    body = ["let n: i64 = len(a);", "let mut i: i64 = 0;", "while i < n",
            "  invariant 0 <= i && i <= n", "  invariant n == len(old(a))",
            "  invariant forall k in 0..i: a[k] == " + new,
            "  invariant forall k in i..n: a[k] == old(a)[k]",
            "  decreases n - i", "{", "  " + step, "  i = i + 1;", "}"]
    return g5_fn(name, "inout a: %s" % t["ty"], "()", req,
                 ["len(a) == len(old(a))", "forall k in 0..len(a): a[k] == " + new], body)


def g5_swap_at(name):
    return g5_fn(name, "inout a: [i64], i: i64, j: i64", "()", ["0 <= i && i < len(a) && 0 <= j && j < len(a)"],
                 ["len(a) == len(old(a))", "a[i] == old(a)[j]", "a[j] == old(a)[i]",
                  "forall k in 0..len(a): k != i && k != j ==> a[k] == old(a)[k]"],
                 ["let x: i64 = a[i];", "let y: i64 = a[j];", "a[i] = y;", "a[j] = x;"])


def g5_reverse(name, swap_call, alt):
    step = (["%s(inout a, i, j);" % swap_call] if alt == 0
            else ["let x: i64 = a[i];", "let y: i64 = a[j];", "a[i] = y;", "a[j] = x;"])
    body = ["let n: i64 = len(a);", "let mut i: i64 = 0;", "let mut j: i64 = n - 1;", "while i < j",
            "  invariant 0 <= i && i <= n", "  invariant j == n - 1 - i", "  invariant len(a) == n",
            "  invariant n == len(old(a))",
            "  invariant forall k in 0..i: a[k] == old(a)[n - 1 - k]",
            "  invariant forall k in 0..n: j < k ==> a[k] == old(a)[n - 1 - k]",
            "  invariant forall k in 0..n: i <= k && k <= j ==> a[k] == old(a)[k]",
            "  decreases j - i", "{"] + ["  " + s for s in step] + ["  i = i + 1;", "  j = j - 1;", "}"]
    return g5_fn(name, "inout a: [i64]", "()", [],
                 ["len(a) == len(old(a))", "forall k in 0..len(a): a[k] == old(a)[len(a) - 1 - k]"], body)


def g5_fill_from(name, T, alt):
    """Recursion (alt 0, one inout reborrow per level) or the equivalent loop (alt 1, same contract)."""
    t = G5_T[T]
    req = [g5_join("0 <= i && i <= len(a)", *g5_vreq(T, ["v"]))]
    ens = ["len(a) == len(old(a))", "forall k in i..len(a): a[k] == v", "forall k in 0..i: a[k] == old(a)[k]"]
    params = "inout a: %s, i: i64, v: %s" % (t["ty"], t["vty"])
    if alt == 0:
        body = ["if i < len(a) {", "  a[i] = v;", "  %s(inout a, i + 1, v);" % name, "}"]
        return g5_fn(name, params, "()", req, ens, body, decreases="len(a) - i")
    body = ["let n: i64 = len(a);", "let mut j: i64 = i;", "while j < n",
            "  invariant 0 <= i && i <= j && j <= n", "  invariant n == len(old(a))",
            "  invariant forall k in 0..i: a[k] == old(a)[k]", "  invariant forall k in i..j: a[k] == v",
            "  invariant forall k in j..n: a[k] == old(a)[k]",
            "  decreases n - j", "{", "  a[j] = v;", "  j = j + 1;", "}"]
    return g5_fn(name, params, "()", req, ens, body)


def g5_exchange(name, alt, pub=False):
    """Generic over the Element bound: used at i64 and bool."""
    body = ["let x: T = buf[i];", "let y: T = buf[j];"]
    body += ["buf[i] = y;", "buf[j] = x;"] if alt == 0 else ["buf[j] = x;", "buf[i] = y;"]
    return g5_fn(name + "<T: Element>", "inout buf: [T], i: i64, j: i64", "()",
                 ["0 <= i && i < len(buf) && 0 <= j && j < len(buf)"],
                 ["len(buf) == len(old(buf))", "buf[i] == old(buf)[j]", "buf[j] == old(buf)[i]",
                  "forall k in 0..len(buf): k != i && k != j ==> buf[k] == old(buf)[k]"], body, pub)


def g5_order_pair(name):
    """An inout function with a bool result (the call is the whole initializer of a let)."""
    return g5_fn(name, "inout a: [i64], i: i64, j: i64", "bool",
                 ["0 <= i && i < len(a) && 0 <= j && j < len(a)"],
                 ["len(a) == len(old(a))", "result ==> old(a)[i] > old(a)[j]", "!result ==> old(a)[i] <= old(a)[j]",
                  "result ==> a[i] == old(a)[j] && a[j] == old(a)[i]",
                  "!result ==> a[i] == old(a)[i] && a[j] == old(a)[j]",
                  "forall k in 0..len(a): k != i && k != j ==> a[k] == old(a)[k]"],
                 ["if a[i] > a[j] {", "  let x: i64 = a[i];", "  let y: i64 = a[j];", "  a[i] = y;", "  a[j] = x;",
                  "  return true;", "}", "return false;"])


def g5_fill_pair(name):
    """Two inout parameters in one call (relational postcondition over both owners)."""
    return g5_fn(name, "inout lo: [i64], inout hi: [i64], v: i64", "()",
                 ["len(lo) >= 2 && len(hi) >= 2 && -1000 < v && v < 1000"],
                 ["len(lo) == len(old(lo))", "len(hi) == len(old(hi))", "lo[0] == v", "lo[1] == v + 1",
                  "hi[0] == v + 2", "hi[1] == v + 3"],
                 ["lo[0] = v;", "hi[0] = lo[0] + 2;", "lo[1] = lo[0] + 1;", "hi[1] = hi[0] + 1;"])


def g5_blit(name):
    """inout destination + read-only source (another owner), prefix copy."""
    return g5_fn(name, "inout dst: [i64], src: [i64], n: i64", "()",
                 ["0 <= n && n <= len(dst) && n <= len(src)"],
                 ["len(dst) == len(old(dst))", "forall k in 0..n: dst[k] == src[k]",
                  "forall k in n..len(dst): dst[k] == old(dst)[k]"],
                 ["let mut i: i64 = 0;", "while i < n",
                  "  invariant 0 <= i && i <= n",
                  "  invariant forall k in 0..i: dst[k] == src[k]",
                  "  invariant forall k in i..len(dst): dst[k] == old(dst)[k]",
                  "  decreases n - i", "{", "  dst[i] = src[i];", "  i = i + 1;", "}"])


def g5_dump(name):
    return g5_fn(name, "a: [i64]", "()", [], [],
                 ["let n: i64 = len(a);", "let mut i: i64 = 0;", "while i < n",
                  "  invariant 0 <= i && i <= n", "  decreases n - i", "{", "  print(a[i]);", "  i = i + 1;", "}"],
                 effects="io")


# ---- input hints: arrays {kind, minlen, elem (lo, hi), bad}, ints {name: (lo, hi)}, idx {name: (array, off)} (valid
# 0..len(array)-off), cnt {name: (array, array)} (valid 0..min of the lengths), samelen [(array, array)]

def g5_ah(T, minlen=0, lo=None, hi=None, bad=None):
    d = {"kind": T, "minlen": minlen}
    if T == "i64":
        d["elem"] = (-50 if lo is None else lo, 50 if hi is None else hi)
    elif T == "u8":
        d["elem"] = (0 if lo is None else lo, 255 if hi is None else hi)
    if bad is not None:
        d["bad"] = bad
    return d


def g5_vh(T):
    return {"i64": (-1000, 1000), "u8": (0, 255)}.get(T, (0, 1))


def g5_hints(arrays=None, ints=None, idx=None, cnt=None, samelen=None):
    return {"arrays": arrays or {}, "ints": ints or {}, "idx": idx or {}, "cnt": cnt or {}, "samelen": samelen or []}


# ---- scenarios: (P, rng, arg, alt) -> {"params", "ret", "hints"}; helpers and the host entry are added to P

def g5_sc_pairs(P, rng, T, alt):
    t = G5_T[T]
    extra = rng.randrange(3)
    P.add(g5_set_at("put_at", T, alt))
    P.add(g5_put_pair("put_pair", T, "put_at"))
    body = ["let mut w: %s = copy(a);" % t["ty"], "put_pair(inout w, i, v, u);", "put_at(inout w, i, u);"]
    if extra >= 1:
        body.append("put_at(inout w, i + 1, v);")
    if extra == 2:
        body.append("put_pair(inout w, i, u, v);")
    body.append("return w;")
    P.add(g5_host("a: %s, i: i64, v: %s, u: %s" % (t["ty"], t["vty"], t["vty"]), t["ty"],
                  [g5_join("0 <= i && i + 1 < len(a)", *g5_vreq(T, ["v", "u"]))],
                  ["len(result) == len(a)"], body))
    P.feat("type_" + T, "repeated_reborrow", "nested_reborrow", "array_return", "frame_forall")
    return {"params": [["a", t["pt"]], ["i", "i64"], ["v", t["pv"]], ["u", t["pv"]]], "ret": t["rt"],
            "hints": g5_hints({"a": g5_ah(T, 2)}, {"v": g5_vh(T), "u": g5_vh(T)}, {"i": ("a", 2)})}


def g5_sc_swapgen(P, rng, in_mod, alt):
    pre = "crate::swaps::" if in_mod else ""
    P.add(g5_exchange("exchange", alt, pub=in_mod), ("swaps",) if in_mod else ())
    body = ["let mut w: [i64] = copy(a);", "let mut g: [bool] = copy(fl);",
            "%sexchange::<i64>(inout w, i, j);" % pre,
            "%sexchange::<bool>(inout g, i, j);" % pre,
            "if g[i] {", "  %sexchange::<i64>(inout w, i, j);" % pre, "}", "return w;"]
    P.add(g5_host("a: [i64], fl: [bool], i: i64, j: i64", "[i64]",
                  ["0 <= i && i < len(a) && 0 <= j && j < len(a) && len(fl) == len(a)"],
                  ["len(result) == len(a)"], body))
    P.feat("type_i64", "type_bool", "generic_instance", "repeated_reborrow", "multi_owner", "array_return",
           "frame_forall")
    if in_mod:
        P.feat("module_call")
    return {"params": [["a", "array"], ["fl", "array_bool"], ["i", "i64"], ["j", "i64"]], "ret": "[i64]",
            "hints": g5_hints({"a": g5_ah("i64", 1), "fl": g5_ah("bool", 0)}, None, {"i": ("a", 1), "j": ("a", 1)},
                              None, [("a", "fl")])}


def g5_sc_loopfill(P, rng, T, alt):
    t = G5_T[T]
    scalar = rng.random() < 0.35
    P.add(g5_set_at("put_at", T, 0))
    P.add(g5_fill_all("fill_all", T, "put_at", alt))
    body = ["let mut w: %s = copy(a);" % t["ty"], "fill_all(inout w, v);", "put_at(inout w, i, u);",
            "return w[i];" if scalar else "return w;"]
    P.add(g5_host("a: %s, i: i64, v: %s, u: %s" % (t["ty"], t["vty"], t["vty"]), t["rs"] if scalar else t["ty"],
                  [g5_join("0 <= i && i < len(a)", *g5_vreq(T, ["v", "u"]))],
                  [] if scalar else ["len(result) == len(a)"], body))
    P.feat("type_" + T, "loop", "nested_reborrow", "repeated_reborrow", "frame_forall",
           "scalar_return" if scalar else "array_return")
    return {"params": [["a", t["pt"]], ["i", "i64"], ["v", t["pv"]], ["u", t["pv"]]],
            "ret": t["rs"] if scalar else t["rt"],
            "hints": g5_hints({"a": g5_ah(T, 1)}, {"v": g5_vh(T), "u": g5_vh(T)}, {"i": ("a", 1)})}


def g5_sc_loopbump(P, rng, T, alt):
    t = G5_T[T]
    scalar = rng.random() < 0.35
    twice = rng.random() < 0.5
    P.add(g5_step_at("step_at", T, 0))
    P.add(g5_step_all("step_all", T, "step_at", alt))
    body = ["let mut w: %s = copy(a);" % t["ty"], "step_all(inout w);"]
    if T == "bool" and twice:
        body.append("step_all(inout w);")          # flipping twice restores the input (no requires on bool)
    body.append("return w[0];" if scalar else "return w;")
    req = ["len(a) >= 1"] if scalar else []
    if T != "bool":
        req.append("forall k in 0..len(a): a[k] < %d" % G5_LIM[T])
    P.add(g5_host("a: %s" % t["ty"], t["rs"] if scalar else t["ty"], req,
                  [] if scalar else ["len(result) == len(a)"], body))
    P.feat("type_" + T, "loop", "nested_reborrow", "frame_forall", "scalar_return" if scalar else "array_return")
    if T == "bool" and twice:
        P.feat("repeated_reborrow")
    if T == "i64":
        ah = g5_ah(T, 1 if scalar else 0, -100, 999, 1000)
    elif T == "u8":
        ah = g5_ah(T, 1 if scalar else 0, 0, 254, 255)
    else:
        ah = g5_ah(T, 1 if scalar else 0)
    return {"params": [["a", t["pt"]]], "ret": t["rs"] if scalar else t["rt"], "hints": g5_hints({"a": ah})}


def g5_sc_reverse(P, rng, T, alt):
    twice = rng.random() < 0.5
    P.add(g5_swap_at("swap_at"))
    P.add(g5_reverse("reverse", "swap_at", alt))
    body = ["let mut w: [i64] = copy(a);", "reverse(inout w);"]
    if twice:
        body.append("reverse(inout w);")
    body.append("return w;")
    P.add(g5_host("a: [i64]", "[i64]", [], ["len(result) == len(a)"], body))
    P.feat("type_i64", "loop", "nested_reborrow", "array_return", "frame_forall",
           "repeated_reborrow" if twice else "single_call")
    return {"params": [["a", "array"]], "ret": "[i64]", "hints": g5_hints({"a": g5_ah("i64", 0)})}


def g5_sc_recur(P, rng, T, alt):
    t = G5_T[T]
    scalar = rng.random() < 0.35
    P.add(g5_fill_from("fill_from", T, alt))
    body = ["let mut w: %s = copy(a);" % t["ty"], "fill_from(inout w, i, v);", "return w[i];" if scalar else "return w;"]
    P.add(g5_host("a: %s, i: i64, v: %s" % (t["ty"], t["vty"]), t["rs"] if scalar else t["ty"],
                  [g5_join("0 <= i && i < len(a)" if scalar else "0 <= i && i <= len(a)", *g5_vreq(T, ["v"]))],
                  [] if scalar else ["len(result) == len(a)"], body))
    P.feat("type_" + T, "recursion" if alt == 0 else "loop", "frame_forall",
           "scalar_return" if scalar else "array_return")
    return {"params": [["a", t["pt"]], ["i", "i64"], ["v", t["pv"]]], "ret": t["rs"] if scalar else t["rt"],
            "hints": g5_hints({"a": g5_ah(T, 1 if scalar else 0)}, {"v": g5_vh(T)},
                              {"i": ("a", 1 if scalar else 0)})}


def g5_sc_multi(P, rng, T, alt):
    P.add(g5_fill_pair("fill_pair"))
    P.add(g5_blit("blit"))
    P.add(g5_dump("dump"))
    body = ["let mut x: [i64] = copy(a);", "let mut y: [i64] = copy(b);", "fill_pair(inout x, inout y, v);",
            "fill_pair(inout y, inout x, v + 10);", "blit(inout x, y, n);", "dump(y);", "return x;"]
    P.add(g5_host("a: [i64], b: [i64], v: i64, n: i64", "[i64]",
                  ["len(a) >= 2 && len(b) >= 2 && -1000 < v && v < 900 && 0 <= n && n <= len(a) && n <= len(b)"],
                  ["len(result) == len(a)"], body, effects="io, alloc"))
    P.feat("type_i64", "multi_owner", "two_inout_args", "swapped_roles", "readonly_other_owner", "loop",
           "print_output", "array_return", "frame_forall")
    return {"params": [["a", "array"], ["b", "array"], ["v", "i64"], ["n", "i64"]], "ret": "[i64]",
            "hints": g5_hints({"a": g5_ah("i64", 2), "b": g5_ah("i64", 2)}, {"v": (-999, 899)}, None,
                              {"n": ("a", "b")})}


def g5_sc_cond(P, rng, T, alt):
    P.add(g5_order_pair("order_pair"))
    body = ["let mut w: [i64] = copy(a);", "let c: bool = order_pair(inout w, i, j);", "if c {", "  return w[i];", "}",
            "return w[j];"]
    P.add(g5_host("a: [i64], i: i64, j: i64", "i64", ["0 <= i && i < len(a) && 0 <= j && j < len(a)"], [], body))
    P.feat("type_i64", "bool_result_call", "scalar_return", "frame_forall")
    return {"params": [["a", "array"], ["i", "i64"], ["j", "i64"]], "ret": "i64",
            "hints": g5_hints({"a": g5_ah("i64", 1)}, None, {"i": ("a", 1), "j": ("a", 1)})}


def g5_sc_modules(P, rng, T, alt, nested=False):
    t = G5_T[T]
    if nested:
        P.add(g5_set_at("put_at", T, alt, pub=True), ("ops", "deep"))
        P.add(g5_put_pair("put_pair", T, "crate::ops::deep::put_at", pub=True), ("ops",))
        extra = "crate::ops::deep::put_at(inout w, i + 1, v);"
    else:
        P.add(g5_set_at("put_at", T, alt, pub=True), ("ops",))
        P.add(g5_put_pair("put_pair", T, "put_at", pub=True), ("ops",))
        extra = "crate::ops::put_at(inout w, i, u);"
    body = ["let mut w: %s = copy(a);" % t["ty"], "crate::ops::put_pair(inout w, i, v, u);", extra, "return w;"]
    P.add(g5_host("a: %s, i: i64, v: %s, u: %s" % (t["ty"], t["vty"], t["vty"]), t["ty"],
                  [g5_join("0 <= i && i + 1 < len(a)", *g5_vreq(T, ["v", "u"]))],
                  ["len(result) == len(a)"], body))
    P.feat("type_" + T, "module_call", "nested_reborrow", "repeated_reborrow", "array_return", "frame_forall")
    if nested:
        P.feat("nested_module")
    return {"params": [["a", t["pt"]], ["i", "i64"], ["v", t["pv"]], ["u", t["pv"]]], "ret": t["rt"],
            "hints": g5_hints({"a": g5_ah(T, 2)}, {"v": g5_vh(T), "u": g5_vh(T)}, {"i": ("a", 2)})}


G5_SCENARIOS = {
    "pairs": g5_sc_pairs, "swapgen": g5_sc_swapgen, "loopfill": g5_sc_loopfill, "loopbump": g5_sc_loopbump,
    "reverse": g5_sc_reverse, "recur": g5_sc_recur, "multi": g5_sc_multi, "cond": g5_sc_cond,
    "modules": lambda P, rng, T, alt: g5_sc_modules(P, rng, T, alt, False),
    "modules_nested": lambda P, rng, T, alt: g5_sc_modules(P, rng, T, alt, True),
}
# (scenario, element type / in-module flag): one full rotation covers every concrete element type, generic instances in the
# root and in a module, loops, recursion, nested and repeated reborrows, two owners, a bool-result call and module calls
G5_COMBOS = [("pairs", "i64"), ("pairs", "u8"), ("pairs", "bool"), ("swapgen", False), ("swapgen", True),
             ("loopfill", "i64"), ("loopfill", "u8"), ("loopfill", "bool"),
             ("loopbump", "i64"), ("loopbump", "u8"), ("loopbump", "bool"),
             ("reverse", "i64"), ("recur", "i64"), ("recur", "u8"), ("recur", "bool"),
             ("multi", "i64"), ("cond", "i64"),
             ("modules", "i64"), ("modules", "u8"), ("modules", "bool"),
             ("modules_nested", "i64"), ("modules_nested", "u8")]
# scenarios with a contract-preserving alternative body (the `alt` argument): twin pairs are drawn from these
G5_ALT_KINDS = ("pairs", "swapgen", "loopfill", "loopbump", "reverse", "recur", "modules", "modules_nested")
G5_ALT_COMBOS = [c for c in G5_COMBOS if c[0] in G5_ALT_KINDS]


def generate_g5_case(seed, index):
    """Program numbers 2k and 2k+1 are a twin pair for about 30% of k: same program except that one callee body is
    replaced by another with the same contract (variant 0 / 1); they get the same inputs (`input_key`)."""
    base, variant = divmod(index, 2)
    twin = random.Random("g5:%s:%s:twin" % (seed, base)).random() < 0.3
    rng = random.Random("g5:%s:%s:prog" % (seed, base) if twin else "g5:%s:%s:single" % (seed, index))
    if twin:
        kind, arg = G5_ALT_COMBOS[(base + seed) % len(G5_ALT_COMBOS)]
    else:
        kind, arg = G5_COMBOS[(index + seed) % len(G5_COMBOS)]
    alt = variant if twin else rng.randrange(2)
    P = G5Prog()
    sc = G5_SCENARIOS[kind](P, rng, arg, alt)
    files = P.files()
    P.feat("old_contract", "files_%d" % len(files))
    if twin:
        P.feat("body_replacement_twin")
    elif kind in G5_ALT_KINDS and alt:
        P.feat("alternative_body")
    return {"name": "g5c%s_%s" % (seed, index), "src": files["root.pruv"], "files": files, "entry": "f",
            "params": sc["params"], "ret": sc["ret"], "kind": "g5_%s_%s" % (kind, arg), "input_hints": sc["hints"],
            "g5": True, "g5_features": sorted(P.feats),
            "g5_has_invariant": any("invariant " in t for t in files.values()),
            "g5_twin": ("%s_%s" % (seed, base)) if twin else None, "g5_variant": variant,
            "input_key": ("g5in%s_%s" % (seed, base)) if twin else None}


def g5_strip_invariants(files):
    """The same program without its loop invariants (for the --infer probe: `decreases` and the contracts stay)."""
    out = {}
    for rel, text in files.items():
        out[rel] = "\n".join(l for l in text.split("\n") if not l.strip().startswith("invariant "))
    return out


def g5_array(rng, h, bad):
    kind, minlen = h["kind"], h.get("minlen", 0)
    if bad and minlen > 0:
        n = minlen - 1
    else:
        n = min(8, rng.choice([minlen, minlen + 1, rng.randint(minlen, 8), rng.randint(minlen, 8), 8]))
    if kind == "bool":
        out = [rng.random() < 0.5 for _ in range(n)]
    else:
        lo, hi = h["elem"]
        out = [pick_in_range(rng, lo, hi) for _ in range(n)]
    if out and h.get("bad") is not None and (bad or rng.random() < 0.06):
        out[rng.randrange(len(out))] = h["bad"]
    return out


def g5_fit(rng, arr, n, h):
    arr = list(arr)[:n]
    while len(arr) < n:
        arr.append((rng.random() < 0.5) if h["kind"] == "bool" else pick_in_range(rng, *h["elem"]))
    return arr


def g5_candidate_inputs(case, rng, n):
    h = case["input_hints"]
    names = [p[0] for p in case["params"]]
    out = []
    for _ in range(n):
        bad = rng.randrange(len(names)) if rng.random() < 0.2 else -1
        vals = {}
        for j, (name, pt) in enumerate(case["params"]):
            if name in h["arrays"]:
                vals[name] = g5_array(rng, h["arrays"][name], j == bad)
        for x, y in h["samelen"]:
            if rng.random() < 0.85:
                vals[y] = g5_fit(rng, vals[y], len(vals[x]), h["arrays"][y])
        for j, (name, pt) in enumerate(case["params"]):
            if name in vals:
                continue
            if name in h["idx"]:
                arr, off = h["idx"][name]
                hi = len(vals[arr]) - off
                if j != bad and hi >= 0:
                    vals[name] = rng.choice([0, hi, rng.randint(0, hi), rng.randint(0, hi)])
                else:
                    vals[name] = rng.choice([-1, hi + 1, hi + 2, len(vals[arr]) + 1])
            elif name in h["cnt"]:
                x, y = h["cnt"][name]
                hi = min(len(vals[x]), len(vals[y]))
                if j != bad:
                    vals[name] = rng.choice([0, hi, rng.randint(0, hi), rng.randint(0, hi)])
                else:
                    vals[name] = rng.choice([-1, hi + 1, hi + 2])
            elif pt == "bool":
                vals[name] = rng.choice([True, False])
            else:
                lo, hi = h["ints"][name]
                vals[name] = g4_pick(rng, lo, hi, j == bad)
        out.append([vals[nm] for nm in names])
    return out


# ---------------------------------------------------------------- case assembly

def render(ctx, body):
    tymap = {"array": "[i64]", "bool": "bool", "Option<i64>": "Option<i64>", "Result<i64>": "Result<i64>",
             "array_u8": "[u8]", "array_bool": "[bool]", "str": "str"}
    sig = ", ".join("%s: %s" % (n, tymap.get(t, "i64" if t == "i64" else t)) for n, t in ctx.params)   # structs/enums keep their type name as is
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


def generate_g7_case(seed, index):
    """Scoped groups with exact frames and complete post-join array observations."""
    rng = random.Random("g7:%s:%s" % (seed, index))
    kind = (seed + index) % 6
    T = ("i64", "u8", "bool")[(seed + index // 6) % 3] if kind != 5 else "i64"
    t = G5_T[T]
    ty, vt = t["ty"], t["vty"]
    req = [g5_join("0 <= i && i < len(a)", *g5_vreq(T, ["v"]))]
    ens = ["a[i] == v", G5_FRAME]
    helpers = [g5_set_at("put", T, rng.randrange(2))]
    helpers.append(g5_fn("forward", "inout a: %s, i: i64, v: %s" % (ty, vt), "()",
                         req, ens, ["put(inout a, i, v);"]))
    helpers.append(g5_fn("pair", "inout a: %s, inout b: %s, i: i64, v: %s" % (ty, ty, vt), "()",
                         req + ["i < len(b)"], ens + ["b[i] == v",
                         "forall k in 0..len(b): k != i ==> b[k] == old(b)[k]"],
                         ["forward(inout a, i, v);", "put(inout b, i, v);"]))
    helpers.append(g5_fn("read", "inout a: %s, src: %s, i: i64" % (ty, ty), "()",
                         ["0 <= i && i < len(a) && i < len(src)"],
                         ["a[i] == src[i]", G5_FRAME], ["a[i] = src[i];"]))
    helpers.append(g5_fn("generic<T: Element>", "inout a: [T], i: i64, v: T", "()",
                         ["0 <= i && i < len(a)"], ens, ["a[i] = v;"]))
    body = ["let mut %s: %s = copy(src);" % (n, ty) for n in ("a", "b", "c")]
    calls = ["forward(inout a, i, v);", "put(inout b, i, v);"]
    features = ["type_" + T, "exact_frames", "nested_helpers"]
    if kind == 1:
        calls.append("put(inout c, i, v);")
    elif kind == 2:
        calls = ["pair(inout a, inout b, i, v);", "put(inout c, i, v);"]
        features.append("multi_array_branch")
    elif kind == 3:
        calls = ["read(inout a, src, i);", "read(inout b, src, i);"]
        features.append("shared_immutable_reads")
    elif kind == 5:
        body.append("let mut bits: [bool] = alloc(len(src), false);")
        calls = ["generic::<i64>(inout a, i, v);", "generic::<bool>(inout bits, i, true);"]
        features += ["generic_two_specializations", "type_bool"]
    features.append("three_branches" if len(calls) == 3 else "two_branches")
    group = "par { " + " ".join(calls) + " }"
    if kind == 4:
        body += ["let mut round: i64 = 0;", "while round < rounds",
                 " invariant 0 <= round && round <= rounds", " decreases rounds - round",
                 "{", group, "round = round + 1;", "}"]
        features.append("loop_groups")
    else:
        body.append(group)
    for n in ["a", "b", "c", "src"] + (["bits"] if kind == 5 else []):
        body += ["print(len(%s));" % n, "let mut j_%s: i64 = 0;" % n,
                 "while j_%s < len(%s)" % (n, n),
                 " invariant 0 <= j_%s && j_%s <= len(%s)" % (n, n, n),
                 " decreases len(%s) - j_%s" % (n, n), "{", "print(%s[j_%s]);" % (n, n),
                 "j_%s = j_%s + 1;" % (n, n), "}"]
    body.append("return 0;")
    helpers.append(g5_host("src: %s, i: i64, v: %s, rounds: i64" % (ty, vt), "i64",
                          [g5_join("0 <= i && i < len(src)", "0 <= rounds && rounds <= 4",
                                   *g5_vreq(T, ["v"]))], [], body, effects="alloc, io"))
    src = "// g7 fuzz case\n" + "\n".join(helpers)
    return {"name": "g7c%s_%s" % (seed, index), "src": src, "files": {"root.pruv": src},
            "entry": "f", "params": [["src", t["pt"]], ["i", "i64"], ["v", t["pv"]], ["rounds", "i64"]],
            "ret": "i64", "kind": "g7_%d_%s" % (kind, T), "g7": True,
            "g7_features": sorted(set(features)), "input_hints": g5_hints(
                {"src": g5_ah(T, 1)}, {"v": g5_vh(T), "rounds": (1, 4)}, {"i": ("src", 1)})}


S5_FAMILIES = ("loop", "nested", "loop_call", "recursion", "generic",
               "alloc_copy", "par", "slack", "conditional")


def generate_s5_case(seed, index):
    """Finite, verified-intended candidates. Twins change only f's bound by one."""
    rng = random.Random("s5:%s:%s" % (seed, index))
    kind = S5_FAMILIES[index % len(S5_FAMILIES)]
    k = rng.randint(1, 5)
    helpers, effects = "", "io"
    loop = ("let mut i: i64 = 0; while i < n "
            "invariant 0 <= i && i <= n invariant spent == UNIT * i "
            "decreases n - i { BODY i = i + 1; } ")
    if kind in ("loop", "slack"):
        bound = "n" if kind == "loop" else "n + %d" % k
        body = loop.replace("UNIT", "1").replace("BODY", "") + "print(i); return i;"
    elif kind == "nested":
        bound = "n * (m + 1)"
        inner = ("let mut j: i64 = 0; while j < m "
                 "invariant 0 <= j && j <= m "
                 "invariant spent == i * (m + 1) + 1 + j "
                 "decreases m - j { j = j + 1; }")
        body = loop.replace("UNIT", "(m + 1)").replace("BODY", inner) + "print(i); return i;"
    elif kind == "loop_call":
        helpers = "fn tick() -> () cost %d {}\n" % k
        bound = "%d * n" % (k + 2)
        body = loop.replace("UNIT", str(k + 2)).replace("BODY", "tick();") + "print(i); return i;"
    elif kind == "recursion":
        helpers = ("fn down(n: i64) -> i64 requires n >= 0 decreases n cost n "
                   "{ if n == 0 { return 0; } else { return down(n - 1); } }\n")
        bound = "n + 1"
        body = "let r: i64 = down(n); print(r); return r;"
    elif kind == "generic":
        helpers = "fn identity<T>(x: T) -> T cost %d { return x; }\n" % k
        bound = str(2 * (k + 1))
        body = ("let b: bool = identity::<bool>(true); let r: i64 = identity::<i64>(n); "
                "print(b); print(r); return r;")
    elif kind == "alloc_copy":
        effects = "io, alloc"
        bound = "2 * (n + 1)"
        body = ("let a: [i64] = alloc(n, %d); let b: [i64] = copy(a); "
                "print(len(b)); return len(b);") % k
    elif kind == "par":
        helpers = "fn tick() -> () cost %d {}\n" % k
        count = rng.randint(2, 4)
        bound = str(count * (k + 1))
        body = "par { " + "tick(); " * count + "} print(n); return n;"
    else:
        helpers = "fn leaf() -> i64 cost %d { return %d; }\n" % (k, k)
        bound = str(k + 1)
        body = ("if n > 0 { let r: i64 = leaf(); print(r); return r; } "
                "else { print(n); return n; }")
    header = ("fn f(n: i64, m: i64) -> i64 ! %s "
              "requires 0 <= n && n <= 12 requires 0 <= m && m <= 8 cost ") % effects
    src = "// s5 fuzz case\n" + helpers + header + bound + " { " + body + " }\n"
    twin = None if kind == "slack" else src.replace(header + bound, header + "(" + bound + ") - 1", 1)
    return {"name": "s5c%s_%s" % (seed, index), "src": src,
            "params": [["n", "i64"], ["m", "i64"]], "ret": "i64",
            "kind": kind, "s5": True, "s5_twin": False, "twin_src": twin}


def s5_inputs(seed, index, count):
    rng = random.Random("s5-inputs:%s:%s" % (seed, index))
    values = [[0, 0], [1, 0], [0, 8], [12, 8], [12, 0], [1, 1], [2, 3], [3, 2]]
    while len(values) < count:
        value = [rng.randrange(13), rng.randrange(9)]
        if value not in values or len(values) >= 117:
            values.append(value)
    # Keep boundary witnesses first; vary the interior inputs with each seed.
    if count >= 8:
        values[6:8] = [[rng.randint(2, 11), rng.randint(1, 7)] for _ in range(2)]
    return values[:count]


def generate_case(seed, index, g2=False, g3=False, g6=False, g9=False, g4=False, g5=False, g7=False, s5=False):
    if s5:
        return generate_s5_case(seed, index)
    if g7:
        return generate_g7_case(seed, index)
    if g5:
        return generate_g5_case(seed, index)
    if g4:
        return generate_g4_case(seed, index)
    if g9:
        return generate_g9_case(seed, index)
    if g6:
        return generate_g6_case(seed, index)
    if g3:
        return generate_g3_case(seed, index)
    if g2:
        return generate_g2_case(seed, index)
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
            case["types"] = ti       # only when f has a struct/enum in its arguments or return
        return case
    r = (r - FAMILY_SHARE) / (1.0 - FAMILY_SHARE)   # the existing ingredients share the remaining portion in their existing proportions
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


# ---------------------------------------------------------------- input generation

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
        if len(out) >= 2 and m < 0.2:        # one adjacent swap
            j = rng.randrange(len(out) - 1)
            out[j], out[j + 1] = out[j + 1], out[j]
        elif len(out) >= 2 and m < 0.4:      # same neighbor
            j = rng.randrange(len(out) - 1)
            out[j + 1] = out[j]
    return out


WIDE = [I64_MAX, I64_MIN, I64_MAX - 1, I64_MIN + 1, 1 << 62, -(1 << 62), 3037000499, 3037000500,
        -3037000499, 1 << 32, -(1 << 32), 1 << 40, -(1 << 40), 1 << 43, 1 << 26, -(1 << 26),
        7, -7, 0, 1, -1]


def bias_inputs(rng, h, vals):
    """Input bias for the undef/division/boundary ingredients (modifies vals in place)."""
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
    # exact_val: give struct/enum/Option/Result parameters values exactly equal to or different from the contract comparison
    for x, lst in h.get("exact_val", {}).items():
        if x in vals and lst and rng.random() < 0.3:
            vals[x] = copy.deepcopy(rng.choice(lst))


def gen_opt(rng, h, consts):
    """Option<i64> argument: {"tag": "Some", "v": n} or {"tag": "None"}."""
    if rng.random() < 0.4:
        return {"tag": "None"}
    return {"tag": "Some", "v": pick_int(rng, h, consts)}


def gen_res(rng, h, eh, consts):
    """Result<i64> argument: {"tag": "Ok", "v": n} or {"tag": "Err", "v": code}. eh: error code hint."""
    if rng.random() < 0.55:
        return {"tag": "Ok", "v": pick_int(rng, h, consts)}
    if rng.random() < 0.5:
        return {"tag": "Err", "v": rng.choice([-2, -1, 0, 1, 2, 3])}
    return {"tag": "Err", "v": pick_int(rng, eh, consts)}


def gen_value(rng, ty, types, h, consts, eh=None, strict=False):
    """Recursively generate an input value for the type string ty using case["types"].
    Struct {"struct": name, "fields": {...}}, enum {"enum": name, "variant": variant, "fields": {...}} (fields in declaration order).
    h: i64 hints (lo/hi/cap). If strict, only values within the hint range are picked (increasing inputs that satisfy the contract)."""
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
        var = rng.choice(list(enums[ty].keys()))      # pick variants uniformly
        return {"enum": ty, "variant": var,
                "fields": {fn: gen_value(rng, ft, types, h, consts, eh, strict) for fn, ft in enums[ty][var]}}
    if strict and h.get("lo") is not None and h.get("hi") is not None:
        return pick_in_range(rng, h["lo"], h["hi"])
    return pick_int(rng, h, consts)


def fit_len(rng, arr, n, h, consts):
    """Truncate or extend array arr to length n (boundary test for two arrays having equal length)."""
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
    if case.get("g7"):
        vals = g5_candidate_inputs(case, rng, n)
        for a in vals:
            if not a[0]:
                a[0] = [False if case["params"][0][1] == "array_bool" else 0]
            a[1] %= len(a[0])
            if case["params"][2][1] != "bool":
                lo, hi = case["input_hints"]["ints"]["v"]
                a[2] = max(lo, min(hi, a[2]))
            a[3] = max(1, min(4, a[3]))
        return vals
    if case.get("g5"):
        return g5_candidate_inputs(case, rng, n)
    if case.get("g4"):
        return g4_candidate_inputs(case, rng, n)
    if case.get("g9"):
        return g9_candidate_inputs(case, rng, n)
    if case.get("g6"):
        return g6_candidate_inputs(case, rng, n)
    if case.get("g3"):
        return g3_candidate_inputs(case, rng, n)
    if case.get("g2"):
        return g2_candidate_inputs(case, rng, n)
    h = case["input_hints"]
    consts = h.get("consts", [])
    out = []
    types = case.get("types") or {}
    named = set(types.get("structs", {})) | set(types.get("enums", {}))
    for _ in range(n):
        vals = {}
        strict = rng.random() < 0.75      # whether to keep a whole struct/enum value within the hint range
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
    ap = argparse.ArgumentParser(description="Pruv fuzzing program generator (writes .pruv files)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--out", default="bench/fuzz/out/generated")
    ap.add_argument("--g2", action="store_true", help="G2 mode: generate [u8], [bool], and str programs")
    ap.add_argument("--g3", action="store_true", help="G3 mode: generate generic programs (some deliberately unproved)")
    ap.add_argument("--g6", action="store_true",
                    help="G6 mode: trusted Rust calls and Vec/HashMap/String programs (some deliberately unproved)")
    ap.add_argument("--g9", action="store_true",
                    help="G9 mode: recursion, recursive types and buffer fields (some deliberately unproved)")
    ap.add_argument("--g4", action="store_true",
                    help="G4 mode: multi-module programs, one directory per program (root.pruv + module files)")
    ap.add_argument("--g5", action="store_true",
                    help="G5 mode: inout-parameter programs, one directory per program (root.pruv + module files)")
    ap.add_argument("--g7", action="store_true", help="G7 scoped parallel calls")
    ap.add_argument("--s5", action="store_true", help="Stage 5 cost bounds and minus-one twins")
    a = ap.parse_args(argv)
    if a.s5 and any((a.g2, a.g3, a.g4, a.g5, a.g6, a.g7, a.g9)):
        ap.error("--s5 is a separate mode")
    if a.g7 and any((a.g2, a.g3, a.g4, a.g5, a.g6, a.g9)):
        ap.error("--g7 is a separate mode")
    if a.g9 and (a.g2 or a.g3 or a.g6):
        ap.error("--g9 is a separate mode (not combinable with --g2/--g3/--g6)")
    if a.g4 and (a.g2 or a.g3 or a.g6 or a.g9):
        ap.error("--g4 is a separate mode (not combinable with --g2/--g3/--g6/--g9)")
    if a.g5 and (a.g2 or a.g3 or a.g6 or a.g9 or a.g4):
        ap.error("--g5 is a separate mode (not combinable with --g2/--g3/--g6/--g9/--g4)")
    os.makedirs(a.out, exist_ok=True)
    for i in range(a.count):
        case = generate_case(a.seed, i, g2=a.g2, g3=a.g3, g6=a.g6, g9=a.g9, g4=a.g4, g5=a.g5, g7=a.g7, s5=a.s5)
        if a.s5 and case["twin_src"]:
            with open(os.path.join(a.out, case["name"] + "_minus_one.pruv"), "w") as fh:
                fh.write(case["twin_src"])
        if a.g4 or a.g5 or a.g7:
            for rel, text in case["files"].items():
                path = os.path.join(a.out, case["name"], *rel.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
            continue
        with open(os.path.join(a.out, case["name"] + ".pruv"), "w", encoding="utf-8") as fh:
            fh.write(case["src"])
    print("wrote %d files to %s" % (a.count, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
