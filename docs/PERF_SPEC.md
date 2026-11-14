# Pruv performance standard (P1)

Goal (BLUEPRINT.md): Pruv code runs as fast as the same program in Rust, or faster where proofs let the compiler
drop checks. This file fixes what "as fast" means: which programs, which Rust baseline, which inputs, how they are
timed and what counts as passing. Every Pruv compiler/backend pair (py/rust, py/llvm, rs/rust, rs/llvm) is held to it.

## Programs

Every program of the public suites that language comparisons use is a target: the Benchmarks Game (all ten), plb2
(all four), kostya/benchmarks (all six), Are We Fast Yet (all fourteen) and the nativejson-benchmark corpora. Each
has a published program that is the reference; the Pruv port must compute the same thing with the same algorithm.
A program that needs a language feature Pruv does not have yet stays in the list with that feature named; the
feature is built and the program ported later. Nothing is dropped for being hard.

### Status

| Program | Suite | Pruv needs first | Status |
|---|---|---|---|
| fannkuch-redux | Benchmarks Game | - | P1 |
| binary-trees | Benchmarks Game | - | P1 |
| reverse-complement | Benchmarks Game | - | P1 |
| brainfuck | kostya | - (flat opcode array; the published `Box<[Op]>` tree needs arrays of enum values) | P1 |
| primes | kostya | - (trie as an arena with an i64 map) | P1 |
| sudoku | plb2 | - (shifts by 16 written as `* 65536`, `/ 65536`, `% 65536` on non-negative values) | P1 |
| nqueen | plb2 | bitwise `& \| ^ << >>` on i64 | P2 |
| bedcov | plb2 | bitwise operators, wrapping u32/u64 arithmetic (hash RNG) | P2 |
| k-nucleotide | Benchmarks Game | map keyed by byte strings (or packed i64 keys) | P2 |
| base64 | kostya | bitwise operators | P2 |
| json | kostya, nativejson (twitter, citm_catalog) | - for parse+walk (L3 JSON parser exists); f64 for canada.json and number values | P2 |
| fasta | Benchmarks Game | f64 | P3 |
| n-body | Benchmarks Game | f64, sqrt | P3 |
| spectral-norm | Benchmarks Game | f64 | P3 |
| mandelbrot | Benchmarks Game | f64, bitwise operators | P3 |
| matmul | plb2, kostya | f64 | P3 |
| pidigits | Benchmarks Game | arbitrary-precision integers (GMP binding or Pruv bigint) | P3 |
| regex-redux | Benchmarks Game | regex engine (binding or Pruv) | P3 |
| havlak | kostya, AWFY | object graphs with sharing (arena form possible) | P3 |
| Bounce, List, Permute, Queens, Sieve, Storage, Towers | AWFY | integer only; shared mutable objects in List/Storage/Towers (arena form) | P2 |
| Richards, DeltaBlue, Json | AWFY | polymorphism / closures (enum dispatch form) | P3 |
| CD, Mandelbrot, NBody | AWFY | f64 | P3 |

AWFY has no verified Rust port; its Rust baseline is written here in the same arena/enum form as the Pruv port and
checked against the Java output.

### P1 details

| # | Program | Suite | What it stresses | Timed input | Dev input | Rust reference |
|---|---|---|---|---|---|---|
| 1 | fannkuch-redux | Benchmarks Game | small arrays, permutations, branches | n=12 | n=10 | [fannkuchredux-rust-4](https://benchmarksgame-team.pages.debian.net/benchmarksgame/program/fannkuchredux-rust-4.html) (rayon loop made sequential) |
| 2 | binary-trees | Benchmarks Game | allocation, recursion | depth 21 | 18 | [binarytrees-rust-1](https://benchmarksgame-team.pages.debian.net/benchmarksgame/program/binarytrees-rust-1.html) (the Rust side may use the same Vec arena as Pruv) |
| 3 | reverse-complement | Benchmarks Game | byte scans, table lookup, large buffers | FASTA n=25,000,000 | 250,000 | [revcomp-rust-3](https://benchmarksgame-team.pages.debian.net/benchmarksgame/program/revcomp-rust-3.html) (sequential) |
| 4 | nqueen (P2) | plb2 | bit operations, backtracking | n=15 | 12 | [plb2 nqueen.rs](https://github.com/attractivechaos/plb2/blob/master/src/rust/nqueen.rs) |
| 5 | sudoku | plb2 | small fixed arrays, search | hard20 x 200 = 4000 puzzles | hard20 x 2 | [plb2 sudoku.rs](https://github.com/attractivechaos/plb2/blob/master/src/rust/sudoku.rs) |
| 6 | bedcov (P2) | plb2 | sorting, interval index, i64 arithmetic | n=1,000,000, seed 11 | 10,000 | [plb2 bedcov.rs](https://github.com/attractivechaos/plb2/blob/master/src/rust/bedcov.rs) |
| 7 | brainfuck | kostya/benchmarks | interpreter loop, byte dispatch | bench.b | bench.b (short program) | [kostya bf.rs](https://github.com/kostya/benchmarks/blob/master/brainfuck/bf.rs/src/main.rs) (QUIET=1) |
| 8 | primes | kostya/benchmarks | sieve, trie of digit strings, collections | limit 5,000,000, prefix 32338 | 50,000 | [kostya primes.rs](https://github.com/kostya/benchmarks/blob/master/primes/primes.rs/src/main.rs) |

Plus the project workload already measured in RESULTS.md (L3-1 Claude window import against the hand-written Rust in
`bench/l3/claude/handrust`).

The revcomp input is made by the fasta generator outside the timed region, so revcomp does not wait for f64.

## Baselines

- Primary: the matched Rust program. It is the reference above with integer widths, containers and the algorithm
  changed only as needed to match the Pruv port (Pruv integers are i64 and u8), single-threaded, with no `unsafe`
  that the reference does not already have. Pruv is compared against this one.
- Secondary: the reference program as published (single-threaded), reported for information.
- Rust flags: `rustc -C opt-level=3 -C codegen-units=1 -C target-cpu=native`, edition 2021, rustc version recorded.
  The rust backend's generated code is built with the same flags; the llvm backend's objects are built at O3 for the
  same CPU.

## Method

The Pruv port exposes one pure function; a small Rust `main` reads the input (I/O is outside the timed region),
calls the function once, prints the result and the call's wall time. Output must be identical to the matched Rust
program's on the dev and timed inputs before any time is recorded.

- Machine quiet, single-threaded, same binary per variant for the whole session.
- 3 warm-up process runs per variant, then 30 timed rounds; every round runs each variant once, in a fresh order
  (interleaved, so drift hits all variants alike).
- Statistic: per variant the mean time; per Pruv pair the ratio Pruv/Rust, with a 95% confidence interval taken on
  the per-round log ratios (t-interval, then exponentiated). Following Georges et al. (OOPSLA 2007) and Kalibera &
  Jones (ISMM 2013) on rigorous timing: repeated independent runs and an interval, not a single number.
- Summary: geometric mean of the ratios over the ported programs, per pair, with the count of
  programs still waiting for a feature next to it.

## Pass rule

- Equal or better: the upper end of the 95% interval is at most 1.05 (no worse than 5%, with confidence).
- Faster: the upper end is below 1.00.
- A pair that misses on a program is a defect of the compiler or of the port, not an accepted result. Each miss is
  fixed, or recorded in RESULTS.md with the measured numbers and the cause.

## Layout

`bench/perf/<program>/` holds the Pruv port (`<program>.pruv`), the matched Rust (`matched.rs`), the published Rust
(`reference.rs`, when it builds standalone), the published algorithm behind the same `bench` interface
(`secondary.rs`, when matched.rs had to change the algorithm; run.py times it and reports it without a verdict) and
the input generator if one is needed. `bench/perf/run.py` builds all
variants, checks outputs and runs the timing above; `bench/perf/run.py --dev` uses the dev inputs and 5 rounds for a
quick check.
