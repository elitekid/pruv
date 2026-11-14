// Verbatim copy of stripUserInfo in Lair src/backend/git-changes.ts at commit 698e1bd1 (drops the user
// info of URLs in Git output before it is shown). Only TypeScript types are removed; the JSON line driver below is added.
// Driver input per line: a JSON string -> the text without URL user info.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

export function stripUserInfo(text) {
  return text.replace(/\b([a-z][a-z0-9+.-]*:\/\/)[^\s/]*@/gi, '$1');
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    console.log(JSON.stringify(stripUserInfo(JSON.parse(line))));
  }
}
