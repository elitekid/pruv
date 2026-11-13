// Verbatim copy of extensionOf and kindOf from Lair src/documents/kinds.ts (commit 5d974738, unchanged at
// 698e1bd1). Only TypeScript types are removed; the JSON line driver below is added.
// Driver input: a JSON array [name, at] per line, at a UTF-16 index or -1 -> JSON array
// [extensionOf(name), kindOf(name), at < 0 ? '' : name.slice(at).toLowerCase()] (the last is the bridge glue).
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const IMAGE = new Set(['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tif', 'tiff']);
const TEXT = new Set([
  'txt', 'md', 'markdown', 'log', 'json', 'jsonl', 'yaml', 'yml', 'xml', 'html', 'htm', 'css', 'ini', 'toml', 'cfg', 'conf', 'env', 'rst', 'tex', 'srt', 'vtt',
  'js', 'mjs', 'cjs', 'ts', 'tsx', 'jsx', 'py', 'rb', 'go', 'rs', 'java', 'kt', 'swift', 'c', 'h', 'cc', 'cpp', 'hpp', 'cs', 'php', 'sh', 'bat', 'ps1', 'sql', 'svg',
]);
const UNSUPPORTED = new Set(['pptx', 'ppt', 'hwp', 'hwpx', 'doc', 'xls', 'odt', 'ods', 'odp', 'rtf', 'pages', 'numbers', 'key', 'zip', 'epub']);

export function extensionOf(name) {
  const base = name.split(/[\\/]/).pop() ?? name;
  const dot = base.lastIndexOf('.');
  return dot > 0 ? base.slice(dot + 1).toLowerCase() : '';
}

/** 확장자로 읽을 형식을 가린다. 모르는 확장자는 unknown 이고, 읽을 때 글인지 열어 보고 가린다. */
export function kindOf(name) {
  const ext = extensionOf(name);
  if (ext === 'pdf') return 'pdf';
  if (ext === 'docx') return 'docx';
  if (ext === 'xlsx') return 'xlsx';
  if (ext === 'csv' || ext === 'tsv') return 'csv';
  if (IMAGE.has(ext)) return 'image';
  if (TEXT.has(ext)) return 'text';
  if (UNSUPPORTED.has(ext)) return 'unsupported';
  return 'unknown';
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const [name, at] = JSON.parse(line);
    console.log(JSON.stringify([extensionOf(name), kindOf(name), at < 0 ? '' : name.slice(at).toLowerCase()]));
  }
}
