import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

export function colLetters(col) {
  let out = '';
  for (let n = col; n > 0; n = Math.floor((n - 1) / 26)) out = String.fromCharCode(65 + (n - 1) % 26) + out;
  return out;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const value = JSON.parse(line);
    console.log(JSON.stringify(colLetters(value)));
  }
}
