// Verbatim copy of Lair src/documents/zip.ts (commit 5d974738). Only TypeScript types
// are removed; the JSON line driver below is added.
// Driver input: one JSON line, the bytes as a hex string; output: JSON number, null or "Infinity".
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

/** zip 중앙 디렉터리에 적힌 압축 풀린 크기의 합. zip 이 아니거나 중앙 디렉터리를 읽을 수 없으면 null(손상), 크기를 알 수 없는 zip64 모양이면 Infinity(한도 초과로 본다). 압축을 풀기 전에 부른다. */
export function zipUncompressedTotal(buf) {
  const min = Math.max(0, buf.length - 0xffff - 22);
  let eocd = -1;
  for (let i = buf.length - 22; i >= min; i -= 1) {
    if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) return null;
  const count = buf.readUInt16LE(eocd + 10);
  let at = buf.readUInt32LE(eocd + 16);
  if (count === 0xffff || at === 0xffffffff) return Infinity;
  let total = 0;
  for (let i = 0; i < count; i += 1) {
    if (at + 46 > buf.length || buf.readUInt32LE(at) !== 0x02014b50) return null;
    const size = buf.readUInt32LE(at + 24);
    if (size === 0xffffffff) return Infinity;
    total += size;
    at += 46 + buf.readUInt16LE(at + 28) + buf.readUInt16LE(at + 30) + buf.readUInt16LE(at + 32);
  }
  return total;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    let out;
    try {
      const r = zipUncompressedTotal(Buffer.from(JSON.parse(line), 'hex'));
      out = r === Infinity ? 'Infinity' : r;
    } catch (e) {
      out = 'throw:' + (e && e.code ? e.code : String(e));
    }
    console.log(JSON.stringify(out));
  }
}
