// Verbatim copies of padded, addNote and addMissing from Lair src/documents/context.ts (commit 698e1bd1). Only
// TypeScript types are removed; the JSON line driver below is added.
// Driver input per line: {"f":"addNote"|"addMissing","list":[s...],"pairs":[{"key":s}|null...]|null,
// "calls":[[text,{"key":s}|null]...]} -> JSON {"list":[s...],"pairs":[...]|null}, the draft list and its key list
// (notes/notesI18n or missing/missingI18n) after the calls in order; a null call key passes no i18n argument.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

/** 원문 배열 list 에 항목을 더하기 직전에 부른다: 짝 배열을 list 길이에 맞춰 돌려준다(키가 하나도 없으면 undefined). */
function padded(list, pairs, i18n) {
  if (!pairs && !i18n) return undefined;
  const out = pairs ?? [];
  while (out.length < list.length) out.push(null);
  return out;
}

/** 읽기 메모 하나를 원문과 키 짝으로 함께 더한다 */
export function addNote(draft, text, i18n) {
  const pairs = padded(draft.notes, draft.notesI18n, i18n);
  draft.notes.push(text);
  if (pairs) { pairs.push(i18n ?? null); draft.notesI18n = pairs; }
}

/** 빠진 범위 하나를 원문과 키 짝으로 함께 더한다 */
export function addMissing(draft, text, i18n) {
  const pairs = padded(draft.missing, draft.missingI18n, i18n);
  draft.missing.push(text);
  if (pairs) { pairs.push(i18n ?? null); draft.missingI18n = pairs; }
}

/** Driver helper: run the calls on a fresh draft -> {list, pairs}. */
export function runCalls(f, list, pairs, calls) {
  const draft = { notes: [], missing: [] };
  if (f === 'addNote') { draft.notes = list; if (pairs) draft.notesI18n = pairs; }
  else { draft.missing = list; if (pairs) draft.missingI18n = pairs; }
  for (const [text, key] of calls) {
    if (f === 'addNote') key ? addNote(draft, text, key) : addNote(draft, text);
    else key ? addMissing(draft, text, key) : addMissing(draft, text);
  }
  return f === 'addNote' ? { list: draft.notes, pairs: draft.notesI18n ?? null } : { list: draft.missing, pairs: draft.missingI18n ?? null };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const { f, list, pairs, calls } = JSON.parse(line);
    console.log(JSON.stringify(runCalls(f, list, pairs, calls)));
  }
}
