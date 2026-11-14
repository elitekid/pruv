#!/usr/bin/env python3
"""Deterministic Q differential corpus; all generated artifacts stay in work/q."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import shutil
import struct
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.setrecursionlimit(30000)
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = HERE / 'work/q'
SEED = 20261114
ELECTRON = '/Users/spica4345/Projects/lair/node_modules/.bin/electron'
JSONL_FILES = [b'',b'0',b'0\n',b'0\r\ntrue\nnull',b'\n\r\n',
               b'0\n{bad}\ntrue\n',b'0\n{"x":',b'\xff\n0',b'0\r\r\n']
ERRORS = {b'': (0,5), b' ': (1,5), b'[1,]': (3,10), b'{"a":1,}': (7,10),
          b'01': (1,13), b'1.': (2,5), b'1e+': (3,5), b'tru': (3,5),
          b'nulx': (3,12), b'"\\x"': (2,14), b'"\\uZZZZ"': (3,15),
          b'"\x00"': (1,16), b'"x': (2,17)}

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def run(cmd, data=None, env=None, timeout=600):
    p = subprocess.run(list(map(str, cmd)), input=data, text=True, capture_output=True,
                       env=env, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f'{cmd[0]} exit {p.returncode}: {p.stderr[-6000:]}')
    return p.stdout

HARNESS = r'''#![allow(dead_code,unused_imports)]
#[path="@SOL@"] mod sol;
use std::io::{self,BufRead};
fn main() {
 for line in io::stdin().lock().lines() {
  let line=line.unwrap(); let mut p=line.split_whitespace();
  let op=p.next().unwrap(); let offset:i64=p.next().unwrap().parse().unwrap();
  let fin=p.next().unwrap()=="1"; let hex=p.next().unwrap_or("");
  let data:Vec<u8>=(0..hex.len()).step_by(2).map(|i|u8::from_str_radix(&hex[i..i+2],16).unwrap()).collect();
  let out=if op=="d" {sol::dump(&data)} else {sol::line_dump(&data,offset,fin)};
  println!("{}",out.iter().map(|v|v.to_string()).collect::<Vec<_>>().join(" "));
 }
}
'''

JS = r'''
const fs=require('fs');
const dec=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true});
function units(s){return Array.from({length:s.length},(_,i)=>s.charCodeAt(i));}
function textBytes(s){
 let t='';for(let i=0;i<s.length;i++){
  const u=s.charCodeAt(i);
  if(u>=0xd800&&u<=0xdbff&&i+1<s.length&&s.charCodeAt(i+1)>=0xdc00&&s.charCodeAt(i+1)<=0xdfff){t+=s[i]+s[++i];}
  else t+=(u>=0xd800&&u<=0xdfff)?'\ufffd':s[i];
 }return Array.from(Buffer.from(t,'utf8'));
}
function bits(n){const b=Buffer.alloc(8);b.writeDoubleBE(n);return b.toString('hex');}
function canon(v){
 if(v===null)return ['null'];
 if(typeof v==='number')return ['number',bits(v)];
 if(typeof v==='boolean')return ['bool',v];
 if(typeof v==='string')return ['string',units(v),textBytes(v)];
 if(Array.isArray(v))return ['array',v.map(canon)];
 return ['object',Object.keys(v).map(k=>[units(k),canon(v[k])]).sort((a,b)=>JSON.stringify(a[0]).localeCompare(JSON.stringify(b[0]),'en'))];
}
for(const line of fs.readFileSync(0,'utf8').trimEnd().split('\n')){
 const q=JSON.parse(line); let text;
 try{text=dec.decode(Buffer.from(q.hex,'hex'));}catch(e){console.log(JSON.stringify({accepted:false,utf8:true}));continue;}
 let v;try{v=JSON.parse(text);}catch(e){console.log(JSON.stringify({accepted:false}));continue;}
 console.log(JSON.stringify({accepted:true,value:q.policy?null:canon(v),numbers:q.tokens.map(t=>bits(JSON.parse(t)))}));
}
'''

def corpus():
    rng = random.Random(SEED)
    pool = ['', 'a', 'a\\b', '\ud800', '\udc00', '\udc00\ud800', '\ud800\ud800\udc00',
            '\ufffd', '😀', '__proto__', 'constructor', '0', '01', '\u0000\b\f\n\r\t"/\\']
    numbers = ['0','-0','-0.0','-0e0','1.0','1e0','9007199254740991','9007199254740992',
               '-9007199254740991','-9007199254740992','1e309','-1e999','1e-999','5e-324',
               '2.2250738585072014e-308','9'*400,'0.'+'1'*400,'1e'+'9'*200]
    def gen(depth):
        k = rng.randrange(7 if depth else 5)
        if k == 0: return 'null'
        if k == 1: return rng.choice(['true','false'])
        if k == 2: return rng.choice(numbers) if rng.randrange(2) else str(rng.randrange(-10**17,10**17))
        if k in (3,4): return json.dumps(rng.choice(pool))
        if k == 5: return '['+','.join(gen(depth-1) for _ in range(rng.randrange(4)))+']'
        return '{'+','.join(json.dumps(rng.choice(pool))+':'+gen(depth-1) for _ in range(rng.randrange(4)))+'}'
    cases = []
    for i in range(10000):
        b = gen(4).encode()
        if i % 3 == 0: b = b' \t'+b+b'\r\n'
        cases.append(b)
        # Byte mutations of valid documents, including guaranteed-invalid suffixes.
        at = rng.randrange(len(b)+1)
        mutation = b[:at]+rng.choice([b',',b'\xff',b'\x00',b':',b']',b'\\'])+b[at:]
        cases.append(mutation if i % 2 else b+b'!')
    fixed = [b'null',b'true',b'false',b'[]',b'{}',b'[{},[true,false,null],{"x":[]}]',
             b'{"a":0,"\\u0061":1,"a":2,"__proto__":3,"constructor":4,"":5,"0":6,"01":7}',
             '{"\\ud800":0,"�":1,"\\ufffd":2,"\\udc00":3}'.encode(),
             b'"\\\"\\\\\\/\\b\\f\\n\\r\\t\\u0000"', b'"'+b'a'*100000+b'"',
             b'"'+b'\\u0061'*20000+b'"']
    fixed += [n.encode() for n in numbers]
    fixed += [json.dumps(s).encode() for s in pool]
    for depth in (127,128,129,2048):
        fixed += [b'['*depth+b'0'+b']'*depth,b'{"a":'*depth+b'null'+b'}'*depth]
    for cp in (0x7f,0x80,0x7ff,0x800,0xd7ff,0xe000,0xffff,0x10000,0x10ffff,0xfffd,0x2028,0x2029,0xfeff):
        fixed += [json.dumps(chr(cp),ensure_ascii=a).encode() for a in (False,True)]
    for b in (b'\x80',b'\xc0\x80',b'\xc1\xbf',b'\xe0\x80\x80',b'\xed\xa0\x80',
              b'\xf0\x80\x80\x80',b'\xf4\x90\x80\x80',b'\xf5\x80\x80\x80',b'\xff',b'\xc2',b'\xe2\x82',b'\xf0\x90\x80'):
        fixed += [b,b'"'+b+b'"',b'null'+b]
    for cp in list(range(33))+[0x7f,0x85,0xa0,0x1680,*range(0x2000,0x200b),0x2028,0x2029,0x202f,0x205f,0x3000,0xfeff]:
        if cp not in (9,10,13,32): fixed.append(chr(cp).encode()+b'0')
    fixed += [b'',b' ',b'[',b'{',b'[1',b'{"a"}',b'{"a":}',b'[1 2]',b'[1,]',b'{"a":1,}',
              b'01',b'+1',b'1.',b'1e+',b'NaN',b'Infinity',b'-Infinity',b'tru',b'True',b'nulx',
              b'null false',b'[]{}',b'"\\x"',b'"\\u123"',b'"\\uZZZZ"',b'"x',b'"\x00"',b'//x',b"'x'"]
    # Record-limit rejection: no successful million-record accessor dump is required.
    fixed.append(b'['+b'0,'*1048575+b'0]')
    for data in JSONL_FILES:
        for record in data.split(b'\n'):
            fixed.append(record[:-1] if record.endswith(b'\r') else record)
    return cases+fixed, len(cases), len(fixed)

def bits(token):
    return struct.pack('>d',float(token)).hex()

def semantic(v, a4):
    if v is None: return ['null']
    if isinstance(v,bool): return ['bool',v]
    if isinstance(v,a4.Number): return ['number',bits(v)]
    if isinstance(v,a4.Pairs):
        last = {tuple(a4.units(k)): semantic(x,a4) for k,x in v}
        # Compare objects as maps in Python, independent of JS enumeration order.
        return ['object',[[list(k),x] for k,x in last.items()]]
    if isinstance(v,list): return ['array',[semantic(x,a4) for x in v]]
    return ['string',a4.units(v),list(a4.normalized(v))]

def normalize(v):
    if v[0] == 'object': return ('object',tuple(sorted((tuple(k),normalize(x)) for k,x in v[1])))
    if v[0] == 'array': return ('array',tuple(map(normalize,v[1])))
    return tuple(tuple(x) if isinstance(x,list) else x for x in v)

def oracle(data, a4):
    try:
        text = data.decode('utf-8','strict')
    except UnicodeDecodeError: return dict(accepted=False,policy='invalid_utf8')
    try:
        v = json.loads(text,strict=True,parse_int=a4.Number,parse_float=a4.Number,
                       object_pairs_hook=a4.Pairs,parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
    except ValueError: return dict(accepted=False,policy=None)
    # Resource exceptions are deliberately not swallowed as grammar rejection.
    depth = 0; maximum = 0; records = 0; stack = [(v,0)]
    while stack:
        x,d = stack.pop(); records += 1
        if isinstance(x,(list,a4.Pairs)):
            maximum = max(maximum,d+1)
            if isinstance(x,a4.Pairs):
                records += len(x); stack.extend((y,d+1) for _,y in x)
            else: stack.extend((y,d+1) for y in x)
    policy = 'depth' if maximum > 128 else 'records' if records > 1048576 else None
    if policy: return dict(accepted=True,policy=policy,tokens=[],value=None)
    tape = a4.document(data)
    # a4's tokenization retains character offsets; convert independently to bytes.
    offsets = [0]
    for c in text: offsets.append(offsets[-1]+len(c.encode()))
    expected = [len(tape)]; tokens = []; lossy = 0
    for r,n in enumerate(tape):
        k = n['kind']; s = offsets[n['start']]; e = offsets[n['end']]
        stop = r+1
        while stop < len(tape) and tape[stop]['start'] < n['end']: stop += 1
        count = len(n['children']) if k in (5,6) else 0
        expected += [k,s,e,stop,n['parent'],count,k if k != 7 else 4,0 if k == 7 else s,e-s if k == 7 else e]
        assert data[s:e] == n['raw']
        if k in (4,7):
            u = a4.units(n['value']); t = a4.normalized(n['value'])
            lossy += int(a4.units(t.decode('utf-8')) != u)
            expected += [len(u),*u,len(t),*t]
            if k == 7:
                parent = tape[n['parent']]
                matches = [val['id'] for key,val in parent['children'] if a4.units(key['value']) == u]
                expected += [matches[-1]]
        if k == 3:
            token = n['value']; tokens.append(token)
            exact = bool(re.fullmatch('-?[0-9]+',token)) and len(token.lstrip('-')) <= 16 and abs(int(token)) <= 9007199254740991
            expected += [s,e,int(exact),int(token) if exact else 0,int(token == '-0')]
        if k in (1,2): expected += [int(n['value'])]
        if k == 5: expected += [count,*[x['id'] for x in n['children']]]
    return dict(accepted=True,policy=None,tokens=tokens,value=semantic(v,a4),dump=expected,lossy_text_views=lossy)

def main():
    started = time.monotonic(); WORK.mkdir(parents=True,exist_ok=True)
    result = dict(seed=SEED,pairs={},failures=[],versions={},status='failed')
    def save():
        result['wall_seconds'] = round(time.monotonic()-started,3)
        (HERE/'q_results.json').write_text(json.dumps(result,ensure_ascii=True,indent=2)+'\n')
    try:
        a4 = load('q_a4',HERE/'run_a4.py'); a4.a3.WORK = WORK
        g2 = a4.a3.configure()
        l0 = load('q_l0',ROOT/'bench/l0/run.py')
        result['versions'] = dict(python=sys.version,node=run(['node','--version']).strip(),
            electron=json.loads(run([ELECTRON,'-p','JSON.stringify(process.versions)'],env=dict(os.environ,ELECTRON_RUN_AS_NODE='1'))),
            rustc=run([g2.RUSTC,'--version']).strip(),
            compiler_commands={k:list(map(str,v)) for k,v in g2.COMPILERS.items()},
            rust_source_sha256=l0.source_digest(ROOT/'pruvc-rs'),
            rust_binary_sha256=hashlib.sha256(Path(g2.COMPILERS['rs'][0]).read_bytes()).hexdigest(),
            python_source_sha256=hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT/'pruvc').rglob('*.py')))).hexdigest())
        cases,generated,fixed = corpus(); result.update(generated=generated,fixed=fixed)
        print(f'seed={SEED}; generated={generated}; fixed={fixed}',flush=True)
        expected = [oracle(d,a4) for d in cases]
        jsfile = WORK/'baseline.js'; jsfile.write_text(JS)
        payload = ''.join(json.dumps(dict(hex=d.hex(),policy=e.get('policy'),tokens=e.get('tokens',[])))+'\n' for d,e in zip(cases,expected))
        for runtime,cmd,env in [('node',['node',jsfile],None),('electron',[ELECTRON,jsfile],dict(os.environ,ELECTRON_RUN_AS_NODE='1'))]:
            got = list(map(json.loads,run(cmd,payload,env=env).splitlines()))
            if len(got) != len(cases): raise RuntimeError(runtime+' response count')
            bad = []
            for i,(g,e) in enumerate(zip(got,expected)):
                if g['accepted'] != e['accepted'] or (e['accepted'] and not e['policy'] and
                    (normalize(g['value']) != normalize(e['value']) or g['numbers'] != list(map(bits,e['tokens'])))):
                    bad.append(i)
            result[runtime] = dict(cases=len(got),mismatches=len(bad))
            for i in sorted(bad,key=lambda i:len(cases[i]))[:10]:
                result['failures'].append(dict(runtime=runtime,input_hex=cases[i].hex(),reason='native/Python differential'))
            print(f'{runtime}: {len(got)} cases; mismatches={len(bad)}',flush=True)
        target = WORK/'str-adapter'
        run([shutil.which('cargo') or str(Path.home()/'.cargo/bin/cargo'),'build','--release','--offline','--quiet',
             '--manifest-path',HERE/'str_adapter/Cargo.toml','--target-dir',target])
        rlib = target/'release/libpruv_str.rlib'; deps = target/'release/deps'
        flags = ['--rust-extern',f'pruv_str={rlib}','--rust-search',str(deps)]
        rustflags = ['--extern',f'pruv_str={rlib}','-L',f'dependency={deps}']
        # JSONL calls include terminal Done/NeedMore, and independently parse each range.
        linecases = []
        for data in JSONL_FILES:
            for final in (False,True):
                offset = 0
                while True:
                    lf = data.find(b'\n',offset)
                    if lf < 0 and (not final or offset == len(data)):
                        linecases.append((data,offset,final,None,[-1,offset,0 if final else 1])); break
                    end = lf if lf >= 0 else len(data); nxt = end+1 if lf >= 0 else end
                    if lf >= 0 and end > offset and data[end-1] == 13: end -= 1
                    linecases.append((data,offset,final,oracle(data[offset:end],a4),[offset,end,nxt]))
                    offset = nxt
        result['jsonl_steps'] = len(linecases)
        payload = ''.join(f'd 0 1 {d.hex()}\n' for d in cases)
        payload += ''.join(f'l {o} {int(f)} {d.hex()}\n' for d,o,f,e,h in linecases)
        for compiler in ('py','rs'):
            for backend in ('rust','llvm'):
                name = f'{compiler}/{backend}'; stats = dict(cases=0,accepted=0,rejected=0,policy_differences={},lossy_text_views=0,mismatches=0)
                result['pairs'][name] = stats
                try:
                    work = WORK/f'{compiler}_{backend}'; work.mkdir(exist_ok=True)
                    c = g2.compile_pruv(compiler,str(HERE/'q_root.pruv'),str(work),backend,flags)
                    if c['rc'] != 0: raise RuntimeError('compile/verify: '+str(c['errors'] or c['stderr']))
                    stats['verified'] = True; print(name+': verified',flush=True)
                    extra = []
                    if c['ll']:
                        extra,error = g2.build_llvm_objects(c['ll'],'json',str(work))
                        if error: raise RuntimeError(error)
                    harness = work/'main.rs'; harness.write_text(HARNESS.replace('@SOL@',c['rs']))
                    exe = work/'runner'; run([g2.RUSTC,'-O','--edition','2021',harness,'-o',exe]+extra+rustflags)
                    rows = run([exe],payload).splitlines()
                    if len(rows) != len(cases)+len(linecases): raise RuntimeError('response count mismatch')
                    bad = []
                    def check(g,e):
                        if g[:1] == [-1]:
                            if len(g) != 3 or g[2] == 18: return False
                            if not 0 <= g[1]: return False
                            if e['accepted']: return e['policy'] in ('depth','records') and g[2] == (3 if e['policy']=='depth' else 2)
                            return True
                        return e['accepted'] and not e['policy'] and g == e['dump']
                    for i,(row,e) in enumerate(zip(rows,expected)):
                        g = list(map(int,row.split())); stats['cases'] += 1
                        stats['lossy_text_views'] += e.get('lossy_text_views',0)
                        stats['rejected' if g[:1] == [-1] else 'accepted'] += 1
                        if g[:1] == [-1] and (len(g)!=3 or g[1] > len(cases[i])): bad.append(i); continue
                        if cases[i] in ERRORS and g != [-1,*ERRORS[cases[i]]]: bad.append(i)
                        elif not check(g,e): bad.append(i)
                        elif e['policy']:
                            p = e['policy']; stats['policy_differences'][p] = stats['policy_differences'].get(p,0)+1
                    stats['mismatches'] = len(bad)
                    # Save the shortest counterexample for each distinct observed failure.
                    for i in sorted(bad,key=lambda i:len(cases[i]))[:10]:
                        result['failures'].append(dict(pair=name,input_hex=cases[i].hex(),input_repr=repr(cases[i]),
                            got=rows[i][:2000],expected=str(expected[i].get('dump',expected[i]))[:2000]))
                    for row,(d,o,f,e,h) in zip(rows[len(cases):],linecases):
                        g = list(map(int,row.split()))
                        if (e is None and g != h) or (e is not None and (g[:3] != h or not check(g[3:],e))):
                            result['failures'].append(dict(pair=name,jsonl_hex=d.hex(),offset=o,final=f,got=g)); stats['mismatches'] += 1
                    print(f'{name}: {stats}',flush=True)
                except Exception as exc:
                    stats['error'] = str(exc); result['failures'].append(dict(pair=name,error=str(exc)))
                    print(name+': '+str(exc),flush=True)
                save()
        result['status'] = 'failed' if result['failures'] else 'passed'
    except Exception as exc:
        result['failures'].append(dict(harness_error=repr(exc)))
        print(repr(exc),file=sys.stderr,flush=True)
    save()
    print(f"status={result['status']}; wall={result['wall_seconds']}s; results=q_results.json",flush=True)
    return int(result['status'] != 'passed')

if __name__ == '__main__':
    raise SystemExit(main())
