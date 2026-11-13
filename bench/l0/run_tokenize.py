#!/usr/bin/env python3
"""Cross-check the Lair search tokenizer tokenize (src/documents/search.ts).

Each case is a text. The TypeScript copy (tokenize.mjs, run in Lair's Electron when available) gives the token
strings. tokenize.pruv gives [token count, then per token: n, n code points]. The Pruv list must equal an
independent oracle (a Python walk over the code points with the Unicode 17.0 data of tokenize_ucd.py: simple
lowercase, U+0130, Final_Sigma with the ICU test order, [\\p{L}\\p{N}] words, runs of the four CJK scripts), the
token strings that fromOutput builds from it (in the same Electron) must equal the verbatim tokens, and the
oracle tokens must equal the verbatim tokens.
No malformed inputs: the input is a str (UTF-8). A JavaScript lone surrogate reaches Pruv as U+FFFD through the
bridge, and both are neither a letter, a number, Cased nor Case_Ignorable, so the tokens are the same.
The [-1] answer past 2^40 output slots is not reached (it needs a text of about 2^39 bytes).
Inputs: ASCII words and punctuation, Hangul syllables and jamo, BMP and supplementary-plane Han, Hiragana,
Katakana and halfwidth Katakana, the Common-script U+30FC and the Han U+3005/U+3007, Greek with capital sigma
in every Final_Sigma context (Case_Ignorable apostrophes, periods, combining marks, U+0345, U+02B0, U+00AD,
Cased-and-ignorable letters before and after), U+0130, Cyrillic, Georgian, Deseret and other supplementary cased
letters, fullwidth Latin, digits of many scripts, emoji and joiners, and random code points of the whole range.
"""
import argparse
import json
import random
import sys

sys.dont_write_bytecode = True

import tokenize_ucd

NAME = 'tokenize'
WHOLE_MAX = 8

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let hex = line[1..].as_bytes();
    let buf: Vec<u8> = hex.chunks(2).map(|p| u8::from_str_radix(std::str::from_utf8(p).unwrap(), 16).unwrap()).collect();
    let s = std::str::from_utf8(&buf).unwrap();
    let words: Vec<String> = sol::tokenize(s).iter().map(|x| x.to_string()).collect();
    writeln!(out, "x {}", words.join(" ")).unwrap();
  }
}
'''

U = None


def data():
    global U
    if U is None:
        U = tokenize_ucd.load()
    return U


def lower(cps):
    d = data()
    out = []
    for i, c in enumerate(cps):
        if c in d['lower_full']:
            out.extend(d['lower_full'][c])
        elif c == 0x3A3:
            out.append(0x3C2 if context(cps, i, -1) and not context(cps, i, 1) else 0x3C3)
        else:
            out.append(d['lower1'].get(c, c))
    return out


def context(cps, i, step):
    """A Cased character next to cps[i] in direction step, past Case_Ignorable ones (ICU tests ignorable first)."""
    d = data()
    j = i + step
    while 0 <= j < len(cps):
        if cps[j] in d['ignorable']:
            j += step
            continue
        return cps[j] in d['cased']
    return False


def oracle(text):
    """The token code point lists of text."""
    d = data()
    w = lower([ord(ch) for ch in text])
    tokens, i = [], 0
    while i < len(w):
        if w[i] not in d['word']:
            i += 1
            continue
        j = i
        while j < len(w) and w[j] in d['word']:
            j += 1
        r = i
        while r < j:
            kind = w[r] in d['cjk']
            e = r
            while e < j and (w[e] in d['cjk']) == kind:
                e += 1
            part = w[r:e]
            if not kind or part[0] > 0xFFFF or len(part) == 1:  # part[0] is a UTF-16 unit in TypeScript
                tokens.append(part)
            else:
                if 3 <= len(part) <= WHOLE_MAX:
                    tokens.append(part)
                tokens.extend(part[k:k + 2] for k in range(len(part) - 1))
            r = e
        i = j
    return tokens


def flat(tokens):
    out = [len(tokens)]
    for t in tokens:
        out.append(len(t))
        out.extend(t)
    return out


def strings(tokens):
    return [''.join(map(chr, t)) for t in tokens]


POOLS = [
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
    ' \t\n.,;:!?-_/()[]"\'’ 　、。',
    ''.join(chr(c) for c in range(0xAC00, 0xD7A4, 97)) + '각ㄱㅏﾡ',
    '一中文日本語字漢々〇㐀豈⺀',
    '\U00020000\U00020001\U0002a6d6\U00030000\U0002f800\U00031350',
    'ぁあんゝゟアカンーヿｦｱﾝ\U0001b000\U0001b001',
    'ΣΣΣσςΑΒαβΆἈ',
    "'.:́ͅʰ­​‍’·ᴬⁱ",
    'İıIiÀßẞŸǅǄΩKÅ',
    'АБЯаႠაᲐᎠꭰԱⰀ',
    '\U00010400\U00010428\U0001e900\U0001e922\U0001d400\U0001d41a\U00016e40\U000104b0',
    'Ａａ０٠०๐Ⅰⅰ½²\U0001d7ce\U0001e950',
    '\U0001f600❤️‍\U0001f468©؀اאกั',
]


def rand_text(r):
    n = r.choice([1, 2, 3, 5, 8, 9, 12, 20, 40, 100])
    pools = r.sample(POOLS, r.randint(1, 4))
    out = []
    for _ in range(n):
        if r.random() < 0.03:
            c = r.randrange(0x110000)
            while 0xD800 <= c < 0xE000:
                c = r.randrange(0x110000)
            out.append(chr(c))
        else:
            out.append(r.choice(r.choice(pools)))
    return ''.join(out)


def sigma_text(r):
    """Capital sigma between random context characters."""
    ctx = 'aAσΣΑα' + "'.:́ͅʰ­" + ' 1한\U00010400İ'
    return ''.join(r.choice(ctx) if r.random() < 0.7 else 'Σ' for _ in range(r.randint(1, 10)))


EDGE = ['', ' ', 'a', 'A', 'Σ', 'aΣ', 'ΣΣ', 'aΣb', 'aΣ.', "a'Σ", "aΣ'", "aΣ'b", 'aΣ́', 'áΣ',
        'aΣͅ', 'ͅΣ', 'aͅΣ', 'ʰΣ', 'aΣʰ', 'a­Σ', '1Σ', 'ΑΣ ΑΣ', 'ΟΔΟΣ ΟΔΟΣ.',
        'İ', 'İstanbul', 'İİ', 'Iı', 'ẞ', 'Ω', 'K', 'Å', 'ǅǄǆ', '한', '한국', '한국어', '대한민국만세', '가나다라마바사아',
        '가나다라마바사아자', '가나다라마바사아자차카타파하', '𠀀', '𠀀𠀁', '𠀀𠀁𠀂', 'a𠀀b', '한𠀀', '𠀀한국', '한𠀀국',
        'abc한국def', '123', '한국123', 'ＡＢＣ', 'ｶﾀｶﾅ', 'カタカナー', 'ーカ', 'カーカ', '日本語のテキスト', '々', '人々', '〇〇',
        '漢字かな交じり文', 'ㄱㄴ', '각', 'Hello, World!', "don't", 'é', 'é', 'ÀÉÎ', 'ΆΈ',
        'Привет МИР', 'ႠႡ', 'ᲐᲑ', '𐐀𐐁', '𞤀𞤢', '𝐀𝐚', '½²', '٠١٢', '😀a😀', 'a‍b', 'a​b', 'x　y',
        '�', 'a�Σ', '\U0010ffff', '\x00a\x00']


def cases(n, seed):
    r = random.Random(seed)
    out = list(EDGE)
    out.append('a ' * 100000)
    out.append('가' * 50000)
    out.append('ΑΣ ' * 30000)
    out.append('Σ' + '́' * 100000)
    out.append('a' + "'" * 100000 + 'Σ' + '.' * 100000 + 'b')
    out.append(''.join(rand_text(r) for _ in range(2000)))
    edges = len(out)
    for _ in range(n):
        out.append(sigma_text(r) if r.random() < 0.2 else rand_text(r))
    return out, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true', help='only print JSON lines [text, oracle list] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for x in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([x, flat(oracle(x))]) + '\n')
        return 0
    from run import HERE, WORK, RESULTS, configure, run
    from run_host_within import portable
    from run_decode_bytes import ts_runtime
    summary = dict(seed=args.seed, random_cases=args.n, runs={}, unicode='17.0.0')
    differences, failed = [], False
    try:
        g2, summary['tools'] = configure()
        inputs, summary['edge_cases'] = cases(args.n, args.seed)
        summary.update(cases=len(inputs), bytes=sum(len(x.encode()) for x in inputs))
        want_tokens = [oracle(x) for x in inputs]
        want = [flat(t) for t in want_tokens]
        want_str = [strings(t) for t in want_tokens]
        summary.update(oracle_tokens=sum(len(t) for t in want_tokens), oracle_slots=sum(len(w) for w in want))
        node, summary['ts_runtime'] = ts_runtime()
        script = [HERE / (NAME+'.mjs')]

        def ts_lines(lines):
            got = run(node + script, ''.join(json.dumps(x) + '\n' for x in lines)).split('\n')[:-1]
            assert len(got) == len(lines)
            return [json.loads(g) for g in got]
        ts = ts_lines([['text', x] for x in inputs])
        summary.update(ts_oracle_pass=sum(a == b for a, b in zip(ts, want_str)))
        for i, (x, a, b) in enumerate(zip(inputs, ts, want_str)):
            if a != b:
                differences.append(dict(compiler_backend='oracle/ts', case_index=i, text=x[:300], ts=a[:100],
                                        oracle=b[:100]))
        payload = ''.join('x%s\n' % x.encode().hex() for x in inputs)
        WORK.mkdir(exist_ok=True)
        src = HERE / (NAME+'.pruv')
        for compiler in ('py', 'rs'):
            for backend in ('rust', 'llvm'):
                key = compiler+'/'+backend
                row_ = summary['runs'][key] = dict(status='error')
                try:
                    work = WORK / (NAME+'_'+compiler+'_'+backend)
                    work.mkdir(exist_ok=True)
                    compiled = g2.compile_pruv(compiler, str(src), str(work), backend)
                    row_['verification'] = portable(compiled)
                    if compiled['rc'] != 0:
                        raise RuntimeError(json.dumps(portable(compiled)))
                    harness = work / 'main.rs'
                    harness.write_text(HARNESS.replace('@SOL@', compiled['rs']))
                    extra = []
                    if compiled['ll']:
                        extra, error = g2.build_llvm_objects(compiled['ll'], NAME, str(work))
                        if error:
                            raise RuntimeError(error)
                    exe = work / 'runner'
                    run([g2.RUSTC, '-O', '--edition', '2021', '-C', 'target-cpu=native', harness, '-o', exe]+extra)
                    lines = run([exe], payload).split('\n')[:-1]
                    assert len(lines) == len(inputs)
                    got = [[int(w) for w in line[2:].split(' ')] if len(line) > 2 else [] for line in lines]
                    built = ts_lines([['out', g] for g in got])
                    for i, (x, g, b, s, w) in enumerate(zip(inputs, got, built, ts, want)):
                        if g != w or b != s:
                            d = dict(compiler_backend=key, case_index=i, text=x[:300], text_chars=len(x),
                                     pruv=g[:300], expected=w[:300])
                            if b != s:
                                d.update(from_output=b[:100], ts=s[:100])
                            differences.append(d)
                    row_.update(cases=len(inputs), pruv_oracle_pass=sum(g == w for g, w in zip(got, want)),
                                pruv_ts_pass=sum(b == s for b, s in zip(built, ts)))
                    ok = row_['pruv_oracle_pass'] == len(inputs) and row_['pruv_ts_pass'] == len(inputs)
                    row_['status'] = 'ok' if ok else 'wrong'
                    failed |= not ok
                    print(key+': '+json.dumps(row_), flush=True)
                except Exception as exc:
                    row_['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row_['error'], flush=True)
        failed |= summary['ts_oracle_pass'] != len(inputs)
    except Exception as exc:
        summary['error'] = portable(str(exc))
        failed = True
    differences.sort(key=lambda d: (len(json.dumps(d)), d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='JSON length of the record, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
