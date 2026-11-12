#!/usr/bin/env python3
"""Compare hostWithin in direct and URL modes (20,000 random cases per mode)."""
import argparse
import json
import random
import re
import sys

sys.dont_write_bytecode = True
from run import HERE, ROOT, WORK, RESULTS, configure, run

HARNESS = r'''
#![allow(dead_code, unused_imports)]
#[path = "@SOL@"] mod sol;
use std::io::{self, BufRead};
fn decode(hex: &str) -> String {
    String::from_utf8((0..hex.len()).step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i+2], 16).unwrap()).collect()).unwrap()
}
fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let mut fields = line.split(' ');
        let host = decode(fields.next().unwrap());
        let mut matched = false;
        for field in fields {
            let site = decode(field);
            // Evaluate every single-site call, even after a match.
            matched |= sol::host_within(&host, &site);
        }
        println!("{}", matched);
    }
}
'''


def oracle(host, sites):
    # Independent character/label specification, not the native suffix byte loop.
    folded = ''.join(chr(ord(c) + 32) if 'A' <= c <= 'Z' else c for c in host)
    labels = folded.split('.')
    return any(labels[-len(site.split('.')):] == site.split('.') for site in sites)


def valid_site(site):
    return (len(site) <= 253 and not site.isdigit() and
            all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', x)
                for x in site.split('.')))


def cases(n, seed):
    direct = [('', ['k']), ('k', ['k']), ('K', ['k']), ('K', ['k']),
              ('K.k', ['k']), ('Kakao.com', ['kakao.com']), ('İ', ['i']),
              ('i\u0307', ['i']), ('xkakao.com', ['kakao.com']),
              ('x.kakao.com', ['kakao.com']), ('.k', ['k']), ('..k', ['k']),
              ('k.', ['k']), ('KAKAO.COM', ['kakao.com']),
              ('a\0.k', ['k']), ('a' * 4094 + '.k', ['k']),
              ('a' * 4096, ['a']), ('x', ['k', 'x', 'z']),
              ('é', ['xn--9ca']), ('ſ', ['s'])]
    urls = [(u, s) for u, s in [
        ('https://K/', ['k']), ('https://Kakao.com/', ['kakao.com']),
        ('https://İ/', ['i']), ('https://é/', ['xn--9ca']),
        ('https://KAKAO.COM/', ['kakao.com']), ('https://kakao.com./', ['kakao.com']),
        ('https://xkakao.com/', ['kakao.com']), ('https://x.kakao.com/', ['kakao.com']),
        ('https://user:pw@%6b/', ['k']), ('http://127.1/', ['example.com']),
        ('http://[::1]:80/', ['example.com']), ('mailto:k@example.com', ['example.com']),
        ('not a URL', ['k']), ('file:///tmp/a', ['k']),
        ('custom://K/', ['k']), ('https://%zz/', ['k']),
        ('https://user@evil.test@k/', ['k']), ('https://k:99999/', ['k'])]]
    edge_counts = {'direct': len(direct), 'real_path': len(urls)}
    r = random.Random(seed)
    pool = ['k', 'i', 'kakao.com', 'example.com', 'a-b.test', 'xn--9ca', 'localhost']
    for _ in range(n):
        label = ''.join(r.choice('abcxyz0123456789') for _ in range(r.randint(1, 20)))
        sites = r.sample(pool + [label + '.test'], r.randint(1, 3))
        site = r.choice(sites)
        variants = [site, site.upper(), 'x.' + site, 'x' + site, site + '.',
                    '.' + site, 'a..' + site, '', site.replace('k', 'K'),
                    'K', 'İ', 'é.' + site, '😀.' + site, site + 'x',
                    'K.' + site, '\0' + site, 'a' + site[1:],
                    ''.join(c.upper() if r.randrange(2) else c for c in site)]
        direct.append((r.choice(variants), sites))
        host = r.choice(variants + ['127.0.0.1', '[::1]', 'é', '%6b',
                                   '%4b.' + site, '%zz', 'Kakao.com', 'İ.test'])
        scheme = r.choice(['https', 'http', 'ftp', 'ws', 'file', 'custom'])
        user = r.choice(['', 'user:pw@', 'kakao.com@'])
        port = r.choice(['', ':80', ':443', ':8080', ':99999'])
        urls.append((f'{scheme}://{user}{host}{port}/path?q=K#frag', sites))
    inputs = [dict(mode=mode, input=value, sites=sites)
              for mode, rows in [('direct', direct), ('real_path', urls)]
              for value, sites in rows]
    assert all(1 <= len(c['sites']) <= 3 and all(map(valid_site, c['sites'])) for c in inputs)
    return inputs, edge_counts


def portable(value):
    # Diagnostics can contain tool/source paths; never persist absolute paths.
    if isinstance(value, dict):
        return {k: portable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [portable(v) for v in value]
    if isinstance(value, str):
        value = value.replace(str(ROOT) + '/', '')
        return re.sub(r'(?<![\w:])/(?:[^\s\"\']+)', '<absolute-path>', value)
    return value


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--seed', type=int, default=12345)
    ap.add_argument('--n', type=int, default=20_000, help='random cases per mode')
    args = ap.parse_args()
    if args.n < 0:
        ap.error('--n must be nonnegative')
    summary = dict(seed=args.seed, random_cases_per_mode=args.n, runs={})
    differences = []
    failed = False
    try:
        g2, summary['tools'] = configure()
        inputs, summary['edge_cases'] = cases(args.n, args.seed)
        observed = [json.loads(line) for line in run(
            ['node', HERE / 'host_within.mjs'],
            ''.join(json.dumps(c) + '\n' for c in inputs)).splitlines()]
        if len(observed) != len(inputs):
            raise RuntimeError('Node output count mismatch')
        active = []
        for index, (c, result) in enumerate(zip(inputs, observed)):
            if result['host'] is not None:
                assert len(result['host'].encode()) <= 4096
                active.append((index, c, result, oracle(result['host'], c['sites'])))
        payload = ''.join(' '.join(s.encode().hex() for s in [v['host']] + c['sites']) + '\n'
                          for _, c, v, _ in active)
        for compiler in ('py', 'rs'):
            for backend in ('rust', 'llvm'):
                name = f'{compiler}/{backend}'
                row = summary['runs'][name] = dict(status='error', modes={})
                try:
                    work = WORK / ('host_within_' + compiler + '_' + backend)
                    work.mkdir(exist_ok=True)
                    compiled = g2.compile_pruv(compiler, str(HERE / 'host_within.pruv'), str(work), backend)
                    row['verification'] = portable(compiled)
                    if compiled['rc'] != 0:
                        raise RuntimeError(json.dumps(portable(compiled)))
                    row['verified'] = True
                    harness = work / 'main.rs'
                    harness.write_text(HARNESS.replace('@SOL@', compiled['rs']))
                    extra = []
                    if compiled['ll']:
                        extra, error = g2.build_llvm_objects(compiled['ll'], 'host_within', str(work))
                        if error:
                            raise RuntimeError(error)
                    exe = work / 'runner'
                    run([g2.RUSTC, '-O', '--edition', '2021', '-C', 'target-cpu=native', harness, '-o', exe] + extra)
                    lines = run([exe], payload).splitlines()
                    if len(lines) != len(active) or any(x not in ('true', 'false') for x in lines):
                        raise RuntimeError('Native output count/value mismatch')
                    for mode in ('direct', 'real_path'):
                        total = sum(c['mode'] == mode for c in inputs)
                        tested = sum(c['mode'] == mode for _, c, _, _ in active)
                        row['modes'][mode] = dict(total=total, tested=tested, skipped=total-tested,
                            equal=0, ts_true_pruv_false=0, ts_false_pruv_true=0,
                            pruv_oracle_pass=0, ts_oracle_pass=0)
                    for (index, c, v, want), line in zip(active, lines):
                        p, t = line == 'true', v['ts']
                        counts = row['modes'][c['mode']]
                        category = 'equal' if t == p else 'ts_true_pruv_false' if t else 'ts_false_pruv_true'
                        counts[category] += 1
                        counts['pruv_oracle_pass'] += p == want
                        counts['ts_oracle_pass'] += t == want
                        failed |= p != want
                        if p != t:
                            differences.append(dict(compiler_backend=name, case_index=index, **c,
                                host=v['host'], host_hex=v['host'].encode().hex(),
                                site_hex=[s.encode().hex() for s in c['sites']],
                                input_bytes=len(c['input'].encode()), classification=category,
                                ts=t, pruv=p, expected=want, pruv_meets_spec=p == want,
                                ts_meets_spec=t == want))
                    row['status'] = 'ok' if all(v['tested'] == v['pruv_oracle_pass'] for v in row['modes'].values()) else 'wrong'
                    print(name + ': ' + json.dumps(row['modes']), flush=True)
                except Exception as exc:
                    row['error'] = portable(str(exc))
                    failed = True
                    print(name + ': ' + row['error'], file=sys.stderr, flush=True)
    except Exception as exc:
        summary['error'] = portable(str(exc))
        failed = True
        print(summary['error'], file=sys.stderr)
    differences.sort(key=lambda d: (d['input_bytes'], sum(map(len, d['sites'])),
                                    d['host_hex'], d['sites'], d['compiler_backend']))
    summary.update(status='error' if failed else 'ok', difference_records_total=len(differences),
                   difference_records_saved=min(50, len(differences)),
                   difference_order='input bytes, site bytes, host hex, sites, compiler/backend',
                   real_path_differences=sum(d['mode'] == 'real_path' for d in differences))
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / 'host_within_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    (RESULTS / 'host_within_differences.jsonl').write_text(''.join(json.dumps(d) + '\n' for d in differences[:50]))
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
