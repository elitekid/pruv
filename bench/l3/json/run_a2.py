#!/usr/bin/env python3
"""A2 parser fixtures: both compilers and backends; --verify-only skips host fixtures."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = HERE / 'work'


HARNESS = r'''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead};
fn main() {
 for line in io::stdin().lock().lines() {
  let line = line.unwrap();
  if line.starts_with("limit ") {
   let children: usize = line[6..].parse().unwrap();
   let mut data = Vec::new(); data.push(b'[');
   for i in 0..children { if i > 0 { data.push(b','); } data.push(b'0'); }
   data.push(b']');
   let out = sol::parse_tape(&data);
   if children == 1048575 {
    assert_eq!(out.len(),6*(children+1));
    assert_eq!(&out[..6], &[5,0,data.len() as i64,(children+1) as i64,-1,children as i64]);
    for r in 1..=children {
     assert_eq!(&out[6*r..6*r+6], &[3,(2*r-1) as i64,(2*r) as i64,(r+1) as i64,0,0]);
    }
   } else { assert_eq!(out,vec![-1,2097151,2]); }
   println!("limit-ok"); continue;
  }
  let data: Vec<u8> = line.split_whitespace().map(|x| x.parse().unwrap()).collect();
  println!("{}",sol::parse_tape(&data).iter().map(|x| x.to_string()).collect::<Vec<_>>().join(" "));
 }
}
'''
# Independent recursive oracle, with Python's decoder for scalar boundaries.
import json
def expected_tape(data):
 text = data.decode('utf-8')
 decoder = json.JSONDecoder()
 out = []
 def ws(p):
  while p < len(text) and text[p] in ' \t\r\n': p += 1
  return p
 def byte(p): return len(text[:p].encode('utf-8'))
 def value(p,parent,key=False):
  p = ws(p); r = len(out)//6; c = text[p]
  kind = 7 if key else {'[':5,'{':6,'"':4,'t':2,'f':1,'n':0}.get(c,3)
  out.extend([kind,byte(p),0,0,parent,0])
  if c in '[{':
   close = ']' if c == '[' else '}'
   q = ws(p+1); count = 0
   while text[q] != close:
    if c == '{':
     q = ws(value(q,r,True)); assert text[q] == ':'; q += 1
    q = ws(value(q,r)); count += 1
    if text[q] == close: break
    assert text[q] == ','; q = ws(q+1)
   end = q+1; out[6*r+5] = count
  else: _,end = decoder.raw_decode(text,p)
  out[6*r+2] = byte(end); out[6*r+3] = len(out)//6
  return end
 assert ws(value(0,-1)) == len(text)
 return out
FIXTURES = []
def valid(data): FIXTURES.append((repr(data[:60]),data,expected_tape(data)))
def bad(data,pos,kind): FIXTURES.append((repr(data[:60]),data,[-1,pos,kind]))
for token in [b'null',b'true',b'false',b'0',b'-0',b'12',b'1.5',b'1e999',b'-1E-99',
 b'""',b'"hello"',b'"\\uD800"',b'"\\uDC00"',b'"\\uD800\\uDC00"',b'"\\u0000"',
 b'"\\\\"',b'"\\/\\b\\f\\n\\r\\t"', '"😀\u2028\u2029"'.encode()]:
 valid(token); valid(b' \t'+token+b'\r\n')
for data in [b'[]',b'{}',b'[ ]',b'{ }',b'[0]',b'{"a":1}',b'[true,false,null,0,"x"]',
 b'[[[]]]',b'{"a":{"b":[]}}',b'[{},[1,2],{"x":false}]',b'{"a":1,"a":2}',
 b'{"__proto__":0}',b'{"":null,"constructor":1}',b'{"a":1,"\\u0061":2}',
 b'{"a":[0,{"b":[true]}],"c":{}}']: valid(data)
for data,pos,kind in [
 (b'',0,5),(b' \t',2,5),(b'[',1,5),(b'{',1,5),(b'[0',2,5),
 (b'{"a"',4,5),(b'{"a":',5,5),(b'{"a":0',6,5),(b'[0,',3,5),
 (b'{"a":0,',7,5),(b'[}',1,6),(b'{]',1,7),
 (b'[1,]',3,10),(b'{"a":1,}',7,10),(b'[1, \n]',5,10),(b'{"a":1, \t}',9,10),
 (b'{"a" 0}',5,8),(b'{"a",0}',4,8),(b'{1:0}',1,7),(b'{true:0}',1,7),
 (b'{a:0}',1,7),(b"{'a':0}",1,7),(b'[1 2]',3,9),(b'{"a":0 "b":1}',7,9),
 (b'[1}',2,9),(b'{"a":0]',6,9),(b'[1,,2]',3,6),(b'{"a":,}',5,6),
 (b'{"a":}',5,6),(b'[,]',1,6),(b'{,}',1,7),(b'truex',4,11),(b'1x',1,11),
 (b'[truex]',5,9),(b'[1x]',2,9),(b'null false',5,11),(b'[]{}',2,11),
 (b'0\x0b',1,11),(b'\xef\xbb\xbfnull',0,6),(b'NaN',0,6),(b'Infinity',0,6),
 (b'+1',0,6),(b'01',1,13),(b'-',1,5),(b'1.',2,5),(b'1e+',3,5),
 (b'1.x',2,13),(b'trux',3,12),(b'tru',3,5),(b'"x',2,17),(b'"\\x"',2,14),
 (b'"\\uG000"',3,15),(b'"\x01"',1,16),(b'?\xff',1,4),(b'[}\xc0\x80',2,4),
 (b'\xff?',0,4)]: bad(data,pos,kind)
for depth in (127,128): valid(b'['*depth+b'0'+b']'*depth)
bad(b'['*129+b'0'+b']'*129,128,3)
valid(b'{"x":'*128+b'0'+b'}'*128)
bad(b'{"x":'*129+b'0'+b'}'*129,640,3)
def configure():
    WORK.mkdir(exist_ok=True)
    os.environ['TMPDIR'] = str(WORK)
    spec = importlib.util.spec_from_file_location('g2', ROOT / 'bench/g2/run.py')
    g2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g2)
    main = ROOT  # a worktree can read the main checkout's installed tools
    git = ROOT / '.git'
    if git.is_file() and git.read_text().startswith('gitdir: '):
        main = Path(git.read_text().strip()[8:]).resolve().parents[2]
    py = os.environ.get('PRUV_PYTHON') or next(
        (str(p) for p in [ROOT / '.venv/bin/python', main / '.venv/bin/python'] if p.exists()), sys.executable)
    binary = Path(os.environ.get('PRUVC_RS', ROOT / 'pruvc-rs/target/release/pruvc'))
    if not binary.exists():
        binary = main / 'pruvc-rs/target/release/pruvc'
    if not binary.exists():
        raise RuntimeError('pruvc-rs binary not found; build it or set PRUVC_RS')
    g2.COMPILERS = {'py': [py, str(ROOT / 'pruvc/pruvc.py')], 'rs': [str(binary)]}
    return g2


def run(cmd, data=None):
    p = subprocess.run([str(x) for x in cmd], input=data, text=True, capture_output=True, timeout=600)
    if p.returncode:
        raise RuntimeError(f'{cmd}: exit {p.returncode}\n{p.stdout}\n{p.stderr}')
    return p.stdout



def main():
 ap = argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--verify-only', action='store_true')
 args = ap.parse_args()
 g2 = configure()
 payload = ''.join(' '.join(map(str,data))+'\n' for _,data,_ in FIXTURES)
 payload += 'limit 1048575\nlimit 1048576\n'
 expected = [' '.join(map(str,want)) for _,_,want in FIXTURES]+['limit-ok']*2
 failed = False
 for compiler in ('py','rs'):
  for backend in ('rust','llvm'):
   key = f'{compiler}/{backend}'
   try:
    work = WORK / f'a2_{compiler}_{backend}'; work.mkdir(exist_ok=True)
    compiled = g2.compile_pruv(compiler,str(HERE/'a2_root.pruv'),str(work),backend)
    if compiled['rc'] != 0:
     raise RuntimeError('compile/verify failed: '+str(compiled['errors'] or compiled['stderr']))
    print(f'{key}: A2 verified and compiled (rc 0)',flush=True)
    if args.verify_only: continue
    harness = work/'main.rs'; harness.write_text(HARNESS.replace('@SOL@',compiled['rs']))
    extra = []
    if compiled['ll']:
     extra,error = g2.build_llvm_objects(compiled['ll'],'json',str(work))
     if error: raise RuntimeError(error)
    exe = work/'runner'
    run([g2.RUSTC,'-O','--edition','2021',harness,'-o',exe]+extra)
    got = run([exe],payload).splitlines()
    if len(got) != len(expected): raise RuntimeError(f'{len(got)} answers for {len(expected)} fixtures')
    bads = [(i,w,g) for i,(w,g) in enumerate(zip(expected,got)) if w != g]
    for i,w,g in bads: print(f'{key}: MISMATCH fixture {i}: expected {w[:300]}, got {g[:300]}')
    failed |= bool(bads)
    print(f'{key}: {len(expected)-len(bads)}/{len(expected)} fixtures as expected (includes exact record limit and one over)',flush=True)
   except Exception as exc:
    failed = True
    print(f'{key}: ERROR {exc}',file=sys.stderr,flush=True)
 print('InputTooLarge fixture skipped (16 MiB); depth 128/129 and record 1048576/1048577 included.')
 return int(failed)
if __name__ == '__main__':
 raise SystemExit(main())

