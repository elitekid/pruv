// The extraction version key (Lair src/documents/versions.ts) at commit 698e1bd1: PARTS, EXTRACTOR_REVISION,
// EXTRACTOR_VERSION, sha256 and extractVersionOf are copied verbatim with the types removed. DOC_LIMITS
// (src/documents/types.ts) is cut down to the two values EXTRACTOR_VERSION reads. The JSON line driver
// below is added.
// Driver input per line: {"f":"sha256","text":string} or {"f":"extract","source":string,"kind":string,
// "variant"?:string} (variant left out uses the default) -> JSON string.
import { createHash } from 'node:crypto';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

const DOC_LIMITS = { ocrPages: 100, chunkChars: 1500 };

export const PARTS = {
  pdfjs: '6.3.289',
  tesseract: '7.0.0',
  langData: 'kor+eng 4.0.0_best_int',
  mammoth: '1.13.0',
  readExcelFile: '9.3.10',
  papaparse: '5.7.0',
};

export const EXTRACTOR_REVISION = 2;

export const EXTRACTOR_VERSION = [
  `rev${EXTRACTOR_REVISION}`,
  `pdfjs${PARTS.pdfjs}`, `tesseract${PARTS.tesseract}`, PARTS.langData, `mammoth${PARTS.mammoth}`, `rxl${PARTS.readExcelFile}`, `papaparse${PARTS.papaparse}`,
  `chunk${DOC_LIMITS.chunkChars}`, `scan${DOC_LIMITS.ocrPages}`,
].join(';');

export const sha256 = (data) => createHash('sha256').update(data).digest('hex');

export const extractVersionOf = (sourceVersion, kind, variant = '') =>
  sha256(`${sourceVersion}\n${kind}\n${variant}\n${EXTRACTOR_VERSION}`);

export const VERSION_PATTERN = /^[0-9a-f]{64}$/;

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const q = JSON.parse(line);
    let out;
    if (q.f === 'sha256') out = sha256(q.text);
    else if (q.variant === undefined) out = extractVersionOf(q.source, q.kind);
    else out = extractVersionOf(q.source, q.kind, q.variant);
    console.log(JSON.stringify(out));
  }
}
