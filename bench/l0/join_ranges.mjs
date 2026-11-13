// Verbatim copy of joinRangeParts (Lair src/documents/context.ts) at commit 698e1bd1. Only TypeScript
// types are removed; the JSON line driver below is added.
// Driver input per line: {"parts":[string,...]} -> JSON string.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

/** 화면용 범위 조각들을 ", " 로 잇는다. 400자를 넘으면 범위 경계에서 자르고 ", …" 를 붙인다(저장 검사의 인자 500자 안). src/backend/evidence.ts 도 쓴다. */
export function joinRangeParts(parts) {
  const full = parts.join(', ');
  if (full.length <= 400) return full;
  let kept = '';
  for (const part of parts) {
    const next = kept ? `${kept}, ${part}` : part;
    if (next.length + 3 > 400) break;
    kept = next;
  }
  return `${kept}, …`;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const q = JSON.parse(line);
    console.log(JSON.stringify(joinRangeParts(q.parts)));
  }
}
