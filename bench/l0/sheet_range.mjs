// The window arithmetic inside sheetWindow (Lair src/documents/preview.ts) at commit 698e1bd1: MAX_ROWS,
// MAX_COLS and the row/col/wantRows/wantCols/rowCount/colCount lines are copied verbatim, wrapped in a
// function of the sheet size and the request fields (parsing, the sheet lookup and the cell loop are left
// out; totalRows and totalCols are passed in). The JSON line driver below is added.
// Driver input per line: {"totalRows":n,"totalCols":n,"request":{row?,col?,rows?,cols?}}
//   -> JSON [row, col, rowCount, colCount].
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const MAX_ROWS = 500;
const MAX_COLS = 100;

export function sheetRange(totalRows, totalCols, request) {
  const row = Math.max(1, Math.floor(request.row ?? 1));
  const col = Math.max(1, Math.floor(request.col ?? 1));
  const wantRows = Math.min(MAX_ROWS, Math.max(1, Math.floor(request.rows ?? 200)));
  const wantCols = Math.min(MAX_COLS, Math.max(1, Math.floor(request.cols ?? 50)));
  const rowCount = Math.max(0, Math.min(wantRows, totalRows - row + 1));
  const colCount = Math.max(0, Math.min(wantCols, totalCols - col + 1));
  return [row, col, rowCount, colCount];
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const q = JSON.parse(line);
    console.log(JSON.stringify(sheetRange(q.totalRows, q.totalCols, q.request)));
  }
}
