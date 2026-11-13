// Verbatim copy of rangeText from Lair src/documents/pdf.ts (commit 698e1bd1). Only TypeScript types are
// removed and the function is exported; the JSON line driver below is added.
// Driver input: a JSON array of numbers per line -> JSON string.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

export const rangeText = (pages) => {
  const out = [];
  for (let i = 0; i < pages.length;) {
    let j = i;
    while (j + 1 < pages.length && pages[j + 1] === pages[j] + 1) j += 1;
    out.push(j > i ? `${pages[i]}~${pages[j]}쪽` : `${pages[i]}쪽`);
    i = j + 1;
  }
  return out.join(', ');
};

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    console.log(JSON.stringify(rangeText(JSON.parse(line))));
  }
}
