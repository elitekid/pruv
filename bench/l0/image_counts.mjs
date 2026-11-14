// Verbatim copy of the listOf closure in extractPdf (Lair src/documents/pdf.ts) at commit 698e1bd1, made a
// top-level function. The inline `shown` + " 외 ..." text in the same function is the same expression.
// Only TypeScript types are removed; the JSON line driver below is added.
// Driver input per line: {"items":[{page,count}...]} -> JSON string.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

export const listOf = (items) => `${items.slice(0, 20).map(item => `${item.page}쪽 ${item.count}개`).join(', ')}${items.length > 20 ? ` 외 ${items.length - 20}쪽` : ''}`;

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const q = JSON.parse(line);
    console.log(JSON.stringify(listOf(q.items)));
  }
}
