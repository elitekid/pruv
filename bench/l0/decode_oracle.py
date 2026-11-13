"""Independent reference for Lair decodeBytes, written from the WHATWG Encoding Standard
algorithms (UTF-8, UTF-16LE/BE and EUC-KR decoders, plus the TextDecoder BOM rule).
It does not call Python codecs, so it does not share code with TextDecoder or encoding_rs.
The EUC-KR index is data/index-euc-kr.txt, downloaded from encoding.spec.whatwg.org
(SHA-256 89af20dd867c84cefb710b1790229786cfef2bf11916361a210d81b90381e267)."""
import hashlib
import random
from pathlib import Path

INDEX_FILE = Path(__file__).resolve().parent / 'data' / 'index-euc-kr.txt'
INDEX_SHA256 = '89af20dd867c84cefb710b1790229786cfef2bf11916361a210d81b90381e267'
ERR = 0xFFFD


def load_index():
    raw = INDEX_FILE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != INDEX_SHA256:
        raise RuntimeError('index-euc-kr.txt does not match the recorded SHA-256')
    table = {}
    for line in raw.decode().splitlines():
        if line and not line.startswith('#'):
            pointer, code = line.split('\t')[:2]
            table[int(pointer)] = int(code, 16)
    return table


INDEX = load_index()


def utf8(data, fatal):
    """WHATWG UTF-8 decoder. Returns a list of code points, or None on error when fatal."""
    out, cp, needed, seen, lower, upper = [], 0, 0, 0, 0x80, 0xBF
    i = 0
    while i < len(data):
        b = data[i]
        if needed == 0:
            i += 1
            if b <= 0x7F:
                out.append(b)
            elif 0xC2 <= b <= 0xDF:
                needed, cp = 1, b & 0x1F
            elif 0xE0 <= b <= 0xEF:
                lower = 0xA0 if b == 0xE0 else 0x80
                upper = 0x9F if b == 0xED else 0xBF
                needed, cp = 2, b & 0xF
            elif 0xF0 <= b <= 0xF4:
                lower = 0x90 if b == 0xF0 else 0x80
                upper = 0x8F if b == 0xF4 else 0xBF
                needed, cp = 3, b & 0x7
            else:
                if fatal:
                    return None
                out.append(ERR)
            continue
        if not lower <= b <= upper:
            cp = needed = seen = 0
            lower, upper = 0x80, 0xBF
            if fatal:
                return None
            out.append(ERR)
            continue  # the byte is read again
        lower, upper = 0x80, 0xBF
        cp = (cp << 6) | (b & 0x3F)
        seen += 1
        i += 1
        if seen == needed:
            out.append(cp)
            cp = needed = seen = 0
    if needed:
        if fatal:
            return None
        out.append(ERR)
    return out


def utf16(data, big):
    """WHATWG shared UTF-16 decoder, replacement mode."""
    out, lead_surrogate = [], None
    i = 0
    while i + 1 < len(data):
        a, b = data[i], data[i + 1]
        unit = (a << 8) | b if big else (b << 8) | a
        if lead_surrogate is not None:
            lead, lead_surrogate = lead_surrogate, None
            if 0xDC00 <= unit <= 0xDFFF:
                out.append(0x10000 + ((lead - 0xD800) << 10) + (unit - 0xDC00))
                i += 2
                continue
            out.append(ERR)
            continue  # the unit is read again
        i += 2
        if 0xD800 <= unit <= 0xDBFF:
            lead_surrogate = unit
        elif 0xDC00 <= unit <= 0xDFFF:
            out.append(ERR)
        else:
            out.append(unit)
    if lead_surrogate is not None or i < len(data):
        out.append(ERR)  # one error for a pending lead byte and/or lead surrogate
    return out


def euc_kr(data):
    """WHATWG EUC-KR decoder, replacement mode."""
    out, lead = [], 0
    i = 0
    while i < len(data):
        b = data[i]
        i += 1
        if lead:
            pointer = (lead - 0x81) * 190 + (b - 0x41) if 0x41 <= b <= 0xFE else None
            lead = 0
            code = INDEX.get(pointer) if pointer is not None else None
            if code is not None:
                out.append(code)
                continue
            if b <= 0x7F:
                i -= 1  # an ASCII byte is read again
            out.append(ERR)
            continue
        if b <= 0x7F:
            out.append(b)
        elif 0x81 <= b <= 0xFE:
            lead = b
        else:
            out.append(ERR)
    if lead:
        out.append(ERR)
    return out


def text(points, strip_bom):
    if strip_bom and points and points[0] == 0xFEFF:
        points = points[1:]
    return ''.join(map(chr, points))


def oracle(data):
    """[text, encoding, binary] for the byte string data."""
    binary = 0 in data[:8192]
    if data[:3] == b'\xef\xbb\xbf':
        return [text(utf8(data[3:], False), True), 'utf-8', binary]
    if data[:2] == b'\xff\xfe':
        return [text(utf16(data[2:], False), True), 'utf-16le', binary]
    if data[:2] == b'\xfe\xff':
        return [text(utf16(data[2:], True), True), 'utf-16be', binary]
    strict = utf8(data, True)
    if strict is not None:
        return [text(strict, True), 'utf-8', binary]
    return [text(euc_kr(data), False), 'cp949', binary]


# Pieces that hit each decoder branch; random cases glue several together.
EUC_POINTERS = sorted(INDEX)
PIECES = [b'', b'a', b'\x00', b'\x7f', b'\x80', b'\xff', b'\xfe', b'\xef', b'\xef\xbb', b'\xef\xbb\xbf',
          b'\xff\xfe', b'\xfe\xff', b'\xc2', b'\xc2\xa0', b'\xc0\xaf', b'\xe0\x80', b'\xe0\xa0\x80',
          b'\xed\xa0\x80', b'\xed\x9f\xbf', b'\xf0\x90\x80\x80', b'\xf4\x90', b'\xf5', b'\xe2\x82',
          '한'.encode(), '😀'.encode(), b'\xb0\xa1', b'\xc7\xd1', b'\x81\x41', b'\xc8\x41', b'\xa1\x41',
          b'\xc9\xa1', b'\xfe\xfe', b'\x81', b'\x81a', b'\x81\x80', b'\x81\xff', b'\x00\xd8', b'\xd8\x00',
          b'\x00\xdc', b'\xdc\x00', b'\x3d\xd8\x00\xde', b'\xd8\x3d\xde\x00', b'\xff\xfe\x00', b'\x41\x00']


def random_bytes(r):
    parts = []
    for _ in range(r.randrange(7)):
        kind = r.randrange(6)
        if kind == 0:
            parts.append(r.choice(PIECES))
        elif kind == 1:
            parts.append(bytes(r.randrange(256) for _ in range(r.randrange(1, 5))))
        elif kind == 2:  # a valid EUC-KR pair from the index
            p = r.choice(EUC_POINTERS)
            parts.append(bytes([0x81 + p // 190, 0x41 + p % 190]))
        elif kind == 3:
            parts.append(''.join(chr(r.choice([r.randrange(0x20, 0x7f), r.randrange(0xa0, 0xd800),
                                               r.randrange(0xe000, 0x110000)])) for _ in range(r.randrange(1, 4))).encode())
        elif kind == 4:  # UTF-16 code units, either order, including lone surrogates
            parts.append(bytes(r.randrange(256) if r.random() < 0.5 else r.choice([0x00, 0xd8, 0xdc, 0xde, 0x41])
                               for _ in range(r.randrange(1, 6))))
        else:
            parts.append(r.choice([b'a', b'\n', b'1,2', b' ']))
    prefix = r.choice([b'', b'', b'', b'\xef\xbb\xbf', b'\xff\xfe', b'\xfe\xff'])
    return prefix + b''.join(parts)


def cases(n, seed):
    r = random.Random(seed)
    rows = [a + b for a in PIECES for b in PIECES]
    rows += [b'\x00' * 8192 + b'a', b'a' * 8192 + b'\x00', b'a' * 8191 + b'\x00']
    edges = len(rows)
    rows += [random_bytes(r) for _ in range(n)]
    return rows, edges


if __name__ == '__main__':
    # JSON lines [input hex, [text, encoding, binary]] for the Node bridge test.
    import argparse
    import json
    import sys
    ap = argparse.ArgumentParser()
    ap.add_argument('--cases', type=int, default=20000)
    ap.add_argument('--seed', type=int, default=12345)
    args = ap.parse_args()
    rows, _ = cases(args.cases, args.seed)
    out = sys.stdout
    for row in rows:
        out.write(json.dumps([row.hex(), oracle(row)]) + '\n')
