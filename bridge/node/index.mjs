import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const native = require('./pruv_bridge.node');
export const clipBytes = native.clipBytes;
export const hostWithin = native.hostWithin;
