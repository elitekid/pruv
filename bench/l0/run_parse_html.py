#!/usr/bin/env python3
"""Cross-check the Lair DOCX HTML parser parseHtml (src/documents/docx.ts).

Each case is an HTML string. The TypeScript copy (parse_html.mjs, run in Lair's Electron when available)
gives the El tree. Pruv parse_html.pruv gives a flat record list (one record per kept text and per element,
in creation order). The records must equal an independent oracle (Python re with the JavaScript whitespace
class written out, its own entity decode and stack walk), and the tree that fromRecords builds from the Pruv
records (in the same Electron) must equal the verbatim tree; the oracle records go through fromRecords too
and must give the same tree. Trees are compared as tag, the own href/colspan/rowspan attributes and children.
Domain: strings with no lone surrogates of at most 2^38 UTF-8 bytes (the bridge glue checks this).
Inputs: mammoth-like documents (paragraphs, headings, lists, tables with colspan/rowspan, links, images,
<br />), entities (named in any case, decimal and hex, 0, past U+10FFFF, huge, surrogate halves alone and in
pairs, "constructor", unknown names, Kelvin sign and long s next to letters), comments closed and never
closed, malformed and stray '<' and '>', tags with every JavaScript whitespace and U+0085/U+001F (not
whitespace in JavaScript), quoted attributes with whitespace around '=' and unclosed quotes, duplicate and
mixed-case attributes, closing tags that cut the stack, deep nesting and long inputs.
"""
import argparse
import json
import random
import re
import sys

sys.dont_write_bytecode = True

NAME = 'parse_html'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let hex = line[1..].as_bytes();
    let buf: Vec<u8> = hex.chunks(2).map(|p| u8::from_str_radix(std::str::from_utf8(p).unwrap(), 16).unwrap()).collect();
    let r = sol::parse_html(std::str::from_utf8(&buf).unwrap());
    let words: Vec<String> = r.iter().map(|x| x.to_string()).collect();
    writeln!(out, "x {}", words.join(" ")).unwrap();
  }
}
'''

WS = '\t\n\x0b\x0c\r \xa0  -     　﻿'
WS_SET = set('\t\n\x0b\x0c\r \xa0     　﻿') | {chr(c) for c in range(0x2000, 0x200b)}
TOKEN = re.compile('<!--[\\s\\S]*?-->|<(/?)([a-zA-Z][a-zA-Z0-9]*)((?:[%s]+[^<>]*?)?)[%s]*(/?)>|[^<]+|<' % (WS, WS))
ATTR = re.compile('([a-zA-Z_:][A-Za-z0-9_:.-]*)[%s]*=[%s]*"([^"]*)"' % (WS, WS))
ENTITY = re.compile(r'&(#x[0-9a-f]+|#[0-9]+|[a-z]+);', re.I | re.A)
NAMED = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'", 'nbsp': ' ',
         # Lair looks names up on a plain object: "constructor" finds Object, whose source text replaces it.
         'constructor': 'function Object() { [native code] }'}
WANTED = ('href', 'colspan', 'rowspan')


def decode(text):
    def one(m):
        name = m.group(1)
        if name[0] == '#':
            code = int(name[2:], 16) if name[1] in 'xX' else int(name[1:])
            return chr(code) if 0 < code <= 0x10ffff else ''
        return NAMED.get(name.lower(), m.group(0))
    return ENTITY.sub(one, text)


def oracle(html):
    """The record list from a regular-expression token walk."""
    rec, stack, count = [], [('#root', -1)], 0
    for m in TOKEN.finditer(html):
        raw, closing, name, attr_text, slash = (m.group(0),) + m.groups()
        top = stack[-1][1]
        if name is None:
            if raw.startswith('<!--'):
                continue
            t = decode(raw)
            if top == -1 and all(c in WS_SET for c in t):
                continue
            rec += [0, top, len(t)] + [ord(c) for c in t]
            continue
        tag = name.lower()
        if closing:
            tags = [x[0] for x in stack]
            at = len(tags) - 1 - tags[::-1].index(tag) if tag in tags else -1
            if at > 0:
                del stack[at:]
            continue
        attrs = {}
        for a in ATTR.finditer(attr_text):
            attrs[a.group(1).lower()] = decode(a.group(2))
        rec += [1, top, len(tag)] + [ord(c) for c in tag]
        for w in WANTED:
            if w in attrs:
                rec += [len(attrs[w])] + [ord(c) for c in attrs[w]]
            else:
                rec.append(-1)
        if tag not in ('br', 'img', 'hr') and not slash:
            stack.append((tag, count))
        count += 1
    return rec


SPACES = [' ', '\t', '\n', '\r', '\x0b', '\x0c', '\xa0', ' ', ' ', ' ', ' ', ' ', ' ',
          ' ', '　', '﻿', '\x85', '\x1f', '​', '᠎']
TEXT = ['a', 'Z', '7', '가', '\U0001f600', 'é', 'K', 'ſ', '_', ':', '.', '-', '=', '"', "'", '/', '>', '&', '#',
        ';', 'x', 'X']
ENTS = ['&amp;', '&AMP;', '&Lt;', '&gt;', '&quot;', '&apos;', '&nbsp;', '&NbSp;', '&#65;', '&#x41;', '&#X1f600;',
        '&#xD83D;', '&#xDE00;', '&#xD83D;&#xDE00;', '&#0;', '&#x0;', '&#1114111;', '&#1114112;', '&#x110000;',
        '&#99999999999999999999999;', '&#xFFFFFFFFFFFFFFFFFFFF;', '&constructor;', '&Constructor;', '&toString;',
        '&unknown;', '&;', '&#;', '&#x;', '&#12a;', '&#xg;', '&amp', '&&amp;', '&aK;', '&aſ;', '&#00065;',
        '&#x00000041;', '&#32;', '&#x3000;', '&#160;', '&#x85;']
TAGS = ['p', 'P', 'h1', 'H2', 'a', 'A', 'ul', 'ol', 'li', 'table', 'tr', 'td', 'th', 'strong', 'em', 'br', 'BR', 'img',
        'hr', 'Hr', 'span', 'b0', 'x1y']


def rand_text(r, k):
    out = []
    for _ in range(k):
        c = r.randrange(4)
        out.append(r.choice(TEXT) if c == 0 else r.choice(ENTS) if c == 1 else r.choice(SPACES) if c == 2
                   else chr(r.randrange(97, 123)))
    return ''.join(out)


def rand_attrs(r):
    out = []
    for _ in range(r.choice([0, 0, 1, 2, r.randrange(0, 6)])):
        name = r.choice(['href', 'HREF', 'colspan', 'ColSpan', 'rowspan', 'ROWSPAN', 'src', 'alt', 'x:y', '_a', 'a.b-c',
                         'hreff', 'xhref', '1href', '-href', 'data-href'])
        sp = lambda: ''.join(r.choice(SPACES) for _ in range(r.choice([0, 0, 1, 2])))
        val = rand_text(r, r.choice([0, 1, 3, 8])).replace('"', r.choice(['', '&quot;', "'"]))
        q = r.choice(['"', '"', '"', "'", ''])
        out.append(r.choice(SPACES[:4] + [r.choice(SPACES)]) + sp() + name + sp() + '=' + sp() + q + val
                   + r.choice([q, q, q, '']))
    return ''.join(out)


def mammoth_like(r):
    parts = []
    depth = []
    for _ in range(r.randrange(1, 40)):
        c = r.randrange(9)
        if c < 3 or not depth:
            tag = r.choice(['p', 'h1', 'h2', 'ul', 'ol', 'li', 'table', 'tr', 'td', 'th', 'strong', 'em', 'a'])
            attrs = ''
            if tag == 'a':
                attrs = ' href="%s"' % rand_text(r, r.randrange(0, 8)).replace('"', '&quot;')
            if tag in ('td', 'th') and r.random() < 0.6:
                attrs = r.choice([' colspan="2"', ' rowspan="3"', ' colspan="2" rowspan="2"', ' colspan="x&amp;y"'])
            parts.append('<%s%s>' % (tag, attrs))
            depth.append(tag)
        elif c < 5:
            parts.append(rand_text(r, r.randrange(0, 12)))
        elif c < 6:
            parts.append(r.choice(['<br />', '<br>', '<img src="a.png" />', '<hr/>', '<!-- note -->', '\n']))
        else:
            parts.append('</%s>' % depth.pop())
    while depth and r.random() < 0.8:
        parts.append('</%s>' % depth.pop())
    return ''.join(parts)


def soup(r):
    out = []
    for _ in range(r.choice([1, 3, r.randrange(0, 20), r.randrange(0, 120)])):
        c = r.randrange(10)
        if c < 3:
            out.append('<' + r.choice(['', '/']) + r.choice(TAGS) + rand_attrs(r)
                       + ''.join(r.choice(SPACES) for _ in range(r.choice([0, 0, 1, 2])))
                       + r.choice(['>', '/>', ' />', '', '<', '/ >', ' / >']))
        elif c < 5:
            out.append(rand_text(r, r.randrange(0, 6)))
        elif c < 6:
            out.append(r.choice(['<!--', '-->', '<!-- x -->', '<!---->', '<!-->', '<!--->', '<!', '<', '>', '</', '</>',
                                 '<1a>', '<a', '< a>', '<a\x85>', '<a　href="1">', '<a />']))
        elif c < 7:
            out.append(r.choice(SPACES))
        else:
            out.append(r.choice(ENTS + TEXT))
    return ''.join(out)


EDGE = ['', ' ', '\n\n', '　﻿', '&nbsp;', '&#32;', '&#0;', '&#x110000;', ' &#0; ', 'a', '<', '>', '<<', '<>',
        '</p>', '<p>', '<p/>', '<p >', '<p / >', '<p/ >', '<p hidden>', '<p a="1" / >', '<P>x</p>', '<br>x', '<img>x',
        '<hr/>x', '<a href="x">y</a>', '<a href = "1" HREF="2">z</a>', '<a href="1>', '<a href="1">', '<a href=\'1\'>',
        '<td colspan="2" rowspan="3">x</td>', '<p><b>x</p>y', '<b><p>x</b>y', '<p><p><p>x</p>y</p>z',
        '</root>', '<#root>', '<!-- a --> b', '<!-- a', '<!-->x-->', '<!--->x', '<!---->x', 'a<!--b<!--c-->d',
        '<!--<!--<!--', '<p>&constructor;</p>', '&#xD83D;&#xDE00;', '<p>&#xD83D;</p>', '&#xDE00;&#xD83D;',
        '<a\x85href="1">', '<a href="1">', '<a　href="1"　>', '<a href = "1">', '<a\x1fb>',
        '<a/>', '<a/ >', '<a //>', '<a ///>', '<a x/y>', '<a href="1"/>t', '<a b="<">', '<a b=">">', 'x&amp;&lt;y',
        '<p>　</p>', '　<p></p>　', '<p>a</p>  <p>b</p>', '&aK;', '&ſ;']


def cases(n, seed):
    r = random.Random(seed)
    out = list(EDGE)
    out.append('<div>' * 800 + 'x' + '</div>' * 800)
    out.append('<p>' * 800 + '</p>' * 400 + 'y')
    out.append('<!--' * 4000 + 'z')
    out.append('<a href="' * 3000)
    out.append('<a ' + 'b' * 50000 + '>')
    out.append(''.join(mammoth_like(r) for _ in range(400)))
    out.append('&#x1F600;' * 5000 + '&constructor;' * 200)
    edges = len(out)
    for _ in range(n):
        out.append(mammoth_like(r) if r.random() < 0.4 else soup(r))
    return out, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [html, oracle records] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for x in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([x, oracle(x)]) + '\n')
        return 0
    from run import HERE, WORK, RESULTS, configure, run
    from run_host_within import portable
    from run_decode_bytes import ts_runtime
    summary = dict(seed=args.seed, random_cases=args.n, runs={})
    differences, failed = [], False
    try:
        g2, summary['tools'] = configure()
        inputs, summary['edge_cases'] = cases(args.n, args.seed)
        summary.update(cases=len(inputs), bytes=sum(len(x.encode()) for x in inputs))
        expected = [oracle(x) for x in inputs]
        summary.update(oracle_records=sum(len(e) for e in expected))
        node, summary['ts_runtime'] = ts_runtime()
        script = [HERE / (NAME+'.mjs')]

        def trees(lines):
            got = run(node + script, ''.join(json.dumps(x) + '\n' for x in lines)).split('\n')[:-1]
            assert len(got) == len(lines)
            return got
        ts = trees([['html', x] for x in inputs])
        from_oracle = trees([['rec', e] for e in expected])
        summary.update(ts_oracle_pass=sum(a == b for a, b in zip(ts, from_oracle)))
        for i, (x, a, b) in enumerate(zip(inputs, ts, from_oracle)):
            if a != b:
                differences.append(dict(compiler_backend="oracle/ts", case_index=i, html=x[:300], ts=a[:600],
                                        from_oracle=b[:600]))
        payload = ''.join('x%s\n' % x.encode().hex() for x in inputs)
        for compiler in ('py', 'rs'):
            for backend in ('rust', 'llvm'):
                key = compiler+'/'+backend
                row_ = summary['runs'][key] = dict(status='error')
                try:
                    work = WORK / (NAME+'_'+compiler+'_'+backend)
                    work.mkdir(exist_ok=True)
                    compiled = g2.compile_pruv(compiler, str(HERE / (NAME+'.pruv')), str(work), backend)
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
                    recs = [[int(w) for w in line[2:].split(' ')] if len(line) > 2 else [] for line in lines]
                    built = trees([['rec', p] for p in recs])
                    for i, (x, p, b, s, want) in enumerate(zip(inputs, recs, built, ts, expected)):
                        if p != want or b != s:
                            d = dict(compiler_backend=key, case_index=i, html=x[:300], html_chars=len(x),
                                     pruv=p[:300], expected=want[:300])
                            if b != s:
                                d.update(from_records=b[:600], ts=s[:600])
                            differences.append(d)
                    row_.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(recs, expected)),
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
