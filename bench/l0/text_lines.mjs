// Verbatim copy of textDraft from Lair src/documents/extract.ts and groupedNumber from
// src/documents/context.ts (commit 698e1bd1). Only TypeScript types are removed and textDraft is exported.
// decodeBytes (decode.ts) is a stand-in that returns the driver's text as UTF-8; chunkLines (chunker.ts) is a
// stand-in that returns the kept lines; docText, addNote, addMissing and setPartialReason (context.ts) are
// stand-ins that record their arguments. The JSON line driver below is added.
// Driver input: {"text":"...","chars":n} per line -> JSON [draft.lines, number of kept lines].
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const groupedNumber = (value) => value.toLocaleString('en-US');
const decodeBytes = (text) => ({ text, encoding: 'utf-8' });
const chunkLines = (lines, max) => lines.slice();
const docText = (key, args) => ({ key, ...(args ? { args } : {}) });
const addNote = (draft, text, i18n) => { draft.notes.push(text); };
const addMissing = (draft, text, i18n) => { draft.missing.push(text); };
const setPartialReason = (draft, text, i18n) => { draft.reason = text; draft.reasonI18n = i18n; };

export function textDraft(bytes, ctx) {
  const decoded = decodeBytes(bytes);
  const lines = decoded.text.split('\n').map(line => (line.endsWith('\r') ? line.slice(0, -1) : line));
  if (lines.length && lines[lines.length - 1] === '') lines.pop();
  const draft = { chunks: [], locKind: 'lines', notes: [], missing: [], lines: lines.length };
  if (decoded.encoding === 'cp949') addNote(draft, 'UTF-8 이 아니라서 CP949 로 읽었어', docText('wireDocs.note.cp949'));
  if (decoded.encoding.startsWith('utf-16')) addNote(draft, 'UTF-16 글이라 줄 위치로 원문을 열 때 어긋날 수 있어', docText('wireDocs.note.utf16'));
  let used = 0;
  let keep = lines.length;
  for (let i = 0; i < lines.length; i += 1) {
    used += lines[i].length + 1;
    if (used > ctx.limits.chars) { keep = i; break; }
  }
  draft.chunks = chunkLines(lines.slice(0, keep), ctx.limits.chunkChars);
  if (keep < lines.length) {
    addMissing(draft, `${keep + 1}~${lines.length}줄은 글자 수 한도(${ctx.limits.chars.toLocaleString('ko-KR')}자)를 넘어 읽지 않았어`,
      docText('wireDocs.missing.textCharLimit', { range: `${keep + 1}-${lines.length}`, limit: groupedNumber(ctx.limits.chars) }));
    setPartialReason(draft, '한도를 넘은 부분이 있어', docText('wireDocs.reason.overLimit'));
  }
  return draft;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const { text, chars } = JSON.parse(line);
    const draft = textDraft(text, { limits: { chars, chunkChars: 1000 } });
    console.log(JSON.stringify([draft.lines, draft.chunks.length]));
  }
}
