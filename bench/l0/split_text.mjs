// Verbatim copy of splitText from Lair src/documents/chunker.ts (commit 5d974738, unchanged at 698e1bd1).
// Only TypeScript types are removed; the JSON line driver below is added.
// Driver input: one JSON line [text, max]; output: the JSON array of pieces.
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

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const [text, max] = JSON.parse(line);
    console.log(JSON.stringify(splitText(text, max)));
  }
}
