# -*- coding: utf-8 -*-
"""Contract-size counter for Pruv solutions.

usage: contract_size.py OUT.json DIR_A DIR_B [...]

For each dir and each q0*.pruv: count clauses (requires/ensures/invariant/
decreases/assert), their lines and tokens, and the remaining code lines.
Writes JSON {dir: {file: {...}, "total": {...}}} and prints a table.
"""
import glob
import json
import os
import re
import sys

KINDS = ("requires", "ensures", "invariant", "decreases", "assert")
STMT = ("let", "if", "else", "while", "return", "for", "loop", "break", "continue")
TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"'
    r"|[A-Za-z_][A-Za-z_0-9]*"
    r"|[0-9][0-9_]*"
    r"|==>|==|!=|<=|>=|&&|\|\||\.\."
    r"|\S"
)
ASSIGN_RE = re.compile(r"^[A-Za-z_]\w*(\[.*\])?\s*=[^=>]")
FIRST_RE = re.compile(r"^[A-Za-z_]\w*|^.")


def strip_comment(line):
    out = []
    in_str = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < len(line):
                out.append(line[i + 1])
                i += 1
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
                out.append(ch)
            elif line.startswith("//", i):
                break
            else:
                out.append(ch)
        i += 1
    return "".join(out).rstrip()


def first_token(line):
    m = FIRST_RE.match(line.strip())
    return m.group(0) if m else ""


def is_stop(line):
    """True if the line starts something that is not a clause continuation."""
    s = line.strip()
    t = first_token(s)
    if t in KINDS or t in STMT or t in ("fn", "{", "}"):
        return True
    return bool(ASSIGN_RE.match(s))


def count_file(path):
    with open(path, encoding="utf-8") as f:
        raw = f.read().split("\n")
    lines = [strip_comment(l) for l in raw]
    n = len(lines)
    kind_of = [None] * n   # clause kind per line
    sig = [False] * n
    i = 0
    clauses = []           # (kind, [line idx])
    while i < n:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        t = first_token(s)
        if t == "fn":
            sig[i] = True
            j = i + 1
            if "{" not in s:
                while j < n:
                    sj = lines[j].strip()
                    if not sj:
                        j += 1
                        continue
                    if first_token(sj) in KINDS or sj.startswith("{"):
                        break
                    sig[j] = True
                    j += 1
            i = j
            continue
        if t in KINDS:
            idx = [i]
            if t == "assert":
                j = i
                while ";" not in lines[j] and j + 1 < n:
                    j += 1
                    if lines[j].strip():
                        idx.append(j)
                    else:
                        pass
                i = j + 1
            else:
                j = i + 1
                while j < n:
                    sj = lines[j].strip()
                    if not sj:
                        j += 1
                        continue
                    if is_stop(sj):
                        break
                    idx.append(j)
                    j += 1
                i = j
            for k in idx:
                kind_of[k] = t
            clauses.append((t, idx))
            continue
        i += 1

    res = {k: {"clauses": 0, "lines": 0, "tokens": 0} for k in KINDS}
    for kind, idx in clauses:
        res[kind]["clauses"] += 1
        res[kind]["lines"] += len(idx)
        for k in idx:
            res[kind]["tokens"] += len(TOKEN_RE.findall(lines[k]))
    code = 0
    for k in range(n):
        if lines[k].strip() and kind_of[k] is None and not sig[k]:
            code += 1
    out = {
        "by_kind": res,
        "clauses": sum(v["clauses"] for v in res.values()),
        "contract_lines": sum(v["lines"] for v in res.values()),
        "contract_tokens": sum(v["tokens"] for v in res.values()),
        "code_lines": code,
    }
    return out


def main(argv):
    if len(argv) < 3:
        sys.stderr.write("usage: contract_size.py OUT.json DIR_A DIR_B [...]\n")
        return 2
    out_path = argv[1]
    dirs = argv[2:]
    result = {}
    for d in dirs:
        files = sorted(glob.glob(os.path.join(d, "q0*.pruv")))
        per = {}
        tot = {"by_kind": {k: {"clauses": 0, "lines": 0, "tokens": 0} for k in KINDS},
               "clauses": 0, "contract_lines": 0, "contract_tokens": 0, "code_lines": 0}
        for p in files:
            r = count_file(p)
            per[os.path.basename(p)] = r
            for k in ("clauses", "contract_lines", "contract_tokens", "code_lines"):
                tot[k] += r[k]
            for kind in KINDS:
                for f in ("clauses", "lines", "tokens"):
                    tot["by_kind"][kind][f] += r["by_kind"][kind][f]
        per["total"] = tot
        result[d] = per
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write("\n")

    names = sorted({fn for d in dirs for fn in result[d]} - {"total"}) + ["total"]
    hdr = "%-10s %-34s %8s %16s %14s %10s" % (
        "file", "dir", "clauses", "contract tokens", "contract lines", "code lines")
    print(hdr)
    print("-" * len(hdr))
    for fn in names:
        for d in dirs:
            r = result[d].get(fn)
            if r is None:
                continue
            print("%-10s %-34s %8d %16d %14d %10d" % (
                fn, d[-34:], r["clauses"], r["contract_tokens"],
                r["contract_lines"], r["code_lines"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
