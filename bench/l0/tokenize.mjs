// Verbatim copy of CJK, WORD, RUN, WHOLE_MAX and tokenize from Lair src/documents/search.ts (last changed at
// commit 5d974738). Only TypeScript types are removed. buildIndex and scoreIndex are not copied (floating point,
// see RESULTS.md section 89).
// Added: fromOutput and the JSON line driver below.
// Driver input, one JSON line per case:
//   ["text", text]  -> tokenize(text)
//   ["out", out]    -> fromOutput for a Pruv tokenize output (tokenize.pruv)
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

const fromCps = (cps, at, n) => {
  let s = '';
  for (let k = 0; k < n; k += 4096) s += String.fromCodePoint(...cps.slice(at + k, at + Math.min(n, k + 4096)));
  return s;
};

/** Added: the token strings of a Pruv output [count, then per token: n, n code points] (the bridge glue does the same). */
export function fromOutput(out) {
  const tokens = [];
  let p = 1;
  for (let t = 0; t < out[0]; t += 1) {
    const n = out[p];
    tokens.push(fromCps(out, p + 1, n));
    p += 1 + n;
  }
  if (p !== out.length) throw new Error('tokenize output has trailing slots');
  return tokens;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const [mode, x] = JSON.parse(line);
    console.log(JSON.stringify(mode === 'text' ? tokenize(x) : fromOutput(x)));
  }
}
