// Verbatim copy of tomlString in Lair src/backend/provider-accounts.ts at commit 698e1bd1 (the TOML basic
// string used when writing engine config). Only TypeScript types are removed; the JSON line driver below is added.
// Driver input per line: a JSON string -> the TOML string.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

/** TOML 기본 문자열. 따옴표·역슬래시·제어 문자를 이스케이프한다. */
export function tomlString(value) {
  let out = '"';
  for (const char of value) {
    const code = char.codePointAt(0);
    if (char === '"') out += '\\"';
    else if (char === '\\') out += '\\\\';
    else if (code < 0x20 || code === 0x7f || code === 0x2028 || code === 0x2029) out += `\\u${code.toString(16).padStart(4, '0')}`;
    else out += char;
  }
  return `${out}"`;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    console.log(JSON.stringify(tomlString(JSON.parse(line))));
  }
}
