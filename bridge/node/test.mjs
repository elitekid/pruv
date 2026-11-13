// Usage: node bridge/node/test.mjs [--cases N] [--seed S]
import { clipBytes, hostWithin, versionAtLeast, colLetters } from './index.mjs';
import { versionAtLeast as tsVersionAtLeast } from '../../bench/l0/version_at_least.mjs';
import { colLetters as tsColLetters } from '../../bench/l0/col_letters.mjs';

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
if (clipBytes('', 0) !== '') {
  console.error("clipBytes('', 0) !== ''");
  errorOk = false;
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
  error_checks: errorOk ? 'ok' : 'FAILED',
}));
process.exit(clipMismatches || hostMismatches || versionMismatches || colMismatches || !errorOk ? 1 : 0);
