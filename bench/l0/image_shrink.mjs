// Verbatim copy of isJpeg, orientationFromTiff, readOrientation, boxShrink and applyOrientation from Lair
// src/documents/image-shrink.ts (commit 28f03e08, unchanged at 698e1bd1), plus the lines of shrinkJpeg
// between jpeg-js decode and encode (shrinkDecoded below: same lines, returning the upright pixels instead
// of encoding them). Only TypeScript types are removed; the JSON line driver below is added.
// Driver input: ["o", hex bytes] -> readOrientation; ["p", width, height, orientation, hex RGBA] ->
// null (TS returns undefined) or [width, height, hex RGBA].
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

export const IMAGE_LONG_SIDE = 2000;

/** JPEG 머리가 SOI(FF D8 FF)인지 */
function isJpeg(bytes) {
  return bytes.length >= 4 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
}

/** TIFF 헤더에서 IFD0 의 방향 태그(0x0112)를 읽는다. 범위를 벗어나거나 깨졌으면 1 */
function orientationFromTiff(bytes, tiff, end) {
  if (tiff + 8 > end) return 1;
  let little;
  if (bytes[tiff] === 0x49 && bytes[tiff + 1] === 0x49) little = true;
  else if (bytes[tiff] === 0x4d && bytes[tiff + 1] === 0x4d) little = false;
  else return 1;
  const u16 = (at) => (little ? bytes[at] | (bytes[at + 1] << 8) : (bytes[at] << 8) | bytes[at + 1]);
  const u32 = (at) => (little
    ? (bytes[at] | (bytes[at + 1] << 8) | (bytes[at + 2] << 16) | (bytes[at + 3] << 24)) >>> 0
    : ((bytes[at] << 24) | (bytes[at + 1] << 16) | (bytes[at + 2] << 8) | bytes[at + 3]) >>> 0);
  if (u16(tiff + 2) !== 42) return 1;
  const ifd = tiff + u32(tiff + 4);
  if (ifd + 2 > end) return 1;
  const count = u16(ifd);
  for (let i = 0; i < count; i += 1) {
    const entry = ifd + 2 + i * 12;
    if (entry + 12 > end) return 1;
    if (u16(entry) !== 0x0112) continue;
    const value = u16(entry + 8);
    return value >= 1 && value <= 8 ? value : 1;
  }
  return 1;
}

/** APP1 Exif 조각에서 방향(1~8)을 읽는다. 없거나 깨졌으면 1 */
function readOrientation(bytes) {
  let pos = 2;
  while (pos + 4 <= bytes.length) {
    if (bytes[pos] !== 0xff) return 1;
    const marker = bytes[pos + 1];
    if (marker === 0xff) { pos += 1; continue; }
    if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) { pos += 2; continue; }
    if (marker === 0xda || marker === 0xd9) return 1;
    const length = (bytes[pos + 2] << 8) | bytes[pos + 3];
    if (length < 2) return 1;
    const end = Math.min(pos + 2 + length, bytes.length);
    if (marker === 0xe1 && pos + 10 <= end
      && bytes[pos + 4] === 0x45 && bytes[pos + 5] === 0x78 && bytes[pos + 6] === 0x69 && bytes[pos + 7] === 0x66
      && bytes[pos + 8] === 0 && bytes[pos + 9] === 0) {
      return orientationFromTiff(bytes, pos + 10, end);
    }
    pos += 2 + length;
  }
  return 1;
}

/** 면적 평균(box)으로 RGBA 를 outWidth x outHeight 로 줄인다. 알파는 255 */
function boxShrink(src, width, height, outWidth, outHeight) {
  const out = new Uint8ClampedArray(outWidth * outHeight * 4);
  const xEdges = new Int32Array(outWidth + 1);
  for (let ox = 0; ox <= outWidth; ox += 1) xEdges[ox] = Math.floor(ox * width / outWidth);
  let write = 0;
  for (let oy = 0; oy < outHeight; oy += 1) {
    const y0 = Math.floor(oy * height / outHeight);
    const y1 = Math.max(y0 + 1, Math.floor((oy + 1) * height / outHeight));
    for (let ox = 0; ox < outWidth; ox += 1) {
      const x0 = xEdges[ox];
      const x1 = Math.max(x0 + 1, xEdges[ox + 1]);
      let r = 0;
      let g = 0;
      let b = 0;
      for (let y = y0; y < y1; y += 1) {
        let read = (y * width + x0) * 4;
        for (let x = x0; x < x1; x += 1) {
          r += src[read];
          g += src[read + 1];
          b += src[read + 2];
          read += 4;
        }
      }
      const n = (y1 - y0) * (x1 - x0);
      out[write] = Math.round(r / n);
      out[write + 1] = Math.round(g / n);
      out[write + 2] = Math.round(b / n);
      out[write + 3] = 255;
      write += 4;
    }
  }
  return out;
}

/** EXIF 방향 2~8 을 픽셀에 적용해 똑바른 그림으로 만든다. 5~8 은 가로·세로가 바뀐다 */
function applyOrientation(pixels, width, height, orientation) {
  if (orientation === 1) return { data: pixels, width, height };
  const swap = orientation >= 5;
  const outWidth = swap ? height : width;
  const outHeight = swap ? width : height;
  const out = new Uint8ClampedArray(outWidth * outHeight * 4);
  const from = new Uint32Array(pixels.buffer, pixels.byteOffset, width * height);
  const to = new Uint32Array(out.buffer, out.byteOffset, outWidth * outHeight);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      let dx = x;
      let dy = y;
      if (orientation === 2) { dx = width - 1 - x; }
      else if (orientation === 3) { dx = width - 1 - x; dy = height - 1 - y; }
      else if (orientation === 4) { dy = height - 1 - y; }
      else if (orientation === 5) { dx = y; dy = x; }
      else if (orientation === 6) { dx = height - 1 - y; dy = x; }
      else if (orientation === 7) { dx = height - 1 - y; dy = width - 1 - x; }
      else { dx = y; dy = width - 1 - x; }
      to[dy * outWidth + dx] = from[y * width + x];
    }
  }
  return { data: out, width: outWidth, height: outHeight };
}


export function shrinkDecoded(decoded, orientation) {
  const { width, height } = decoded;
  if (!(width > 0 && height > 0)) return undefined;
  const longSide = Math.max(width, height);
  if (longSide <= IMAGE_LONG_SIDE && orientation === 1) return undefined;
  let scaledWidth = width;
  let scaledHeight = height;
  if (longSide > IMAGE_LONG_SIDE) {
    scaledWidth = Math.max(1, Math.round(width * IMAGE_LONG_SIDE / longSide));
    scaledHeight = Math.max(1, Math.round(height * IMAGE_LONG_SIDE / longSide));
  }
  const scaled = boxShrink(decoded.data, width, height, scaledWidth, scaledHeight);
  const upright = applyOrientation(scaled, scaledWidth, scaledHeight, orientation);
  return upright;
}

export { isJpeg, readOrientation };

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const v = JSON.parse(line);
    let out;
    if (v[0] === 'o') {
      out = readOrientation(new Uint8Array(Buffer.from(v[1], 'hex')));
    } else {
      const r = shrinkDecoded({ width: v[1], height: v[2], data: new Uint8Array(Buffer.from(v[4], 'hex')) }, v[3]);
      out = r === undefined ? null : [r.width, r.height, Buffer.from(r.data.buffer, r.data.byteOffset, r.data.length).toString('hex')];
    }
    console.log(JSON.stringify(out));
  }
}
