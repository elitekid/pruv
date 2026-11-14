#!/usr/bin/env python3
"""L3-1 A4 fixtures: the complete pure API (head_packet, tail_packet, window_packet of a4_root.pruv) on
py/rust, py/llvm, rs/rust, rs/llvm.

Fixed end-to-end transcripts: malformed middle lines, dropped (oversized) users, synthetic/error assistants, a model
without a current draft, tools-only replies, head/tail/window disagreement, option presence, caps and policy cases.
Expected packets come from oracle.py (independent Python oracle; reuses the A1-A3 oracles; no Pruv code, no TS).
The same fixtures are written to work/a4/fixtures.json (data as base64, expected packet as ints) for reference.mjs,
which runs the verbatim TS logic under Node/Electron and compares the projected results.

Fixture line: `op flag|bytes`, bytes as decimal words (`v*k` repeats v k times); op head|tail|window, flag cut_after
(head) or cut_before (tail, window). Result words are compared run-length encoded.

Flags and TS comparability: with a cut flag the TS file reader only reproduces the selection when the data has exactly
the edge/window size (the host cuts at size - limit). A flagged fixture is therefore padded with whitespace to that size:
head appends spaces to the (discarded) unterminated end, tail/window prepend spaces to the (discarded) first range.
"""
import base64
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
JSON_DIR = HERE.parent / 'json'
WORK = HERE / 'work' / 'a4'

_spec = importlib.util.spec_from_file_location('l3_oracle', HERE / 'oracle.py')
oracle = importlib.util.module_from_spec(_spec)
sys.modules['l3_oracle'] = oracle
_spec.loader.exec_module(oracle)
a1, a2, a3 = oracle.a1, oracle.a2, oracle.a3

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
fn rle(v: &[i64]) -> String {
 let mut parts: Vec<String> = Vec::new();
 let mut i = 0;
 while i < v.len() {
  let mut j = i;
  while j < v.len() && v[j] == v[i] { j += 1; }
  let k = j - i;
  if k >= 4 { parts.push(format!("{}*{}", v[i], k)); } else { for _ in 0..k { parts.push(v[i].to_string()); } }
  i = j;
 }
 parts.join(" ")
}
fn main() {
 for line in io::stdin().lock().lines() {
  let line = line.unwrap();
  let (head, body) = line.split_once('|').unwrap();
  let mut hw = head.split_whitespace();
  let op = hw.next().unwrap();
  let flag: i64 = hw.next().unwrap().parse().unwrap();
  let data = expand(body.split_whitespace().collect());
  let out: Vec<i64> = match op {
   "head" => sol::head_packet(&data, flag),
   "tail" => sol::tail_packet(&data, flag),
   "window" => sol::window_packet(&data, flag),
   _ => panic!("unknown fixture"),
  };
  println!("{}", rle(&out));
 }
}
'''

EDGE, WINDOW, LINE = oracle.EDGE, oracle.WINDOW, oracle.LINE
LIM = oracle.LIM
RUN = re.compile(rb'(.)\1*', re.S)


def enc_bytes(data):
    """Run-length word encoding of bytes (same grouping as the Rust harness)."""
    words = []
    for m in RUN.finditer(data):
        v, k = m.group(1)[0], m.end() - m.start()
        words.append(f'{v}*{k}' if k >= 4 else ' '.join([str(v)] * k))
    return ' '.join(words)


# ---------------- transcript builders ----------------
NO = object()
J = a2.J


def L(*items, crlf=False, final_lf=True):
    return a2.lines(*items, crlf=crlf, final_lf=final_lf)


def user(content, **top):
    d = {'type': 'user', 'message': {'role': 'user', 'content': content}}
    d.update(top)
    return d


def asst(content=NO, model=NO, msg=NO, **top):
    m = {'role': 'assistant'}
    if model is not NO:
        m['model'] = model
    if content is not NO:
        m['content'] = content
    d = {'type': 'assistant', 'message': m if msg is NO else msg}
    d.update(top)
    return d


def tx(text):
    return {'type': 'text', 'text': text}


def tool_use(name='Bash', ident='t1'):
    return {'type': 'tool_use', 'id': ident, 'name': name, 'input': {}}


def tool_result(text='r'):
    return {'type': 'tool_result', 'tool_use_id': 't1', 'content': text}


def exact(prefix, suffix, total, fill=b'a'):
    k = total - len(prefix) - len(suffix)
    assert k >= 0, (len(prefix), len(suffix), total)
    return prefix + fill * k + suffix


USER_PRE = b'{"type":"user","message":{"role":"user","content":"'
USER_SUF = b'"}}'


def pad_for(op, flag, data):
    """Flagged fixtures get the exact edge/window size so the TS file reader selects the same bytes."""
    if not flag:
        return data
    target = WINDOW if op == 'window' else EDGE
    if len(data) >= target:
        return data
    pad = b' ' * (target - len(data))
    return data + pad if op == 'head' else pad + data


# ---------------- fixtures ----------------
def fixtures():
    cases = []

    def add(name, op, flag, data):
        data = pad_for(op, flag, data)
        cases.append((f'{op}{flag}: {name}', op, flag, data, oracle.api(op, flag, data)))

    def window(name, data, cut=0):
        add(name, 'window', cut, data)

    def triple(name, data, cut=0):
        add(name, 'head', cut, data)
        add(name, 'tail', cut, data)
        add(name, 'window', cut, data)

    # ---- basic transcripts through all three entry points ----
    base = [user('hello  there', cwd='/w', entrypoint='cli', timestamp=100), asst('hi back', model='m1', timestamp=101),
            user('second', timestamp='2025-02-03T04:05:06.007Z'), asst([tx('a'), tx('b')], model='m1', timestamp=1700000000123)]
    triple('basic', L(*base))
    triple('basic crlf', L(*base, crlf=True))
    triple('basic no final lf', L(*base, final_lf=False))
    for cut in (0, 1):
        triple('empty', b'', cut)
        triple('only newlines', b'\n\r\n\n', cut)
        triple('single complete line', L(user('x', cwd='/c')), cut)
        triple('single unterminated line', J(user('x', cwd='/c')), cut)
        triple('cut start inside first line', b'ial":1}\n' + L(*base), cut)
        triple('cut start on a boundary', L(*base), cut)
        triple('no newline at all', b'no newline here', cut)

    # ---- malformed middle lines ----
    bad = [b'garbage{', b'[1,2]', b'"str"', b'7', b'null', b'', b'   ', b'\r', b'{"type":"user","message":{"content":"x"',
           b'\xff\xfe', b'{"type":"user","message":{"content":"bad utf8 \xff"}}', b'\xef\xbb\xbf' + J(user('bom')),
           b'{"type":"user","message":{"content":"x"}} trailing', b'{"a":1}{"b":2}', b'{,}', b"{'type':'user'}",
           b'{"type":"user","message":{"content":"nan"},"n":NaN}', b'{"type":"user","message":{"content":"01"},"n":01}']
    triple('malformed middle', L(user('a', cwd='/m'), *bad, asst('r', model='mm'), *bad, user('b'), asst('r2')))
    window('malformed between answer parts', L(user('a'), asst([tx('p1')]), bad[0], asst([tx('p2')]), bad[8], asst('p3')))
    for n in (125, 126, 127, 128, 129):
        deep = b'{"type":"user","message":{"content":"deep%d"},"x":' % n + b'[' * n + b'0' + b']' * n + b'}'
        window(f'depth {n}', L(user('before'), deep, asst('after')))
        add(f'depth {n}', 'head', 0, L(deep))
        add(f'depth {n}', 'tail', 0, L(b'{"timestamp":1,"x":' + b'[' * n + b'0' + b']' * n + b'}'))
    window('duplicate keys last wins', b'{"type":"user","type":"assistant","message":{"content":"x"}}\n'
           b'{"type":"user","message":{"content":"first"},"message":{"content":"last"}}\n'
           b'{"type":"assistant","message":{"model":"m","content":"r1"},"message":{"model":"n","content":"r2"}}\n')
    window('escaped keys', b'{"typ\\u0065":"user","mess\\u0061ge":{"cont\\u0065nt":"esc"}}\n'
           b'{"type":"assistant","message":{"m\\u006fdel":"em","content":"ok"}}\n')
    window('only malformed', L(*bad))
    window('window skips cr only', b'\r\n\r\n' + L(user('a'), asst('b')))

    # ---- dropped users: oversized lines (> 1048576 raw bytes) never parsed; skip_user before later lines ----
    head_lines = L(user('first'), asst('r1', model='m0'))
    tail_lines = L(asst('orphan', model='m-orphan', timestamp=7), asst([tool_use()]), user('second'), asst('r2', model='m2', timestamp=8))

    def drop_case(name, big, cut=0, prefix=head_lines, suffix=tail_lines):
        window(name, prefix + big + b'\n' + suffix, cut)

    big_user = exact(USER_PRE, USER_SUF, LINE + 1)
    drop_case('oversized user', big_user)
    drop_case('oversized user, first line of window', big_user, prefix=b'')
    drop_case('oversized isMeta', exact(b'{"isMeta":true,"type":"user","message":{"content":"', USER_SUF, LINE + 1))
    drop_case('oversized isSidechain', exact(b'{"type":"user","isSidechain":true,"message":{"content":"', USER_SUF, LINE + 1))
    drop_case('oversized isMeta false', exact(b'{"isMeta":false,"type":"user","message":{"content":"', USER_SUF, LINE + 1))
    drop_case('oversized tool_result', exact(b'{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t","content":"',
                                             b'"}]}}', LINE + 1))
    drop_case('oversized text then tool_result', exact(b'{"type":"user","message":{"content":[{"type":"text","text":"',
                                                       b'"},{"type":"tool_result"}]}}', LINE + 1))
    drop_case('oversized type after 8192', exact(b'{"pad":"' + b'x' * 9000 + b'","type":"user","message":{"content":"', USER_SUF, LINE + 1))
    drop_case('oversized isMeta after 8192', exact(b'{"type":"user","pad":"' + b'x' * 9000 + b'","isMeta":true,"message":{"content":"',
                                                   USER_SUF, LINE + 1))
    drop_case('oversized assistant', exact(b'{"type":"assistant","message":{"model":"mb","content":"', USER_SUF, LINE + 1))
    drop_case('oversized nested type user', exact(b'{"type":"assistant","message":{"type":"user","content":"', USER_SUF, LINE + 1))
    drop_case('oversized spaced pattern', exact(b'{"type" \t:\n "user","message":{"content":"', USER_SUF, LINE + 1))
    drop_case('oversized no type', exact(b'{"message":{"content":"', USER_SUF, LINE + 1))
    drop_case('oversized escaped key', exact(b'{"typ\\u0065":"user","message":{"content":"', USER_SUF, LINE + 1))
    drop_case('oversized split multibyte at 8192',
              exact(USER_PRE + b'x' * (8192 - len(USER_PRE) - 1) + '\u00e9'.encode(), USER_SUF, LINE + 1))
    drop_case('oversized user, invalid utf-8 prefix', exact(b'{"type":"user","bad":"\xff\xfe","message":{"content":"', USER_SUF, LINE + 1))
    # the 1 MiB cap counts every raw byte before LF, including CR
    for name, total, ending in [('LF cap-1', LINE - 1, b'\n'), ('LF cap', LINE, b'\n'), ('LF cap+1', LINE + 1, b'\n'),
                                ('CRLF cap-1 (raw cap)', LINE - 1, b'\r\n'), ('CRLF cap (raw cap+1)', LINE, b'\r\n'),
                                ('CRLF cap+1', LINE + 1, b'\r\n')]:
        window(f'line length {name}', head_lines + exact(USER_PRE, USER_SUF, total) + ending + tail_lines)
    window('two oversized users', head_lines + big_user + b'\n' + big_user + b'\n' + tail_lines)
    window('oversized user after skip then answers', head_lines + big_user + b'\n' + L(asst('x'), asst([tool_use()]), asst('y')) + big_user + b'\n' + L(user('z'), asst('w')))
    window('oversized user first, then draft', big_user + b'\n' + L(user('after'), asst('r')))
    window('oversized user last (newline)', head_lines + big_user + b'\n')
    window('oversized user last (no newline)', head_lines + big_user)
    window('oversized unterminated assistant', head_lines + exact(b'{"type":"assistant","message":{"content":"', USER_SUF, LINE + 1))
    window('short unterminated tail ignored', head_lines + J(user('late')))
    window('short unterminated assistant ignored', head_lines + J(asst('late', model='late-model')))
    window('exactly cap unterminated tail ignored', head_lines + exact(USER_PRE, USER_SUF, LINE))
    window('unterminated cr tail ignored', head_lines + J(user('late')) + b'\r')
    window('oversized between answers', L(user('q')) + L(asst('a1')) + big_user + b'\n' + L(asst('a2')))
    window('parsed 1 MiB user clipped', head_lines + exact(USER_PRE, USER_SUF, LINE) + b'\n' + tail_lines)
    window('parsed 1 MiB assistant text', L(user('q')) + exact(b'{"type":"assistant","message":{"model":"mb","content":"', USER_SUF, LINE) + b'\n' + L(asst('tail')))
    window('1 MiB array content', L(user('q')) + exact(b'{"type":"assistant","message":{"content":[{"type":"text","text":"', b'"}]}}', LINE) + b'\n')
    for cut in (1,):
        drop_case('oversized after cut start', big_user, cut=cut, prefix=b'tial":"x"}}\n' + head_lines)
        window('cut start is itself oversized', exact(b'tail of a huge line', b'', LINE + 5) + b'\n' + head_lines + tail_lines, cut)
        window('cut start oversized without newline', exact(b'tail of a huge line', b'', LINE + 5), cut)
        window('cut then oversized unterminated', b'part\n' + head_lines + big_user, cut)

    # ---- synthetic / error assistants ----
    syn = '<synthetic>'
    window('synthetic suppressed', L(user('q'), asst('x', model=syn), asst([tool_use(), tx('y')], model=syn, timestamp=9)))
    window('synthetic with api error true', L(user('q'), asst('err text', model=syn, isApiErrorMessage=True, timestamp=9)))
    window('synthetic with api error true, tools', L(user('q'), asst([tool_use(), tx('e')], model=syn, isApiErrorMessage=True)))
    window('synthetic with api error not true', L(user('q'), asst('a', model=syn, isApiErrorMessage='true'),
                                                 asst('b', model=syn, isApiErrorMessage=1), asst('c', model=syn, isApiErrorMessage=False),
                                                 asst('d', model=syn, isApiErrorMessage=None), asst('e', model=syn, isApiErrorMessage=[True])))
    window('synthetic after real keeps real', L(user('q'), asst('a', model='real'), asst('b', model=syn, isApiErrorMessage=True)))
    window('synthetic before real', L(user('q'), asst('a', model=syn), asst('b', model='real')))
    window('real, synthetic suppressed, real', L(user('q'), asst('a', model='r1'), asst('b', model=syn), asst('c', model='r2')))
    window('synthetic without draft', L(asst('x', model=syn, isApiErrorMessage=True), user('q'), asst('y', model=syn)))
    window('synthetic spelled differently', L(user('q'), asst('a', model='<Synthetic>'), asst('b', model='<synthetic> '), asst('c', model=' <synthetic>')))
    window('synthetic escaped', b'{"type":"user","message":{"content":"q"}}\n{"type":"assistant","message":{"model":"<synth\\u0065tic>","content":"s"}}\n')
    window('model empty keeps previous', L(user('q'), asst('a', model='keep'), asst('b', model='')))
    window('model empty only', L(user('q'), asst('a', model='')))
    window('model wrong kinds', L(user('q'), asst('a', model='k'), asst('b', model=5), asst('c', model=None), asst('d', model=['z']),
                                  asst('e', model={'a': 1}), asst('f', model=True)))
    window('model last nonempty wins', L(user('q'), asst('a', model='m1'), asst('b', model='m2'), asst('c', model='m3')))
    window('model on sidechain ignored', L(user('q'), asst('a', model='m1'), asst('b', model='side', isSidechain=True)))
    window('model sidechain not true', L(user('q'), asst('a', model='m1'), asst('b', model='m2', isSidechain='true'),
                                         asst('c', model='m3', isSidechain=0), asst('d', model='m4', isSidechain=None)))
    window('isMeta assistant still counts', L(user('q'), asst('a', model='mm', isMeta=True)))
    window('model with escapes and surrogates', b'{"type":"user","message":{"content":"q"}}\n{"type":"assistant","message":{"model":"m\\u00e9\\ud83d\\ude00","content":"a"}}\n')
    window('model lone surrogate', b'{"type":"user","message":{"content":"q"}}\n{"type":"assistant","message":{"model":"m\\ud800x","content":"a"}}\n')
    window('model long', L(user('q'), asst('a', model='M' * 100000)))
    window('model 3-byte chars', L(user('q'), asst('a', model='\u20ac' * 1000)))

    # ---- a model without a current draft ----
    window('model before first user', L(asst('orphan', model='early'), user('q'), asst('a')))
    window('model only', L(asst('orphan', model='only')))
    window('model on tools-only line without draft', L(asst([tool_use()], model='tm')))
    window('model after skipped user', L(user('q'), asst('a', model='m1')) + big_user + b'\n' + L(asst('x', model='m2')))
    window('model line without content', L(user('q'), asst(model='nc'), asst('x')))
    window('model line with wrong content', L(user('q'), asst(5, model='w1'), asst(None, model='w2'), asst({'a': 1}, model='w3'), asst(True, model='w4')))
    window('model line with empty array', L(user('q'), asst([], model='ea')))
    window('model in non-object message', L(user('q'), asst(msg='text', model='x'), asst(msg=['m'], model='x'), asst(msg=None), asst(msg=5)))
    window('message missing', L(user('q'), {'type': 'assistant'}, {'type': 'assistant', 'content': 'x', 'model': 'top'}))
    window('model not in message', L(user('q'), {'type': 'assistant', 'model': 'top', 'message': {'content': 'x'}}))
    window('model line before and after only assistant', L(asst('a', model='m1'), asst('b', model='m2')))

    # ---- tools-only replies and block handling ----
    window('tools only', L(user('q'), asst([tool_use()], timestamp=50), asst([tool_use('Read', 't2'), tool_use('Read', 't2')], timestamp=51)))
    window('tools only no timestamp update', L(user('q', timestamp=10), asst([tool_use()], timestamp=50)))
    window('tools then text', L(user('q'), asst([tool_use(), tx('done')], timestamp=60)))
    window('text then tools', L(user('q'), asst([tx('first'), tool_use(), tx('second')], timestamp=61)))
    window('tool_use odd shapes', L(user('q'), asst([{'type': 'tool_use'}, {'type': 'tool_use', 'name': 5}, {'type': 'tool_use', 'id': None}, {'type': 'tool_use', 'id': 't', 'name': 'x', 'input': [1]}])))
    window('tool_use in string content not counted', L(user('q'), asst('{"type":"tool_use"}')))
    window('non text blocks ignored', L(user('q'), asst([{'type': 'thinking', 'thinking': 'z'}, {'type': 'image'}, 'str', 5, None, [tx('nested')], tx('real'), {'type': 'tool_result'}, {'text': 'no type'}])))
    window('text block wrong text', L(user('q'), asst([{'type': 'text', 'text': 5}, {'type': 'text'}, {'type': 'text', 'text': None}, {'type': 'text', 'text': ['x']}, tx('ok')])))
    window('empty text blocks update time only', L(user('q'), asst([tx('')], timestamp=70), asst('', timestamp=71)))
    window('empty then text pieces', L(user('q'), asst([tx(''), tx('a'), tx(''), tx('b')])))
    window('assistant string content empty', L(user('q', timestamp=1), asst('', timestamp=2)))
    window('tools after skip ignored', L(user('q')) + big_user + b'\n' + L(asst([tool_use(), tx('lost')]), user('r'), asst([tool_use()])))
    window('tools before first user ignored', L(asst([tool_use()]), user('q'), asst([tool_use()])))
    window('many tools', L(user('q'), asst([tool_use() for _ in range(40)]), asst([tool_use() for _ in range(60)])))
    window('same message repeated', L(user('q'), asst('dup', model='m'), asst('dup', model='m'), asst([tool_use('X', 'same')]), asst([tool_use('X', 'same')])))
    window('type tool_use as user', L(user([tool_use()]), user('q'), asst('a')))

    # ---- user classification inside the window ----
    window('user content kinds', L(user(5), user(None), user({'a': 1}), user(''), user('   '), user('\u3000\ufeff'), user([]), user('x', isMeta=True), user('y', isSidechain=True),
                                   user('z', isMeta='true'), user('w', isMeta=1), user('v', isSidechain='x'), user('kept1'), asst('r1')))
    window('user array content', L(user([tx('a'), tx(''), tx('b')]), asst('r1'), user([tx(''), tx('')]), asst('r2'),
                                   user([tx('x'), tool_result()]), asst('r3'), user([tool_result(), tx('y')]), asst('r4'),
                                   user([5, None, 'str', tx('z')]), asst('r5')))
    window('user interrupt lines', L(user('[Request interrupted by user]'), user(' [Request interrupted by user for tool use] \n'),
                                     user('[Request interrupted by user] more'), user('real'), asst('r')))
    window('task notification', L(user('<task-notification>x</task-notification>', origin={'kind': 'task-notification'}),
                                  user('<task-notification>x</task-notification>'),
                                  user('<task-notification></task-notification>', origin={'kind': 'task-notification'}),
                                  user('<task-notification>', origin={'kind': 'task-notification'}),
                                  user('q <task-notification>x</task-notification>', origin={'kind': 'task-notification'}), asst('r')))
    window('user with timestamp forms', L(user('t1', timestamp=1), user('t2', timestamp=1.5), user('t3', timestamp='x'), user('t4', timestamp=None),
                                          user('t5', timestamp='1700000000'), user('t6', timestamp=-1), user('t7', timestamp=100000000000),
                                          user('t8', timestamp='2024-02-29T23:59:59.999Z'), user('t9', timestamp='2023-02-29T00:00:00.000Z'),
                                          user('t10', timestamp=253402300800000), user('t11', timestamp=True), user('t12', timestamp=[1]), user('t13')))
    window('prompt and assistant on timestamps', L(user('q', timestamp='bad'), asst('a', timestamp=1.5), asst('b', timestamp=5), asst('c', timestamp='zzz'),
                                                   asst('d', timestamp=None)))
    window('timestamps out of order', L(user('q', timestamp=900), asst('a', timestamp=800), asst('b', timestamp=1000), asst('c', timestamp=700)))

    # ---- titles inside the window (ranks, ties, no fallback to the head title) ----
    window('titles rank order', L({'type': 'summary', 'summary': 'S1'}, {'type': 'ai-title', 'aiTitle': 'A1'}, {'type': 'custom-title', 'customTitle': 'C1'},
                                  {'type': 'summary', 'summary': 'S2'}, {'type': 'ai-title', 'aiTitle': 'A2'}, user('first human text'), asst('r')))
    window('titles tie later wins', L({'type': 'ai-title', 'aiTitle': 'A1'}, {'type': 'ai-title', 'aiTitle': 'A2'}, {'type': 'ai-title', 'aiTitle': ' '}))
    window('title only human', L(user('first human text'), asst('r')))
    window('title keys', L({'type': 'custom-title', 'title': 'T-only'}, {'type': 'summary', 'summary': ' ', 'title': 'S-fallback'}, {'type': 'ai-title', 'aiTitle': 5, 'title': 'ignored lower'}))
    window('title with flags ignored', L({'type': 'custom-title', 'customTitle': 'Flags', 'isMeta': True, 'isSidechain': True}))
    window('title long', L({'type': 'custom-title', 'customTitle': 'x ' * 200}))
    window('title emoji cut', L({'type': 'custom-title', 'customTitle': 'a' * 119 + '\U0001F600'}, {'type': 'ai-title', 'aiTitle': 'b' * 118 + '\U0001F600'}))
    window('title whitespace folded', L({'type': 'custom-title', 'customTitle': '\u3000 a \t\n b\u00a0 c \ufeff'}))
    window('title lone surrogate', b'{"type":"custom-title","customTitle":"t\\ud800 x"}\n')
    window('title custom without text then summary', L({'type': 'custom-title', 'customTitle': ''}, {'type': 'summary', 'summary': 'S'}))
    window('title on a user line type', L({'type': 'user', 'title': 'no', 'message': {'content': 'x'}}))
    window('title lines with timestamps', L({'type': 'summary', 'summary': 'S', 'timestamp': 'junk'}, {'type': 'ai-title', 'aiTitle': 'A', 'timestamp': 5}))

    # ---- head / tail / window disagree on the same bytes ----
    triple('disagree: titles', L({'type': 'custom-title', 'customTitle': 'Ranked'}, user('First human', cwd='/hc', entrypoint='sdk', timestamp=11),
                                 {'type': 'summary', 'summary': 'Late summary', 'timestamp': 99}, asst('r', model='mx', timestamp=12), user('Second', timestamp=13)))
    triple('disagree: cwd late', L(user('hello'), {'cwd': ''}, {'cwd': '/later', 'entrypoint': 'e'}, asst('r', model='m')))
    triple('disagree: lastAt last accepted', L(user('a', timestamp=900), asst('b', timestamp=5), {'type': 'system', 'timestamp': 'junk'},
                                              {'type': 'system', 'timestamp': 1.5}, {'type': 'x'}))
    triple('disagree: head meta user', L(user('meta', isMeta=True, cwd='/m'), user('side', isSidechain=True), user('real'), asst('r')))
    triple('disagree: interrupt first', L(user('[Request interrupted by user]', cwd='/i'), user('human'), asst('answer')))
    triple('disagree: tool_result first', L(user([tool_result()]), user('human'), asst('a', model='mm')))
    for cut in (0, 1):
        triple('disagree: unterminated last line', L(user('one', cwd='/a'), asst('r', model='m1', timestamp=5)) + J(user('last-unterminated', timestamp=9)), cut)
        triple('disagree: partial first line', b'rest","x":1}\n' + L(user('after cut', cwd='/b'), asst('r', model='m1', timestamp=6), {'type': 'summary', 'summary': 'S'}), cut)
        triple('disagree: first line complete', J(user('first-line', cwd='/f', timestamp=1)) + b'\n' + L(asst('r', model='m2', timestamp=2), user('u2', timestamp=3)), cut)
        triple('disagree: crlf', L(user('one', cwd='/a'), asst('r', model='m1', timestamp=5), {'type': 'ai-title', 'aiTitle': 'AI'}, crlf=True), cut)
    triple('disagree: invalid utf-8 line', b'\xff\n' + L(user('ok', cwd='/u'), asst('r', model='m')))

    # ---- option presence ----
    window('presence: none', b'')
    window('presence: prompt only', L(user('only prompt')))
    window('presence: prompt created', L(user('p', timestamp=1)))
    window('presence: completed without created', L(user('p'), asst('r', timestamp=2)))
    window('presence: both', L(user('p', timestamp=1), asst('r', timestamp=2)))
    window('presence: created, completed absent (unsupported)', L(user('p', timestamp=1), asst('r', timestamp='bad')))
    window('presence: tools no text', L(user('p'), asst([tool_use()])))
    window('presence: clipped long prompt', L(user('p' * (LIM + 1)), asst('r')))
    window('presence: clipped long reply', L(user('p'), asst('r' * (LIM + 1))))
    window('presence: clipped by lost user', L(user('a')) + big_user + b'\n' + L(user('b')))
    window('presence: no model no title', L(user('p'), asst('r')))
    window('presence: model only', L(asst('r', model='only-model')))
    window('presence: title only', L({'type': 'summary', 'summary': 'only title'}))
    window('presence: empty reply completed', L(user('p'), asst('', timestamp=3)))
    window('presence: unanswered last prompt', L(user('a'), asst('r'), user('b')))
    window('presence: omitted by cut only', L(user('a'), asst('r')), 1)
    window('presence: omitted by cut, no complete line', b'x', 1)
    window('presence: empty prompt text blocks skipped', L(user([tx('')]), user('real')))
    window('presence: reply cap exact', L(user('p'), asst('r' * LIM)))
    window('presence: reply cap plus one then more', L(user('p'), asst('r' * (LIM + 1)), asst('more', timestamp=4)))

    # ---- caps, ring and policy cases through the whole pipeline ----
    pair = lambda i, p=5, r=5: [user(f'{"p%d-" % i}'.ljust(p, 'p'), timestamp=1000 + i), asst(f'{"r%d-" % i}'.ljust(r, 'r'), model='cm', timestamp=2000 + i)]
    for n in (199, 200, 201, 202, 399, 401):
        window(f'{n} drafts', L(*[x for i in range(n) for x in pair(i)]))
    window('201 drafts with oversized users between', b''.join(L(*pair(i)) + (big_user + b'\n' if i % 90 == 7 else b'') for i in range(250)))
    window('total cap exact 32 full pairs', L(*[x for i in range(32) for x in (user('a' * LIM), asst('b' * LIM))]))
    window('total cap overflow 33 full pairs', L(*[x for i in range(33) for x in (user('a' * LIM), asst('b' * LIM))]))
    window('total cap stop at first unfit', L(user('tiny'), asst('t'), *[x for i in range(32) for x in (user('a' * LIM), asst('b' * LIM))], user('n'), asst('m')))
    window('prompt cap multibyte cuts', L(user('\u20ac' * 10923), user('\U0001F600' * 8193), user('a' + '\u00e9' * 16384), user('\ufffd' * 10923)))
    window('reply cap multibyte', L(user('p'), asst('\u20ac' * 10923), asst('z', timestamp=9), user('q'), asst('a' * (LIM - 4)), asst('\u20ac'), asst('late')))
    window('reply separator partial', L(user('p'), asst('a' * (LIM - 2)), asst('bb'), user('q'), asst('a' * (LIM - 1)), asst('b')))
    window('lone surrogates policy', b'{"type":"user","message":{"content":"a\\ud800b \\udc00 \\ud83d\\ude00"}}\n{"type":"assistant","message":{"model":"m","content":"r\\ud83d x"}}\n'
           b'{"type":"user","message":{"content":[{"type":"text","text":"\\ud800"},{"type":"text","text":"\\udc00"}]}}\n')
    window('lone surrogate prompt blank', b'{"type":"user","message":{"content":"\\ud800"}}\n')
    window('whitespace prompts', L(user('\u2028x\u2029'), user('\u00a0'), user('\u180e'), user('\u200b'), user('\u0085'), user('\u1680\u2000 y \u202f\u205f\u3000')))
    window('prompt lone surrogate clip', b'{"type":"user","message":{"content":"' + b'a' * 32767 + b'\\ud800b"}}\n')
    window('prompt fffd at cap', L(user('a' * 32765 + '\ufffd\ufffd\ufffd')))
    window('filler lines to the window limit', b' ' * (WINDOW - len(L(user('last'))) - 1) + b'\n' + L(user('last')))
    window('window limit exact', L(user('first')) + b' ' * (WINDOW - len(L(user('first')))))
    window('window limit plus one', b'a' * (WINDOW + 1))
    add('limit plus one', 'head', 0, b'a' * (EDGE + 1))
    add('limit plus one', 'tail', 0, b'a' * (EDGE + 1))
    return cases


# ---------------- hand-derived facts that keep the oracle honest ----------------
def hand_checks(cases):
    by = {name: oracle.decode(want) for name, _, _, _, want in cases}

    def turns(name):
        return by[name]['turns']

    def lbl(n):
        return f'window0: {n}'

    t = turns(lbl('oversized user'))
    assert [x['prompt'] for x in t] == ['first', 'second'] and t[0]['reply'] == 'r1' and t[1].get('clipped') is True, t
    assert t[1]['reply'] == 'r2' and 'orphan' not in json.dumps(t) and by[lbl('oversized user')]['model'] == 'm2'
    t = turns(lbl('oversized isMeta'))
    assert [x['prompt'] for x in t] == ['first', 'second'] and 'clipped' not in t[1] and t[0]['reply'] == 'r1\n\norphan', t
    assert 'clipped' not in turns(lbl('oversized tool_result'))[1] and 'clipped' not in turns(lbl('oversized type after 8192'))[1]
    assert turns(lbl('oversized isMeta after 8192'))[1].get('clipped') is True
    assert turns(lbl('oversized nested type user'))[1].get('clipped') is True
    assert 'clipped' not in turns(lbl('oversized assistant'))[1]
    # the cap counts CR: LF cap is parsed (clipped by the 32 KiB prompt rule only), CRLF cap is dropped
    assert len(turns(lbl('line length LF cap'))) == 3 and len(turns(lbl('line length LF cap+1'))) == 2
    assert len(turns(lbl('line length CRLF cap (raw cap+1)'))) == 2 and len(turns(lbl('line length CRLF cap-1 (raw cap)'))) == 3
    assert [x['prompt'] for x in turns(lbl('short unterminated tail ignored'))] == ['first']
    assert by[lbl('short unterminated assistant ignored')]['model'] == 'm0'
    t = turns(lbl('synthetic suppressed'))
    assert t[0]['reply'] == '' and t[0]['tools'] == 0 and 'model' not in by[lbl('synthetic suppressed')]
    t = turns(lbl('synthetic with api error true'))
    assert t[0]['reply'] == 'err text' and 'model' not in by[lbl('synthetic with api error true')]
    assert turns(lbl('synthetic with api error true, tools'))[0]['tools'] == 1
    assert by[lbl('synthetic after real keeps real')]['model'] == 'real' and by[lbl('synthetic before real')]['model'] == 'real'
    assert by[lbl('model only')] == {'omittedBefore': False, 'turns': [], 'model': 'only'}
    assert by[lbl('model empty keeps previous')]['model'] == 'keep' and 'model' not in by[lbl('model empty only')]
    assert by[lbl('model before first user')]['model'] == 'early' and turns(lbl('model before first user'))[0]['reply'] == 'a'
    assert by[lbl('model line without content')]['model'] == 'nc'
    t = turns(lbl('tools only'))
    assert t[0]['tools'] == 3 and t[0]['reply'] == '' and 'completedAt' not in t[0], t
    t = turns(lbl('tools only no timestamp update'))
    assert t[0]['tools'] == 1 and 'completedAt' not in t[0] and 'createdAt' in t[0]
    assert turns(lbl('tools then text'))[0]['tools'] == 1 and turns(lbl('tools then text'))[0]['reply'] == 'done'
    assert turns(lbl('tool_use in string content not counted'))[0]['tools'] == 0
    assert turns(lbl('many tools'))[0]['tools'] == 100
    assert turns(lbl('empty text blocks update time only'))[0]['completedAt'] == '1970-01-01T00:01:11.000Z'
    assert turns(lbl('empty then text pieces'))[0]['reply'] == 'a\n\nb'
    assert turns(lbl('tools after skip ignored'))[1]['tools'] == 1 and turns(lbl('tools after skip ignored'))[0]['tools'] == 0
    assert by[lbl('titles rank order')]['title'] == 'C1' and by[lbl('titles tie later wins')]['title'] == 'A2'
    assert 'title' not in by[lbl('title only human')]
    assert by[lbl('titles tie later wins')]['omittedBefore'] is False
    assert by['window1: presence: omitted by cut only']['omittedBefore'] is True
    assert by[lbl('201 drafts')]['omittedBefore'] is True and len(by[lbl('201 drafts')]['turns']) == 200
    assert by[lbl('200 drafts')]['omittedBefore'] is False and by[lbl('202 drafts')]['turns'][-1]['prompt'].startswith('p201-')
    assert len(by[lbl('total cap exact 32 full pairs')]['turns']) == 32 and by[lbl('total cap exact 32 full pairs')]['omittedBefore'] is False
    assert len(by[lbl('total cap overflow 33 full pairs')]['turns']) == 32 and by[lbl('total cap overflow 33 full pairs')]['omittedBefore'] is True
    assert by[lbl('total cap stop at first unfit')]['turns'][0]['prompt'] == 'a' * LIM
    assert by[lbl('window limit plus one')] == {'error': 1, 'position': 0}
    assert by['head0: limit plus one'] == {'error': 1, 'position': 0}
    d = by['head0: disagree: titles']
    assert d == {'title': 'First human', 'cwd': '/hc', 'entrypoint': 'sdk'}, d
    assert by['tail0: disagree: titles'] == {'title': 'Ranked', 'lastAt': '1970-01-01T00:00:13.000Z'}, by['tail0: disagree: titles']
    assert by[lbl('disagree: titles')]['title'] == 'Ranked'
    assert by['tail0: disagree: lastAt last accepted']['lastAt'] == '1970-01-01T00:00:05.000Z'


# ---------------- driver ----------------
def configure():
    WORK.mkdir(parents=True, exist_ok=True)
    os.environ['TMPDIR'] = str(WORK)
    spec_ = importlib.util.spec_from_file_location('a2_setup', JSON_DIR / 'run_a2.py')
    setup = importlib.util.module_from_spec(spec_)
    spec_.loader.exec_module(setup)
    setup.WORK = WORK
    return setup.configure(), setup.run


def write_fixtures(cases):
    out = [{'name': name, 'op': op, 'flag': flag, 'data': base64.b64encode(data).decode(), 'expected': want}
           for name, op, flag, data, want in cases]
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / 'fixtures.json').write_text(json.dumps(out))


def main():
    oracle.selfcheck()
    cases = fixtures()
    hand_checks(cases)
    names = [c[0] for c in cases]
    assert len(set(names)) == len(names), 'fixture names must be unique'
    write_fixtures(cases)
    print(f'{len(cases)} fixtures (fixtures.json written for reference.mjs)', flush=True)
    g2, run = configure()
    # The str adapter crate (UTF-8 representation conversion), as in test_a3.py.
    target = WORK / 'str-adapter'
    run([shutil.which('cargo') or str(Path.home() / '.cargo/bin/cargo'), 'build', '--release', '--offline', '--quiet',
         '--manifest-path', JSON_DIR / 'str_adapter/Cargo.toml', '--target-dir', target])
    rlib, deps = target / 'release/libpruv_str.rlib', target / 'release/deps'
    flags = ['--rust-extern', f'pruv_str={rlib}', '--rust-search', str(deps)]
    rustflags = ['--extern', f'pruv_str={rlib}', '-L', f'dependency={deps}']
    payload = ''.join(f'{op} {flag}|{enc_bytes(data)}\n' for _, op, flag, data, _ in cases)
    expected = [a3.enc(want) for *_, want in cases]
    failed = False
    for compiler in ('py', 'rs'):
        for backend in ('rust', 'llvm'):
            key = f'{compiler}/{backend}'
            try:
                work = WORK / f'{compiler}_{backend}'
                work.mkdir(exist_ok=True)
                compiled = g2.compile_pruv(compiler, str(HERE / 'a4_root.pruv'), str(work), backend, flags)
                if compiled['rc'] != 0:
                    raise RuntimeError('compile/verify failed: ' + str(compiled['errors'] or compiled['stderr']))
                print(f'{key}: verified and compiled', flush=True)
                harness = work / 'main.rs'
                harness.write_text(HARNESS.replace('@SOL@', compiled['rs']))
                extra = []
                if compiled['ll']:
                    extra, error = g2.build_llvm_objects(compiled['ll'], 'a4', str(work))
                    if error:
                        raise RuntimeError(error)
                exe = work / 'runner'
                run([g2.RUSTC, '-O', '--edition', '2021', harness, '-o', exe] + extra + rustflags)
                got = run([exe], payload).splitlines()
                if len(got) != len(expected):
                    raise RuntimeError(f'{len(got)} answers for {len(expected)} fixtures')
                bad = [(i, w, g) for i, (w, g) in enumerate(zip(expected, got)) if w != g]
                for i, w, g in bad[:20]:
                    print(f'{key}: fixture {i} {cases[i][0]}: expected {w[:240]}, got {g[:240]}')
                failed |= bool(bad)
                print(f'{key}: {len(cases) - len(bad)}/{len(cases)} fixtures passed', flush=True)
            except Exception as exc:
                failed = True
                print(f'{key}: ERROR {exc}', file=sys.stderr, flush=True)
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
