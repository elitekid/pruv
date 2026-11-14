#!/usr/bin/env python3
"""Generate the original full workload or a small nested-counter workload."""
from pathlib import Path
import sys

mode, out = sys.argv[1:]
if mode == 'full':
    data = Path(__file__).with_name('bench.b').read_bytes()
elif mode == 'dev':
    data = (b"++++++++++[" + b">++++++++++[" * 6 + b"-]" + b"<-]" * 6
            + b"+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++.++.++.")
else:
    raise SystemExit('expected dev or full')
Path(out).write_bytes(data)
