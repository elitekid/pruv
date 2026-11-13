import { createRequire } from 'node:module';
import { crc32, deflateSync } from 'node:zlib';
const require = createRequire(import.meta.url);
const native = require('./pruv_bridge.node');
export const clipBytes = native.clipBytes;
export const hostWithin = native.hostWithin;
export const versionAtLeast = native.versionAtLeast;
export const colLetters = native.colLetters;
export const termPlain = native.termPlain;
export const termState = native.termState;
export const decodeBytes = native.decodeBytes;
export const looksBinary = native.looksBinary;
export const zipUncompressedTotal = native.zipUncompressedTotal;
export const pngScanlines = native.pngScanlines;

// PNG chunk framing, as in Lair src/documents/png.ts.
function chunk(type, body) {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(body.length, 0);
  head.write(type, 4, 'latin1');
  const tail = Buffer.alloc(4);
  tail.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), body])) >>> 0, 0);
  return Buffer.concat([head, body, tail]);
}

/** Lair encodePng: the pixels come from the verified Pruv pngScanlines; only the deflate and the PNG
 *  chunks are JS (byte-identical to TS). null where TS returns null. Throws (InvalidArg) outside the
 *  integer domain of pngScanlines. */
export function encodePng(image, maxPixels) {
  const { width, height, kind, data } = image;
  if (!(width > 0 && height > 0) || ![1, 2, 3].includes(kind)) return null;
  const s = native.pngScanlines(data, width, height, kind, maxPixels);
  if (s === null) return null;
  const header = Buffer.alloc(13);
  header.writeUInt32BE(s.width, 0);
  header.writeUInt32BE(s.height, 4);
  header[8] = 8;
  header[9] = kind === 1 ? 0 : 2;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(s.raw, { level: 1 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}
