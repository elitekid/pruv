import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

function versionParts(version) {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(version.trim());
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null;
}

export function versionAtLeast(a, b) {
  const left = versionParts(a);
  const right = versionParts(b);
  if (!left || !right) return false;
  for (let i = 0; i < 3; i += 1) {
    const x = left[i] ?? 0;
    const y = right[i] ?? 0;
    if (x !== y) return x > y;
  }
  return true;
}


if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for await (const line of createInterface({ input: process.stdin })) {
    const value = JSON.parse(line);
    console.log(JSON.stringify(versionAtLeast(...value)));
  }
}
