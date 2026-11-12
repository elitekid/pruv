"""Replay isolated G8 compiler omissions using only existing targeted groups."""
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
spec = importlib.util.spec_from_file_location('g8_perf', HERE.parent/'perf.py')
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)

# Reachability is transitive, starting with every non-std definition. Filtering
# only the verification loop preserves contracts in the ordinary call model.
REACH = '''    from vast import Call
    def calls(node):
        if isinstance(node, (list, tuple)):
            return set().union(*(calls(n) for n in node)) if node else set()
        if not hasattr(node, '__dataclass_fields__'):
            return set()
        found = {node.name} if isinstance(node, Call) else set()
        for value in vars(node).values():
            found.update(calls(value))
        return found
    reachable = {f.name for f in prog.functions if f.file != '@std/std.pruv'}
    while True:
        expanded = reachable | set().union(*(calls(f.body) for f in prog.functions if f.name in reachable))
        if expanded == reachable:
            break
        reachable = expanded
'''
FAULTS = [
 ('f1_unused', 'verify.py', [('    if not infer:\n', REACH+'    if not infer:\n'),
   ('        for f in prog.functions:\n            FnVerifier', '        for f in prog.functions:\n            if f.name not in reachable: continue  # FAULT\n            FnVerifier'),
   ('    for f in prog.functions:\n        res =', '    for f in prog.functions:\n        if f.name not in reachable: continue  # FAULT\n        res =')], ['g8_proof']),
 ('f2_trusted', 'verify.py', [
   ('        for f in prog.functions:\n            FnVerifier', "        for f in prog.functions:\n            if f.file == '@std/std.pruv': continue  # FAULT\n            FnVerifier"),
   ('    for f in prog.functions:\n        res =', "    for f in prog.functions:\n        if f.file == '@std/std.pruv': continue  # FAULT\n        res =")], ['g8_proof']),
 ('f3_local', 'modules.py', [
   ('                if os.path.lexists(fpath):\n                    raise PruvError("parse", md.line, md.col, "std_module_conflict",\n                                    "local std.pruv conflicts with the bundled std module",\n                                    "rename the user module/file and its paths", file=m.file)\n                fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stdlib", "std.pruv")',
    '                if not os.path.lexists(fpath):  # FAULT: local wins\n                    fpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "stdlib", "std.pruv")')], ['g8_frontend','must_reject']),
 ('f4_rust_requires', 'codegen.py', [
   ('s.entry(f, ps, ret, body_name, f.name, False, True)', "s.entry(f, ps, ret, body_name, f.name, False, not (s.trust and f.file == '@std/std.pruv'))")], ['runtime']),
 ('f5_llvm_requires', 'llvmgen.py', [
   ('                chunks.append(entry_of(m, funcs, f, False, budget))',
    "                chunks.append(entry_of(m, funcs, f, trust_callers and f.file == '@std/std.pruv', budget))")], ['runtime']),
]
DESCRIPTIONS = dict(f1_unused='Skip proofs of std functions unreachable from user definitions',
    f2_trusted='Trust every std contract without proving bundle bodies',
    f3_local='Load local std.pruv despite the reserved-module conflict',
    f4_rust_requires='Drop safe std requires under trust-callers (Rust)',
    f5_llvm_requires='Drop safe std requires under trust-callers (LLVM)')

def snapshot(dest):
    # Copy the runner too: bundle meta-tests derive their compiler from __file__,
    # so --compiler-path alone would silently test the clean compiler there.
    for name in ('pruvc', 'stdlib', 'tests', 'examples'):
        shutil.copytree(ROOT/name, dest/name, symlinks=True,
                        ignore=shutil.ignore_patterns('__pycache__', 'target'))
    shutil.copy2(ROOT/'SPEC.md', dest/'SPEC.md')
    (dest/'docs').mkdir()
    shutil.copy2(ROOT/'docs/G8_SPEC.md', dest/'docs/G8_SPEC.md')

def group(root, name):
    cmd = [G.PY, root/'tests/run_all.py', '--compiler','py', '--backend','both','--only',name]
    if name in ('runtime','must_reject'):
        cmd += ['--sample-prefix', 'tests/'+name+'/g8_']
    return G.run(cmd, timeout=540, cwd=root)

def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--only', choices=['f1','f2','f3','f4','f5'])
    a = p.parse_args()
    selected = [f for f in FAULTS if not a.only or f[0].startswith(a.only+'_')]
    out = HERE.parent/'results/faults.json'
    rows = {r['id']:r for r in json.loads(out.read_text())['rows']} if a.only and out.exists() else {}
    baseline = {}
    with tempfile.TemporaryDirectory(dir=HERE, prefix='clean_') as tmp:
        wd = Path(tmp); snapshot(wd)
        for name in dict.fromkeys(g for f in selected for g in f[3]):
            baseline[name] = group(wd,name)
            print('baseline',name,baseline[name]['rc'],flush=True)
    for ident, filename, replacements, groups in selected:
        original = (ROOT/'pruvc'/filename).read_text(); changed = original
        for old,new in replacements:
            assert changed.count(old) == 1, (ident,old,changed.count(old))
            changed = changed.replace(old,new)
        patch = ''.join(difflib.unified_diff(original.splitlines(True),changed.splitlines(True),
                       fromfile='a/pruvc/'+filename,tofile='b/pruvc/'+filename))
        patchfile = HERE/(ident+'.diff'); patchfile.write_text(patch)
        row = dict(id=ident,patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
                   baselines={g:baseline[g] for g in groups},runs=[],detecting_tests=[],excluded_failures=[])
        with tempfile.TemporaryDirectory(dir=HERE,prefix=ident+'_') as tmp:
            wd = Path(tmp); snapshot(wd)
            row['patch_apply'] = G.run(['patch','-p1','-i',patchfile],cwd=wd)
            assert row['patch_apply']['rc'] == 0
            assert (wd/'pruvc'/filename).read_text() == changed
            for name in groups:
                r = group(wd,name); row['runs'].append(r)
                for line in r['stdout'].splitlines():
                    if not line.startswith('FAIL '): continue
                    infrastructure = any(word in line.lower() for word in
                        ('timeout','cannot execute','error[e','not found','permission denied','internal error'))
                    if baseline[name]['rc'] == 0 and r['rc'] == 1 and not infrastructure:
                        row['detecting_tests'].append(line[5:])
                    else:
                        row['excluded_failures'].append(line)
        row['detected'] = bool(row['detecting_tests'])
        row['gap'] = '' if row['detected'] else 'No detection established; inspect baseline/infrastructure and add a regression for this omitted rule if baseline passes.'
        rows[ident] = row
        out.write_text(json.dumps(dict(rows=list(rows.values()),isolation='Disposable compiler, bundle and unchanged test copies inside owned faults directory; removed after each run. No /tmp writes.'),indent=2)+'\n')
        print(ident,row['detected'],row['detecting_tests'],flush=True)
    write_readme(rows)
    return int(any(not rows[f[0]]['detected'] for f in selected))

def write_readme(rows):
    lines = ['# G8 compiler faults','',
      'Run `python3 -B bench/g8/faults/check.py` or `--only f1` through `--only f5`. Only named G8 groups run.',
      'Each patch is applied alone with patch -p1; clean baselines must pass. The unchanged test runner is copied too so bundle meta-tests use the faulty compiler.',
      'User write boundaries override /tmp: all disposable copies and TMPDIR live in owned directories and copies are removed. Full commands and output: ../results/faults.json.','',
      '| ID | Omission | SHA256 prefix | Replay command | Detecting tests | Gap |','|---|---|---|---|---|---|']
    for r in rows.values():
        lines.append('| %s | %s | %s | `python3 -B bench/g8/faults/check.py --only %s` | %s | %s |' %
          (r['id'],DESCRIPTIONS[r['id']],r['patch_sha256'][:16],r['id'].split('_')[0],', '.join(t.split('  -- ')[0] for t in r['detecting_tests']) or 'none',r['gap'] or 'none'))
    (HERE/'README.md').write_text('\n'.join(lines)+'\n')

if __name__ == '__main__':
    sys.exit(main())
