#!/usr/bin/env python3
"""Q measurements: median of three timed calls, excluding file IO and builds."""
import sys
sys.dont_write_bytecode = True
import json
import platform
import shutil
import statistics
import subprocess
import time
from run_q_mutants import HERE, WORK, setup, build, run

HARNESS = r'''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::{env,fs,hint::black_box,time::Instant};
fn main() {
 let a: Vec<String> = env::args().collect();
 let data = fs::read(&a[1]).unwrap();
 for _ in 0..3 {
  let start = Instant::now();
  let out = black_box(sol::parse_tape(black_box(&data)));
  let elapsed = start.elapsed().as_secs_f64()*1000.0;
  if out[0] == -1 { println!("{} error {} {}",elapsed,out[1],out[2]); }
  else {
   assert_eq!(out[1],0); assert_eq!(out[2],data.len() as i64);
   assert_eq!(out[3],(out.len()/6) as i64);
   println!("{} ok {} {}",elapsed,out.len()/6,out[5]);
  }
 }
}
'''
TEXT_HARNESS = r'''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::{env,fs,hint::black_box,time::Instant};
fn main() {
 let a: Vec<String> = env::args().collect();
 let data = fs::read(&a[1]).unwrap();
 for _ in 0..3 {
  let start = Instant::now();
  let out = black_box(sol::text_of(black_box(&data)));
  let elapsed = start.elapsed().as_secs_f64()*1000.0;
  println!("{} text {} {}",elapsed,out.len(),out.as_bytes().iter().map(|b| *b as u64).sum::<u64>());
 }
}
'''
NODE = r'''
const fs = require('fs');
const text = fs.readFileSync(process.argv[1], 'utf8');
const out = [];
for (let i=0;i<3;i++) {
 const start=process.hrtime.bigint();
 const value=JSON.parse(text);
 const ms=Number(process.hrtime.bigint()-start)/1e6;
 out.push(ms);
 if (value === undefined) throw Error('missing result');
}
console.log(JSON.stringify(out));
'''

def cases():
    plain = b'"'+b'a'*(8*1024*1024)+b'"'
    escaped = b'"'+b'\\n\\u0061'*(4*1024*1024//8)+b'"'
    obj = b'{'+b','.join(b'"k%d":0'%i for i in range(100000))+b'}'
    arr = b'['+b','.join([b'0']*500000)+b']'
    # Expected summaries: status, record count / position, children / error kind.
    return [
      ('plain_8MiB',plain,['ok','1','0']),
      ('escapes_4MiB',escaped,['ok','1','0']),
      ('object_100000',obj,['ok','200001','100000']),
      ('array_500000',arr,['ok','500001','500000']),
      ('depth_128',b'['*128+b'0'+b']'*128,['ok','129','1']),
      ('depth_129',b'['*129+b'0'+b']'*129,['error','128','3']),
      ('hostile_depth_1000000',b'['*1000000,['error','128','3']),
      ('bytes_16777216',b'"'+b'a'*16777214+b'"',['ok','1','0']),
      ('bytes_16777217',b'"'+b'a'*16777215+b'"',['error','0','1']),
    ]

def save(report):
    (HERE/'measure.json').write_text(json.dumps(report,indent=2)+'\n')

def main():
    start = time.monotonic()
    report = {'method':'Wall-clock milliseconds inside host process; median of 3, no warmup; input IO, compilation and output validation excluded. text_of includes parsing and decoding. Node times JSON.parse only.',
              'platform':platform.platform(),'cases':{},'builds':{},'errors':[]}
    failed = False
    try:
        g2, flags, rustflags = setup()
        root = WORK/'q-measure'; root.mkdir(parents=True,exist_ok=True)
        inputs = cases()
        for name,data,expected in inputs:
            path = root/(name+'.json'); path.write_bytes(data)
            report['cases'][name] = {'bytes':len(data),'expected':expected,'pairs':{}}
        node = shutil.which('node')
        if not node: raise RuntimeError('Node is required for reference measurements')
        report['node_version'] = run([node,'--version']).strip()
        for name,data,expected in inputs:
            if expected[0] != 'ok': continue
            samples = json.loads(run([node,'-e',NODE,root/(name+'.json')],timeout=30))
            report['cases'][name]['node'] = {'samples_ms':samples,'median_ms':statistics.median(samples)}
        for compiler in ('py','rs'):
            for backend in ('rust','llvm'):
                pair = compiler+'/'+backend
                for batch,template in ((2,HARNESS),(3,TEXT_HARNESS)):
                    if time.monotonic()-start > 1100: raise RuntimeError('Measurement build budget exceeded')
                    work = root/f'a{batch}_{compiler}_{backend}'; work.mkdir(exist_ok=True)
                    c = g2.compile_pruv(compiler,str(HERE/f'a{batch}_root.pruv'),str(work),backend,flags)
                    report['builds'][f'{pair}/a{batch}'] = c
                    if c['rc']: raise RuntimeError(f'{pair}/a{batch} compile failed: {c}')
                    exe = build(g2,c,work,template,rustflags)
                    for name,data,expected in inputs:
                        if batch == 3 and name not in ('plain_8MiB','escapes_4MiB'): continue
                        label = name if batch == 2 else name+'_text'
                        if label not in report['cases']:
                            report['cases'][label] = {'bytes':len(data),'pairs':{}}
                        want = expected
                        if batch == 3:
                            decoded = json.loads(data)
                            want = ['text',str(len(decoded.encode())),str(sum(decoded.encode()))]
                        try:
                            lines = run([exe,root/(name+'.json')],timeout=30).splitlines()
                            if len(lines) != 3: raise RuntimeError(f'Expected 3 samples, got {lines}')
                            samples = []
                            for line in lines:
                                fields = line.split()
                                if fields[1:] != want: raise RuntimeError(f'{label}: expected {want}, got {fields[1:]}')
                                samples.append(float(fields[0]))
                            result = {'samples_ms':samples,'median_ms':statistics.median(samples),'observed':want}
                            print(f'{pair} {label}: {result["median_ms"]:.3f} ms',flush=True)
                        except Exception as exc:
                            failed = True
                            result = {'error':str(exc)}
                            report['errors'].append(f'{pair}/{label}: {exc}')
                        report['cases'][label]['pairs'][pair] = result
                        save(report)
    except Exception as exc:
        failed = True
        report['errors'].append(str(exc))
        print(str(exc),file=sys.stderr)
    report['elapsed_seconds'] = time.monotonic()-start
    save(report)
    return int(failed)

if __name__ == '__main__':
    raise SystemExit(main())
