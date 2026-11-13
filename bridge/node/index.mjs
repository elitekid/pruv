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
export const splitText = native.splitText;
export const groupTexts = native.groupTexts;
export const jpegOrientation = native.jpegOrientation;
export const shrinkPixels = native.shrinkPixels;
export const numberRanges = native.numberRanges;

/** Lair shrinkJpeg: `jpeg` is the jpeg-js module ({decode, encode}); the orientation and the pixels come
 *  from the verified Pruv jpegOrientation and shrinkPixels. undefined where TS returns undefined (the
 *  caller keeps the original). */
export function shrinkJpeg(bytes, jpeg) {
  if (!(bytes.length >= 4 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff)) return undefined;
  let decoded;
  try {
    decoded = jpeg.decode(bytes, { useTArray: true, formatAsRGBA: true });
  } catch {
    return undefined;
  }
  const { width, height } = decoded;
  if (!(width > 0 && height > 0)) return undefined;
  const s = native.shrinkPixels(decoded.data, width, height, native.jpegOrientation(bytes));
  if (s === null) return undefined;
  const encoded = jpeg.encode({ data: s.data, width: s.width, height: s.height }, 85);
  return Buffer.from(encoded.data);
}

/** Lair chunkLines: lines numbered from 1, grouped by the verified Pruv groupTexts. */
export function chunkLines(lines, max) {
  return native.groupTexts(lines, max).map(g => ({ loc: { kind: 'lines', from: g.from + 1, to: g.to + 1 }, text: g.text }));
}

/** Lair chunkBlocks: numbered blocks grouped by the verified Pruv groupTexts. */
export function chunkBlocks(blocks, max) {
  return native.groupTexts(blocks.map(b => b.text), max).map(g => ({ loc: { kind: 'block', from: blocks[g.from].n, to: blocks[g.to].n }, text: g.text }));
}
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

export const clipSheetBackground = native.clipSheetBackground;
export const clipSheetCell = native.clipSheetCell;

/** Lair renderClipSheet: `jpeg` is the jpeg-js module ({decode, encode}). The board, the fitted pictures,
 *  the label strips and the number boxes come from the verified Pruv clipSheetBackground and clipSheetCell;
 *  only the JPEG decode/encode and the JS-rounded fit size are JS (same doubles as TS). Throws the TS errors. */
export function renderClipSheet(cells, jpeg) {
  if (cells.length < 1 || cells.length > 4) throw new Error(`장면 판 칸은 1~4개여야 해(받은 ${cells.length}개).`);
  let sheet = native.clipSheetBackground();
  cells.forEach((cell, index) => {
    const decoded = jpeg.decode(cell.jpeg, { useTArray: true, formatAsRGBA: true });
    const { width, height } = decoded;
    if (!(width > 0 && height > 0)) throw new Error('장면 사진 크기를 읽지 못했어.');
    const ratio = Math.min(768 / width, 432 / height);
    const outW = Math.max(1, Math.min(768, Math.round(width * ratio)));
    const outH = Math.max(1, Math.min(432, Math.round(height * ratio)));
    sheet = native.clipSheetCell(sheet, index, decoded.data, width, height, outW, outH, cell.label, String(cell.number));
  });
  return Buffer.from(jpeg.encode({ data: sheet, width: 1560, height: 920 }, 80).data);
}
