// Verbatim copy of luhn in Lair src/shared/common-memory.ts at commit 698e1bd1 (the Luhn check that
// sensitiveReason runs on 13- to 19-digit runs). Only TypeScript types are removed; the JSON line driver
// below is added. Driver input per line: {"text"} -> true or false.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

export function luhn(digits) {
  let sum = 0;
  let double = false;
  for (let at = digits.length - 1; at >= 0; at--) {
    let value = digits.charCodeAt(at) - 48;
    if (double) { value *= 2; if (value > 9) value -= 9; }
    sum += value;
    double = !double;
  }
  return sum % 10 === 0;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const q = JSON.parse(line);
    console.log(JSON.stringify(luhn(q.text)));
  }
}
