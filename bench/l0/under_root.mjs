// Verbatim copy of under from Lair src/documents/archive.ts (commit 698e1bd1). Only TypeScript types
// are removed and the function is exported; the JSON line driver below is added.
// Driver input: a JSON [path, root] per line -> JSON boolean (sep is this platform's node:path sep).
import { sep } from 'node:path';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

export const under = (path, root) => path === root || path.startsWith(root.endsWith(sep) ? root : root + sep);

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const [path, root] = JSON.parse(line);
    console.log(JSON.stringify(under(path, root)));
  }
}
