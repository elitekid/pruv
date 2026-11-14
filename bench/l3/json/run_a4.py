#!/usr/bin/env python3
"""A4 accessor verification and deterministic independent oracle cross-check."""
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import shutil
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = HERE / 'work/a4'
spec = importlib.util.spec_from_file_location('a3', HERE / 'run_a3.py')
a3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a3)
run = a3.run
nums = a3.nums

HARNESS = r'''#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead};
fn ints(s: &str) -> Vec<i64> { s.split_whitespace().map(|v| v.parse().unwrap()).collect() }
fn main() {
 for line in io::stdin().lock().lines() {
  let line = line.unwrap(); let p: Vec<_> = line.split('|').collect();
  let data: Vec<u8> = ints(p[0]).iter().map(|x| *x as u8).collect();
  let ops = ints(p[1]); let key = ints(p[2]);
  let bytes: Vec<u8> = ints(p[3]).iter().map(|x| *x as u8).collect();
  let text = std::str::from_utf8(&bytes).unwrap();
  let out = sol::query(&data, &ops, &key, text, p[4].parse().unwrap());
  println!("{}", out.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(" "));
 }
}
'''

class Number(str):
    pass

class Pairs(list):
    pass

def units(s):
    b = s.encode('utf-16-le', 'surrogatepass')
    return [b[i] + 256*b[i+1] for i in range(0, len(b), 2)]

def normalized(s):
    u = units(s)
    out = []
    i = 0
    while i < len(u):
        v = u[i]
        if 0xD800 <= v <= 0xDBFF and i+1 < len(u) and 0xDC00 <= u[i+1] <= 0xDFFF:
            out.append(chr(0x10000 + (v-0xD800)*1024 + u[i+1]-0xDC00)); i += 2
        else:
            out.append(chr(0xFFFD if 0xD800 <= v <= 0xDFFF else v)); i += 1
    return ''.join(out).encode()

def document(data):
    text = data.decode('utf-8', 'strict')
    value = json.loads(text, strict=True, parse_int=Number, parse_float=Number,
                       object_pairs_hook=Pairs,
                       parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))
    # Token offsets are only for raw-span and tape-ID expectations. json.loads
    # supplies all semantic values, duplicate pairs, and decoded key strings.
    tokens = list(re.finditer(r'"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|true|false|null|[\[\]{},:]', text))
    cursor = 0
    tape = []
    def take():
        nonlocal cursor
        t = tokens[cursor]; cursor += 1; return t
    def build(v, parent=-1, key=False):
        t = take()
        k = 7 if key else (0 if v is None else 2 if v is True else 1 if v is False else
            3 if isinstance(v, Number) else 6 if isinstance(v, Pairs) else 5 if isinstance(v, list) else 4)
        n = dict(id=len(tape), kind=k, value=v, parent=parent, children=[], start=t.start(), end=t.end())
        tape.append(n)
        if k == 5:
            for i, child in enumerate(v):
                if i: assert take().group() == ','
                n['children'].append(build(child, n['id']))
            n['end'] = take().end()
        if k == 6:
            for i, (name, child) in enumerate(v):
                if i: assert take().group() == ','
                kn = build(name, n['id'], True)
                assert take().group() == ':'
                n['children'].append((kn, build(child, n['id'])))
            n['end'] = take().end()
        n['raw'] = text[n['start']:n['end']].encode()
        return n
    build(value)
    assert cursor == len(tokens)
    return tape

def answer(tape, ops, key, text, mode):
    ident = 0
    for op, arg in zip(ops[::2], ops[1::2]):
        if op == 0:
            ident = arg; continue
        if ident < 0 or ident >= len(tape) or tape[ident]['kind'] == 7: return [-3]
        n = tape[ident]
        if op == 1:
            if n['kind'] != 5: return [-2]
            if arg < 0 or arg >= len(n['children']): return [-1]
            ident = n['children'][arg]['id']
        else:
            if n['kind'] != 6: return [-2]
            wanted = key if op == 2 else units(text)
            matches = [v['id'] for k, v in n['children'] if units(k['value']) == wanted]
            if not matches: return [-1]
            ident = matches[-1]
    if ident < 0 or ident >= len(tape) or tape[ident]['kind'] == 7: return [-3]
    n = tape[ident]; k = n['kind']; v = n['value']
    if mode == 0: return [k]
    if mode == 1: return list(n['raw'])
    if mode == 2: return [len(v)] if k == 5 else [-2]
    if mode == 3: return [int(v)] if k in (1, 2) else [-2]
    if mode == 4:
        if k != 3: return [-2]
        exact = bool(re.fullmatch('-?[0-9]+', v)) and len(v.lstrip('-')) <= 16 and abs(int(v)) <= 9007199254740991
        return [0, int(exact), int(v) if exact else 0, int(v == '-0')] + list(n['raw'])
    if k != 4: return [-2]
    return units(v) if mode == 5 else list(normalized(v))

def fixtures():
    cases = []
    def add(data, ops, key=(), text='', mode=0, tape=None):
        tape = tape if tape is not None else document(data)
        cases.append((data, ops, list(key), text, mode, answer(tape, ops, key, text, mode)))
    fixed = [b'null', b'true', b'false', b'[]', b'{}', b'[null,[1,[2,3]],{},false,"x"]',
             b'{"a":null,"a":1,"\\u0061":[2],"__proto__":3,"constructor":4,"":5,"01":6}',
             '{"\\uD800":1,"�":2,"\\ufffd":3,"😀":4,"\\ud83d\\ude00":5}'.encode(),
             b'"\\uD800a\\uDC00\\uD83D\\uDE00\\n\\u0000"', b'""',
             b'{"a":[{"a":false},null],"b":{"a":true}}']
    fixed += [x.encode() for x in ['0','-0','-0.0','1.0','1e0','-1','9007199254740991',
              '-9007199254740991','9007199254740992','-9007199254740992','9'*200,'-'+'9'*200]]
    for data in fixed:
        tape = document(data)
        for ident in [-1, len(tape), 9223372036854775807] + list(range(len(tape))):
            for mode in range(7): add(data, [0, ident], mode=mode, tape=tape)
            for index in [-1,0,1,4,20]: add(data,[0,ident,1,index],tape=tape)
            for key in ['', 'a', '__proto__', 'constructor', '01', '😀', '�', '\ud800', 'missing']:
                add(data,[0,ident,2,0],key=units(key),tape=tape)
                if not any(0xD800 <= ord(c) <= 0xDFFF for c in key):
                    add(data,[0,ident,3,0],text=key,tape=tape)
    rng = random.Random(404)
    pool = ['', 'a', '😀', '�', '\ud800', '__proto__', 'constructor', '01', 'a\\b']
    def generate(depth):
        t = rng.randrange(7 if depth else 5)
        if t == 0: return 'null'
        if t == 1: return rng.choice(['true','false'])
        if t == 2: return rng.choice(['-0','1.0','1e0',str(rng.randrange(-10**16,10**16))])
        if t in (3,4): return json.dumps(rng.choice(pool))
        if t == 5: return '['+','.join(generate(depth-1) for _ in range(rng.randrange(5)))+']'
        return '{'+','.join(json.dumps(rng.choice(pool))+':'+generate(depth-1) for _ in range(rng.randrange(5)))+'}'
    for _ in range(400):
        data = generate(4).encode(); tape = document(data)
        for _ in range(6):
            n = tape[0]; ops = []; key = []; text = ''
            for _ in range(rng.randrange(1,6)):
                if n['kind'] == 5:
                    idx = rng.randrange(-1,len(n['children'])+1); ops += [1,idx]
                    if idx < 0 or idx >= len(n['children']): break
                    n = n['children'][idx]
                elif n['kind'] == 6:
                    # Use one lookup key per query; later steps can still index arrays.
                    candidates = [k['value'] for k,v in n['children']]+['missing']
                    text = rng.choice(candidates); key = units(text); ops += [2,0]
                    matches = [v for k,v in n['children'] if units(k['value']) == key]
                    if matches: n = matches[-1]
                    break
                else:
                    if rng.randrange(2): ops += [1,0]
                    break
            add(data,ops,key,text if not any(0xD800 <= ord(c) <= 0xDFFF for c in text) else '',rng.randrange(7),tape)
    return cases

def main():
    WORK.mkdir(parents=True, exist_ok=True)
    a3.WORK = WORK
    g2 = a3.configure()
    target = WORK/'str-adapter'
    run([shutil.which('cargo') or str(Path.home()/'.cargo/bin/cargo'), 'build','--release','--offline','--quiet',
         '--manifest-path',HERE/'str_adapter/Cargo.toml','--target-dir',target])
    rlib, deps = target/'release/libpruv_str.rlib', target/'release/deps'
    flags = ['--rust-extern',f'pruv_str={rlib}','--rust-search',str(deps)]
    rustflags = ['--extern',f'pruv_str={rlib}','-L',f'dependency={deps}']
    cases = fixtures()
    payload = ''.join('|'.join([nums(d),nums(o),nums(k),nums(t.encode()),str(m)])+'\n' for d,o,k,t,m,w in cases)
    expected = [nums(c[-1]) for c in cases]
    failed = False
    print(f'seed=404; random documents=400; fixtures={len(cases)}',flush=True)
    for compiler in ('py','rs'):
        for backend in ('rust','llvm'):
            name = f'{compiler}/{backend}'
            try:
                work = WORK/f'{compiler}_{backend}'; work.mkdir(exist_ok=True)
                c = g2.compile_pruv(compiler,str(HERE/'a4_root.pruv'),str(work),backend,flags)
                if c['rc'] != 0: raise RuntimeError('compile/verify failed: '+str(c['errors'] or c['stderr']))
                print(f'{name}: A4 verified and compiled',flush=True)
                extra = []
                if c['ll']:
                    extra,error = g2.build_llvm_objects(c['ll'],'json',str(work))
                    if error: raise RuntimeError(error)
                harness = work/'main.rs'; harness.write_text(HARNESS.replace('@SOL@',c['rs']))
                exe = work/'runner'
                run([g2.RUSTC,'-O','--edition','2021',harness,'-o',exe]+extra+rustflags)
                got = run([exe],payload).splitlines()
                if len(got) != len(expected): raise RuntimeError(f'{len(got)} answers for {len(expected)} fixtures')
                bad = [i for i,(a,b) in enumerate(zip(expected,got)) if a != b]
                for i in bad[:5]: print(f'{name}: mismatch {i}: {cases[i]!r}; got={got[i]!r}')
                if bad: (work/'failure.json').write_text(json.dumps({'case':repr(cases[bad[0]]),'got':got[bad[0]]}))
                failed |= bool(bad)
                print(f'{name}: {len(cases)-len(bad)}/{len(cases)} fixtures passing',flush=True)
            except Exception as exc:
                failed = True; print(f'{name}: ERROR {exc}',file=sys.stderr,flush=True)
    return int(failed)

if __name__ == '__main__':
    raise SystemExit(main())
