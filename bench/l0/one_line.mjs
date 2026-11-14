// Verbatim copy of oneLine in Lair src/backend/engine-import/tail.ts at commit 698e1bd1 (whitespace runs
// folded to one space, trimmed, and cut to max UTF-16 units). Only TypeScript types are removed; the JSON
// line driver below is added.
// Driver input per line: {"text", "max"} -> the one-line text (JSON.stringify writes a lone surrogate as
// a \u escape).
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

/** 줄바꿈을 공백으로 접고 앞뒤를 다듬어 max 글자로 자른다 */
export function oneLine(text, max) {
  return text.replace(/\s+/g, ' ').trim().slice(0, max);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const q = JSON.parse(line);
    console.log(JSON.stringify(oneLine(q.text, q.max)));
  }
}
