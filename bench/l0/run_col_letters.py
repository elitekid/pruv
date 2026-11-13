#!/usr/bin/env python3
"""Cross-check colLetters over dense, boundary and seeded random inputs."""
import sys
sys.dont_write_bytecode = True
from run_second_bundle import main

if __name__ == '__main__':
    raise SystemExit(main('col_letters'))
