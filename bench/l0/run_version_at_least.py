#!/usr/bin/env python3
"""Cross-check versionAtLeast against an exact Python integer oracle."""
import sys
sys.dont_write_bytecode = True
from run_second_bundle import main

if __name__ == '__main__':
    raise SystemExit(main('version_at_least'))
