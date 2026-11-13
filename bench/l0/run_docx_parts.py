#!/usr/bin/env python3
"""Cross-check the Lair DOCX block walk docxParts (src/documents/docx.ts) past its parse.

Each case is an HTML string. The TypeScript copy (docx_parts.mjs, run in Lair's Electron when available) gives
the blocks (number, kind, element, collapsed text), the preview HTML and the <img\\b count. Pruv takes the
parse_html records of the text (parse_html.pruv, checked by run_parse_html.py) and docx_parts.pruv gives the
blocks and the preview HTML as one flat list, img_count the image count. The Pruv list must equal an
independent oracle (a recursive Python walk over the records, Python re for collapse with the JavaScript
whitespace class written out), and the parts that fromOutput builds from it (in the same Electron) must equal
the verbatim parts; the oracle list goes through fromOutput too and must give the same parts. Blocks name
their element by its preorder position (the record element number).
Also: malformed record lists (a kind not 0/1, a parent not an earlier element, a length past the list, a code
point outside 0..U+10FFFF, a cut record) must give [-1].
Domain: parse_html record lists of at most 2^36 slots (the bridge glue passes parse_html output only).
Inputs: the parse_html generators (mammoth-like documents and tag soup) and document trees with paragraphs,
headings h1..h7, nested lists with stray non-li children, li holding p/div and text after nested lists,
tables with thead/tbody/tfoot, rows of empty cells, cells with p and br, colspan/rowspan values that are and
are not 1..3 ASCII digits, links with https in any case and other schemes and quotes or ampersands in the
href, script/style, br/img/<img variants, sup/sub/u/strong/em, div, and every JavaScript whitespace around
line breaks.
"""
import argparse
import json
import random
import re
import sys

sys.dont_write_bytecode = True
sys.setrecursionlimit(100000)

from run_parse_html import oracle as parse_records, mammoth_like, soup, rand_text

NAME = 'docx_parts'

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap();
    let words: Vec<String> = if line.starts_with('x') {
      let hex = line[1..].as_bytes();
      let buf: Vec<u8> = hex.chunks(2).map(|p| u8::from_str_radix(std::str::from_utf8(p).unwrap(), 16).unwrap()).collect();
      let s = std::str::from_utf8(&buf).unwrap();
      let rec = sol::parse_html(s);
      let mut w = vec![sol::img_count(s).to_string()];
      w.extend(sol::docx_parts(&rec).iter().map(|x| x.to_string()));
      w
    } else {
      let rec: Vec<i64> = line[1..].split_whitespace().map(|x| x.parse().unwrap()).collect();
      sol::docx_parts(&rec).iter().map(|x| x.to_string()).collect()
    };
    writeln!(out, "x {}", words.join(" ")).unwrap();
  }
}
'''

JS_WS = {chr(c) for c in [9, 10, 11, 12, 13, 32, 160, 5760, 8232, 8233, 8239, 8287, 12288, 65279]} \
    | {chr(c) for c in range(8192, 8203)}
SP_RUN = re.compile('[ \t\r\x0c\x0b]+')
NL = re.compile(' ?\n ?')
SEPS = re.compile(r'( \| )+')
SPAN = re.compile('[0-9]{1,3}')
KINDS = {'p': 0, 'h': 1, 'li': 2, 'tr': 3}
HEADINGS = {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}


def tree(rec):
    """[(tag, attrs, children, element number)] with texts as str."""
    top, els, p = [], [], 0
    while p < len(rec):
        kind, parent, n = rec[p:p + 3]
        into = top if parent == -1 else els[parent][2]
        s = ''.join(map(chr, rec[p + 3:p + 3 + n]))
        p += 3 + n
        if kind == 0:
            into.append(s)
            continue
        attrs = {}
        for name in ('href', 'colspan', 'rowspan'):
            m = rec[p]
            p += 1
            if m >= 0:
                attrs[name] = ''.join(map(chr, rec[p:p + m]))
                p += m
        el = (s, attrs, [], len(els))
        els.append(el)
        into.append(el)
    return top


def is_list(x):
    return not isinstance(x, str) and x[0] in ('ul', 'ol')


def inline(el, skip_lists):
    out = ''
    for c in el[2]:
        if isinstance(c, str):
            out += c
        elif skip_lists and is_list(c):
            pass
        elif c[0] == 'br':
            out += '\n'
        elif c[0] == 'img':
            out += '[그림]'
        elif c[0] in ('p', 'div', 'li'):
            out += (' ' if out and not out.endswith('\n') else '') + inline(c, skip_lists)
        else:
            out += inline(c, skip_lists)
    return out


def collapse(text):
    return NL.sub('\n', SP_RUN.sub(' ', text)).strip(''.join(JS_WS))


def collect(nodes, blocks):
    def add(kind, el, text):
        clean = collapse(text)
        if clean:
            blocks.append((kind, el, clean))
    for node in nodes:
        if isinstance(node, str):
            continue
        tag = node[0]
        if tag == 'p' or tag in HEADINGS:
            add('p' if tag == 'p' else 'h', node, inline(node, False))
        elif is_list(node):
            for item in node[2]:
                if isinstance(item, str):
                    continue
                if item[0] != 'li':
                    collect([item], blocks)
                    continue
                add('li', item, inline(item, True))
                collect([c for c in item[2] if is_list(c)], blocks)
        elif tag == 'table':
            rows = []

            def gather(parent):
                for c in parent[2]:
                    if isinstance(c, str):
                        continue
                    if c[0] == 'tr':
                        rows.append(c)
                    elif c[0] in ('thead', 'tbody', 'tfoot'):
                        gather(c)
            gather(node)
            for row in rows:
                cells = [re.sub('\n+', ' ', collapse(inline(c, False))) for c in row[2]
                         if not isinstance(c, str) and c[0] in ('td', 'th')]
                text = ' | '.join(cells)
                add('tr', row, '' if SEPS.fullmatch(text) else text)
        else:
            collect(node[2], blocks)


def esc(s, attr=False):
    s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return s.replace('"', '&quot;') if attr else s


def render(nodes, num, cell=False):
    out = []
    for node in nodes:
        if isinstance(node, str):
            out.append(esc(node))
            continue
        tag, attrs, kids, en = node
        n = num.get(en)
        mark = ' data-block="%d"' % n if n else ''
        if tag in ('script', 'style'):
            continue
        if tag == 'p' or tag in HEADINGS:
            if n or cell:
                out.append('<%s%s>%s</%s>' % (tag, mark, render(kids, num, cell), tag))
        elif tag in ('ul', 'ol', 'thead', 'tbody', 'tfoot', 'strong', 'em', 'u', 'sup', 'sub', 'table'):
            out.append('<%s>%s</%s>' % (tag, render(kids, num, cell), tag))
        elif tag == 'li':
            nested = render([c for c in kids if is_list(c)], num)
            if n:
                out.append('<li%s>%s%s</li>' % (mark, render([c for c in kids if not is_list(c)], num), nested))
            else:
                out.append(nested)
        elif tag == 'tr':
            out.append('<tr%s>%s</tr>' % (mark, render(kids, num, cell)))
        elif tag in ('td', 'th'):
            span = ''.join(' %s="%s"' % (k, attrs[k]) for k in ('colspan', 'rowspan')
                           if SPAN.fullmatch(attrs.get(k, '')))
            out.append('<%s%s>%s</%s>' % (tag, span, render(kids, num, True), tag))
        elif tag == 'br':
            out.append('<br>')
        elif tag == 'img':
            out.append('[그림]')
        elif tag == 'a':
            href = attrs.get('href', '')
            if href[:8].lower() == 'https://' and href[:8].isascii():
                out.append('<a href="%s" rel="noopener noreferrer">%s</a>' % (esc(href, True), render(kids, num, cell)))
            else:
                out.append(render(kids, num, cell))
        else:
            out.append(render(kids, num, cell))
    return ''.join(out)


def expected(rec):
    """The docx_parts list for a parse_html record list."""
    nodes = tree(rec)
    blocks = []
    collect(nodes, blocks)
    out = [len(blocks)]
    num = {}
    for k, (kind, el, text) in enumerate(blocks):
        num[el[3]] = k + 1
        out += [KINDS[kind], el[3], len(text)] + [ord(c) for c in text]
    html = render(nodes, num)
    return out + [len(html)] + [ord(c) for c in html]


def images(html):
    return len(re.findall(r'<img(?![A-Za-z0-9_])', html, re.I | re.A))


WS = ['', ' ', '  ', '\n', ' \n ', '\t', '\r\n', '\x0b', '\x0c', '\xa0', ' ', '　', '﻿', ' ', '\x85',
      ' \n\n ', '\n \n', ' ']
WORDS = ['a', 'Bb', '가나', '\U0001f600', '&amp;', '&lt;x&gt;', '"q"', "'", '|', ' | ', '&nbsp;', '&#10;', '&#x2028;']
HREFS = ['https://a.b/c?d=1&amp;e=2', 'HTTPS://X', 'HtTpS://y"z', 'https:/x', 'http://x', 'https:', ' https://x',
         'javascript:alert(1)', 'https://&lt;&gt;&quot;', '', 'https://K', 'httpſ://x', 'https://']
SPANS = ['1', '2', '22', '999', '1000', '0', '01', '', 'x', ' 2', '2 ', '٣', '2&#10;', '+1', '-1']


def words(r):
    return ''.join(r.choice(WS) + r.choice(WORDS) for _ in range(r.choice([0, 1, 1, 2, 4])))


def inline_html(r, depth):
    parts = []
    for _ in range(r.choice([0, 1, 2, 3, 5])):
        c = r.randrange(12)
        if c < 4 or depth > 4:
            parts.append(words(r))
        elif c < 5:
            parts.append(r.choice(['<br>', '<br/>', '<BR />', '<img src="a">', '<IMG/>', '<img>', '<imgx>',
                                   '<img_a>', '<img-a>']))
        elif c < 8:
            tag = r.choice(['strong', 'em', 'u', 'sup', 'sub', 'span', 'b', 'p', 'div', 'li', 'h2', 'script',
                            'style', 'ul'])
            parts.append('<%s>%s</%s>' % (tag, inline_html(r, depth + 1), tag))
        elif c < 10:
            parts.append('<a href="%s">%s</a>' % (r.choice(HREFS), inline_html(r, depth + 1)))
        else:
            parts.append('<a>%s</a>' % inline_html(r, depth + 1))
    return ''.join(parts)


def list_html(r, depth):
    tag = r.choice(['ul', 'ol'])
    items = []
    for _ in range(r.choice([0, 1, 2, 3, 4])):
        c = r.randrange(10)
        if c < 6:
            inner = inline_html(r, depth + 1)
            if depth < 4 and r.random() < 0.4:
                inner += list_html(r, depth + 1) + r.choice(['', words(r), '<p>%s</p>' % words(r)])
            items.append('<li>%s</li>' % inner)
        elif c < 7:
            items.append(words(r))
        elif c < 8 and depth < 4:
            items.append(list_html(r, depth + 1))
        else:
            items.append(r.choice(['<p>%s</p>' % words(r), '<div><p>%s</p></div>' % words(r), '<table><tr><td>t</td></tr></table>']))
    return '<%s>%s</%s>' % (tag, ''.join(items), tag)


def table_html(r, depth):
    def row():
        cells = []
        for _ in range(r.choice([0, 1, 2, 3])):
            tag = r.choice(['td', 'th', 'td'])
            attrs = ''
            if r.random() < 0.4:
                attrs += ' colspan="%s"' % r.choice(SPANS)
            if r.random() < 0.3:
                attrs += ' rowspan="%s"' % r.choice(SPANS)
            body = r.choice(['', '', ' ', inline_html(r, depth + 1), '<p>%s</p><p>%s</p>' % (words(r), words(r)),
                             'a<br>b', '<br><br>', '\n\n'])
            cells.append('<%s%s>%s</%s>' % (tag, attrs, body, tag))
        if r.random() < 0.2:
            cells.append(words(r))
        return '<tr>%s</tr>' % ''.join(cells)
    parts = []
    for _ in range(r.choice([0, 1, 2, 3])):
        c = r.randrange(6)
        if c < 3:
            parts.append(row())
        elif c < 5:
            sec = r.choice(['thead', 'tbody', 'tfoot'])
            parts.append('<%s>%s</%s>' % (sec, ''.join(row() for _ in range(r.choice([0, 1, 2]))), sec))
        else:
            parts.append(r.choice(['<p>x</p>', words(r), '<div><tr><td>d</td></tr></div>']))
    return '<table>%s</table>' % ''.join(parts)


def document(r):
    parts = []
    for _ in range(r.randrange(1, 12)):
        c = r.randrange(10)
        if c < 3:
            tag = r.choice(['p', 'p', 'h1', 'h3', 'h6', 'h7', 'H2', 'P'])
            parts.append('<%s>%s</%s>' % (tag, inline_html(r, 0), tag))
        elif c < 5:
            parts.append(list_html(r, 0))
        elif c < 7:
            parts.append(table_html(r, 0))
        elif c < 8:
            parts.append('<div>%s</div>' % document(r) if r.random() < 0.3 else words(r))
        elif c < 9:
            parts.append(r.choice(['<script>a<p>x</p></script>', '<style>p{}</style>', '<hr>', '<img src="i.png" />',
                                   '<br>', '<blockquote><p>q</p></blockquote>']))
        else:
            parts.append(inline_html(r, 0))
    return ''.join(parts)


EDGE = ['', ' ', '<p></p>', '<p> </p>', '<p>\n</p>', '<p>a<br>b</p>', '<p>a <br> b</p>', '<p>a  b</p>',
        '<p>\xa0a\xa0</p>', '<p> \t a \x0b\x0c b \r </p>', '<p>a\n\n \n b</p>', '<p>a<div>b</div></p>',
        '<p><div>b</div><div>c</div></p>', '<p>a<br><div>b</div></p>', '<p><li>x</li></p>', '<h1>t</h1><h7>u</h7>',
        '<ul><li>a<ul><li>b</li></ul>c</li></ul>', '<ul><li><ul><li>b</li></ul></li></ul>', '<ul>x<p>y</p></ul>',
        '<ol><li></li><li> </li></ol>', '<ul><li>a<p>b</p></li></ul>', '<ul><ul><li>z</li></ul></ul>',
        '<table><tr><td></td><td></td></tr></table>', '<table><tr><td></td><td></td><td></td></tr></table>',
        '<table><tr><td>a</td><td></td></tr></table>', '<table><tr><td></td><td>b</td></tr></table>',
        '<table><tr><td>|</td><td></td></tr></table>', '<table><tr><td> | </td></tr></table>',
        '<table><thead><tr><th>h</th></tr></thead><tbody><tr><td colspan="2" rowspan="3">x</td></tr></tbody></table>',
        '<table><tr><td colspan="1000">a</td><td rowspan="٣">b</td></tr></table>',
        '<table><tr><td>a<br>b<br><br>c</td></tr></table>', '<table><tr><td><p>a</p><p>b</p></td></tr></table>',
        '<table><tr><td><table><tr><td>in</td></tr></table></td></tr></table>', '<table>x<tr></tr></table>',
        '<a href="https://x">y</a>', '<a href="HTTPS://x">y</a>', '<a href="https://a&quot;&lt;">y</a>',
        '<a href="http://x">y</a>', '<a>y</a>', '<p><a href="https://x">y</a></p>', '<p><script>s</script>t</p>',
        '<script><p>x</p></script>', '<img><IMG><imgx><img_><img-><img', '<!-- <img> -->', '<p>[그림]</p>',
        '<p><img></p>', '<p>a<img>b</p>', '<strong><p>x</p></strong>', '<u>a</u><sup>b</sup><sub>c</sub>',
        '<p>&amp;&lt;&gt;"\'</p>', '<li>x</li>', '<tr><td>x</td></tr>', '<td>x</td>', '<div><p>x</p></div>',
        '<p>﻿a﻿</p>', '<p>\x85</p>', '<p> </p>', '<p>a \n</p>', '<p>\n a</p>']

BAD = [[2, -1, 0], [0, 0, 0], [0, -2, 0], [0, -1, 2, 97], [0, -1, 1, 1114112], [0, -1, 1, -1], [0, -1],
       [1, -1, 1, 112, -1, -1], [1, -1, 1, 112, -1, -1, 3, 49], [1, -1, 1, 112, -2, -1, -1],
       [1, -1, 1, 112, -1, -1, -1, 0, 1, 0], [1, -1, -1], [0, -1, -1],
       [1, -1, 1, 112, 1, 1114112, -1, -1]]


def cases(n, seed):
    r = random.Random(seed)
    out = list(EDGE)
    out.append('<ul><li>' * 600 + 'deep' + '</li></ul>' * 600)
    out.append('<div>' * 800 + '<p>x</p>' + '</div>' * 800)
    out.append('<table><tr>' + '<td>c</td>' * 3000 + '</tr></table>')
    out.append(''.join(document(r) for _ in range(300)))
    out.append('<p>' + ' \n' * 20000 + '</p>')
    edges = len(out)
    for _ in range(n):
        c = r.random()
        out.append(document(r) if c < 0.6 else mammoth_like(r) if c < 0.8 else soup(r))
    return out, edges


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    ap.add_argument('--emit', action='store_true',
                    help='only print JSON lines [html, images, oracle list] (Node bridge test)')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    if args.emit:
        for x in cases(args.n, args.seed)[0]:
            sys.stdout.write(json.dumps([x, images(x), expected(parse_records(x))]) + '\n')
        return 0
    from run import HERE, WORK, RESULTS, configure, run
    from run_host_within import portable
    from run_decode_bytes import ts_runtime
    summary = dict(seed=args.seed, random_cases=args.n, runs={})
    differences, failed = [], False
    try:
        g2, summary['tools'] = configure()
        inputs, summary['edge_cases'] = cases(args.n, args.seed)
        summary.update(cases=len(inputs), malformed_cases=len(BAD), bytes=sum(len(x.encode()) for x in inputs))
        want = [[images(x)] + expected(parse_records(x)) for x in inputs]
        summary.update(oracle_slots=sum(len(w) for w in want))
        node, summary['ts_runtime'] = ts_runtime()
        script = [HERE / (NAME+'.mjs')]

        def parts(lines):
            got = run(node + script, ''.join(json.dumps(x) + '\n' for x in lines)).split('\n')[:-1]
            assert len(got) == len(lines)
            return got
        ts = parts([['html', x] for x in inputs])
        from_oracle = parts([['out', [w[0], w[1:]]] for w in want])
        summary.update(ts_oracle_pass=sum(a == b for a, b in zip(ts, from_oracle)))
        for i, (x, a, b) in enumerate(zip(inputs, ts, from_oracle)):
            if a != b:
                differences.append(dict(compiler_backend="oracle/ts", case_index=i, html=x[:300], ts=a[:600],
                                        from_oracle=b[:600]))
        payload = ''.join('x%s\n' % x.encode().hex() for x in inputs) + ''.join(
            'r%s\n' % ' '.join(map(str, b)) for b in BAD)
        src = WORK / (NAME+'.pruv')
        WORK.mkdir(exist_ok=True)
        src.write_text((HERE / 'parse_html.pruv').read_text() + (HERE / (NAME+'.pruv')).read_text())
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
                    assert len(lines) == len(inputs) + len(BAD)
                    got = [[int(w) for w in line[2:].split(' ')] if len(line) > 2 else [] for line in lines]
                    bad_ok = sum(g == [-1] for g in got[len(inputs):])
                    got = got[:len(inputs)]
                    built = parts([['out', [g[0], g[1:]]] for g in got])
                    for i, (x, g, b, s, w) in enumerate(zip(inputs, got, built, ts, want)):
                        if g != w or b != s:
                            d = dict(compiler_backend=key, case_index=i, html=x[:300], html_chars=len(x),
                                     pruv=g[:300], expected=w[:300])
                            if b != s:
                                d.update(from_output=b[:600], ts=s[:600])
                            differences.append(d)
                    row_.update(cases=len(inputs), pruv_oracle_pass=sum(g == w for g, w in zip(got, want)),
                                pruv_ts_pass=sum(b == s for b, s in zip(built, ts)), malformed_pass=bad_ok)
                    ok = (row_['pruv_oracle_pass'] == len(inputs) and row_['pruv_ts_pass'] == len(inputs)
                          and bad_ok == len(BAD))
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
