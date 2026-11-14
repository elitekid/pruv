#!/usr/bin/env python3
"""L3-1 Q seed mutants for the Pruv Claude importer (docs/CLAUDE_IMPORT_SPEC.md, "Seed targeted mutants").

For every mutant: copy the .pruv files to work/qm/<id>/, apply ONE exact textual replacement (the old snippet must
occur exactly once, else the mutant is 'stale'), verify+compile with the rs compiler / rust backend, and either
record 'proof-rejected' or run all test_a4 fixtures (plus the narrow extra fixtures below) and record 'detected' or
'SURVIVED'. The unmutated baseline must verify and pass every fixture first. Originals are never modified.
Usage: python3 q_mutants.py [--ids=3,18]   (--ids reruns only those and merges into mutants.json; exit 1 if a mutant SURVIVED or is stale; 2 on infrastructure failure)
"""
import sys
sys.dont_write_bytecode = True
import collections
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
QM = HERE / 'work' / 'qm'
JSON_MODULES = ('json', 'lex', 'parse', 'lines', 'jstr', 'access')
PROOF_WORDS = ('verif', 'postcondition', 'precondition', 'invariant', 'proof', 'assertion', 'decreases',
               'ensures', 'requires', 'bounds', 'index', 'overflow', 'cannot prove', 'unproved')


def load_test():
    spec = importlib.util.spec_from_file_location('test_a4', HERE / 'test_a4.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules['test_a4'] = mod
    spec.loader.exec_module(mod)
    return mod


# ---- mutants: (id, file, description, old, new) -------------------------------------------------------------
M5_OLD = 'last = copy(iso.text);'
M5_NEW = '''let mut keep: bool = true;
                if has_at && len(last) == 24 && len(iso.text) == 24 {
                  let mut q: i64 = 0;
                  let mut fin: bool = false;
                  while q < 24 && !fin
                    invariant 0 <= q && q <= 24 && len(last) == 24 && len(iso.text) == 24
                    decreases 24 - q
                  {
                    let ca: i64 = iso.text[q];
                    let cb: i64 = last[q];
                    if ca != cb { fin = true; keep = ca > cb; }
                    q = q + 1;
                  }
                }
                if keep { last = copy(iso.text); }'''

MUTANTS = [
 (1, 'entry.pruv', 'invert the exact-true isMeta filter in human_text',
  'if meta == 1 { return Field::Missing; }', 'if meta == 0 { return Field::Missing; }'),
 (2, 'entry.pruv', 'remove the any-position tool_result veto (a tool_result block is just ignored)',
  'Block::Veto => { return Field::Missing; }', 'Block::Veto => { seen = seen + 1; }'),
 (3, 'import.pruv', 'allow synthetic non-error replies (drop the isApiErrorMessage requirement)',
  'if api != 1 { return done(rank, title, nothing); }', 'if api < 0 { return done(rank, title, nothing); }'),
 (4, 'import.pruv', 'title rank comparison >= changed to > (a tie no longer lets the later one win)',
  'return rank >= best;', 'return rank > best;'),
 (5, 'import.pruv', 'lastAt takes the maximum accepted timestamp instead of the last accepted one', M5_OLD, M5_NEW),
 (6, 'import.pruv', 'omit the skip_user call in the window loop (dropped user line)',
  'if crate::text::dropped_user(head) { crate::turns::skip_user(inout st); }',
  'if crate::text::dropped_user(head) { idle = true; }'),
 (7, 'framing.pruv', 'raw line cap does not count the CR before LF',
  'if i - offset > limit {',
  'let mut raw: i64 = i - offset;\n      if i > offset { if data[i - 1] == 13 { raw = raw - 1; } }\n      if raw > limit {'),
 (8, 'framing.pruv', 'accept the short incomplete tail of a window as an entry',
  '  }\n  return Frame::Done;\n}', '  }\n  return Frame::Entry(offset, len(data), len(data));\n}'),
 (9, 'turns.pruv', 'remove the "\\n\\n" separator between reply pieces',
  'if rl > 0 { sep = 2; }', 'if rl > 0 { sep = 0; }'),
 (10, 'turns.pruv', 'use the actual reply length instead of the saturated reply budget',
  'let used: i64 = sl[8 * c + 2];', 'let used: i64 = sl[8 * c + 1];'),
 (11, 'turns.pruv', 'block replies (and completedAt) after the prompt was clipped',
  '  let c: i64 = st[3];\n  if len(at) == 24 {',
  '  let c: i64 = st[3];\n  if sl[8 * c + 4] == 1 { return; }\n  if len(at) == 24 {'),
 (12, 'turns.pruv', 'reverse the suffix order in finish (newest turn first)',
  'let t: i64 = kept - 1 - j;', 'let t: i64 = j;'),
 (13, 'turns.pruv', 'plan uses >= at the inclusive 2097152 total cap',
  'if total + size > 2097152 {', 'if total + size >= 2097152 {'),
 (14, 'import.pruv', 'omittedBefore from oversize loss (lost_before) instead of cut_before || trimmed',
  'if cut_before || col.trimmed == 1 { m[2] = 1; }', 'if st[2] == 1 || col.trimmed == 1 { m[2] = 1; }'),
 (15, 'time.pruv', 'seconds/milliseconds threshold 1e11 moved to 1e10',
  'if v < 100000000000 {', 'if v < 10000000000 {'),
 (16, 'boundary.pruv', 'unsafe output index: widen writes the turns one slot too far',
  '{ out[18 + j] = turns[j]; j = j + 1; }', '{ out[19 + j] = turns[j]; j = j + 1; }'),
 (17, 'turns.pruv', 'state-frame violation: tool writes the tools counter of the next slot, not the current one',
  'sl[8 * c + 3] = t + 1;', 'sl[8 * ((c + 1) % 200) + 3] = t + 1;'),
 (18, 'turns.pruv', 'stop updating completedAt once the reply budget is full',
  '  let c: i64 = st[3];\n  if len(at) == 24 {',
  '  let c: i64 = st[3];\n  if sl[8 * c + 2] >= 32768 { return; }\n  if len(at) == 24 {'),
]

# Notes only; the real outcome is always measured.
EXPECTED = {4: 'proof-rejected', 7: 'proof-rejected', 8: 'proof-rejected', 9: 'proof-rejected', 11: 'proof-rejected',
            13: 'proof-rejected', 15: 'proof-rejected', 16: 'proof-rejected', 17: 'proof-rejected'}
# A mutant that is genuinely equivalent would be listed here as id -> one-line argument (none is assumed).
EQUIVALENT = {}


def extra_fixtures(ta):
    """Narrow extra fixtures (op, flag, data) built with test_a4's builders; they must pass on the baseline."""
    L, user, asst, tx, tr = ta.L, ta.user, ta.asst, ta.tx, ta.tool_result
    items = [
        ('qm extra: veto on the last of three blocks', 'window', 0, L(user([tx('a'), tx('b'), tr()]), asst('r'), user('real'))),
        ('qm extra: lastAt decreasing', 'tail', 0, L(user('a', timestamp=900), asst('b', timestamp=300))),
        ('qm extra: isMeta then plain user', 'window', 0, L(user('m', isMeta=True), user('p'), asst('r'))),
    ]
    return [(n, op, flag, data, ta.oracle.api(op, flag, data)) for n, op, flag, data in items]


def first_line(text):
    for line in str(text).splitlines():
        if line.strip():
            return line.strip()[:240]
    return ''


def diagnostic(c):
    errs = c.get('errors')
    if isinstance(errs, (list, tuple)):
        errs = '\n'.join(map(str, errs))
    return f"{errs or ''}\n{c.get('stderr') or ''}"


def copy_sources(work):
    work.mkdir(parents=True, exist_ok=True)
    for p in HERE.glob('*.pruv'):
        shutil.copyfile(p, work / p.name)
    for m in JSON_MODULES:  # json modules are copied from the json batch when this folder lacks them
        if not (work / f'{m}.pruv').exists() and (HERE.parent / 'json' / f'{m}.pruv').exists():
            shutil.copyfile(HERE.parent / 'json' / f'{m}.pruv', work / f'{m}.pruv')


def build_runner(g2, run, ta, compiled, work, rustflags):
    harness = work / 'main.rs'
    harness.write_text(ta.HARNESS.replace('@SOL@', compiled['rs']))
    extra = []
    if compiled.get('ll'):
        extra, error = g2.build_llvm_objects(compiled['ll'], 'a4', str(work))
        if error:
            raise RuntimeError(error)
    exe = work / 'runner'
    run([g2.RUSTC, '-O', '--edition', '2021', harness, '-o', exe] + extra + rustflags)
    return exe


def run_fixtures(exe, payload, timeout=300):
    p = subprocess.run([str(exe)], input=payload, text=True, capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f'runner exit {p.returncode}: {first_line(p.stderr)}')
    return p.stdout.splitlines()


def first_difference(expected, got, names):
    for i in range(max(len(expected), len(got))):
        if i >= len(got) or i >= len(expected) or got[i] != expected[i]:
            name = names[i] if i < len(names) else 'extra output'
            return f'fixture {i} {name}'
    return None


def main():
    ta = load_test()
    cases = ta.fixtures() + extra_fixtures(ta)
    names = [c[0] for c in cases]
    assert len(set(names)) == len(names), 'fixture names must be unique'
    payload = ''.join(f'{op} {flag}|{ta.enc_bytes(data)}\n' for _, op, flag, data, _ in cases)
    expected = [ta.a3.enc(want) for *_, want in cases]
    QM.mkdir(parents=True, exist_ok=True)
    g2, run = ta.configure()
    target = QM / 'str-adapter'
    run([shutil.which('cargo') or str(Path.home() / '.cargo/bin/cargo'), 'build', '--release', '--offline', '--quiet',
         '--manifest-path', ta.JSON_DIR / 'str_adapter/Cargo.toml', '--target-dir', target])
    rlib, deps = target / 'release/libpruv_str.rlib', target / 'release/deps'
    flags = ['--rust-extern', f'pruv_str={rlib}', '--rust-search', str(deps)]
    rustflags = ['--extern', f'pruv_str={rlib}', '-L', f'dependency={deps}']

    # ---- baseline ----
    t0 = time.monotonic()
    work = QM / 'baseline'
    copy_sources(work)
    out = work / 'out'
    out.mkdir(exist_ok=True)
    c = g2.compile_pruv('rs', str(work / 'a4_root.pruv'), str(out), 'rust', flags)
    if c['rc'] != 0:
        print('baseline does not verify: ' + first_line(diagnostic(c)), file=sys.stderr)
        return 2
    exe = build_runner(g2, run, ta, c, out, rustflags)
    diff = first_difference(expected, run_fixtures(exe, payload), names)
    if diff:
        print('baseline fixture mismatch: ' + diff, file=sys.stderr)
        return 2
    baseline_seconds = time.monotonic() - t0
    print(f'baseline verified, {len(cases)} fixtures pass ({baseline_seconds:.1f}s)', flush=True)

    ids = {int(x) for a in sys.argv[1:] if a.startswith('--ids=') for x in a[6:].split(',')}
    prev = json.loads((QM / 'mutants.json').read_text())['mutants'] if ids and (QM / 'mutants.json').exists() else []
    results = [m for m in prev if m['id'] not in ids]
    for mid, fname, description, old, new in MUTANTS:
        if ids and mid not in ids:
            continue
        start = time.monotonic()
        entry = {'id': mid, 'file': fname, 'description': description}
        work = QM / f'm{mid:02d}'
        copy_sources(work)
        path = work / fname
        text = path.read_text()
        n = text.count(old)
        if n != 1:
            entry.update(outcome='stale', detail=f'old snippet occurs {n} times in {fname}, expected exactly one')
        else:
            path.write_text(text.replace(old, new, 1))
            out = work / 'out'
            out.mkdir(exist_ok=True)
            try:
                c = g2.compile_pruv('rs', str(work / 'a4_root.pruv'), str(out), 'rust', flags)
                if c['rc'] != 0:
                    diag = diagnostic(c)
                    note = '' if any(w in diag.lower() for w in PROOF_WORDS) else '[no proof keyword; check it is not a syntax error] '
                    entry.update(outcome='proof-rejected', detail=note + first_line(diag))
                else:
                    exe = build_runner(g2, run, ta, c, out, rustflags)
                    try:
                        diff = first_difference(expected, run_fixtures(exe, payload), names)
                        entry.update(outcome='detected' if diff else 'SURVIVED', detail=diff or 'all fixtures equal the baseline')
                    except (RuntimeError, subprocess.TimeoutExpired) as exc:
                        entry.update(outcome='detected', detail='runtime failure: ' + first_line(exc))
            except Exception as exc:  # infrastructure/build failure of the mutated runner
                entry.update(outcome='error', detail=first_line(exc))
        if mid in EQUIVALENT and entry['outcome'] == 'SURVIVED':
            entry.update(outcome='equivalent', detail=EQUIVALENT[mid])
        entry['seconds'] = round(time.monotonic() - start, 2)
        results.append(entry)
        print(f"{mid} {entry['outcome']} {entry['detail']}", flush=True)

    results.sort(key=lambda m: m['id'])
    counts = dict(collections.Counter(m['outcome'] for m in results))
    report = {'mutants': results, 'counts': counts, 'baseline_seconds': baseline_seconds}
    (QM / 'mutants.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(counts), flush=True)
    bad = counts.get('SURVIVED', 0) + counts.get('stale', 0) + counts.get('error', 0)
    return int(bad > 0)


if __name__ == '__main__':
    raise SystemExit(main())
