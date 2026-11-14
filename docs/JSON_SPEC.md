# JSON parser design

Status: design fixed (2026-11-14), track L3-0 first feature. Code lives in `bench/l3/json/`. Batches A0–A5 and Q are done; results are in RESULTS.md section 115.

## Goal

Implement JSON parsing in Pruv as the first L3-0 feature for the future Lair backend. The first consumer is conversation import from engine JSON Lines logs.

The parser handles untrusted bytes. Grammar recognition, tokenization, escape decoding, structural indexing and accessors are written in Pruv. Do not wrap `serde_json` or delegate JSON parsing to Rust.

This document specifies implementation targets, not completed proofs or test results. It requires **no language changes**.

## Decisions

### Representation

Use a flat, preorder tape of fixed-width `i64` records referencing immutable input bytes.

| Choice | Assessment |
|---|---|
| Flat tape | Array bounds, source spans and forward indexes have directly expressible contracts. Fixed-width records support field lookup and subtree skipping without recursive allocation. |
| Recursive enum tree | G9 supports it through linked `Items` and `Members`, but not `Vec<Json>` or `[Json]`. Existing values deep-copy in owning positions; construction, copying and destruction can recurse. Recursive semantic predicates remain limited. |

Choose the tape. It follows the count-pass and explicit-stack precedents in `bench/l0/parse_html.pruv` and `bench/l0/docx_parts.pruv`, while adding stronger successful-result contracts.

### Numbers

Accept the complete JSON number grammar:

`-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?`

Every number retains its exact source span. Never reject a syntactically valid number because its magnitude exceeds i64 or binary64.

The number accessor returns:

- The raw span.
- `exact_integer: Option<i64>`.
- `negative_zero: bool`.

`exact_integer` is present **only** for integer-form tokens without a fraction or exponent whose magnitude is at most `9007199254740991` (`2^53 - 1`). Accumulate digits with a guard before multiplication and addition.

Thus `1` gives `Some(1)`, while `1.0`, `1e0` and `9007199254740992` give `None`. This is a lexical fast path, not a claim that those other numbers are nonintegral.

`-0` gives `Some(0)` and `negative_zero = true`. Other tokens retain sign information in their raw text; no binary64 conversion occurs in Pruv.

### Strings and key identity

Recognize all JSON escapes: `\"`, `\\`, `\/`, `\b`, `\f`, `\n`, `\r`, `\t`, and exactly four hexadecimal digits after `\u`.

Decode adjacent escaped high/low surrogate pairs into their supplementary Unicode scalar. Accept lone escaped surrogates, as `JSON.parse` does.

Provide two views:

- **Text view:** valid UTF-8 `str`; each unmatched surrogate becomes U+FFFD.
- **Lossless view:** decoded UTF-16 units as `[i64]`, each in `0..65535`.

The lossless view is also the basis of key equality. Do not normalize keys to replacement text before comparing them: `"\uD800"` and `"�"` are different keys.

A `str` lookup key is compared using its UTF-16 units. A separate units-based lookup supports keys containing lone surrogates. No Unicode normalization or case folding occurs.

### Input encoding

The core input is `[u8]`, not `str`, so malformed external encoding produces a parser error rather than failing a host string ABI check.

Require strict UTF-8: reject overlong sequences, encoded surrogate values, values above U+10FFFF, stray continuation bytes and truncated sequences. Validate the selected input range before grammar parsing.

Do not remove a BOM. UTF-8 BOM bytes outside a string are rejected by the grammar. U+FEFF inside a string is ordinary text.

Byte-to-string conversion is a small G6b trusted adapter, described below. It performs no JSON decoding.

### Objects and duplicate keys

Preserve every member in source order on the tape. Field lookup scans direct members and returns the **last** value whose decoded UTF-16 key equals the requested key.

This also covers escape-equivalent keys such as `"a"` and `"a"`.

Treat `__proto__`, `constructor` and similar names as ordinary keys. There is no prototype lookup or host-object assignment in the parser.

### Grammar and limits

Accept one complete JSON value followed only by JSON whitespace:

- Whitespace is exactly SPACE, TAB, LF and CR.
- Top-level values may be objects, arrays, strings, numbers, booleans or null.
- Object keys must be strings.
- Reject trailing commas, comments, single quotes, leading `+`, leading zeroes, incomplete fractions/exponents, `NaN`, `Infinity`, unescaped U+0000–U+001F, and trailing non-whitespace data.
- Unescaped U+2028 and U+2029 inside strings are valid.

Initial limits:

| Resource | Limit |
|---|---:|
| Input bytes per document or JSON Lines record | 16,777,216 |
| Tape records, including object-key records | 1,048,576 |
| Simultaneously open arrays and objects | 128 |

A scalar has container depth zero; a root array or object has depth one. Reject the opening delimiter that would create depth 129.

These are explicit operational limits for untrusted import data, not measured Lair requirements. The depth limit bounds explicit stack storage; the record limit bounds tape allocation. They are documented differences from otherwise accepted `JSON.parse` inputs.

### Errors

Use a dedicated scalar `JsonError { position: i64, kind: i64 }`.

Positions are zero-based **byte offsets relative to the selected document**, within `0..input_length`; EOF is `input_length`.

Kinds distinguish:

- `InputTooLarge`, `TooManyRecords`, `DepthLimit`
- `InvalidUtf8`
- `UnexpectedEof`, `ExpectedValue`, `ExpectedKey`, `ExpectedColon`
- `ExpectedCommaOrEnd`, `TrailingComma`, `TrailingData`
- `InvalidLiteral`, `InvalidNumber`, `InvalidEscape`, `InvalidUnicodeEscape`
- `UnescapedControl`, `UnterminatedString`
- `InternalInvariant`

For UTF-8 errors, report the start of the first invalid sequence. For syntax errors, report the offending byte, or EOF if a required byte is missing.

Precedence is input-size check, UTF-8 validation, then left-to-right grammar processing. Record/depth errors occur when the corresponding limit would be exceeded. Required-byte EOF checks precede unexpected-byte classifications.

`InternalInvariant` reports a count/fill mismatch or failed structural publication check. It is an implementation defect, never an accepted malformed-input outcome in tests.

Allocation failure remains a runtime resource failure; the current language does not provide recoverable allocation errors.

## Representation

### Document and records

Use a nonrecursive G9 `JsonDocument` containing:

- `source: [u8]`: owned bytes of exactly the selected document.
- `tape: [i64]`: owned records.

A dedicated non-generic parse enum contains either this document or `JsonError`. Do not use `Result<JsonDocument>`: buffer-bearing types are not permitted as generic payloads.

Record `r` occupies slots `6*r .. 6*r+6`:

| Slot | Meaning |
|---|---|
| 0 | Kind: null, false, true, number, string, array, object, key |
| 1 | Inclusive source start |
| 2 | Exclusive source end |
| 3 | `skip`: record immediately after this subtree |
| 4 | Parent container record; `-1` for the root |
| 5 | Array element count or object member count; zero for other kinds |

Strings and keys include their quotes in the raw span. Container spans include delimiters. No span includes surrounding whitespace.

Root ID is zero. Record count `m` is the end sentinel, never a valid value ID.

An object is laid out as:

`object, key, value-subtree, key, value-subtree, ...`

Keys are leaf records. The key and its value have the object as parent. A value follows its key immediately; its `skip` reaches the next key or the object's end sentinel.

Duplicate members remain represented. Object member count counts occurrences, not distinct keys.

### Construction

Use one scanner with count and fill modes:

1. Validate input length and UTF-8.
2. Run the grammar scanner with explicit bounded stacks, counting records.
3. Allocate exactly `6 * record_count` slots.
4. Run the same scanner in fill mode, patching container end, skip and count fields on close.
5. Check count/fill agreement and structural well-formedness before publishing success.

Count mode does not write tape slots. Fill mode must fail on insufficient capacity; never silently discard writes or return a partial document.

Mutable arrays remain separate locals passed through G5 `inout`. Do not mutate array fields or pass fields as `inout`, which the language does not support. Wrap completed buffers only at the ownership boundary.

G9 wrapping may copy existing buffers. Account for those copies; do not assume aggregate move syntax or guaranteed copy elision.

### Structural publication check

Use an ordinary verified Pruv checker with explicit stacks. Its successful return establishes the tape properties required by accessors.

This avoids making successful-result safety depend on an unproved equivalence between count and fill passes. It does not replace grammar cross-checking.

Contract descriptions below are mathematical shorthand. In source, expand them into guarded slot reads, quantifiers and aggregates. User-defined predicates such as `well_formed(tape)` cannot be called inside contracts.

## API

The library is a normal child module, for example `json.pruv`, loaded through G4. Its public buffer-bearing types and functions are Pruv APIs, not host ABI entries.

| Operation | Result and behavior |
|---|---|
| `parse(data)` | Parse all bytes; dedicated success/error enum |
| `parse_range(data, lo, hi)` | Parse one bounded range; positions relative to `lo`; document owns that range |
| `root(document)` | Value ID zero |
| `kind(document, id)` | Kind or invalid-ID error; key IDs are not ordinary value IDs |
| `raw_span(document, id)` | Checked half-open source span |
| `array_length(document, id)` | Element count; wrong-kind error for non-arrays |
| `array_at(document, id, index)` | Found value ID, missing index, or access error |
| `field(document, id, key: str)` | Last matching direct member, missing key, or access error |
| `field_units(document, id, key: [i64])` | Same lookup with exact UTF-16 units |
| `string_text(document, id)` | Decoded UTF-8 text, replacing lone surrogates |
| `string_units(document, id)` | Exact decoded UTF-16 units |
| `number(document, id)` | Raw span, optional safe integer and lexical negative-zero flag |
| `boolean(document, id)` | Boolean or wrong-kind error |

Use scalar `Result<i64>` or small value enums where sufficient. String/array-bearing results use dedicated non-generic enums. Missing fields, JSON null and wrong-kind errors remain distinct.

`parse_range` requires valid caller-provided range bounds. It has no precondition that the selected bytes are valid JSON or UTF-8. The 16 MiB limit applies to the range, not the enclosing file.

Accessor IDs and requested indexes are checked before use. Document integrity is a Pruv contract established by parsing, not an opaque-type guarantee: G4 does not provide private fields on a public type.

Array indexing skips preceding subtrees; field lookup scans direct members. These are linear operations. A hash index is unnecessary for the initial import consumer.

### Producing `str`

Decode escapes, surrogate handling and UTF-8 output bytes in Pruv into an exactly sized `[u8]`.

Add one dependency-free G6b adapter equivalent to the existing `utf8_copy` pattern:

- Accept `[u8]`, return owned `String`.
- Strictly convert valid UTF-8 byte-for-byte.
- Return empty on invalid UTF-8.
- Contract: result is empty or has the input length; equal lengths imply byte-for-byte equality.

Pruv checks that the returned length equals the decoded byte length before `string_to_str`. A mismatch becomes `InternalInvariant`; it must not silently turn a nonempty string into empty text.

This adapter is only representation conversion. No token recognition, escape decoding, key comparison or numeric conversion belongs in Rust.

The LLVM build uses generated Rust bindings and the existing G6 shim. Native `--emit exe|obj` without that host link is not supported for this adapter path.

### JSON Lines

Provide a byte-range iterator:

`jsonl_next(data, offset, final) -> Line(start, end, next) | NeedMore | Done`

Rules:

- LF separates records.
- Exclude LF and one immediately preceding CR from the returned range.
- Preserve all other bytes; do not trim or skip blank lines.
- With no LF remaining, return `NeedMore` when `final` is false.
- At final EOF, return a nonempty remaining range as the last record.
- Empty input and the position immediately after a final LF return `Done`; do not invent an extra blank record.
- Every `Line` advances `next` strictly.

Parse each returned range independently. Blank/whitespace-only records produce a JSON error. Malformed records remain visible to the caller, which decides whether to stop or continue.

The import caller maintains the one-based physical line number and file base offset. Absolute error offset is `base + start + error.position`, with checked arithmetic.

Chunk buffering, file reads and import recovery policy remain outside this helper. An incomplete nonfinal tail must be retained rather than prematurely rejected.

## Proof goals

All claims in this section are implementation acceptance goals.

### Safety and progress

Prove on both compilers:

- Every source, tape, output and stack read/write is in bounds.
- Every arithmetic operation is free of i64 overflow.
- Allocation lengths satisfy Pruv's limits.
- UTF-16 units and output bytes satisfy their respective ranges.
- Error positions lie within the selected input, including EOF.
- Scanner results remain within their input range and successful token scans advance.
- Every loop terminates, including errors, accessors and JSON Lines iteration.

Organize scanner iterations to consume input or return; fold bookkeeping into the consuming transition. If a phase needs a non-consuming transition, use an explicit bounded phase measure.

No arbitrary fuel exhaustion may become successful parsing or truncated output.

### Successful tape shape

Prove success implies:

- Tape length is exactly `6*m`, with `1 <= m <= 1048576`.
- Every kind is admitted.
- Every span satisfies `0 <= start < end <= input_length`.
- Every record satisfies `r < skip[r] <= m`.
- Scalars and keys have `skip[r] = r+1` and zero child count.
- Root has parent `-1` and `skip[0] = m`.
- Every other record has an earlier container parent and lies within its parent's source and tape intervals.
- Subtree intervals do not cross. For `r < j < skip[r]`, record `j` remains inside `r`'s source interval, has `skip[j] <= skip[r]`, and has `parent[j] >= r`.
- Array direct children are values; object direct children alternate key/value-subtree.
- Counts agree with direct-child structure: array values or object key/value pairs.
- No unfinished container, uninitialized record or trailing candidate storage is published.

Use ordered domain guards before quantified indexing. Preserve precise `old` frame clauses in mutation helpers; length preservation alone does not preserve tape contents.

### Accessors

Prove returned spans and IDs are in range, found children have the requested container as parent, skips move forward, and string output lengths are bounded by the source token length.

Prove safe-integer accumulation cannot overflow and returned integers stay within the selected safe range.

Full JSON grammar equivalence, exact decoding, exact decimal interpretation and last-wins lookup semantics are cross-checked. Do not present them as formally proved unless implementation contracts actually establish them.

The structural checker's postconditions are mandatory. A solver timeout blocks that batch; it does not justify weakening success to "some bounded array."

### Trusted boundary

Compiler correctness, z3, allocation/runtime support, G6 catalog operations and the byte-to-String adapter remain trusted.

UTF-8 scalar semantics are not automatically supplied by Pruv's string model. Decoder correctness and adapter behavior need explicit tests; `str` validity alone is not a proof of the intended decoded text.

This feature does not claim a proof of wall-clock complexity, peak memory or allocation success.

## Cross-check

Reuse the L2 harness pattern: an independent Python oracle, an unmodified native `JSON.parse` call, and Python/Rust compiler × Rust/LLVM backend.

### Python oracle

Decode input with strict UTF-8 before calling `json.loads` on a Python string. Do not pass bytes directly, which permits encoding detection outside this design.

Use:

- `strict=True`.
- `parse_constant` that raises for `NaN`, `Infinity` and `-Infinity`.
- `parse_int` and `parse_float` callbacks that retain exact token strings in a distinct number wrapper.
- `object_pairs_hook` that retains ordered pairs in a distinct object wrapper.

This avoids Python integer digit limits, preserves duplicate members, and distinguishes objects, arrays, strings and numbers.

Convert decoded Python strings to UTF-16 unit sequences with surrogate-preserving handling. Compare keys and apply last-wins using those sequences. For text-view comparison, combine valid pairs and replace each unmatched surrogate with U+FFFD explicitly.

Apply resource-limit policy separately from grammar acceptance. Python recursion/resource failures are harness failures, not evidence that JSON is invalid.

### JavaScript baseline

Run literal `JSON.parse(text)` without a reviver in the recorded Electron runtime and Node runtime. The surrounding driver may encode outputs; it must not replace or patch the parser.

Use a strict UTF-8 decoding boundary that preserves BOM. Never use replacement decoding to conceal invalid input bytes.

Canonicalize results by type:

- Strings as UTF-16 unit arrays, plus separately normalized text.
- Objects as own-property key/value entries; ignore enumeration-order differences.
- Arrays in index order.
- Numbers as binary64 bit patterns, retaining negative zero and infinities.

For each Pruv number span, pass its raw token to the native `JSON.parse` in the test host and compare binary64 bits with the corresponding native result. Separately compare the raw token and optional safe integer with the Python token oracle.

Do not use ordinary JSON serialization of numeric values as the comparison: it loses negative zero and maps infinities to null.

The number test demonstrates correct token preservation and host interpretation, not a Pruv binary64 implementation.

### Corpus and acceptance

Q runs at least 20,000 deterministic generated cases plus fixed edges on all four compiler/backend pairs.

Include:

- Every scalar kind, empty containers and mixed nesting.
- Depths 127, 128 and 129; much deeper hostile inputs.
- Long plain/escaped strings and every escape form.
- Surrogate pairs, lone halves, reversed halves, repeated halves and U+FFFD key collisions.
- UTF-8 boundary values and malformed/truncated sequences.
- Safe-integer boundaries, long mantissas/exponents, underflow, overflow and negative zero.
- Duplicate and escape-equivalent keys; `__proto__`, `constructor`, empty and numeric-looking keys.
- Missing delimiters, invalid literals, trailing commas/data and every forbidden whitespace class.
- JSON Lines with LF/CRLF, blank records, malformed middle records and incomplete tails.

Compare accepted values through accessors. Independently inspect tape structure and raw spans. Use fixed cases for exact error kind/position; native parser error wording and offsets are not the oracle.

Record expected policy differences separately: resource limits and lossy text views. Invalid UTF-8 is a byte-boundary rejection, not a comparison against an already-decoded JS string.

Any unexplained mismatch, crash, timeout or `InternalInvariant` fails the run. Save tool/runtime versions, seed, counts, verification results and the smallest failing inputs.

## Batches

Each worker runs only its batch's fixtures. No worker runs the full repository suite. Fuzzing, mutation testing and performance measurement belong only to Q.

| Batch | Deliverable | Added tests / exit evidence |
|---|---|---|
| A0 | Module types, six-slot records, error codes, structural checker and initial contracts | Hand-built valid/malformed tapes; bad spans, parents, skips, counts and object pairing. Both compilers prove successful-check shape clauses. |
| A1 | Strict UTF-8 validation and bounded lexical scanners | Fixed cases for literals, number grammar, whitespace, quotes, escapes, invalid UTF-8 and exact error offsets. Prove bounds and cursor progress. |
| A2 | Container state machine, count/fill passes and parse result | Fixed nested objects/arrays, all comma/colon states, duplicate preservation, limit boundaries and count/fill agreement. Success carries A0 contracts on all four pairs. |
| A3 | String units, UTF-8 decoding and representation adapter | Every escape, surrogate combinations, NUL, multibyte boundaries and adapter valid/invalid input. Prove unit/byte ranges and output bounds; compare exact units/text. |
| A4 | Value accessors, key lookup and number metadata | Missing versus null, wrong kinds/IDs, array boundaries, nested skipping, duplicate keys, surrogate-key collisions, safe integers and `-0`. |
| A5 | JSON Lines range iteration and import-shaped example | LF/CRLF, empty file, blank records, malformed middle line, final/nonfinal tails and absolute offset calculation. No Lair integration. |
| Q | Complete differential corpus, targeted mutants and measurements | At least 20,000 generated cases plus edges on four pairs, Electron/Node baselines, zero unexplained mismatches. Classify mutants as proof-rejected or behavior-detected; measure large-string, wide-object and depth-limit cases. |

Use plain-array/scalar root wrappers for host tests. Do not add an extended-value host ABI to export `JsonDocument`.

If a required proof fails, fix the relevant implementation or invariants in that batch. Do not introduce trusted parser facts, bypass verification or expand into compiler changes without a demonstrated language blocker.

## Deferred

- Binary64 conversion/arithmetic in Pruv and general exact-decimal arithmetic.
- Hash-indexed objects, constant-time array indexing and mutable JSON values.
- Serialization, revivers, JSON5, comments and relaxed grammar.
- Streaming partial-token parsing, file I/O, IPC and actual Lair backend replacement.
- Promotion into the bundled `std`; G8 currently contains twelve verified numeric/array functions, not JSON or Unicode facilities.
- Recoverable allocation failure and formal peak-memory/complexity bounds.
- Range parsing without the extra copy: `parse_range` copies the selected bytes into an owned buffer and `parse` then copies them once more when it publishes the document. This adds one linear memcpy per record next to at least three linear scans (UTF-8 check, count pass, fill pass). Removing it would need a range-offset core across every scanner contract, so it waits for a measured need.
