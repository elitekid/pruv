// Verbatim copy of colLetters, cellText and rowPieces from Lair src/documents/sheets.ts and splitText from
// src/documents/chunker.ts (both last changed at commit b99c75b6, unchanged at 698e1bd1). Only TypeScript
// types are removed; the JSON line driver below is added. Driver input: one JSON line [cells, rowNo, max];
// output: rowPieces as [[row, col1, col2, text], ...].
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

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

/** 한 행을 "행 N: 값 | 값" 글로. 이어진 칸은 ' | ', 빈 칸을 건너뛰면 열 이름을 붙인다. max 를 넘으면 칸 단위로 나눈다. */
export function rowPieces(row, rowNo, max) {
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

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const [cells, rowNo, max] = JSON.parse(line);
    console.log(JSON.stringify(rowPieces(cells, rowNo, max).map(p => [p.row, p.col1, p.col2, p.text])));
  }
}
