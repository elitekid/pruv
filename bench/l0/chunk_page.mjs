// Verbatim copy of splitText, chunkPage and chunkImage from Lair src/documents/chunker.ts (commit 698e1bd1).
// Only TypeScript types are removed; the JSON line driver below is added.
// Driver input: one JSON line [kind, page, text, max, ocr] (kind 'page' or 'image', ocr an object or null
// for undefined); output: the JSON array of chunk drafts.
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

/** 쪽 하나의 글을 쪽 경계를 넘지 않게 조각낸다(PDF) */
export function chunkPage(page, text, max, ocr) {
  return splitText(text, max).map(piece => ({ loc: { kind: 'page', page }, text: piece, ...(ocr ? { ocr } : {}) }));
}

/** 그림 하나의 글(OCR)을 조각낸다 */
export function chunkImage(text, max, ocr) {
  return splitText(text, max).map(piece => ({ loc: { kind: 'image' }, text: piece, ...(ocr ? { ocr } : {}) }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const [kind, page, text, max, ocr] = JSON.parse(line);
    const info = ocr === null ? undefined : ocr;
    console.log(JSON.stringify(kind === 'page' ? chunkPage(page, text, max, info) : chunkImage(text, max, info)));
  }
}
