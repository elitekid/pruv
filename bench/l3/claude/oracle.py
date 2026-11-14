"""L3-1 Python oracle of the full pure Claude import API (head, tail, window packets).

Independent of the Pruv code and of the TS reference. It follows docs/CLAUDE_IMPORT_SPEC.md with the policies P1-P5:
strict UTF-8 and JSON (Python's decoder, ordered pairs, raw number wrappers, last-wins keys, depth <= 128),
ECMAScript whitespace, lone surrogates in values -> U+FFFD, longest whole-scalar clipping, the restricted iso_of.
Reused from the earlier batches (same repository, no generated Pruv code):
  test_a1.py  ECMAScript trim, one_line, human_text, titles, dropped-user patterns, JSON object wrappers
  test_a2.py  o_parse (raw number wrappers), o_iso (restricted timestamps), o_head, o_tail, packet layout
  test_a3.py  clip, collector caps
The window collector is modelled as an ordinary list of drafts; the suffix is chosen from its end.

    api(op, flag, data) -> [int]   op in head | tail | window; flag = cut_after (head) / cut_before (tail, window)
Result: [0, 14, turn_slots, byte_len, ...meta, ...turns, ...text bytes] or [code, position].
"""
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def _load(name, file):
    cached = sys.modules.get(name)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


a2 = _load('test_a2_oracle', 'test_a2.py')
a1 = a2.a1                      # the A1 oracle instance test_a2 already uses (shared Obj class)
a3 = _load('test_a3_oracle', 'test_a3.py')

EDGE, WINDOW, LINE, DROP = 65536, 8388608, 1048576, 8192
LIM, TOTAL, MAXTURNS = a3.LIM, a3.TOTAL, a3.MAXTURNS
SYNTHETIC = '<synthetic>'


# ---------------- window framing (independent of framing.pruv) ----------------
def window_events(data, cut_before):
    """File-order events of an import window: ('line', bytes) or ('drop', 8 KiB prefix of an oversized line)."""
    pos = 0
    if cut_before:
        i = data.find(b'\n')
        pos = len(data) if i < 0 else i + 1          # the whole first range goes, even if the window starts on a boundary
    events = []
    while pos < len(data):
        i = data.find(b'\n', pos)
        if i < 0:
            if len(data) - pos > LINE:               # an unterminated range over the cap is still dropped once
                events.append(('drop', data[pos:pos + DROP]))
            break                                    # a shorter unterminated tail is ignored
        raw = data[pos:i]
        if len(raw) > LINE:                          # the raw length counts a CR
            events.append(('drop', raw[:DROP]))
        else:
            events.append(('line', raw[:-1] if raw.endswith(b'\r') else raw))
        pos = i + 1
    return events


# ---------------- collector (plain list of drafts) ----------------
class Collector:
    def __init__(self):
        self.drafts, self.cur, self.lost = [], None, False

    def begin(self, prompt, created):
        raw = prompt.encode('utf-8')
        cur = {'prompt': a3.clip(raw, LIM), 'reply': b'', 'used': 0, 'tools': 0,
               'created': created, 'completed': None, 'clipped': len(raw) > LIM or self.lost}
        self.lost = False
        self.cur = cur
        self.drafts.append(cur)

    def skip_user(self):
        self.cur, self.lost = None, True

    def answer(self, text, at):
        cur = self.cur
        if cur is None:
            return
        if at:
            cur['completed'] = at
        raw = text.encode('utf-8')
        if not raw or cur['used'] >= LIM:
            return
        piece = b'\n\n' + raw if cur['reply'] else raw
        room = LIM - cur['used']
        if len(piece) <= room:
            cur['reply'] += piece
            cur['used'] += len(piece)
        else:
            cur['reply'] += a3.clip(piece, room)
            cur['used'] = LIM
            cur['clipped'] = True

    def tool(self):
        if self.cur is not None:
            self.cur['tools'] += 1

    def finish(self):
        kept, total = [], 0
        for d in reversed(self.drafts):
            if len(kept) >= MAXTURNS:
                break
            size = len(d['prompt']) + len(d['reply'])
            if total + size > TOTAL:
                break
            total += size
            kept.append(d)
        kept.reverse()
        return kept, len(kept) < len(self.drafts)


def consume(e, col, state):
    """The readClaude loop body for one parsed object; state = {'rank', 'title', 'model'}."""
    found = a1.o_title(e)
    if found and found[0] >= state['rank']:
        state['rank'], state['title'] = found[0], found[1]
    prompt = a1.o_human(e)
    at = a2.o_iso(e.get('timestamp'))
    if prompt is not None:
        col.begin(prompt, at)
        return
    if e.get('type') != 'assistant' or e.get('isSidechain') is True:
        return
    msg = e.get('message') if isinstance(e.get('message'), dict) else None
    model = a1.S(msg.get('model')) if msg is not None else None
    if model == SYNTHETIC and e.get('isApiErrorMessage') is not True:
        return
    if model and model != SYNTHETIC:
        state['model'] = model
    content = msg.get('content') if msg is not None else None
    if isinstance(content, str):
        col.answer(a1.fix(content), at)
        return
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get('type') == 'text' and isinstance(block.get('text'), str):
            col.answer(a1.fix(block['text']), at)
        elif block.get('type') == 'tool_use':
            col.tool()


def window_packet(data, cut_before):
    if len(data) > WINDOW:
        return [1, 0]
    col, state = Collector(), {'rank': 0, 'title': None, 'model': None}
    for kind, payload in window_events(data, cut_before):
        if kind == 'drop':
            if a1.o_dropped(payload):
                col.skip_user()
            continue
        e = a2.o_parse(payload)
        if e is not None:
            consume(e, col, state)
    kept, trimmed = col.finish()
    title = a1.o_one_line(state['title'], 120) if state['rank'] > 0 else ''
    text = bytearray()

    def put(b):
        start = len(text)
        text.extend(b)
        return [start, len(b)]

    title_ref = put(title.encode('utf-8')) if title else [-1, 0]
    model_ref = [-1, 0]
    # packing order: title, (cwd, entrypoint, lastAt absent), model, then every turn
    if state['model']:
        model_ref = put(state['model'].encode('utf-8'))
    turns = []
    for d in kept:
        rec = put(d['prompt']) + put(d['reply'])
        rec += put(d['created'].encode()) if d['created'] else [-1, 0]
        rec += put(d['completed'].encode()) if d['completed'] else [-1, 0]
        turns += rec + [d['tools'], int(d['clipped'])]
    meta = [1, 2, int(bool(cut_before) or trimmed), len(kept)] + title_ref + [-1, 0, -1, 0, -1, 0] + model_ref
    return [0, 14, len(turns), len(text)] + meta + turns + list(text)


def api(op, flag, data):
    if op == 'head':
        return a2.o_head(data, bool(flag))
    if op == 'tail':
        return a2.o_tail(data, bool(flag))
    if op == 'window':
        return window_packet(data, bool(flag))
    raise ValueError(op)


# ---------------- packet decoding (for readable diffs and the reference comparison) ----------------
def decode(packet):
    """Packet -> dict of the selected projection (strings as Python str; absent keys omitted)."""
    if packet[0] != 0:
        return {'error': packet[0], 'position': packet[1]}
    ts, n = packet[2], packet[3]
    meta, turns = packet[4:18], packet[18:18 + ts]
    text = bytes(packet[18 + ts:18 + ts + n])

    def ref(i):
        s, l = meta[i], meta[i + 1]
        return None if s == -1 else text[s:s + l].decode('utf-8')

    mode = meta[1]
    out = {}
    if mode == 0:
        out = {k: v for k, v in (('title', ref(4)), ('cwd', ref(6)), ('entrypoint', ref(8))) if v is not None}
    elif mode == 1:
        out = {k: v for k, v in (('title', ref(4)), ('lastAt', ref(10))) if v is not None}
    else:
        out = {'omittedBefore': bool(meta[2]), 'turns': []}
        for k, v in (('model', ref(12)), ('title', ref(4))):
            if v is not None:
                out[k] = v
        for i in range(meta[3]):
            r = turns[10 * i:10 * i + 10]
            t = {'prompt': text[r[0]:r[0] + r[1]].decode('utf-8'), 'reply': text[r[2]:r[2] + r[3]].decode('utf-8'), 'tools': r[8]}
            if r[4] != -1:
                t['createdAt'] = text[r[4]:r[4] + r[5]].decode('utf-8')
            if r[6] != -1:
                t['completedAt'] = text[r[6]:r[6] + r[7]].decode('utf-8')
            if r[9]:
                t['clipped'] = True
            out['turns'].append(t)
    return out


def selfcheck():
    """Hand-derived expectations that keep this oracle honest."""
    B = lambda s: list(s.encode())
    u = b'{"type":"user","message":{"content":"hi"}}\n'
    a = b'{"type":"assistant","timestamp":5,"message":{"model":"m","content":"yo"}}\n'
    got = window_packet(u + a, False)
    assert got[:4] == [0, 14, 10, 5 + 24], got[:4]
    assert got[4:18] == [1, 2, 0, 1, -1, 0, -1, 0, -1, 0, -1, 0, 0, 1], got[4:18]
    assert bytes(got[28:]) == b'mhiyo1970-01-01T00:00:05.000Z', bytes(got[28:])
    assert got[18:28] == [1, 2, 3, 2, -1, 0, 5, 24, 0, 0], got[18:28]
    # cut_before drops the first range even on a boundary; an unterminated tail is ignored
    got = window_packet(u + u + b'{"type":"user","message":{"content":"tail"}}', True)
    assert got[2:4] == [10, 2] and got[6] == 1 and bytes(got[28:]) == b'hi', got
    assert window_packet(b'', False) == [0, 14, 0, 0, 1, 2, 0, 0, -1, 0, -1, 0, -1, 0, -1, 0, -1, 0]
    # synthetic model without the error flag suppresses the whole entry, with it only hides the model
    s1 = b'{"type":"assistant","message":{"model":"<synthetic>","content":"x"}}\n'
    s2 = b'{"type":"assistant","isApiErrorMessage":true,"message":{"model":"<synthetic>","content":"x"}}\n'
    assert decode(window_packet(u + s1, False))['turns'][0]['reply'] == ''
    d = decode(window_packet(u + s2, False))
    assert d['turns'][0]['reply'] == 'x' and 'model' not in d, d
    # oversized user line: skip_user, so the next draft is clipped and orphan replies are dropped
    big = b'{"type":"user","message":{"content":"' + b'a' * LINE + b'"}}\n'
    d = decode(window_packet(u + big + a + u, False))
    assert [t.get('clipped') for t in d['turns']] == [None, True] and d['turns'][0]['reply'] == '' and d['model'] == 'm', d
    assert a1.o_dropped(b'{"type":"user"}') and not a1.o_dropped(b'{"type":"user","isMeta":true}')
    assert api('window', 0, b'a' * (WINDOW + 1)) == [1, 0]
    assert decode(api('head', 0, b'{"cwd":"/a"}\n')) == {'cwd': '/a'}
