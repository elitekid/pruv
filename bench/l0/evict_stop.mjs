// Verbatim copy of evict and readMeta from Lair src/documents/archive.ts (commit 698e1bd1). Only TypeScript types
// are removed and the fs/promises and path imports are replaced by an in-memory folder (readdir, stat, readFile,
// rm, join below) so no disk is touched; missing, STALE_MS and VERSION_PATTERN are copied as they are. The JSON
// line driver below is added.
// Driver input per line: {"entries":[{"name":s,"mtime":n,"bytes":n|null}...],"limit":n,"pinned":[s...],"keep":s}
// in folder order; bytes null means a folder without a readable meta.json. Every mtime is within the last hour,
// so no stale folder is removed. -> JSON [removed count, [removed names in delete order]].
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

let folder = new Map();
const removedNames = [];
const join = (...parts) => parts.join('/');
const readdir = async () => [...folder.keys()];
const stat = async (dir) => { const e = folder.get(dir.slice(dir.lastIndexOf('/') + 1)); if (!e) throw Object.assign(new Error('missing'), { code: 'ENOENT' }); return { isDirectory: () => true, mtimeMs: e.mtime }; };
const readFile = async (path) => { const name = path.split('/').at(-2); const e = folder.get(name); if (!e || e.bytes === null) throw Object.assign(new Error('missing'), { code: 'ENOENT' }); return JSON.stringify({ v: 1, extractor: 'x', createdAt: 0, bytes: e.bytes, status: { state: 'done' } }); };
const rm = async (dir) => { const name = dir.slice(dir.lastIndexOf('/') + 1); removedNames.push(name); folder.delete(name); };

const missing = (error) => error?.code === 'ENOENT';
const STALE_MS = 60 * 60_000;
const VERSION_PATTERN = /^[0-9a-f]{64}$/;

export async function readMeta(dir) {
  try {
    const meta = JSON.parse(await readFile(join(dir, 'meta.json'), 'utf8'));
    return meta?.v === 1 && meta.status ? meta : null;
  } catch { return null; }
}

/** 영구 보관이 한도를 넘으면 고정 안 된 것을 오래된 순서로 지운다. 반쯤 쓰다 남은 임시 폴더도 치운다. 지운 판 수를 돌려준다. */
export async function evict(root, limitBytes, pinned, keep) {
  let names;
  try { names = await readdir(root); } catch (error) { if (missing(error)) return 0; throw error; }
  const entries = [];
  let total = 0;
  const now = Date.now();
  for (const name of names) {
    const dir = join(root, name);
    const info = await stat(dir).catch(() => null);
    if (!info?.isDirectory()) continue;
    if (!VERSION_PATTERN.test(name)) {
      if (/^\.(tmp|old)-/.test(name) && now - info.mtimeMs > STALE_MS) await rm(dir, { recursive: true, force: true });
      continue;
    }
    const meta = await readMeta(dir);
    if (!meta) {
      if (now - info.mtimeMs > STALE_MS) await rm(dir, { recursive: true, force: true });
      continue;
    }
    entries.push({ version: name, bytes: meta.bytes, mtime: info.mtimeMs });
    total += meta.bytes;
  }
  let removed = 0;
  for (const entry of entries.sort((a, b) => a.mtime - b.mtime)) {
    if (total <= limitBytes) break;
    if (pinned.has(entry.version) || entry.version === keep) continue;
    await rm(join(root, entry.version), { recursive: true, force: true });
    total -= entry.bytes;
    removed += 1;
  }
  return removed;
}

/** Driver helper: run evict on an in-memory folder of driver entries -> [removed count, removed names]. */
export async function evictFolder(entries, limit, pinned, keep) {
  const now = Date.now();
  folder = new Map(entries.map(e => [e.name, { mtime: now - 60_000 + e.mtime, bytes: e.bytes }]));
  removedNames.length = 0;
  const count = await evict('/root', limit, new Set(pinned), keep);
  return [count, [...removedNames]];
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const { entries, limit, pinned, keep } = JSON.parse(line);
    console.log(JSON.stringify(await evictFolder(entries, limit, pinned, keep)));
  }
}
