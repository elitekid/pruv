// Verbatim copy of pad and cellText from Lair src/documents/sheets.ts (commit 698e1bd1). Only TypeScript
// types are removed; the JSON line driver below is added.
// Driver input: integer per line -> JSON string of cellText(n).
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

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

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    console.log(JSON.stringify(cellText(JSON.parse(line))));
  }
}
