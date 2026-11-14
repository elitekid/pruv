#!/usr/bin/env python3
"""L3-1 A1 fixtures: text helpers and entry classification on py/rust, py/llvm, rs/rust, rs/llvm.

The oracle is independent of the Pruv code. It follows the TS rules of claude.ts/tail.ts with the policies of
docs/CLAUDE_IMPORT_SPEC.md: strict UTF-8 + strict JSON (last duplicate key wins, NaN/Infinity rejected, container
depth limit 128), lone surrogates in values become U+FFFD, explicit ECMAScript whitespace, one_line in UTF-16 units
with a scalar-safe cut, clip_bytes as the longest UTF-8 prefix (genuine U+FFFD kept), and dropped_user through
Python `re` over the replacement-decoded bytes. Inputs travel as decimal words (`v*k` repeats v k times); a
fixture line is `op a|bytes1|bytes2|bytes3`.
"""
import importlib.util
from itertools import groupby
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
JSON_DIR = HERE.parent / 'json'
WORK = HERE / 'work' / 'a1'

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
   "one_line" => sol::one_line_w(&w(1), a),
   "clip" => sol::clip_bytes_w(&w(1), a),
   "trim" => sol::trim_w(&w(1)),
   "blank" => sol::is_blank_w(&w(1)),
   "engine" => sol::engine_line_w(&w(1), a != 0),
   "space" => sol::space_len_w(&w(1), a),
   "dropped" => sol::dropped_user_w(&w(1)),
   "kind" => sol::line_kind_w(&w(1)),
   "sfield" => sol::string_field_w(&w(1), &w(2)),
   "ofield" => sol::object_field_w(&w(1), &w(2)),
   "istrue" => sol::is_true_w(&w(1), &w(2)),
   "origin" => sol::task_origin_w(&w(1)),
   "human" => sol::human_text_w(&w(1)),
   "pick" => sol::pick_title_w(&w(1), &w(2), &w(3)),
   "title" => sol::title_of_w(&w(1)),
   _ => panic!("unknown fixture"),
  };
  println!("{}", out.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(" "));
 }
}
'''


def enc(values):
    """Run-length word encoding of a byte sequence."""
    words = []
    for v, grp in groupby(values):
        k = len(list(grp))
        words.append(f'{v}*{k}' if k >= 4 else ' '.join([str(v)] * k))
    return ' '.join(w for w in words if w)


# ---------------- oracle ----------------
WS = ('\t\n\x0b\x0c\r \u00a0\u1680' + ''.join(map(chr, range(0x2000, 0x200B)))
      + '\u2028\u2029\u202f\u205f\u3000\ufeff')
WS_LIST = list(WS)
NEAR = [chr(c) for c in (0x180E, 0x200B, 0x200C, 0x200D, 0x2060, 0x0085, 0x1C, 0x1D, 0x1E, 0x1F, 0xFFFD, 0xA1,
                          0x3001, 0x2010, 0x202E, 0x205E, 0x2065, 0x1FFF, 0xFEFE, 0xFFFE)]
WS_RE = re.compile('[' + ''.join(re.escape(c) for c in WS) + ']+')
SC = '[' + ''.join(re.escape(c) for c in WS) + ']'
RE_USER = re.compile('"type"' + SC + '*:' + SC + '*"user"')
RE_META = re.compile('"isMeta"' + SC + '*:' + SC + '*true')
RE_SIDE = re.compile('"isSidechain"' + SC + '*:' + SC + '*true')
RE_TOOL = re.compile('"content"' + SC + '*:' + SC + r'*\[' + SC + r'*\{[^{}]*"type"' + SC + '*:' + SC + '*"tool_result"')


def es_trim(s):
    a, b = 0, len(s)
    while a < b and s[a] in WS:
        a += 1
    while b > a and s[b - 1] in WS:
        b -= 1
    return s[a:b]


def fix(s):
    """Policy P2: lone surrogates in values become U+FFFD (pairs were already merged by the JSON decoder)."""
    return ''.join('\ufffd' if 0xD800 <= ord(c) <= 0xDFFF else c for c in s)


def o_one_line(s, mx):
    t = es_trim(WS_RE.sub(' ', s))
    out, u = [], 0
    for c in t:
        w = 2 if ord(c) > 0xFFFF else 1
        if u + w > mx:
            break
        out.append(c)
        u += w
    return ''.join(out)


def o_clip(b, mx):
    if len(b) <= mx:
        return b
    return b[:mx].decode('utf-8', 'ignore').encode('utf-8')  # longest whole-scalar prefix; FFFD kept


def o_engine(text, origin):
    t = es_trim(text)
    if t in ('[Request interrupted by user]', '[Request interrupted by user for tool use]'):
        return True
    return (origin and len(t) >= 39 and t.startswith('<task-notification>') and t.endswith('</task-notification>'))


def o_dropped(head):
    s = head.decode('utf-8', errors='replace')
    return bool(RE_USER.search(s)) and not (RE_TOOL.search(s) or RE_META.search(s) or RE_SIDE.search(s))


def _bad_constant(name):
    raise ValueError(name)


class Obj(dict):
    """An object that remembers its depth over every member, duplicate keys included."""
    d = 1


def obj_hook(pairs):
    o = Obj(pairs)
    o.d = 1 + max([depth(x) for _, x in pairs], default=0)
    return o


def depth(v):
    if isinstance(v, Obj):
        return v.d
    if isinstance(v, dict):
        return 1 + max([depth(x) for x in v.values()], default=0)
    if isinstance(v, list):
        return 1 + max([depth(x) for x in v], default=0)
    return 0


def o_parse(line):
    try:
        text = line.decode('utf-8')
    except UnicodeDecodeError:
        return None
    try:
        v = json.loads(text, object_pairs_hook=obj_hook, parse_constant=_bad_constant)
    except (ValueError, RecursionError):
        return None
    if not isinstance(v, dict) or depth(v) > 128:
        return None
    return v


def S(v):
    return fix(v) if isinstance(v, str) else None


def o_task_origin(e):
    o = e.get('origin')
    return isinstance(o, dict) and o.get('kind') == 'task-notification'


def o_human(e):
    if e.get('type') != 'user' or e.get('isMeta') is True or e.get('isSidechain') is True:
        return None
    msg = e.get('message')
    content = msg.get('content') if isinstance(msg, dict) else None
    if isinstance(content, str):
        c = fix(content)
        return c if es_trim(c) and not o_engine(c, o_task_origin(e)) else None
    if not isinstance(content, list):
        return None
    pieces = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get('type') == 'tool_result':
            return None
        if block.get('type') == 'text' and isinstance(block.get('text'), str):
            pieces.append(fix(block['text']))
    joined = '\n\n'.join(pieces)
    return joined if es_trim(joined) and not o_engine(joined, o_task_origin(e)) else None


def o_pick(e, *keys):
    for k in keys:
        v = S(e.get(k))
        if v and es_trim(v):
            return v
    return None


def o_title(e):
    for kind, keys, rank in (('custom-title', ('customTitle', 'title'), 3), ('ai-title', ('aiTitle', 'title'), 2),
                             ('summary', ('summary', 'title'), 1)):
        if e.get('type') == kind:
            t = o_pick(e, *keys)
            return (rank, t) if t else None
    return None


def field_enc(v):
    return [1] if v is None else [0] + list(v.encode('utf-8'))


def space_at(b, at):
    if at < len(b) and 0x80 <= b[at] <= 0xBF:
        return 0  # not the start of a character
    ch =b[at:at + 4].decode('utf-8', 'ignore')[:1]
    return len(ch.encode()) if ch and ch in WS else 0


def oracle(op, a, w):
    if op in ('one_line', 'clip') and a < 0:
        return [-2]
    if op == 'space' and not 0 <= a <= len(w[0]):
        return [-2]
    if op == 'one_line':
        return [0] + list(o_one_line(w[0].decode('utf-8'), a).encode())
    if op == 'clip':
        return [0] + list(o_clip(w[0], a))
    if op == 'trim':
        return [0] + list(es_trim(w[0].decode('utf-8')).encode())
    if op == 'blank':
        return [1 if not es_trim(w[0].decode('utf-8')) else 0]
    if op == 'engine':
        return [1 if o_engine(w[0].decode('utf-8'), bool(a)) else 0]
    if op == 'space':
        return [space_at(w[0], a)]
    if op == 'dropped':
        return [1 if o_dropped(w[0]) else 0]
    e = o_parse(w[0])
    if op == 'kind':
        return [0] if e is not None else [1]
    if e is None:
        return [9, 0] if op == 'title' else [9]
    if op == 'sfield':
        return field_enc(S(e.get(w[1].decode('utf-8'))))
    if op == 'ofield':
        return [1] if isinstance(e.get(w[1].decode('utf-8')), dict) else [0]
    if op == 'istrue':
        return [1] if e.get(w[1].decode('utf-8')) is True else [0]
    if op == 'origin':
        return [1] if o_task_origin(e) else [0]
    if op == 'human':
        return field_enc(o_human(e))
    if op == 'pick':
        return field_enc(o_pick(e, w[1].decode('utf-8'), w[2].decode('utf-8')))
    if op == 'title':
        t = o_title(e)
        return [1, 0] if t is None else [0, t[0]] + list(t[1].encode('utf-8'))
    raise RuntimeError(op)


def selfcheck():
    """Hand-derived expectations that keep the oracle itself honest."""
    B = lambda s: list(s.encode())
    msg = lambda c: json.dumps({'type': 'user', 'message': {'content': c}}).encode()
    t = lambda s: {'type': 'text', 'text': s}
    checks = [
        (oracle('one_line', 120, [b'  a \t\n b  ']), [0] + B('a b')),
        (oracle('one_line', 2, [b'a   b']), [0] + B('a ')),
        (oracle('one_line', 2, ['a\U0001F600'.encode()]), [0] + B('a')),
        (oracle('one_line', 3, ['\U0001F600\U0001F600'.encode()]), [0] + B('\U0001F600')),
        (oracle('clip', 7, ['ab\u20ac\u20ac'.encode()]), [0] + B('ab\u20ac')),
        (oracle('clip', 7, ['ab\ufffd\ufffd'.encode()]), [0] + B('ab\ufffd')),
        (oracle('clip', 4, ['\u00e9\u00e9\u00e9'.encode()]), [0] + B('\u00e9\u00e9')),
        (oracle('engine', 0, [b' [Request interrupted by user] ']), [1]),
        (oracle('engine', 0, [b'<task-notification></task-notification>']), [0]),
        (oracle('engine', 1, [b'<task-notification></task-notification>']), [1]),
        (oracle('engine', 1, [b'<task-notification>']), [0]),
        (oracle('human', 0, [msg([t(''), t('a')])]), [0] + B('\n\na')),
        (oracle('human', 0, [msg([t(''), t('')])]), [1]),
        (oracle('human', 0, [msg([t('a'), {'type': 'tool_result'}])]), [1]),
        (oracle('human', 0, [msg('  hi ')]), [0] + B('  hi ')),
        (oracle('dropped', 0, [b'{"type" : "user"}']), [1]),
        (oracle('dropped', 0, [b'{"type":"user","isMeta":true}']), [0]),
        (oracle('dropped', 0, [b'{"type":"user","content":[{"type":"text"},{"type":"tool_result"}]}']), [1]),
        (oracle('dropped', 0, [b'{"type":"user","content":[{"a":"b","type":"tool_result"}]}']), [0]),
        (oracle('title', 0, [b'{"type":"summary","summary":" ","title":" x "}']), [0, 1] + B(' x ')),
        (oracle('space', 0, [b'\xe2\x80\x8b']), [0]),
        (oracle('space', 0, [b'\xe3\x80\x80']), [3]),
        (oracle('space', 1, ['é '.encode()]), [0]),
        (oracle('kind', 0, [b'{"a":' + b'[' * 128 + b'0' + b']' * 128 + b',"a":0}']), [1]),
    ]
    for i, (got, want) in enumerate(checks):
        if got != want:
            raise RuntimeError(f'oracle self-check {i}: {got!r} != {want!r}')


# ---------------- fixtures ----------------
def J(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def JA(obj):
    return json.dumps(obj, ensure_ascii=True, separators=(',', ':')).encode('ascii')


def T(s):
    return {'type': 'text', 'text': s}


def user(content, **extra):
    d = {'type': 'user', 'message': {'role': 'user', 'content': content}}
    d.update(extra)
    return d


INT1 = '[Request interrupted by user]'
INT2 = '[Request interrupted by user for tool use]'
OPEN, CLOSE = '<task-notification>', '</task-notification>'
TS_ORIGIN = {'kind': 'task-notification'}


def fixtures():
    cases = []

    def add(op, a=0, *w):
        ws = [x.encode() if isinstance(x, str) else bytes(x) for x in w] + [b''] * 3
        ws = ws[:3]
        cases.append((op, a, ws, oracle(op, a, ws)))

    # ---- whitespace: every ECMAScript space and near-misses ----
    for c in WS_LIST + NEAR:
        add('blank', 0, c)
        add('blank', 0, c * 3)
        add('blank', 0, c + 'x')
        add('blank', 0, 'x' + c)
        add('trim', 0, c + 'ab' + c + 'c' + c)
        add('trim', 0, c * 2)
        add('space', 0, c + 'x')
        add('space', len(c.encode()), c + 'x')
        add('one_line', 120, 'a' + c + c + 'b' + c)
        add('one_line', 120, c + 'a' + c)
    add('blank', 0, '')
    add('trim', 0, '')
    add('trim', 0, 'x')
    add('trim', 0, ''.join(WS_LIST) + 'mid dle' + ''.join(WS_LIST))
    add('space', 1, 'x')
    add('space', 0, '')
    add('space', 5, 'x')
    add('space', -1, 'x')
    # an index inside a character never starts a space
    add('space', 1, 'é ')
    add('space', 1, '　 ')
    add('space', 2, '　 ')
    add('space', 1, '\U0001F600 ')

    # ---- one_line ----
    for s, mx in [('', 120), ('   ', 120), ('a  b', 120), ('  a \t\n b  ', 120), ('a b c', 0), ('a b c', 1), ('a b c', 2),
                  ('a b c', 3), ('a b c', 4), ('a b c', 5), ('a     b', 2), ('a     b', 1), ('a\u3000\u3000b', 2),
                  ('\U0001F600' * 3, 1), ('\U0001F600' * 3, 2), ('\U0001F600' * 3, 3), ('\U0001F600' * 3, 4),
                  ('\U0001F600' * 3, 5), ('\U0001F600' * 3, 6), ('\U0001F600' * 3, 7), ('a\U0001F600', 1),
                  ('a\U0001F600', 2), ('a\U0001F600', 3), ('a \U0001F600', 2), ('a \U0001F600', 3), ('a \U0001F600', 4),
                  ('a' * 130, 120), ('a' * 119 + '\U0001F600', 120), ('a' * 118 + '\U0001F600', 120),
                  ('a' * 119 + '\U0001F600', 121), ('\u3042' * 200, 120), ('\u00e9\u20ac\U0001F600x', 5),
                  ('a ' * 100, 120), ('a ' * 100, 119), ('ab \ufffd cd', 4), ('x\ufffdy', 2),
                  ('line one\nline two\r\n\tline three', 120), ('a\u00a0\u2028b\ufeffc', 120)]:
        add('one_line', mx, s)
    add('one_line', -1, 'a')
    for mx in range(0, 12):
        add('one_line', mx, 'a \U0001F600 \u00e9 b')

    # ---- clip_bytes: UTF-8 cuts at 1/2/3/4-byte scalars, genuine U+FFFD ----
    for s in ['', 'abc', 'a\u00e9\u20ac\U0001F600', '\u00e9\u00e9\u00e9', '\u20ac\u20ac\u20ac', '\U0001F600' * 3, 'ab\ufffd',
              'ab\ufffd\ufffd', '\ufffd\ufffd\ufffd', 'a\ufffd\U0001F600\ufffd']:
        n = len(s.encode())
        for mx in sorted({0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, n - 1, n, n + 1} - {-1}):
            add('clip', mx, s)
    add('clip', 32768, '\u20ac' * 14000)
    add('clip', 32767, '\u20ac' * 14000)
    add('clip', 32768, '\U0001F600' * 9000)
    add('clip', 32767, '\U0001F600' * 9000)
    add('clip', 32768, '\u00e9' * 20000)
    add('clip', 32767, '\u00e9' * 20000)
    add('clip', 32768, 'a' * 32768)
    add('clip', 32768, 'a' * 32769)
    add('clip', -1, 'a')

    # ---- engine_line ----
    texts = [INT1, INT2, ' ' + INT1 + '\n', '\u3000' + INT2 + '\ufeff', INT1 + 'x', 'x' + INT1, INT1[:-1], INT2[:-1],
             INT1.lower(), '[Request interrupted by user for tool use ]', INT1 + INT1, INT1 + ' ' + INT1, '', ' ',
             INT1.replace(' ', '\u00a0'), '\u200b' + INT1, '\u0085' + INT1, INT1 + '\u180e', '\n\n' + INT1 + '\n\n',
             '[Request interrupted by user for tool  use]']
    notes = [OPEN + CLOSE, OPEN + 'x' + CLOSE, OPEN, CLOSE, OPEN + CLOSE[:-1], OPEN[:-1] + CLOSE, OPEN + CLOSE[1:],
             OPEN + '\n' + CLOSE, OPEN + '\n\n<a>b</a>\n\n' + CLOSE, ' \t' + OPEN + 'x' + CLOSE + '\n',
             'x' + OPEN + 'y' + CLOSE, OPEN + 'y' + CLOSE + 'z', OPEN + 'a' + CLOSE + 'b' + CLOSE, OPEN + OPEN + CLOSE,
             OPEN + CLOSE + CLOSE, OPEN[:-2] + CLOSE[2:], OPEN + '/' + CLOSE[1:], '\u3000' + OPEN + CLOSE + '\u3000',
             OPEN.upper() + CLOSE.upper(), OPEN + 'x' * 5000 + CLOSE, OPEN + CLOSE + '\u200b', '\u200b' + OPEN + CLOSE]
    for t in texts + notes:
        for flag in (0, 1):
            add('engine', flag, t)

    # ---- dropped_user ----
    def drop(raw):
        add('dropped', 0, raw)

    base = b'{"parentUuid":null,"type":"user","message":{"role":"user","content":"hello"}}'
    drop(base)
    drop(b'')
    drop(b'{}')
    drop(b'{"type":"assistant"}')
    drop(b'{"type":"user"}')
    drop(b'{"type" : "user"}')
    drop(b'{"type"\t:\n"user"}')
    drop(b'{"type":"users"}')
    drop(b'{"type":"user')
    drop(b'{"type":"us')
    drop(b'"type":"user"')
    drop(b'"type"')
    drop(b'"')
    drop(b'{"t\\u0079pe":"user"}')
    drop(b'{"type":"\\u0075ser"}')
    drop(b'{"type":"User"}')
    drop(b'{"Type":"user"}')
    drop(b"{'type':'user'}")
    drop(b'{"type": "user" "type"}')
    for c in WS_LIST:
        e = c.encode()
        drop(b'{"type"' + e + b':' + e + b'"user"}')
        drop(b'{"type"' + e + e + b':' + e * 3 + b'"user"}')
        drop(b'{"type":"user","isMeta"' + e + b':' + e + b'true}')
        drop(b'{"type":"user","isSidechain"' + e + b':' + e + b'true}')
        drop(b'{"type":"user","content"' + e + b':' + e + b'[' + e + b'{' + b'"type":"tool_result"}')
    for c in NEAR:
        e = c.encode()
        drop(b'{"type"' + e + b':"user"}')
        drop(b'{"type":' + e + b'"user"}')
        drop(b'{"type":"user","isMeta"' + e + b':true}')
        drop(b'{"type":"user","isMeta":' + e + b'true}')
        drop(b'{"type":"user","content":[' + e + b'{"type":"tool_result"}')
        drop(b'{"type":"user","content":' + e + b'[{"type":"tool_result"}')
    for pre in (b'\xff', b'\xc3', b'\xe2\x80', b'\xe2', b'\xf0\x9f\x98', b'\x80', b'\xed\xa0\x80'):
        drop(b'{"type"' + pre + b':"user"}')
        drop(b'{"type":' + pre + b'"user"}')
        drop(b'{"type"' + pre + b'\xe3\x80\x80:"user"}')   # an invalid prefix before a valid U+3000
        drop(b'{"type":"user"}' + pre)
        drop(b'{"type":"user","isMeta":true' + pre)
        drop(b'{"type":"user","content":[' + pre + b'{' + pre + b'"type":"tool_result"}')
        drop(b'{"type":"user"' + pre + b'}')
    drop(b'{"type":"user","isMeta":true}')
    drop(b'{"type":"user","isMeta":"true"}')
    drop(b'{"type":"user","isMeta":false}')
    drop(b'{"type":"user","isMeta":truex}')
    drop(b'{"type":"user","isMeta":tru}')
    drop(b'{"type":"user","isMeta": True}')
    drop(b'{"isMeta":true,"type":"user"}')
    drop(b'{"type":"user","isSidechain":true}')
    drop(b'{"type":"user","isSidechain":false,"isMeta":false}')
    drop(b'{"type":"user","isSidechain" : true , "isMeta":false}')
    drop(b'{"type":"user","message":{"isMeta":true}}')
    drop(b'{"type":"user","x":"\\"isMeta\\":true"}')
    drop(b'{"type":"user","x":"\\"isMeta\\"\\n:true"}')
    drop(b'{"type":"user","isMeta":\n\ttrue}')
    # tool_result veto and the brace-free span
    drop(b'{"type":"user","message":{"content":[{"type":"tool_result","content":"x"}]}}')
    drop(b'{"type":"user","message":{"content":[{"tool_use_id":"t","type":"tool_result"}]}}')
    drop(b'{"type":"user","message":{"content":[{"type":"text","text":"a"},{"type":"tool_result"}]}}')
    drop(b'{"type":"user","message":{"content":[{"type":"text","text":"a"}],"x":[{"type":"tool_result"}]}}')
    drop(b'{"type":"user","message":{"content":[{"a":{"type":"tool_result"}}]}}')
    drop(b'{"type":"user","message":{"content":[{"a":[],"type":"tool_result"}]}}')
    drop(b'{"type":"user","message":{"content":[{"a":"}","type":"tool_result"}]}}')
    drop(b'{"type":"user","message":{"content":[{"a":"{","type":"tool_result"}]}}')
    drop(b'{"type":"user","message":{"content":[{"a":"x\ny\n","type":"tool_result"}]}}')
    drop(b'{"type":"user","message":{"content" : [ \n { "x": 1,\n "type" : "tool_result" }]}}')
    drop(b'{"type":"user","message":{"content":[{"type":"tool_resul"}]}}')
    drop(b'{"type":"user","message":{"content":[{"type":"tool_results"}]}}')
    drop(b'{"type":"user","message":{"content":[{"type":"tool_result')
    drop(b'{"type":"user","message":{"content":[{"type":"tool')
    drop(b'{"type":"user","message":{"content":[{')
    drop(b'{"type":"user","message":{"content":[')
    drop(b'{"type":"user","message":{"content":{"type":"tool_result"}}}')
    drop(b'{"type":"user","message":{"content":"[{\\"type\\":\\"tool_result\\"}]"}}')
    drop(b'{"type":"user","message":{"content":[{"type":"text"}],"content":[{"type":"tool_result"}]}}')
    drop(b'{"content":[{"type":"tool_result"}],"type":"user"}')
    drop(b'{"content":[{"type":"tool_result"}]')
    drop(b'{"type":"user","message":{"content":[{"type":"text","text":"{"},{"type":"tool_result"}]}}')
    drop(b'{"type":"user","message":{"content":[{"type":"text","text":"x"},{"type":"tool_result"}]}}'.replace(b'},{', b','))
    # raw-prefix false positives: nested and later fields still count
    drop(b'{"type":"assistant","message":{"role":{"type":"user"}}}')
    drop(b'{"type":"assistant","x":"\\"type\\":\\"user\\""}')
    drop(b'{"type":"assistant","x":"\\"type\\":\\"user\\"","y":{"type":"user"}}')
    drop(b'{"type":"assistant","message":{"content":[{"type":"text","text":"{\\"type\\": \\"user\\"}"}]}}')
    drop(b'{"type":"assistant","message":{"content":[{"type":"tool_result"},{"type":"user"}]}}')
    drop(b'{"type":"user","isMeta":true,"type":"user"}')
    # long spans and the 8 KiB prefix edges
    drop(b'{"type"' + b' ' * 8000 + b':"user"}')
    drop(b'{"type"' + b' ' * 8000 + b':' + b' ' * 100 + b'"user"}')
    drop(b'{"type"' + '\u3000'.encode() * 2700 + b':"user"}')
    drop(b'{"type"' + '\u3000'.encode() * 2700 + b'x:"user"}')
    drop(b'a' * 8150 + b'{"type":"user"}')
    drop(b'a' * 8180 + b'{"type":"user')
    drop(b'{"x":"' + b'a' * 8100 + b'","type":"user"}')
    drop(b'{"type":"user","x":"' + b'a' * 8100 + b'","isMeta":true}')
    drop(b'{"type":"user","message":{"content":[{"x":"' + b'a' * 8100 + b'","type":"tool_result"}]}}')
    drop(b'{"type":"user","message":{"content":[{"x":"' + b'a\n' * 4000 + b'","type":"tool_result"}]}}')
    drop(b'{"type":"user","message":{"content":[{"x":"' + b'a ' * 4000 + b'"}]}}')
    drop(b'{"content":[{' * 600 + b'"type":"user"}')
    drop(b'{"content":[{' * 300 + b'"type":"tool_result"}' + b'"type":"user"')
    drop(b'"content":[{"x":1 ' * 300 + b'"type":"user"')
    drop(b'"content":[{ ' * 300 + b'"type":"tool_result","type":"user"')
    drop(b'"type":"user"' * 50)
    drop((b'"type":"user"' * 50)[:-1])
    drop(b'\xe2\x80\xa8"type"\xe2\x80\xa8:\xe2\x80\xa8"user"\xe2\x80\xa8')
    drop(b'"type"\xef\xbb\xbf:\xef\xbb\xbf"user"')
    drop(b'"type"\xef\xbb:"user"')
    drop(b'"type"\xe2\x80\x8a:"user"')
    drop(b'"type"\xe2\x80\x8b:"user"')
    drop(b'"type"\xc2\xa0:"user"')
    drop(b'"type"\xc2\x85:"user"')
    drop(b'"type"\xe1\xa0\x8e:"user"')
    drop(b'"type":"user" "isMeta"\xe2\x80\xafmore')
    drop(b'"type":"user" "isMeta"\xe2\x80\xaf:\xe2\x80\xaftrue')
    drop(b'"isSidechain"\xe2\x81\x9f:\xe2\x81\x9ftrue "type":"user"')
    drop(b'"content"\xe1\x9a\x80:\xe1\x9a\x80[\xe1\x9a\x80{\xe1\x9a\x80"type"\xe1\x9a\x80:\xe1\x9a\x80"tool_result" "type":"user"')

    # ---- entry: non-object lines, malformed JSON, parse limits ----
    bad = [b'', b' ', b'\t\r', b'[1]', b'[]', b'"str"', b'123', b'null', b'true', b'{', b'}', b'{"a":1,}', b'{"a":}',
           b'{"a" 1}', b"{'a':1}", b'{"a":1} x', b'{"a":1}{"b":2}', b'\xef\xbb\xbf{}', b'\xff', b'{"type":"user"\xff}',
           b'{"type":"user","message":{"content":"a\xffb"}}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":-Infinity}',
           b'{"a":01}', b'{"a":1.}', b'{"a":.5}', b'{"a":"\x01"}', b'{"a":"\\x"}', b'{"a":"\\u12"}', b'{"a":"abc',
           b'{"type":"user","message":{"content":"x"}', b'\xed\xa0\x80', b'{"a":"\xed\xa0\x80"}', b'{"a":"\xc0\x80"}',
           b'{"a":"\xf4\x90\x80\x80"}', b'{"a":tru}', b'{"a":nul}', b'{"a":[1,]}', b'{"a":[1 2]}', b'{"a"}',
           b'{,}', b'{"a":1,,"b":2}', b'{"a":"\n"}']
    for line in bad:
        add('kind', 0, line)
        add('human', 0, line)
        add('title', 0, line)
        add('origin', 0, line)
    good = [b'{}', b' {} ', b'\t{"a":1}\r', b'{"a":{"b":[1,2,{"c":null}]}}', J(user('x')), b'{"a":1e999}', b'{"a":-0}',
            b'{"a":"\\ud800"}', b'{"\\u0074ype":"user"}']
    for line in good:
        add('kind', 0, line)
    for d in (126, 127, 128, 129, 130):
        add('kind', 0, b'{"x":' * d + b'0' + b'}' * d)
        add('human', 0, b'{"type":"user","message":{"content":"a"},"x":' + b'{"x":' * (d - 1) + b'0' + b'}' * d)
    add('kind', 0, b'{"a":' + b'[' * 127 + b']' * 127 + b'}')
    add('kind', 0, b'{"a":' + b'[' * 128 + b']' * 128 + b'}')
    add('kind', 0, b'{"a":[' + b'0,' * 5000 + b'0]}')
    # depth counts a duplicate key's earlier value even though the later value wins
    add('kind', 0, b'{"a":' + b'[' * 128 + b'0' + b']' * 128 + b',"a":0}')
    add('kind', 0, b'{"a":' + b'[' * 127 + b'0' + b']' * 127 + b',"a":0}')
    add('human', 0, b'{"type":"user","message":{"content":"a"},"a":' + b'[' * 128 + b'0' + b']' * 128 + b',"a":0}')

    # ---- entry: field helpers ----
    keys = [b'a', b'', b'type', b'\xc3\xa9', '\U0001F600'.encode(), b'A', b'a b', b'ab']
    docs = [b'{"a":"s"}', b'{"a":""}', b'{"a":1}', b'{"a":null}', b'{"a":true}', b'{"a":false}', b'{"a":[]}', b'{"a":{}}',
            b'{"b":"s"}', b'{}', b'{"a":"1","a":2}', b'{"a":2,"a":"1"}', b'{"\\u0061":"esc"}', b'{"a":"x","\\u0061":"y"}',
            b'{"":"empty key"}', b'{"type":"t"}', b'{"t\\u0079pe":"esc"}', b'{"\xc3\xa9":"e1"}', b'{"\\u00e9":"e2"}',
            '{"\U0001F600":"astral"}'.encode(), b'{"\\ud83d\\ude00":"pair"}', b'{"a b":"sp","ab":"nosp"}',
            b'{"a":{"a":"nested"}}', b'{"x":{"a":"nested"},"a":"top"}', b'{"a":"\\ud800"}', b'{"a":"\\udc00x"}',
            b'{"a":"\\ud83d\\ude00"}', b'{"a":"\\ud83d","b":"\\ude00"}', b'{"a":"\\ud83dx\\ude00"}',
            b'{"a":"\\ude00\\ud83d"}', b'{"a":"\\ud800\\ud83d\\ude00"}', b'{"a":"\\u0000nul"}', b'{"a":"line\\nbreak"}',
            b'{"a":"\xf0\x9f\x98\x80 raw"}', b'{"a":"\\/\\"\\\\"}']
    for doc in docs:
        for key in keys:
            add('sfield', 0, doc, key)
            add('ofield', 0, doc, key)
            add('istrue', 0, doc, key)
    for doc in [b'{"isMeta":true}', b'{"isMeta":false}', b'{"isMeta":"true"}', b'{"isMeta":1}', b'{"isMeta":null}',
                b'{"isMeta":[true]}', b'{"isMeta":{"a":true}}', b'{"isMeta":true,"isMeta":false}',
                b'{"isMeta":false,"isMeta":true}', b'{"is\\u004deta":true}', b'{"x":{"isMeta":true}}', b'{}',
                b'{"isMeta":"\\u0074rue"}', b'{"isMeta":TRUE}', b'{"isMeta":True}']:
        add('istrue', 0, doc, b'isMeta')
        add('istrue', 0, doc, b'isSidechain')

    # ---- entry: task origin ----
    for origin in [TS_ORIGIN, {'kind': 'other'}, {'kind': 'task-notification '}, {'kind': 'Task-Notification'},
                   {'kind': 1}, {'kind': None}, {'kind': ['task-notification']}, {'kind': {'k': 'task-notification'}},
                   {}, {'k': 'task-notification'}, 'task-notification', ['task-notification'], None, 1, True,
                   {'kind': 'x', 'k2': 1}, {'kind': 'other', 'kind ': 'task-notification'}]:
        add('origin', 0, J({'type': 'user', 'origin': origin}))
    add('origin', 0, b'{"origin":{"kind":"task-notification","kind":"x"}}')
    add('origin', 0, b'{"origin":{"kind":"x","kind":"task-notification"}}')
    add('origin', 0, b'{"origin":{"kind":"task-notification"},"origin":null}')
    add('origin', 0, b'{"origin":null,"origin":{"kind":"task-notification"}}')
    add('origin', 0, b'{"orig\\u0069n":{"k\\u0069nd":"task-\\u006eotification"}}')
    add('origin', 0, b'{}')

    # ---- entry: human_text ----
    h = lambda obj: add('human', 0, J(obj))
    ha = lambda obj: add('human', 0, JA(obj))
    # type and flag kinds
    for tp in ['user', 'assistant', 'User', 'USER', ' user', 'user ', '', None, 1, True, ['user'], {'a': 'user'}]:
        h({'type': tp, 'message': {'content': 'hi'}})
    h({'message': {'content': 'hi'}})
    for flag in [True, False, 'true', 'false', 'True', '', 1, 0, None, [True], {'a': True}, 'yes']:
        h(user('hi', isMeta=flag))
        h(user('hi', isSidechain=flag))
        h(user('hi', isMeta=flag, isSidechain=flag))
    add('human', 0, b'{"type":"user","isMeta":true,"isMeta":false,"message":{"content":"x"}}')
    add('human', 0, b'{"type":"user","isMeta":false,"isMeta":true,"message":{"content":"x"}}')
    add('human', 0, b'{"type":"user","isMeta":"true","isSidechain":false,"message":{"content":"x"}}')
    add('human', 0, b'{"type":"user","isMeta":true,"isSidechain":false,"message":{"content":"x"}}')
    add('human', 0, b'{"type":"user","isMeta":false,"isSidechain":true,"message":{"content":"x"}}')
    # duplicate and escaped keys
    add('human', 0, b'{"type":"assistant","type":"user","message":{"content":"dup"}}')
    add('human', 0, b'{"type":"user","type":"assistant","message":{"content":"dup"}}')
    add('human', 0, b'{"t\\u0079pe":"user","message":{"content":"esc"}}')
    add('human', 0, b'{"type":"user","m\\u0065ssage":{"c\\u006fntent":"esc2"}}')
    add('human', 0, b'{"type":"u\\u0073er","message":{"content":"escval"}}')
    add('human', 0, b'{"type":"user","message":{"content":"a"},"message":{"content":"b"}}')
    add('human', 0, b'{"type":"user","message":{"content":"a"},"message":"b"}')
    add('human', 0, b'{"type":"user","message":"b","message":{"content":"a"}}')
    add('human', 0, b'{"type":"user","message":{"content":"a","content":"b"}}')
    add('human', 0, b'{"type":"user","message":{"content":"a","content":["x"]}}')
    add('human', 0, b'{"type":"user","message":{"content":["x"],"content":"a"}}')
    add('human', 0, b'{"type":"user","message":{"content":[{"type":"text","text":"a"}],"content":[{"type":"tool_result"}]}}')
    add('human', 0, b'{"type":"user","message":{"content":[{"type":"tool_result"}],"content":[{"type":"text","text":"a"}]}}')
    # message and content kinds
    for msg in [None, 'text', 1, True, [], [{'content': 'x'}], {}, {'content': None}, {'content': 1}, {'content': True},
                {'content': {'type': 'text', 'text': 'a'}}, {'text': 'a'}, {'role': 'user'}, {'content': 'ok'}]:
        h({'type': 'user', 'message': msg})
    h({'type': 'user'})
    h({'type': 'user', 'content': 'top level'})
    # string content
    for c in ['hello', '  hello  ', '', ' ', '\u3000\n\t', '\ufeff', '\u200b', '\u180e', '\u0085', 'a\nb', '\n\nx\n\n',
              INT1, INT2, ' ' + INT1 + ' ', '\n' + INT2 + '\u3000', INT1 + 'x', INT1.lower(), 'x ' + INT1,
              OPEN + CLOSE, OPEN + 'x' + CLOSE, ' ' + OPEN + 'x' + CLOSE + ' ', 'x' + OPEN + 'y' + CLOSE,
              OPEN + 'y' + CLOSE + 'z', OPEN, CLOSE, '\U0001F600', 'caf\u00e9', '[Request interrupted by user]\n\nx']:
        h(user(c))
        h(user(c, origin=TS_ORIGIN))
        h(user(c, origin={'kind': 'task-notification-x'}))
        h(user(c, origin='task-notification'))
    for origin in [None, 1, [], {}, {'kind': 1}, {'kind': None}, {'kind': 'Task-Notification'}]:
        h(user(OPEN + 'x' + CLOSE, origin=origin))
        h(user([T(OPEN + 'x' + CLOSE)], origin=origin))
    # array content
    h(user([]))
    h(user([T('a')]))
    h(user([T('a'), T('b')]))
    h(user([T('a'), T('b'), T('c')]))
    h(user([T(''), T('a')]))
    h(user([T('a'), T('')]))
    h(user([T(''), T('')]))
    h(user([T(''), T(''), T('')]))
    h(user([T(' '), T(' ')]))
    h(user([T('\n'), T('x'), T('\n')]))
    h(user([T('  a  '), T(' b ')]))
    h(user([T('\u3000'), T('\ufeff')]))
    h(user([T('a\n\n'), T('\n\nb')]))
    h(user([T(INT1)]))
    h(user([T(INT2)]))
    h(user([T(INT1), T('')]))
    h(user([T(''), T(INT1)]))
    h(user([T(INT1), T(INT1)]))
    h(user([T(INT1), T('x')]))
    h(user([T(' ' + INT1 + ' ')]))
    h(user([T(OPEN), T(CLOSE)], origin=TS_ORIGIN))
    h(user([T(OPEN), T(CLOSE)]))
    h(user([T(OPEN + 'x'), T(CLOSE)], origin=TS_ORIGIN))
    h(user([T(OPEN + CLOSE)], origin=TS_ORIGIN))
    h(user([T(OPEN + CLOSE)]))
    h(user([T(OPEN), T('')], origin=TS_ORIGIN))
    h(user([T(OPEN[:-1]), T(CLOSE)], origin=TS_ORIGIN))
    h(user([T('x'), T(OPEN + 'y' + CLOSE)], origin=TS_ORIGIN))
    h(user([T(OPEN + 'y' + CLOSE), T('x')], origin=TS_ORIGIN))
    # wrong kinds inside arrays
    for blk in [None, 'text', 1, True, [], [T('a')], {}, {'text': 'a'}, {'type': 'text'}, {'type': 'text', 'text': None},
                {'type': 'text', 'text': 1}, {'type': 'text', 'text': ['a']}, {'type': 'text', 'text': {'a': 1}},
                {'type': 'image', 'text': 'a'}, {'type': 'Text', 'text': 'a'}, {'type': ['text'], 'text': 'a'},
                {'type': 'tool_use', 'id': 'x', 'text': 'a'}, {'type': 'thinking', 'thinking': 'a'},
                {'type': 'text', 'text': 'z', 'extra': {'type': 'tool_result'}},
                {'type': 'text', 'text': 'z', 'content': [{'type': 'tool_result'}]},
                {'type': 'tool_use_result', 'text': 'a'}, {'type': 'tool_results'}, {'type': 'tool_result '},
                {'type': None}, {'type': 1}, {'type': True}, {'type': {'k': 'tool_result'}}, {'type': ['tool_result']}]:
        h(user([blk]))
        h(user([T('a'), blk]))
        h(user([blk, T('a')]))
        h(user([T('a'), blk, T('b')]))
    # tool_result at first, middle and last positions
    TR = {'type': 'tool_result', 'tool_use_id': 'x', 'content': 'out'}
    h(user([TR]))
    h(user([TR, T('a')]))
    h(user([T('a'), TR]))
    h(user([T('a'), TR, T('b')]))
    h(user([T('a'), T('b'), TR]))
    h(user([TR, TR]))
    h(user([T('a'), {'type': 'image'}, TR, 5, None]))
    h(user([None, 5, 'str', [TR], T('a')]))
    h(user([None, 5, 'str', [TR], {'x': TR}, T('a')]))
    h(user([T('x')] * 40 + [TR] + [T('y')] * 40))
    h(user([T('x')] * 80 + [TR]))
    h(user([TR] + [T('x')] * 80))
    h(user([T('x')] * 80))
    h(user([T(str(i)) for i in range(300)]))
    h(user([{'type': 'image', 'source': {'type': 'base64', 'data': 'abc'}}, T('look')]))
    h(user([{'type': 'tool_result', 'content': [{'type': 'text', 'text': 'inner'}]}]))
    h(user([{'type': 'text', 'text': 'x', 'a': [1, 2, {'b': [{'type': 'tool_result'}]}]}, T('y')]))
    h(user([{'a': [1, 2, [3, [4]]], 'type': 'text', 'text': 'deep'}, {'z': {'y': {'x': 1}}}, T('after')]))
    add('human', 0, b'{"type":"user","message":{"content":[{"type":"tool_result","type":"text","text":"a"}]}}')
    add('human', 0, b'{"type":"user","message":{"content":[{"type":"text","type":"tool_result","text":"a"}]}}')
    add('human', 0, b'{"type":"user","message":{"content":[{"type":"text","text":"a","text":"b"}]}}')
    add('human', 0, b'{"type":"user","message":{"content":[{"type":"text","text":"a","text":5}]}}')
    add('human', 0, b'{"type":"user","message":{"content":[{"type":"text","text":5,"text":"b"}]}}')
    add('human', 0, b'{"type":"user","message":{"content":[{"t\\u0079pe":"tool_result"},{"type":"text","text":"a"}]}}')
    add('human', 0, b'{"type":"user","message":{"content":[{"type":"t\\u0065xt","te\\u0078t":"esc"}]}}')
    add('human', 0, b'{"type":"user","message":{"content":[{"type":"tool_\\u0072esult"}]}}')
    add('human', 0, b'{"type":"user","message":{"content":[{"type":"text","text":"a"}, {"type" : "text" , "text" : "b"} ]}}')
    # surrogates and Unicode text
    add('human', 0, b'{"type":"user","message":{"content":"\\ud800"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\udc00"}}')
    add('human', 0, b'{"type":"user","message":{"content":"a\\ud83d"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\ude00\\ud83d"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\ud83d\\ude00"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\ud83d\\ud83d\\ude00"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\ud83d x \\ude00"}}')
    add('human', 0, b'{"type":"user","message":{"content":[{"type":"text","text":"\\ud800"},{"type":"text","text":"\\udc00"}]}}')
    add('human', 0, b'{"type":"user","message":{"content":[{"type":"text","text":"\\ud83d"},{"type":"text","text":"\\ude00"}]}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\ud800 "}}')
    add('human', 0, b'{"type":"user","message":{"content":" \\ud800"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\u2028\\u2029\\u00a0"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\u2028x\\u2029"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\u0000"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\u0000x"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\u001f"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\u00a0\\u1680\\u2000\\u200a\\u202f\\u205f\\u3000\\ufeff"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\u180e"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\u200b\\u0085"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\ufffd"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\n\\r\\t\\f\\b"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\b"}}')
    add('human', 0, b'{"type":"user","message":{"content":"\\u005b\\u0052equest interrupted by user]"}}')
    for c in ['caf\u00e9 \u20ac \U0001F600 \u3042', '\U0001F600' * 50, 'x' * 5000, '\u3042' * 3000]:
        h(user(c))
        h(user([T(c), T(c)]))
        ha(user(c))
    ha(user('a\U0001F600\u00e9'))
    ha(user([T('a\U0001F600'), T('\u00e9\u20ac')]))

    # ---- entry: titles ----
    def ti(**kw):
        add('title', 0, J(kw))

    for tp, keys3 in [('custom-title', ('customTitle', 'title')), ('ai-title', ('aiTitle', 'title')), ('summary', ('summary', 'title'))]:
        k1, k2 = keys3
        ti(type=tp, **{k1: 'First'})
        ti(type=tp, **{k2: 'Second'})
        ti(type=tp, **{k1: 'First', k2: 'Second'})
        ti(type=tp, **{k1: '', k2: 'Second'})
        ti(type=tp, **{k1: ' \t\n', k2: 'Second'})
        ti(type=tp, **{k1: '\u3000\ufeff\u00a0', k2: 'Second'})
        ti(type=tp, **{k1: '\u200b', k2: 'Second'})
        ti(type=tp, **{k1: '\u180e', k2: 'Second'})
        ti(type=tp, **{k1: None, k2: 'Second'})
        ti(type=tp, **{k1: 5, k2: 'Second'})
        ti(type=tp, **{k1: True, k2: 'Second'})
        ti(type=tp, **{k1: ['x'], k2: 'Second'})
        ti(type=tp, **{k1: {'a': 'x'}, k2: 'Second'})
        ti(type=tp, **{k1: 'First', k2: None})
        ti(type=tp, **{k1: '', k2: ''})
        ti(type=tp, **{k1: ' ', k2: '\n'})
        ti(type=tp, **{k1: None, k2: None})
        ti(type=tp, **{k1: 5, k2: 5})
        ti(type=tp, **{k1: '  padded  '})
        ti(type=tp, **{k1: '', k2: '  padded2  '})
        ti(type=tp, **{k1: '\n\tx\u3000y\n', k2: 'z'})
        ti(type=tp)
        ti(type=tp, other='x', ignored={'title': 'nested'})
        ti(type=tp, isMeta=True, **{k1: 'meta'})
        ti(type=tp, isSidechain=True, **{k1: 'side'})
        ti(type=tp, **{k1: 'L' * 5000})
        ti(type=tp, **{k1: 'caf\u00e9 \U0001F600'})
        add('title', 0, ('{"type":"%s","%s":"a","%s":"b"}' % (tp, k1, k1)).encode())
        add('title', 0, ('{"type":"%s","%s":"b","%s":"a"}' % (tp, k1, k1)).encode())
        add('title', 0, ('{"type":"%s","%s":"a","%s":5}' % (tp, k1, k1)).encode())
        add('title', 0, ('{"type":"%s","%s":5,"%s":"a"}' % (tp, k1, k1)).encode())
        add('title', 0, ('{"type":"%s","%s":"a","%s":""}' % (tp, k1, k1)).encode())
        add('title', 0, ('{"type":"%s","%s":"","%s":"a"}' % (tp, k1, k1)).encode())
        add('title', 0, ('{"type":"%s","%s":"\\ud800"}' % (tp, k1)).encode())
        add('title', 0, ('{"type":"%s","%s":"\\ud83d\\ude00"}' % (tp, k1)).encode())
        add('title', 0, ('{"type":"%s","%s":" ","%s":"\\udc00"}' % (tp, k1, k2)).encode())
        add('title', 0, ('{"type":"%s","%s":"\\u0020\\u0020"}' % (tp, k1)).encode())
        add('title', 0, ('{"%s":"x","type":"%s"}' % (k1, tp)).encode())
        add('title', 0, ('{"ty\\u0070e":"%s","%s":"esc"}' % (tp, k1)).encode())
        add('title', 0, ('{"type":"%s","%s":"esc"}' % (tp.replace('-', '\\u002d').replace('s', '\\u0073'), k1)).encode())
        add('title', 0, ('{"type":"%s","%s":"esc"}' % (tp, k1[:2] + '\\u' + '%04x' % ord(k1[2]) + k1[3:])).encode())
        add('title', 0, ('{"type":"other","type":"%s","%s":"dup"}' % (tp, k1)).encode())
        add('title', 0, ('{"type":"%s","type":"other","%s":"dup"}' % (tp, k1)).encode())
    # cross-type keys and wrong type values
    ti(type='custom-title', aiTitle='x', summary='y')
    ti(type='ai-title', customTitle='x', summary='y')
    ti(type='summary', customTitle='x', aiTitle='y')
    ti(type='ai-title', title='fallback', customTitle='no')
    ti(type='summary', title='fallback', aiTitle='no')
    ti(type='custom-title', title='fallback', aiTitle='no')
    for tp in ['Custom-Title', 'custom_title', 'customTitle', 'custom-title ', ' summary', 'SUMMARY', 'title', '', 'user',
               'assistant', None, 1, True, ['summary'], {'a': 'summary'}]:
        ti(type=tp, customTitle='x', aiTitle='y', summary='z', title='w')
    ti(customTitle='x', aiTitle='y', summary='z', title='w')
    ti()

    # ---- pick_title with explicit keys ----
    for doc in [b'{"a":"x","b":"y"}', b'{"a":"","b":"y"}', b'{"a":" ","b":"y"}', b'{"a":"\\u3000","b":"y"}', b'{"a":"\\u200b","b":"y"}',
                b'{"a":5,"b":"y"}', b'{"a":null,"b":" y "}', b'{"a":"x","b":5}', b'{"b":"y"}', b'{"a":"x"}', b'{}',
                b'{"a":"x","a":"z","b":"y"}', b'{"a":" ","a":"z","b":"y"}', b'{"a":"z","a":" ","b":"y"}',
                b'{"a":"\\ud800","b":"y"}', b'{"a":" ","b":"\\ud800"}', b'{"a":["x"],"b":{"c":"y"}}']:
        add('pick', 0, doc, b'a', b'b')
        add('pick', 0, doc, b'a', b'a')
        add('pick', 0, doc, b'b', b'a')
        add('pick', 0, doc, b'a', b'zz')
        add('pick', 0, doc, b'zz', b'b')
        add('pick', 0, doc, b'', b'a')
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
                compiled = g2.compile_pruv(compiler, str(HERE / 'a1_root.pruv'), str(work), backend, flags)
                if compiled['rc'] != 0:
                    raise RuntimeError('compile/verify failed: ' + str(compiled['errors'] or compiled['stderr']))
                print(f'{key}: verified and compiled', flush=True)
                harness = work / 'main.rs'
                harness.write_text(HARNESS.replace('@SOL@', compiled['rs']))
                extra = []
                if compiled['ll']:
                    extra, error = g2.build_llvm_objects(compiled['ll'], 'a1', str(work))
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
                    print(f'{key}: fixture {i} {op} {a} {ws[0][:60]!r}: expected {w[:200]}, got {g[:200]}')
                failed |= bool(bad)
                print(f'{key}: {len(cases) - len(bad)}/{len(cases)} fixtures passed', flush=True)
            except Exception as exc:
                failed = True
                print(f'{key}: ERROR {exc}', file=sys.stderr, flush=True)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
