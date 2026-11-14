#!/usr/bin/env python3
"""Q targeted source mutations; originals are never changed."""
import sys
sys.dont_write_bytecode = True
import collections
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
WORK = HERE / 'work'
MODULES = ('json', 'lex', 'parse', 'jstr', 'access', 'lines')

def run(cmd, data=None, timeout=180):
    p = subprocess.run(list(map(str, cmd)), input=data, text=True, capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f'{cmd}: exit {p.returncode}\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}')
    return p.stdout

def setup():
    a3 = importlib.import_module('run_a3')
    g2 = a3.configure()
    target = WORK / 'q-str-adapter'
    run([shutil.which('cargo') or Path.home()/'.cargo/bin/cargo', 'build', '--release', '--offline',
         '--quiet', '--manifest-path', HERE/'str_adapter/Cargo.toml', '--target-dir', target])
    rlib, deps = target/'release/libpruv_str.rlib', target/'release/deps'
    return g2, ['--rust-extern', f'pruv_str={rlib}', '--rust-search', str(deps)], ['--extern', f'pruv_str={rlib}', '-L', f'dependency={deps}']

def build(g2, c, work, template, rustflags):
    extra = []
    if c['ll']:
        extra, error = g2.build_llvm_objects(c['ll'], 'json', str(work))
        if error: raise RuntimeError(error)
    harness = work/'main.rs'
    harness.write_text(template.replace('@SOL@', c['rs']))
    exe = work/'runner'
    run([g2.RUSTC, '-O', '--edition', '2021', harness, '-o', exe] + extra + rustflags)
    return exe

def fixtures(batch):
    a = importlib.import_module(f'run_a{batch}')
    nums = lambda v: ' '.join(map(str, v))
    if batch == 0:
        names = [c[0] for c in a.FIXTURES]
        payload = ''.join(f'{n} {nums(t)}\n' for _,_,n,t in a.FIXTURES)
        expected = [str(w).lower() for _,w,_,_ in a.FIXTURES]
    elif batch == 1:
        names = [c[0] for c in a.FIXTURES]
        payload = ''.join(f'{op} {lo} {hi} {nums(d)}\n' for _,op,d,lo,hi,_ in a.FIXTURES)
        expected = [str(c[-1]) for c in a.FIXTURES]
    elif batch == 2:
        names = [c[0] for c in a.FIXTURES] + ['record limit exact', 'record limit plus one']
        payload = ''.join(nums(d)+'\n' for _,d,_ in a.FIXTURES) + 'limit 1048575\nlimit 1048576\n'
        expected = [nums(w) for _,_,w in a.FIXTURES] + ['limit-ok']*2
    elif batch == 3:
        cases = a.fixtures()
        names = [repr(d[:80]) for _,d,_ in cases]
        payload = ''.join(op+':'+nums(d)+'\n' for op,d,_ in cases)
        expected = [w for _,_,w in cases]
    elif batch == 4:
        cases = a.fixtures()
        names = [repr(c[:5])[:200] for c in cases]
        payload = ''.join('|'.join([nums(d),nums(o),nums(k),nums(t.encode()),str(m)])+'\n' for d,o,k,t,m,w in cases)
        expected = [nums(c[-1]) for c in cases]
    else:
        cases = a.fixtures()
        names = [repr(c[:-1])[:200] for c in cases]
        payload = ''.join(nums((op,x,y,z,*d))+'\n' for op,x,y,z,d,_ in cases)
        expected = [nums(c[-1]) for c in cases]
    return a.HARNESS, payload, expected, names

# Only executable source is changed; proof contracts remain intact.
MUTANTS = [
 ('json','depth_constant',0,'Depth 128 to 129','{ return 128; }','{ return 129; }'),
 ('json','record_constant',0,'Record cap plus one','{ return 1048576; }','{ return 1048577; }'),
 ('json','span_empty',0,'Allow empty source spans','s >= e || e > input_length','s > e || e > input_length'),
 ('json','skip_equal',0,'Allow skip equal to record','sk <= r || sk > m','sk < r || sk > m'),
 ('lex','leading_zero',1,'Accept a leading zero','if b >= 48 && b <= 57 { return outcome(i, 13); }','if b >= 48 && b <= 57 { return outcome(i + 1, 0); }'),
 ('lex','control_bound',1,'Allow raw U+001F','if c < 32 { return outcome(i, 16); }','if c < 31 { return outcome(i, 16); }'),
 ('lex','wrong_escape_kind',1,'Wrong escape error kind','return outcome(i, 14);','return outcome(i, 15);'),
 ('lex','wrong_literal_position',1,'Wrong literal error position','return outcome(i, 12);','return outcome(pos, 12);'),
 ('lex','utf8_comparison',1,'Reject valid UTF-8 boundary','if c == 237 && b >= 160','if c == 237 && b >= 159'),
 ('parse','trailing_comma',2,'Accept trailing commas','if matches && (state == 1 || state == 4) { return done(p, 10, records); }','if matches && (state == 1 || state == 4) { return done(p + 1, 0, records); }'),
 ('parse','record_bound',2,'Reject one record too early','if records == 1048576 {','if records == 1048575 {'),
 ('parse','depth_bound',2,'Move primary depth guard to 129','&& depth == 128 {','&& depth == 129 {'),
 ('parse','skip_not_advanced',2,'Do not advance scalar skip','tape[b + 3] = r + 1;','tape[b + 3] = r;'),
 ('parse','wrong_colon_kind',2,'Wrong missing-colon error','if c != 58 { return done(p, 8, records); }','if c != 58 { return done(p, 9, records); }'),
 ('jstr','surrogate_combine',3,'Drop surrogate-pair combine','v = 65536 + (v - 55296) * 1024 + low - 56320; n = 2;','v = 65533; n = 2;'),
 ('jstr','replacement_bytes',3,'Wrong replacement scalar / UTF-8 bytes','if 55296 <= v && v <= 57343 { v = 65533; }','if 55296 <= v && v <= 57343 { v = 65532; }'),
 ('jstr','newline_decode',3,'Decode newline as CR','if e == 110 { v = 10; }','if e == 110 { v = 13; }'),
 ('jstr','hex_digit',3,'Wrong lowercase hex value','return c - 87;','return c - 86;'),
 ('access','first_wins',4,'First duplicate wins','if equal(units, key) { found = v; }','if equal(units, key) && found == -1 { found = v; }'),
 ('access','safe_integer',4,'2^53 boundary off by one','if v > (9007199254740991 - d) / 10','if v > (9007199254740992 - d) / 10'),
 ('access','negative_zero',4,'Wrong negative-zero flag','let nz: bool = neg &&','let nz: bool = !neg &&'),
 ('access','array_index',4,'Wrong array index comparison','if n == index { return j; }','if n + 1 == index { return j; }'),
 ('lines','cr_included',5,'Keep CR in physical line','end = i - 1;','end = i;'),
 ('lines','lf_included',5,'Keep LF in physical line','JsonlStep::Line(offset, end, i + 1)','JsonlStep::Line(offset, i + 1, i + 1)'),
 ('lines','next_not_advanced',5,'Do not advance next past LF','JsonlStep::Line(offset, end, i + 1)','JsonlStep::Line(offset, end, i)'),
]

def write_report(report):
    report['counts'] = dict(collections.Counter(m['classification'] for m in report['mutants']))
    (HERE/'mutants.json').write_text(json.dumps(report, indent=2)+'\n')

def main():
    start = time.monotonic()
    report = {'mutants': [], 'errors': [], 'policy': 'Infrastructure failures are errors, never proof-rejected.'}
    try:
        g2, flags, rustflags = setup()
        cache = {}
        for batch in range(6):
            cache[batch] = fixtures(batch)
            work = WORK/'mutants'/f'baseline_a{batch}'; work.mkdir(parents=True, exist_ok=True)
            c = g2.compile_pruv('rs', str(HERE/f'a{batch}_root.pruv'), str(work), 'rust', flags)
            if c['rc']: raise RuntimeError(f'baseline A{batch}: {c}')
            exe = build(g2, c, work, cache[batch][0], rustflags)
            if run([exe], cache[batch][1]).splitlines() != cache[batch][2]:
                raise RuntimeError(f'baseline A{batch} fixtures differ')
            print(f'기준 A{batch}: 통과', flush=True)
        for module,name,batch,description,old,new in MUTANTS:
            work = WORK/'mutants'/name; work.mkdir(parents=True, exist_ok=True)
            for m in MODULES: shutil.copyfile(HERE/f'{m}.pruv', work/f'{m}.pruv')
            for b in range(6): shutil.copyfile(HERE/f'a{b}_root.pruv', work/f'a{b}_root.pruv')
            path = work/f'{module}.pruv'; text = path.read_text()
            if text.count(old) != 1: raise RuntimeError(f'{name}: replacement occurs {text.count(old)} times, expected exactly one')
            path.write_text(text.replace(old,new,1))
            entry = {'name':name,'module':module+'.pruv','description':description,'replacement':{'old':old,'new':new},'verification':{}}
            rejected = []
            compiled = None
            for compiler in ('py','rs'):
                out = work/compiler; out.mkdir(exist_ok=True)
                c = g2.compile_pruv(compiler,str(work/f'a{batch}_root.pruv'),str(out),'rust',flags)
                entry['verification'][compiler] = c
                if c['rc']:
                    diagnostic = json.dumps(c['errors']) + c['stderr']
                    if c['rc'] < 0 or not any(s in diagnostic.lower() for s in ('verif','postcondition','precondition','invariant','proof','assertion','decreases')):
                        raise RuntimeError(f'{name}/{compiler}: not an identified proof rejection: {c}')
                    rejected.append(compiler)
                if compiler == 'rs': compiled = c
            if rejected:
                entry.update(classification='proof-rejected', caught_by={'verifiers':rejected})
            else:
                template,payload,expected,names = cache[batch]
                exe = build(g2,compiled,work/'rs',template,rustflags)
                try:
                    got = run([exe],payload,timeout=60).splitlines()
                    bad = [i for i in range(max(len(got),len(expected))) if i >= len(got) or i >= len(expected) or got[i] != expected[i]]
                    caught = None
                    if bad:
                        i = bad[0]
                        caught = {'batch':batch,'fixture':i,'name':names[i] if i < len(names) else 'extra output','expected':expected[i][:300] if i < len(expected) else None,'actual':got[i][:300] if i < len(got) else None}
                except (RuntimeError,subprocess.TimeoutExpired) as exc:
                    caught = {'batch':batch,'runtime_failure':str(exc)[-2000:]}
                entry.update(classification='behavior-detected' if caught else 'survived',caught_by=caught)
                if not caught:
                    entry['reason'] = ('Equivalent: the later depth >= 128 guard still rejects the 129th container before stack growth.'
                                       if name == 'depth_bound' else 'Not distinguished by imported batch fixtures.')
            report['mutants'].append(entry)
            write_report(report)
            print(f'{name}: {entry["classification"]}',flush=True)
    except Exception as exc:
        report['errors'].append(str(exc))
        print(str(exc),file=sys.stderr)
    report['elapsed_seconds'] = time.monotonic()-start
    write_report(report)
    print(json.dumps(report['counts']),flush=True)
    return int(bool(report['errors']))

if __name__ == '__main__':
    raise SystemExit(main())
