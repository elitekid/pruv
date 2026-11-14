// Verbatim copy of validThread in Lair src/backend/engine-import/tail.ts at commit 698e1bd1 (the shape a
// conversation number must have before it is used as a file name). Only TypeScript types are removed; the
// JSON line driver below is added. Driver input per line: {"text"} -> true or false.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

/** 대화 번호를 파일 이름으로 쓰기 전 거르는 모양. 경로 글자·점으로 시작하는 이름을 막는다 */
export function validThread(thread) {
  return /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(thread);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const q = JSON.parse(line);
    console.log(JSON.stringify(validThread(q.text)));
  }
}
