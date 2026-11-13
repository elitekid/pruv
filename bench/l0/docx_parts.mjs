// Verbatim copy of escapeHtml, escapeAttr, isEl, inlineText, collapse, HEADING, isList, collectBlocks,
// INLINE_ALLOWED, renderHtml, inlineRender and docxParts from Lair src/documents/docx.ts (last changed at commit
// b99c75b6). Only TypeScript types are removed. parseHtml comes from the verbatim copy in parse_html.mjs.
// Added: canonParts, fromOutput and the JSON line driver below.
// Driver input, one JSON line per case:
//   ["html", text]          -> canonParts(docxParts(text))
//   ["out", [images, out]]  -> fromOutput for a Pruv docx_parts output (docx_parts.pruv) and img_count
// canonParts gives {blocks: [[n, kind, element index, text]...], html, images}; the element index of a block is
// the position of its El in the preorder of the parsed tree (the element number of the parse_html records).
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';
import { parseHtml } from './parse_html.mjs';

const escapeHtml = (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const escapeAttr = (text) => escapeHtml(text).replace(/"/g, '&quot;');

const isEl = (node) => typeof node !== 'string';

/** 요소 안 글. 줄바꿈은 \n, 그림은 [그림]. skip 이 true 인 요소는 들어가지 않는다. */
function inlineText(el, skip = () => false) {
  let out = '';
  for (const child of el.children) {
    if (!isEl(child)) { out += child; continue; }
    if (skip(child)) continue;
    if (child.tag === 'br') out += '\n';
    else if (child.tag === 'img') out += '[그림]';
    else if (['p', 'div', 'li'].includes(child.tag)) out += `${out && !out.endsWith('\n') ? ' ' : ''}${inlineText(child, skip)}`;
    else out += inlineText(child, skip);
  }
  return out;
}
const collapse = (text) => text.replace(/[ \t\r\f\v]+/g, ' ').replace(/ ?\n ?/g, '\n').trim();

const HEADING = /^h[1-6]$/;
const isList = (el) => el.tag === 'ul' || el.tag === 'ol';

function collectBlocks(nodes, out) {
  const add = (kind, el, text) => {
    const clean = collapse(text);
    if (clean) out.push({ n: out.length + 1, kind, el, text: clean });
  };
  for (const node of nodes) {
    if (!isEl(node)) continue;
    if (node.tag === 'p') add('p', node, inlineText(node));
    else if (HEADING.test(node.tag)) add('h', node, inlineText(node));
    else if (isList(node)) {
      for (const item of node.children.filter(isEl)) {
        if (item.tag !== 'li') { collectBlocks([item], out); continue; }
        add('li', item, inlineText(item, isList));
        collectBlocks(item.children.filter(child => isEl(child) && isList(child)), out);
      }
    } else if (node.tag === 'table') {
      const rows = [];
      const gather = (parent) => { for (const child of parent.children.filter(isEl)) { if (child.tag === 'tr') rows.push(child); else if (['thead', 'tbody', 'tfoot'].includes(child.tag)) gather(child); } };
      gather(node);
      for (const row of rows) {
        const cells = row.children.filter(isEl).filter(cell => cell.tag === 'td' || cell.tag === 'th').map(cell => collapse(inlineText(cell)).replace(/\n+/g, ' '));
        add('tr', row, cells.join(' | ').replace(/^( \| )+$/, ''));
      }
    } else collectBlocks(node.children, out);
  }
}

const INLINE_ALLOWED = new Set(['strong', 'em', 'u', 'sup', 'sub']);

/** 허용한 태그만 남긴 미리보기 HTML. 블록 요소에 data-block 번호를 단다. */
function renderHtml(nodes, numbers, inCell = false) {
  let out = '';
  for (const node of nodes) {
    if (!isEl(node)) { out += escapeHtml(node); continue; }
    const n = numbers.get(node);
    const mark = n ? ` data-block="${n}"` : '';
    const tag = node.tag;
    if (tag === 'script' || tag === 'style') continue;
    const inner = (cell = inCell) => renderHtml(node.children, numbers, cell);
    if (tag === 'p' || HEADING.test(tag)) {
      // 번호 없는 문단은 표 칸 안 것만 남긴다(바깥의 번호 없는 문단은 빈 문단)
      if (n || inCell) out += `<${tag}${mark}>${inner()}</${tag}>`;
    } else if (tag === 'ul' || tag === 'ol') out += `<${tag}>${inner()}</${tag}>`;
    else if (tag === 'li') {
      const nested = node.children.filter(child => isEl(child) && isList(child)).map(child => renderHtml([child], numbers)).join('');
      out += n ? `<li${mark}>${inlineRender(node, numbers)}${nested}</li>` : nested;
    }
    else if (tag === 'table') out += `<table>${inner()}</table>`;
    else if (tag === 'thead' || tag === 'tbody' || tag === 'tfoot') out += `<${tag}>${inner()}</${tag}>`;
    else if (tag === 'tr') out += `<tr${mark}>${inner()}</tr>`;
    else if (tag === 'td' || tag === 'th') {
      const span = ['colspan', 'rowspan'].map(name => /^\d{1,3}$/.test(node.attrs[name] ?? '') ? ` ${name}="${node.attrs[name]}"` : '').join('');
      out += `<${tag}${span}>${inner(true)}</${tag}>`;
    } else if (INLINE_ALLOWED.has(tag)) out += `<${tag}>${inner()}</${tag}>`;
    else if (tag === 'br') out += '<br>';
    else if (tag === 'img') out += '[그림]';
    else if (tag === 'a') {
      const href = node.attrs.href ?? '';
      out += /^https:\/\//i.test(href) ? `<a href="${escapeAttr(href)}" rel="noopener noreferrer">${inner()}</a>` : inner();
    } else out += inner();
  }
  return out;
}

/** li 안에서 중첩 목록을 뺀 글머리 내용 */
function inlineRender(li, numbers) {
  return renderHtml(li.children.filter(child => !(isEl(child) && isList(child))), numbers);
}

export function docxParts(html) {
  const tree = parseHtml(html);
  const blocks = [];
  collectBlocks(tree, blocks);
  const numbers = new Map(blocks.map(block => [block.el, block.n]));
  const images = (html.match(/<img\b/gi) ?? []).length;
  return { blocks, html: renderHtml(tree, numbers), images };
}

/** Added: preorder positions of the elements of tree. */
function preorder(nodes, at = new Map()) {
  const stack = [...nodes].reverse();
  while (stack.length) {
    const node = stack.pop();
    if (!isEl(node)) continue;
    at.set(node, at.size);
    for (let k = node.children.length - 1; k >= 0; k--) stack.push(node.children[k]);
  }
  return at;
}

const KINDS = ['p', 'h', 'li', 'tr'];

const fromCps = (cps, at, n) => {
  let s = '';
  for (let k = 0; k < n; k += 4096) s += String.fromCodePoint(...cps.slice(at + k, at + Math.min(n, k + 4096)));
  return s;
};

/** Added: {blocks: [[n, kind, element index, text]], html, images} for a Pruv output (the bridge glue does the same). */
export function fromOutput(images, out) {
  if (out.length === 1 && out[0] === -1) throw new Error('docx_parts input malformed or too large');
  const blocks = [];
  let p = 1;
  for (let b = 0; b < out[0]; b++) {
    const n = out[p + 2];
    blocks.push([b + 1, KINDS[out[p]], out[p + 1], fromCps(out, p + 3, n)]);
    p += 3 + n;
  }
  const html = fromCps(out, p + 1, out[p]);
  if (p + 1 + out[p] !== out.length) throw new Error('docx_parts output has trailing slots');
  return { blocks, html, images };
}

/** Added: docxParts with element indexes. docxParts keeps its tree to itself, so the indexes come from collectBlocks
 * over a second parse of the same text, whose blocks must match. */
function canonParts(html) {
  const parts = docxParts(html);
  const tree = parseHtml(html);
  const at = preorder(tree);
  const again = [];
  collectBlocks(tree, again);
  if (again.length !== parts.blocks.length) throw new Error('second parse gave other blocks');
  const blocks = parts.blocks.map((b, k) => {
    if (again[k].n !== b.n || again[k].kind !== b.kind || again[k].text !== b.text) throw new Error('second parse gave other blocks');
    return [b.n, b.kind, at.get(again[k].el), b.text];
  });
  return { blocks, html: parts.html, images: parts.images };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const [mode, x] = JSON.parse(line);
    console.log(JSON.stringify(mode === 'html' ? canonParts(x) : fromOutput(x[0], x[1])));
  }
}
