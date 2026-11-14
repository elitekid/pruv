#!/usr/bin/env node
// L3-1 A4 reference run: the verbatim TypeScript logic (claude.ts readHead / tailInfo / readClaude, tail.ts
// readEdgeLines / openLineWindow / TurnCollector / isoOf / oneLine / clipBytes, plan.ts) on the fixtures written by
// test_a4.py, compared with the Python oracle's packet projected to the same shape.
//
//   node reference.mjs [--typescript DIR] [--src DIR] [--fixtures FILE] [--out FILE] [--only SUBSTRING] [--verbose]
//
// Defaults: --src <repo>/.lair-src-l3-1, --fixtures work/a4/fixtures.json (run test_a4.py first).
//
// How the TS is run: the source files are type-stripped (node:module stripTypeScriptTypes, Node >= 22.13; else the
// `typescript` package if resolvable), only import specifiers are rewritten, and the private functions of claude.ts
// are exposed by an appended `export { ... }` line. Function bodies are never touched. Environment dependencies are
// replaced at the module boundary: node:fs/promises -> an in-memory file system (one virtual snapshot per fixture,
// served through the original readEdgeLines / openLineWindow code with 256 KiB stream chunks), the child-process
// helpers -> stubs, opencode.ts -> a stub whose folderKey returns one constant (folder matching is a host duty),
// shared contracts -> LAST_PLAN_LIMITS. plan.ts runs unchanged; the comparison projects only turns, omittedBefore,
// model and title (window) / title, cwd, entrypoint (head) / title, lastAt (tail).
//
// Strings are compared as UTF-16 code unit arrays, so lone surrogates are visible (policy P2) and replacement-encoding
// of the baseline is not applied; the oracle packet is decoded from UTF-8 into units. Differences are reported, not
// hidden: classify each against P1-P5 (docs/CLAUDE_IMPORT_SPEC.md). Exit code 1 when any difference or TS error remains.
// Fixtures larger than the API limits (the TS reader has no such rejection) and flagged fixtures whose size does not
// equal the edge/window size (the host cut cannot be reproduced) are reported as skipped.
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import * as nodeModule from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const opt = (name, fallback) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : fallback; };
const SRC = path.resolve(opt('--src', path.join(HERE, '..', '..', '..', '.lair-src-l3-1')));
const FIXTURES = path.resolve(opt('--fixtures', path.join(HERE, 'work', 'a4', 'fixtures.json')));
const OUT = opt('--out', undefined);
const ONLY = opt('--only', undefined);
const VERBOSE = args.includes('--verbose');
const TS_DIR = opt('--typescript', undefined);
const EDGE = 65536;
const WINDOW = 8 * 1024 * 1024;

// ---------------- building the reference modules ----------------
function stripTypes(source) {
  // The sources use parameter properties, which strip-only mode rejects, so the `typescript` package comes first
  // (resolved from --typescript DIR, else from this folder); Node's strip mode is only a fallback.
  let ts;
  try {
    const from = TS_DIR ? path.join(path.resolve(TS_DIR), 'package.json') : import.meta.url;
    ts = createRequire(from)('typescript');
  } catch {}
  if (ts) return ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
  if (typeof nodeModule.stripTypeScriptTypes === 'function') return nodeModule.stripTypeScriptTypes(source, { mode: 'strip' });
  throw new Error('no `typescript` package (pass --typescript DIR) and no module.stripTypeScriptTypes');
}

const SPECIFIERS = {
  'node:fs/promises': './vfs.mjs',
  '../engine-children': './stubs.mjs',
  '../windows-system': './stubs.mjs',
  './opencode': './opencode_stub.mjs',
  './tail': './tail.mjs',
  './plan': './plan.mjs',
  '../../shared/engine-import': './shared_stub.mjs',
  '../../shared/contracts': './shared_stub.mjs',
};
const rewriteImports = code => code.replace(/from\s+(['"])([^'"]+)\1/g, (whole, _q, spec) => (SPECIFIERS[spec] ? `from '${SPECIFIERS[spec]}'` : whole));

const VFS = `import { Readable } from 'node:stream';
const world = () => globalThis.__L3_VFS;
const fail = code => Object.assign(new Error(code), { code });
function node(p) {
  const w = world();
  if (w.files.has(p)) return { isSymbolicLink: () => false, isFile: () => true, isDirectory: () => false, size: w.files.get(p).length, dev: 1, ino: 1, mtimeMs: 0 };
  if (w.dirs.has(p)) return { isSymbolicLink: () => false, isFile: () => false, isDirectory: () => true, size: 0, dev: 1, ino: 2, mtimeMs: 0 };
  return undefined;
}
export async function lstat(p) { const n = node(p); if (!n) throw fail('ENOENT'); return n; }
export async function realpath(p) { if (!node(p)) throw fail('ENOENT'); return p; }
export async function readdir(p) {
  const w = world();
  if (!w.dirs.has(p)) throw fail('ENOENT');
  const names = new Set();
  for (const f of [...w.files.keys(), ...w.dirs]) { const parent = f.slice(0, f.lastIndexOf('/')) || '/'; if (parent === p && f !== p) names.add(f.slice(f.lastIndexOf('/') + 1)); }
  return [...names];
}
export async function open(p) {
  const data = world().files.get(p);
  if (!data) throw fail('ENOENT');
  return {
    async stat() { return node(p); },
    async read(buffer, offset, length, position) { return { bytesRead: data.copy(buffer, offset, position, Math.min(data.length, position + length)), buffer }; },
    async close() {},
    createReadStream({ start, end, highWaterMark }) {
      const chunks = [];
      for (let at = start; at <= end; at += highWaterMark) chunks.push(data.subarray(at, Math.min(end + 1, at + highWaterMark)));
      return Readable.from(chunks, { objectMode: true });
    },
  };
}
`;
const STUBS = `export const spawnEngine = () => { throw new Error('child processes are not part of the reference run'); };
export const systemTaskkillPath = () => '';
`;
const OPENCODE_STUB = `export const folderKey = () => 'k'; // folder matching is a host duty; every cwd matches the virtual folder
`;
const SHARED_STUB = `export const LAST_PLAN_LIMITS = { items: 30, text: 200 };
`;

async function buildReference() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'l3-ref-'));
  const hashes = {};
  const transform = (file, extra = '') => {
    const source = fs.readFileSync(path.join(SRC, file), 'utf8');
    hashes[file] = crypto.createHash('sha256').update(source).digest('hex');
    return rewriteImports(stripTypes(source)) + extra;
  };
  fs.writeFileSync(path.join(dir, 'vfs.mjs'), VFS);
  fs.writeFileSync(path.join(dir, 'stubs.mjs'), STUBS);
  fs.writeFileSync(path.join(dir, 'opencode_stub.mjs'), OPENCODE_STUB);
  fs.writeFileSync(path.join(dir, 'shared_stub.mjs'), SHARED_STUB);
  fs.writeFileSync(path.join(dir, 'tail.mjs'), transform('tail.ts'));
  fs.writeFileSync(path.join(dir, 'plan.mjs'), transform('plan.ts'));
  fs.writeFileSync(path.join(dir, 'claude.mjs'), transform('claude.ts', '\nexport { engineLine, humanText, titleOf, tailInfo, droppedUser };\n'));
  const load = name => import(pathToFileURL(path.join(dir, name)).href);
  return { tail: await load('tail.mjs'), claude: await load('claude.mjs'), hashes, dir };
}

// ---------------- running one fixture ----------------
const THREAD = 'fixture1';
const FILE = `/h/projects/-w/${THREAD}.jsonl`;
const IDENTITY = { dev: 1, ino: 1 };

function virtualFile(fx, data) {
  if (fx.op === 'head') {
    if (fx.flag) return data.length === EDGE ? Buffer.concat([data, Buffer.from('x')]) : undefined;
    return data.length <= EDGE ? data : undefined;
  }
  const limit = fx.op === 'tail' ? EDGE : WINDOW;
  if (fx.flag) return data.length === limit ? Buffer.concat([Buffer.from('x'), data]) : undefined;
  return data.length <= limit ? data : undefined;
}

async function runTs(mods, fx, file) {
  globalThis.__L3_VFS = { files: new Map([[FILE, file]]), dirs: new Set(['/h', '/h/projects', '/h/projects/-w']) };
  const { tail, claude } = mods;
  if (fx.op === 'head') return claude.readHead(await tail.readEdgeLines(FILE, 'head', file.length, IDENTITY));
  if (fx.op === 'tail') return claude.tailInfo(await tail.readEdgeLines(FILE, 'tail', file.length, IDENTITY));
  const source = { source: 'fixture', engine: 'claude', home: '/h', kind: 'home' };
  return claude.readClaude(source, '/w', THREAD, { signal: new AbortController().signal, env: {} });
}

// ---------------- projection to one comparable shape (strings as UTF-16 code unit arrays) ----------------
const units = s => Array.from({ length: s.length }, (_, i) => s.charCodeAt(i));
function project(op, r) {
  const o = {};
  const put = (k, v) => { if (v !== undefined) o[k] = units(v); };
  if (op === 'head') { put('title', r.title); put('cwd', r.cwd); put('entrypoint', r.entrypoint); return o; }
  if (op === 'tail') { put('title', r.title); put('lastAt', r.lastAt); return o; }
  o.omittedBefore = r.omittedBefore;
  put('model', r.model);
  put('title', r.title);
  o.turns = r.turns.map(t => {
    const q = { prompt: units(t.prompt), reply: units(t.reply), tools: t.tools };
    if (t.createdAt !== undefined) q.createdAt = units(t.createdAt);
    if (t.completedAt !== undefined) q.completedAt = units(t.completedAt);
    if (t.clipped) q.clipped = true;
    return q;
  });
  return o;
}

// The oracle packet [0, 14, turn_slots, byte_len, ...meta, ...turns, ...text] in the same shape.
function decodePacket(op, packet) {
  if (packet[0] !== 0) return { error: packet[0] };
  const ts = packet[2];
  const n = packet[3];
  const meta = packet.slice(4, 18);
  const turns = packet.slice(18, 18 + ts);
  const text = Buffer.from(packet.slice(18 + ts, 18 + ts + n));
  const ref = i => (meta[i] === -1 ? undefined : units(text.subarray(meta[i], meta[i] + meta[i + 1]).toString('utf8')));
  const o = {};
  const put = (k, v) => { if (v !== undefined) o[k] = v; };
  if (op === 'head') { put('title', ref(4)); put('cwd', ref(6)); put('entrypoint', ref(8)); return o; }
  if (op === 'tail') { put('title', ref(4)); put('lastAt', ref(10)); return o; }
  o.omittedBefore = meta[2] === 1;
  put('model', ref(12));
  put('title', ref(4));
  o.turns = [];
  for (let i = 0; i < meta[3]; i++) {
    const r = turns.slice(10 * i, 10 * i + 10);
    const str = (s, l) => units(text.subarray(s, s + l).toString('utf8'));
    const t = { prompt: str(r[0], r[1]), reply: str(r[2], r[3]), tools: r[8] };
    if (r[4] !== -1) t.createdAt = str(r[4], r[5]);
    if (r[6] !== -1) t.completedAt = str(r[6], r[7]);
    if (r[9] === 1) t.clipped = true;
    o.turns.push(t);
  }
  return o;
}

const canon = v => (Array.isArray(v) ? v.map(canon) : v && typeof v === 'object' ? Object.fromEntries(Object.keys(v).sort().map(k => [k, canon(v[k])])) : v);
const same = (a, b) => JSON.stringify(canon(a)) === JSON.stringify(canon(b));
const isUnits = v => Array.isArray(v) && v.every(x => typeof x === 'number');
function show(v) {
  if (isUnits(v)) { const s = String.fromCharCode(...v.slice(0, 60)); return `${JSON.stringify(s)}${v.length > 60 ? '…' : ''}(len ${v.length})`; }
  if (Array.isArray(v)) return v.map(show);
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, show(x)]));
  return v;
}
function diffPaths(a, b, at = '', out = []) {
  if (out.length >= 6) return out;
  if (isUnits(a) && isUnits(b)) {
    if (a.length !== b.length || a.some((x, i) => x !== b[i])) {
      const i = a.findIndex((x, j) => x !== b[j]);
      out.push(`${at}: ts len ${a.length}, oracle len ${b.length}, first difference at unit ${i < 0 ? Math.min(a.length, b.length) : i}`);
    }
    return out;
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    for (const k of new Set([...Object.keys(a), ...Object.keys(b)])) {
      if (!(k in a)) out.push(`${at}/${k}: only in oracle`);
      else if (!(k in b)) out.push(`${at}/${k}: only in ts`);
      else diffPaths(a[k], b[k], `${at}/${k}`, out);
    }
    return out;
  }
  if (a !== b) out.push(`${at}: ts ${JSON.stringify(a)}, oracle ${JSON.stringify(b)}`);
  return out;
}

// ---------------- main ----------------
const cases = JSON.parse(fs.readFileSync(FIXTURES, 'utf8')).filter(fx => !ONLY || fx.name.includes(ONLY));
const mods = await buildReference();
const meta = {
  node: process.versions.node, electron: process.versions.electron ?? null, v8: process.versions.v8, platform: process.platform,
  sources: mods.hashes, fixtures: FIXTURES, count: cases.length,
};
console.log(`reference: node ${meta.node}${meta.electron ? ` electron ${meta.electron}` : ''}, ${cases.length} fixtures`);
console.log(`sources: ${Object.entries(meta.sources).map(([f, h]) => `${f} ${h.slice(0, 12)}`).join(', ')}`);

const results = [];
let diffs = 0;
let errors = 0;
let skipped = 0;
for (const fx of cases) {
  const data = Buffer.from(fx.data, 'base64');
  const expectedRaw = fx.expected;
  if (expectedRaw[0] !== 0) { results.push({ name: fx.name, status: 'skipped', reason: `API limit (code ${expectedRaw[0]})` }); skipped++; continue; }
  const file = virtualFile(fx, data);
  if (!file) { results.push({ name: fx.name, status: 'skipped', reason: 'flagged fixture does not have the exact edge/window size' }); skipped++; continue; }
  let ts;
  try {
    ts = project(fx.op, await runTs(mods, fx, file));
  } catch (error) {
    errors++;
    results.push({ name: fx.name, status: 'ts-error', error: String(error && error.stack ? error.stack : error) });
    console.log(`TS ERROR ${fx.name}: ${error && error.message}`);
    continue;
  }
  const want = decodePacket(fx.op, expectedRaw);
  if (same(ts, want)) { results.push({ name: fx.name, status: 'match' }); if (VERBOSE) console.log(`match    ${fx.name}`); continue; }
  diffs++;
  const where = diffPaths(ts, want);
  results.push({ name: fx.name, status: 'diff', where });
  console.log(`DIFF     ${fx.name}`);
  for (const w of where) console.log(`           ${w}`);
  if (VERBOSE) { console.log('           ts    ', JSON.stringify(show(ts)).slice(0, 600)); console.log('           oracle', JSON.stringify(show(want)).slice(0, 600)); }
}
const matched = results.filter(r => r.status === 'match').length;
console.log(`summary: ${matched} match, ${diffs} differ, ${errors} TS errors, ${skipped} skipped, of ${cases.length}`);
if (OUT) fs.writeFileSync(OUT, JSON.stringify({ meta, results }, null, 1));
fs.rmSync(mods.dir, { recursive: true, force: true });
process.exit(diffs || errors ? 1 : 0);
