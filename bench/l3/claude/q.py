#!/usr/bin/env python3
"""L3-1 Q: differential corpus driver for the Pruv Claude JSONL importer (q_root.pruv).

    python3 q.py [--count N] [--seed S] [--pairs py/rust,rs/llvm,...]     run the corpus on the selected pairs
    python3 q.py classify REF_OUT.json [REF_OUT2.json ...]               classify reference.mjs differences

Corpus = test_a4.fixtures() (fixed edges) + N generated TRANSCRIPTS (several JSONL lines each). Expected packets come
from oracle.api (independent Python oracle). The corpus is written to work/q/corpus-NN.json shards (listed in
work/q/corpus_shards.txt) in the fixtures.json format of test_a4.write_fixtures plus the keys `triggers`, `seed`,
`fixed`; reference.mjs reads the shards with
    node reference.mjs --fixtures "$(cat work/q/corpus_shards.txt)" --out work/q/reference-node.json
and `classify` then sorts every TS/oracle difference into "explained by policy" and "UNEXPLAINED".

Triggers are the policy tags the generator deliberately injected (an untagged transcript must agree with TS exactly):
  P1-utf8 invalid UTF-8 bytes in a line (also a BOM line)   P1-depth nesting > 128
  P2-surrogate lone surrogate escapes in a string           P2-cut supplementary char near a 1-line (120 unit) cut
  P3-fffd genuine U+FFFD near a clip cap                    P4-time timestamp outside the supported iso_of domain
Flagged (cut) items follow test_a4.pad_for. Padding a window to 8 MiB for every flagged window is not affordable, so
only a small budget of flagged windows is padded (name has no 'nopad'); the others are flagged but unpadded
(name ends with ' nopad'): reference.mjs skips those, the Pruv/oracle comparison still covers them.
"""
import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import random

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE / 'work' / 'q'

_spec = importlib.util.spec_from_file_location('l3_a4', HERE / 'test_a4.py')
t4 = importlib.util.module_from_spec(_spec)
sys.modules['l3_a4'] = t4
_spec.loader.exec_module(t4)
t4.WORK = WORK                      # configure() of test_a4 works in this directory
oracle, a1, a2, a3 = t4.oracle, t4.a1, t4.a2, t4.a3

EDGE, WINDOW, LINE, LIM, TOTAL = oracle.EDGE, oracle.WINDOW, oracle.LINE, oracle.LIM, oracle.TOTAL
NO = t4.NO
WS_LIST, NEAR = a1.WS_LIST, a1.NEAR
INT1, INT2 = a1.INT1, a1.INT2
OPEN, CLOSE = a1.OPEN, a1.CLOSE
SYN = '<synthetic>'
PAIRS = ['py/rust', 'py/llvm', 'rs/rust', 'rs/llvm']
TRIGGERS = ['P1-utf8', 'P1-depth', 'P2-surrogate', 'P2-cut', 'P3-fffd', 'P4-time']
INJECT_RATE = 0.025
RAW_RE = re.compile(rb'"@@RAW:([^"]*)@@"')


def raw(s):
    """A JSON value emitted verbatim (number forms Python cannot produce)."""
    return '@@RAW:' + s + '@@'


# ---------------------------------------------------------------- random text and values
WORDS = ['alpha', 'beta', 'refactor', 'the', 'fix', 'bug', 'in', 'parser', 'tests', 'please', 'über', 'naïve', '日本語',
         '한국어', 'привет', 'café', '😀', '🎉', '€', '—', '…', 'x', 'y', 'a/b.c', '"quoted"', 'back\\slash', '<tag>', '{json}']


def chance(rng, p):
    return rng.random() < p


def rtext(rng, lo=1, hi=10):
    r = rng.random()
    if r < 0.03:
        return rng.choice(WS_LIST) * rng.randint(1, 4)
    if r < 0.07:
        pad = lambda: ''.join(rng.choice(WS_LIST) for _ in range(rng.randint(1, 3)))
        return pad() + rng.choice(WORDS) + pad()
    parts = []
    for _ in range(rng.randint(lo, hi)):
        q = rng.random()
        if q < 0.70:
            parts.append(rng.choice(WORDS))
        elif q < 0.78:
            parts.append(rng.choice(WS_LIST))
        elif q < 0.83:
            parts.append(rng.choice(NEAR))
        elif q < 0.90:
            parts.append(rng.choice(['\n', '\r\n', '\t', '\u2028', '\u2029', '\n\n']))
        else:
            parts.append(str(rng.randrange(10 ** rng.randint(1, 12))))
    return rng.choice(['', ' ', ' ', '\n']).join(parts)


def tag_text(ctx, s):
    """A long text with a supplementary scalar could be split by a 120-unit one_line cut."""
    if len(s) > 90 and any(ord(c) > 0xFFFF for c in s):
        ctx.add('P2-cut')
    return s


BASE = 1700000000000
BAD_TS = ['x', 'junk', 'bad', 'zzz']            # rejected by Date.parse and by the oracle alike
P4_VALUES = [1.5, 1700000000.5, 0.5, '1700000000', ' 1700000000 ', -1, -1000, 10 ** 20, 253402300800000, 253402300800001,
             9007199254740993, '2023-02-29T00:00:00.000Z', '2024-02-30T10:00:00.000Z', '2100-02-29T00:00:00.000Z',
             '10000-01-01T00:00:00.000Z', '+010000-01-01T00:00:00.000Z', '-000001-01-01T00:00:00.000Z', '2024-01-01',
             '2024-01-01T00:00:00Z', '2024-01-01T00:00:00.000+09:00', '2024-01-01T00:00:00', '2024-01-01T00:00:00.1Z',
             '2024-01-01 00:00:00', 'Mon, 01 Jan 2024 00:00:00 GMT', '2024-01-01T24:00:00.000Z', '2024-06-31T00:00:00.000Z',
             '2024-13-01T00:00:00.000Z', '2024-01-01t00:00:00.000z', True, False, [1], {'a': 1},
             raw('1e3'), raw('1.0'), raw('-0'), raw('1E+12'), raw('1700000000000.0')]


def ts_state(rng):
    return {'ms': BASE + rng.randint(0, 10 ** 10), 'form': rng.randrange(6), 'order': chance(rng, 0.25),
            'p': rng.choice([0, 0.3, 0.8, 1.0])}


def good_ts(rng, ms, form):
    if form == 0:
        return a2.o_fmt(ms)
    if form == 1:
        return ms
    if form == 2:
        return ms // 1000
    if form == 3:
        return rng.choice([a2.o_fmt(ms), ms, ms // 1000])
    if form == 4:
        return a2.o_fmt(rng.randint(a2.MIN_MS, a2.MAX_MS))
    return rng.choice([99999999999, 100000000000, 100000000001, 1, 86400, 253402300799])


def stamp(rng, T):
    if rng.random() > T['p']:
        if chance(rng, 0.06):
            return rng.choice(BAD_TS + [None])
        return NO
    if T['order']:
        T['ms'] += rng.randint(-10 ** 9, 10 ** 9)
    else:
        T['ms'] += rng.randint(1000, 10 ** 6)
    ms = max(T['ms'], BASE // 2)
    return good_ts(rng, ms, T['form'])


def nest(rng, lo, hi):
    n = rng.randint(lo, hi)
    return json.loads('[' * n + '0' + ']' * n)


def decorate(rng, ctx, d, T):
    """Timestamp, cwd/entrypoint and irrelevant fields."""
    if 'timestamp' not in d:
        ts = stamp(rng, T)
        if ts is not NO:
            d['timestamp'] = ts
    if chance(rng, 0.15):
        d['cwd'] = rng.choice(['/w/proj', '', '/tmp/é', 'C:\\w', '/w/proj', 5, None, ' ', '😀'])
    if chance(rng, 0.10):
        d['entrypoint'] = rng.choice(['cli', 'sdk', '', 'ide', 7, None, 'é'])
    for _ in range(rng.choice([0, 0, 1, 1, 2, 3])):
        k = rng.randrange(18)
        if k == 0:
            d['uuid'] = '%08x-0000-4000-8000-%012x' % (rng.getrandbits(32), rng.getrandbits(48))
        elif k == 1:
            d['parentUuid'] = rng.choice([None, 'p-1', 'p-2'])
        elif k == 2:
            d['sessionId'] = 's-%d' % rng.randrange(5)
        elif k == 3:
            d['version'] = '1.0.%d' % rng.randrange(100)
        elif k == 4:
            d['gitBranch'] = rng.choice(['main', '', 'feat/é'])
        elif k == 5:
            d['userType'] = 'external'
        elif k == 6:
            d['requestId'] = 'req_%d' % rng.randrange(1000)
        elif k == 7:
            d['isCompactSummary'] = rng.choice([True, False, 1, 'true', None])
        elif k == 8:
            d['isVisibleInTranscriptOnly'] = rng.choice([True, False, 'yes'])
        elif k == 9:
            d['toolUseResult'] = {'type': 'tool_result', 'content': 'x', 'isMeta': True, 'isSidechain': True}
        elif k == 10:
            d['meta'] = {'type': 'user', 'isMeta': True, 'isSidechain': True, 'message': {'content': [{'type': 'tool_result'}]}}
        elif k == 11:
            d['n'] = raw(rng.choice(['1e3', '-0', '1.5E+3', '0', '123456789012345678901234567890', '-1.25e-7', '1E400']))
        elif k == 12:
            d['unicode'] = 'é😀\u2028'
        elif k == 13:
            d['deep'] = nest(rng, 3, 100)
        elif k == 14:
            d['level'] = rng.choice(['info', 'warn'])
        elif k == 15:
            d['cost'] = rng.choice([0.0123, 12, 1e-7])
        elif k == 16:
            d['type_'] = {'type': rng.choice(['user', 'assistant', 'summary'])}
        else:
            d['summary'] = rtext(rng, 1, 3)          # a summary key on a non-summary line
    return d


# ---------------------------------------------------------------- line builders
def interrupt(rng):
    pad = lambda: ''.join(rng.choice(WS_LIST) for _ in range(rng.randint(0, 2)))
    base = rng.choice([INT1, INT2, INT1, INT2, INT1 + ' more', INT1.lower(), INT1[:-1], '[Request  interrupted by user]',
                       INT1 + INT1, INT1 + '\n' + INT2, '[Request interrupted by user for tool use] '])
    return pad() + base + pad()


def notif(rng):
    body = rng.choice(['x', 'task done', '', '<a>b</a>', 'line1\nline2'])
    text = rng.choice([OPEN + body + CLOSE, ' ' + OPEN + body + CLOSE + ' \n', 'q ' + OPEN + body + CLOSE, OPEN + body,
                       OPEN + body + CLOSE + ' tail', OPEN + CLOSE, OPEN + body + CLOSE + OPEN + body + CLOSE,
                       OPEN + 'a' * 25 + CLOSE])
    origin = rng.choice([{'kind': 'task-notification'}] * 4 + [{'kind': 'other'}, {'kind': 'task-notification '}, {'kind': 1}, {},
                         'task-notification', None, NO, NO, {'kind': 'task-notification', 'k2': 1}, ['task-notification']])
    return text, origin


CMD = ['<command-name>/clear</command-name>\n<command-message>clear</command-message>\n<command-args></command-args>',
       '<local-command-stdout></local-command-stdout>', '<local-command-caveat>Caveat: generated by local commands</local-command-caveat>',
       '<command-name>/model</command-name>', '<system-reminder>reminder</system-reminder>']


def user_blocks(rng, ctx):
    blocks = []
    for _ in range(rng.randint(0, 5)):
        q = rng.random()
        if q < 0.50:
            blocks.append(t4.tx(tag_text(ctx, rtext(rng))))
        elif q < 0.60:
            blocks.append(t4.tx(''))
        elif q < 0.72:
            blocks.append(rng.choice([t4.tool_result(rtext(rng, 1, 3)), {'type': 'tool_result', 'tool_use_id': 't', 'content': [t4.tx('x')]},
                                      {'type': 'tool_result'}, {'type': 'tool_result', 'is_error': True, 'content': ''}]))
        elif q < 0.78:
            blocks.append({'type': 'thinking', 'thinking': rtext(rng)})
        elif q < 0.82:
            blocks.append({'type': 'image', 'source': {'type': 'base64', 'data': 'AAAA'}})
        elif q < 0.90:
            blocks.append(rng.choice([5, None, 'str', [t4.tx('nested')], {'text': 'no type'}, {'type': 'text', 'text': 5},
                                      {'type': 'text'}, {'type': 'text', 'text': None}, {'type': 'tool_use', 'id': 'u'},
                                      {'type': 'Text', 'text': 'cap'}, {'type': 'text ', 'text': 'sp'}]))
        else:
            blocks.append(t4.tx(interrupt(rng)))
    return blocks


FLAG_VALUES = [True, True, False, 1, 0, 'true', None, [True], 'x']


def make_user(rng, ctx, T):
    r = rng.random()
    origin = NO
    if r < 0.50:
        content = tag_text(ctx, rtext(rng, 1, 14))
    elif r < 0.58:
        content = interrupt(rng)
        if chance(rng, 0.3):
            content = [t4.tx(content)]
    elif r < 0.66:
        content, origin = notif(rng)
        if chance(rng, 0.25):
            content = [t4.tx(content)]
    elif r < 0.70:
        content = rng.choice(CMD)
    elif r < 0.84:
        content = user_blocks(rng, ctx)
    elif r < 0.88:
        content = rng.choice([5, None, {'a': 1}, '', '   ', [], True, 1.5, '\u3000\ufeff'])
    else:
        content = [rng.choice([t4.tool_result('res'), {'type': 'tool_result', 'tool_use_id': 't9', 'content': [t4.tx('y')]}])]
        if chance(rng, 0.3):
            content.append(t4.tx(rtext(rng)))
    d = t4.user(content)
    if origin is not NO:
        d['origin'] = origin
    elif chance(rng, 0.03):
        d['origin'] = rng.choice([{'kind': 'task-notification'}, {'kind': 'x'}, 'task-notification', None])
    if chance(rng, 0.12):
        d['isMeta'] = rng.choice(FLAG_VALUES)
    if chance(rng, 0.10):
        d['isSidechain'] = rng.choice(FLAG_VALUES)
    if chance(rng, 0.02):
        d['type'] = rng.choice(['User', 'user ', 'USER', 5, None, 'assistant'])
    return decorate(rng, ctx, d, T)


def asst_blocks(rng, ctx):
    blocks = []
    for _ in range(rng.randint(0, 5)):
        q = rng.random()
        if q < 0.50:
            blocks.append(t4.tx(rtext(rng)))
        elif q < 0.58:
            blocks.append(t4.tx(''))
        elif q < 0.78:
            blocks.append(t4.tool_use(rng.choice(['Bash', 'Read', 'Edit', 'X']), rng.choice(['t1', 't1', 't2', 't3'])))
        elif q < 0.85:
            blocks.append({'type': 'thinking', 'thinking': rtext(rng)})
        elif q < 0.89:
            blocks.append({'type': 'tool_result', 'tool_use_id': 't1', 'content': 'r'})
        else:
            blocks.append(rng.choice([5, None, 'str', [t4.tx('n')], {'text': 'no type'}, {'type': 'text', 'text': 5}, {'type': 'tool_use'},
                                      {'type': 'tool_use', 'name': 5}, {'type': 'tool_use', 'id': None}, {'type': 'text'},
                                      {'type': 'tool_use', 'id': 't', 'name': 'x', 'input': [1]}]))
    return blocks


MODELS = ['claude-opus-4-1', 'claude-sonnet-4-5', 'claude-haiku-4', 'claude-3-5-sonnet-20241022', 'm1', 'm2']


def make_asst(rng, ctx, T):
    r = rng.random()
    if r < 0.55:
        model = rng.choice(MODELS)
    elif r < 0.67:
        model = SYN
    elif r < 0.72:
        model = ''
    elif r < 0.82:
        model = NO
    elif r < 0.87:
        model = rng.choice(['<Synthetic>', '<synthetic> ', ' <synthetic>', 'synthetic', '<synthetic>x'])
    elif r < 0.92:
        model = rng.choice([5, None, ['z'], {'a': 1}, True])
    else:
        model = rtext(rng, 1, 3)
    q = rng.random()
    if q < 0.42:
        content = rtext(rng, 1, 14)
    elif q < 0.76:
        content = asst_blocks(rng, ctx)
    elif q < 0.82:
        content = NO
    elif q < 0.88:
        content = rng.choice([5, None, {'a': 1}, True, 1.5])
    elif q < 0.92:
        content = rng.choice([[], '', [t4.tx('')], [t4.tool_use()], [t4.tool_use(), t4.tool_use('R', 't2')]])
    else:
        content = rng.choice(['{"type":"tool_use"}', '[{"type":"tool_use"}]', INT1, OPEN + 'x' + CLOSE])
    m = rng.random()
    d = t4.asst(content, model)
    if m < 0.03:
        d = t4.asst(msg=rng.choice(['text', ['m'], None, 5, True]), model=model)
    elif m < 0.05:
        del d['message']
    elif m < 0.07 and content is not NO:
        d = {'type': 'assistant', 'content': content, 'model': model if model is not NO else 'top'}
    elif m < 0.30 and isinstance(d.get('message'), dict):
        d['message'].update(rng.choice([{'id': 'msg_1', 'stop_reason': 'end_turn', 'usage': {'input_tokens': 5}},
                                        {'type': 'message'}, {'type': 'user', 'isMeta': True}, {'role': 'user'}, {'stop_reason': None}]))
    if model == SYN and chance(rng, 0.6):
        d['isApiErrorMessage'] = rng.choice([True, True, True, 'true', 1, False, None, [True]])
    elif chance(rng, 0.03):
        d['isApiErrorMessage'] = rng.choice(FLAG_VALUES)
    if chance(rng, 0.07):
        d['isSidechain'] = rng.choice(FLAG_VALUES)
    if chance(rng, 0.03):
        d['isMeta'] = rng.choice(FLAG_VALUES)
    if chance(rng, 0.015):
        d['type'] = rng.choice(['Assistant', 'assistant ', 5, None, 'user'])
    return decorate(rng, ctx, d, T)


TITLE_KEYS = {'custom-title': 'customTitle', 'ai-title': 'aiTitle', 'summary': 'summary'}


def make_title(rng, ctx, T):
    kind = rng.choice(list(TITLE_KEYS))
    key = TITLE_KEYS[kind]
    txt = rng.choice(['T-a', 'T-b', 'Same', 'Same']) if chance(rng, 0.3) else tag_text(ctx, rtext(rng, 1, 5))
    d = {'type': kind}
    q = rng.random()
    if q < 0.55:
        d[key] = txt
    elif q < 0.65:
        d['title'] = txt
    elif q < 0.77:
        d[key] = rng.choice(['', ' ', 5, None, ['x'], '\u3000', '\ufeff\t'])
        d['title'] = txt
    elif q < 0.84:
        d[rng.choice([k for k in TITLE_KEYS.values() if k != key])] = txt
    elif q < 0.90:
        d[key] = txt
        d['isMeta'] = rng.choice(FLAG_VALUES)
        d['isSidechain'] = rng.choice(FLAG_VALUES)
    elif q < 0.95:
        d['type'] = rng.choice(['Custom-Title', 'custom_title', 'title', '', 'summary ', 'ai-title '])
        d[key] = txt
    else:
        d[key] = txt
        d['title'] = rtext(rng, 1, 3)
    return decorate(rng, ctx, d, T)


def make_noise(rng, ctx, T):
    q = rng.random()
    if q < 0.18:
        d = {'type': 'system', 'subtype': 'info', 'content': rtext(rng)}
    elif q < 0.30:
        d = {'type': 'file-history-snapshot', 'messageId': 'x', 'snapshot': {'trackedFileBackups': {}}}
    elif q < 0.40:
        d = {'type': 'attachment', 'attachment': {'type': 'text', 'text': rtext(rng)}}
    elif q < 0.50:
        d = {'type': 'progress', 'data': {'type': 'user', 'message': {'content': 'nested user'}, 'isMeta': False}}
    elif q < 0.58:
        d = {'type': rng.choice([5, None, ['user'], {'a': 1}, '', 'User', 'user ']), 'message': {'content': 'x'}}
    elif q < 0.65:
        d = {'message': {'role': 'user', 'content': 'no type'}}
    elif q < 0.71:
        d = {'type': 'queue-operation', 'operation': 'enqueue', 'content': rtext(rng)}
    elif q < 0.77:
        d = {'type': 'user'}
    elif q < 0.82:
        d = {'type': 'assistant'}
    elif q < 0.88:
        d = {'type': 'user', 'message': rng.choice(['str', None, ['x'], 5, {}, {'role': 'user'}])}
    elif q < 0.93:
        d = {'type': 'system', 'x': list(range(rng.randint(100, 3000)))}
    elif q < 0.96:
        d = {'type': 'system'}
        d.update({'k%d' % i: i for i in range(rng.randint(50, 600))})
    else:
        d = {'type': 'last-prompt', 'lastPrompt': rtext(rng)}
    return decorate(rng, ctx, d, T)


MALFORMED = [b'garbage{', b'[1,2]', b'"str"', b'7', b'null', b'true', b'{"type":"user","message":{"content":"x"',
             b'{"type":"user","message":{"content":"x"}} trailing', b'{"a":1}{"b":2}', b'{,}', b"{'type':'user'}",
             b'{"type":"user","message":{"content":"nan"},"n":NaN}', b'{"type":"user","n":01}', b'{"type":"user","n":Infinity}',
             b'{"type":"user","message":{"content":"ctl\x01"}}', b'{"type":"assistant","message":{"content":"tab\there"}}',
             b'{"type":"user","message":{"content":"x"},}', b'{"type":"user","message":{"content":"\\x"}}',
             b'{"type":"user","message":{"content":"\\u12"}}', b'{"type":"user" "message":1}', b'{"type":"user","message":{"content":"q"}',
             b'{"type":"assistant","message":{"content":[{"type":"text","text":"cut']
BLANKS = [b'', b'  ', b'\r', b'\t', b' \r']


def ins(rng, items, x):
    items.insert(rng.randint(0, len(items)), x)


# ---------------------------------------------------------------- emitting JSON lines
DUP_VALUES = [True, False, 'user', 'assistant', 'x', 1, None, '', 5, 'summary']
ESC_NAMES = ['type', 'message', 'content', 'model', 'text', 'isMeta', 'isSidechain', 'timestamp', 'role', 'origin', 'kind',
             'customTitle', 'aiTitle', 'summary', 'title', 'cwd', 'entrypoint', 'tool_result', 'user', 'assistant', 'thinking', 'tool_use']


def emit(rng, d):
    if chance(rng, 0.15):
        pairs = list(d.items())
        rng.shuffle(pairs)
        d = dict(pairs)
    sep = (',', ':') if chance(rng, 0.6) else rng.choice([(', ', ': '), (' , ', ' : '), (',\t', ':\t')])
    ascii_ = chance(rng, 0.3)
    try:
        line = json.dumps(d, ensure_ascii=ascii_, separators=sep).encode('utf-8')
    except UnicodeEncodeError:                      # lone surrogates: \u escapes
        line = json.dumps(d, ensure_ascii=True, separators=sep).encode('ascii')
    line = RAW_RE.sub(rb'\1', line)
    r = rng.random()
    if r < 0.04 and d:
        key = rng.choice([k for k in d if k != 'message'] or ['type'])
        extra = b'"' + str(key).encode() + b'":' + json.dumps(rng.choice(DUP_VALUES)).encode()
        if chance(rng, 0.5):
            line = line[:-1] + b',' + extra + b'}'      # the duplicate comes last and wins
        else:
            line = b'{' + extra + b',' + line[1:]       # the duplicate comes first and loses
    elif r < 0.10:
        name = rng.choice(ESC_NAMES)
        pat = b'"' + name.encode() + b'"'
        i = line.find(pat)
        if i >= 0:
            pos = rng.randrange(len(name))
            esc = (b'\\u%04x' if chance(rng, 0.5) else b'\\u%04X') % ord(name[pos])
            line = line[:i + 1 + pos] + esc + line[i + 2 + pos:]
    if chance(rng, 0.06):
        line = rng.choice([b' ', b'\t', b'  ']) + line + rng.choice([b'', b' ', b'\t'])
    return line


def join_lines(rng, lines):
    mode = rng.random()
    out = bytearray()
    for i, ln in enumerate(lines):
        out += ln
        if i == len(lines) - 1 and chance(rng, 0.1):
            break
        if mode < 0.80:
            out += b'\n'
        elif mode < 0.90:
            out += b'\r\n'
        else:
            out += rng.choice([b'\n', b'\r\n'])
    return bytes(out)


# ---------------------------------------------------------------- trigger injectors (each returns nothing, tags ctx)
def inject_utf8(rng, items, ctx, T):
    bad = [b'\xff\xfe', b'{"type":"user","message":{"content":"bad utf8 \xff"}}', b'{"type":"assistant","message":{"model":"m","content":"\xc3\x28"}}',
           b'{"type":"user","message":{"content":"\xc0\xaf"}}', b'{"type":"user","message":{"content":"trunc \xe2\x82"}}',
           b'{"type":"user","message":{"content":"\xed\xa0\x80"}}', b'{"type":"custom-title","customTitle":"t\xf8"}',
           b'\xef\xbb\xbf{"type":"user","message":{"content":"bom"}}']
    ins(rng, items, rng.choice(bad))
    ctx.add('P1-utf8')


def inject_depth(rng, items, ctx, T):
    n = rng.randint(127, 150)
    opener, closer = rng.choice([(b'[', b']'), (b'[', b']'), (b'{"a":', b'}')])
    head = rng.choice([b'{"type":"user","message":{"content":"deep%d"},"x":' % n, b'{"type":"assistant","message":{"model":"md","content":"deep%d"},"x":' % n,
                       b'{"type":"custom-title","customTitle":"deep%d","x":' % n, b'{"timestamp":1,"x":'])
    ins(rng, items, head + opener * n + b'0' + closer * n + b'}')
    ctx.add('P1-depth')


def string_slots(d):
    out = []
    m = d.get('message')
    if isinstance(m, dict):
        c = m.get('content')
        if isinstance(c, str):
            out.append((m, 'content'))
        elif isinstance(c, list):
            out.extend((b, 'text') for b in c if isinstance(b, dict) and isinstance(b.get('text'), str))
        if isinstance(m.get('model'), str):
            out.append((m, 'model'))
    out.extend((d, k) for k in ('customTitle', 'aiTitle', 'summary', 'title', 'cwd') if isinstance(d.get(k), str))
    return out


def inject_surrogate(rng, items, ctx, T):
    slots = [s for it in items if isinstance(it, dict) for s in string_slots(it)]
    if not slots:
        d = t4.user('seed text')
        ins(rng, items, d)
        slots = string_slots(d)
    box, key = rng.choice(slots)
    s = box[key]
    pos = rng.randint(0, len(s))
    lone = rng.choice(['\ud800', '\udbff', '\udc00', '\udfff', '\ud83d', '\ude00'])
    box[key] = s[:pos] + lone + s[pos:]
    ctx.add('P2-surrogate')


def inject_cut(rng, items, ctx, T):
    txt = ' ' * rng.randint(0, 2) + 'a' * rng.choice([117, 118, 119, 120]) + '\U0001F600' + 'b' * rng.randint(0, 3)
    if chance(rng, 0.5):
        kind = rng.choice(list(TITLE_KEYS))
        ins(rng, items, {'type': kind, TITLE_KEYS[kind]: txt})
    else:
        ins(rng, items, t4.user(txt))
    ctx.add('P2-cut')


def inject_fffd(rng, items, ctx, T):
    k = LIM - rng.randint(1, 4)
    txt = 'a' * k + '\ufffd' * rng.randint(1, 4) + rng.choice(['', '\u20ac', 'a'])
    if chance(rng, 0.5):
        ins(rng, items, t4.user(txt))
    else:
        ins(rng, items, t4.user('p'))
        ins(rng, items, t4.asst(txt, model='mf'))
    ctx.add('P3-fffd')


def inject_p4(rng, items, ctx, T):
    dicts = [it for it in items if isinstance(it, dict)]
    if not dicts:
        d = t4.user('seed text')
        ins(rng, items, d)
        dicts = [d]
    rng.choice(dicts)['timestamp'] = rng.choice(P4_VALUES)
    ctx.add('P4-time')


INJECTORS = [inject_utf8, inject_depth, inject_surrogate, inject_cut, inject_fffd, inject_p4]


# ---------------------------------------------------------------- small transcripts
def gen_small(rng):
    ctx = set()
    T = ts_state(rng)
    items = []
    has_users = not chance(rng, 0.05)
    if chance(rng, 0.08):
        items.append(make_asst(rng, ctx, T))        # a model without a current draft
    for _ in range(rng.choice([0, 1, 1, 2, 2, 3, 4, 5, 8, 12])):
        if chance(rng, 0.2):
            items.append(make_noise(rng, ctx, T))
        if has_users:
            items.append(make_user(rng, ctx, T))
            if chance(rng, 0.06):
                items.append(make_user(rng, ctx, T))
        if chance(rng, 0.8):                         # else an unanswered prompt
            for _ in range(rng.choice([1, 1, 1, 2, 3, 4])):
                items.append(make_asst(rng, ctx, T))
                if chance(rng, 0.1):
                    items.append(make_noise(rng, ctx, T))
            if chance(rng, 0.12):
                items.append(t4.user([t4.tool_result(rtext(rng, 1, 3))]))
                items.append(make_asst(rng, ctx, T))
        if chance(rng, 0.05) and items:
            items.append(copy.deepcopy(items[-1]))
    for _ in range(rng.choice([0, 0, 0, 1, 1, 2, 3, 4])):
        ins(rng, items, make_title(rng, ctx, T))
    if chance(rng, 0.06):
        for _ in range(rng.randint(1, 3)):
            bad = rng.choice(MALFORMED)
            ins(rng, items, bad)
    if chance(rng, 0.08):
        ins(rng, items, rng.choice(BLANKS))
    dicts = [it for it in items if isinstance(it, dict)]
    if len(dicts) >= 2 and chance(rng, 0.08):       # first present-empty head field, later real values
        dicts[0]['cwd'], dicts[0]['entrypoint'] = '', ''
        dicts[-1]['cwd'], dicts[-1]['entrypoint'] = '/real', 'cli'
    if chance(rng, 0.10) and len(items) > 1:
        for _ in range(rng.randint(1, 3)):
            i = rng.randrange(len(items) - 1)
            items[i], items[i + 1] = items[i + 1], items[i]
    if chance(rng, 0.01):
        n = rng.randint(100, 126)                    # deep, but within the limit
        items.append(b'{"type":"user","message":{"content":"ok deep"},"x":' + b'[' * n + b'0' + b']' * n + b'}')
    for fn in INJECTORS:
        if rng.random() < INJECT_RATE:
            fn(rng, items, ctx, T)
    lines = [it if isinstance(it, bytes) else emit(rng, it) for it in items]
    return join_lines(rng, lines), ctx, 'small'


# ---------------------------------------------------------------- large transcripts
def sized_text(rng, nbytes, style):
    ch = {'a': 'a', 'e': 'é', 'eur': '€', 'emo': '😀', 'fffd': '\ufffd'}[style]
    w = len(ch.encode())
    pre = rng.randint(0, min(3, nbytes))
    k = (nbytes - pre) // w
    s = 'a' * pre + ch * k + 'a' * (nbytes - pre - k * w)
    assert len(s.encode()) == nbytes
    return s


def big_prompt_reply(rng, ctx, T):
    items = [t4.user('first', timestamp=1), t4.asst('r', model='mb', timestamp=2)]
    for _ in range(rng.randint(1, 3)):
        style = rng.choice(['a', 'a', 'e', 'eur', 'emo', 'fffd'])
        if style == 'fffd':
            ctx.add('P3-fffd')
        items.append(t4.user(sized_text(rng, LIM + rng.randint(-4, 4), style)))
        style = rng.choice(['a', 'e', 'eur', 'emo', 'fffd'])
        if style == 'fffd':
            ctx.add('P3-fffd')
        parts = rng.choice([1, 1, 2, 3])
        if parts == 1:
            items.append(t4.asst(sized_text(rng, LIM + rng.randint(-4, 4), style), model='mb'))
        else:                                       # the reply grows over several lines (separators count)
            left = LIM + rng.randint(-4, 4)
            for _ in range(parts - 1):
                n = rng.randint(1, left)
                items.append(t4.asst(sized_text(rng, n, style) if style != 'fffd' else 'a' * n, model='mb'))
                left = max(left - n, 1)
            items.append(t4.asst(sized_text(rng, left + rng.randint(0, 5), style), model='mb'))
        items.append(t4.asst('late', timestamp=9))
    return b''.join(t4.L(it) for it in items), 'big-prompt-reply'


def big_drafts(rng, ctx, T):
    n = rng.choice([199, 200, 201, 202, 250, 399, 401, 450])
    items = []
    for i in range(n):
        items.append(t4.user(('p%d-' % i).ljust(rng.choice([5, 20]), 'p'), timestamp=1000 + i))
        if chance(rng, 0.9):
            items.append(t4.asst(('r%d-' % i).ljust(rng.choice([5, 30]), 'r'), model='cm', timestamp=2000 + i))
        if chance(rng, 0.05):
            items.append(t4.asst([t4.tool_use()]))
    return b''.join(t4.L(it) for it in items), 'big-drafts'


def big_tools(rng, ctx, T):
    items = [t4.user('q')]
    for _ in range(rng.randint(1, 4)):
        k = rng.choice([100, 255, 256, 257, 1000, 2000])
        items.append(t4.asst([t4.tool_use('X', 't%d' % (i % 3)) for i in range(k)] + [t4.tx('done')]))
    items.append(t4.user('q2'))
    items.append(t4.asst([t4.tool_use() for _ in range(rng.randint(1, 800))]))
    return b''.join(t4.L(it) for it in items), 'big-tools'


def big_total(rng, ctx, T):
    pairs = rng.choice([30, 31, 32, 33, 34, 40])
    items = [t4.user('tiny'), t4.asst('t')] if chance(rng, 0.5) else []
    for i in range(pairs):
        d = rng.choice([0, 0, 0, 1, 2, 5])
        items += [t4.user('a' * (LIM - d)), t4.asst('b' * (LIM - rng.choice([0, 0, 1, 3])))]
    if chance(rng, 0.5):
        items += [t4.user('n'), t4.asst('m')]
    return b''.join(t4.L(it) for it in items), 'big-total'


def big_line(rng, ctx, T):
    """A parsed or dropped (oversized) line around the 1 MiB cap, with the shapes of the A4 drop cases."""
    head = t4.L(t4.user('first'), t4.asst('r1', model='m0'))
    tail = t4.L(t4.asst('orphan', model='m-orphan', timestamp=7), t4.asst([t4.tool_use()]), t4.user('second'), t4.asst('r2', model='m2', timestamp=8))
    total = LINE + rng.choice([-2, -1, 0, 1, 2])
    shapes = [(t4.USER_PRE, t4.USER_SUF), (b'{"isMeta":true,"type":"user","message":{"content":"', t4.USER_SUF),
              (b'{"type":"user","isSidechain":true,"message":{"content":"', t4.USER_SUF),
              (b'{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t","content":"', b'"}]}}'),
              (b'{"type":"user","message":{"content":[{"type":"text","text":"', b'"},{"type":"tool_result"}]}}'),
              (b'{"pad":"' + b'x' * 9000 + b'","type":"user","message":{"content":"', t4.USER_SUF),
              (b'{"type":"assistant","message":{"model":"mb","content":"', t4.USER_SUF),
              (b'{"type":"assistant","message":{"type":"user","content":"', t4.USER_SUF),
              (b'{"message":{"content":"', t4.USER_SUF), (b'{"typ\\u0065":"user","message":{"content":"', t4.USER_SUF),
              (b'{"type" \t:\n "user","message":{"content":"', t4.USER_SUF),
              (b'{"type":"user","bad":"\xff\xfe","message":{"content":"', t4.USER_SUF)]
    pre, suf = rng.choice(shapes)
    if b'\xff' in pre:
        ctx.add('P1-utf8')
    ending = rng.choice([b'\n', b'\r\n'])
    big = t4.exact(pre, suf, total) + ending
    body = head + big + (tail if chance(rng, 0.8) else b'')
    if chance(rng, 0.25):
        body += t4.exact(t4.USER_PRE, t4.USER_SUF, LINE + rng.choice([-1, 0, 1]))       # an unterminated 1 MiB tail
    return body, 'big-line'


def big_window(rng, ctx, T, delta, cut):
    """A window of exactly WINDOW+delta bytes made of one transcript, spaces-only filler lines, a short closing transcript."""
    first = t4.L(*[x for i in range(rng.randint(1, 4)) for x in (t4.user('w%d é' % i, timestamp=1000 + i), t4.asst('r%d' % i, model='mw', timestamp=2000 + i))])
    last = t4.L(t4.user('closing'), t4.asst('done', timestamp=3000))
    rem = WINDOW + delta - len(first) - len(last)
    parts = [first]
    while rem > 0:
        m = min(rem, LINE - rng.choice([0, 0, 1, 2]))
        parts.append(b' ' * (m - 1) + b'\n')
        rem -= m
        if chance(rng, 0.3) and rem > 600:
            parts.append(t4.L(t4.user('mid', timestamp=1500), t4.asst('mid-r')))
            rem -= len(parts[-1])
    parts.append(last)
    data = b''.join(parts)
    assert len(data) == WINDOW + delta, (len(data), delta)
    return data, 'big-window%+d' % delta


# ---------------------------------------------------------------- generator
def generate(seed, n):
    """Deterministic: list of (name, op, flag, data, triggers); each item is one generated transcript."""
    rng = random.Random(seed)
    budget = {'line': 8, 'win': 4, 'wpad': 4}
    out = []
    ops = ['window', 'window', 'head', 'window', 'tail', 'window', 'window', 'head', 'window', 'tail']
    for i in range(n):
        op = ops[i % 10]
        ctx = set()
        flag = 1 if rng.random() < 0.10 else 0
        T = ts_state(rng)
        label = 'small'
        if i % 100 == 99:                            # ~1% large transcripts (window only)
            op = 'window'
            flag = 0
            k = (i // 100) % 8
            if k == 6 and budget['line'] > 0:
                budget['line'] -= 1
                data, label = big_line(rng, ctx, T)
            elif k == 7 and budget['win'] > 0:
                budget['win'] -= 1
                delta, flag = rng.choice([(0, 0), (0, 1), (-1, 0), (1, 0)])
                data, label = big_window(rng, ctx, T, delta, flag)
            else:
                data, label = [big_prompt_reply, big_drafts, big_tools, big_total][k % 4](rng, ctx, T)
            if chance(rng, 0.2) and flag == 0 and not label.startswith('big-window'):
                data = b'tail of a cut line"}}\n' + data
                flag = 1
        else:
            data, ctx, label = gen_small(rng)
        padded = len(data) in (EDGE, WINDOW) and flag
        if flag and not padded:
            if op == 'window':
                if budget['wpad'] > 0 and len(data) < WINDOW:
                    budget['wpad'] -= 1
                    data = t4.pad_for(op, flag, data)
                else:
                    label += ' nopad'
            else:
                data = t4.pad_for(op, flag, data)
        out.append((f'{op}{flag}: gen{i:05d} {label}', op, flag, data, sorted(ctx)))
    return out


def build_entries(seed, n):
    entries = []
    for name, op, flag, data, want in t4.fixtures():
        entries.append({'name': name, 'op': op, 'flag': flag, 'data': data, 'expected': want, 'triggers': [], 'seed': seed, 'fixed': True})
    nfixed = len(entries)
    for name, op, flag, data, triggers in generate(seed, n):
        try:
            want = oracle.api(op, flag, data)
        except Exception as exc:                     # an oracle defect must name the transcript
            raise RuntimeError(f'oracle failed on {name}: {exc!r}') from exc
        entries.append({'name': name, 'op': op, 'flag': flag, 'data': data, 'expected': want, 'triggers': triggers, 'seed': seed, 'fixed': False})
    names = [e['name'] for e in entries]
    assert len(set(names)) == len(names), 'corpus names must be unique'
    return entries, nfixed


SHARD_BYTES = 256 << 20          # a JS string holds at most 0x1fffffe8 chars, so reference.mjs reads the corpus in shards


def write_corpus(path, entries):
    """Write corpus-NN.json shards of at most about SHARD_BYTES each; return their paths."""
    WORK.mkdir(parents=True, exist_ok=True)
    for old in WORK.glob('corpus-*.json'):
        old.unlink()
    paths, f, size = [], None, 0
    for e in entries:
        rec = json.dumps({'name': e['name'], 'op': e['op'], 'flag': e['flag'], 'data': base64.b64encode(e['data']).decode(),
                          'expected': e['expected'], 'triggers': e['triggers'], 'seed': e['seed'], 'fixed': e['fixed']})
        if f is None or size + len(rec) > SHARD_BYTES:
            if f:
                f.write(']')
                f.close()
            paths.append(path.parent / f'corpus-{len(paths):02d}.json')
            f, size = open(paths[-1], 'w'), 0
            f.write('[')
        elif size:
            f.write(',')
        f.write(rec)
        size += len(rec) + 1
    if f:
        f.write(']')
        f.close()
    return paths


# ---------------------------------------------------------------- running pairs
def sha256(path):
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def tool_version(cmd):
    try:
        p = subprocess.run([str(x) for x in cmd], capture_output=True, text=True, timeout=30)
        return (p.stdout or p.stderr).strip().splitlines()[0]
    except Exception:
        return None


def build_adapter(run):
    """The str adapter crate build of test_a4.main (UTF-8 representation conversion)."""
    target = WORK / 'str-adapter'
    cargo = shutil.which('cargo') or str(Path.home() / '.cargo/bin/cargo')
    run([cargo, 'build', '--release', '--offline', '--quiet', '--manifest-path', t4.JSON_DIR / 'str_adapter/Cargo.toml', '--target-dir', target])
    rlib, deps = target / 'release/libpruv_str.rlib', target / 'release/deps'
    return ['--rust-extern', f'pruv_str={rlib}', '--rust-search', str(deps)], ['--extern', f'pruv_str={rlib}', '-L', f'dependency={deps}']


def run_pair(g2, run, key, entries, flags, rustflags, chunk=2000, timeout=3600):
    compiler, backend = key.split('/')
    res = {'passed': 0, 'failed': 0, 'seconds': 0.0, 'compile_seconds': 0.0, 'runner_seconds': 0.0, 'errors': [], 'mismatches': []}
    t0 = time.perf_counter()
    try:
        work = WORK / f'{compiler}_{backend}'
        work.mkdir(parents=True, exist_ok=True)
        compiled = g2.compile_pruv(compiler, str(HERE / 'q_root.pruv'), str(work), backend, flags)
        if compiled['rc'] != 0:
            raise RuntimeError('compile/verify failed: ' + str(compiled['errors'] or compiled['stderr']))
        harness = work / 'main.rs'
        harness.write_text(t4.HARNESS.replace('@SOL@', compiled['rs']))
        extra = []
        if compiled['ll']:
            extra, error = g2.build_llvm_objects(compiled['ll'], 'q', str(work))
            if error:
                raise RuntimeError(error)
        exe = work / 'runner'
        run([g2.RUSTC, '-O', '--edition', '2021', harness, '-o', exe] + extra + rustflags)
        res['compile_seconds'] = time.perf_counter() - t0
    except Exception as exc:
        res['errors'].append(f'build: {exc}')
        res['failed'] = len(entries)
        res['seconds'] = time.perf_counter() - t0
        return res
    for start in range(0, len(entries), chunk):
        part = entries[start:start + chunk]
        payload = ''.join(f'{e["op"]} {e["flag"]}|{t4.enc_bytes(e["data"])}\n' for e in part).encode()
        t1 = time.perf_counter()
        try:
            p = subprocess.run([str(exe)], input=payload, capture_output=True, timeout=timeout)
            res['runner_seconds'] += time.perf_counter() - t1
            if p.returncode:
                raise RuntimeError(f'runner exit {p.returncode}: {p.stderr.decode(errors="replace")[:500]}')
            got = p.stdout.decode().splitlines()
            if len(got) != len(part):
                raise RuntimeError(f'{len(got)} answers for {len(part)} items')
        except Exception as exc:                     # crash / timeout / protocol error: the whole chunk fails
            res['runner_seconds'] += time.perf_counter() - t1
            res['errors'].append(f'chunk at {start}: {exc!r}')
            res['failed'] += len(part)
            continue
        for e, g in zip(part, got):
            want = a3.enc(e['expected'])
            if want == g:
                res['passed'] += 1
            else:
                res['failed'] += 1
                res['mismatches'].append((e['name'], want[:240], g[:240]))
    res['seconds'] = time.perf_counter() - t0
    return res


def main_run(argv):
    ap = argparse.ArgumentParser(prog='q.py')
    ap.add_argument('--count', type=int, default=20000)
    ap.add_argument('--seed', type=int, default=20261114)
    ap.add_argument('--pairs', default=','.join(PAIRS))
    args = ap.parse_args(argv)
    pairs = [p.strip() for p in args.pairs.split(',') if p.strip()]
    for p in pairs:
        if p not in PAIRS:
            ap.error(f'unknown pair {p}')
    oracle.selfcheck()
    t0 = time.perf_counter()
    entries, nfixed = build_entries(args.seed, args.count)
    t4.hand_checks([(e['name'], e['op'], e['flag'], e['data'], e['expected']) for e in entries[:nfixed]])
    shards = write_corpus(WORK / 'corpus.json', entries)
    (WORK / 'corpus_shards.txt').write_text(','.join(str(x) for x in shards) + '\n')
    (WORK / 'corpus_index.json').write_text(json.dumps({e['name']: {'triggers': e['triggers'], 'fixed': e['fixed']} for e in entries}))
    gen = entries[nfixed:]
    by_op, by_trigger = {}, {}
    for e in gen:
        by_op[e['op']] = by_op.get(e['op'], 0) + 1
        for t in e['triggers']:
            by_trigger[t] = by_trigger.get(t, 0) + 1
    counts = {'generated': len(gen), 'fixed': nfixed, 'by_op': by_op, 'by_trigger': by_trigger,
              'flagged': sum(1 for e in gen if e['flag']), 'unpadded_flagged': sum(1 for e in gen if e['name'].endswith(' nopad')),
              'untagged': sum(1 for e in gen if not e['triggers']), 'bytes': sum(len(e['data']) for e in gen),
              'max_bytes': max([len(e['data']) for e in gen] or [0])}
    print(f'{nfixed} fixed + {len(gen)} generated items (seed {args.seed}; {len(shards)} corpus shards written, {time.perf_counter() - t0:.1f}s)', flush=True)
    print(f'  by op {by_op}, by trigger {by_trigger}', flush=True)
    g2, run = t4.configure()
    flags, rustflags = build_adapter(run)
    results, failed = {}, False
    for key in pairs:
        res = run_pair(g2, run, key, entries, flags, rustflags)
        results[key] = {k: v for k, v in res.items() if k != 'mismatches'}
        results[key]['first_mismatches'] = [m[0] for m in res['mismatches'][:10]]
        print(f'{key}: {res["passed"]}/{len(entries)} passed ({res["seconds"]:.1f}s wall, {res["runner_seconds"]:.1f}s runner, '
              f'{res["compile_seconds"]:.1f}s build)', flush=True)
        for name, want, got in res['mismatches'][:10]:
            print(f'  MISMATCH {name}: expected {want}, got {got}', flush=True)
        for err in res['errors']:
            print(f'  ERROR {err}', file=sys.stderr, flush=True)
        failed |= res['failed'] > 0 or bool(res['errors'])
    hashes = {p.name: sha256(p) for p in sorted(HERE.glob('*.pruv'))}
    for extra in ('oracle.py', 'q.py', 'test_a4.py'):
        hashes[extra] = sha256(HERE / extra)
    versions = {'python': sys.version.split()[0], 'rustc': tool_version([g2.RUSTC, '--version'])}
    out = {'seed': args.seed, 'counts': counts, 'pairs': results, 'sha256': hashes, 'versions': versions,
           'selected_pairs': pairs, 'total_items': len(entries)}
    (WORK / 'q_results.json').write_text(json.dumps(out, indent=1))
    print(f'q_results.json written; {"FAILED" if failed else "all selected pairs agree with the oracle"}', flush=True)
    return int(failed)


# ---------------------------------------------------------------- classify
FIXED_POLICY = [('malformed middle', ['P1-utf8', 'P1-depth']), ('only malformed', ['P1-utf8', 'P1-depth']),
                ('depth 128', ['P1-utf8', 'P1-depth']), ('depth 129', ['P1-utf8', 'P1-depth']),
                ('lone surrogate', ['P2-surrogate', 'P2-cut']), ('title emoji cut', ['P2-surrogate', 'P2-cut']),
                ('lone surrogates policy', ['P2-surrogate', 'P2-cut']),
                ('prompt cap multibyte cuts', ['P3-fffd']), ('prompt fffd at cap', ['P3-fffd']),
                ('timestamp forms', ['P4-time']), ('lastAt last accepted', ['P4-time'])]
TIME_LEAVES = ('createdAt', 'completedAt', 'lastAt')


def path_of(where):
    m = re.match(r'\s*(/[^\s:]*)', where)
    return m.group(1) if m else ''


def allowed(trigger, path):
    top = path.split('/')[1] if path.count('/') >= 1 and path else ''
    leaf = path.rsplit('/', 1)[-1]
    if trigger in ('P1-utf8', 'P1-depth'):
        return True                                  # a skipped line changes attachment: any field
    if trigger in ('P2-surrogate', 'P2-cut'):
        return top in ('title', 'model', 'cwd', 'entrypoint', 'turns', 'omittedBefore')
    if trigger == 'P3-fffd':
        return top in ('title', 'turns', 'omittedBefore')
    if trigger == 'P4-time':
        return leaf in TIME_LEAVES
    return False


def triggers_of(entry):
    if entry.get('fixed'):
        for sub, pol in FIXED_POLICY:
            if sub in entry['name']:
                return pol
        return []
    return entry.get('triggers', [])


def main_classify(files):
    if not files:
        print('usage: q.py classify REF_OUT.json [...]', file=sys.stderr)
        return 2
    index = WORK / 'corpus_index.json'              # small name -> triggers/fixed index written next to corpus.json
    if index.exists():
        corpus = {k: {'name': k, **v} for k, v in json.loads(index.read_text()).items()}
    else:
        corpus = {e['name']: e for sh in sorted(WORK.glob('corpus-*.json')) for e in json.loads(sh.read_text())}
    report, bad = {}, False
    for fname in files:
        results = json.loads(Path(fname).read_text())['results']
        counts = {'match': 0, 'explained': 0, 'unexplained': 0, 'ts-error': 0, 'skipped': 0}
        items, unexplained = [], []
        for r in results:
            st = r['status']
            if st == 'match':
                counts['match'] += 1
                continue
            if st in ('skipped', 'ts-error'):
                counts[st] += 1
                items.append({'name': r['name'], 'class': st, 'detail': r.get('reason') or r.get('error', '')[:300]})
                continue
            entry = corpus.get(r['name'])
            trig = triggers_of(entry) if entry else []
            paths = [path_of(w) for w in r.get('where', [])]
            ok = bool(trig) and all(any(allowed(t, p) for t in trig) for p in paths)
            counts['explained' if ok else 'unexplained'] += 1
            if not ok:
                unexplained.append(r['name'])
            items.append({'name': r['name'], 'class': 'explained' if ok else 'unexplained', 'triggers': trig, 'where': r.get('where', [])})
        print(f'{fname}: match {counts["match"]}, explained by policy {counts["explained"]}, UNEXPLAINED {counts["unexplained"]}, '
              f'ts-error {counts["ts-error"]}, skipped {counts["skipped"]}')
        for name in unexplained:
            print(f'  UNEXPLAINED {name}')
        report[fname] = {'counts': counts, 'items': items}
        bad |= bool(unexplained) or counts['ts-error'] > 0
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / 'classified.json').write_text(json.dumps(report, indent=1))
    return int(bad)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'classify':
        raise SystemExit(main_classify(sys.argv[2:]))
    raise SystemExit(main_run(sys.argv[1:]))
