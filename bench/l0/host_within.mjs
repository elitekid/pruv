import { createInterface } from 'node:readline';

// Verbatim TS original, Lair src/shared/web-sources.ts:47-50,97-99:
/*
export function hostWithin(host: string, sites: readonly string[]): boolean {
  const h = host.toLowerCase();
  return sites.some(site => h === site || h.endsWith(`.${site}`));
}
export function webHost(url: string): string | undefined {
  try { return new URL(url).hostname.toLowerCase() || undefined; } catch { return undefined; }
}
*/
// Executable copy with only TypeScript annotations removed.
export function hostWithin(host, sites) {
  const h = host.toLowerCase();
  return sites.some(site => h === site || h.endsWith(`.${site}`));
}
export function webHost(url) {
  try { return new URL(url).hostname.toLowerCase() || undefined; } catch { return undefined; }
}

for await (const line of createInterface({ input: process.stdin })) {
  const c = JSON.parse(line);
  const host = c.mode === 'direct' ? c.input : webHost(c.input);
  console.log(JSON.stringify({ host: host ?? null,
    ts: host === undefined ? null : hostWithin(host, c.sites) }));
}
