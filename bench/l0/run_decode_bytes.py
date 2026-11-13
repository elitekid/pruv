#!/usr/bin/env python3
"""Cross-check Lair decodeBytes + looksBinary (src/documents/decode.ts).

Pruv (decode_bytes.pruv) picks the encoding with proved BOM checks and a proved strict UTF-8
validator, then decodes through the encoding_rs adapters in decode_adapter/ (crate pruv_decode).
Each byte string goes to Pruv, to the TypeScript copy (TextDecoder) and to decode_oracle.py, an
independent WHATWG decoder; all three must give the same [text, encoding, binary].
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
from run import HERE, WORK, RESULTS, build_decode_adapter, configure, run
from run_host_within import portable
from decode_oracle import cases, oracle

NAME = 'decode_bytes'
KINDS = ['utf-8', 'utf-16le', 'utf-16be', 'utf-8', 'cp949']

HARNESS = '''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead, Write};
fn main() {
  let out = io::stdout(); let mut out = out.lock();
  for line in io::stdin().lock().lines() {
    let line = line.unwrap(); let hex = &line[1..];
    let data: Vec<u8> = (0..hex.len()).step_by(2).map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect();
    let text = sol::decode_text(&data);
    let text: String = text.bytes().map(|b| format!("{:02x}", b)).collect();
    writeln!(out, "{} {} x{}", sol::decode_kind(&data), sol::looks_binary(&data) as u8, text).unwrap();
  }
}
'''


def ts_runtime():
    """Lair runs decode.ts in Electron's Node. Plain Node's TextDecoder('euc-kr') can differ from
    WHATWG (Node 26 on macOS maps byte 0x80 to U+0080), so prefer the Electron binary: LAIR_ELECTRON,
    then an installed Lair Preview, then node."""
    candidates = [os.environ.get('LAIR_ELECTRON'), '/Applications/Lair Preview.app/Contents/MacOS/Lair']
    exe = next((c for c in candidates if c and Path(c).exists()), None)
    if exe:
        os.environ['ELECTRON_RUN_AS_NODE'] = '1'
        cmd = [exe]
    else:
        cmd = ['node']
    versions = json.loads(run(cmd + ['-e', 'console.log(JSON.stringify([process.versions.node, process.versions.electron || null, process.versions.icu]))']))
    return cmd, dict(electron=bool(exe), node=versions[0], electron_version=versions[1], icu=versions[2])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20000)
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    summary = dict(seed=args.seed, random_cases=args.n, runs={})
    differences, failed = [], False
    try:
        g2, summary['tools'] = configure()
        flags, link = build_decode_adapter()
        inputs, summary['edge_cases'] = cases(args.n, args.seed)
        summary['cases'] = len(inputs)
        expected = [oracle(x) for x in inputs]
        node, summary['ts_runtime'] = ts_runtime()
        # split('\n'), not splitlines(): decoded text may hold U+2028 or U+0085 raw.
        ts = [json.loads(x) for x in run(node + [HERE / (NAME+'.mjs')], ''.join(json.dumps(x.hex())+'\n' for x in inputs)).split('\n')[:-1]]
        assert len(ts) == len(inputs)
        # Each line is prefixed with 'x' so empty input is still a line with a field.
        payload = ''.join('x'+x.hex()+'\n' for x in inputs)
        for compiler in ('py', 'rs'):
            for backend in ('rust', 'llvm'):
                key = compiler+'/'+backend
                row = summary['runs'][key] = dict(status='error')
                try:
                    work = WORK / (NAME+'_'+compiler+'_'+backend)
                    work.mkdir(exist_ok=True)
                    compiled = g2.compile_pruv(compiler, str(HERE / (NAME+'.pruv')), str(work), backend, flags)
                    row['verification'] = portable(compiled)
                    if compiled['rc'] != 0:
                        raise RuntimeError(json.dumps(portable(compiled)))
                    harness = work / 'main.rs'
                    harness.write_text(HARNESS.replace('@SOL@', compiled['rs']))
                    extra = []
                    if compiled['ll']:
                        extra, error = g2.build_llvm_objects(compiled['ll'], NAME, str(work))
                        if error:
                            raise RuntimeError(error)
                    exe = work / 'runner'
                    run([g2.RUSTC, '-O', '--edition', '2021', '-C', 'target-cpu=native', harness, '-o', exe]+link+extra)
                    lines = run([exe], payload).splitlines()
                    assert len(lines) == len(inputs)
                    pruv = []
                    for x in lines:
                        kind, binary, hx = x.split(' ')
                        pruv.append([bytes.fromhex(hx[1:]).decode(), KINDS[int(kind)], binary == '1'])
                    for i, (c, p, t, want) in enumerate(zip(inputs, pruv, ts, expected)):
                        if p != t or p != want:
                            differences.append(dict(compiler_backend=key, case_index=i, input=c.hex(),
                                input_bytes=len(c), pruv=p, ts=t, expected=want))
                    row.update(cases=len(inputs), pruv_oracle_pass=sum(p == w for p, w in zip(pruv, expected)),
                               ts_oracle_pass=sum(t == w for t, w in zip(ts, expected)),
                               pruv_ts_pass=sum(p == t for p, t in zip(pruv, ts)))
                    ok = row['pruv_oracle_pass'] == row['ts_oracle_pass'] == len(inputs)
                    row['status'] = 'ok' if ok else 'wrong'
                    failed |= not ok
                    print(key+': '+json.dumps(row), flush=True)
                except Exception as exc:
                    row['error'] = portable(str(exc))
                    failed = True
                    print(key+': '+row['error'], flush=True)
    except Exception as exc:
        summary['error'] = portable(str(exc))
        failed = True
    differences.sort(key=lambda d: (d['input_bytes'], d['input'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='input bytes, input hex, compiler/backend')
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / (NAME+'_summary.json')).write_text(json.dumps(summary, indent=2)+'\n')
    (RESULTS / (NAME+'_differences.jsonl')).write_text(''.join(json.dumps(d)+'\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
