import { createInterface } from 'node:readline';

// Source: Lair src/backend/engine-import/tail.ts:142; verbatim function body.
export function clipBytes(text, max) {
  if (Buffer.byteLength(text) <= max) return text;
  return Buffer.from(text, 'utf8').subarray(0, max).toString('utf8').replace(/�+$/, '');
}

for await (const line of createInterface({ input: process.stdin })) {
  const { hex, max } = JSON.parse(line);
  const text = Buffer.from(hex, 'hex').toString('utf8');
  console.log(JSON.stringify({ hex: Buffer.from(clipBytes(text, max), 'utf8').toString('hex') }));
}
