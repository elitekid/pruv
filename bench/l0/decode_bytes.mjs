// Verbatim copy of Lair src/documents/decode.ts (commit 5d974738). Only TypeScript types
// are removed; the JSON line driver below is added.
// Driver input: one JSON line, the bytes as a hex string; output: JSON [text, encoding, binary].
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

export function decodeBytes(buf) {
  if (buf.length >= 3 && buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf) return { text: new TextDecoder('utf-8').decode(buf.subarray(3)), encoding: 'utf-8' };
  if (buf.length >= 2 && buf[0] === 0xff && buf[1] === 0xfe) return { text: new TextDecoder('utf-16le').decode(buf.subarray(2)), encoding: 'utf-16le' };
  if (buf.length >= 2 && buf[0] === 0xfe && buf[1] === 0xff) return { text: new TextDecoder('utf-16be').decode(buf.subarray(2)), encoding: 'utf-16be' };
  try { return { text: new TextDecoder('utf-8', { fatal: true }).decode(buf), encoding: 'utf-8' }; }
  catch { return { text: new TextDecoder('euc-kr').decode(buf), encoding: 'cp949' }; }
}

/** 글 파일이 아닐 만한 바이트(앞 8 KiB 에 NUL) */
export const looksBinary = (buf) => buf.subarray(0, 8192).includes(0);

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const buf = Uint8Array.from(Buffer.from(JSON.parse(line), 'hex'));
    const r = decodeBytes(buf);
    console.log(JSON.stringify([r.text, r.encoding, looksBinary(buf)]));
  }
}
