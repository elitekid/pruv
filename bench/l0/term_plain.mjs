// Verbatim copy of Lair src/backend/engine-install.ts: C1_KIND (line 54), AnsState ..
// applyCrLf (lines 205-313). Only TypeScript types are removed; `export` and the JSON line
// driver below are added.
// Driver input: one JSON line [state, [chunk, ...]]; output: JSON [text, state].
// state = mode (0 plain, 1 esc, 2 esc+escInt, 3 csi, 4 str, 5 str+stEsc) + 6 if skipLf.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const C1_KIND = { 0x9d: ']', 0x90: 'P', 0x9f: '_', 0x9e: '^', 0x98: 'X' };

export function freshAnsState() {
  return { mode: 'plain', stEsc: false, escInt: false };
}

function resetAns(state) {
  state.mode = 'plain';
  state.kind = undefined;
  state.stEsc = false;
  state.escInt = false;
}

function charStep(data, index) {
  const code = data.charCodeAt(index);
  if (code >= 0xd800 && code <= 0xdbff && index + 1 < data.length) {
    const low = data.charCodeAt(index + 1);
    if (low >= 0xdc00 && low <= 0xdfff) return 2;
  }
  return 1;
}

/** OSC/DCS/SOS/PM/APC의 ESC+백슬래시(ST) 종료. 청크 끝 ESC는 stEsc로 다음 청크에서 본다. */
function tryStEnd(state, data, index) {
  if (data.charCodeAt(index) !== 0x1b) return null;
  if (index + 1 < data.length) {
    if (data[index + 1] === '\\') { resetAns(state); return index + 2; }
    return index + 1;
  }
  state.stEsc = true;
  return index + 1;
}

/** CSI·OSC(BEL/ST)·DCS/SOS/PM/APC와 C0/C1/DEL을 빼고 탭·LF·CR만 남긴다. CR은 applyCrLf에서 처리한다. */
export function plainFromAnsi(state, data) {
  let out = '';
  for (let index = 0; index < data.length; ) {
    if (state.stEsc) {
      state.stEsc = false;
      if (data.charCodeAt(index) === 0x5c) { resetAns(state); index += 1; continue; }
    }
    const code = data.charCodeAt(index);
    const step = charStep(data, index);
    const ch = step === 2 ? data.slice(index, index + 2) : data[index];
    if (state.mode === 'plain') {
      if (code === 0x1b && step === 1) { state.mode = 'esc'; index += 1; continue; }
      if (code === 0x9b && step === 1) { state.mode = 'csi'; index += 1; continue; }
      const eight = C1_KIND[code];
      if (eight && step === 1) { state.mode = 'str'; state.kind = eight; index += 1; continue; }
      if (code === 0x09 || code === 0x0a || code === 0x0d) { out += ch; index += step; continue; }
      if (code >= 0xdc00 && code <= 0xdfff) { index += step; continue; }
      if (code >= 0xd800 && code <= 0xdbff) {
        if (step === 2) { out += ch; index += 2; continue; }
        index += 1;
        continue;
      }
      if (code < 0x20 || code === 0x7f || (step === 1 && code >= 0x80 && code <= 0x9f)) { index += step; continue; }
      out += ch;
      index += step;
      continue;
    }
    if (state.mode === 'esc') {
      if (code >= 0x20 && code <= 0x2f) { state.escInt = true; index += step; continue; }
      if (!state.escInt) {
        if (ch === '[') { state.mode = 'csi'; index += step; continue; }
        if (ch === ']') { state.mode = 'str'; state.kind = ']'; index += step; continue; }
        if ('PX^_'.includes(ch)) { state.mode = 'str'; state.kind = ch; index += step; continue; }
      }
      if (code >= 0x30 && code <= 0x7e) { resetAns(state); index += step; continue; }
      resetAns(state);
      continue;
    }
    if (state.mode === 'csi') {
      if (code >= 0x40 && code <= 0x7e) resetAns(state);
      index += step;
      continue;
    }
    if (code === 0x07 || code === 0x9c) { resetAns(state); index += step; continue; }
    const st = tryStEnd(state, data, index);
    if (st !== null) { index = st; continue; }
    index += step;
  }
  return out;
}

/** 단독 CR은 LF로 바꾸고 다음 LF 하나만 건너뛴다(CRLF 하나로). */
export function applyCrLf(skipLf, text) {
  let out = '';
  let skip = skipLf;
  for (let index = 0; index < text.length; ) {
    const code = text.charCodeAt(index);
    const step = charStep(text, index);
    const ch = step === 2 ? text.slice(index, index + 2) : text[index];
    if (skip) {
      skip = false;
      if (code === 0x0a) { index += step; continue; }
    }
    if (code === 0x0d) {
      out += '\n';
      skip = true;
      index += step;
      continue;
    }
    out += ch;
    index += step;
  }
  return { text: out, skipLf: skip };
}

const MODES = ['plain', 'esc', 'esc', 'csi', 'str', 'str'];

export function fromState(n) {
  const a = n % 6;
  const state = freshAnsState();
  state.mode = MODES[a];
  state.escInt = a === 2;
  state.stEsc = a === 5;
  return { state, skipLf: n >= 6 };
}

export function toState(state, skipLf) {
  const a = { plain: 0, esc: state.escInt ? 2 : 1, csi: 3, str: state.stEsc ? 5 : 4 }[state.mode];
  return a + (skipLf ? 6 : 0);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const [n, chunks] = JSON.parse(line);
    let { state, skipLf } = fromState(n);
    let text = '';
    for (const chunk of chunks) {
      const r = applyCrLf(skipLf, plainFromAnsi(state, chunk));
      text += r.text;
      skipLf = r.skipLf;
    }
    console.log(JSON.stringify([text, toState(state, skipLf)]));
  }
}
