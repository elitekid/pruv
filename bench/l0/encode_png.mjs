// Verbatim copy of Lair src/documents/png.ts (commit 5d974738). Only TypeScript types
// are removed; the JSON line driver below is added.
// Driver input: one JSON line [width, height, kind, data hex, maxPixels]; output: the PNG as a hex
// string, or null.
import { crc32, deflateSync } from 'node:zlib';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

// pdf.js 가 꺼낸 쪽 그림(날 화소)을 OCR 에 넣을 PNG 로 만든다. 순수 JS 라 그림 그리기 부품(canvas)이 필요 없다.
// kind 는 pdf.js ImageKind: 1 = 1비트 흑백, 2 = RGB 24비트, 3 = RGBA 32비트.

function chunk(type, body) {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(body.length, 0);
  head.write(type, 4, 'latin1');
  const tail = Buffer.alloc(4);
  tail.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), body])) >>> 0, 0);
  return Buffer.concat([head, body, tail]);
}

/** 화소가 maxPixels 를 넘으면 정수 배로 솎아 줄인다. 그림이 아니면 null. */
export function encodePng(image, maxPixels) {
  const { width, height, kind, data } = image;
  if (!(width > 0 && height > 0) || ![1, 2, 3].includes(kind)) return null;
  const step = width * height > maxPixels ? Math.ceil(Math.sqrt(width * height / maxPixels)) : 1;
  const outW = Math.floor(width / step);
  const outH = Math.floor(height / step);
  if (outW < 1 || outH < 1) return null;
  const color = kind === 1 ? 0 : 2;
  const channels = kind === 1 ? 1 : 3;
  const rowBytes = 1 + outW * channels;
  const raw = Buffer.alloc(rowBytes * outH);
  const bitRow = (width + 7) >> 3;
  let white = 0;
  for (let y = 0; y < outH; y += 1) {
    const sy = y * step;
    let at = y * rowBytes + 1;
    for (let x = 0; x < outW; x += 1) {
      const sx = x * step;
      if (kind === 1) {
        const bit = (data[sy * bitRow + (sx >> 3)] >> (7 - (sx & 7))) & 1;
        raw[at++] = bit ? 255 : 0;
        white += bit;
      } else if (kind === 2) {
        const from = (sy * width + sx) * 3;
        raw[at++] = data[from]; raw[at++] = data[from + 1]; raw[at++] = data[from + 2];
      } else {
        // 투명한 곳은 흰 종이로 본다
        const from = (sy * width + sx) * 4;
        const alpha = data[from + 3] / 255;
        raw[at++] = Math.round(data[from] * alpha + 255 * (1 - alpha));
        raw[at++] = Math.round(data[from + 1] * alpha + 255 * (1 - alpha));
        raw[at++] = Math.round(data[from + 2] * alpha + 255 * (1 - alpha));
      }
    }
  }
  // 1비트 그림은 쪽 대부분이 흰 종이여야 정상이다. 반대면 뒤집어 읽은 것이다(이미지 마스크).
  if (kind === 1 && white < outW * outH / 2) {
    for (let y = 0; y < outH; y += 1) for (let x = 0; x < outW; x += 1) raw[y * rowBytes + 1 + x] = 255 - raw[y * rowBytes + 1 + x];
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(outW, 0);
  header.writeUInt32BE(outH, 4);
  header[8] = 8;
  header[9] = color;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(raw, { level: 1 })),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    let out;
    try {
      const [width, height, kind, hex, maxPixels] = JSON.parse(line);
      const r = encodePng({ width, height, kind, data: new Uint8Array(Buffer.from(hex, 'hex')) }, maxPixels);
      out = r === null ? null : r.toString('hex');
    } catch (e) {
      out = 'throw:' + (e && e.code ? e.code : String(e));
    }
    console.log(JSON.stringify(out));
  }
}
