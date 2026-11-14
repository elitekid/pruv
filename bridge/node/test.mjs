// Usage: node bridge/node/test.mjs [--cases N] [--seed S]
import { crc32 } from 'node:zlib';
import { clipBytes, hostWithin, versionAtLeast, colLetters, termPlain, termState, decodeBytes, looksBinary, zipUncompressedTotal, pngScanlines, encodePng, splitText, groupTexts, chunkLines, chunkBlocks, jpegOrientation, shrinkPixels, shrinkJpeg, numberRanges, clipSheetBackground, clipSheetCell, renderClipSheet, kindOf, extensionOf, kindCode, extensionAt, rowPieces, rowTextPieces, sheetChunks, cellRange, extractSheetChunks, textAroundPlan, textAround, parseHtmlRecords, parseHtml, docxPartsRecords, docxParts, tokenizeRecords, tokenize, csvName, countList, joinRangeParts, cutCell, sheetRange, pageRanges, groupedNumber, under, capKeep, evictStop, indexTerms, notePairs, cellDate, cellStr, cellInt, sha256Hex, extractVersionOf, chunkPage, chunkImage, imageCountText, imageCounts, textLineCounts, textLines, luhn, chatRefText } from './index.mjs';
import { csvName as tsCsvName, countList as tsCountList } from '../../bench/l0/doc_labels.mjs';
import { joinRangeParts as tsJoinRangeParts } from '../../bench/l0/join_ranges.mjs';
import { cutCell as tsCutCell } from '../../bench/l0/cut_cell.mjs';
import { sha256 as tsSha256, extractVersionOf as tsExtractVersionOf } from '../../bench/l0/extract_version.mjs';
import { chunkPage as tsChunkPage, chunkImage as tsChunkImage } from '../../bench/l0/chunk_page.mjs';
import { listOf as tsListOf } from '../../bench/l0/image_counts.mjs';
import { textDraft as tsTextDraft } from '../../bench/l0/text_lines.mjs';
import { luhn as tsLuhn } from '../../bench/l0/luhn.mjs';
import { chatRefText as tsChatRefText } from '../../bench/l0/chat_ref.mjs';
import { sheetRange as tsSheetRange } from '../../bench/l0/sheet_range.mjs';
import { rangeText as tsRangeText } from '../../bench/l0/page_ranges.mjs';
import { groupedNumber as tsGroupedNumber } from '../../bench/l0/grouped_number.mjs';
import { under as tsUnder } from '../../bench/l0/under_root.mjs';
import { capChars as tsCapChars } from '../../bench/l0/cap_keep.mjs';
import { evictFolder as tsEvictFolder } from '../../bench/l0/evict_stop.mjs';
import { buildIndex as tsBuildIndex } from '../../bench/l0/index_terms.mjs';
import { runCalls as tsRunCalls } from '../../bench/l0/note_pairs.mjs';
import { cellText as tsCellText } from '../../bench/l0/cell_date.mjs';
import { sep as pathSep } from 'node:path';
import { tokenize as tsTokenize } from '../../bench/l0/tokenize.mjs';
import { docxParts as tsDocxParts } from '../../bench/l0/docx_parts.mjs';
import { parseHtml as tsParseHtml } from '../../bench/l0/parse_html.mjs';
import { textAround as tsTextAround } from '../../bench/l0/text_around.mjs';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { extractSheets as tsExtractSheets } from '../../bench/l0/sheet_chunks.mjs';
import { rowPieces as tsRowPieces } from '../../bench/l0/row_pieces.mjs';
import { kindOf as tsKindOf, extensionOf as tsExtensionOf } from '../../bench/l0/kind_of.mjs';
import { renderClipSheet as tsRenderClipSheet } from '../../bench/l0/clip_sheet.mjs';
import { numberRanges as tsNumberRanges } from '../../bench/l0/number_ranges.mjs';
import { shrinkDecoded as tsShrinkDecoded, readOrientation as tsReadOrientation } from '../../bench/l0/image_shrink.mjs';
import { chunkLines as tsChunkLines, chunkBlocks as tsChunkBlocks } from '../../bench/l0/group_text.mjs';
import { splitText as tsSplitText } from '../../bench/l0/split_text.mjs';
import { encodePng as tsEncodePng } from '../../bench/l0/encode_png.mjs';
import { versionAtLeast as tsVersionAtLeast } from '../../bench/l0/version_at_least.mjs';
import { colLetters as tsColLetters } from '../../bench/l0/col_letters.mjs';
import { plainFromAnsi, applyCrLf, fromState, toState } from '../../bench/l0/term_plain.mjs';
import { decodeBytes as tsDecodeBytes, looksBinary as tsLooksBinary } from '../../bench/l0/decode_bytes.mjs';
import { zipUncompressedTotal as tsZipTotal } from '../../bench/l0/zip_total.mjs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

function arg(name, def) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? Number(process.argv[i + 1]) : def;
}
const CASES = arg('--cases', 20000);
const SEED = arg('--seed', 12345);

function mulberry32(a) {
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const rnd = mulberry32(SEED);
const ri = (n) => Math.floor(rnd() * n); // 0..n-1
const pick = (arr) => arr[ri(arr.length)];

// Verbatim from bench/l0/clip_bytes.mjs (Lair src/backend/engine-import/tail.ts:142).
function tsClipBytes(text, max) {
  if (Buffer.byteLength(text) <= max) return text;
  return Buffer.from(text, 'utf8').subarray(0, max).toString('utf8').replace(/�+$/, '');
}
// Verbatim from bench/l0/host_within.mjs (Lair src/shared/web-sources.ts).
function tsHostWithin(host, sites) {
  const h = host.toLowerCase();
  return sites.some(site => h === site || h.endsWith(`.${site}`));
}

const hex = (s) => Buffer.from(s, 'utf8').toString('hex');

// ---- a) clipBytes ----
const CLIP_CHARS = ['a', 'b', 'Z', '0', ' ', '\n', 'é', 'ß', 'ж', '€', '漢', '한', '😀', '𐍈', '�'];
function randClipString() {
  const n = ri(41);
  let s = '';
  for (let i = 0; i < n; i++) {
    if (rnd() < 0.25) s += '�'.repeat(1 + ri(4));
    else s += pick(CLIP_CHARS);
  }
  return s;
}
function clipOracle(text, max) {
  const b = Buffer.from(text, 'utf8');
  let k = Math.min(max, b.length);
  while (k > 0 && k < b.length && b[k] >= 0x80 && b[k] <= 0xbf) k--;
  return b.subarray(0, k).toString('hex');
}

let clipMismatches = 0;
let clipTsDiff = 0;
for (let i = 0; i < CASES; i++) {
  const text = randClipString();
  const max = ri(Buffer.byteLength(text) + 4);
  const got = hex(clipBytes(text, max));
  if (got !== clipOracle(text, max)) {
    clipMismatches++;
    if (clipMismatches <= 5) console.error('clip mismatch', JSON.stringify({ hex: hex(text), max, got }));
  }
  if (hex(tsClipBytes(text, max)) !== got) clipTsDiff++;
}

// ---- b) hostWithin ----
const HOST_CHARS = ['a', 'b', 'c', 'x', 'z', 'A', 'B', 'Z', 'K', '0', '1', '9', '-', 'K', 'İ', 'é', '漢'];
// 'k' and 'i' let U+212A KELVIN SIGN and U+0130 in hosts reach the TS toLowerCase difference.
const SITE_CHARS = ['a', 'b', 'c', 'i', 'k', 'x', 'z', '0', '1', '-'];
function label(chars) {
  const n = 1 + ri(6);
  let s = '';
  for (let i = 0; i < n; i++) s += pick(chars);
  return s;
}
function labels(chars, maxLabels) {
  const n = 1 + ri(maxLabels);
  const out = [];
  for (let i = 0; i < n; i++) out.push(label(chars));
  return out.join('.');
}
function randCase(s) {
  let o = '';
  for (const ch of s) o += rnd() < 0.5 ? ch.toUpperCase() : ch.toLowerCase();
  return o;
}
function asciiLower(s) {
  return s.replace(/[A-Z]/g, (c) => String.fromCharCode(c.charCodeAt(0) + 32));
}
function hostOracle(host, site) {
  const h = asciiLower(host);
  return Buffer.from(h, 'utf8').equals(Buffer.from(site, 'utf8')) ||
    Buffer.from(h, 'utf8').toString('hex').endsWith(Buffer.from('.' + site, 'utf8').toString('hex'));
}

let hostMismatches = 0;
let hostTsDiff = 0;
for (let i = 0; i < CASES; i++) {
  const site = labels(SITE_CHARS, 3);
  let host;
  const r = rnd();
  if (r < 0.25) host = randCase(site);
  else if (r < 0.55) host = randCase(labels(HOST_CHARS, 3) + '.' + site);
  else if (r < 0.65) host = randCase(label(HOST_CHARS) + site);
  // The site written with U+212A KELVIN SIGN for some 'k': TS lowercases it to 'k', Pruv does not.
  else if (r < 0.7) host = labels(HOST_CHARS, 2) + '.' + site.replace(/k/g, () => (rnd() < 0.5 ? 'K' : 'k'));
  else host = labels(HOST_CHARS, 4);
  const got = hostWithin(host, site);
  if (got !== hostOracle(host, site)) {
    hostMismatches++;
    if (hostMismatches <= 5) console.error('host mismatch', JSON.stringify({ host, site, got }));
  }
  if (tsHostWithin(host, [site]) !== got) hostTsDiff++;
}

// Exact BigInt oracle with ASCII-only trimming.
function versionOracle(a, b) {
  const parts = [a, b].map(s => s.replace(/^[\x09-\x0d ]+|[\x09-\x0d ]+$/g, ''));
  if (!parts.every(s => /^[0-9]+\.[0-9]+\.[0-9]+$/.test(s))) return false;
  const [left, right] = parts.map(s => s.split('.').map(BigInt));
  for (let i = 0; i < 3; i++) {
    if (left[i] !== right[i]) return left[i] > right[i];
  }
  return true;
}
function colOracle(col) {
  let n = BigInt(col), block = 1n, width = 0;
  while (n >= block) { n -= block; block *= 26n; width++; }
  let out = '';
  for (let i = width - 1; i >= 0; i--) out += String.fromCharCode(65 + Number(n / 26n**BigInt(i) % 26n));
  return out;
}
const versionEdges = ['', '0.0.0', '1.2.3', '0001.02.003', '1..2', '.1.2', '1.2.',
  '1.2.3.4', '+1.2.3', '-1.2.3', '١.2.3', '１.2.3', '9'.repeat(4092)+'.0.0',
  '0'.repeat(4092)+'.0.0', '9007199254740992.0.0', '9007199254740993.0.0',
  '\t\n\v\f\r 0.0.0 \r', '\u00a00.0.0', '\ufeff0.0.0', '\u20280.0.0', '\u30000.0.0'];
const versionInputs = versionEdges.flatMap(a => versionEdges.map(b => [a, b]));
for (let i = 0; i < CASES; i++) {
  const x = 9007199254740992n + BigInt(ri(40)-20);
  const a = pick([`${x}.0.0`, `000${ri(100)}.${ri(100)}.${ri(100)}`, pick(versionEdges),
    Array.from({length: ri(20)}, () => pick(['x', '.', '1', ' ', '😀'])).join('')]);
  versionInputs.push([pick(['', '', '\u00a0', '\ufeff', ' \t'])+a, pick([a, `${x+1n}.0.0`, pick(versionEdges)])]);
}
// Keep generated inputs within the byte precondition after adding whitespace.
const validVersions = versionInputs.filter(pair => pair.every(s => Buffer.byteLength(s) <= 4096));
let versionMismatches = 0, versionTsDiff = 0;
for (const [a,b] of validVersions) {
  const want = versionOracle(a,b);
  versionMismatches += versionAtLeast(a,b) !== want;
  versionTsDiff += tsVersionAtLeast(a,b) !== want;
}
const colInputs = Array.from({length: 100001}, (_,i) => i);
for (let k = 1; 26**k <= 1e15; k++) {
  for (let d = -3; d <= 3; d++) colInputs.push(26**k+d);
}
colInputs.push(1e15-1, 1e15);
for (let i = 0; i < CASES; i++) colInputs.push(ri(1e15+1));
let colMismatches = 0, colTsDiff = 0;
for (const col of colInputs) {
  const want = colOracle(col);
  colMismatches += colLetters(col) !== want;
  colTsDiff += tsColLetters(col) !== want;
}

// ---- termPlain / termState ----
// Whole-text oracle on the UTF-8 round trip (lone surrogates become U+FFFD, as in Node-API):
// a mode machine over code points, then a regex CR/LF fold.
const MODES = ['text', 'esc', 'escint', 'csi', 'str', 'strend'];
function termOracle(state, chunks) {
  const text = Buffer.from(chunks.join(''), 'utf8').toString('utf8');
  let mode = MODES[state % 6];
  let raw = '';
  const cps = Array.from(text);
  for (let i = 0; i < cps.length; ) {
    const ch = cps[i], o = ch.codePointAt(0);
    if (mode === 'strend') {
      mode = ch === '\\' ? 'text' : 'str';
      if (mode === 'text') { i++; continue; }
    }
    if (mode === 'esc' || mode === 'escint') {
      if (o >= 0x20 && o <= 0x2f) mode = 'escint';
      else if (mode === 'esc' && ch === '[') mode = 'csi';
      else if (mode === 'esc' && ']PX^_'.includes(ch)) mode = 'str';
      else { mode = 'text'; if (!(o >= 0x30 && o <= 0x7e)) continue; }
      i++;
      continue;
    }
    if (mode === 'csi') { if (o >= 0x40 && o <= 0x7e) mode = 'text'; }
    else if (mode === 'str') { if (o === 0x07 || o === 0x9c) mode = 'text'; else if (o === 0x1b) mode = 'strend'; }
    else if (o === 0x1b) mode = 'esc';
    else if (o === 0x9b) mode = 'csi';
    else if ([0x90, 0x98, 0x9d, 0x9e, 0x9f].includes(o)) mode = 'str';
    else if (o === 9 || o === 10 || o === 13 || !(o < 0x20 || (o >= 0x7f && o <= 0x9f))) raw += ch;
    i++;
  }
  const skipOut = raw.endsWith('\r') || (raw === '' && state >= 6);
  if (state >= 6 && raw.startsWith('\n')) raw = raw.slice(1);
  return [raw.replace(/\r\n?/g, '\n'), MODES.indexOf(mode) + (skipOut ? 6 : 0)];
}
const TERM_CHARS = ['\x1b', '\x1b', '\x1b', '[', ']', 'P', 'X', '^', '_', '\\', '\x07', '\r', '\r', '\n', '\n',
  '\t', '0', '1', ';', 'm', 'A', '~', '@', ' ', '#', '(', '/', '\x7f', '\x00', '\x08',
  '\x9b', '\x9c', '\x9d', '\x90', '\x98', '\x9e', '\x9f', '\x85', '\xa0', 'é', '한', '😀', 'a', '\ud800', '\udc00'];
let termMismatches = 0, termTsDiff = 0;
for (let i = 0; i < CASES; i++) {
  const n = ri(41);
  let text = '';
  for (let k = 0; k < n; k++) text += pick(TERM_CHARS);
  const cps = Array.from(text);
  const cuts = Array.from({ length: ri(4) }, () => ri(cps.length + 1)).sort((a, b) => a - b);
  const bounds = [0, ...cuts, cps.length];
  const chunks = bounds.slice(1).map((b, k) => cps.slice(bounds[k], b).join(''));
  const state = ri(12);
  let st = state, out = '';
  for (const c of chunks) { out += termPlain(st, c); st = termState(st, c); }
  const want = termOracle(state, chunks);
  if (out !== want[0] || st !== want[1]) {
    termMismatches++;
    if (termMismatches <= 5) console.error('term mismatch', JSON.stringify({ state, chunks, got: [out, st], want }));
  }
  let { state: s, skipLf } = fromState(state), tsOut = '';
  for (const c of chunks) { const r = applyCrLf(skipLf, plainFromAnsi(s, c)); tsOut += r.text; skipLf = r.skipLf; }
  if (tsOut !== out || toState(s, skipLf) !== st) termTsDiff++;
}

// ---- c) error path ----
let errorOk = true;
function mustThrow(name, fn) {
  try {
    fn();
  } catch (e) {
    if (e instanceof Error) return;
  }
  console.error(`expected Error from ${name}`);
  errorOk = false;
}
mustThrow("clipBytes('a', -1)", () => clipBytes('a', -1));
mustThrow("clipBytes('a', 1000001)", () => clipBytes('a', 1000001));
mustThrow("hostWithin('x'.repeat(4097), 'a')", () => hostWithin('x'.repeat(4097), 'a'));
function mustInvalidArg(name, fn) {
  try { fn(); } catch (e) {
    if (e instanceof Error && e.code === 'InvalidArg') return;
  }
  console.error(`expected InvalidArg from ${name}`);
  errorOk = false;
}
for (const col of [-1, 0.5, 1e15+1, NaN, Infinity, -Infinity]) {
  mustInvalidArg(`colLetters(${String(col)})`, () => colLetters(col));
}
mustInvalidArg('versionAtLeast long a', () => versionAtLeast('x'.repeat(4097), '0.0.0'));
mustInvalidArg('versionAtLeast long b', () => versionAtLeast('0.0.0', 'é'.repeat(2049)));
for (const col of ['1', null, undefined]) mustThrow('colLetters non-number', () => colLetters(col));
mustThrow('versionAtLeast non-string', () => versionAtLeast(1, '0.0.0'));
for (const st of [-1, 12, 0.5, NaN, Infinity]) {
  mustInvalidArg(`termPlain(${String(st)})`, () => termPlain(st, 'a'));
  mustInvalidArg(`termState(${String(st)})`, () => termState(st, 'a'));
}
mustThrow('termPlain non-string', () => termPlain(0, 1));
if (clipBytes('', 0) !== '') {
  console.error("clipBytes('', 0) !== ''");
  errorOk = false;
}

// ---- decodeBytes / looksBinary against the independent WHATWG oracle (bench/l0/decode_oracle.py) ----
// TS differences are informational: plain Node's TextDecoder('euc-kr') is not WHATWG on every build.
const oracleScript = fileURLToPath(new URL('../../bench/l0/decode_oracle.py', import.meta.url));
const decodeRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [oracleScript, '--cases', String(CASES), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let decodeMismatches = 0, decodeTsDiff = 0;
for (const [h, want] of decodeRows) {
  const buf = Uint8Array.from(Buffer.from(h, 'hex'));
  const r = decodeBytes(buf);
  const got = [r.text, r.encoding, looksBinary(buf)];
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    decodeMismatches++;
    if (decodeMismatches <= 5) console.error('decode mismatch', JSON.stringify({ hex: h, got, want }));
  }
  const t = tsDecodeBytes(buf);
  if (JSON.stringify([t.text, t.encoding, tsLooksBinary(buf)]) !== JSON.stringify(got)) decodeTsDiff++;
}
mustThrow('decodeBytes string', () => decodeBytes('abc'));
mustThrow('looksBinary number', () => looksBinary(1));
{
  const r = decodeBytes(Buffer.from([0xef, 0xbb, 0xbf, 0x61]));
  if (r.text !== 'a' || r.encoding !== 'utf-8') { console.error('decodeBytes Buffer input failed'); errorOk = false; }
}

// ---- zipUncompressedTotal against the struct/rfind oracle (bench/l0/run_zip_total.py --emit) ----
const zipScript = fileURLToPath(new URL('../../bench/l0/run_zip_total.py', import.meta.url));
const zipRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [zipScript, '--emit', '--n', String(CASES), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let zipMismatches = 0, zipTsDiff = 0;
const zipShow = (r) => (r === Infinity ? 'Infinity' : r);
for (const [h, want] of zipRows) {
  const buf = Buffer.from(h, 'hex');
  const got = zipShow(zipUncompressedTotal(Uint8Array.from(buf)));
  if (got !== want) {
    zipMismatches++;
    if (zipMismatches <= 5) console.error('zip mismatch', JSON.stringify({ hex: h.slice(0, 200), got, want }));
  }
  if (zipShow(tsZipTotal(buf)) !== got) zipTsDiff++;
}
mustThrow('zipUncompressedTotal string', () => zipUncompressedTotal('PK'));

// ---- encodePng against the exact-integer oracle (bench/l0/run_encode_png.py --emit) ----
// Scanlines must equal the oracle; the whole PNG must be byte-identical to the verbatim TS encodePng.
const pngScript = fileURLToPath(new URL('../../bench/l0/run_encode_png.py', import.meta.url));
const pngRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [pngScript, '--emit', '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let pngMismatches = 0, pngTsDiff = 0;
for (const [w, h, kind, hex, max, want] of pngRows) {
  const data = Uint8Array.from(Buffer.from(hex, 'hex'));
  const s = pngScanlines(data, w, h, kind, max);
  const got = s === null ? null : [s.width, s.height, kind === 1 ? 0 : 2, s.raw.toString('hex')];
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    pngMismatches++;
    if (pngMismatches <= 5) console.error('png mismatch', JSON.stringify({ w, h, kind, max, got: got && got.slice(0, 3), want: want && want.slice(0, 3) }));
  }
  const mine = encodePng({ width: w, height: h, kind, data }, max);
  const ts = tsEncodePng({ width: w, height: h, kind, data }, max);
  if ((mine === null) !== (ts === null) || (mine !== null && !mine.equals(ts))) pngTsDiff++;
}
const px = new Uint8Array(12);
mustThrow('pngScanlines width 0', () => pngScanlines(px, 0, 1, 2, 10));
mustThrow('pngScanlines fractional height', () => pngScanlines(px, 1, 1.5, 2, 10));
mustThrow('pngScanlines kind 4', () => pngScanlines(px, 1, 1, 4, 10));
mustThrow('pngScanlines maxPixels 0', () => pngScanlines(px, 1, 1, 2, 0));
mustThrow('pngScanlines maxPixels 2^36+1', () => pngScanlines(px, 1, 1, 2, 2 ** 36 + 1));
mustThrow('pngScanlines area 2^40+1', () => pngScanlines(px, 2 ** 20 + 1, 2 ** 20, 2, 10));
mustThrow('pngScanlines data string', () => pngScanlines('abc', 1, 1, 2, 10));
if (encodePng({ width: 0, height: 4, kind: 2, data: px }, 10) !== null || encodePng({ width: 2, height: 2, kind: 5, data: px }, 10) !== null) {
  console.error('encodePng null shapes failed'); errorOk = false;
}

// ---- splitText against the code-point oracle (bench/l0/run_split_text.py --emit) ----
const splitScript = fileURLToPath(new URL('../../bench/l0/run_split_text.py', import.meta.url));
const splitRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [splitScript, '--emit', '--n', String(CASES), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let splitMismatches = 0, splitTsDiff = 0;
for (const [text, max, want] of splitRows) {
  const got = JSON.stringify(splitText(text, max));
  if (got !== JSON.stringify(want)) {
    splitMismatches++;
    if (splitMismatches <= 5) console.error('split mismatch', JSON.stringify({ text: text.slice(0, 200), max, got: got.slice(0, 300) }));
  }
  if (JSON.stringify(tsSplitText(text, max)) !== got) splitTsDiff++;
}
mustThrow('splitText max 1', () => splitText('ab', 1));
mustThrow('splitText max 0', () => splitText('ab', 0));
mustThrow('splitText max 2.5', () => splitText('ab', 2.5));
mustThrow('splitText max 2^40+1', () => splitText('ab', 2 ** 40 + 1));
mustThrow('splitText max NaN', () => splitText('ab', NaN));
mustThrow('splitText text number', () => splitText(5, 10));

// ---- chunkLines / chunkBlocks against the grouping oracle (bench/l0/run_group_text.py --emit) ----
const groupScript = fileURLToPath(new URL('../../bench/l0/run_group_text.py', import.meta.url));
const groupRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [groupScript, '--emit', '--n', String(CASES), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let groupMismatches = 0, groupTsDiff = 0;
for (const [lines, max, want] of groupRows) {
  const got = JSON.stringify(chunkLines(lines, max).map(c => [c.loc.from, c.loc.to, c.text]));
  if (got !== JSON.stringify(want)) {
    groupMismatches++;
    if (groupMismatches <= 5) console.error('group mismatch', JSON.stringify({ lines: lines.slice(0, 5), max, got: got.slice(0, 300) }));
  }
  if (JSON.stringify(tsChunkLines(lines, max)) !== JSON.stringify(chunkLines(lines, max))) groupTsDiff++;
  // chunkBlocks with sparse block numbers must match the TS original too.
  const blocks = lines.map((text, i) => ({ n: 3 * i + 7, text }));
  if (JSON.stringify(tsChunkBlocks(blocks, max)) !== JSON.stringify(chunkBlocks(blocks, max))) groupTsDiff++;
}
mustThrow('groupTexts max 1', () => groupTexts(['ab'], 1));
mustThrow('groupTexts max 2.5', () => groupTexts(['ab'], 2.5));
mustThrow('groupTexts max 2^40+1', () => groupTexts(['ab'], 2 ** 40 + 1));
mustThrow('groupTexts texts string', () => groupTexts('ab', 10));
mustThrow('groupTexts texts numbers', () => groupTexts([1, 2], 10));

// ---- jpegOrientation / shrinkPixels against the struct/Fraction oracle (bench/l0/run_image_shrink.py --emit) ----
const shrinkScript = fileURLToPath(new URL('../../bench/l0/run_image_shrink.py', import.meta.url));
const shrinkRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [shrinkScript, '--emit', '--n', String(Math.min(CASES, 6000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let shrinkMismatches = 0, shrinkTsDiff = 0;
// Stub jpeg-js: decode hands back fixed pixels, encode echoes its input, so shrinkJpeg's glue is compared too.
const stubJpeg = (decoded) => ({
  decode: () => decoded,
  encode: (img, q) => ({ data: Buffer.from(JSON.stringify([img.width, img.height, q, Buffer.from(img.data).toString('hex')])) }),
});
for (const row of shrinkRows) {
  let got, ts;
  if (row[0] === 'o') {
    const buf = Uint8Array.from(Buffer.from(row[1], 'hex'));
    got = jpegOrientation(buf);
    ts = tsReadOrientation(buf);
  } else {
    const [, w, h, o, hx] = row;
    const data = Uint8Array.from(Buffer.from(hx, 'hex'));
    const s = shrinkPixels(data, w, h, o);
    got = s === null ? null : [s.width, s.height, s.data.toString('hex')];
    const t = tsShrinkDecoded({ width: w, height: h, data }, o);
    ts = t === undefined ? null : [t.width, t.height, Buffer.from(t.data).toString('hex')];
  }
  const want = row[row.length - 1];
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    shrinkMismatches++;
    if (shrinkMismatches <= 5) console.error('shrink mismatch', JSON.stringify({ row: row.slice(0, 4), got: JSON.stringify(got).slice(0, 200) }));
  }
  if (JSON.stringify(ts) !== JSON.stringify(got)) shrinkTsDiff++;
}
{
  // shrinkJpeg glue: a JPEG head with EXIF orientation 6 around a 3x2 image, and the undefined paths.
  const tiff = Buffer.from('4d4d002a000000080001011200030000000100060000', 'hex');
  const app1 = Buffer.concat([Buffer.from([0xff, 0xe1, 0, tiff.length + 8]), Buffer.from('Exif\0\0', 'latin1'), tiff]);
  const jpg = Uint8Array.from(Buffer.concat([Buffer.from([0xff, 0xd8]), app1, Buffer.from([0xff, 0xda])]));
  const data = Uint8Array.from({ length: 24 }, (_, i) => (i * 37) % 256);
  const t = tsShrinkDecoded({ width: 3, height: 2, data }, tsReadOrientation(jpg));
  const want = JSON.stringify([t.width, t.height, 85, Buffer.from(t.data).toString('hex')]);
  const mine = shrinkJpeg(jpg, stubJpeg({ width: 3, height: 2, data }));
  if (tsReadOrientation(jpg) !== 6 || !mine || mine.toString() !== want) { console.error('shrinkJpeg glue failed'); errorOk = false; }
  const plain = Uint8Array.from([0xff, 0xd8, 0xff, 0xda]);
  const throwing = { decode: () => { throw new Error('bad'); }, encode: () => { throw new Error('unreachable'); } };
  if (shrinkJpeg(plain, stubJpeg({ width: 3, height: 2, data })) !== undefined
    || shrinkJpeg(plain, throwing) !== undefined
    || shrinkJpeg(Uint8Array.from([0x89, 0x50, 0x4e, 0x47]), throwing) !== undefined
    || shrinkJpeg(jpg, stubJpeg({ width: 0, height: 2, data })) !== undefined) {
    console.error('shrinkJpeg undefined paths failed'); errorOk = false;
  }
}
const one = new Uint8Array(4);
mustInvalidArg('shrinkPixels width 0', () => shrinkPixels(one, 0, 1, 1));
mustInvalidArg('shrinkPixels width 65536', () => shrinkPixels(new Uint8Array(4 * 65536), 65536, 1, 2));
mustInvalidArg('shrinkPixels height 1.5', () => shrinkPixels(one, 1, 1.5, 1));
mustInvalidArg('shrinkPixels orientation 0', () => shrinkPixels(one, 1, 1, 0));
mustInvalidArg('shrinkPixels orientation 9', () => shrinkPixels(one, 1, 1, 9));
mustInvalidArg('shrinkPixels orientation NaN', () => shrinkPixels(one, 1, 1, NaN));
mustInvalidArg('shrinkPixels short data', () => shrinkPixels(new Uint8Array(3), 1, 1, 2));
mustInvalidArg('shrinkPixels long data', () => shrinkPixels(new Uint8Array(5), 1, 1, 2));
mustThrow('shrinkPixels data string', () => shrinkPixels('abcd', 1, 1, 2));
mustThrow('jpegOrientation string', () => jpegOrientation('abc'));

// ---- numberRanges against the groupby oracle (bench/l0/run_number_ranges.py --emit) ----
const rangesScript = fileURLToPath(new URL('../../bench/l0/run_number_ranges.py', import.meta.url));
const rangesRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [rangesScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let rangesMismatches = 0, rangesTsDiff = 0;
for (const [nums, want] of rangesRows) {
  const got = numberRanges(nums);
  if (got !== want) {
    rangesMismatches++;
    if (rangesMismatches <= 5) console.error('ranges mismatch', JSON.stringify({ nums: nums.slice(0, 10), got, want }));
  }
  if (tsNumberRanges(nums) !== got) rangesTsDiff++;
}
mustInvalidArg('numberRanges 1.5', () => numberRanges([1.5]));
mustInvalidArg('numberRanges NaN', () => numberRanges([1, NaN]));
mustInvalidArg('numberRanges 1e15+1', () => numberRanges([1e15 + 1]));
mustInvalidArg('numberRanges -Infinity', () => numberRanges([-Infinity]));
mustThrow('numberRanges string', () => numberRanges('12'));

// ---- csvName and countList against the Python oracle (bench/l0/run_doc_labels.py --emit) ----
const labelsScript = fileURLToPath(new URL('../../bench/l0/run_doc_labels.py', import.meta.url));
const labelsRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [labelsScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let labelsMismatches = 0, labelsTsDiff = 0;
for (const row of labelsRows) {
  // ["csvName", name, want] or ["countList", items, max, want]
  const isName = row[0] === 'csvName';
  const got = isName ? csvName(row[1]) : countList(row[1], row[2]);
  const want = isName ? row[2] : row[3];
  const ts = isName ? tsCsvName(row[1]) : tsCountList(row[1], row[2]);
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    labelsMismatches++;
    if (labelsMismatches <= 5) console.error('labels mismatch', JSON.stringify({ row: row.slice(0, 3).map(x => (Array.isArray(x) ? x.slice(0, 5) : x)), got, want }));
  }
  if (JSON.stringify(ts) !== JSON.stringify(got)) labelsTsDiff++;
}
mustInvalidArg('countList page 1.5', () => countList([{ page: 1.5, count: 1 }]));
mustInvalidArg('countList count NaN', () => countList([{ page: 1, count: NaN }]));
mustInvalidArg('countList page 1e15+1', () => countList([{ page: 1e15 + 1, count: 1 }]));
mustInvalidArg('countList max -1', () => countList([{ page: 1, count: 1 }], -1));
mustInvalidArg('countList max 1.5', () => countList([{ page: 1, count: 1 }], 1.5));
mustInvalidArg('countList max 1e9+1', () => countList([], 1e9 + 1));
mustThrow('csvName number', () => csvName(12));

// ---- joinRangeParts against the UTF-16 oracle (bench/l0/run_join_ranges.py --emit) ----
const joinScript = fileURLToPath(new URL('../../bench/l0/run_join_ranges.py', import.meta.url));
const joinRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [joinScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let joinMismatches = 0, joinTsDiff = 0;
for (const [parts, want] of joinRows) {
  const got = joinRangeParts(parts);
  if (got !== want) {
    joinMismatches++;
    if (joinMismatches <= 5) console.error('join mismatch', JSON.stringify({ parts: parts.slice(0, 5).map(p => p.slice(0, 60)), got: got.slice(0, 80), want: want.slice(0, 80) }));
  }
  if (tsJoinRangeParts(parts) !== got) joinTsDiff++;
}
mustThrow('joinRangeParts string', () => joinRangeParts('ab'));
mustThrow('joinRangeParts numbers', () => joinRangeParts([1, 2]));
mustThrow('joinRangeParts undefined', () => joinRangeParts());

// ---- cutCell against the UTF-16 oracle (bench/l0/run_cut_cell.py --emit) ----
// TS results are compared after UTF-8 encoding: a lone high surrogate left by the cut becomes U+FFFD.
const cutScript = fileURLToPath(new URL('../../bench/l0/run_cut_cell.py', import.meta.url));
const cutRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [cutScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let cutMismatches = 0, cutTsDiff = 0;
for (const [text, want] of cutRows) {
  const got = cutCell(text);
  if (got !== want) {
    cutMismatches++;
    if (cutMismatches <= 5) console.error('cut mismatch', JSON.stringify({ text: text.slice(0, 60), got: got.slice(0, 80), want: want.slice(0, 80) }));
  }
  if (Buffer.from(tsCutCell(text), 'utf8').toString('utf8') !== got) cutTsDiff++;
}
mustThrow('cutCell number', () => cutCell(12));
mustThrow('cutCell undefined', () => cutCell());

// ---- sheetRange against the range-intersection oracle (bench/l0/run_sheet_range.py --emit) ----
const rangeScript = fileURLToPath(new URL('../../bench/l0/run_sheet_range.py', import.meta.url));
const rangeRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [rangeScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let rangeMismatches = 0, rangeTsDiff = 0;
for (const [totalRows, totalCols, request, want] of rangeRows) {
  const got = sheetRange(totalRows, totalCols, request);
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    rangeMismatches++;
    if (rangeMismatches <= 5) console.error('range mismatch', JSON.stringify({ totalRows, totalCols, request, got, want }));
  }
  if (JSON.stringify(tsSheetRange(totalRows, totalCols, request)) !== JSON.stringify(got)) rangeTsDiff++;
}
mustInvalidArg('sheetRange row 1.5', () => sheetRange(10, 10, { row: 1.5 }));
mustInvalidArg('sheetRange rows NaN', () => sheetRange(10, 10, { rows: NaN }));
mustInvalidArg('sheetRange cols 2^53', () => sheetRange(10, 10, { cols: 2 ** 53 }));
mustInvalidArg('sheetRange totalRows -1', () => sheetRange(-1, 10));
mustInvalidArg('sheetRange totalCols 1e12+1', () => sheetRange(10, 1e12 + 1));
mustThrow('sheetRange row string', () => sheetRange(10, 10, { row: '3' }));

// ---- pageRanges against the run-start oracle (bench/l0/run_page_ranges.py --emit) ----
const pageScript = fileURLToPath(new URL('../../bench/l0/run_page_ranges.py', import.meta.url));
const pageRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [pageScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let pageMismatches = 0, pageTsDiff = 0;
for (const [pages, want] of pageRows) {
  const got = pageRanges(pages);
  if (got !== want) {
    pageMismatches++;
    if (pageMismatches <= 5) console.error('page mismatch', JSON.stringify({ pages: pages.slice(0, 10), got, want }));
  }
  if (tsRangeText(pages) !== got) pageTsDiff++;
}
mustInvalidArg('pageRanges 1.5', () => pageRanges([1.5]));
mustInvalidArg('pageRanges NaN', () => pageRanges([1, NaN]));
mustInvalidArg('pageRanges 1e15+1', () => pageRanges([1e15 + 1]));
mustInvalidArg('pageRanges Infinity', () => pageRanges([Infinity]));
mustThrow('pageRanges string', () => pageRanges('12'));

// ---- groupedNumber against Python's format(n, ',') (bench/l0/run_grouped_number.py --emit) ----
const groupedScript = fileURLToPath(new URL('../../bench/l0/run_grouped_number.py', import.meta.url));
const groupedRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [groupedScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let groupedMismatches = 0, groupedTsDiff = 0;
for (const [value, want] of groupedRows) {
  const got = groupedNumber(value);
  if (got !== want) {
    groupedMismatches++;
    if (groupedMismatches <= 5) console.error('grouped mismatch', JSON.stringify({ value, got, want }));
  }
  if (tsGroupedNumber(value) !== got) groupedTsDiff++;
}
mustInvalidArg('groupedNumber 1.5', () => groupedNumber(1.5));
mustInvalidArg('groupedNumber NaN', () => groupedNumber(NaN));
mustInvalidArg('groupedNumber 1e15+1', () => groupedNumber(1e15 + 1));
mustInvalidArg('groupedNumber -Infinity', () => groupedNumber(-Infinity));
mustInvalidArg('groupedNumber -0', () => groupedNumber(-0));
mustThrow('groupedNumber string', () => groupedNumber('12'));

// ---- under against the code point regex oracle (bench/l0/run_under_root.py --emit) ----
// Rows carry the oracle for "/" and for "\\"; this platform's node:path sep picks one.
const underScript = fileURLToPath(new URL('../../bench/l0/run_under_root.py', import.meta.url));
const underRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [underScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let underMismatches = 0, underTsDiff = 0;
for (const [path, root, wantSlash, wantBackslash] of underRows) {
  const got = under(path, root);
  const want = pathSep === '/' ? wantSlash : wantBackslash;
  if (got !== want) {
    underMismatches++;
    if (underMismatches <= 5) console.error('under mismatch', JSON.stringify({ path, root, got, want }));
  }
  if (tsUnder(path, root) !== got) underTsDiff++;
}
mustThrow('under number', () => under(1, '/'));

// ---- capKeep against the prefix-total oracle (bench/l0/run_cap_keep.py --emit) ----
// The verbatim TS capChars builds real strings, so it runs only on rows the oracle marks (total <= 10^6).
const capScript = fileURLToPath(new URL('../../bench/l0/run_cap_keep.py', import.meta.url));
const capRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [capScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let capMismatches = 0, capTsDiff = 0, capTsCases = 0;
for (const [lens, max, want, tsRuns] of capRows) {
  const got = capKeep(lens, max);
  if (got !== want) {
    capMismatches++;
    if (capMismatches <= 5) console.error('capKeep mismatch', JSON.stringify({ lens: lens.slice(0, 20), max, got, want }));
  }
  if (tsRuns) {
    capTsCases++;
    const draft = { chunks: lens.map(n => ({ loc: { kind: 'image' }, text: 'x'.repeat(n) })), missing: [], missingI18n: [] };
    tsCapChars(draft, max);
    if (draft.chunks.length !== got) capTsDiff++;
  }
}
mustThrow('capKeep negative length', () => capKeep([1, -1], 5));
mustThrow('capKeep length over 1e9', () => capKeep([1e9 + 1], 5));
mustThrow('capKeep fractional max', () => capKeep([1], 0.5));
mustThrow('capKeep max over 1e15', () => capKeep([1], 1e15 + 2));

// ---- evictStop against the bisect oracle (bench/l0/run_evict_stop.py --emit) ----
// The verbatim TS evict runs on rows the oracle marks (at most 2,000 entries) over an in-memory folder built
// from the row: version k has mtime k and is pinned when free[k] differs from bytes[k].
const evictScript = fileURLToPath(new URL('../../bench/l0/run_evict_stop.py', import.meta.url));
const evictRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [evictScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let evictMismatches = 0, evictTsDiff = 0, evictTsCases = 0;
const hexName = k => k.toString(16).padStart(64, '0');
for (const [bytes, free, limit, want, tsRuns] of evictRows) {
  const got = evictStop(bytes, free, limit);
  if (got !== want) {
    evictMismatches++;
    if (evictMismatches <= 5) console.error('evictStop mismatch', JSON.stringify({ bytes: bytes.slice(0, 20), free: free.slice(0, 20), limit, got, want }));
  }
  if (tsRuns) {
    evictTsCases++;
    const entries = bytes.map((b, k) => ({ name: hexName(k), mtime: k, bytes: b }));
    const pinned = entries.filter((_, k) => free[k] !== bytes[k]).map(e => e.name);
    const [, names] = await tsEvictFolder(entries, limit, pinned, '');
    const expectNames = entries.slice(0, got).filter((_, k) => free[k] === bytes[k]).map(e => e.name);
    if (JSON.stringify(names) !== JSON.stringify(expectNames)) evictTsDiff++;
  }
}
mustThrow('evictStop negative size', () => evictStop([1, -1], [1, -1], 5));
mustThrow('evictStop size over 1e9', () => evictStop([1e9 + 1], [0], 5));
mustThrow('evictStop free not 0 or size', () => evictStop([5], [3], 0));
mustThrow('evictStop length mismatch', () => evictStop([5, 6], [5], 0));
mustThrow('evictStop fractional limit', () => evictStop([1], [1], 0.5));
mustThrow('evictStop limit over 1e15', () => evictStop([1], [1], 1e15 + 2));

// ---- indexTerms against the Counter oracle (bench/l0/run_index_terms.py --emit) ----
// Each row is a corpus: the oracle's token strings by id, each chunk's ids and the oracle's per-chunk result.
// The bridge results are assembled into buildIndex's terms/lens/count/avg and compared with the verbatim TS
// buildIndex (its tokenizer follows the runtime's Unicode tables, so TS differences count only on Unicode 17.0).
const indexScript = fileURLToPath(new URL('../../bench/l0/run_index_terms.py', import.meta.url));
const indexRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [indexScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let indexMismatches = 0, indexTsDiff = 0;
const indexUnicode17 = process.versions.unicode === '17.0';
const sortKeys = o => JSON.stringify(Object.keys(o).sort().map(k => [k, o[k]]));
for (const [vocab, names, chunks, want, texts] of indexRows) {
  const terms = new Map();
  chunks.forEach((tok, i) => {
    const got = indexTerms(tok, vocab);
    if (JSON.stringify(got) !== JSON.stringify(want[i])) {
      indexMismatches++;
      if (indexMismatches <= 5) console.error('indexTerms mismatch', JSON.stringify({ tok: tok.slice(0, 20), got: got.slice(0, 21), want: want[i].slice(0, 21) }));
    }
    for (let p = 0; p < got[0]; p++) {
      const name = names[got[1 + 2 * p]];
      if (!terms.has(name)) terms.set(name, []);
      terms.get(name).push(i, got[2 + 2 * p]);
    }
  });
  const lens = chunks.map(tok => tok.length);
  const total = lens.reduce((a, b) => a + b, 0);
  const n = chunks.length;
  const ts = tsBuildIndex(texts);
  if (ts.count !== n || ts.avg !== (n ? Math.max(total / n, 1) : 1) || JSON.stringify(ts.lens) !== JSON.stringify(lens)
      || sortKeys(ts.terms) !== sortKeys(Object.fromEntries(terms))) {
    indexTsDiff++;
    if (indexTsDiff <= 5 && indexUnicode17) console.error('indexTerms ts difference', JSON.stringify({ texts: texts.map(t => t.slice(0, 80)) }));
  }
}
mustThrow('indexTerms id at vocab', () => indexTerms([0, 3], 3));
mustThrow('indexTerms negative id', () => indexTerms([-1], 3));
mustThrow('indexTerms fractional id', () => indexTerms([0.5], 3));
mustThrow('indexTerms vocab zero', () => indexTerms([], 0));
mustThrow('indexTerms vocab over 1e7', () => indexTerms([], 1e7 + 1));

// ---- notePairs against the closed-form oracle (bench/l0/run_note_pairs.py --emit) ----
// Each row is [n0, has, pre, keys, oracle result]; the same calls also run through the verbatim TS addNote /
// addMissing (alternating), whose final text list and key list must match.
const noteScript = fileURLToPath(new URL('../../bench/l0/run_note_pairs.py', import.meta.url));
const noteRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [noteScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let noteMismatches = 0, noteTsDiff = 0;
noteRows.forEach(([n0, has, pre, keys, want], i) => {
  const got = notePairs(n0, has, pre, keys);
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    noteMismatches++;
    if (noteMismatches <= 5) console.error('notePairs mismatch', JSON.stringify({ n0, has, pre: pre.slice(0, 20), keys: keys.slice(0, 20), got: got.slice(0, 21), want: want.slice(0, 21) }));
  }
  const key = k => (k ? { key: 'k' + k } : null);
  const list = Array.from({ length: n0 }, (_, k) => 't' + k);
  const ts = tsRunCalls(i % 2 ? 'addMissing' : 'addNote', list, has ? pre.map(key) : null, keys.map((k, j) => ['c' + j, key(k)]));
  const tsFlat = ts.pairs === null ? [0] : [1, ...ts.pairs.map(x => (x ? Number(x.key.slice(1)) : 0))];
  if (ts.list.length !== n0 + keys.length || JSON.stringify(tsFlat) !== JSON.stringify(got)) {
    noteTsDiff++;
    if (noteTsDiff <= 5) console.error('notePairs ts difference', JSON.stringify({ n0, has, pre: pre.slice(0, 20), keys: keys.slice(0, 20) }));
  }
});
mustThrow('notePairs n0 negative', () => notePairs(-1, 0, [], []));
mustThrow('notePairs n0 over 1e7', () => notePairs(1e7 + 1, 0, [], []));
mustThrow('notePairs has 2', () => notePairs(0, 2, [], []));
mustThrow('notePairs pre without has', () => notePairs(0, 0, [1], []));
mustThrow('notePairs fractional key', () => notePairs(0, 0, [], [0.5]));
mustThrow('notePairs key over 1e9', () => notePairs(0, 1, [1e9 + 1], []));

// ---- cellDate against the 400-year-cycle datetime oracle (bench/l0/run_cell_date.py --emit) ----
const cellDateScript = fileURLToPath(new URL('../../bench/l0/run_cell_date.py', import.meta.url));
const cellDateRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [cellDateScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let cellDateMismatches = 0, cellDateTsDiff = 0;
for (const [ms, want] of cellDateRows) {
  const got = cellDate(ms);
  if (got !== want) {
    cellDateMismatches++;
    if (cellDateMismatches <= 5) console.error('cellDate mismatch', JSON.stringify({ ms, got, want }));
  }
  if (tsCellText(new Date(ms)) !== got) cellDateTsDiff++;
}
mustInvalidArg('cellDate 0.5', () => cellDate(0.5));
mustInvalidArg('cellDate NaN', () => cellDate(NaN));
mustInvalidArg('cellDate 8.64e15+1', () => cellDate(8.64e15 + 1));
mustInvalidArg('cellDate -Infinity', () => cellDate(-Infinity));
mustThrow('cellDate string', () => cellDate('0'));

// ---- cellStr against the replace-and-strip oracle (bench/l0/run_cell_str.py --emit) ----
const cellStrScript = fileURLToPath(new URL('../../bench/l0/run_cell_str.py', import.meta.url));
const cellStrRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [cellStrScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let cellStrMismatches = 0, cellStrTsDiff = 0;
for (const [text, want] of cellStrRows) {
  const got = cellStr(text);
  if (got !== want) {
    cellStrMismatches++;
    if (cellStrMismatches <= 5) console.error('cellStr mismatch', JSON.stringify({ text: text.slice(0, 60), got: got.slice(0, 80), want: want.slice(0, 80) }));
  }
  if (tsCellText(text) !== got) cellStrTsDiff++;
}
mustThrow('cellStr number', () => cellStr(12));
mustThrow('cellStr undefined', () => cellStr());

// ---- cellInt against the decimal-module oracle (bench/l0/run_cell_int.py --emit) ----
const cellIntScript = fileURLToPath(new URL('../../bench/l0/run_cell_int.py', import.meta.url));
const cellIntRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [cellIntScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let cellIntMismatches = 0, cellIntTsDiff = 0;
for (const [n, want] of cellIntRows) {
  const got = cellInt(n);
  if (got !== want) {
    cellIntMismatches++;
    if (cellIntMismatches <= 5) console.error('cellInt mismatch', JSON.stringify({ n, got, want }));
  }
  if (tsCellText(n) !== got) cellIntTsDiff++;
}
if (cellInt(-0) !== '0' || tsCellText(-0) !== '0') cellIntMismatches++;
mustInvalidArg('cellInt 0.5', () => cellInt(0.5));
mustInvalidArg('cellInt NaN', () => cellInt(NaN));
mustInvalidArg('cellInt 2^53', () => cellInt(2 ** 53));
mustInvalidArg('cellInt -Infinity', () => cellInt(-Infinity));
mustThrow('cellInt string', () => cellInt('1'));

// ---- sha256Hex / extractVersionOf against the hashlib oracle (bench/l0/run_extract_version.py --emit) ----
const extractScript = fileURLToPath(new URL('../../bench/l0/run_extract_version.py', import.meta.url));
const extractRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [extractScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let extractMismatches = 0, extractTsDiff = 0;
for (const [c, want] of extractRows) {
  let got, ts;
  if (c[0] === 's') { got = sha256Hex(c[1]); ts = tsSha256(c[1]); }
  else if (c[3] === null) { got = extractVersionOf(c[1], c[2]); ts = tsExtractVersionOf(c[1], c[2]); }
  else { got = extractVersionOf(c[1], c[2], c[3]); ts = tsExtractVersionOf(c[1], c[2], c[3]); }
  if (got !== want) {
    extractMismatches++;
    if (extractMismatches <= 5) console.error('extractVersion mismatch', JSON.stringify({ c: c.map(p => p === null ? p : p.slice(0, 60)), got, want }));
  }
  if (ts !== got) extractTsDiff++;
}
if (sha256Hex('abc') !== 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad') extractMismatches++;
mustThrow('sha256Hex number', () => sha256Hex(1));
mustThrow('extractVersionOf missing kind', () => extractVersionOf('a'));

// ---- chunkPage / chunkImage against the oracle (bench/l0/run_chunk_page.py --emit) ----
const chunkPageScript = fileURLToPath(new URL('../../bench/l0/run_chunk_page.py', import.meta.url));
const chunkPageRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [chunkPageScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let chunkPageMismatches = 0, chunkPageTsDiff = 0;
for (const [kind, page, text, max, ocr, want] of chunkPageRows) {
  const info = ocr === null ? undefined : ocr;
  const got = JSON.stringify(kind === 'page' ? chunkPage(page, text, max, info) : chunkImage(text, max, info));
  const ts = JSON.stringify(kind === 'page' ? tsChunkPage(page, text, max, info) : tsChunkImage(text, max, info));
  if (got !== JSON.stringify(want)) {
    chunkPageMismatches++;
    if (chunkPageMismatches <= 5) console.error('chunkPage mismatch', JSON.stringify({ kind, page, text: text.slice(0, 60), max, got: got.slice(0, 200) }));
  }
  if (ts !== got) chunkPageTsDiff++;
}
mustInvalidArg('chunkPage fractional page', () => chunkPage(1.5, 'a', 10));
mustInvalidArg('chunkPage page 2^53', () => chunkPage(2 ** 53, 'a', 10));
mustInvalidArg('chunkPage max 1', () => chunkPage(1, 'a', 1));
mustInvalidArg('chunkImage max 1', () => chunkImage('a', 1));
mustThrow('chunkImage number text', () => chunkImage(1, 10));

// ---- imageCounts (pdf.ts listOf) against the oracle (bench/l0/run_image_counts.py --emit) ----
const imageCountsScript = fileURLToPath(new URL('../../bench/l0/run_image_counts.py', import.meta.url));
const imageCountsRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [imageCountsScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let imageCountsMismatches = 0, imageCountsTsDiff = 0;
for (const [items, want] of imageCountsRows) {
  const got = imageCounts(items);
  if (got !== want) {
    imageCountsMismatches++;
    if (imageCountsMismatches <= 5) console.error('imageCounts mismatch', JSON.stringify({ items: items.slice(0, 5), n: items.length, got, want }));
  }
  if (tsListOf(items) !== got) imageCountsTsDiff++;
}
mustInvalidArg('imageCounts page 1.5', () => imageCounts([{ page: 1.5, count: 1 }]));
mustInvalidArg('imageCounts count NaN', () => imageCounts([{ page: 1, count: NaN }]));
mustInvalidArg('imageCounts page 1e15+1', () => imageCounts([{ page: 1e15 + 1, count: 1 }]));
mustInvalidArg('imageCountText unequal lengths', () => imageCountText([1, 2], [1]));

// ---- textLines (extract.ts textDraft lines) against the oracle (bench/l0/run_text_lines.py --emit) ----
const textLinesScript = fileURLToPath(new URL('../../bench/l0/run_text_lines.py', import.meta.url));
const textLinesRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [textLinesScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let textLinesMismatches = 0, textLinesTsDiff = 0;
for (const [text, chars, want] of textLinesRows) {
  const got = textLines(text, chars);
  if (got.lines !== want[0] || got.keep !== want[1]) {
    textLinesMismatches++;
    if (textLinesMismatches <= 5) console.error('textLines mismatch', JSON.stringify({ text, chars, got, want }));
  }
  const draft = tsTextDraft(text, { limits: { chars, chunkChars: 1000 } });
  if (draft.lines !== got.lines || draft.chunks.length !== got.keep) textLinesTsDiff++;
}
mustInvalidArg('textLines chars 1.5', () => textLines('a', 1.5));
mustInvalidArg('textLines chars NaN', () => textLines('a', NaN));
mustInvalidArg('textLines chars 1e15+1', () => textLines('a', 1e15 + 1));
mustThrow('textLineCounts number text', () => textLineCounts(1, 10));

// ---- luhn (common-memory.ts) against the oracle (bench/l0/run_luhn.py --emit) ----
const luhnScript = fileURLToPath(new URL('../../bench/l0/run_luhn.py', import.meta.url));
const luhnRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [luhnScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let luhnMismatches = 0, luhnTsDiff = 0;
for (const [text, want] of luhnRows) {
  const got = luhn(text);
  if (got !== want) {
    luhnMismatches++;
    if (luhnMismatches <= 5) console.error('luhn mismatch', JSON.stringify({ text, got, want }));
  }
  if (tsLuhn(text) !== got) luhnTsDiff++;
}
mustThrow('luhn number text', () => luhn(4111111111111111));

// ---- chatRefText (chat-ref.ts) against the oracle (bench/l0/run_chat_ref.py --emit) ----
const chatRefScript = fileURLToPath(new URL('../../bench/l0/run_chat_ref.py', import.meta.url));
const chatRefRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [chatRefScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let chatRefMismatches = 0, chatRefTsDiff = 0;
for (const [title, id, want] of chatRefRows) {
  const got = chatRefText(title, id);
  if (got !== want) {
    chatRefMismatches++;
    if (chatRefMismatches <= 5) console.error('chatRefText mismatch', JSON.stringify({ title, id, got, want }));
  }
  if (tsChatRefText(title, id) !== got) chatRefTsDiff++;
}
mustThrow('chatRefText number title', () => chatRefText(1, 'x'));

// ---- renderClipSheet against the integral-image oracle (bench/l0/run_clip_sheet.py --emit) ----
// A stub jpeg module: decode passes the {width, height, data} cell through, encode returns the RGBA sheet.
const passJpeg = { decode: (j) => j, encode: (image) => ({ data: image.data }) };
const sheetScript = fileURLToPath(new URL('../../bench/l0/run_clip_sheet.py', import.meta.url));
const sheetRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [sheetScript, '--emit', '--n', String(Math.min(CASES, 20)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
const sheetCells = (row) => row.map(([width, height, hex, number, label]) => (
  { jpeg: { width, height, data: new Uint8Array(Buffer.from(hex, 'hex')) }, number, label }));
const crcHex = (buf) => (crc32(buf) >>> 0).toString(16).padStart(8, '0');
let sheetMismatches = 0, sheetTsDiff = 0;
for (const [row, want] of sheetRows) {
  const got = crcHex(renderClipSheet(sheetCells(row), passJpeg));
  if (got !== want) {
    sheetMismatches++;
    if (sheetMismatches <= 5) console.error('clip sheet mismatch', JSON.stringify({ sizes: row.map(c => [c[0], c[1], c[3]]), got, want }));
  }
  if (crcHex(tsRenderClipSheet(sheetCells(row))) !== got) sheetTsDiff++;
}
const blankSheet = clipSheetBackground();
const onePixel = new Uint8Array([1, 2, 3, 255]);
mustThrow('renderClipSheet 0 cells', () => renderClipSheet([], passJpeg));
mustThrow('renderClipSheet 5 cells', () => renderClipSheet(Array(5).fill({ jpeg: { width: 1, height: 1, data: onePixel }, number: 1, label: '' }), passJpeg));
mustThrow('renderClipSheet zero size', () => renderClipSheet([{ jpeg: { width: 0, height: 1, data: onePixel }, number: 1, label: '' }], passJpeg));
mustInvalidArg('clipSheetCell short sheet', () => clipSheetCell(blankSheet.subarray(1), 0, onePixel, 1, 1, 1, 1, '', '1'));
mustInvalidArg('clipSheetCell index 4', () => clipSheetCell(blankSheet, 4, onePixel, 1, 1, 1, 1, '', '1'));
mustInvalidArg('clipSheetCell width 65536', () => clipSheetCell(blankSheet, 0, onePixel, 65536, 1, 1, 1, '', '1'));
mustInvalidArg('clipSheetCell out_w 769', () => clipSheetCell(blankSheet, 0, onePixel, 1, 1, 769, 1, '', '1'));
mustInvalidArg('clipSheetCell out_h 0.5', () => clipSheetCell(blankSheet, 0, onePixel, 1, 1, 1, 0.5, '', '1'));
mustInvalidArg('clipSheetCell data length', () => clipSheetCell(blankSheet, 0, onePixel, 2, 1, 1, 1, '', '1'));
mustInvalidArg('clipSheetCell long number', () => clipSheetCell(blankSheet, 0, onePixel, 1, 1, 1, 1, '', '9'.repeat(4097)));
mustInvalidArg('clipSheetCell long label', () => clipSheetCell(blankSheet, 0, onePixel, 1, 1, 1, 1, 'x'.repeat(1000001), '1'));

// ---- kindOf / extensionOf against the re.split oracle (bench/l0/run_kind_of.py --emit) ----
const kindScript = fileURLToPath(new URL('../../bench/l0/run_kind_of.py', import.meta.url));
const kindRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [kindScript, '--emit', '--n', String(Math.min(CASES, 20000)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let kindMismatches = 0, kindTsDiff = 0;
for (const [name, at, ext, kind] of kindRows) {
  const got = [extensionAt(name), extensionOf(name), kindOf(name)];
  if (got[0] !== at || got[1] !== ext || got[2] !== kind) {
    kindMismatches++;
    if (kindMismatches <= 5) console.error('kind mismatch', JSON.stringify({ name, got, want: [at, ext, kind] }));
  }
  if (tsKindOf(name) !== got[2] || tsExtensionOf(name) !== got[1]) kindTsDiff++;
}
mustThrow('kindOf number', () => kindCode(5));
mustThrow('extensionAt null', () => extensionAt(null));

// ---- rowPieces against the sheet-row oracle (bench/l0/run_row_pieces.py --emit) ----
const rowScript = fileURLToPath(new URL('../../bench/l0/run_row_pieces.py', import.meta.url));
const rowRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [rowScript, '--emit', '--n', String(CASES), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let rowMismatches = 0, rowTsDiff = 0;
for (const [cells, rowNo, max, want] of rowRows) {
  const pieces = rowPieces(cells, rowNo, max);
  const got = JSON.stringify(pieces.map(p => [p.row, p.col1, p.col2, p.text]));
  if (got !== JSON.stringify(want)) {
    rowMismatches++;
    if (rowMismatches <= 5) console.error('row mismatch', JSON.stringify({ cells: cells.slice(0, 5), rowNo, max, got: got.slice(0, 300) }));
  }
  if (JSON.stringify(tsRowPieces(cells, rowNo, max)) !== JSON.stringify(pieces)) rowTsDiff++;
}
mustThrow('rowTextPieces rowNo 0', () => rowTextPieces(['a'], 0, 10));
mustThrow('rowTextPieces rowNo 1.5', () => rowTextPieces(['a'], 1.5, 10));
mustThrow('rowTextPieces rowNo 1e15+1', () => rowTextPieces(['a'], 1e15 + 1, 10));
mustThrow('rowTextPieces max 0', () => rowTextPieces(['a'], 1, 0));
mustThrow('rowTextPieces max 2^40+1', () => rowTextPieces(['a'], 1, 2 ** 40 + 1));
mustThrow('rowTextPieces texts numbers', () => rowTextPieces([1, 2], 1, 10));

// sheet chunks: the extractSheets grouping and rangeOf.
const chunkScript = fileURLToPath(new URL('../../bench/l0/run_sheet_chunks.py', import.meta.url));
const chunkRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [chunkScript, '--emit', '--n', String(Math.ceil(CASES / 10)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let chunkMismatches = 0, chunkTsDiff = 0, chunkCases = 0, rangeCases = 0;
const tsCtx = { limits: { chunkChars: 0, cells: Infinity, chars: Infinity }, check() {} };
for (const item of chunkRows) {
  if (item[0] === 'range' && item.length === 6) {
    rangeCases++;
    const got = cellRange(item[1], item[2], item[3], item[4]);
    if (got !== item[5]) {
      chunkMismatches++;
      if (chunkMismatches <= 5) console.error('range mismatch', JSON.stringify({ item, got }));
    }
    continue;
  }
  chunkCases++;
  const [name, rows, max, want] = item;
  const chunks = extractSheetChunks(name, rows, max);
  const got = JSON.stringify(chunks.map(c => [c.loc.range, c.loc.row1, c.loc.row2, c.loc.col1, c.loc.col2, c.text]));
  if (got !== JSON.stringify(want)) {
    chunkMismatches++;
    if (chunkMismatches <= 5) console.error('chunk mismatch', JSON.stringify({ name, max, rows: rows.length, got: got.slice(0, 300) }));
  }
  tsCtx.limits.chunkChars = max;
  if (JSON.stringify(tsExtractSheets({ sheets: [{ name, rows }], notes: [] }, tsCtx).chunks) !== JSON.stringify(chunks)) chunkTsDiff++;
}
mustThrow('cellRange row1 0', () => cellRange(0, 1, 1, 1));
mustThrow('cellRange col2 1e15+1', () => cellRange(1, 1, 1, 1e15 + 1));
mustThrow('cellRange row2 1.5', () => cellRange(1, 1.5, 1, 1));
mustThrow('sheetChunks max 0', () => sheetChunks('S', [], 0));
mustThrow('sheetChunks max 2^40+1', () => sheetChunks('S', [], 2 ** 40 + 1));
mustThrow('sheetChunks piece row 0', () => sheetChunks('S', [{ row: 0, col1: 1, col2: 1, text: 'a' }], 10));
mustThrow('sheetChunks piece col1 1.5', () => sheetChunks('S', [{ row: 1, col1: 1.5, col2: 2, text: 'a' }], 10));
mustThrow('sheetChunks piece without text', () => sheetChunks('S', [{ row: 1, col1: 1, col2: 1 }], 10));

// text around: the textAround byte window plan, and the glue against the verbatim textAround.
const aroundScript = fileURLToPath(new URL('../../bench/l0/run_text_around.py', import.meta.url));
const aroundRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [aroundScript, '--emit', '--n', String(Math.ceil(CASES / 10)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let aroundMismatches = 0, aroundTsDiff = 0, aroundGlueCases = 0;
// Every field but text must match the verbatim textAround; text can differ only where this Node's
// TextDecoder differs from the verified decodeBytes (counted, as decode_ts_differences).
function aroundCompare(request, got, want) {
  if (JSON.stringify({ ...got, text: '' }) !== JSON.stringify({ ...want, text: '' })) {
    aroundMismatches++;
    if (aroundMismatches <= 5) console.error('around glue mismatch', JSON.stringify({ request, got, want }).slice(0, 600));
  } else if (got.text !== want.text) aroundTsDiff++;
}
const aroundDir = mkdtempSync(join(tmpdir(), 'pruv-around-'));
try {
  const aroundPath = join(aroundDir, 'f.txt');
  for (const [i, [hex, line, before, after, maxBytes, want]] of aroundRows.entries()) {
    const buf = Buffer.from(hex, 'hex');
    const got = textAroundPlan(buf, line, before, after, maxBytes);
    if (JSON.stringify(got) !== JSON.stringify(want)) {
      aroundMismatches++;
      if (aroundMismatches <= 5) console.error('around mismatch', JSON.stringify({ i, line, before, after, maxBytes, got, want }));
    }
    // The glue on a file: every case with a small file, every 20th otherwise.
    if (buf.length > 4096 && i % 20) continue;
    aroundGlueCases++;
    writeFileSync(aroundPath, buf);
    aroundCompare({ path: aroundPath, line, before, after, maxBytes }, await textAround({ path: aroundPath, line, before, after, maxBytes }),
      await tsTextAround({ path: aroundPath, line, before, after, maxBytes }));
  }
  // Defaults, a fractional line, expectSource and a missing file go through the glue as in Lair.
  writeFileSync(aroundPath, 'a\nb\nc\n');
  for (const request of [{ path: aroundPath, line: 2 }, { path: aroundPath, line: 2.7, before: -3 },
    { path: aroundPath, line: 0 }, { path: aroundPath, line: 2, expectSource: 'x' },
    { path: join(aroundDir, 'missing.txt'), line: 1 }]) {
    aroundGlueCases++;
    aroundCompare(request, await textAround(request), await tsTextAround(request));
  }
} finally { rmSync(aroundDir, { recursive: true, force: true }); }
mustThrow('textAroundPlan line 0', () => textAroundPlan(Buffer.from('a'), 0, 0, 0, 10));
mustThrow('textAroundPlan line 1e15+1', () => textAroundPlan(Buffer.from('a'), 1e15 + 1, 0, 0, 10));
mustThrow('textAroundPlan before -1', () => textAroundPlan(Buffer.from('a'), 1, -1, 0, 10));
mustThrow('textAroundPlan after 0.5', () => textAroundPlan(Buffer.from('a'), 1, 0, 0.5, 10));
mustThrow('textAroundPlan maxBytes 2^40+1', () => textAroundPlan(Buffer.from('a'), 1, 0, 0, 2 ** 40 + 1));
mustThrow('textAroundPlan maxBytes NaN', () => textAroundPlan(Buffer.from('a'), 1, 0, 0, NaN));
mustThrow('textAroundPlan data string', () => textAroundPlan('a', 1, 0, 0, 10));

// parse html: the parseHtml record list against the Python oracle, and the El tree glue against the
// verbatim parseHtml (own href, colspan and rowspan attributes only, the ones Lair reads).
const htmlScript = fileURLToPath(new URL('../../bench/l0/run_parse_html.py', import.meta.url));
const htmlRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [htmlScript, '--emit', '--n', String(Math.ceil(CASES / 10)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let htmlMismatches = 0, htmlTsDiff = 0;
const htmlCanon = (node) => typeof node === 'string' ? node : [node.tag,
  Object.fromEntries(['href', 'colspan', 'rowspan'].filter(k => Object.hasOwn(node.attrs, k)).map(k => [k, node.attrs[k]])),
  node.children.map(htmlCanon)];
for (const [i, [html, want]] of htmlRows.entries()) {
  const got = parseHtmlRecords(html);
  if (got.length !== want.length || got.some((x, k) => x !== want[k])) {
    htmlMismatches++;
    if (htmlMismatches <= 5) console.error('html mismatch', JSON.stringify({ i, html: html.slice(0, 200) }));
  }
  if (JSON.stringify(parseHtml(html).map(htmlCanon)) !== JSON.stringify(tsParseHtml(html).map(htmlCanon))) {
    htmlTsDiff++;
    if (htmlTsDiff <= 5) console.error('html ts difference', JSON.stringify({ i, html: html.slice(0, 200) }));
  }
}
mustThrow('parseHtmlRecords number', () => parseHtmlRecords(1));
mustThrow('parseHtmlRecords undefined', () => parseHtmlRecords());

// docx parts: the docx_parts list (after the parse records and the image count) against the Python oracle,
// and the glue objects against the verbatim docxParts (block elements compared as subtrees).
const partsScript = fileURLToPath(new URL('../../bench/l0/run_docx_parts.py', import.meta.url));
const partsRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [partsScript, '--emit', '--n', String(Math.ceil(CASES / 10)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let partsMismatches = 0, partsTsDiff = 0;
for (const [i, [html, images, want]] of partsRows.entries()) {
  const out = docxPartsRecords(html);
  const got = out.slice(1 + out[0]);
  if (got.length !== want.length + 1 || got[0] !== images || want.some((x, k) => x !== got[k + 1])) {
    partsMismatches++;
    if (partsMismatches <= 5) console.error('parts mismatch', JSON.stringify({ i, html: html.slice(0, 200) }));
  }
  const mine = docxParts(html);
  const ts = tsDocxParts(html);
  const a = JSON.stringify([mine.blocks.map(x => [x.n, x.kind, htmlCanon(x.el), x.text]), mine.html, mine.images]);
  const b = JSON.stringify([ts.blocks.map(x => [x.n, x.kind, htmlCanon(x.el), x.text]), ts.html, ts.images]);
  if (a !== b) {
    partsTsDiff++;
    if (partsTsDiff <= 5) console.error('parts ts difference', JSON.stringify({ i, html: html.slice(0, 200) }));
  }
}
mustThrow('docxPartsRecords number', () => docxPartsRecords(1));
mustThrow('docxPartsRecords undefined', () => docxPartsRecords());

// tokenize: the token list against the Python oracle (Unicode 17.0), and the glue against the verbatim
// tokenize. The verbatim one uses this Node's ICU, so its differences fail only on Unicode 17.0.
const tokenScript = fileURLToPath(new URL('../../bench/l0/run_tokenize.py', import.meta.url));
const tokenRows = execFileSync(process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3'),
  [tokenScript, '--emit', '--n', String(Math.ceil(CASES / 10)), '--seed', String(SEED)],
  { encoding: 'utf8', maxBuffer: 1 << 30 }).split('\n').filter(Boolean).map(l => JSON.parse(l));
let tokenMismatches = 0, tokenTsDiff = 0;
const tokenUnicode17 = process.versions.unicode === '17.0';
for (const [i, [text, want]] of tokenRows.entries()) {
  const got = tokenizeRecords(text);
  if (got.length !== want.length || got.some((x, k) => x !== want[k])) {
    tokenMismatches++;
    if (tokenMismatches <= 5) console.error('token mismatch', JSON.stringify({ i, text: text.slice(0, 200) }));
  }
  if (JSON.stringify(tokenize(text)) !== JSON.stringify(tsTokenize(text))) {
    tokenTsDiff++;
    if (tokenTsDiff <= 5 && tokenUnicode17) console.error('token ts difference', JSON.stringify({ i, text: text.slice(0, 200) }));
  }
}
if (JSON.stringify(tokenize('a\ud800Σ')) !== JSON.stringify(tokenize('a\ufffdΣ'))) { tokenMismatches++; console.error('token lone surrogate'); }
mustThrow('tokenizeRecords number', () => tokenizeRecords(1));
mustThrow('tokenizeRecords undefined', () => tokenizeRecords());

// ---- d) summary ----
console.log(JSON.stringify({
  node: process.version,
  platform: process.platform,
  arch: process.arch,
  clip_cases: CASES,
  clip_mismatches: clipMismatches,
  clip_ts_differences: clipTsDiff,
  host_cases: CASES,
  host_mismatches: hostMismatches,
  host_ts_differences: hostTsDiff,
  version_cases: validVersions.length,
  version_mismatches: versionMismatches,
  version_ts_differences: versionTsDiff,
  col_cases: colInputs.length,
  col_mismatches: colMismatches,
  col_ts_differences: colTsDiff,
  term_cases: CASES,
  term_mismatches: termMismatches,
  term_ts_differences: termTsDiff,
  decode_cases: decodeRows.length,
  decode_mismatches: decodeMismatches,
  decode_ts_differences: decodeTsDiff,
  zip_cases: zipRows.length,
  zip_mismatches: zipMismatches,
  zip_ts_differences: zipTsDiff,
  png_cases: pngRows.length,
  png_mismatches: pngMismatches,
  png_ts_differences: pngTsDiff,
  split_cases: splitRows.length,
  split_mismatches: splitMismatches,
  split_ts_differences: splitTsDiff,
  group_cases: groupRows.length,
  group_mismatches: groupMismatches,
  group_ts_differences: groupTsDiff,
  shrink_cases: shrinkRows.length,
  shrink_mismatches: shrinkMismatches,
  shrink_ts_differences: shrinkTsDiff,
  ranges_cases: rangesRows.length,
  ranges_mismatches: rangesMismatches,
  ranges_ts_differences: rangesTsDiff,
  labels_cases: labelsRows.length,
  labels_mismatches: labelsMismatches,
  labels_ts_differences: labelsTsDiff,
  join_cases: joinRows.length,
  join_mismatches: joinMismatches,
  join_ts_differences: joinTsDiff,
  cut_cases: cutRows.length,
  cut_mismatches: cutMismatches,
  cut_ts_differences: cutTsDiff,
  range_cases: rangeRows.length,
  range_mismatches: rangeMismatches,
  range_ts_differences: rangeTsDiff,
  page_cases: pageRows.length,
  page_mismatches: pageMismatches,
  page_ts_differences: pageTsDiff,
  grouped_cases: groupedRows.length,
  grouped_mismatches: groupedMismatches,
  grouped_ts_differences: groupedTsDiff,
  under_cases: underRows.length,
  under_mismatches: underMismatches,
  under_ts_differences: underTsDiff,
  cap_keep_cases: capRows.length,
  cap_keep_mismatches: capMismatches,
  cap_keep_ts_cases: capTsCases,
  cap_keep_ts_differences: capTsDiff,
  evict_stop_cases: evictRows.length,
  evict_stop_mismatches: evictMismatches,
  evict_stop_ts_cases: evictTsCases,
  evict_stop_ts_differences: evictTsDiff,
  index_terms_cases: indexRows.length,
  index_terms_mismatches: indexMismatches,
  index_terms_ts_differences: indexTsDiff,
  note_pairs_cases: noteRows.length,
  note_pairs_mismatches: noteMismatches,
  note_pairs_ts_differences: noteTsDiff,
  cell_date_cases: cellDateRows.length,
  cell_date_mismatches: cellDateMismatches,
  cell_date_ts_differences: cellDateTsDiff,
  cell_str_cases: cellStrRows.length,
  cell_str_mismatches: cellStrMismatches,
  cell_str_ts_differences: cellStrTsDiff,
  cell_int_cases: cellIntRows.length,
  cell_int_mismatches: cellIntMismatches,
  cell_int_ts_differences: cellIntTsDiff,
  extract_version_cases: extractRows.length,
  extract_version_mismatches: extractMismatches,
  extract_version_ts_differences: extractTsDiff,
  chunk_page_cases: chunkPageRows.length,
  chunk_page_mismatches: chunkPageMismatches,
  chunk_page_ts_differences: chunkPageTsDiff,
  image_counts_cases: imageCountsRows.length,
  image_counts_mismatches: imageCountsMismatches,
  image_counts_ts_differences: imageCountsTsDiff,
  text_lines_cases: textLinesRows.length,
  text_lines_mismatches: textLinesMismatches,
  text_lines_ts_differences: textLinesTsDiff,
  luhn_cases: luhnRows.length,
  luhn_mismatches: luhnMismatches,
  luhn_ts_differences: luhnTsDiff,
  chat_ref_cases: chatRefRows.length,
  chat_ref_mismatches: chatRefMismatches,
  chat_ref_ts_differences: chatRefTsDiff,
  sheet_cases: sheetRows.length,
  sheet_mismatches: sheetMismatches,
  sheet_ts_differences: sheetTsDiff,
  kind_cases: kindRows.length,
  kind_mismatches: kindMismatches,
  kind_ts_differences: kindTsDiff,
  row_cases: rowRows.length,
  row_mismatches: rowMismatches,
  row_ts_differences: rowTsDiff,
  chunk_cases: chunkCases,
  chunk_range_cases: rangeCases,
  chunk_mismatches: chunkMismatches,
  chunk_ts_differences: chunkTsDiff,
  around_cases: aroundRows.length,
  around_mismatches: aroundMismatches,
  around_glue_cases: aroundGlueCases,
  around_ts_differences: aroundTsDiff,
  html_cases: htmlRows.length,
  html_mismatches: htmlMismatches,
  html_ts_differences: htmlTsDiff,
  parts_cases: partsRows.length,
  parts_mismatches: partsMismatches,
  parts_ts_differences: partsTsDiff,
  token_cases: tokenRows.length,
  token_mismatches: tokenMismatches,
  token_ts_differences: tokenTsDiff,
  token_unicode: process.versions.unicode,
  error_checks: errorOk ? 'ok' : 'FAILED',
}));
process.exit(chatRefMismatches || chatRefTsDiff || luhnMismatches || luhnTsDiff || textLinesMismatches || textLinesTsDiff || imageCountsMismatches || imageCountsTsDiff || clipMismatches || hostMismatches || versionMismatches || colMismatches || termMismatches || decodeMismatches || zipMismatches || zipTsDiff || pngMismatches || pngTsDiff || splitMismatches || splitTsDiff || groupMismatches || groupTsDiff || shrinkMismatches || shrinkTsDiff || rangesMismatches || rangesTsDiff || labelsMismatches || labelsTsDiff || joinMismatches || joinTsDiff || cutMismatches || cutTsDiff || rangeMismatches || rangeTsDiff || pageMismatches || pageTsDiff || groupedMismatches || groupedTsDiff || underMismatches || underTsDiff || capMismatches || capTsDiff || evictMismatches || evictTsDiff || indexMismatches || (indexUnicode17 && indexTsDiff) || noteMismatches || noteTsDiff || cellDateMismatches || cellDateTsDiff || cellStrMismatches || cellStrTsDiff || cellIntMismatches || cellIntTsDiff || extractMismatches || extractTsDiff || chunkPageMismatches || chunkPageTsDiff || sheetMismatches || sheetTsDiff || kindMismatches || kindTsDiff || rowMismatches || rowTsDiff || chunkMismatches || chunkTsDiff || aroundMismatches || htmlMismatches || htmlTsDiff || partsMismatches || partsTsDiff || tokenMismatches || (tokenUnicode17 && tokenTsDiff) || !errorOk ? 1 : 0);
