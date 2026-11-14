// Verbatim copy of alignOffset in Lair src/backend/requests/ai-result.ts at commit 698e1bd1 (the UTF-16
// offset that moves back to the start of a surrogate pair), with the isHighSurrogate and isLowSurrogate
// helpers it uses from the same file. Only TypeScript types are removed; the JSON line driver below is added.
// Driver input per line: {"text", "offset"} -> the aligned offset.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const isHighSurrogate = (code) => code >= 0xd800 && code <= 0xdbff;
const isLowSurrogate = (code) => code >= 0xdc00 && code <= 0xdfff;

/** offset 이 서로게이트 쌍 가운데(low surrogate 자리)면 한 칸 앞으로 당긴 실제 시작 위치를 돌려준다. 호출한 쪽이 결과의 offset 에 이 값을 적는다. */
export function alignOffset(text, offset) {
  return offset > 0 && offset < text.length && isLowSurrogate(text.charCodeAt(offset)) && isHighSurrogate(text.charCodeAt(offset - 1)) ? offset - 1 : offset;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const q = JSON.parse(line);
    console.log(JSON.stringify(alignOffset(q.text, q.offset)));
  }
}
