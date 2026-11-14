// Verbatim copy of chatRefText in Lair src/shared/chat-ref.ts at commit 698e1bd1 (the chat reference text
// the input box inserts). Only TypeScript types are removed; the JSON line driver below is added.
// Driver input per line: {"title", "id"} -> the reference text.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

/** 입력칸에 넣을 참조 글. 제목의 `\`·`[`·`]` 는 `\` 로 이스케이프하고 줄바꿈은 공백으로 바꾼다. */
export function chatRefText(title, id) {
  const clean = title.replace(/\s*[\r\n]+\s*/g, ' ').replace(/[\\[\]]/g, '\\$&');
  return `@[${clean}](chat:${id})`;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const q = JSON.parse(line);
    console.log(JSON.stringify(chatRefText(q.title, q.id)));
  }
}
