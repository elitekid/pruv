"""G8 bundle-body mutants: independent safe execution and four verified configurations."""
import sys
sys.dont_write_bytecode = True
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import run as G

CONFIGS = [(c, b) for c in ('py', 'rs') for b in ('rust', 'llvm')]
SEVERITY = ['wrong_but_proved', 'crash', 'timeout', 'unsupported', 'unknown',
            'unexecuted', 'accepted_correct', 'rejected_checker', 'rejected_verify']


def catalogue():
    base = (G.ROOT / 'stdlib/std.pruv').read_text()
    items = []

    def add(fn, op, old, new, intent='incorrect', whole=False):
        pattern = r'pub fn ' + fn + r'\b.*?(?=\npub fn |\Z)'
        match = re.search(pattern, base, re.S)
        chunk = match.group()
        header, body = chunk.split('{', 1)
        if intent == 'weak':
            assert old in header
            changed = header.replace(old, new, 1) + '{' + body
        else:
            assert old in body, (fn, old)
            changed = header + '{' + (new if whole else body.replace(old, new, 1))
        source = base[:match.start()] + changed + base[match.end():]
        # Whitespace-only compaction inside the changed body permits equal-length
        # embedding without touching any approved public header.
        if len(source.encode()) > len(base.encode()):
            h, b = changed.split('{', 1)
            changed = h + '{' + re.sub(r'\s+', ' ', b) + '\n'
            source = base[:match.start()] + changed + base[match.end():]
        rs_supported = len(source.encode()) <= len(base.encode())
        if rs_supported:
            source += ' ' * (len(base.encode()) - len(source.encode()))
        items.append(dict(id=f'm{len(items)+1:03}', function=fn, operator=op, intent=intent,
                          edit={'old': old, 'new': new, 'whole_body': whole}, source=source,
                          rs_supported=rs_supported, sha256=hashlib.sha256(source.encode()).hexdigest()))

    for fn, cmp in [('min_i64', '<='), ('max_i64', '>=')]:
        add(fn, 'flipped_comparison', 'a '+cmp+' b', 'a '+('>' if cmp=='<=' else '<')+' b')
        add(fn, 'wrong_value', 'return a;', 'return b;')
        add(fn, 'wrong_value', 'return b;', 'return a;')
    for old,new in [('x < lo','x > lo'),('x > hi','x < hi'),('return lo;','return hi;'),('return hi;','return lo;')]:
        add('clamp_i64','flipped_clamp',old,new)
    for old,new in [('x < 0','x > 0'),('return -x;','return x;'),('return x;','return 0;')]:
        add('abs_i64','wrong_absolute',old,new)
    for fn, guards in [('checked_add_i64', [('a > 9223372036854775807 - b','a >= 9223372036854775807 - b'),('a < -9223372036854775808 - b','a <= -9223372036854775808 - b')]),
                       ('checked_sub_i64', [('a < -9223372036854775808 + b','a <= -9223372036854775808 + b'),('a > 9223372036854775807 + b','a >= 9223372036854775807 + b')])]:
        for old,new in guards: add(fn,'overflow_boundary',old,new)
        add(fn,'wrong_checked_result','return Some(a '+('+' if 'add' in fn else '-')+' b);','return None;')
        add(fn,'skipped_overflow','return None;','return Some(0);')
    for old,new in [('let mut i: i64 = 0;','let mut i: i64 = 1;'),('s = s + a[i];','return s;'),('s = s + a[i];','s = a[i];'),('return s;','return 0;')]:
        add('sum_i64','premature_sum',old,new)
    for fn, ret in [('contains_i64','true'),('index_of_i64','Some(i)')]:
        add(fn,'skipped_match','let mut i: i64 = 0;','let mut i: i64 = 1;')
        add(fn,'flipped_match','a[i] == x','a[i] != x')
        add(fn,'skipped_match','return '+ret+';','return '+('false' if fn=='contains_i64' else 'None')+';')
    add('index_of_i64','last_index','let mut i: i64 = 0;',
        ' let mut i: i64 = len(a); while i > 0 invariant 0 <= i && i <= len(a) decreases i { i = i - 1; if a[i] == x { return Some(i); } } return None; }\n',whole=True)
    for old,new in [('a[i - 1] > a[i]','a[i - 1] < a[i]'),('a[i - 1] > a[i]','a[i - 1] >= a[i]'),('return false;','return true;'),('if len(a) < 2 { return true; }','if len(a) < 2 { return false; }')]:
        add('is_sorted_i64','wrong_sortedness',old,new)
    for old,new in [('a[i] > m','a[i] < m'),('let mut m: i64 = a[0];','let mut m: i64 = 0;'),('m = a[i];','m = a[0];'),('return m;','return a[0];')]:
        add('array_max_i64','incorrect_maximum',old,new)
    for old,new in [('out[i] = a[len(a) - 1 - i];','out[i] = a[i];'),('out[i] = a[len(a) - 1 - i];','out[i] = a[len(a) - i];'),('out[i] = a[len(a) - 1 - i];','out[i] = a[0];'),('out[i] = a[len(a) - 1 - i];','out[i] = 0;')]:
        add('reverse_i64','reversal_index',old,new)
    add('min_i64','weak_contract','ensures result == a || result == b','ensures true','weak')
    add('min_i64','equivalent','a <= b','a < b','equivalent')
    assert len({i['sha256'] for i in items}) == len(items)
    return items


def probe(fn):
    base = (G.ROOT / 'stdlib/std.pruv').read_text()
    header = re.search(r'pub fn '+fn+r'\b[^\{]*',base).group()
    header = '\n'.join(line for line in header.splitlines() if not line.strip().startswith('ensures'))
    args = {'clamp_i64':'x, lo, hi','abs_i64':'x','contains_i64':'a, x','index_of_i64':'a, x'}
    arg = args.get(fn,'a, b' if fn in ('min_i64','max_i64','checked_add_i64','checked_sub_i64') else 'a')
    return 'mod std;\n'+header.replace('fn '+fn+'(', 'fn run(')+'\n{ return crate::std::'+fn+'('+arg+'); }\n'


def inputs(fn):
    lo,hi=G.MIN,G.MAX
    nums=[lo,lo+1,-9,-2,-1,0,1,2,9,hi-1,hi]
    if fn in ('min_i64','max_i64','checked_add_i64','checked_sub_i64'):
        return [(a,b) for a in nums for b in nums]
    if fn=='abs_i64': return [(a,) for a in nums if a!=lo]
    if fn=='clamp_i64': return [(x,l,h) for x in nums for l,h in [(lo,hi),(-2,2),(0,0),(-9,-1)]]
    arrays=G.cases('q02')+[[lo],[hi],[lo,hi,lo],[hi,lo],[2,3,2],[1,2,1,2]]
    if fn=='sum_i64': arrays=G.cases('q02')
    if fn=='array_max_i64': arrays=[a for a in arrays if a]
    if fn in ('contains_i64','index_of_i64'):
        return [(a,x) for a in arrays for x in [-9,-2,-1,0,1,2,3,9,lo,hi]]
    return [(a,) for a in arrays]


def oracle(fn,t):
    if fn=='min_i64': return min(t)
    if fn=='max_i64': return max(t)
    if fn=='abs_i64': return abs(t[0])
    if fn=='clamp_i64': return max(t[1],min(t[2],t[0]))
    if fn.startswith('checked_'):
        value=t[0]+t[1] if fn=='checked_add_i64' else t[0]-t[1]
        return value if G.MIN<=value<=G.MAX else None
    a=t[0]
    if fn=='sum_i64': return sum(a)
    if fn=='array_max_i64': return max(a)
    if fn=='reverse_i64': return a[::-1]
    if fn=='is_sorted_i64': return all(x<=y for x,y in zip(a,a[1:]))
    if fn=='contains_i64': return t[1] in a
    if fn=='index_of_i64': return a.index(t[1]) if t[1] in a else None
    raise ValueError(fn)


def driver(fn):
    body='fn main(){ std::panic::set_hook(Box::new(|_| {})); let mut passed=0; let mut total=0;'
    for t in inputs(fn):
        args=[]
        body+='{'
        for k,x in enumerate(t):
            body+=f'let x{k}: '+('Vec<i64>' if isinstance(x,list) else 'i64')+' = '+G.literal(x)+';'
            args.append(('&' if isinstance(x,list) else '')+f'x{k}')
        want=oracle(fn,t)
        literal=G.literal(want)
        if fn.startswith('checked_') or fn=='index_of_i64':
            literal='None' if want is None else 'Some('+str(want)+')'
        body+=G.assertion('sol::run('+','.join(args)+')',literal)+'}'
    return body+'println!("TESTS {} {}",passed,total);}'


def execute(src,fn,comp,backend,wd,safe):
    wd.mkdir()
    c=G.G2.compile_pruv(comp,str(src),str(wd),backend,['--no-verify'] if safe else [])
    if c['rc']: return dict(c,status='pruv_error')
    # Verified acceptance is decisive for an independently observed wrong body;
    # execution here also checks the equivalent/weak controls.
    exe,error=G.build(c,wd,driver(fn))
    if error: return dict(status='compile_error',error=error)
    r=G.run([exe],timeout=60)
    m=re.search(r'TESTS (\d+) (\d+)',r['stdout'])
    passed,total=map(int,m.groups()) if m else (0,-1)
    return dict(r,status=('timeout' if r['rc']==-1 else 'ok' if r['rc']==0 and passed==total else 'wrong'),tests_passed=passed,tests_total=total)


def classify(r,truth):
    if r['status']=='ok': return 'wrong_but_proved' if truth=='incorrect' else 'accepted_correct'
    if r['status']=='wrong': return 'wrong_but_proved'
    if r['status']=='timeout' or r.get('rc')==-1: return 'timeout'
    if r['status']=='compile_error': return 'unexecuted'
    errors=r.get('errors',[])
    if r.get('rc')!=1 or not errors: return 'crash'
    if any('unknown' in e.get('code','') or 'timeout' in e.get('code','') for e in errors): return 'unknown'
    if any(e.get('stage')=='codegen' for e in errors): return 'unsupported'
    if all(e.get('stage')=='verify' for e in errors): return 'rejected_verify'
    if all(e.get('stage') in ('parse','type','effect') for e in errors): return 'rejected_checker'
    return 'crash'


def measure(item):
    with tempfile.TemporaryDirectory(prefix=item['id']+'_',dir=G.WORK) as tmp:
        wd=Path(tmp)
        package=wd/'distribution'
        shutil.copytree(G.ROOT/'pruvc',package/'pruvc',ignore=shutil.ignore_patterns('__pycache__'))
        (package/'stdlib').mkdir()
        (package/'stdlib/std.pruv').write_text(item['source'])
        G.G2.COMPILERS['py']=[G.G2.COMPILERS['py'][0],str(package/'pruvc/pruvc.py')]
        original_rs=Path(G.G2.COMPILERS['rs'][0])
        # Process workers are reused; always restore their original compiler paths.
        if item['rs_supported']:
            base=(G.ROOT/'stdlib/std.pruv').read_bytes()
            image=original_rs.read_bytes()
            assert image.count(base)==1,'embedded original bundle not found exactly once'
            exe=wd/'pruvc'
            exe.write_bytes(image.replace(base,item['source'].encode()))
            exe.chmod(0o755)
            if sys.platform=='darwin':
                signing=G.run(['codesign','-f','-s','-',exe])
                assert signing['rc']==0,signing
            G.G2.COMPILERS['rs']=[str(exe)]
        src=wd/'root.pruv'; src.write_text(probe(item['function']))
        try:
            truth_run=execute(src,item['function'],'py','rust',wd/'truth',True)
            truth={'ok':'correct','wrong':'incorrect'}.get(truth_run['status'],'unknown')
            runs={}
            for c,b in CONFIGS:
                if c=='rs' and not item['rs_supported']: continue
                r=execute(src,item['function'],c,b,wd/(c+'-'+b),False)
                runs[c+'-'+b]={'class':classify(r,truth),'grader':r}
            cls=min((r['class'] for r in runs.values()),key=SEVERITY.index)
            return {k:v for k,v in item.items() if k!='source'} | dict(truth=truth,truth_detail=truth_run,runs=runs,**{'class':cls})
        finally:
            G.G2.COMPILERS['rs']=[str(original_rs)]


def self_test(items):
    base=(G.ROOT/'stdlib/std.pruv').read_text()
    headers=lambda s: re.findall(r'pub fn [^\{]*',s)
    for i in items:
        if i['intent']!='weak': assert headers(i['source'])==headers(base)
        if i['rs_supported']: assert len(i['source'].encode())==len(base.encode())
        assert inputs(i['function'])
    assert sum(i['intent']=='incorrect' for i in items)>=36
    assert classify({'status':'ok'},'incorrect')=='wrong_but_proved'
    assert classify({'status':'pruv_error','rc':1,'errors':[{'stage':'verify','code':'verify_unknown'}]},'incorrect')=='unknown'
    print('self-test: unique edits, frozen headers, embedded lengths, independent oracles and classification OK')


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('out',nargs='?',type=Path,default=G.HERE/'results/mutants.json')
    p.add_argument('--self-test',action='store_true'); p.add_argument('--list',action='store_true')
    p.add_argument('--jobs',type=int,default=8); p.add_argument('--limit',type=int)
    a=p.parse_args(); items=catalogue()
    if a.self_test: self_test(items); return 0
    if a.list:
        for i in items: print(i['id'],i['function'],i['operator'],i['intent'],'both' if i['rs_supported'] else 'py-only')
        return 0
    if a.limit: items=items[:a.limit]
    results=[]
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        for r in pool.map(measure,items):
            results.append(r)
            print(r['id'],r['truth'],r['class'],flush=True)
    summary={'total':len(results),'by_intent':dict(Counter(r['intent'] for r in results)),
             'all_by_class':dict(Counter(r['class'] for r in results)),
             'incorrect_by_class':dict(Counter(r['class'] for r in results if r['truth']=='incorrect')),
             'wrong_but_proved':sum(r['class']=='wrong_but_proved' for r in results),
             'by_operator':dict(Counter(r['operator'] for r in results))}
    summary['intent_mismatch']=[r['id'] for r in results if r['truth']!=('incorrect' if r['intent']=='incorrect' else 'correct')]
    summary['unresolved']=[r['id'] for r in results if r['class'] not in ('rejected_verify','rejected_checker','accepted_correct')]
    payload={'bundle_sha256':hashlib.sha256((G.ROOT/'stdlib/std.pruv').read_bytes()).hexdigest(),
             'tools':G.G2.COMPILERS,'summary':summary,'results':results}
    a.out.write_text(json.dumps(payload,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    return int(bool(summary['wrong_but_proved'] or summary['intent_mismatch'] or summary['unresolved'] or
                    sum(r['truth']=='incorrect' for r in results)<36))


if __name__=='__main__': sys.exit(main())
