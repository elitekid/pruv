// Verbatim copy of whole, failAround and textAround from Lair src/documents/preview.ts (last changed at
// commit 60afe277, unchanged at 698e1bd1). Only TypeScript types and `satisfies WireKey` are removed;
// decodeBytes is the verbatim copy in decode_bytes.mjs. Added: fromPlan and the JSON line driver below.
// Driver input, one JSON line per case:
//   [hexBytes, line, before, after, maxBytes, expectSource]  -> the TextAround of textAround on a temporary
//                                                               file with those bytes (null fields are left out
//                                                               of the request)
//   ["plan", hexBytes, plan]                                  -> the TextAround built by fromPlan from a Pruv
//                                                               around_plan record (text_around.pruv)
import { createHash } from 'node:crypto';
import { open, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';
import { decodeBytes } from './decode_bytes.mjs';

const READ_BLOCK = 1024 * 1024;
/** 끝이 UTF-8 글자 가운데에서 잘렸으면 그 글자를 뺀다 */
function whole(buffer) {
  let end = buffer.length;
  let back = 0;
  while (end - 1 - back >= 0 && back < 4 && (buffer[end - 1 - back] & 0xc0) === 0x80) back += 1;
  const leadAt = end - 1 - back;
  if (leadAt >= 0 && buffer[leadAt] >= 0xc0) {
    const need = buffer[leadAt] >= 0xf0 ? 4 : buffer[leadAt] >= 0xe0 ? 3 : 2;
    if (back + 1 < need) end = leadAt;
  }
  return buffer.subarray(0, end);
}

const failAround = (reason, extra = {}) =>
  ({ ok: false, reason, totalLines: 0, from: 0, to: 0, target: 0, text: '', truncated: false, bytes: 0, ...extra });

/** 목표 줄 앞뒤 200줄(기본), 256 KiB 까지. 파일을 한 번 훑으며 해시·줄 수·줄 시작 위치를 함께 구한다. */
export async function textAround(request) {
  const before = Math.max(0, request.before ?? 200);
  const after = Math.max(0, request.after ?? 200);
  const maxBytes = request.maxBytes ?? 256 * 1024;
  let file;
  try { file = await open(request.path, 'r'); } catch (error) {
    return error.code === 'ENOENT'
      ? failAround('파일이 없어', { reasonI18n: { key: 'wireWork.documents.preview.fileMissing' } })
      : failAround('파일을 열지 못했어', { reasonI18n: { key: 'wireWork.documents.preview.openFailed' } });
  }
  try {
    const size = (await file.stat()).size;
    const target = Math.max(1, Math.floor(request.line));
    const from = Math.max(1, target - before);
    const to = target + after;
    const hash = createHash('sha256');
    const block = Buffer.alloc(READ_BLOCK);
    let newlines = 0;
    let startOffset = from === 1 ? 0 : -1;
    let endOffset = -1;
    let targetStart = target === 1 ? 0 : -1;
    let targetEnd = -1;
    let lastStart = 0;
    let prevStart = 0;
    let offset = 0;
    let last = 0;
    for (;;) {
      const { bytesRead } = await file.read(block, 0, READ_BLOCK, offset);
      if (!bytesRead) break;
      hash.update(block.subarray(0, bytesRead));
      let at = 0;
      for (;;) {
        const found = block.indexOf(10, at);
        if (found < 0 || found >= bytesRead) break;
        newlines += 1;
        // 줄 newlines 가 끝났으니 다음 줄(newlines + 1)은 found + 1 에서 시작한다
        prevStart = lastStart;
        lastStart = offset + found + 1;
        if (newlines + 1 === from) startOffset = offset + found + 1;
        if (newlines + 1 === target) targetStart = offset + found + 1;
        if (newlines === target) targetEnd = offset + found + 1;
        if (newlines === to) endOffset = offset + found + 1;
        at = found + 1;
      }
      last = block[bytesRead - 1];
      offset += bytesRead;
    }
    const sourceVersion = hash.digest('hex');
    if (request.expectSource && request.expectSource !== sourceVersion) return failAround('changed', { sourceVersion });
    const totalLines = size === 0 ? 0 : newlines + (last === 10 ? 0 : 1);
    if (!totalLines || from > totalLines || startOffset < 0) return failAround('그 줄이 파일 끝을 넘었어', { sourceVersion, totalLines, reasonI18n: { key: 'wireWork.documents.preview.linePastEnd' } });
    // 목표 줄이 파일 끝을 넘으면 마지막 줄을 목표로 본다
    const shown = Math.min(target, totalLines);
    if (targetStart < 0 || target > totalLines) targetStart = last === 10 ? prevStart : lastStart;
    if (targetEnd < 0 || target > totalLines) targetEnd = size;
    const end = endOffset >= 0 ? endOffset : size;
    // 바이트 상한 안에 목표 줄이 반드시 들어가게 앞뒤 예산을 나눈다(목표 줄이 상한보다 길면 그 줄을 잘라 넣는다)
    const targetBytes = targetEnd - targetStart;
    const targetCut = targetBytes > maxBytes;
    const targetLen = targetCut ? maxBytes : targetBytes;
    const beforeNeed = targetStart - startOffset;
    const afterNeed = Math.max(0, end - targetEnd);
    let beforeBudget = Math.floor((maxBytes - targetLen) / 2);
    let afterBudget = maxBytes - targetLen - beforeBudget;
    if (beforeNeed < beforeBudget) afterBudget += beforeBudget - beforeNeed;
    else if (afterNeed < afterBudget) beforeBudget += afterBudget - afterNeed;
    const beforeLen = Math.min(beforeNeed, beforeBudget);
    const afterLen = Math.min(afterNeed, afterBudget);
    let truncated = targetCut;
    const readAt = async (position, length) => {
      const buffer = Buffer.alloc(length);
      if (length) await file.read(buffer, 0, length, position);
      return buffer;
    };
    // 앞쪽은 줄 시작에 맞춰 앞을 자르고, 뒤쪽은 줄 끝에 맞춰 뒤를 자른다
    let beforeBuf = await readAt(targetStart - beforeLen, beforeLen);
    if (beforeLen < beforeNeed) {
      // 바로 앞 바이트가 줄바꿈이면 이미 줄 시작이다
      const edge = await readAt(targetStart - beforeLen - 1, 1);
      if (edge[0] !== 10) {
        const cut = beforeBuf.indexOf(10);
        beforeBuf = cut >= 0 ? beforeBuf.subarray(cut + 1) : Buffer.alloc(0);
      }
      truncated = true;
    }
    let afterBuf = await readAt(targetEnd, afterLen);
    if (afterLen < afterNeed) {
      const cut = afterBuf.lastIndexOf(10);
      afterBuf = cut >= 0 ? afterBuf.subarray(0, cut + 1) : Buffer.alloc(0);
      truncated = true;
    }
    let targetBuf = await readAt(targetStart, targetLen);
    if (targetCut) targetBuf = whole(targetBuf);
    const beforeLines = beforeBuf.filter(byte => byte === 10).length;
    const used = Buffer.concat([beforeBuf, targetBuf, afterBuf]);
    let text = decodeBytes(used).text.replace(/\r\n/g, '\n');
    if (text.endsWith('\n')) text = text.slice(0, -1);
    const lines = text === '' && used.length === 0 ? 0 : text.split('\n').length;
    const from0 = shown - beforeLines;
    return { ok: true, sourceVersion, totalLines, from: from0, to: Math.min(from0 + lines - 1, totalLines), target: shown, text, truncated, bytes: used.length, targetIncluded: true, ...(targetCut ? { targetTruncated: true } : {}) };
  } finally { await file.close(); }
}

/** Added: the TextAround from the bytes of the file and a Pruv around_plan record, by the same steps as the
 *  tail of textAround above (the bridge glue does the same with its native decodeBytes). */
export function fromPlan(buf, plan) {
  const sourceVersion = createHash('sha256').update(buf).digest('hex');
  if (plan[0] === 0) return failAround('그 줄이 파일 끝을 넘었어', { sourceVersion, totalLines: plan[1], reasonI18n: { key: 'wireWork.documents.preview.linePastEnd' } });
  if (plan[0] !== 1) throw new Error('bad plan ' + JSON.stringify(plan));
  const [, totalLines, shown, b1, b2, t1, t2, a1, a2, beforeLines, truncated, targetCut] = plan;
  const used = Buffer.concat([buf.subarray(b1, b2), buf.subarray(t1, t2), buf.subarray(a1, a2)]);
  let text = decodeBytes(used).text.replace(/\r\n/g, '\n');
  if (text.endsWith('\n')) text = text.slice(0, -1);
  const lines = text === '' && used.length === 0 ? 0 : text.split('\n').length;
  const from0 = shown - beforeLines;
  return { ok: true, sourceVersion, totalLines, from: from0, to: Math.min(from0 + lines - 1, totalLines), target: shown, text, truncated: truncated === 1, bytes: used.length, targetIncluded: true, ...(targetCut ? { targetTruncated: true } : {}) };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const dir = await mkdtemp(join(tmpdir(), 'text-around-'));
  const path = join(dir, 'f.txt');
  try {
    for await (const line of createInterface({ input: process.stdin })) {
      const x = JSON.parse(line);
      if (x[0] === 'plan') {
        console.log(JSON.stringify(fromPlan(Buffer.from(x[1], 'hex'), x[2])));
        continue;
      }
      const [hex, ln, before, after, maxBytes, expectSource] = x;
      await writeFile(path, Buffer.from(hex, 'hex'));
      const request = { path, line: ln };
      if (before !== null) request.before = before;
      if (after !== null) request.after = after;
      if (maxBytes !== null) request.maxBytes = maxBytes;
      if (expectSource !== null) request.expectSource = expectSource;
      console.log(JSON.stringify(await textAround(request)));
    }
  } finally { await rm(dir, { recursive: true, force: true }); }
}
