#!/usr/bin/env python3
"""L3-1 A2 fixtures: time.pruv (iso_of and helpers) and import.pruv (read_head, tail_info, selection helpers) on
py/rust, py/llvm, rs/rust, rs/llvm.

The oracle is independent of the Pruv code. It follows tail.ts/claude.ts with the policies of
docs/CLAUDE_IMPORT_SPEC.md (P1 strict UTF-8/JSON, P2 lone surrogates -> U+FFFD, P4 restricted iso_of). JSON is
parsed with Python's strict decoder, last-wins keys and raw number wrappers (parse_int/parse_float callbacks,
no float coercion). Calendar expectations use proleptic-Gregorian day counting by 400-year cycles and a year
walk, not the civil-from-days formula of time.pruv. The text oracles (ECMAScript trim, one_line, human_text,
ranked titles) are the independent A1 oracles imported from test_a1.py (same repository, same policies); they
are not generated from Pruv code.

Fixture line: `op a|bytes1|bytes2`, bytes as decimal words (`v*k` repeats v k times). Ops:
  iso a|line|key       time.iso_of of the value of `key` in the object line
  itime v              integer_time        fmt ms          format_iso        canon|text   canonical_iso
  lastmax|ranks        last_max            first|flags     first_present
  head cut_after|data  read_head packet    tail cut_before|data  tail_info packet
"""
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import shutil
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
JSON_DIR = HERE.parent / 'json'
WORK = HERE / 'work' / 'a2'

_spec = importlib.util.spec_from_file_location('test_a1_oracle', HERE / 'test_a1.py')
a1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(a1)

HARNESS = r'''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead};
fn expand(words: Vec<&str>) -> Vec<u8> {
 let mut out = Vec::new();
 for w in words {
  match w.split_once('*') {
   Some((v, k)) => { let v: u8 = v.parse().unwrap(); for _ in 0..k.parse::<usize>().unwrap() { out.push(v); } }
   None => out.push(w.parse().unwrap()),
  }
 }
 out
}
fn main() {
 for line in io::stdin().lock().lines() {
  let line = line.unwrap();
  let parts: Vec<&str> = line.split('|').collect();
  let mut head = parts[0].split_whitespace();
  let op = head.next().unwrap();
  let a: i64 = head.next().unwrap().parse().unwrap();
  let w = |k: usize| -> Vec<u8> { expand(parts.get(k).map(|s| s.split_whitespace().collect::<Vec<&str>>()).unwrap_or_default()) };
  let out: Vec<i64> = match op {
   "iso" => sol::iso_w(&w(1), &w(2)),
   "itime" => sol::integer_time_w(a),
   "fmt" => sol::format_iso_w(a),
   "canon" => sol::canonical_w(&w(1)),
   "lastmax" => sol::last_max_w(&w(1)),
   "first" => sol::first_present_w(&w(1)),
   "head" => sol::head_packet(&w(1), a),
   "tail" => sol::tail_packet(&w(1), a),
   _ => panic!("unknown fixture"),
  };
  println!("{}", out.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(" "));
 }
}
'''

enc = a1.enc
es_trim = a1.es_trim

# ---------------- oracle ----------------
SAFE = 9007199254740991
MIN_MS, MAX_MS = -62167219200000, 253402300799999
NONE_TIME = 9223372036854775807
EDGE = 65536


class RInt:
    def __init__(self, text):
        self.text = text


class RFloat:
    def __init__(self, text):
        self.text = text


def _bad_constant(name):
    raise ValueError(name)


def o_parse(line):
    """tail.ts parseLine under P1: strict UTF-8, strict JSON, object roots, depth <= 128."""
    try:
        text = line.decode('utf-8')
    except UnicodeDecodeError:
        return None
    try:
        v = json.loads(text, object_pairs_hook=a1.obj_hook, parse_constant=_bad_constant, parse_int=RInt, parse_float=RFloat)
    except (ValueError, RecursionError):
        return None
    if not isinstance(v, dict) or a1.depth(v) > 128:
        return None
    return v


def is_leap(y):
    return y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)


def ylen(y):
    return 366 if is_leap(y) else 365


def mdays(y, m):
    return 29 if (m == 2 and is_leap(y)) else [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]


def days_before_year(y):
    """Days from 0000-01-01 to y-01-01: whole 400-year cycles of 146097 days plus a year walk."""
    cycles = y // 400
    d = 146097 * cycles
    for yy in range(400 * cycles, y):
        d += ylen(yy)
    return d


def ms_of(y, mo, d, h=0, mi=0, s=0, f=0):
    n = days_before_year(y) + sum(mdays(y, k) for k in range(1, mo)) + d - 1
    return ((n - 719528) * 86400 + h * 3600 + mi * 60 + s) * 1000 + f   # 719528 days: 0000-01-01 -> 1970-01-01


def o_fmt(ms):
    days, rem = divmod(ms, 86400000)
    n = days + 719528
    cycles, n = divmod(n, 146097)
    y = 400 * cycles
    while n >= ylen(y):
        n -= ylen(y)
        y += 1
    mo = 1
    while n >= mdays(y, mo):
        n -= mdays(y, mo)
        mo += 1
    s, f = divmod(rem, 1000)
    mi, s = divmod(s, 60)
    h, mi = divmod(mi, 60)
    return '%04d-%02d-%02dT%02d:%02d:%02d.%03dZ' % (y, mo, n + 1, h, mi, s, f)


def o_itime(v):
    ms = v * 1000 if v < 100000000000 else v
    return ms if MIN_MS <= ms <= MAX_MS else None


CANON = re.compile('([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})\\.([0-9]{3})Z')


def o_canon(s):
    m = CANON.fullmatch(s)
    if not m:
        return False
    y, mo, d, h, mi, sec, _ = map(int, m.groups())
    return 1 <= mo <= 12 and 1 <= d <= mdays(y, mo) and h <= 23 and mi <= 59 and sec <= 59


def o_iso(v):
    if isinstance(v, RInt):
        if len(v.text.lstrip('-')) > 17:
            return None
        n = int(v.text)
        if abs(n) > SAFE:
            return None
        ms = o_itime(n)
        return None if ms is None else o_fmt(ms)
    if isinstance(v, str):
        s = a1.fix(v)
        t = es_trim(s)
        if t and all(c in '0123456789' for c in t):
            digits = t.lstrip('0')
            if len(digits) > 16 or int(digits or '0') > SAFE:
                return None
            ms = o_itime(int(digits or '0'))
            return None if ms is None else o_fmt(ms)
        if len(s.encode('utf-8')) == 24 and o_canon(s):
            return s
        return None
    return None     # missing, null, booleans, arrays, objects, RFloat


def split_lines(data, is_final):
    out, pos = [], 0
    while True:
        i = data.find(b'\n', pos)
        if i < 0:
            if is_final and pos < len(data):
                out.append(data[pos:])
            return out
        line = data[pos:i]
        out.append(line[:-1] if line.endswith(b'\r') else line)
        pos = i + 1


def packet(mode, title=None, cwd=None, ep=None, last=None):
    text, refs = b'', []
    for v in (title, cwd, ep, last, None):
        if v is None:
            refs += [-1, 0]
        else:
            b = v.encode('utf-8')
            refs += [len(text), len(b)]
            text += b
    return [0, 14, 0, len(text), 1, mode, 0, 0] + refs + list(text)


def o_head(data, cut_after):
    if len(data) > EDGE:
        return [1, 0]
    cwd = ep = title = None
    for line in split_lines(data, not cut_after):
        e = o_parse(line)
        if e is None:
            continue
        if cwd is None:
            cwd = a1.S(e.get('cwd'))
        if ep is None:
            ep = a1.S(e.get('entrypoint'))
        if title is None:
            t = a1.o_human(e)
            if t:
                title = a1.o_one_line(t, 120)
        if title is not None and cwd is not None and ep is not None:
            break
    return packet(0, title=title, cwd=cwd, ep=ep)


def o_tail(data, cut_before):
    if len(data) > EDGE:
        return [1, 0]
    if cut_before:
        i = data.find(b'\n')
        data = data[i + 1:] if i >= 0 else b''
    best, last = None, None
    for line in split_lines(data, True):
        e = o_parse(line)
        if e is None:
            continue
        at = o_iso(e.get('timestamp'))
        if at:
            last = at
        found = a1.o_title(e)
        if found and (best is None or found[0] >= best[0]):
            best = found
    return packet(1, title=None if best is None else a1.o_one_line(best[1], 120), last=last)


def oracle(op, a, w):
    if op == 'itime':
        if abs(a) > SAFE:
            return [-2]
        ms = o_itime(a)
        return [NONE_TIME if ms is None else ms]
    if op == 'fmt':
        return [-2] if not MIN_MS <= a <= MAX_MS else [0] + list(o_fmt(a).encode())
    if op == 'canon':
        return [1 if o_canon(w[0].decode('utf-8')) else 0]
    if op == 'lastmax':
        r = list(w[0])
        if any(not 1 <= x <= 3 for x in r):
            return [-2]
        return [-1] if not r else [max(range(len(r)), key=lambda i: (r[i], i))]
    if op == 'first':
        f = list(w[0])
        return [next((i for i, x in enumerate(f) if x), -1)]
    if op == 'head':
        return o_head(w[0], bool(a))
    if op == 'tail':
        return o_tail(w[0], bool(a))
    if op == 'iso':
        e = o_parse(w[0])
        if e is None:
            return [9]
        key = w[1].decode('utf-8')
        if key not in e:
            return [1]
        r = o_iso(e[key])
        return [1] if r is None else [0] + list(r.encode())
    raise RuntimeError(op)


def selfcheck():
    """Hand-derived expectations that keep the oracle itself honest."""
    B = lambda s: list(s.encode())
    L = lambda s: s.encode()
    checks = [
        (o_fmt(0), '1970-01-01T00:00:00.000Z'),
        (o_fmt(1500), '1970-01-01T00:00:01.500Z'),
        (o_fmt(o_itime(99999999999)), '5138-11-16T09:46:39.000Z'),       # 1e11 - 1 seconds
        (o_fmt(o_itime(100000000000)), '1973-03-03T09:46:40.000Z'),      # 1e11 as milliseconds
        (o_fmt(o_itime(-1)), '1969-12-31T23:59:59.000Z'),
        (o_fmt(o_itime(-62167219200)), '0000-01-01T00:00:00.000Z'),
        (o_fmt(MAX_MS), '9999-12-31T23:59:59.999Z'),
        (o_fmt(o_itime(951782400)), '2000-02-29T00:00:00.000Z'),
        (o_fmt(o_itime(4107542400)), '2100-03-01T00:00:00.000Z'),
        (o_fmt(o_itime(4107456000)), '2100-02-28T00:00:00.000Z'),
        (o_itime(-62167219201), None),
        (o_itime(253402300800000), None),
        (o_itime(253402300799999), 253402300799999),
        (o_itime(-0), 0),
        (o_iso(RInt('-0')), '1970-01-01T00:00:00.000Z'),
        (o_iso(RFloat('1.0')), None),
        (o_iso(RInt('9007199254740992')), None),
        (o_iso('  123  '), '1970-01-01T00:02:03.000Z'),
        (o_iso('\u3000012\ufeff'), '1970-01-01T00:00:12.000Z'),
        (o_iso('1.5'), None),
        (o_iso('+1'), None),
        (o_iso('2000-02-29T00:00:00.000Z'), '2000-02-29T00:00:00.000Z'),
        (o_iso('1900-02-29T00:00:00.000Z'), None),
        (o_iso('0000-02-29T00:00:00.000Z'), '0000-02-29T00:00:00.000Z'),
        (o_iso(' 2000-02-29T00:00:00.00Z'), None),
        (o_iso('2000-02-29T24:00:00.000Z'), None),
        (o_iso(None), None),
        (o_iso(True), None),
        (ms_of(1970, 1, 1), 0),
        (ms_of(2000, 2, 29), 951782400000),
        (ms_of(0, 1, 1), MIN_MS),
        (ms_of(9999, 12, 31, 23, 59, 59, 999), MAX_MS),
        (o_head(b'{"cwd":"/a","entrypoint":"cli"}\n', 0), [0, 14, 0, 5, 1, 0, 0, 0, -1, 0, 0, 2, 2, 3, -1, 0, -1, 0] + B('/acli')),
        (o_head(b'{"cwd":"","type":"user","message":{"content":" hi  there "}}\n', 0),
         [0, 14, 0, 8, 1, 0, 0, 0, 0, 8, 8, 0, -1, 0, -1, 0, -1, 0] + B('hi there')),
        (o_head(b'{"cwd":"/a"}', 1), [0, 14, 0, 0, 1, 0, 0, 0, -1, 0, -1, 0, -1, 0, -1, 0, -1, 0]),
        (o_tail(L('{"type":"summary","summary":"S","timestamp":0}\n{"type":"ai-title","aiTitle":"A"}\n'), 0),
         [0, 14, 0, 25, 1, 1, 0, 0, 0, 1, -1, 0, -1, 0, 1, 24, -1, 0] + B('A1970-01-01T00:00:00.000Z')),
        (o_tail(L('{"timestamp":1}\n{"timestamp":2}\n'), 1), [0, 14, 0, 24, 1, 1, 0, 0, -1, 0, -1, 0, -1, 0, 0, 24, -1, 0] + B('1970-01-01T00:00:02.000Z')),
        (o_tail(b'a' * 70000, 0), [1, 0]),
    ]
    for i, (got, want) in enumerate(checks):
        if got != want:
            raise RuntimeError(f'oracle self-check {i}: {got!r} != {want!r}')
    # formatter against native datetime over the representable years (year 0000 is outside datetime)
    from datetime import datetime, timedelta, timezone
    rnd = random.Random(7)
    for _ in range(300):
        ms = rnd.randint(ms_of(1, 1, 1), MAX_MS)
        dt = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)
        want = dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)
        if o_fmt(ms) != want:
            raise RuntimeError(f'oracle formatter {ms}: {o_fmt(ms)} != {want}')
    for y in (0, 1, 4, 100, 400, 1900, 2000, 2100, 9999):
        for mo, d in ((1, 1), (2, 28), (3, 1), (12, 31)):
            if o_fmt(ms_of(y, mo, d, 12, 34, 56, 789)) != '%04d-%02d-%02dT12:34:56.789Z' % (y, mo, d):
                raise RuntimeError(f'oracle round trip {y}-{mo}-{d}')


# ---------------- fixtures ----------------
def J(obj):
    """Compact JSON bytes; text with lone surrogates falls back to \\u escapes."""
    try:
        return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    except UnicodeEncodeError:
        return json.dumps(obj, ensure_ascii=True, separators=(',', ':')).encode('ascii')


def lines(*items, crlf=False, final_lf=True):
    out = []
    for it in items:
        out.append(it if isinstance(it, bytes) else J(it))
    sep = b'\r\n' if crlf else b'\n'
    return sep.join(out) + (sep if final_lf else b'')


def at_line(token, typ='user'):
    """A line whose timestamp is the raw JSON token (None: no timestamp key)."""
    if token is None:
        return b'{"type":"%s"}' % typ.encode()
    return b'{"type":"%s","timestamp":%s}' % (typ.encode(), token if isinstance(token, bytes) else token.encode())


def title_line(typ, **kw):
    return J(dict(type=typ, **kw))


def fixtures():
    cases = []

    def add(op, a=0, *w):
        ws = [x.encode() if isinstance(x, str) else bytes(x) for x in w] + [b''] * 3
        ws = ws[:3]
        cases.append((op, a, ws, oracle(op, a, ws)))

    def iso(token, key='timestamp'):
        add('iso', 0, b'{"%s":%s}' % (key.encode(), token if isinstance(token, bytes) else token.encode()), key)

    # ---- integer_time: signed seconds/milliseconds threshold, range edges, safe bounds ----
    for v in [0, 1, -1, 59, 86400, 951782400, 99999999998, 99999999999, 100000000000, 100000000001, 100000000002,
              -99999999999, -100000000000, -100000000001, -62167219199, -62167219200, -62167219201, -62167219202,
              -62135596800, -62135596801, 253402300798999, 253402300799998, 253402300799999, 253402300800000,
              253402300800001, 253402300799, 253402300800, 253402300801, 1000000000000, SAFE - 1, SAFE, -SAFE + 1, -SAFE,
              SAFE + 1, -SAFE - 1, 1 << 62, -(1 << 62)]:
        add('itime', v)

    # ---- format_iso: boundaries and calendar edges ----
    for ms in [0, 1, 999, 1000, -1, -999, -1000, -1001, 86399999, 86400000, 951782400000, 951868799999, 951868800000,
               MIN_MS, MIN_MS + 1, MIN_MS - 1, MAX_MS, MAX_MS - 1, MAX_MS + 1, 253402300800000, -62135596800000,
               -62135596800001, 99999999999000, 100000000000, 1573 * 86400000]:
        add('fmt', ms)

    # ---- canonical_iso: shapes, calendar, year 0000/9999, adjacent rejected values ----
    canon = ['2020-01-01T00:00:00.000Z', '0000-01-01T00:00:00.000Z', '9999-12-31T23:59:59.999Z', '0000-02-29T00:00:00.000Z',
             '0000-12-31T23:59:59.999Z', '0000-00-01T00:00:00.000Z', '0000-01-00T00:00:00.000Z', '9999-12-32T23:59:59.999Z',
             '9999-13-01T00:00:00.000Z', '9999-12-31T24:00:00.000Z', '9999-12-31T23:60:00.000Z', '9999-12-31T23:59:60.000Z',
             '9999-12-31T23:59:59.1000Z', '9999-12-31T23:59:59.99Z', '9999-12-31T23:59:59Z', '10000-01-01T00:00:00.000Z',
             '+010000-01-01T00:00:00.000Z', '-000001-12-31T23:59:59.999Z', '+002020-01-01T00:00:00.000Z',
             '2020-01-01T00:00:00.000+00:00', '2020-01-01T00:00:00.000+01:00', '2020-01-01T00:00:00.000-0000',
             '2020-01-01T00:00:00.000', '2020-01-01T00:00:00', '2020-01-01 00:00:00.000Z', '2020-01-01t00:00:00.000Z',
             '2020-01-01T00:00:00.000z', '2020-01-01T00:00:00,000Z', '2020-01-01T00:00:00:000Z', '2020/01/01T00:00:00.000Z',
             '2020-01-01', '2020-01', '2020', '20200101T000000.000Z', '2020-W01-1T00:00:00.000Z', '2020-001T00:00:00.000Z',
             ' 2020-01-01T00:00:00.000Z', '2020-01-01T00:00:00.000Z ', '2020-01-01T00:00:00.000Z\n', '2020-01-01T00:00:00.00Z ',
             '2020-01-01T00:00:00.000ZZ', '2020-01-0aT00:00:00.000Z', '2020-01-01T0x:00:00.000Z', '２０２０-01-01T00:00:00.000Z',
             '2020-01-01T00:00:00.000\u0661', '', 'Z', '2020-04-30T00:00:00.000Z', '2020-04-31T00:00:00.000Z',
             '2020-06-31T00:00:00.000Z', '2020-09-31T00:00:00.000Z', '2020-11-31T00:00:00.000Z', '2020-01-31T00:00:00.000Z',
             '2020-12-31T00:00:00.000Z', '2020-02-30T00:00:00.000Z', '2020-00-10T00:00:00.000Z', '2020-01-01T23:59:59.999Z',
             'Tue, 01 Jan 2020 00:00:00 GMT', 'Jan 1 2020', '2020-01-01T00:00:00.000Z'.lower()]
    for y in (0, 1, 4, 100, 399, 400, 1600, 1700, 1800, 1900, 1999, 2000, 2001, 2023, 2024, 2100, 2200, 2300, 2400, 9996, 9999):
        for d in (28, 29, 30):
            canon.append('%04d-02-%02dT00:00:00.000Z' % (y, d))
        canon.append('%04d-03-01T23:59:59.999Z' % y)
        canon.append('%04d-12-31T23:59:59.999Z' % y)
    for s in canon:
        add('canon', 0, s)
    add('canon', 0, b'2020-01-01T00:00:00.000Z\x00')
    add('canon', 0, b'2020-01-01T00:00:00.000\xc3\xa9')

    # ---- iso_of: JSON numbers ----
    num_tokens = ['0', '-0', '1', '-1', '59', '60', '86399', '86400', '951782400', '4107542400', '4107456000',
                  '99999999998', '99999999999', '100000000000', '100000000001', '-99999999999', '-100000000000',
                  '-100000000001', '-62167219200', '-62167219201', '-62167219199', '-62135596800', '-62135596801',
                  '253402300799999', '253402300800000', '253402300799998', '253402300800', '253402300799', '1700000000',
                  '1700000000000', '1700000000123', '9007199254740991', '9007199254740992', '9007199254740990',
                  '-9007199254740991', '-9007199254740992', '18014398509481984', '99999999999999999999',
                  '123456789012345678901234567890',
                  '1.0', '1.5', '1e0', '1E2', '1e+2', '1e-2', '1.0e0', '-1.5', '0.0', '-0.0', '-0e0', '1e11', '1.5e9',
                  '100000000000.0', '1700000000.5', '0e5', '-1e0', '1E11', '2.5E+3']
    for t in num_tokens:
        iso(t)
    # ---- iso_of: strings (numeric, whitespace, rejected forms) ----
    str_values = ['0', '1', '  12  ', '\t12\n', '\u3000 12', '\ufeff12', '\u00a012\u2028', '012', '000000000000000000012',
                  '0' * 40, '0' * 40 + '7', '9007199254740991', '9007199254740992', '99999999999999999999999', '',
                  ' ', '\u3000', '\ufeff\n', '1.5', '1.0', '1.', '.5', '+1', '-1', '-0', '1e3', '1E3', '1_0', '0x10',
                  '\uff11\uff12\uff13', '\u0661\u0662\u0663', '12a', 'a12', '1 2', '12\u200b', '\u200b12', '12\u0085',
                  '12\u180e', '99999999999', '100000000000', ' 100000000000 ', '99999999998', '-62167219200',
                  '62167219200', '253402300800000', '253402300799999', '253402300800', '4107542400', 'null', 'NaN',
                  'Infinity', '0.0', '00', '0000000000000000', '12\x00', '\ud800', '\ud83d\ude00', '12\ud800']
    for s in str_values:
        iso(J(s).decode('utf-8'))
    # JSON-escaped digits and surrogates decode before the digit test
    for raw in [b'"\\u0031\\u0032"', b'"\\u00201\\u0020"', b'"1\\n"', b'"\\u3000\\u000912"', b'"1\\u0000"', b'"\\ud800"',
                b'"\\ud83d\\ude00"', b'"12\\ud800"', b'"\\u0031.\\u0035"', b'"2020-01-01T00:00:00.000\\u005a"',
                b'"2020-01-01T00:00:00.000\\u005A"', b'"2020-01-01T00:00:00.000Z\\n"', b'"\\u0032020-01-01T00:00:00.000Z"',
                b'"2020-01-01T00:00:00.000\\u00e9"', b'"2020-01-01T00:00:00\\u002e000Z"']:
        iso(raw)
    # ---- iso_of: ISO strings through the JSON path ----
    for s in canon[:70]:
        iso(J(s).decode('utf-8'))
    # ---- iso_of: other kinds, keys and line shapes ----
    for raw in ['null', 'true', 'false', '[]', '[0]', '[1700000000]', '["2020-01-01T00:00:00.000Z"]', '{}', '{"a":1}',
                '{"timestamp":1}']:
        iso(raw)
    add('iso', 0, b'{}', 'timestamp')
    add('iso', 0, b'{"Timestamp":5}', 'timestamp')
    add('iso', 0, b'{"timestamp":"x","timestamp":5}', 'timestamp')
    add('iso', 0, b'{"timestamp":5,"timestamp":"x"}', 'timestamp')
    add('iso', 0, b'{"timestamp":5,"timestamp":null}', 'timestamp')
    add('iso', 0, b'{"time\\u0073tamp":5}', 'timestamp')
    add('iso', 0, b'{"x":{"timestamp":5}}', 'timestamp')
    add('iso', 0, b'{"timestamp":5}', 'x')
    add('iso', 0, b'[5]', 'timestamp')
    add('iso', 0, b'', 'timestamp')
    add('iso', 0, b'{"timestamp":', 'timestamp')
    add('iso', 0, b'{"timestamp":5}\r', 'timestamp')
    add('iso', 0, b'{"timestamp":"\xff"}', 'timestamp')
    add('iso', 0, b'{"timestamp":NaN}', 'timestamp')
    add('iso', 0, b'{"timestamp":01}', 'timestamp')
    # depth carried by an overwritten duplicate key (128 rejects the line, 127 keeps it)
    for n in (127, 128):
        deep = b'{"x":' + b'[' * n + b'0' + b']' * n + b',"x":0,"cwd":"bad","timestamp":1}'
        add('iso', 0, deep, 'timestamp')
        add('head', 0, deep + b'\n')
        add('tail', 0, b'{"timestamp":2}\n' + deep + b'\n')

    # ---- iso_of: leap days, centuries, year 0000/9999 and neighbours as numbers and strings ----
    years = (0, 1, 3, 4, 99, 100, 399, 400, 401, 1600, 1699, 1700, 1800, 1899, 1900, 1904, 1969, 1970, 1972, 2000, 2024, 2096,
             2100, 2399, 2400, 5138, 9996, 9999)

    def number_token(ms):
        if ms >= 100000000000:
            return str(ms)
        return str(ms // 1000) if ms % 1000 == 0 else None

    for y in years:
        for mo, d in ((2, 28), (2, 29), (3, 1), (12, 31), (1, 1)):
            if d > mdays(y, mo):
                continue
            for hms in ((0, 0, 0, 0), (23, 59, 59, 999)):
                ms = ms_of(y, mo, d, *hms)
                for delta in (0, 1000):
                    tok = number_token(ms + delta)
                    if tok is not None:
                        iso(tok)
                        iso('"%s"' % tok)
                if MIN_MS <= ms <= MAX_MS:
                    iso('"%s"' % o_fmt(ms))
    for y in (1900, 2100, 2023, 1999, 0, 2000, 2024, 400):
        iso('"%04d-02-29T00:00:00.000Z"' % y)
    rnd = random.Random(20261114)
    for _ in range(160):
        ms = rnd.randint(MIN_MS, MAX_MS)
        tok = number_token(ms)
        if tok is None:
            tok = str(ms // 1000)
        iso(tok)
        iso('"%s"' % tok)
        iso('"%s"' % o_fmt(ms))

    # ---- selection helpers ----
    for r in [[], [1], [2], [3], [1, 1], [3, 3], [1, 2, 3], [3, 2, 1], [2, 3, 3, 1], [2, 3, 1, 3, 2], [1, 1, 1, 1], [3, 1, 3],
              [1, 3, 2, 3, 3, 1], [2, 2, 3, 2, 3, 3, 3], [0], [4], [1, 2, 0], [1, 9, 3], [3] * 50 + [2], [1] * 50]:
        add('lastmax', 0, bytes(r))
    for f in [[], [0], [1], [0, 0], [0, 1], [1, 0], [0, 0, 5], [0, 7, 0, 1], [0] * 40, [0] * 40 + [255], [2, 2, 2]]:
        add('first', 0, bytes(f))

    # ---- head: empty vs absent cwd/entrypoint, early stop, title, framing ----
    USER = lambda text, **kw: dict({'type': 'user', 'message': {'role': 'user', 'content': text}}, **kw)
    ASSIST = lambda text: {'type': 'assistant', 'message': {'role': 'assistant', 'content': text}}
    MISSING = object()

    def cwd_line(key, v):
        return {} if v is MISSING else {key: v}

    values = [MISSING, None, 5, True, '', 'a', ['a'], {'k': 'a'}, ' ', 'caf\u00e9 \U0001F600']
    for key in ('cwd', 'entrypoint'):
        for first in values:
            for second in values:
                add('head', 0, lines(cwd_line(key, first), cwd_line(key, second)))
    for v in ['\ud800', 'a\ud83d', '\ud83d\ude00', 'x\u0000y', '/tmp/a b', '\\\\srv\\share', '', 'C:\\Users\\x']:
        add('head', 0, lines({'cwd': v, 'entrypoint': v}))
    add('head', 0, b'{"cwd":"a\\ud800b","entrypoint":"\\ud83d\\ude00"}\n')
    add('head', 0, b'{"cwd":"x","cwd":"y"}\n')
    add('head', 0, b'{"cwd":"x","cwd":null}\n')
    add('head', 0, b'{"cwd":null,"cwd":"y"}\n')
    add('head', 0, b'{"c\\u0077d":"esc","entrypo\\u0069nt":"esc2"}\n')
    add('head', 0, lines({'cwd': '/a'}, {'entrypoint': 'cli'}))
    add('head', 0, lines({'entrypoint': 'cli'}, {'cwd': '/a'}))
    add('head', 0, lines({'cwd': '', 'entrypoint': ''}, {'cwd': '/a', 'entrypoint': 'cli'}))
    add('head', 0, lines({'cwd': '', 'entrypoint': None}, {'cwd': '/a', 'entrypoint': 'cli'}))
    # early stop: all three present, then garbage and different values
    full = USER('first question', cwd='/one', entrypoint='cli')
    add('head', 0, lines(full, {'cwd': '/two', 'entrypoint': 'sdk'}, USER('second'), b'{broken', b'\xff'))
    add('head', 0, lines(full, b'{"a":' * 200 + b'0' + b'}' * 200))
    add('head', 0, lines({'cwd': '/a'}, {'entrypoint': 'cli'}, USER('late title'), {'cwd': 'zzz'}, USER('later')))
    add('head', 0, lines({'cwd': '/a'}, USER('t1'), {'entrypoint': 'cli'}, USER('t2')))
    add('head', 0, lines(USER('t1', cwd='/a'), {'entrypoint': 'cli'}, USER('t2')))
    # head title: first human text only, one_line, filters
    inter = '[Request interrupted by user]'
    add('head', 0, lines(ASSIST('answer'), USER('  hello \n\t world  ')))
    add('head', 0, lines(USER(inter), USER('real')))
    add('head', 0, lines(USER(inter + ' for tool use'), USER('  '), USER('real2')))
    add('head', 0, lines(USER('x', isMeta=True), USER('y', isSidechain=True), USER('z', isMeta='true')))
    add('head', 0, lines(USER([{'type': 'tool_result', 'content': 'r'}, {'type': 'text', 'text': 'no'}]), USER('yes')))
    add('head', 0, lines(USER([{'type': 'text', 'text': 'a'}, {'type': 'text', 'text': ''}, {'type': 'text', 'text': 'b'}])))
    add('head', 0, lines(USER([{'type': 'text', 'text': ''}, {'type': 'text', 'text': ''}]), USER('next')))
    add('head', 0, lines(USER('<task-notification>x</task-notification>', origin={'kind': 'task-notification'}), USER('h')))
    add('head', 0, lines(USER('<task-notification>x</task-notification>'), USER('h')))
    add('head', 0, lines({'type': 'custom-title', 'customTitle': 'T'}, {'type': 'summary', 'summary': 'S'}))
    add('head', 0, lines({'type': 'custom-title', 'customTitle': 'T'}, USER('real')))
    add('head', 0, lines(USER('a' * 130)))
    add('head', 0, lines(USER('a' * 119 + '\U0001F600')))
    add('head', 0, lines(USER('a' * 118 + '\U0001F600')))
    add('head', 0, lines(USER('\u3042' * 200)))
    add('head', 0, lines(USER('a  b ' * 40)))
    add('head', 0, lines(USER('\ud800 \udc00 x')))
    add('head', 0, b'{"type":"user","message":{"content":"\\ud83d\\ude00 \\ud800"}}\n')
    add('head', 0, lines(USER('\u2028x\u2029y\u00a0z\ufeff')))
    add('head', 0, lines(USER('line1\nline2\r\nline3')))
    # framing: LF/CRLF, cut_after, final unterminated range, malformed middle lines
    for cut in (0, 1):
        add('head', cut, lines(USER('t', cwd='/a', entrypoint='e'), final_lf=False))
        add('head', cut, lines({'cwd': '/a'}, USER('t'), final_lf=False))
        add('head', cut, lines({'cwd': '/a'}, USER('t')))
        add('head', cut, lines({'cwd': '/a'}, {'entrypoint': 'e'}, final_lf=False))
        add('head', cut, lines({'cwd': '/a'}, USER('t'), crlf=True))
        add('head', cut, lines({'cwd': '/a'}, USER('t'), crlf=True, final_lf=False))
        add('head', cut, b'')
        add('head', cut, b'\n')
        add('head', cut, b'\n\n\r\n')
        add('head', cut, b'{"cwd":"/a"}')
        add('head', cut, b'{"cwd":"/a"}\r')
        add('head', cut, b'{"cwd":"/a"')
        add('head', cut, b'garbage\n{"cwd":"/g"}\n[1]\n"s"\n7\nnull\n{"entrypoint":"/e"}\n')
        add('head', cut, b'\xef\xbb\xbf{"cwd":"/bom"}\n{"cwd":"/ok"}\n')
        add('head', cut, b'{"cwd":"\xff"}\n{"cwd":"/ok"}\n')
        add('head', cut, b'{"cwd":"/a"}\n' + J(USER('t')))
    add('head', 0, lines({'a': 1}, {'cwd': '/b'}, final_lf=False) + b'\n')
    # head size limit 65536
    pad = lambda n: b'{"cwd":"' + b'x' * n + b'"}\n'
    add('head', 0, pad(65536 - 11))
    add('head', 0, pad(65536 - 10))
    add('head', 1, pad(65536 - 11))
    add('head', 0, pad(65536 - 12) + b'\n')
    add('head', 0, b'{"cwd":"/a"}\n' + b' ' * (65536 - 13))
    add('head', 0, b'{"cwd":"/a"}\n' + b' ' * (65536 - 12))
    add('head', 1, b'{"cwd":"/a"}\n' + b'{"entrypoint":"e"' + b' ' * (65536 - 13 - 17))
    add('head', 0, b'{"cwd":"' + b'\\u00e9' * 9000 + b'"}\n')
    add('head', 0, b'{"cwd":"\xe2\x82\xac' * 1 + b'a' * 100 + b'"}\n')

    # ---- tail: framing, cut_before ----
    T1 = lambda **kw: dict({'type': 'user', 'timestamp': '2020-01-01T00:00:00.000Z'}, **kw)
    for cut in (0, 1):
        add('tail', cut, b'')
        add('tail', cut, b'\n')
        add('tail', cut, b'\n\n')
        add('tail', cut, lines({'timestamp': 1}))
        add('tail', cut, lines({'timestamp': 1}, final_lf=False))
        add('tail', cut, lines({'timestamp': 1}, {'timestamp': 2}))
        add('tail', cut, lines({'timestamp': 1}, {'timestamp': 2}, final_lf=False))
        add('tail', cut, lines({'timestamp': 1}, {'timestamp': 2}, {'timestamp': 3}, crlf=True))
        add('tail', cut, lines({'timestamp': 1}, {'timestamp': 2}, {'timestamp': 3}, crlf=True, final_lf=False))
        add('tail', cut, b'{"timestamp":1}')
        add('tail', cut, b'{"timestamp":1}\r')
        add('tail', cut, b'{"timestamp":1}\n{"timestamp":2}')
        add('tail', cut, b'{"timestamp":2}\n{"timestamp":')
        add('tail', cut, b'junk\n{"timestamp":7}\n')
        add('tail', cut, b'ial":1}\n{"timestamp":2}\n')
        add('tail', cut, b'{"type":"summary","summary":"first"}\n{"timestamp":2}\n')
        add('tail', cut, b'{"type":"custom-title","customTitle":"dropped when cut"}\n{"type":"summary","summary":"kept"}\n')
        add('tail', cut, b'no newline at all')
        add('tail', cut, b'\xff\xfe\n{"timestamp":1}\n')
        add('tail', cut, b'{"timestamp":1}\n\xff\n')
        add('tail', cut, b'\xef\xbb\xbf{"timestamp":1}\n{"timestamp":2}\n')
    add('tail', 1, b'\n{"timestamp":1}\n')
    add('tail', 1, b'\r\n{"timestamp":1}\n')
    add('tail', 1, b'{"timestamp":1}\n{"timestamp":2}\n')
    add('tail', 0, b'{"timestamp":1}\n{"timestamp":2}\n')
    pad_tail = lambda n: b'{"timestamp":1,"x":"' + b'y' * n + b'"}\n'
    add('tail', 0, pad_tail(65536 - 24))
    add('tail', 0, pad_tail(65536 - 23))
    add('tail', 0, pad_tail(65536 - 22))
    add('tail', 1, pad_tail(65536 - 24))
    add('tail', 1, b'z' * 100 + b'\n' + pad_tail(65536 - 24 - 101))
    add('tail', 0, b'a' * 65537)
    add('tail', 1, b'\n' * 65537)

    # ---- tail: nonmonotonic times, invalid times between valid ones, signed/ms/seconds mixes ----
    seqs = [
        ['1700000002', '1700000001'], ['1700000001', '1700000002'], ['"2021-01-01T00:00:00.000Z"', '"2020-01-01T00:00:00.000Z"'],
        ['"2020-01-01T00:00:00.000Z"', '1500000000'], ['1700000000000', '1700000000'], ['0', '-0'], ['-1', '1'],
        ['1700000000', None, '1600000000'], ['1700000000', 'null', '1600000000'], ['1700000000', '1.5', '1600000000'],
        ['1700000000', '"nonsense"', '1600000000'], ['1700000000', '"nonsense"'], ['1700000000', '9007199254740992'],
        ['1700000000', '"2020-02-30T00:00:00.000Z"'], ['1700000000', '"2020-01-01T00:00:00Z"'],
        ['1700000000', '"2020-01-01T00:00:00.000+00:00"'], ['1700000000', '"2020-01-01"'], ['1700000000', '[1]'],
        ['1700000000', '{}'], ['1700000000', 'true'], ['1700000000', '253402300800000'], ['1700000000', '-62167219201'],
        ['1700000000', '"  "'], ['1700000000', '""'], ['1700000000', '"+5"'], ['1700000000', '1e9'],
        ['"nonsense"', '1700000000', '"bad"'], ['"bad"'], ['null'], [None], ['1', '"9999-12-31T23:59:59.999Z"', '2'],
        ['"0000-01-01T00:00:00.000Z"', '-62167219200', '"0000-02-29T00:00:00.000Z"'],
        ['253402300799999', '253402300800000'], ['99999999999', '100000000000', '99999999999'],
        ['"  1700000000  "', '"x"'], ['"1700000000.5"', '5'], ['1700000000', '"12 34"', None, 'null', '2'],
    ]
    for toks in seqs:
        for typ in ('user', 'assistant'):
            add('tail', 0, lines(*[at_line(t, typ) for t in toks]))
    add('tail', 0, lines(at_line('5', 'file-history-snapshot'), at_line('7', 'system'), at_line('6', 'summary'), at_line('1', 'queue-operation')))
    add('tail', 0, lines(at_line('3', 'user'), b'{"timestamp":2}', b'{"type":1,"timestamp":1}'))
    add('tail', 0, lines(b'{"timestamp":5}', b'[5]', b'"7"', b'{"timestamp":'))
    add('tail', 0, lines(b'{"timestamp":5,"timestamp":null}'))
    add('tail', 0, lines(b'{"timestamp":null,"timestamp":5}'))
    add('tail', 0, lines(b'{"timestamp":5}', b'{"timestamp":6,"timestamp":"junk"}'))

    # ---- tail: title ranks, ties, key preferences ----
    TYPES = [('custom-title', 'customTitle'), ('ai-title', 'aiTitle'), ('summary', 'summary')]
    for n in (1, 2, 3):
        def seq(prefix, n=n):
            if n == 0:
                yield prefix
                return
            for t in TYPES:
                yield from seq(prefix + [t], n - 1)
        for combo in seq([]):
            add('tail', 0, lines(*[title_line(t, **{k: 'T%d' % i}) for i, (t, k) in enumerate(combo)]))
    for t, k in TYPES:
        for a_ in (1, 2):
            add('tail', 0, lines(title_line(t, **{k: 'early'}), title_line(t, **{k: 'late'})))
        add('tail', 0, lines(title_line(t, **{k: 'real'}), title_line(t, **{k: ' '}), title_line(t, **{k: 5})))
        add('tail', 0, lines(title_line(t, **{k: 'real'}), title_line(t, other='x')))
        # key preference and fallback to `title`
        add('tail', 0, lines(title_line(t, **{k: 'KEY', 'title': 'FALLBACK'})))
        add('tail', 0, lines(title_line(t, title='FALLBACK')))
        add('tail', 0, lines(title_line(t, **{k: '', 'title': 'FALLBACK'})))
        add('tail', 0, lines(title_line(t, **{k: ' \t\n\u3000\ufeff', 'title': 'FALLBACK'})))
        add('tail', 0, lines(title_line(t, **{k: '\u200b', 'title': 'FALLBACK'})))
        add('tail', 0, lines(title_line(t, **{k: None, 'title': 'FALLBACK'})))
        add('tail', 0, lines(title_line(t, **{k: 5, 'title': 'FALLBACK'})))
        add('tail', 0, lines(title_line(t, **{k: ['x'], 'title': 'FALLBACK'})))
        add('tail', 0, lines(title_line(t, **{k: ' ', 'title': ' '})))
        add('tail', 0, lines(title_line(t, **{k: 'KEY', 'title': None})))
        add('tail', 0, lines(title_line(t, **{k: '  padded  \n title  '})))
        add('tail', 0, lines(title_line(t, **{k: 'a' * 130})))
        add('tail', 0, lines(title_line(t, **{k: 'a' * 119 + '\U0001F600'})))
        add('tail', 0, lines(title_line(t, **{k: 'a' * 118 + '\U0001F600'})))
        add('tail', 0, lines(title_line(t, **{k: '\u3042' * 200})))
        add('tail', 0, lines(title_line(t, **{k: 'a \t b \u3000 c'})))
        add('tail', 0, lines(title_line(t, **{k: 'x ' * 70})))
        add('tail', 0, b'{"type":"%s","%s":"\\ud800"}\n' % (t.encode(), k.encode()))
        add('tail', 0, b'{"type":"%s","%s":"\\ud83d\\ude00 z"}\n' % (t.encode(), k.encode()))
        add('tail', 0, b'{"type":"%s","%s":"a","%s":"b"}\n' % (t.encode(), k.encode(), k.encode()))
        add('tail', 0, b'{"type":"%s","%s":"a","%s":5}\n' % (t.encode(), k.encode(), k.encode()))
        add('tail', 0, b'{"type":"other","type":"%s","%s":"dup"}\n' % (t.encode(), k.encode()))
        add('tail', 0, b'{"type":"%s","type":"other","%s":"dup"}\n' % (t.encode(), k.encode()))
        add('tail', 0, lines(title_line(t, isMeta=True, isSidechain=True, **{k: 'flags ignored'})))
        add('tail', 0, lines(title_line(t, **{k: 'with time', 'timestamp': 1700000000})))
    # key-less / wrong-type / cross-type lines never count
    add('tail', 0, lines({'title': 'orphan'}, {'type': 'user', 'title': 'u'}, {'customTitle': 'c'}))
    add('tail', 0, lines(title_line('custom-title', aiTitle='wrong key'), title_line('ai-title', customTitle='wrong key')))
    add('tail', 0, lines(title_line('summary', customTitle='x', aiTitle='y')))
    for tp in ['Custom-Title', 'custom_title', 'custom-title ', ' summary', 'SUMMARY', '', None, 1, ['summary']]:
        add('tail', 0, lines({'type': tp, 'customTitle': 'x', 'aiTitle': 'y', 'summary': 'z', 'title': 'w'}))
    # ties and lower-after-higher
    add('tail', 0, lines(title_line('custom-title', customTitle='C'), title_line('ai-title', aiTitle='A'), title_line('summary', summary='S')))
    add('tail', 0, lines(title_line('summary', summary='S1'), title_line('summary', summary='S2'), title_line('ai-title', aiTitle='A1'),
                         title_line('ai-title', aiTitle='A2'), title_line('summary', summary='S3')))
    add('tail', 0, lines(title_line('ai-title', aiTitle='A1'), title_line('custom-title', customTitle='C1'),
                         title_line('custom-title', customTitle='C2'), title_line('custom-title', title='C3')))
    add('tail', 0, lines(title_line('custom-title', customTitle='C1'), title_line('custom-title', customTitle=' ')))
    add('tail', 0, lines(title_line('summary', summary='S1', timestamp=1), title_line('summary', summary='S2'), at_line('2')))
    add('tail', 0, lines(title_line('summary', summary='S', timestamp='bad'), title_line('ai-title', aiTitle='A', timestamp=9)))
    return cases


def configure():
    WORK.mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = str(WORK)
    spec = importlib.util.spec_from_file_location('a2_setup', JSON_DIR / 'run_a2.py')
    setup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(setup)
    setup.WORK = WORK
    return setup.configure(), setup.run


def main():
    selfcheck()
    g2, run = configure()
    # The str adapter crate (UTF-8 representation conversion), as in run_a3.py.
    target = WORK / 'str-adapter'
    run([shutil.which('cargo') or str(Path.home() / '.cargo/bin/cargo'), 'build', '--release', '--offline', '--quiet',
         '--manifest-path', JSON_DIR / 'str_adapter/Cargo.toml', '--target-dir', target])
    rlib, deps = target / 'release/libpruv_str.rlib', target / 'release/deps'
    flags = ['--rust-extern', f'pruv_str={rlib}', '--rust-search', str(deps)]
    rustflags = ['--extern', f'pruv_str={rlib}', '-L', f'dependency={deps}']
    cases = fixtures()
    payload = ''.join(f'{op} {a}|' + '|'.join(enc(list(x)) for x in w) + '\n' for op, a, w, _ in cases)
    expected = [' '.join(map(str, want)) for *_, want in cases]
    failed = False
    for compiler in ('py', 'rs'):
        for backend in ('rust', 'llvm'):
            key = f'{compiler}/{backend}'
            try:
                work = WORK / f'{compiler}_{backend}'
                work.mkdir(exist_ok=True)
                compiled = g2.compile_pruv(compiler, str(HERE / 'a2_root.pruv'), str(work), backend, flags)
                if compiled['rc'] != 0:
                    raise RuntimeError('compile/verify failed: ' + str(compiled['errors'] or compiled['stderr']))
                print(f'{key}: verified and compiled', flush=True)
                harness = work / 'main.rs'
                harness.write_text(HARNESS.replace('@SOL@', compiled['rs']))
                extra = []
                if compiled['ll']:
                    extra, error = g2.build_llvm_objects(compiled['ll'], 'a2', str(work))
                    if error:
                        raise RuntimeError(error)
                exe = work / 'runner'
                run([g2.RUSTC, '-O', '--edition', '2021', harness, '-o', exe] + extra + rustflags)
                got = run([exe], payload).splitlines()
                if len(got) != len(expected):
                    raise RuntimeError(f'{len(got)} answers for {len(expected)} fixtures')
                bad = [(i, w, g) for i, (w, g) in enumerate(zip(expected, got)) if w != g]
                for i, w, g in bad[:20]:
                    op, a, ws, _ = cases[i]
                    print(f'{key}: fixture {i} {op} {a} {ws[0][:60]!r} {ws[1][:30]!r}: expected {w[:200]}, got {g[:200]}')
                failed |= bool(bad)
                print(f'{key}: {len(cases) - len(bad)}/{len(cases)} fixtures passed', flush=True)
            except Exception as exc:
                failed = True
                print(f'{key}: ERROR {exc}', file=sys.stderr, flush=True)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
