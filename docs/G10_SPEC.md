# G10: File I/O Effect and Owned File Handles (first slice)

Status: **Design fixed for implementation, 2026-11-12; not implemented.**

BLUEPRINT row G10 ("refine the `io` effect and bundle with resource lifetimes (Stage 5 item 3)") is large. This
document fixes only its first slice: one new effect for the file system and one owned resource type, `File`,
whose lifetime is enforced by the ownership checker that G6 already has. Processes, network, async and the other
Stage 5 items are later slices (section 9).

The slice is built in four batches A0-A3 and a bounded Q batch, like G5. Each batch finishes the Python compiler
first, then its byte-identical Rust port, and passes the differential gates before the next batch starts. The
numbered decisions in sections 4-8 are binding acceptance criteria, not measured results.

## 1. Goal and foundation

Goal: a Pruv program can read a file and write a file, the type checker proves that every handle is used by one
owner, never used after it was closed or moved, and always closed on every path (including early `return`), and the
verifier proves that a read is only attempted on a handle opened for reading and a write only on one opened for
writing. Failures of the operating system (missing file, permission, disk full) are values the program must look
at, not crashes.

The design adds no new checker. A `File` is one more owned catalog type next to `Vec`, `HashMap` and `String`, so
use-after-close, double close and leaks are all instances of rules that already exist and are already tested.

### 1.1 Verified repository facts

Read on 2026-11-12 in the working tree at commit `cbe33cc`:

- Effects today are exactly `io` and `alloc`. The Python parser rejects any other name in `pruvc/vparser.py`
  (function header, `if e.val not in ("io", "alloc")`, hint "effects are io, alloc"); the Rust parser has the same
  check in `pruvc-rs/crates/pruv-core/src/parser.rs` (around line 994). `vast.py` documents `Function.effects` as a
  subset of `["io", "alloc"]`.
- Effect checking is a set comparison. `pruvc/check.py` collects `used_effects` while typing a body; `print` adds
  `io`; a call adds the callee's effects; after the body, every used effect missing from the declaration is a
  `missing_effect` error (stage `effect`). The Rust port is in `pruvc-rs/crates/pruv-core/src/check.rs` (around line
  2921).
- The LLVM host wrapper flushes standard output when `io` is among the effects (`pruvc/llvmgen.py`, around line 3098).
- Owned types are a closed table: `pruvc/typeinfo.py` `COLLECTION_ARITY = {"vec": 1, "hashmap": 2, "string": 0}`,
  `is_collection` and `contains_collection`. The placement rules (no collections inside structs, arrays, Options or
  map keys) are reported as `foreign_owned_type` in `pruvc/check.py`.
- The catalog is a fixed dictionary built in `pruvc/foreign.py` by `_add(name, bounds, build, effects)`; a parameter
  built with `_p(name, type, True)` is a `take` parameter. `string_new`, `string_push_str`, `string_byte` and
  `string_to_str` show the pattern for a non-generic owned type with byte observers.
- Ownership is checked by `_Ownership` / `check_ownership` in `pruvc/foreign.py`, called from `check.py` right after
  typing (`check_ownership(f, s.funcs)`). It tracks borrowed (unmarked) parameters and owned (`take`) parameters and
  locals, kills a binding on `move`, reports a binding that is moved on only some paths (`foreign_move`), a loop that
  leaves an outer owner dead (`foreign_loop_move`) and misuse of a borrowed collection (`foreign_borrow`).
- Owned values are freed at scope exit: the Rust backend relies on Rust drop; the LLVM backend calls
  `g6_drop` / `@pruv_drop__*` helpers (`pruvc/llvmgen.py`, `g6_drop`). The G6 LLVM path links a generated Rust shim
  (SPEC.md 6d "Build"); `--emit exe|obj` rejects such programs with `codegen/foreign_target`.
- Run-time checking of catalog `requires` already exists (`--foreign-checks requires|all|off`, SPEC.md 6d) with
  exit code 101 and the message prefix `pruv: foreign requires violated:`.

To confirm in A0 (not read yet, do not assume): how `verify.py` encodes `String` (length plus byte map) and whether
that encoding can be reused for the `File` buffer unchanged.

### 1.2 Non-goals of this slice

- Processes (`proc`), network (`net`), environment variables, clocks: later G10 slices, each with its own effect name.
- Async and `await`: deferred until G7 decides the concurrency model.
- G7 concurrency (sharing a handle between threads): deferred to G7.
- Stage 5 item 1 (automatic caching), item 2 (`reads state.x`, `io none` contracts) and item 4 (`cost O(n)`): not in
  this slice; `io none` would become meaningful only once effects are fine-grained, which this slice starts.
- Directories, seeking, metadata, appending, partial reads, streaming: later. This slice reads a whole file and
  writes a whole file.
- Proving anything about the contents of the file system across calls (a file written and read back is not proved
  to contain the same bytes).
- Linear "must call `file_close`" typing. Dropping a handle closes it (section 3.3).

## 2. User surface

### 2.1 The `fs` effect

`fs` is a third effect name, beside `io` and `alloc`: `fn f(...) -> T ! fs, alloc`. A function that calls any `file_*`
operation marked `fs` (directly or through a callee) must declare `fs`; otherwise `missing_effect`, exactly as for
`io`. `io` keeps its current meaning (writes to standard output with `print`) and is not renamed: existing programs do
not change. There is one spelling per effect, no dotted names and no aliases. Unknown effect names stay a parse
error whose hint lists `io, alloc, fs`.

### 2.2 The `File` type

`File` is an owned type with the same placement rules as `String`: a local, a `take` parameter, a borrowed (unmarked)
parameter or a result; never inside a struct, enum, Option, Result, array, `Vec` or `HashMap`; never a parameter or
result of a host entry (the existing "collection-bearing functions are internal" rule). A host entry that does file
work takes a `path: str` and returns ordinary values.

Ownership is the G6 rule unchanged: one owner; pass it with `move f`; after `move f`, `f` is dead until reassigned;
moved on only some paths means dead after the join; a loop must leave every outer owner alive at the end of each
iteration; a borrowed `File` parameter is read only for the call.

### 2.3 Catalog operations

| Operation | Effects | Contract (catalog `requires` / `ensures`) |
|---|---|---|
| `file_open_read(path: str) -> File` | `fs` | ensures `file_readable(result) == file_ok(result)`, `!file_writable(result)`, `file_size(result) == 0` |
| `file_create(path: str) -> File` | `fs` | ensures `file_writable(result) == file_ok(result)`, `!file_readable(result)`, `file_size(result) == 0`; truncates an existing file |
| `file_read_all(take f: File) -> File` | `fs, alloc` | requires `file_readable(f)`; ensures `!file_writable(result)`, `file_readable(result) == file_ok(result)`, `file_ok(result) ==> file_size(result) >= 0`, `!file_ok(result) ==> file_size(result) == 0` |
| `file_write_str(take f: File, text: str) -> File` | `fs` | requires `file_writable(f)`; ensures `!file_readable(result)`, `file_writable(result) == file_ok(result)`, `file_size(result) == 0` |
| `file_write_bytes(take f: File, data: [u8]) -> File` | `fs` | as `file_write_str` |
| `file_close(take f: File) -> bool` | `fs` | ensures `result ==> file_ok(f)` (true only if every write and the final flush succeeded) |
| `file_ok(f: File) -> bool` | none | observer: no operation on this handle has failed |
| `file_readable(f: File) -> bool` | none | observer: opened for reading and ok |
| `file_writable(f: File) -> bool` | none | observer: created for writing and ok |
| `file_size(f: File) -> i64` | none | observer: number of bytes read into the handle; ensures `result >= 0` |
| `file_byte(f: File, i: i64) -> i64` | none | requires `0 <= i && i < file_size(f)`; ensures `0 <= result && result <= 255` |

All observers may be used in code and in contracts. Paths are relative to the process working directory. The
read-all buffer lives inside the handle, so reading needs no second owned value, and its bytes are reached with
`file_byte` the way `string_byte` reaches a `String`.

Example (the only way to write it):

```
fn sum_bytes(f: File) -> i64
  requires file_size(f) <= 1000000
{
  let mut s: i64 = 0;
  let mut i: i64 = 0;
  while i < file_size(f)
    invariant 0 <= i && i <= file_size(f) && 0 <= s && s <= 255 * i
    decreases file_size(f) - i
  {
    s = s + file_byte(f, i);
    i = i + 1;
  }
  return s;
}

pub fn checksum(path: str) -> i64 ! fs, alloc
  ensures result >= -1
{
  let f: File = file_open_read(path);
  if !file_readable(f) {
    return -1;                       // f is dropped (closed) here
  }
  let g: File = file_read_all(move f);
  if !file_ok(g) || file_size(g) > 1000000 {
    return -1;
  }
  return sum_bytes(g);               // g is borrowed by the call, dropped after it
}
```

## 3. Static rules

### 3.1 Effects

`fs` joins the effect set in the parser (both compilers) and `vast.Function.effects`. Every catalog operation listed
with `fs` adds `fs` to `used_effects` like a call to a user function with `! fs`. Nothing else changes in
`missing_effect`.

### 3.2 Ownership and lifetime

`File` is added to the owned-type table (`COLLECTION_ARITY["file"] = 0` and the spelling `File`), so `is_collection`,
`contains_collection`, the placement checks and `_Ownership` apply without new code paths. Consequences, each an
existing diagnostic:

- use after `file_close(move f)` or after any `move f`: `foreign_move` (use of a moved binding);
- closing twice: the second `move f` is a use of a dead binding: `foreign_move`;
- handle moved on only one branch and used after the join: `foreign_move`;
- a loop that closes an outer handle and does not reassign it: `foreign_loop_move`;
- closing or returning a borrowed handle parameter: `foreign_borrow`;
- `File` inside a struct, array, Option or collection: `foreign_owned_type`;
- `File` in a host entry signature: the existing host-entry rule for owned types (`foreign_export`).

### 3.3 Closing

Every live owner at scope exit (block end, `return`, loop `break`/`continue` leaving the scope) is dropped by the
existing drop machinery; dropping a `File` closes it and ignores errors. So no path leaks a handle (Stage 5 item 3).
`file_close` is the only way to learn whether buffered writes reached the disk; a program that needs that answer
calls it. Requiring a call to `file_close` (linear typing) is deferred (section 9).

## 4. Verification (binding)

1. A `File` value is modelled as a record of `ok`, `readable`, `writable` (Bool), `size` (Int) and a byte map
   (Int -> Int), using the same encoding as `String` if A0 confirms it fits (section 1.1); otherwise a new SMT
   datatype with exactly these fields.
2. The observers are field reads; `file_byte(f, i)` is the byte map at `i`, constrained to 0..255 by the catalog
   ensures.
3. Every `fs` operation's result is a fresh unconstrained value assumed to satisfy the catalog `ensures` (the file
   system is not modelled). Two opens of the same path are unrelated.
4. Catalog `requires` are proof obligations at the call, like any catalog call: reading a handle not proved
   `file_readable` or writing one not proved `file_writable` does not verify.
5. `ensures` of a user function may mention `file_*` observers of its parameters and result.
6. `--infer` treats `File` locals like `String` locals; it infers no `fs`-specific invariants.

## 5. Rust backend (binding)

1. The generated runtime prelude gets one struct
   `PruvFile { file: Option<std::fs::File>, ok: bool, readable: bool, writable: bool, buf: Vec<u8> }`; `File` maps to
   `PruvFile`. Operations never panic on an I/O error: they set `ok = false`, drop the inner file and keep going.
2. `file_close` flushes and syncs nothing beyond `std::io::Write::flush` and reports `ok && flush succeeded`.
   Dropping a `PruvFile` drops the inner `std::fs::File` (closes it); errors are ignored.
3. Run-time checks of catalog `requires` follow `--foreign-checks` unchanged: with `--no-verify`, reading a
   non-readable handle exits 101 with `pruv: foreign requires violated:`.
4. Host entries with `! fs` are allowed; the File itself never crosses the host boundary.

## 6. LLVM backend (binding)

1. `File` uses the G6 shim bridge: the Rust shim generated with `--rust-bindings` holds `PruvFile` (the same code as
   section 5), the LLVM code holds an opaque pointer and calls shim functions for every operation and for drop
   (`@pruv_drop__File` through `g6_drop`).
2. `--emit exe|obj` rejects programs that use `File` with `codegen/foreign_target`, like every G6 program that needs
   the shim.
3. The stdout flush for `io` (llvmgen host wrapper) is unchanged and independent of `fs`.

## 7. Diagnostics and compatibility (binding)

1. No new error codes. Effects use `missing_effect` and the parse error for unknown names (hint now
   "effects are io, alloc, fs"); lifetime errors use `foreign_move`, `foreign_loop_move`, `foreign_borrow`,
   `foreign_owned_type`, `foreign_export`; unproved catalog `requires` use the existing verification failure.
2. Programs without `fs` and without `File` produce byte-identical output to the previous compiler on both backends
   (checked by `tests/run_all.py --compare-rows` with unchanged rows).
3. `SPEC.md` gets one new page, section 6h "Files (G10)", of at most one page, written in A3.

## 8. Batches (binding gates)

Shared gate for every batch: Python first, then the Rust port in the same batch; `tests/run_all.py --backend both`
passes with py and rs; new rows are added to `tests/run_all_rows.txt`; py/rs outputs are byte-identical on all new
rows; `cargo test` for `pruvc-rs` passes; CI is green after the push.

- **A0 frontend.** `fs` effect in both parsers and the effect checker; `File` in the owned-type table; catalog
  entries with signatures and effects (contracts may be `ensures true` placeholders until A1); must_reject roots for
  each item in section 3.2 and for a missing `fs` (at least 8 roots, each with a json naming the expected code).
  A checked program that uses `File` or a `file_*` operation stops with a staging guard
  (`codegen/unsupported_type`, "files (G10) are not implemented by the verifier yet") in every mode until A1 moves
  the guard after verification and A2/A3 remove it per backend, like the G5 guard. Programs that only declare `! fs`
  are not guarded. Confirm the section 1.1 open question in a short note in this document.
- **A1 verification.** Section 4. Proof rows: the example of section 2.3 verifies; a read of a handle from
  `file_create`, a write to a handle from `file_open_read`, `file_byte` past `file_size`, and a missing
  `file_readable` check after open each fail to verify (must_reject, default mode).
- **A2 Rust backend.** Section 5. Runtime rows that create, write, close, reopen, read back and compare bytes in a
  temporary directory chosen by the test harness; a missing file gives `file_ok == false`, not a crash; a
  `--no-verify` read of a write handle exits 101; a handle dropped without `file_close` leaves a complete file.
- **A3 LLVM and SPEC.** Section 6 and the SPEC page; every A2 runtime row also passes on the LLVM backend.
- **Q.** `bench/g10/` with two fresh problems (a byte transformation copying one file to another, and a line/field
  counter), reference solutions, grader and at least 40 explicit incorrect mutants (wrong mode, read without check,
  use after close via a renamed binding, missing close of a write before reopen, off-by-one `file_byte`), zero
  mutants wrongly verified; one compiler fault injection per section 3.2 rule family and per section 4 item 4,
  each detected by a named test; one independent author (spec and problems only) solves both problems, both
  backends; measurement: reading and summing a 10 MB file is within 1.5x of a hand-written Rust program on both
  backends.

## 9. Deferred work

- `proc` and `net` effects with their handle types (`Process`, `Socket`), each reusing this pattern.
- Linear handles: a `File` that was written must reach `file_close` (a new "must consume" rule in `_Ownership`).
- Streaming reads/writes, seeking, appending, directories, metadata.
- `io none` / `reads` contracts (Stage 5 item 2) and a finer split of `io` (stdout vs stderr).
- Async (after G7), cost bounds (Stage 5 item 4), caching (Stage 5 item 1).
