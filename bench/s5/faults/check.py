"""Apply one Stage 5 fault at a time to disposable compiler snapshots.

The delegated write boundary overrides the brief's /tmp location. Fixtures and
test runner remain read-only; compiler copies and all temporary outputs stay here.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('s5_perf', HERE.parent/'perf.py')
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)

FAULTS = [
 ('f1_loop', 'verify.py', [('s.spend(b, [], z3.IntVal(1))','s.spend(b, [], z3.IntVal(0))')], ['s5_proof']),
 ('f2_call', 'verify.py', [('s.spend(st, g, 1 + bound)','s.spend(st, g, bound)')], ['s5_proof','must_reject']),
 ('f3_assume', 'verify.py', [
  ('s.prove(st, [], st.env["spent"] <= s.cost0, node, "cost_bound",\n                    "spent <= cost `%s` (C at entry)" % _expr_text(s.f.cost))',
   's.assume(st, [], st.env["spent"] <= s.cost0)')], ['must_reject']),
 ('f4_havoc', 'verify.py', [('names.add("spent")','pass  # FAULT: retain pre-loop spent')], ['must_reject']),
 ('f5_rust_return', 'codegen.py', [
  ('return \'if pruv_cost < 0 || pruv_spent > pruv_cost as u128 { panic!("pruv: cost exceeded"); }\'',
   'return ""  # FAULT: erase safe return check')], ['runtime']),
 ('f6_llvm_return', 'llvmgen.py', [
  ('def cost_check(s):\n        negative', 'def cost_check(s):\n        return  # FAULT: erase safe return check\n        negative')], ['runtime']),
 ('f7_lengths', 'verify.py', [('s.spend(st, g, 1 + args[0])','s.spend(st, g, z3.IntVal(1))'),
                            ('s.spend(st, g, 1 + args[0].n)','s.spend(st, g, z3.IntVal(1))')], ['must_reject']),
 ('f8_erasure', 'codegen.py', [
  ('s.cost = not s.verified and f.cost is not None',
   'if s.verified and f.cost is not None:\n            s.emit(1, "let mut pruv_spent: u128 = 0;")\n        s.cost = not s.verified and f.cost is not None')], ['s5_proof']),
]

def group(compiler, name):
    cmd = [G.PY, ROOT/'tests/run_all.py', '--compiler','py','--compiler-path',compiler,
           '--backend','both','--only',name]
    if name in ('must_reject','runtime'):
        cmd += ['--sample-prefix','tests/'+name+'/s5_']
    return G.run(cmd, timeout=540, cwd=ROOT)

def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--only', help='fault id prefix, e.g. f1')
    a = p.parse_args()
    selected = [f for f in FAULTS if not a.only or f[0].split('_')[0] == a.only or f[0] == a.only]
    if not selected: p.error('unknown fault')
    path = HERE.parent/'results/faults.json'
    previous = json.loads(path.read_text()) if path.exists() and a.only else {'rows':[]}
    rows = {r['id']:r for r in previous['rows']}
    baselines = {}
    for name in dict.fromkeys(g for f in selected for g in f[3]):
        baselines[name] = group(ROOT/'pruvc/pruvc.py',name)
        print('baseline', name, baselines[name]['rc'],flush=True)
    for ident, filename, replacements, groups in selected:
        original = (ROOT/'pruvc'/filename).read_text()
        changed = original
        for old,new in replacements:
            assert changed.count(old) == 1, (ident,old,changed.count(old))
            changed = changed.replace(old,new)
        patch = ''.join(difflib.unified_diff(original.splitlines(True),changed.splitlines(True),
                       fromfile='a/pruvc/'+filename,tofile='b/pruvc/'+filename))
        patchfile = HERE/(ident+'.diff'); patchfile.write_text(patch)
        row = dict(id=ident, patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
                   baselines={g:baselines[g] for g in groups}, runs=[], detecting_tests=[], excluded_failures=[])
        with tempfile.TemporaryDirectory(dir=HERE,prefix='s5_'+ident+'_') as tmp:
            wd = Path(tmp)
            shutil.copytree(ROOT/'pruvc',wd/'pruvc',ignore=shutil.ignore_patterns('__pycache__'))
            row['patch_apply'] = G.run(['patch','-p1','-i',patchfile],cwd=wd)
            assert row['patch_apply']['rc'] == 0
            assert (wd/'pruvc'/filename).read_text() == changed
            for name in groups:
                r = group(wd/'pruvc/pruvc.py',name)
                row['runs'].append(r)
                for line in r['stdout'].splitlines():
                    if not line.startswith('FAIL '): continue
                    infrastructure = any(word in line.lower() for word in
                        ['traceback','timeout','internal error','unknown','cannot execute','error[e','not found'])
                    if baselines[name]['rc'] == 0 and r['rc'] == 1 and not infrastructure:
                        row['detecting_tests'].append(line[5:])
                    else:
                        row['excluded_failures'].append(line)
        row['detected'] = bool(row['detecting_tests'])
        row['gap'] = '' if row['detected'] else 'No semantic detection established. Add a minimal regression exercising this omitted rule with a tight bound; for f8 compare generated Rust with its clause-free twin.'
        rows[ident] = row
        print(ident, 'detected' if row['detected'] else 'NOT DETECTED',len(row['detecting_tests']),flush=True)
        path.write_text(json.dumps(dict(rows=list(rows.values()),
            isolation='One patch per temporary compiler snapshot inside bench/s5/faults; snapshot deleted after run. Existing named groups only; no test edits.'),indent=2)+'\n')
    lines = ['# Stage 5 compiler fault injections','',
      'Run `python3 -B bench/s5/faults/check.py` (or `--only f1` through `--only f8`).',
      'Python uses the existing z3 environment via PYTHONPATH; PRUV_PYTHON may override it.',
      'Each patch is applied alone with patch -p1 to a disposable compiler copy. All writes stay in owned directories.',
      'The user write boundary overrides the brief /tmp copy location, matching the current G7 isolation model.',
      'A passing clean baseline is mandatory. Infrastructure failures do not count as detection.',
      'Full commands, baseline output, failing named rows, hashes and exit codes are in ../results/faults.json.','',
      '| ID / omission | Patch SHA256 prefix | Command | Detecting tests | Result / gap |',
      '|---|---|---|---|---|']
    for row in rows.values():
        names = ', '.join(t.split('  -- ')[0] for t in row['detecting_tests']) or 'none'
        lines.append('| %s | %s | `python3 -B bench/s5/faults/check.py --only %s` | %s | %s |' %
                     (row['id'],row['patch_sha256'][:16],row['id'].split('_')[0],names,
                      'detected' if row['detected'] else row['gap']))
    (HERE/'README.md').write_text('\n'.join(lines)+'\n')
    return int(any(not rows[f[0]]['detected'] for f in selected))

if __name__ == '__main__':
    sys.exit(main())
