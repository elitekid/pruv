// Verbatim copy of groupedNumber from Lair src/documents/context.ts (commit 698e1bd1). Only TypeScript types
// are removed; the JSON line driver below is added.
// Driver input: a JSON number per line -> JSON string.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

export const groupedNumber = (value) => value.toLocaleString('en-US');

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    console.log(JSON.stringify(groupedNumber(JSON.parse(line))));
  }
}
