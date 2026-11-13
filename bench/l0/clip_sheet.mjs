// Verbatim copy of src/documents/clip-sheet.ts from Lair (commit e0e70c08, unchanged at 698e1bd1). Only
// TypeScript types are removed, the jpeg-js import is replaced by the driver's pass-through stubs below
// (decode returns the cell's raw RGBA unchanged, encode returns the sheet pixels) and
// BOARD_CLIP_SHEET_CELLS (src/shared/board-video.ts) is inlined as 4; the JSON line driver is added.
// Driver input: [[width, height, hex RGBA, number, label], ...] per line -> crc32 of the 1560 x 920 RGBA
// sheet as 8 hex digits, or {"error": message} if renderClipSheet throws.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';
import { crc32 } from 'node:zlib';

const decode = (jpeg) => jpeg;
const encode = (image) => ({ data: image.data });

export const SHEET_WIDTH = 1560;
export const SHEET_HEIGHT = 920;
export const SHEET_MAX_CELLS = 4;
const QUALITY = 80;
const CELL_WIDTH = 768;
const CELL_HEIGHT = 432;
const STRIP_HEIGHT = 20;
const COLUMN_X = [8, 784];
const ROW_Y = [8, 468];
const BACKGROUND = [13, 17, 23];
const SCALE = 2;
const GLYPH_WIDTH = 5;
const GLYPH_HEIGHT = 7;
const GLYPH_ADVANCE = (GLYPH_WIDTH + 1) * SCALE;


/** 5×7 비트맵 글꼴. 한 줄이 5비트(왼쪽이 높은 비트)다. 0~9 와 ':' '.' 만 있다. */
const FONT = {
  '0': [0b01110, 0b10001, 0b10011, 0b10101, 0b11001, 0b10001, 0b01110],
  '1': [0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110],
  '2': [0b01110, 0b10001, 0b00001, 0b00010, 0b00100, 0b01000, 0b11111],
  '3': [0b11110, 0b00001, 0b00001, 0b01110, 0b00001, 0b00001, 0b11110],
  '4': [0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010],
  '5': [0b11111, 0b10000, 0b11110, 0b00001, 0b00001, 0b10001, 0b01110],
  '6': [0b00110, 0b01000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110],
  '7': [0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000],
  '8': [0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110],
  '9': [0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00010, 0b01100],
  ':': [0b00000, 0b00100, 0b00100, 0b00000, 0b00100, 0b00100, 0b00000],
  '.': [0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b01100, 0b01100],
};

function fillRect(data, x, y, width, height, color) {
  for (let row = y; row < y + height; row += 1) {
    let at = (row * SHEET_WIDTH + x) * 4;
    for (let col = 0; col < width; col += 1) {
      data[at] = color[0];
      data[at + 1] = color[1];
      data[at + 2] = color[2];
      data[at + 3] = 255;
      at += 4;
    }
  }
}

function textWidth(text) {
  return text.length * GLYPH_ADVANCE - SCALE;
}

/** 흰 글자를 (x, y) 왼쪽 위부터 2배로 그린다. 글꼴에 없는 글자는 건너뛴다. */
function drawText(data, x, y, text) {
  let left = x;
  for (const char of text) {
    const glyph = FONT[char];
    if (glyph) {
      for (let row = 0; row < GLYPH_HEIGHT; row += 1) {
        for (let col = 0; col < GLYPH_WIDTH; col += 1) {
          if ((glyph[row] >> (GLYPH_WIDTH - 1 - col)) & 1) fillRect(data, left + col * SCALE, y + row * SCALE, SCALE, SCALE, [255, 255, 255]);
        }
      }
    }
    left += GLYPH_ADVANCE;
  }
}

/** 원본을 비율을 지키며 칸 안에 맞춰 가운데에 그린다(면적 평균). 남는 곳은 바탕색 그대로 둔다. */
function drawFitted(data, source, left, top) {
  const { width, height } = source;
  const ratio = Math.min(CELL_WIDTH / width, CELL_HEIGHT / height);
  const outWidth = Math.max(1, Math.min(CELL_WIDTH, Math.round(width * ratio)));
  const outHeight = Math.max(1, Math.min(CELL_HEIGHT, Math.round(height * ratio)));
  const originX = left + Math.floor((CELL_WIDTH - outWidth) / 2);
  const originY = top + Math.floor((CELL_HEIGHT - outHeight) / 2);
  for (let oy = 0; oy < outHeight; oy += 1) {
    const y0 = Math.floor(oy * height / outHeight);
    const y1 = Math.max(y0 + 1, Math.floor((oy + 1) * height / outHeight));
    let write = ((originY + oy) * SHEET_WIDTH + originX) * 4;
    for (let ox = 0; ox < outWidth; ox += 1) {
      const x0 = Math.floor(ox * width / outWidth);
      const x1 = Math.max(x0 + 1, Math.floor((ox + 1) * width / outWidth));
      let r = 0;
      let g = 0;
      let b = 0;
      for (let y = y0; y < y1; y += 1) {
        let read = (y * width + x0) * 4;
        for (let x = x0; x < x1; x += 1) {
          r += source.data[read];
          g += source.data[read + 1];
          b += source.data[read + 2];
          read += 4;
        }
      }
      const n = (y1 - y0) * (x1 - x0);
      data[write] = Math.round(r / n);
      data[write + 1] = Math.round(g / n);
      data[write + 2] = Math.round(b / n);
      data[write + 3] = 255;
      write += 4;
    }
  }
}

/** 장면 JPEG 1~4장으로 판 JPEG 을 굽는다. 칸 수가 범위 밖이거나 JPEG 을 풀지 못하면 던진다. */
export function renderClipSheet(cells) {
  if (cells.length < 1 || cells.length > SHEET_MAX_CELLS) throw new Error(`장면 판 칸은 1~${SHEET_MAX_CELLS}개여야 해(받은 ${cells.length}개).`);
  const data = new Uint8Array(SHEET_WIDTH * SHEET_HEIGHT * 4);
  fillRect(data, 0, 0, SHEET_WIDTH, SHEET_HEIGHT, BACKGROUND);
  cells.forEach((cell, index) => {
    const left = COLUMN_X[index % 2];
    const top = ROW_Y[Math.floor(index / 2)];
    const decoded = decode(cell.jpeg, { useTArray: true, formatAsRGBA: true });
    if (!(decoded.width > 0 && decoded.height > 0)) throw new Error('장면 사진 크기를 읽지 못했어.');
    drawFitted(data, decoded, left, top);
    const stripTop = top + CELL_HEIGHT;
    fillRect(data, left, stripTop, CELL_WIDTH, STRIP_HEIGHT, [0, 0, 0]);
    drawText(data, left + Math.floor((CELL_WIDTH - textWidth(cell.label)) / 2), stripTop + Math.floor((STRIP_HEIGHT - GLYPH_HEIGHT * SCALE) / 2), cell.label);
    const numberText = String(cell.number);
    const padding = 4;
    fillRect(data, left, top, textWidth(numberText) + padding * 2, GLYPH_HEIGHT * SCALE + padding * 2, [0, 0, 0]);
    drawText(data, left + padding, top + padding, numberText);
  });
  return Buffer.from(encode({ data, width: SHEET_WIDTH, height: SHEET_HEIGHT }, QUALITY).data);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const cells = JSON.parse(line).map(([width, height, hex, number, label]) => (
      { jpeg: { width, height, data: new Uint8Array(Buffer.from(hex, 'hex')) }, number, label }));
    let out;
    try {
      out = (crc32(renderClipSheet(cells)) >>> 0).toString(16).padStart(8, '0');
    } catch (error) {
      out = { error: error.message };
    }
    console.log(JSON.stringify(out));
  }
}
