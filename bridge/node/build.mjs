// Builds the native module and copies it to bridge/node/pruv_bridge.node.
import { spawnSync } from 'node:child_process';
import { copyFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const target = process.env.CARGO_TARGET_DIR
  ? path.resolve(process.env.CARGO_TARGET_DIR)
  : path.join(dir, 'target');

const r = spawnSync('cargo', ['build', '--release', '--manifest-path', path.join(dir, 'Cargo.toml')], {
  stdio: 'inherit',
  shell: process.platform === 'win32',
  env: { ...process.env, CARGO_TARGET_DIR: target },
});
if (r.error) {
  console.error(`failed to run cargo: ${r.error.message}`);
  process.exit(1);
}
if (r.status !== 0) process.exit(r.status ?? 1);

const libName = {
  darwin: 'libpruv_node_bridge.dylib',
  linux: 'libpruv_node_bridge.so',
  win32: 'pruv_node_bridge.dll',
}[process.platform];
if (!libName) {
  console.error(`unsupported platform: ${process.platform}`);
  process.exit(1);
}
const src = path.join(target, 'release', libName);
if (!existsSync(src)) {
  console.error(`built library not found: ${src}`);
  process.exit(1);
}
const dest = path.join(dir, 'pruv_bridge.node');
copyFileSync(src, dest);
console.log(`wrote ${dest}`);
