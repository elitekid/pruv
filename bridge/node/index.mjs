import { createRequire } from 'node:module';
import { crc32, deflateSync } from 'node:zlib';
import { createHash } from 'node:crypto';
import { open } from 'node:fs/promises';
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
export const csvName = native.csvName;
export const joinRangeParts = native.joinRangeParts;
export const cutCell = native.cutCell;
export const countListText = native.countListText;
export const countListMore = native.countListMore;

/** Lair countList (src/documents/context.ts): the first max "page (count)" items as text and the number of
 *  items left out. The text and the count come from the verified Pruv countListText and countListMore; pages,
 *  counts and max must be integers in their domains (InvalidArg). */
export function countList(items, max = 20) {
  return {
    list: native.countListText(items.map(item => item.page), items.map(item => item.count), max),
    more: native.countListMore(items.length, max),
  };
}

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

export const kindCode = native.kindCode;
export const extensionAt = native.extensionAt;
const KINDS = ['unknown', 'pdf', 'docx', 'xlsx', 'csv', 'image', 'text', 'unsupported'];

/** Lair extensionOf: the start index comes from the verified Pruv extensionAt; the Unicode lowercasing is JS. */
export function extensionOf(name) {
  const at = native.extensionAt(name);
  return at < 0 ? '' : name.slice(at).toLowerCase();
}

/** Lair kindOf, decided by the verified Pruv kindCode. */
export function kindOf(name) {
  return KINDS[native.kindCode(name)];
}

export const rowTextPieces = native.rowTextPieces;

// pad and cellText verbatim from Lair src/documents/sheets.ts.
const pad = (n) => String(n).padStart(2, '0');
function cellText(value) {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value.replace(/\r?\n/g, ' ').trim();
  if (typeof value === 'number') return Number.isFinite(value) ? String(Number(value.toPrecision(15))) : '';
  if (typeof value === 'boolean') return value ? 'TRUE' : 'FALSE';
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    const date = `${value.getUTCFullYear()}-${pad(value.getUTCMonth() + 1)}-${pad(value.getUTCDate())}`;
    const time = value.getUTCHours() || value.getUTCMinutes() || value.getUTCSeconds() ? ` ${pad(value.getUTCHours())}:${pad(value.getUTCMinutes())}` : '';
    return date + time;
  }
  return String(value);
}

/** Lair rowPieces: the cell values become text with Lair's cellText (JS); the pieces, the labels and the
 *  cuts come from the verified Pruv rowTextPieces. */
export function rowPieces(row, rowNo, max) {
  return native.rowTextPieces(row.map(cellText), rowNo, max);
}

export const sheetChunks = native.sheetChunks;
export const cellRange = native.cellRange;

/** The chunks extractSheets makes from one sheet within its cell and character limits: the rows become
 *  pieces with rowPieces, and the verified Pruv sheetChunks groups them and names their A1 ranges. */
export function extractSheetChunks(name, rows, max) {
  const pieces = rows.flatMap((row, r) => rowPieces(row, r + 1, max));
  return native.sheetChunks(name, pieces, max).map(c => ({
    loc: { kind: 'cells', sheet: name, range: c.range, row1: c.row1, row2: c.row2, col1: c.col1, col2: c.col2 },
    text: c.text,
  }));
}

export const textAroundPlan = native.textAroundPlan;

// failAround verbatim from Lair src/documents/preview.ts.
const failAround = (reason, extra = {}) =>
  ({ ok: false, reason, totalLines: 0, from: 0, to: 0, target: 0, text: '', truncated: false, bytes: 0, ...extra });

/** Lair textAround: the text around a target line of a file, within the byte budget. The file is read
 *  whole (Lair reads it in 1 MiB blocks); the verified Pruv textAroundPlan picks the shown bytes, and the
 *  hash, the decode and the line count are the same tail steps as Lair. Defaults and line flooring are
 *  Lair's; before, after and maxBytes must then be integers in the textAroundPlan domain (InvalidArg). */
export async function textAround(request) {
  const before = Math.max(0, request.before ?? 200);
  const after = Math.max(0, request.after ?? 200);
  const maxBytes = request.maxBytes ?? 256 * 1024;
  let file;
  try { file = await open(request.path, 'r'); } catch (error) {
    return error.code === 'ENOENT'
      ? failAround('파일이 없어', { reasonI18n: { key: 'wireWork.documents.preview.fileMissing' } })
      : failAround('파일을 열지 못했어', { reasonI18n: { key: 'wireWork.documents.preview.openFailed' } });
  }
  let buf;
  try { buf = await file.readFile(); } finally { await file.close(); }
  const target = Math.max(1, Math.floor(request.line));
  const sourceVersion = createHash('sha256').update(buf).digest('hex');
  if (request.expectSource && request.expectSource !== sourceVersion) return failAround('changed', { sourceVersion });
  const plan = native.textAroundPlan(buf, target, before, after, maxBytes);
  if (plan[0] === 0) return failAround('그 줄이 파일 끝을 넘었어', { sourceVersion, totalLines: plan[1], reasonI18n: { key: 'wireWork.documents.preview.linePastEnd' } });
  const [, totalLines, shown, b1, b2, t1, t2, a1, a2, beforeLines, truncated, targetCut] = plan;
  const used = Buffer.concat([buf.subarray(b1, b2), buf.subarray(t1, t2), buf.subarray(a1, a2)]);
  let text = native.decodeBytes(used).text.replace(/\r\n/g, '\n');
  if (text.endsWith('\n')) text = text.slice(0, -1);
  const lines = text === '' && used.length === 0 ? 0 : text.split('\n').length;
  const from0 = shown - beforeLines;
  return { ok: true, sourceVersion, totalLines, from: from0, to: Math.min(from0 + lines - 1, totalLines), target: shown, text, truncated: truncated === 1, bytes: used.length, targetIncluded: true, ...(targetCut ? { targetTruncated: true } : {}) };
}

export const parseHtmlRecords = native.parseHtmlRecords;

const fromCps = (rec, at, n) => {
  let s = '';
  for (let k = 0; k < n; k += 4096) s += String.fromCodePoint(...rec.slice(at + k, at + Math.min(n, k + 4096)));
  return s;
};

/** Lair parseHtml (src/documents/docx.ts): the El tree { tag, attrs, children } of mammoth HTML. The
 *  verified Pruv parseHtmlRecords does the tokens, entity decoding, the open element stack and the blank
 *  top text filter; this only builds the objects. attrs holds the attributes Lair's DOCX code reads (href,
 *  colspan, rowspan). A JS string with lone surrogates reaches Pruv with U+FFFD in their place. */
export function parseHtml(html) {
  const rec = native.parseHtmlRecords(html);
  const top = [];
  const els = [];
  let p = 0;
  while (p < rec.length) {
    const [kind, parent, n] = [rec[p], rec[p + 1], rec[p + 2]];
    const into = parent === -1 ? top : els[parent].children;
    const text = fromCps(rec, p + 3, n);
    p += 3 + n;
    if (kind === 0) { into.push(text); continue; }
    const attrs = {};
    for (const name of ['href', 'colspan', 'rowspan']) {
      const m = rec[p++];
      if (m >= 0) { attrs[name] = fromCps(rec, p, m); p += m; }
    }
    const el = { tag: text, attrs, children: [] };
    els.push(el);
    into.push(el);
  }
  return top;
}

export const docxPartsRecords = native.docxPartsRecords;

const PART_KINDS = ['p', 'h', 'li', 'tr'];

/** Lair docxParts (src/documents/docx.ts): {blocks: [{n, kind, el, text}], html, images}. The verified Pruv
 *  parse_html and docx_parts do the parse, the block walk with its text collapse, the preview HTML and the
 *  image count; this builds the El tree (as parseHtml does) so each block can point at its element. */
export function docxParts(html) {
  const out = native.docxPartsRecords(html);
  const len = out[0];
  const els = [];
  const top = [];
  let p = 1;
  while (p < 1 + len) {
    const [kind, parent, n] = [out[p], out[p + 1], out[p + 2]];
    const into = parent === -1 ? top : els[parent].children;
    const text = fromCps(out, p + 3, n);
    p += 3 + n;
    if (kind === 0) { into.push(text); continue; }
    const attrs = {};
    for (const name of ['href', 'colspan', 'rowspan']) {
      const m = out[p++];
      if (m >= 0) { attrs[name] = fromCps(out, p, m); p += m; }
    }
    const el = { tag: text, attrs, children: [] };
    els.push(el);
    into.push(el);
  }
  const images = out[p++];
  const blocks = [];
  const count = out[p++];
  for (let b = 0; b < count; b++) {
    const n = out[p + 2];
    blocks.push({ n: b + 1, kind: PART_KINDS[out[p]], el: els[out[p + 1]], text: fromCps(out, p + 3, n) });
    p += 3 + n;
  }
  return { blocks, html: fromCps(out, p + 1, out[p]), images };
}

export const tokenizeRecords = native.tokenizeRecords;

/** Lair tokenize (src/documents/search.ts): the search tokens of text. The verified Pruv tokenizeRecords
 *  does the lowercase (Unicode 17.0, ICU 78.2), the letter/number words, the CJK runs and their pairs; this
 *  only builds the strings. A JS string with lone surrogates reaches Pruv with U+FFFD in their place. */
export function tokenize(text) {
  const out = native.tokenizeRecords(text);
  const tokens = [];
  let p = 1;
  for (let t = 0; t < out[0]; t++) {
    tokens.push(fromCps(out, p + 1, out[p]));
    p += 1 + out[p];
  }
  return tokens;
}
