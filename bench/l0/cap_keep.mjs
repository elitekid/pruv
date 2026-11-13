// Verbatim copy of capChars from Lair src/documents/extract.ts and groupedNumber from
// src/documents/context.ts (commit 698e1bd1). Only TypeScript types are removed and capChars is exported.
// docText, addMissing and setPartialReason (context.ts) are stand-ins that record their arguments; the JSON
// line driver below is added.
// Driver input: {"lens":[n...],"max":n} per line, each chunk an image chunk of 'x' repeated n times
// -> JSON number of chunks capChars keeps.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const groupedNumber = (value) => value.toLocaleString('en-US');
const docText = (key, args) => ({ key, ...(args ? { args } : {}) });
const addMissing = (draft, text, i18n) => { draft.missing.push(text); draft.missingI18n.push(i18n); };
const setPartialReason = (draft, text, i18n) => { draft.reason = text; draft.reasonI18n = i18n; };

export function capChars(draft, max) {
  let used = 0;
  let keep = draft.chunks.length;
  for (let i = 0; i < draft.chunks.length; i += 1) {
    used += draft.chunks[i].text.length;
    if (used > max) { keep = i; break; }
  }
  if (keep >= draft.chunks.length) return;
  const dropped = draft.chunks.slice(keep);
  draft.chunks = draft.chunks.slice(0, keep);
  const first = dropped[0].loc;
  const last = dropped[dropped.length - 1].loc;
  let where = '뒷부분';
  const limit = groupedNumber(max);
  let i18n = docText('wireDocs.missing.extractedLimitRest', { limit });
  if (first.kind === 'page' && last.kind === 'page') {
    where = first.page === last.page ? `${first.page}쪽` : `${first.page}~${last.page}쪽`;
    i18n = docText('wireDocs.missing.extractedLimitPages', { pages: first.page === last.page ? `${first.page}` : `${first.page}-${last.page}`, limit });
  } else if (first.kind === 'block' && last.kind === 'block') {
    where = `블록 ${first.from}~${last.to}`;
    i18n = docText('wireDocs.missing.extractedLimitBlocks', { range: `${first.from}-${last.to}`, limit });
  }
  addMissing(draft, `${where}은 뽑은 글 글자 수 한도(${max.toLocaleString('ko-KR')}자)를 넘어 읽지 않았어`, i18n);
  setPartialReason(draft, '한도를 넘은 부분이 있어', docText('wireDocs.reason.overLimit'));
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const { lens, max } = JSON.parse(line);
    const draft = { chunks: lens.map(n => ({ loc: { kind: 'image' }, text: 'x'.repeat(n) })), missing: [], missingI18n: [] };
    capChars(draft, max);
    console.log(JSON.stringify(draft.chunks.length));
  }
}
