# P2 design: bit operations and wrapping arithmetic

Smallest feature that ports plb2 nqueen, kostya base64 and plb2 bedcov with their published algorithms
(PERF_SPEC.md). No new operator syntax, no unsigned types, no change to `+ - * / %`.

## What the three programs need (read from the published sources)

- nqueen ([nqueen.rs](https://github.com/attractivechaos/plb2/blob/master/src/rust/nqueen.rs)): `| & ^ << >>` on
  column/diagonal masks. No complement, no wrapping multiply. Masks stay non-negative at n=15.
- base64: the kostya Rust driver calls the `base64` 0.22.1 crate, so the algorithm to match is the crate's engine.
  Encoder ([mod.rs](https://github.com/marshallpierce/rust-base64/blob/v0.22.1/src/engine/general_purpose/mod.rs#L44)):
  big-endian u64 load, `>> 58,52,46,40,34,28,22,16`, `& 63`, 6 input bytes per step unrolled 4 times; tail with u8
  shifts. Decoder ([decode.rs](https://github.com/marshallpierce/rust-base64/blob/v0.22.1/src/engine/general_purpose/decode.rs#L160),
  [decode_suffix.rs](https://github.com/marshallpierce/rust-base64/blob/v0.22.1/src/engine/general_purpose/decode_suffix.rs#L112)):
  sextets widened to u64, `<<` and `|`, big-endian byte extraction; tail on u32 with `<< 26,20,14,8`, `!0u32`, `&`,
  `>> 24`. Do not replace the word loop with a 3-byte scalar loop.
- bedcov ([bedcov.rs](https://github.com/attractivechaos/plb2/blob/master/src/rust/bedcov.rs)): the RNG is u32 only
  (`wrapping_add(0x9e3779b9)`, xor, `>> 16`/`>> 15`, `wrapping_mul(0x21f0aaad)`/`(0x735a2d97)`); no u64 multiply.
  The interval tree uses `<<`, `>>`, `& 1` and shift-built masks.

## Decisions

1. **Seven pure builtins**, `(i64, i64) -> i64`, allowed in code and contracts: `band`, `bor`, `bxor`,
   `wrapping_shl(a, k)`, `ushr(a, k)` (logical right shift, zero fill), `wrapping_add`, `wrapping_mul`. Ordinary call
   syntax, so precedence, the refinement `|` and `< >` type syntax are untouched. Arguments are evaluated left to
   right once; the names are reserved (no user function, no type arguments). Complement is `bxor(x, -1)`.
2. **Obligations.** Operands may be negative. Only shifts need `0 <= k < 64`, new error `verify/shift_range`.
   `wrapping_shl`, `wrapping_add`, `wrapping_mul` have no result-overflow obligation; ordinary arithmetic inside their
   arguments keeps its obligations. In contracts each argument must be inside i64 (and `k` in 0..64), checked as
   `contract_domain` under the existing short-circuit rules; no silent truncation of mathematical integers.
3. **Z3 encoding.** Values stay `Int`. At each builtin: `Int2BV(64)` on the arguments, exact BV op (`bvand`, `bvor`,
   `bvxor`, `bvshl`, `bvlshr`, `bvadd`, `bvmul`), back to signed Int as `If(u < 2^63, u, u - 2^64)` with
   `u = BV2Int`. Plus per-call facts, guarded by the domain and path condition (no global quantified axioms):
   result in i64; `m >= 0 ==> 0 <= band(x, m) <= m`; `x >= 0 ==> 0 <= band(x, m) <= x`; `a, b >= 0 ==>` `bor`/`bxor`
   in `0..=a+b`; `ushr(x, 0) == x`; `x >= 0 ==> 0 <= ushr(x, k) <= x`; `k > 0 ==> ushr(x, k) >= 0`; constant `k > 0`:
   `ushr(x, k) <= 2^(64-k) - 1` and `ushr(x, k) == U(x) / 2^k` with `U(x) = If(x < 0, x + 2^64, x)`. Proof time is not
   measured yet. pruv-proof's own Z3 C API wrapper (`sys.rs`) has no BV support and needs the wrappers.
4. **u32/u64.** A u64 is the i64 with the same bits (`ushr(-1, 1) == 9223372036854775807`). A u32 is a non-negative
   i64 in 0..=4294967295; programs mask: `wrap32_add(a, b) = band(wrapping_add(a, b), 4294967295)`, same for mul
   (low 32 of low 64 is low 32). bedcov constants in decimal: 2654435769, 569420461, 1935289751. base64 u8/u32 cuts are
   `band(x, 255)` / `band(x, 4294967295)` where the crate truncates.
5. **Emission** (keep `SAFE_ARITH`/`CONTRACT_ARITH` as they are; handle the builtins in the call branch):

   | builtin | Rust | LLVM |
   |---|---|---|
   | band/bor/bxor | `a & b`, `a \| b`, `a ^ b` | `and`/`or`/`xor i64` |
   | wrapping_shl | `((a as u64) << (k as u32)) as i64` | `shl i64`, no flags |
   | ushr | `((a as u64) >> (k as u32)) as i64` | `lshr i64` |
   | wrapping_add/mul | `a.wrapping_add(b)` / `a.wrapping_mul(b)` | `add`/`mul i64`, no `nsw`/`nuw` |

   `--no-verify`: check the shift count before shifting (arithmetic error), never rely on Rust masking or LLVM poison.
   Runtime contracts check i128 arguments are in i64 (and k range) first, then compute, widen to i128; failure is
   `pruv: requires undefined`. Both compilers emit identical helper names, order and strings.
6. **Spec text** (SPEC.md §5, §6 contract arithmetic/domain, runtime modes): the builtins and their 64-bit
   two's-complement meaning, shift rule and `verify/shift_range`, no overflow obligation on the wrapping ones, contracts
   use the same 64-bit meaning with i64-range arguments under `contract_domain` (example: `wrapping_add(9223372036854775807, 1)`
   is `-9223372036854775808`, `band(9223372036854775807 + 1, 255)` is outside the domain), `--no-verify` gives the same
   results and stops on a bad shift count.

## Tests

Runtime (`.pruv`, `.rs`, `.json`, picked up by `tests/run_all.py` automatically; verified and `--no-verify`, rust and
llvm): `p2_rt_bits` (negatives, 0, MAX/MIN, `band(-1, 255) == 255`, masked index used for an array access, same meaning
in contracts), `p2_rt_shifts` (k = 0 and 63, `wrapping_shl(1, 63) == MIN`, `ushr(-1, 1) == MAX`, `ushr(-1, 63) == 1`,
constant-shift range fact, short-circuit-guarded contract shift), `p2_rt_shift_guard` (`--no-verify`, k = 64 stops before
shifting), `p2_rt_contract_guard` (`--no-verify` runtime contract rejects an out-of-i64 argument), `p2_rt_wrap`
(MAX+1 -> MIN, MIN * -1 -> MIN, u32 add/mul masking, contract equals runtime), `p2_rt_kernels` (small nqueen mask loop,
base64 u64 word with high bit and padded tail, seed-11 RNG outputs and the bedcov tree shift expressions, expected
values from the original Rust).

Must-reject (`.pruv`, `.json`): `p2_bits_type` (bool argument, `type/type_mismatch`), `p2_bits_arity` (`type/arity`),
`p2_shift_negative`, `p2_shift_64`, `p2_shift_unbounded` (all `verify/shift_range`), `p2_contract_word_range` and
`p2_contract_shift` (`verify/contract_domain`), `p2_false_bit_claim` (`ensures band(x, 1) == 0` for any x,
`verify/ensures`).

## Batches (Python and its Rust port together in each)

Every batch touches the common set C: `SPEC.md`, `pruvc/check.py`, `pruvc/verify.py`, `pruvc/codegen.py`,
`pruvc/llvmgen.py`, `pruvc-rs/crates/pruv-core/src/{check,modules,codegen,llvmgen}.rs`,
`pruvc-rs/crates/pruv-proof/src/{symbolic,sys}.rs`. Templates: `%` end to end (`grep '"%"'`) and the `truncate` builtin
with its `l3_rt_truncate` tests. `tests/diff_compilers.py --input ... --backend both` checks identical output.

1. band/bor/bxor: registration, typing, BV conversion and facts, contract domain, both backends; tests `p2_rt_bits`,
   `p2_rt_contract_guard`, `p2_bits_type`, `p2_bits_arity`, `p2_contract_word_range`, `p2_false_bit_claim`.
2. wrapping_shl/ushr: code and contract domain, `--no-verify` guard, constant-shift facts; tests `p2_rt_shifts`,
   `p2_rt_shift_guard`, the three `p2_shift_*`, `p2_contract_shift`.
3. wrapping_add/mul and the kernels; tests `p2_rt_wrap`, `p2_rt_kernels`.

Then port nqueen (n=15, dev 12), base64 and bedcov (n=1,000,000 seed 11, dev 10,000) into `bench/perf/` and run
`bench/perf/run.py`.
