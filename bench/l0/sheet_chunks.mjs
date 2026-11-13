// Verbatim copy of sheetCols, rowPieces, rangeOf and extractSheets from Lair src/documents/sheets.ts, with
// colLetters, cellText and splitText as in row_pieces.mjs (all last changed at commit b99c75b6, unchanged at
// 698e1bd1). Only TypeScript types are removed. Added: stand-ins for docText, addMissing and setPartialReason
// from src/documents/context.ts (the driver's limits are never reached, so they only record) and the JSON line
// driver below. Driver input: one JSON line [sheetName, rows, max]; output: the chunks as
// [[range, row1, row2, col1, col2, text], ...].
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const docText = (key, params) => ({ key, params });
function addMissing(draft, text, i18n) { draft.missing.push(text); }
function setPartialReason(draft, text, i18n) { draft.partialReason = text; }

/** 글 하나를 max 자 안쪽으로 줄바꿈·공백에서 나눈다. 자르는 자리가 없으면 max 에서 자른다. */
export function splitText(text, max) {
  const out = [];
  let rest = text.trim();
  while (rest.length > max) {
    let cut = rest.lastIndexOf('\n', max);
    if (cut < max * 0.5) cut = rest.lastIndexOf(' ', max);
    if (cut < max * 0.5) cut = max;
    // 서로게이트 쌍 가운데를 자르지 않는다
    const code = rest.charCodeAt(cut - 1);
    if (code >= 0xd800 && code <= 0xdbff) cut -= 1;
    out.push(rest.slice(0, cut).trim());
    rest = rest.slice(cut).trim();
  }
  if (rest) out.push(rest);
  return out.filter(Boolean);
}

export function colLetters(col) {
  let out = '';
  for (let n = col; n > 0; n = Math.floor((n - 1) / 26)) out = String.fromCharCode(65 + (n - 1) % 26) + out;
  return out;
}

const pad = (n) => String(n).padStart(2, '0');
export function cellText(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value.replace(/\r?\n/g, ' ').trim();
  if (typeof value === 'number') return Number.isFinite(value) ? String(Number(value.toPrecision(15))) : '';
  if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE';
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    const date = `${value.getUTCFullYear()}-${pad(value.getUTCMonth() + 1)}-${pad(value.getUTCDate())}`;
    const time = value.getUTCHours() || value.getUTCMinutes() || value.getUTCSeconds() ? ` ${pad(value.getUTCHours())}:${pad(value.getUTCMinutes())}` : '';
    return date + time;
  }
  return String(value);
}

export const sheetCols = (rows) => rows.reduce((max, row) => Math.max(max, row.length), 0);

/** 이만큼 넘게 떨어진 행은 다른 조각으로 나눈다 */
const FAR_ROWS = 50;

/** 한 행을 "행 N: 값 | 값" 글로. 이어진 칸은 ' | ', 빈 칸을 건너뛰면 열 이름을 붙인다. max 를 넘으면 칸 단위로 나눈다. */
function rowPieces(row, rowNo, max) {
  const head = `행 ${rowNo}: `;
  const out = [];
  let text = '';
  let col1 = 0;
  let col2 = 0;
  let prev = 0;
  const flush = () => { if (text) out.push({ row: rowNo, col1, col2, text: head + text }); text = ''; };
  for (let i = 0; i < row.length; i += 1) {
    const value = cellText(row[i]);
    if (!value) continue;
    const col = i + 1;
    const label = `${colLetters(col)}=`;
    for (const part of splitText(value, Math.max(max - head.length - 12, 100))) {
      let seg = (text ? prev !== col && col !== prev + 1 : col !== 1) ? label + part : part;
      if (text && text.length + seg.length + 3 > max - head.length) { flush(); seg = col !== 1 ? label + part : part; }
      if (!text) { col1 = col; text = seg; } else text += ` | ${seg}`;
      col2 = col;
      prev = col;
    }
  }
  flush();
  return out;
}

const rangeOf = (row1, row2, col1, col2) =>
  row1 === row2 && col1 === col2 ? `${colLetters(col1)}${row1}` : `${colLetters(col1)}${row1}:${colLetters(col2)}${row2}`;

export function extractSheets(loaded, ctx) {
  const draft = { chunks: [], locKind: 'cells', notes: [...loaded.notes], missing: [], sheets: [], ...(loaded.notesI18n ? { notesI18n: [...loaded.notesI18n] } : {}) };
  let cells = 0;
  let chars = 0;
  let stopped = false;
  const max = ctx.limits.chunkChars;
  for (const sheet of loaded.sheets) {
    const rowCount = sheet.rows.length;
    draft.sheets.push({ name: sheet.name, rows: rowCount, cols: sheetCols(sheet.rows) });
    if (stopped) { addMissing(draft, `시트 ${sheet.name} 은 한도를 넘어 읽지 않았어`, docText('wireDocs.missing.sheetSkipped', { sheet: sheet.name })); continue; }
    const header = `[시트: ${sheet.name}]\n`;
    let lines = [];
    let size = header.length;
    const flush = () => {
      if (!lines.length) return;
      const row1 = Math.min(...lines.map(line => line.row));
      const row2 = Math.max(...lines.map(line => line.row));
      const col1 = Math.min(...lines.map(line => line.col1));
      const col2 = Math.max(...lines.map(line => line.col2));
      const chunk = { loc: { kind: 'cells', sheet: sheet.name, range: rangeOf(row1, row2, col1, col2), row1, row2, col1, col2 }, text: header + lines.map(line => line.text).join('\n') };
      draft.chunks.push(chunk);
      lines = [];
      size = header.length;
    };
    for (let r = 0; r < rowCount; r += 1) {
      if (r % 2000 === 0) ctx.check();
      const row = sheet.rows[r];
      const filled = row.reduce((count, cell) => count + (cellText(cell) ? 1 : 0), 0);
      if (!filled) continue;
      if (cells + filled > ctx.limits.cells || chars > ctx.limits.chars) {
        flush();
        const byCells = cells + filled > ctx.limits.cells;
        addMissing(draft, `시트 ${sheet.name} 의 ${r + 1}행부터는 ${byCells ? '셀 수' : '글자 수'} 한도를 넘어 읽지 않았어`,
          docText(byCells ? 'wireDocs.missing.sheetCellLimit' : 'wireDocs.missing.sheetCharLimit', { sheet: sheet.name, row: r + 1 }));
        stopped = true;
        break;
      }
      cells += filled;
      for (const piece of rowPieces(row, r + 1, max)) {
        // 행이 멀리 떨어진 셀을 한 조각으로 묶으면 위치 범위가 부풀어 근거가 흐려진다
        if (lines.length && (size + piece.text.length + 1 > max || piece.row - lines[lines.length - 1].row > FAR_ROWS)) flush();
        lines.push(piece);
        size += piece.text.length + 1;
        chars += piece.text.length;
      }
    }
    flush();
  }
  if (draft.missing.length) setPartialReason(draft, '한도를 넘은 부분이 있어', docText('wireDocs.reason.overLimit'));
  return draft;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const ctx = { limits: { chunkChars: 0, cells: Infinity, chars: Infinity }, check() {} };
  for await (const line of createInterface({ input: process.stdin })) {
    const [name, rows, max] = JSON.parse(line);
    ctx.limits.chunkChars = max;
    const draft = extractSheets({ sheets: [{ name, rows }], notes: [] }, ctx);
    console.log(JSON.stringify(draft.chunks.map(c => [c.loc.range, c.loc.row1, c.loc.row2, c.loc.col1, c.loc.col2, c.text])));
  }
}
