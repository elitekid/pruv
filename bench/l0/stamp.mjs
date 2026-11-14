// Verbatim copy of stamp in Lair src/backend/clip-notice.ts at commit 698e1bd1 (the clip time label in
// the 0:03.2 shape). Only TypeScript types are removed; the JSON line driver below is added.
// Driver input per line: {"ms"} -> the label.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

/** 0:03.2 모양(초 한 자리). */
export function stamp(ms) {
  const tenths = Math.max(0, Math.round(ms / 100));
  const minutes = Math.floor(tenths / 600);
  return `${minutes}:${((tenths % 600) / 10).toFixed(1).padStart(4, '0')}`;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const q = JSON.parse(line);
    console.log(JSON.stringify(stamp(q.ms)));
  }
}
