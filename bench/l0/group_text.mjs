// Verbatim copy of splitText, chunkLines, chunkBlocks and groupNumbered from Lair src/documents/chunker.ts
// (commit 5d974738, unchanged at 698e1bd1). Only TypeScript types are removed; the JSON line driver
// below is added. Driver input: one JSON line [lines, max]; output: chunkLines as [[from, to, text], ...].
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

/** 글 하나를 max 자 안쪽으로 줄바꿈·공백에서 나눈다. 자르는 자리가 없으면 max 에서 자른다. */
export function splitText(text, max) {
  const out = [];
  let rest = text.trim();
  while (rest.length > max) {
    let cut = rest.lastIndexOf('\n', max);
    if (cut < max * 0.5) cut = rest.lastIndexOf(' ', max);
    if (cut < max * 0.5) cut = max;
    // 서로게이트 쌍 가운데를 자르지 않는다
    const code = rest.charCodeAt(cut - 1);
    if (code >= 0xd800 && code <= 0xdbff) cut -= 1;
    out.push(rest.slice(0, cut).trim());
    rest = rest.slice(cut).trim();
  }
  if (rest) out.push(rest);
  return out.filter(Boolean);
}

/** 줄을 위에서부터 모아 max 자 안쪽 조각으로 만든다. 줄 하나가 max 를 넘으면 그 줄만 따로 나눈다(글). */
export function chunkLines(lines, max) {
  return groupNumbered(lines.map((text, i) => ({ n: i + 1, text })), max, (from, to) => ({ kind: 'lines', from, to }));
}

/** 블록을 위에서부터 모아 조각으로 만든다. 블록 하나가 max 를 넘으면 그 블록만 따로 나눈다(DOCX). */
export function chunkBlocks(blocks, max) {
  return groupNumbered(blocks, max, (from, to) => ({ kind: 'block', from, to }));
}

function groupNumbered(items, max, loc) {
  const out = [];
  let parts = [];
  let from = 0;
  let to = 0;
  let size = 0;
  const flush = () => {
    const text = parts.join('\n').trim();
    if (text) out.push({ loc: loc(from, to), text });
    parts = [];
    size = 0;
  };
  for (const item of items) {
    if (item.text.length > max) {
      flush();
      for (const piece of splitText(item.text, max)) out.push({ loc: loc(item.n, item.n), text: piece });
      continue;
    }
    if (parts.length && size + item.text.length + 1 > max) flush();
    if (!parts.length) from = item.n;
    parts.push(item.text);
    to = item.n;
    size += item.text.length + 1;
  }
  flush();
  return out;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const [lines, max] = JSON.parse(line);
    console.log(JSON.stringify(chunkLines(lines, max).map(c => [c.loc.from, c.loc.to, c.text])));
  }
}
