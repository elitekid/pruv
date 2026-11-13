// Verbatim copy of CJK, WORD, RUN, WHOLE_MAX, tokenize, SearchIndex's shape and buildIndex from Lair
// src/documents/search.ts (last changed at commit 5d974738). Only TypeScript types are removed.
// scoreIndex is not copied (floating point).
// Added: the JSON line driver below. Input, one JSON line per case: an array of chunk texts. Output: buildIndex of it.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const CJK = /[\p{Script=Hangul}\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]/u;
const WORD = /[\p{L}\p{N}]+/gu;
const RUN = /[\p{Script=Hangul}\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]+|[^\p{Script=Hangul}\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}]+/gu;
/** 한글 덩어리가 이보다 길면 통째 낱말은 만들지 않고 2글자 묶음만 쓴다 */
const WHOLE_MAX = 8;

export function tokenize(text) {
  const out = [];
  for (const word of text.toLowerCase().matchAll(WORD)) {
    for (const run of word[0].matchAll(RUN)) {
      const part = run[0];
      if (!CJK.test(part[0])) { out.push(part); continue; }
      const chars = Array.from(part);
      if (chars.length === 1) { out.push(part); continue; }
      if (chars.length >= 3 && chars.length <= WHOLE_MAX) out.push(part);
      for (let i = 0; i + 1 < chars.length; i += 1) out.push(chars[i] + chars[i + 1]);
    }
  }
  return out;
}

export function buildIndex(texts) {
  const terms = new Map();
  const lens = [];
  let total = 0;
  let i = 0;
  for (const text of texts) {
    const tf = new Map();
    const tokens = tokenize(text);
    for (const token of tokens) tf.set(token, (tf.get(token) ?? 0) + 1);
    for (const [token, count] of tf) {
      const list = terms.get(token);
      if (list) list.push(i, count); else terms.set(token, [i, count]);
    }
    lens.push(tokens.length);
    total += tokens.length;
    i += 1;
  }
  return { v: 1, count: i, avg: i ? Math.max(total / i, 1) : 1, lens, terms: Object.fromEntries(terms) };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    console.log(JSON.stringify(buildIndex(JSON.parse(line))));
  }
}
