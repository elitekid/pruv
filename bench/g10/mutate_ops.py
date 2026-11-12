"""Explicit G10 source mutants; never count crashes/timeouts as rejection.

Omitting close alone is legal under G10 3.3 (drop closes). Two controls document
that fact. Reopen mutants additionally make unsound claims about the new handle.
"""
import sys
sys.dont_write_bytecode = True
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import tempfile
import run as G

# Every row is a deliberate, exact edit, not a regex mutation generator.
# pid, family, old text, replacement. Replacement must match exactly once.
EXPLICIT = [
 ('q01','wrong_mode','let f: File = file_open_read(input);\n  if !file_readable(f) { return -1; }','let f: File = file_create(input);\n  if !file_writable(f) { return -1; }'),
 ('q02','wrong_mode','let f: File = file_open_read(path);\n  if !file_readable(f) { return -1; }','let f: File = file_create(path);\n  if !file_writable(f) { return -1; }'),
 ('q01','wrong_mode','let g: File = file_read_all(move f);','let g: File = file_write_str(move f, input);'),
 ('q02','wrong_mode','let g: File = file_read_all(move f);','let g: File = file_write_str(move f, path);'),
 ('q01','wrong_mode','let written: File = file_write_bytes(move w, data);','let written: File = file_read_all(move w);'),
 ('q01','wrong_mode','if !file_writable(w) { return -2; }','if !file_ok(w) { return -2; }\n  let reader: File = file_open_read(output);\n  if !file_readable(reader) { return -2; }\n  let bad: File = file_write_bytes(move reader, data);'),
 ('q01','unchecked_read','if !file_readable(f) { return -1; }',''),
 ('q02','unchecked_read','if !file_readable(f) { return -1; }',''),
 ('q01','unchecked_read','if !file_readable(f) { return -1; }','if file_readable(f) { return -1; }'),
 ('q02','unchecked_read','if !file_readable(f) { return -1; }','if file_readable(f) { return -1; }'),
 ('q01','unchecked_read','if !file_readable(f) { return -1; }','if file_size(f) != 0 { return -1; }'),
 ('q02','unchecked_read','if !file_readable(f) { return -1; }','if file_size(f) != 0 { return -1; }'),
 ('q01','renamed_after_close','let data: [u8] = invert(g);','let alias: File = move g;\n  let done: bool = file_close(move alias);\n  let data: [u8] = invert(alias);'),
 ('q02','renamed_after_close','return count(g);','let alias: File = move g;\n  let done: bool = file_close(move alias);\n  return count(alias);'),
 ('q01','renamed_after_close','let read_closed: bool = file_close(move g);','let alias: File = move g;\n  let read_closed: bool = file_close(move alias);\n  let size: i64 = file_size(alias);'),
 ('q02','renamed_after_close','return count(g);','let alias: File = move g;\n  let done: bool = file_close(move alias);\n  let again: File = move alias;\n  return count(again);'),
 ('q01','renamed_after_close','let closed: bool = file_close(move written);','let alias: File = move written;\n  let closed: bool = file_close(move alias);\n  let ok: bool = file_ok(alias);'),
 ('q01','renamed_after_close','let closed: bool = file_close(move written);','let alias: File = move written;\n  let closed: bool = file_close(move alias);\n  let twice: bool = file_close(move alias);'),
 ('q01','byte_oob','data[i] = 255 - file_byte(f, i);','data[i] = 255 - file_byte(f, i + 1);'),
 ('q01','byte_oob','data[i] = 255 - file_byte(f, i);','data[i] = 255 - file_byte(f, i - 1);'),
 ('q01','byte_oob','data[i] = 255 - file_byte(f, i);','data[i] = 255 - file_byte(f, n);'),
 ('q01','byte_oob','data[i] = 255 - file_byte(f, i);','data[i] = 255 - file_byte(f, -1);'),
 ('q02','byte_oob','let b: i64 = file_byte(f, i);','let b: i64 = file_byte(f, i + 1);'),
 ('q02','byte_oob','let b: i64 = file_byte(f, i);','let b: i64 = file_byte(f, i - 1);'),
 ('q02','byte_oob','file_byte(f, n - 1)','file_byte(f, n)'),
 ('q02','byte_oob','file_byte(f, n - 1)','file_byte(f, n - 2)'),
 ('q01','bad_transform','data[i] = 255 - file_byte(f, i);','data[i] = file_byte(f, i);'),
 ('q01','bad_transform','data[i] = 255 - file_byte(f, i);','data[i] = 0;'),
 ('q01','bad_transform','data[i] = 255 - file_byte(f, i);','data[i] = 255;'),
 ('q01','bad_transform','data[i] = 255 - file_byte(f, i);','data[i] = (254 + file_byte(f, i)) % 256;'),
 ('q01','bad_transform','data[i] = 255 - file_byte(f, i);','data[i] = (256 - file_byte(f, i)) % 256;'),
 ('q01','bad_transform','data[i] = 255 - file_byte(f, i);','data[i] = file_byte(f, n - 1 - i);'),
 ('q01','missing_close_reopen','let closed: bool = file_close(move written);','let reopened: File = file_open_read(output);\n  let reread: File = file_read_all(move reopened);\n  let closed: bool = file_ok(written);'),
 ('q01','missing_close_reopen','let closed: bool = file_close(move written);','let reopened: File = file_open_read(output);\n  assert file_ok(reopened);\n  let closed: bool = file_ok(written);'),
 ('q01','missing_close_reopen','let closed: bool = file_close(move written);','let reopened: File = file_open_read(output);\n  assert file_readable(reopened);\n  let closed: bool = file_ok(written);'),
 ('q01','missing_close_reopen','let closed: bool = file_close(move written);','let reopened: File = file_open_read(output);\n  let byte: i64 = file_byte(reopened, 0);\n  let closed: bool = file_ok(written);'),
 ('q01','missing_close_reopen','let closed: bool = file_close(move written);','let reopened: File = file_open_read(output);\n  assert file_size(reopened) == len(data);\n  let closed: bool = file_ok(written);'),
 ('q01','missing_close_reopen','let closed: bool = file_close(move written);','let reopened: File = file_open_read(output);\n  if !file_readable(reopened) { return -2; }\n  let reread: File = file_read_all(move reopened);\n  assert file_size(reread) == len(data);\n  let closed: bool = file_ok(written);'),
 ('q01','unchecked_write','if !file_writable(w) { return -2; }',''),
 ('q01','unchecked_write','if !file_writable(w) { return -2; }','if file_writable(w) { return -2; }'),
 ('q01','missing_bound','if file_size(g) > 10000000 { return -3; }',''),
 ('q02','missing_bound','if file_size(g) > 4096 { return -2; }',''),
]
CONTROLS = [
 ('q01','drop_close_control','let closed: bool = file_close(move written);','let closed: bool = file_ok(written);'),
 ('q01','reopen_control','let closed: bool = file_close(move written);','let reopened: File = file_open_read(output);\n  let closed: bool = file_ok(written);'),
]


def catalogue():
    items = []
    for index, (pid, family, old, new) in enumerate(EXPLICIT + CONTROLS, 1):
        text = (G.HERE / 'solutions' / pid / 'root.pruv').read_text()
        assert text.count(old) == 1, (pid, family, old)
        source = text.replace(old, new)
        items.append(dict(id=f'm{index:03}', pid=pid, family=family, old=old, new=new,
                          source=source, intent='incorrect' if index <= len(EXPLICIT) else 'control',
                          sha256=hashlib.sha256(source.encode()).hexdigest()))
    assert len({x['sha256'] for x in items}) == len(items)
    return items


def classify(r):
    if r['status'] == 'ok':
        return 'accepted'
    if r['status'] == 'wrong':
        return 'wrong_but_proved'
    if r['status'] == 'pruv_error':
        if r['rc'] == -1:
            return 'timeout'
        errors = r.get('errors', [])
        if not errors or r['rc'] != 1:
            return 'compiler_crash'
        if any(e.get('stage') == 'internal' for e in errors):
            return 'compiler_crash'
        if any(e.get('code') in ('solver_unknown', 'solver_timeout', 'inference_timeout', 'verify_unknown') for e in errors):
            return 'unknown'
        if any(e.get('stage') == 'codegen' for e in errors):
            return 'unsupported'
        return 'rejected_verify' if all(e.get('stage') == 'verify' for e in errors) else 'rejected_check'
    return 'unresolved_' + r['status']


def measure(item, compiler, backends):
    with tempfile.TemporaryDirectory(prefix=item['id'] + '_', dir=G.WORK) as tmp:
        src = Path(tmp) / 'root.pruv'
        src.write_text(item['source'])
        truth = G.grade_one(src, item['pid'], compiler, 'rust', ['--no-verify'])
        t = {'ok': 'passes_tests', 'wrong': 'incorrect', 'pruv_error': 'not_compilable'}.get(truth['status'], 'unknown')
        rows = {}
        for backend in backends:
            r = G.grade_one(src, item['pid'], compiler, backend)
            rows[compiler + '-' + backend] = {'class': classify(r), 'grader': r}
        return {k: v for k, v in item.items() if k != 'source'} | {'truth': t, 'truth_run': truth, 'runs': rows}


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('out', type=Path, nargs='?', default=G.HERE / 'results/mutants.json')
    p.add_argument('--self-test', action='store_true')
    p.add_argument('--list', action='store_true')
    p.add_argument('--compiler', choices=['py', 'rs'], default='py')
    p.add_argument('--backend', choices=['rust', 'llvm', 'both'], default='both')
    p.add_argument('--jobs', type=int, default=8)
    a = p.parse_args()
    items = catalogue()
    if a.self_test:
        assert len(EXPLICIT) >= 40
        for item in items:
            assert G.HEADERS[item['pid']] in ' '.join(item['source'].split())
        assert G.ref_count(b',,\n\n') == 20004
        assert G.ref_transform(bytes([0, 127, 255])) == bytes([255, 128, 0])
        print('self-test: PASS;', len(EXPLICIT), 'explicit incorrect mutants;', len(CONTROLS), 'controls')
        return 0
    if a.list:
        for item in items:
            print(item['id'], item['pid'], item['intent'], item['family'])
        return 0
    backends = ['rust', 'llvm'] if a.backend == 'both' else [a.backend]
    with ThreadPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        rows = list(ex.map(lambda i: measure(i, a.compiler, backends), items))
    classes = Counter(r['class'] for item in rows for r in item['runs'].values())
    unexpected = [i['id'] for i in rows if i['intent'] == 'incorrect' and
                  any(r['class'] not in ('rejected_check', 'rejected_verify') for r in i['runs'].values())]
    wrong_ids = [i['id'] for i in rows if any(r['class'] == 'wrong_but_proved' for r in i['runs'].values())]
    summary = {'total': len(rows), 'explicit_incorrect': len(EXPLICIT), 'controls': len(CONTROLS),
               'all_by_class': dict(classes),
               'by_config': {a.compiler + '-' + b: dict(Counter(i['runs'][a.compiler + '-' + b]['class'] for i in rows))
                             for b in backends},
               'truth': dict(Counter(i['truth'] for i in rows)),
               'wrong_but_proved': len(wrong_ids), 'wrong_but_proved_ids': wrong_ids,
               'unexpected_incorrect': unexpected}
    a.out.write_text(json.dumps({'tools': G.G2.COMPILERS, 'summary': summary, 'items': rows}, indent=2))
    print(json.dumps(summary, indent=2))
    return int(bool(unexpected) or bool(classes['wrong_but_proved']))


if __name__ == '__main__':
    sys.exit(main())
