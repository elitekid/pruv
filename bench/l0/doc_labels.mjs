// Verbatim copies of csvName (Lair src/documents/sheets.ts) and countList (Lair src/documents/context.ts)
// at commit 698e1bd1. Only TypeScript types are removed; the JSON line driver below is added.
// Driver input per line: {"f":"csvName","name":string} or {"f":"countList","items":[{page,count}...],"max":n}
// -> JSON string for csvName, {list,more} for countList.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

export function csvName(name) {
  return (name.split(/[\\/]/).pop() ?? name).replace(/\.[^.]+$/, '') || '표';
}

/** 화면용 쪽별 개수 목록: 앞 max 개를 "3 (2), 5 (1)" 꼴로, 나머지 항목 수는 more */
export function countList(items, max = 20) {
  return { list: items.slice(0, max).map(item => `${item.page} (${item.count})`).join(', '), more: Math.max(0, items.length - max) };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const q = JSON.parse(line);
    console.log(JSON.stringify(q.f === 'csvName' ? csvName(q.name) : countList(q.items, q.max)));
  }
}
