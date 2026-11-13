// Verbatim copy of numberRanges and joinRangeParts from Lair src/documents/context.ts (commit 8da07603,
// unchanged at 698e1bd1). Only TypeScript types are removed; the JSON line driver below is added.
// Driver input: a JSON array of numbers per line -> JSON string.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

/** 화면용 쪽·줄·블록 범위 글: 오름차순 번호를 "3-5, 8" 꼴로(단위 낱말 없음). 400자를 넘으면 범위 경계에서 자르고 ", …" 를 붙인다(저장 검사의 인자 500자 안). */
export function numberRanges(numbers) {
  const out = [];
  for (let i = 0; i < numbers.length;) {
    let j = i;
    while (j + 1 < numbers.length && numbers[j + 1] === numbers[j] + 1) j += 1;
    out.push(j > i ? `${numbers[i]}-${numbers[j]}` : `${numbers[i]}`);
    i = j + 1;
  }
  return joinRangeParts(out);
}

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
    console.log(JSON.stringify(numberRanges(JSON.parse(line))));
  }
}
