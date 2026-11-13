// Usage: node bridge/node/test.mjs [--cases N] [--seed S]
import { clipBytes, hostWithin, versionAtLeast, colLetters, termPlain, termState, decodeBytes, looksBinary } from './index.mjs';
import { versionAtLeast as tsVersionAtLeast } from '../../bench/l0/version_at_least.mjs';
import { colLetters as tsColLetters } from '../../bench/l0/col_letters.mjs';
import { plainFromAnsi, applyCrLf, fromState, toState } from '../../bench/l0/term_plain.mjs';
import { decodeBytes as tsDecodeBytes, looksBinary as tsLooksBinary } from '../../bench/l0/decode_bytes.mjs';
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
  error_checks: errorOk ? 'ok' : 'FAILED',
}));
process.exit(clipMismatches || hostMismatches || versionMismatches || colMismatches || termMismatches || decodeMismatches || !errorOk ? 1 : 0);
