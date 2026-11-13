// Verbatim copy of VOID, ENTITIES, decode and parseHtml from Lair src/documents/docx.ts (last changed at
// commit b99c75b6). Only TypeScript types are removed. Added: fromRecords, canon and the JSON line driver below.
// Driver input, one JSON line per case:
//   ["html", text]     -> canon(parseHtml(text))
//   ["rec", records]   -> canon(fromRecords(records)) for a Pruv parse_html record list (parse_html.pruv)
// canon keeps tag, the own attributes href, colspan and rowspan (the only ones Lair's DOCX code reads) and
// children, as [tag, {href?, colspan?, rowspan?}, [child...]] with text children as strings.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const VOID = new Set(['br', 'img', 'hr']);
const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' };
const decode = (text) => text.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (all, name) => {
  if (name[0] === '#') {
    const code = name[1].toLowerCase() === 'x' ? parseInt(name.slice(2), 16) : parseInt(name.slice(1), 10);
    return Number.isFinite(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : '';
  }
  return ENTITIES[name.toLowerCase()] ?? all;
});

/** mammoth 출력은 짜임이 규칙적이라 작은 파서로 충분하다(허용하지 않은 태그는 어차피 버린다) */
export function parseHtml(html) {
  const root = { tag: '#root', attrs: {}, children: [] };
  const stack = [root];
  const token = /<!--[\s\S]*?-->|<(\/?)([a-zA-Z][a-zA-Z0-9]*)((?:\s+[^<>]*?)?)\s*(\/?)>|[^<]+|</g;
  for (const match of html.matchAll(token)) {
    const [raw, closing, tagName, attrText, selfClosing] = match;
    const top = stack[stack.length - 1];
    if (!tagName) { if (!raw.startsWith('<!--')) top.children.push(decode(raw)); continue; }
    const tag = tagName.toLowerCase();
    if (closing) {
      const at = stack.map(item => item.tag).lastIndexOf(tag);
      if (at > 0) stack.length = at;
      continue;
    }
    const attrs = {};
    for (const attr of attrText.matchAll(/([a-zA-Z_:][\w:.-]*)\s*=\s*"([^"]*)"/g)) attrs[attr[1].toLowerCase()] = decode(attr[2]);
    const el = { tag, attrs, children: [] };
    top.children.push(el);
    if (!VOID.has(tag) && !selfClosing) stack.push(el);
  }
  return root.children.filter(child => typeof child !== 'string' || child.trim() !== '');
}

const fromCps = (rec, at, n) => {
  let s = '';
  for (let k = 0; k < n; k += 4096) s += String.fromCodePoint(...rec.slice(at + k, at + Math.min(n, k + 4096)));
  return s;
};

/** Added: the El tree of a Pruv parse_html record list (the bridge glue does the same). */
export function fromRecords(rec) {
  if (rec.length === 1 && rec[0] === -1) throw new Error('parse_html output too large');
  const top = [];
  const els = [];
  let p = 0;
  while (p < rec.length) {
    const kind = rec[p];
    const parent = rec[p + 1];
    const into = parent === -1 ? top : els[parent].children;
    const n = rec[p + 2];
    if (kind === 0) {
      into.push(fromCps(rec, p + 3, n));
      p += 3 + n;
      continue;
    }
    const tag = fromCps(rec, p + 3, n);
    p += 3 + n;
    const attrs = {};
    for (const name of ['href', 'colspan', 'rowspan']) {
      const m = rec[p];
      p += 1;
      if (m >= 0) { attrs[name] = fromCps(rec, p, m); p += m; }
    }
    const el = { tag, attrs, children: [] };
    els.push(el);
    into.push(el);
  }
  return top;
}

const canon = (node) => typeof node === 'string' ? node : [node.tag,
  Object.fromEntries(['href', 'colspan', 'rowspan'].filter(k => Object.hasOwn(node.attrs, k)).map(k => [k, node.attrs[k]])),
  node.children.map(canon)];

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const [mode, x] = JSON.parse(line);
    const tree = mode === 'html' ? parseHtml(x) : fromRecords(x);
    console.log(JSON.stringify(tree.map(canon)));
  }
}
