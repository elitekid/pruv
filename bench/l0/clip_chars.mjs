// Verbatim copy of clipChars in Lair src/backend/requests/ai-result.ts at commit 698e1bd1 (the cut that
// keeps at most `chars` UTF-16 units without splitting a surrogate pair), with the isHighSurrogate helper
// it uses from the same file. Only TypeScript types are removed; the JSON line driver below is added.
// Driver input per line: {"text", "chars"} -> the clipped text.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const isHighSurrogate = (code) => code >= 0xd800 && code <= 0xdbff;

/** 글을 chars 글자(UTF-16)로 줄인다. 서로게이트 쌍 가운데서 자르지 않는다. */
export function clipChars(text, chars) {
  if (text.length <= chars) return text;
  const end = chars > 0 && isHighSurrogate(text.charCodeAt(chars - 1)) ? chars - 1 : chars;
  return text.slice(0, end);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const q = JSON.parse(line);
    console.log(JSON.stringify(clipChars(q.text, q.chars)));
  }
}
