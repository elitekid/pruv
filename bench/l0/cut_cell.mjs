// The cell cut inside sheetWindow (Lair src/documents/preview.ts) at commit 698e1bd1: CELL_CUT and the
// cut expression are copied verbatim, wrapped in a function of one cell text (the cut list that
// sheetWindow also fills is left out). The JSON line driver below is added.
// Driver input per line: {"text":string} -> JSON string.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const CELL_CUT = 200;

export function cutCell(text) {
  return text.length > CELL_CUT ? `${text.slice(0, CELL_CUT)}…` : text;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const q = JSON.parse(line);
    console.log(JSON.stringify(cutCell(q.text)));
  }
}
