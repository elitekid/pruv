"""Generate and exercise eight isolated compiler faults without editing the source compiler.

Direct named must_reject rows are used (same diagnostic JSON oracle as run_all.py).
No unrelated test group runs. The disposable working-tree compiler copies live in
bench/g10/.work, respecting the delegation's stricter write boundary.
"""
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1]))
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import run as G

FAULTS = [
 ('f1_use_after_close', 'foreign.py',
  [('if v == "dead":', 'if False and v == "dead":')], ['g10_use_after_close']),
 ('f2_double_close', 'foreign.py',
  [('        s.use(e, st)\n        if not consuming:', '        # FAULT: do not check liveness when consuming again\n        if not consuming:')], ['g10_double_close']),
 ('f3_branch_move', 'foreign.py',
  [('if v == "maybe":', 'if False and v == "maybe":')], ['g10_branch_move']),
 ('f4_loop_move', 'foreign.py',
  [('if v == "live" and end.get(n) != "live":', 'if False and v == "live" and end.get(n) != "live":')], ['g10_loop_move']),
 ('f5_borrow_consume', 'foreign.py',
  [('        if n in s.bor:', '        if False and n in s.bor:')], ['g10_borrow_close']),
 ('f6_owned_placement', 'check.py',
  [('                    if contains_collection(f.type):', '                    if False and contains_collection(f.type):')], ['g10_owned_field']),
 ('f7_host_entry', 'check.py',
  [('if contains_collection(ty) or any(n in s.extended for n in dependencies(ty)):',
    'if False and (contains_collection(ty) or any(n in s.extended for n in dependencies(ty))):'),
   ('elif f.name == "main" and (is_collection(f.ret) or any(is_collection(p.type) for p in f.params)):',
    'elif False and f.name == "main" and (is_collection(f.ret) or any(is_collection(p.type) for p in f.params)):')],
  ['g10_host_entry', 'g10_main_signature']),
 ('f8_catalog_requires', 'verify.py',
  [('        def need(ob):\n            if code:', '        def need(ob):\n            if code and not n.startswith("file_"):')],
  ['g10_v_read_created', 'g10_v_write_opened', 'g10_v_byte_at_size', 'g10_v_read_unchecked']),
]


def probe(compiler, test, wd):
    source = G.ROOT / 'tests/must_reject' / (test + '.pruv')
    expected = json.loads(source.with_suffix('.json').read_text())
    cmd = [G.G2.COMPILERS['py'][0], compiler, source, '--backend', 'rust', '-o', wd / (test + '.rs')]
    r = G.run(cmd)
    diags = []
    for line in r['stdout'].splitlines():
        try:
            diags.append(json.loads(line))
        except ValueError:
            pass
    matched = r['rc'] == 1 and any(all(d.get(k) == expected[k] for k in ('stage', 'code')) for d in diags)
    return dict(r, command=[str(x) for x in cmd], expected=expected, matched=matched,
                internal_error=any(d.get('stage') == 'internal' for d in diags))


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--generate-only', action='store_true')
    a = p.parse_args()
    rows = []
    for name, filename, edits, tests in FAULTS:
        original = (G.ROOT / 'pruvc' / filename).read_text()
        altered = original
        for old, new in edits:
            assert altered.count(old) == 1, (name, old, altered.count(old))
            altered = altered.replace(old, new)
        patch = ''.join(difflib.unified_diff(original.splitlines(True), altered.splitlines(True),
                        fromfile='a/pruvc/' + filename, tofile='b/pruvc/' + filename))
        path = G.HERE / 'faults' / (name + '.diff')
        path.write_text(patch)
        row = {'fault': name, 'patch': path.name, 'sha256': hashlib.sha256(patch.encode()).hexdigest(),
               'source_sha256': hashlib.sha256(original.encode()).hexdigest(), 'tests': {}}
        if not a.generate_only:
            with tempfile.TemporaryDirectory(prefix=name + '_', dir=G.WORK) as tmp:
                wd = Path(tmp)
                shutil.copytree(G.ROOT / 'pruvc', wd / 'pruvc', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                baseline = {test: probe(wd / 'pruvc/pruvc.py', test, wd) for test in tests}
                applied = G.run(['patch', '--batch', '-p1', '-d', wd, '-i', path])
                row['patch_apply'] = applied
                if applied['rc']:
                    row['status'] = 'patch_error'
                else:
                    for test in tests:
                        faulty = probe(wd / 'pruvc/pruvc.py', test, wd)
                        row['tests'][test] = {'baseline': baseline[test], 'faulty': faulty,
                            'detected': baseline[test]['matched'] and not faulty['matched'] and
                                        faulty['rc'] in (0, 1, 3),
                            'detection_kind': 'internal_error' if faulty['internal_error'] else
                                              'accepted' if faulty['rc'] == 0 else 'diagnostic_change'}
                    row['status'] = 'detected' if any(t['detected'] for t in row['tests'].values()) else 'NOT_DETECTED'
        else:
            row['status'] = 'not_run'
        print(name, row['status'], flush=True)
        rows.append(row)
    if not a.generate_only:
        (G.HERE / 'results/faults.json').write_text(json.dumps({'rows': rows}, indent=2))
    table = ['# G10 compiler fault injections', '',
             'Each patch is applied alone with `patch -p1` to a disposable copy of the current `pruvc/`.',
             'The copy, generated output and compiler caches stay under `bench/g10/.work` and are removed.',
             'The original compiler is never patched. Run `python3 bench/g10/faults/check.py`.',
             'Direct named must_reject rows use their checked-in stage/code JSON oracle; clean baselines must pass.',
             'Timeouts and startup failures do not count. An internal error counts only as a detected',
             'diagnostic regression, never as acceptance or a successful source-mutant rejection.', '',
             '| Rule family | Patch SHA256 prefix | Named test(s) | Command in disposable copy | Result |',
             '|---|---|---|---|---|']
    for row, (_, _, _, tests) in zip(rows, FAULTS):
        kinds = ', '.join(sorted({t['detection_kind'] for t in row['tests'].values() if t['detected']}))
        table.append('| ' + ' | '.join([row['patch'], row['sha256'][:16], ', '.join(tests),
            '`$PRUV_PYTHON pruvc/pruvc.py <test>.pruv --backend rust -o <work>/out.rs`', row['status'] + ' (' + kinds + ')']) + ' |')
    table += ['', 'Full commands, exit codes, baseline diagnostics and faulty diagnostics are in `../results/faults.json`.',
              'The host-entry family includes both explicit public entries (`entry_signature`) and implicit main',
              '(`foreign_export`), reflecting the actual diagnostic names rather than treating them as identical.',
              'The proof fault covers both byte bounds and read/write mode catalog preconditions.', '']
    (G.HERE / 'faults/README.md').write_text('\n'.join(table))
    return int(not a.generate_only and any(r['status'] != 'detected' for r in rows))


if __name__ == '__main__':
    sys.exit(main())
