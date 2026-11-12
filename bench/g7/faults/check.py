"""Apply each G7 compiler fault alone; rerun named rejection/runtime/artifact oracles.

Disposable compiler snapshots preserve working-tree source (not git HEAD). Only
pruvc/ is copied, as in G10: fixtures are read from the working tree. All writes
stay in the owned faults/ and perf/ directories, never /tmp or the source compiler.
"""
import sys
sys.dont_write_bytecode = True
import argparse
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location('g7_perf', HERE.parent / 'perf.py')
G = importlib.util.module_from_spec(spec)
spec.loader.exec_module(G)

FAULTS = [
 ('f1_write_read', 'check.py', [
  ('if name in ri:', 'if False and name in ri:'),
  ('for name, node in rj.items():\n                    if name in wi:', 'for name, node in rj.items():\n                    if False and name in wi:')],
  ['g7_alias_write_read', 'g7_alias_read_write']),
 ('f2_write_write', 'check.py', [
  ('for name, node in wj.items():\n                    if name in wi:', 'for name, node in wj.items():\n                    if False and name in wi:')],
  ['g7_alias_write_write', 'g7_alias_write_write_noverify']),
 ('f3_transitive_foreign', 'check.py', [
  ('path = s.par_witness(n, lambda i: i["foreign"] is not None, cache)', 'path = None  # FAULT: omit transitive foreign eligibility')],
  ['g7_foreign_deep']),
 ('f4_nested', 'check.py', [
  ('path = s.par_witness(n, lambda i: i["par"], cache)', 'path = None  # FAULT: admit nested parallelism')],
  ['g7_nested_indirect']),
 ('f5_early_ensures', 'verify.py', [
  ('                s.termination(c, f, st, [], cenv)\n            finally:',
   '                s.termination(c, f, st, [], cenv)\n                # FAULT: expose ensures to later sibling requires.\n                for en in f.ensures:\n                    s.assume(st, [], s.ev(en, st, [], False, cenv))\n            finally:')],
  ['g7_v_sibling_ensures', 'g7_v_second_requires', 'g7_v_sibling_ensures_order']),
 ('f6_no_havoc', 'verify.py', [
  ('            if ios:\n                s.inout_finals(c, f, ios, args, cenv, st, [])',
   '            if False and ios:\n                s.inout_finals(c, f, ios, args, cenv, st, [])')],
  ['g7_v_stale_contents', 'g7_v_partial_frame']),
 ('f7_loop_writes', 'verify.py', [
  ('elif isinstance(st, Par):      # G7 A0: every branch\'s inout operands (verification itself is A1)\n                for c in st.calls:\n                    s._inout_ops(c, out)',
   'elif isinstance(st, Par):      # FAULT: retain stale loop facts\n                pass')],
  ['g7_v_loop_stale', 'g7_v_loop_stale_infer']),
 ('f8_detached_bridge', 'parallel_shim.py', [
  ('::std::thread::scope(|scope| {', '(|| {'),
  ('::std::thread::Builder::new().spawn_scoped(scope, move || {', '::std::thread::Builder::new().spawn(move || {'),
  ('if h.join().is_err() { panicked = true; }', '::std::mem::drop(h); // FAULT: detach; stack contexts can expire'),
  ('            });\n        }));', '            })();\n        }));')],
  ['runtime:g7_r10_join_return']),
 ('f9_mutable_readonly', 'llvmgen.py', [
  ('("ptr noalias nocapture" if n in mut else "ptr noalias nocapture readonly")',
   '("ptr noalias nocapture readonly" if n in mut else "ptr noalias nocapture readonly")')],
  ['artifact:mutable_attributes']),
 ('f10_safe_body', 'llvmgen.py', [
  ('target = "par_chk" if not s.verified and f.requires else "body"', 'target = "body"  # FAULT: bypass safe requires checks')],
  ['artifact:safe_routing']),
]

GAPS = {
 'f8_detached_bridge': 'Add deterministic worker gating and a parent continuation assertion proving all callbacks joined; do not rely on scheduler timing.',
}

def rejection(compiler, name, wd, backend):
    src = ROOT / 'tests/must_reject' / (name + '.pruv')
    want = json.loads(src.with_suffix('.json').read_text())
    r = G.run([G.PY, compiler, src, '--backend', backend, '-o', wd / 'out', *want.get('flags', [])])
    diags = []
    for line in r['stdout'].splitlines():
        try: diags.append(json.loads(line))
        except ValueError: pass
    r['passed'] = r['rc'] == 1 and any(all(d.get(k) == want[k] for k in ('stage','code')) for d in diags)
    r['valid'] = r['rc'] in (0,1,3) and not any(d.get('stage') == 'internal' or d.get('code') == 'verify_unknown' for d in diags) and not r['stderr']
    return r

def artifact(compiler, name, wd):
    fixture = 'g7_l02_optimized' if name == 'mutable_attributes' else 'g7_safe_requires'
    rs,ll = G.compile_source(ROOT / 'tests/runtime' / fixture / 'root.pruv', wd, 'llvm', [G.PY,compiler])
    ir = ll.read_text()
    if name == 'mutable_attributes':
        signatures = re.findall(r'define internal void @\w+__pruv_body\([^\n]+', ir)
        mutable = [s for s in signatures if '%p.a.a' in s]
        assert mutable, 'fixture must contain a mutable a parameter'
        forbidden = [s for s in mutable if re.search(r'ptr[^,]*readonly[^,]*%p.a.a',s)]
        ctx = re.findall(r'define private void @pruv_g7_cb_\d+\(([^)]*)\)',ir)
        passed = not forbidden and bool(ctx) and all(c == 'ptr %ctx' for c in ctx)
        evidence = mutable + ctx
    else:
        callbacks = re.findall(r'define private void @pruv_g7_cb_\d+.*?\n}',ir,re.S)
        assert callbacks, 'fixture must contain trampolines'
        passed = all('__pruv_par_chk(' in c and '__pruv_body(' not in c for c in callbacks)
        evidence = callbacks
    return dict(passed=passed, valid=True, evidence=evidence, fixture=fixture, flags=['--no-verify'])

def runtime(compiler, name, wd):
    # Exact source, driver, flags and stdout oracle of this named runtime row.
    fixture = ROOT / 'tests/runtime' / name
    want = json.loads((fixture/'spec.json').read_text())
    rs,ll = G.compile_source(fixture/'root.pruv',wd,'llvm',[G.PY,compiler],flags=())
    exe = G.build(rs,ll,wd,(fixture/'main.rs').read_text(),'llvm')
    r = G.run([exe],timeout=30,cwd=wd)
    r['passed'] = r['rc'] == want['exit'] and r['stdout'].splitlines() == want['stdout_lines']
    r['valid'] = r['rc'] != -1
    r['expected'] = want['stdout_lines']
    return r

def probe(compiler, name, wd, backend):
    try:
        if name.startswith('artifact:'): return artifact(compiler,name.split(':')[1],wd)
        if name.startswith('runtime:'): return runtime(compiler,name.split(':')[1],wd)
        return rejection(compiler,name,wd,backend)
    except (RuntimeError, AssertionError) as e:
        return dict(passed=False, valid=False, error=str(e))

def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--generate-only',action='store_true')
    p.add_argument('--only',nargs='+',help='fault IDs, e.g. f8')
    a = p.parse_args()
    rows = []
    for name, filename, edits, tests in FAULTS:
        if a.only and name.split('_')[0] not in a.only: continue
        original = (ROOT/'pruvc'/filename).read_text()
        altered = original
        for old,new in edits:
            assert altered.count(old) == 1, (name,old,altered.count(old))
            altered = altered.replace(old,new)
        patch = ''.join(difflib.unified_diff(original.splitlines(True),altered.splitlines(True),fromfile='a/pruvc/'+filename,tofile='b/pruvc/'+filename))
        path = HERE/(name+'.diff'); path.write_text(patch)
        row = dict(fault=name,patch=path.name,sha256=hashlib.sha256(patch.encode()).hexdigest(),source_sha256=hashlib.sha256(original.encode()).hexdigest(),tests={},status='not_run')
        if not a.generate_only:
            with tempfile.TemporaryDirectory(prefix=name+'_',dir=HERE) as tmp:
                wd = Path(tmp)
                shutil.copytree(ROOT/'pruvc',wd/'pruvc',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                compiler = wd/'pruvc/pruvc.py'
                cases = [(t,b) for t in tests for b in (['llvm'] if ':' in t else ['rust','llvm'])]
                baseline = {(t,b):probe(compiler,t,wd,b) for t,b in cases}
                applied = G.run(['patch','--batch','-p1','-d',wd,'-i',path]); row['patch_apply']=applied
                if applied['rc']: row['status']='patch_error'
                else:
                    for t,b in cases:
                        bad = probe(compiler,t,wd,b); good = baseline[t,b]
                        kind = ('artifact_assertion' if t.startswith('artifact:') else
                                'runtime_signal_or_wrong_output' if t.startswith('runtime:') else
                                'accepted' if bad.get('rc') == 0 else 'diagnostic_regression')
                        row['tests'][t+':'+b] = dict(baseline=good,faulty=bad,detected=good['passed'] and bad['valid'] and not bad['passed'],detection_kind=kind)
                    row['status']='detected' if any(t['detected'] for t in row['tests'].values()) else 'gap'
                    if row['status']=='gap': row['gap']=GAPS.get(name,'Add a focused fixture isolating this omitted rule; see baseline/fault diagnostics before attributing nondetection to coverage.')
        rows.append(row); print(name,row['status'],flush=True)
    output = HERE.parent/'results/faults.json'
    if a.only and output.exists():
        previous = json.loads(output.read_text())['rows']
        updated = {r['fault']:r for r in rows}
        rows = [updated.pop(r['fault'],r) for r in previous] + list(updated.values())
    output.write_text(json.dumps(dict(rows=rows),indent=2)+'\n')
    table = ['# G7 compiler fault injections','',
      'Run `PRUV_PYTHON=/path/to/python python -B bench/g7/faults/check.py`.',
      'Each patch is applied alone to a disposable working-tree compiler snapshot under faults/.',
      'Fixtures are read from this working tree; no git reset/checkout, /tmp writes, or compiler edits.',
      'This follows G10 snapshot isolation instead of copying the entire repository, to honor the delegated write boundary.',
      'Named must_reject oracles compare checked-in stage/code and flags on both backends.',
      'Runtime f8 builds/runs the existing g7_r10_join_return source/driver and compares its spec stdout.',
      'f9/f10 are direct LLVM artifact assertions; these are benchmark assertions, not additions to tests/.',
      'Clean baseline success is required; compile failures, timeouts, internal errors and unknown proofs never count.',
      '', '| ID / omitted rule | SHA256 prefix | Rerun command | Detecting tests | Result / gap |','|---|---|---|---|---|']
    for row in rows:
        detected = ', '.join(k+' ('+v.get('detection_kind','see JSON')+')' for k,v in row['tests'].items() if v['detected']) or 'none'
        table.append('| '+ ' | '.join([row['fault'],row['sha256'][:16],'`python -B bench/g7/faults/check.py --only '+row['fault'].split('_')[0]+'`',detected,row['status']+(': '+row['gap'] if 'gap' in row else '')])+' |')
    table += ['', 'Full baseline/fault commands, outputs, artifact evidence, patch hashes and exit codes: `../results/faults.json`.',
              'Diagnostic regressions detect a missing static rule even if a later proof still rejects the program; they are not claimed as wrong acceptance.',
              'f8 detaches native workers: only the disposable subprocess executes the faulty bridge; no faulty code is loaded into this runner.',
              'A runtime signal is evidence of this lifetime fault, not a successful semantic result. Its scheduling is nondeterministic; a deterministic gated lifetime regression remains desirable.', '']
    (HERE/'README.md').write_text('\n'.join(table))
    return int(any(r['status'] not in ('detected','not_run') for r in rows))

if __name__ == '__main__': sys.exit(main())
