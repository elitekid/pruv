# Claude transcript import design

Status: proposed design (2026-11-14), track L3-1. Implementation belongs in `bench/l3/claude/`, built on the completed L3-0 modules in `bench/l3/json/`.

## Goal

Implement the pure part of Lair's Claude JSON Lines import in Pruv: head metadata, human-message filtering, ranked titles, tail metadata, and bounded conversation turns. Input consists of already-read byte windows. Output is flat records and UTF-8 bytes, suitable for constructing `Head`, tail information and the non-plan fields of `ExternalRecord` in the host.

The reference is the source snapshot in `.lair-src-l3-1/`, not a reconstruction of Claude's log format. Preserve its ordering and filtering rules, including their unintuitive cases. Parsing, classification, selection and collection run in verified Pruv; Rust does not implement the importer.

This document specifies implementation and acceptance targets, not completed proofs or measurements. It requires **no language changes**. Actual Lair integration, filesystem operations and plan tracking are not acceptance requirements for L3-1.

## Decisions

### Small, sequential core

Use L3-0's six-slot JSON tape and last-wins object lookup. Parse one line at a time and release its document after processing. Walk array children by their forward `skip` indexes rather than repeatedly calling linear `array_at` from index zero. Do not build a general object model, regex engine, event bus or asynchronous importer.

The turn collector retains only the newest 200 drafts in a ring. Older drafts cannot appear in the reference's final suffix. Prompt and reply storage each have 32,768 bytes per slot; final publication packs only retained strings. A fixed 12.5 MiB text workspace is acceptable for this first implementation and prevents repeated whole-reply concatenation. Do not introduce a general allocator or compacting arena.

No `par` is needed: line order determines current-turn attachment, title ties and timestamp selection. Independent files may be scheduled by the host later. Existing cost clauses may express local iteration budgets, but a global cost proof is not a release requirement.

### Text and timestamps

Use L3-0's UTF-8 text view for values and lossless UTF-16 identity for keys. Reuse the algorithms in `bench/l0/one_line.pruv` and `clip_bytes.pruv`, explicitly keeping their documented differences from TS. Do not silently treat byte counts as JavaScript character counts.

Implement a deliberately restricted `iso_of` in Pruv: safe lexical integer numbers, unsigned integer strings, and canonical UTC ISO strings with four-digit years. This covers ordinary Claude ISO timestamps without adding floating point, a date library or a trusted date parser. Unsupported timestamps are absent, not errors. The exact domain is specified below.

### Plan tracking stays in the host

Do not port `plan.ts::ClaudePlanTracker`, `plain`, `statusOf` or `fit` in this feature. Tracking requires a pending-call map, result correlation and mutable tasks across lines, independently of turn collection. Implementing only `TodoWrite` would silently lose `TaskCreate`/`TaskUpdate` semantics; adding all of them is a separate feature.

The pure result has no `lastPlan` slot. A future Lair wrapper can retain the existing tracker over the same admitted lines, before human/assistant filtering, and merge its result. L3-1 alone is therefore not a drop-in replacement for the entire `readClaude` function. The current `LAST_PLAN_LIMITS` are 30 nonblank items and 200 **UTF-16 units** per trimmed text; `more` counts additional nonblank items. These are host obligations, not new Pruv caps.

## Scope

### Function mapping

All TS paths in this table are relative to `.lair-src-l3-1/`; new Pruv paths are relative to `bench/l3/claude/` unless explicitly qualified.

| TS function or behavior | Pruv replacement | Extent |
|---|---|---|
| `tail.ts::parseLine` | `entry.pruv::parse_line` | L3-0 range parse; accept object roots only; skip malformed/nonobject lines. |
| `tail.ts::record`, `str` | `entry.pruv::object_id`, `string_id`, `string_value` | Checked kinds and optional fields, without coercion. |
| `tail.ts::readEdgeLines` | `framing.pruv::edge_next` | Only byte selection into lines; open/read/close stay in host. |
| `tail.ts::openLineWindow` | `framing.pruv::window_next` | Only line framing, initial-fragment skip and oversized-line events; no stream, signal or file. |
| `tail.ts::headText` | `framing.pruv::drop_prefix` | First at most 8,192 bytes of an oversized line, without assembling stream chunks. |
| `claude.ts::droppedUser` | `text.pruv::dropped_user` | Same four raw-prefix pattern tests; not JSON interpretation. |
| `claude.ts::engineLine` | `text.pruv::engine_line` | Whole trimmed interrupt/notification matching. |
| `claude.ts::humanText` | `entry.pruv::human_text` | User flags, content extraction, any-block tool-result veto and engine-line filtering. |
| `tail.ts::oneLine` | `text.pruv::one_line` | Local module copy of L2 `bench/l0/one_line.pruv::one_line`, with its scalar-safe cut policy. |
| `tail.ts::clipBytes` | `text.pruv::clip_bytes` | L2 longest UTF-8 prefix algorithm; widen its 1,000,000-byte input precondition for import temporaries. Preserve genuine U+FFFD. |
| `claude.ts::titleOf` (including local `pick`) | `entry.pruv::title_of`, `pick_title` | Field priority, ranks 1–3 and nonblank tests. |
| `claude.ts::readHead` | `import.pruv::read_head` | First defined cwd/entrypoint and first human title; early stop when all three exist. |
| `tail.ts::isoOf` | `time.pruv::iso_of`, `integer_time`, `canonical_iso`, `format_iso` | Narrowed domain; no native `Date` calls. |
| `claude.ts::tailInfo` | `import.pruv::tail_info` | Ranked last title and last accepted timestamp in input order. |
| `tail.ts::TurnCollector.begin` | `turns.pruv::begin` | Prompt clipping, new current draft and lost-user flag consumption. |
| `tail.ts::TurnCollector.skipUser` | `turns.pruv::skip_user` | Detach current draft; mark the next draft clipped. |
| `tail.ts::TurnCollector.answer` | `turns.pruv::answer` | Timestamp updates, separators, reply budget and clipping. |
| `tail.ts::TurnCollector.tool` | `turns.pruv::tool` | Increment once per admitted `tool_use`; general caller-supplied counts are not needed. |
| `tail.ts::TurnCollector.finish` | `turns.pruv::finish` | Newest contiguous suffix under turn/text caps, published oldest first. |
| `claude.ts::readClaude` loop and result assembly | `import.pruv::read_window`, `consume_entry` | Model/title selection, turn dispatch, `omittedBefore`; excludes path discovery, plan and exception translation. |

`boundary.pruv` defines limits, flat-output types, checked packing and `check_output`. `root.pruv` supplies the plain-array host entry points described below. All new names are ordinary module functions; no `const` syntax or variants named reserved `Ok`/`Err` are required.

`bench/l0/valid_thread.pruv::valid_thread` already implements `tail.ts::validThread`. It remains available to the path-owning host but is not called by this byte-only API. `clip_chars.pruv::clip_chars` is also available; it is not a replacement for TS plan `slice`, which can split a surrogate pair. No L2 source modification or common-library refactor is required here.

### Classification and metadata semantics

- `human_text` requires `type == "user"` and rejects only literal boolean `true` for `isMeta` or `isSidechain`. A nonempty string such as `"false"` is not that boolean. `message` must be an object.
- String content is returned untrimmed if its ECMAScript-trimmed value is nonempty and is not an engine line. Array content takes only object blocks of type `text` with string `text`, including empty strings, joined with exactly `"\n\n"`. A `tool_result` object **anywhere** in the array vetoes the entire user message. Ignore all other blocks. Test the joined text for blankness and engine-line status only after joining.
- An engine line is exactly `[Request interrupted by user]` or `[Request interrupted by user for tool use]` after trim; or, only with object `origin.kind == "task-notification"`, the whole trimmed text starts with `<task-notification>` and ends with `</task-notification>` with a nonoverlapping middle of any length. Do not parse XML or filter a human message merely containing these tags.
- `dropped_user` searches the raw 8 KiB prefix for `"type"\s*:\s*"user"`, and rejects if any of `"isMeta"\s*:\s*true`, `"isSidechain"\s*:\s*true`, or `"content"\s*:\s*\[\s*\{[^{}]*"type"\s*:\s*"tool_result"` matches. Preserve unanchored matching, including nested-field false positives, and literal rather than escape-decoded key spelling. A bounded byte scanner for these four patterns is sufficient. `\s` uses the ECMAScript set below; invalid UTF-8 in this diagnostic prefix acts as nonwhitespace replacement characters, as with `Buffer.toString`. This also covers a prefix ending inside a multibyte sequence. No JSON parser is called for the dropped line.
- Head cwd and entrypoint use first **string**, including an empty string; null or a wrong kind does not stop searching. The head title is `one_line(first human text, 120)`, not a ranked engine title. Stop only once all three optional values are present.
- Title types and key preference are `custom-title: customTitle, title` (rank 3), `ai-title: aiTitle, title` (rank 2), and `summary: summary, title` (rank 1). Pick the first string whose trim is nonempty, keeping its untrimmed value until `one_line(text, 120)`. Higher rank wins; equal rank replaces with the later physical line. These rules do not filter metadata/sidechain flags.
- Tail `lastAt` is the last **accepted** timestamp of any parsed object, not the largest time, and not limited to conversational roles. Missing/unsupported timestamps leave it unchanged.
- The window loop considers titles on every parsed object, then human text. A human prompt begins a draft and skips assistant processing. Otherwise only `type == "assistant"` with `isSidechain !== true` proceeds; `isMeta` alone does not suppress an assistant.
- Assistant `message.model == "<synthetic>"` suppresses the whole assistant unless `isApiErrorMessage === true`. The exception permits reply/tool processing but never publishes `<synthetic>` as model. The last nonempty nonsynthetic string model wins, even on a line with no valid content or no current draft.
- Assistant string content calls `answer` once, including for `""`. Array content is processed in block order: string-valued text blocks call `answer`; `tool_use` blocks increment tools regardless of name/id; everything else is ignored. A tools-only line does not update completion time. There is no deduplication of message IDs, replayed lines or tool IDs.
- Window title has no head-title fallback. Head, tail and window results remain separate. The host's list title choice stays `tail.title ?? head.title ?? ''`; updatedAt fallback to file mtime is also host behavior.

### Host responsibilities

Keep `claudeProjectName`, `plainName`, `projectFolders`, `realHome`, `alivePids`, `listClaude` orchestration and the filesystem half of `readClaude` in the host. This includes environment overrides, filename validation, directory enumeration, symlink/realpath/inode checks, file identity, read races, sort-by-mtime, list size 50, parallelism 4, cancellation, exception translation and process checks. No Pruv result authorizes access to a path.

`opencode.ts::folderKey` stays there too: Windows slash conversion, trailing-separator removal and Unicode lowercase depend on host platform/path policy; other platforms strip trailing `/` only. Do not replace it with ASCII lowercase or infer folder identity from the project-directory name.

Child processes, RPC timeout 20,000 ms, network and event-loop operations in `tail.ts` are unrelated. G10 single-file reading may later supply buffers, but no G10 work is required now. Retaining `ClaudePlanTracker` must preserve its call-before-filter ordering, last duplicate call ID wins, consume-on-error behavior, broken-state handling and TodoWrite reset; L3-1 does not assert these are verified.

## Boundary representation

### Input windows and framing

Three child-module APIs take immutable `[u8]` arrays:

| API | Input and meaning |
|---|---|
| `read_head(data, cut_after)` | At most 65,536 bytes read at file offset zero; `cut_after` means the file extends beyond this head selection. |
| `tail_info(data, cut_before)` | At most 65,536 bytes of the selected tail; `cut_before` means its start offset is greater than zero. |
| `read_window(data, cut_before)` | At most 8,388,608 bytes of the selected import window; `cut_before` means its start offset is greater than zero. |

The host supplies actual bytes read and flags calculated from the file selection. The core does not accept a path or trust a pre-parsed host object. Short reads are represented by the shorter array; the core cannot prove the host's flags or snapshot identity. Input over these API limits returns `InputTooLarge`, never silent truncation. Empty arrays are valid.

Framing uses `bench/l3/json/lines.pruv::jsonl_next` and `parse_range`:

1. LF is the only separator. CRLF is accepted. For the 1 MiB limit count all raw bytes before LF, **including CR**, before using the JSONL range that removes one CR.
2. Head discards the final unterminated range when `cut_after`; at genuine EOF it accepts a nonempty final range without LF. Tail always accepts such a final range, but when `cut_before` it discards the entire first range through the first LF, even if the window happens to begin at a line boundary. Head/tail do not invoke the dropped-user watcher.
3. Import windows also discard the entire first range if `cut_before`, without a watcher callback. They process only LF-terminated lines (`jsonl_next(..., false)`). A trailing unterminated line of at most 1,048,576 bytes is ignored, even if syntactically valid JSON.
4. A subsequent window line longer than 1,048,576 bytes is never parsed. Emit one `Dropped(prefix)` event at its position, run `dropped_user`, and if true call `skip_user` **before** consuming later lines. This also happens for an oversized unterminated final range. Do not emit multiple events for the same line.
5. Empty, whitespace-only, malformed and nonobject lines have no entry effects. Other L3-0 failures skip that line except `InternalInvariant`, which fails the whole operation. Never confuse a parser/accessor defect with malformed external data. Unsupported timestamp values alone do not skip the entry.

The import's `omittedBefore` is `cut_before || trimmed`, where `trimmed` is turn-suffix loss. It is **not** set merely because a malformed/oversized line or final incomplete line was ignored. These unusual reference semantics are intentional.

### Optional strings and published records

Use a child-module result with `meta: [i64]`, `turns: [i64]`, `text: [u8]`. A dedicated non-generic enum contains `Imported(output)` or scalar `Failed(code, position)`. A string reference is `(start, length)` into `text`, in bytes. Absent is `(-1, 0)`; present empty is `(p, 0)` with `0 <= p <= len(text)`. No NUL termination; U+0000 is ordinary string data.

`meta` has exactly 14 slots:

| Slots | Meaning |
|---|---|
| 0 | Schema version, 1 |
| 1 | Mode: 0 head, 1 tail, 2 window |
| 2 | `omittedBefore` as 0/1; zero outside window mode |
| 3 | Turn count, zero outside window mode |
| 4–5 | Title reference |
| 6–7 | Cwd reference (head only) |
| 8–9 | Entrypoint reference (head only) |
| 10–11 | LastAt reference (tail only) |
| 12–13 | Model reference (window only) |

Turn `i` occupies 10 slots: `[prompt_start, prompt_len, reply_start, reply_len, created_start, created_len, completed_start, completed_len, tools, clipped]`. Prompt and reply are always present. Timestamp refs are absent or 24-byte canonical ISO text. `tools` is nonnegative; `clipped` is 0/1. Output order is oldest to newest among kept drafts. Host reconstruction omits absent optionals and false `clipped`, and never converts absence to the empty string. `omittedBefore` itself is always a boolean in `ExternalRecord`.

Pack metadata strings in the order title/cwd/entrypoint/lastAt/model, then each turn's prompt/reply/created/completed. Copy each present string once at publication; no interning or unused arena tail. With `E = 65,536`, `L = 1,048,576`, `T = 2,097,152`, a conservative output bound for all modes is `T + 3*L + 6*E + 400*24 + 360 + 24 = 5,646,080` bytes. This includes the L3-0 decoder's conservative three-times-raw-span bound for model/cwd/entrypoint, even though actual decoding is usually smaller. Do not impose an undocumented short model/path cap.

### Host ABI and ownership

Root `pub fn` cannot return this buffer-bearing aggregate. Supply three root wrappers, `head_packet`, `tail_packet`, `window_packet`, with the same input arguments, each returning one `[i64]`:

- Success: `[0, meta_len, turn_slots, byte_len, ...meta, ...turns, ...text_bytes]`.
- Failure: `[code, position]`, with no partial payload. Codes are 1 `InputTooLarge`, 2 `InternalInvariant`; position is a byte offset in `0..len(data)` (zero when no source position applies).

Here `meta_len = 14`, `turn_slots = 10 * meta[3]`, and every text byte widened to i64 is in `0..255`. Hosts check tags, exact lengths and version before decoding. This simple transport widens bytes and adds a copy, as existing JSON test roots do; a production multi-buffer Node bridge is deferred. Do not run the import multiple times merely to retrieve separate fields.

Use separate mutable arrays passed through G5 `inout`; never mutate aggregate array fields or pass those fields as `inout`. Retained arguments/fields require explicit `copy`, following `json.pruv::wrap_document`. Expect aggregate copies and measure them in Q. Reuse L3-0's checked `utf8_to_string` adapter where necessary; it only converts representation, with a length check. No trusted regex, calendar, classifier or collector facts are introduced.

### Collector state and transitions

Keep a scalar `begun` counter, a ring of at most 200 draft records, current-slot presence, `lost_before`, and per-slot prompt/reply bytes, timestamp refs, tools and `reply_budget_used`. Timestamp storage can reserve two 24-byte cells per slot. Per-line extraction scratch is bounded by decoded selected strings and separators: at most `5 * line_limit` bytes suffices using L3-0's conservative decoding bound and at most one two-byte separator per tape record. Guard allocation arithmetic; do not apply the L2 clip helper's smaller original input precondition to these temporaries.

- `begin`: start a new slot, evicting the oldest if full; clip prompt to 32,768 bytes. Set clipped if its original UTF-8 length exceeded the cap or `lost_before` was set. Clear `lost_before`; reset reply, budget, tools and completedAt. Preserve optional createdAt.
- `skip_user`: clear current-slot presence, set `lost_before`; keep the earlier draft in the ring. Replies/tools until the next `begin` are ignored. A skipped user is not a draft and does not itself imply `trimmed`.
- `answer`: with no current draft do nothing. Otherwise update completedAt first if `at` exists, **even for empty text or an already-full reply**. If text is empty or `reply_budget_used >= 32768`, stop. Form `piece = text` when actual reply is empty, else `"\n\n" + text`. If its byte length fits the remaining budget, append it and increase the counter by that length. Otherwise append its longest fitting UTF-8 prefix, set the budget counter to 32,768 and set clipped. Keep this saturating counter separately from actual reply length: a multibyte cut can leave unused bytes that later calls must not fill. Prompt clipping never prevents reply accumulation.
- `tool`: increment current tools once, else do nothing; no timestamp update. The bounded input/tape gives a safe counter bound (conservatively `1,048,576 * len(data)`); no JS-number or i64 overflow is reachable.
- `finish`: scan drafts newest to oldest, keeping at most 200 while cumulative **actual** prompt+reply UTF-8 byte length stays at most 2,097,152. Stop at the first draft that would exceed it; do not skip it to fit older drafts. Exclude metadata/timestamps from this sum. Reverse the selected suffix for output. `trimmed = kept < begun`, including drafts evicted from the ring. Empty replies and unanswered last prompts remain valid turns.

## Policies (TS divergences)

These are the complete intended semantic differences for the selected core. Any further difference needs a specification amendment, not a generic test exclusion.

### P1 — strict external encoding and parser limits

TS reads bytes with replacement UTF-8 decoding before `JSON.parse`; L3-1 instead skips a complete line that L3-0 rejects as invalid UTF-8. BOM is not removed and remains a grammar error, as in `JSON.parse`. The dropped-prefix heuristic still follows replacement-decoded pattern behavior; it is separate from parsing.

L3-0's input limit 16,777,216, record limit 1,048,576 and container depth 128 apply to every parsed range. Edge/window limits normally make the JSON input limit unreachable, but depth rejection can affect otherwise valid TS records. Resource rejection skips that record without a `skip_user` event, matching the malformed-line path. The 1 MiB window line cap is earlier and does invoke the oversized-line policy. `InternalInvariant` is always a defect, not this policy.

### P2 — string values are Unicode scalar text

Decode escaped pairs normally; replace each lone surrogate in **values** with U+FFFD before filtering, joining, length calculation or clipping. TS can retain such units in uncut strings. Output is always UTF-8; keys still use exact UTF-16 lookup and duplicate keys remain last-wins. No Unicode normalization or case folding occurs.

ECMAScript whitespace for trim/`\s` is TAB, LF, VT, FF, CR, SPACE, U+00A0, U+1680, U+2000–U+200A, U+2028, U+2029, U+202F, U+205F, U+3000 and U+FEFF. Do not use Python's broader `isspace` or ASCII-only trim. `one_line` collapses runs to one ASCII space, trims, then budgets 120 UTF-16 units; when a cut splits a supplementary scalar, omit that scalar instead of returning TS's lone high surrogate. Preserve the L2 behavior even when it leaves a final separator space at the cut.

### P3 — byte clipping preserves genuine replacement characters

Use the longest whole-scalar UTF-8 prefix within the cap. The TS clipping branch applies `.replace(/�+$/, '')`, which can remove genuine U+FFFD characters adjacent to a cut; Pruv preserves them. Do not change TS's reply-budget saturation or `clipped` trigger as part of this correction. P2/P3 can change actual text sizes and therefore which suffix survives the total-byte cap; the oracle must simulate the policies through collection, not normalize only the final output.

### P4 — explicit `iso_of` domain

Return absent for null, booleans, arrays, objects and missing values. For the other kinds:

1. A JSON number is supported only if L3-0 `number(...).has_integer` is true: integer lexical form, magnitude at most `9007199254740991`, including `-0`. Thus `1.0` and `1e0` are deliberately unsupported even when JS evaluates them to an integer.
2. For a string, trim the ECMAScript whitespace set. If it is nonempty ASCII digits only, accumulate a nonnegative integer at most `9007199254740991` with guarded arithmetic. Leading zeroes are permitted. A decimal point, sign, exponent or other character prevents this numeric-string branch; it does not invoke a general `Number` or `Date.parse` fallback.
3. For either supported integer value `v`, set `ms = v * 1000` when `v < 100000000000`, otherwise `ms = v`. This is a signed comparison, **not** `abs(v)`: negative numeric values always take the seconds branch. Guard multiplication, then require `-62167219200000 <= ms <= 253402300799999` (UTC years 0000–9999). Render exactly `YYYY-MM-DDTHH:mm:ss.sssZ`. Zero and negative zero render the Unix epoch. Integer milliseconds within this range are exactly representable in JS, so no rounding convention is needed.
4. Otherwise accept a string only when the **original untrimmed value** is exactly 24 ASCII bytes `YYYY-MM-DDTHH:mm:ss.sssZ`. Validate all separators/digits, Gregorian month/day and leap-year rules, hours 00–23, minutes/seconds 00–59 and milliseconds 000–999. Year 0000 is permitted. Return the same canonical bytes. Using the original value avoids adding whitespace acceptance that native ISO parsing need not provide.

Everything else is absent: fractional/exponent numeric tokens, fractional numeric strings, signed numeric strings, out-of-range values, extended signed years, ISO offsets, date-only forms, local times, missing/variable fractions, lowercase variants, 24:00, leap seconds, calendar overflow and legacy/runtime-specific `Date.parse` formats. Some of these TS also rejects; those it accepts are deliberate divergences. Do not substitute current time or the preceding timestamp for absence. Tail/collector rules decide whether to retain an earlier timestamp.

Use the integer civil-calendar arithmetic already demonstrated in `bench/l0/cell_date.pruv`, with a local ISO formatter and strict calendar validation in `time.pruv`; `cell_date` itself has a different output format. No floating-point or trusted date adapter is necessary. Whole-import equality to arbitrary JS `Date` semantics is not claimed.

### P5 — API extent and host environment

The bounded byte API rejects oversized caller buffers; TS's pure `readHead(lines)` accepts arbitrary arrays, although its actual caller supplies a 64 KiB edge. Differential inputs must use the documented acquisition domain. `lastPlan`, mtime fallback, folder matching and list metadata are outside the pure output, not silently replaced by empty values. Compare the explicitly selected projection of TS results.

Object access is own-field lookup. Assume an unmodified JSON/Date runtime and unpolluted standard prototypes for TS comparison; inherited properties injected by unrelated host code are not input semantics. These are boundary/environment conditions, not an excuse to ignore mismatches on ordinary parsed objects.

## Proof targets

All claims below are implementation acceptance goals on **both compilers**. Contract notation is mathematical shorthand; expand guards, quantifiers and aggregates inline as in L3-0. User-defined specification predicates cannot be called directly inside contracts.

### Safety, framing and publication

Prove every byte/tape/ring/output read and write in bounds; i64 arithmetic and allocations within language limits; all loops terminate. JSONL steps and array-child skips advance strictly. Prove selected ranges are within the supplied window and ordered without overlap, the raw line cap includes CR, and no incomplete short window tail is published as an entry. Do not use arbitrary fuel to produce truncated success.

`check_output` establishes exact record widths, mode-specific absent fields, optional-ref representation, admitted flags, byte ranges and valid span bounds before publication. Prove turns <= 200, each prompt/reply <= 32,768 bytes, their total <= 2,097,152, timestamps absent or 24 bytes, and packed byte count within the stated bound. Pack-copy contracts preserve every selected byte and have precise `old` frame clauses. Scalar-boundary/UTF-8 semantics need explicit algorithm tests as well as boundary checks; a `str` type alone is not a Unicode-correctness proof.

### Selection and collector semantics

Carry internal draft ordinals, not host-visible IDs, to prove the ring contains the latest `min(begun, 200)` drafts in order. A skipped user clears current without deleting a draft; no answer/tool mutation is possible while current is absent. Prove writes preserve all other slots.

For final retained draft sizes `s[i] >= 0`, prove the chosen suffix has sum <= total and length <= 200, and extending it one draft earlier is impossible unless all begun drafts are kept. If the ring has already evicted a draft and all 200 remaining drafts fit, the turn-count cap prevents extension. Publish increasing ordinals and prove `trimmed == (kept < begun)` and `omittedBefore == (cut_before || trimmed)` exactly. This is stronger than proving only output bounds.

Prove reply-budget saturation and `actual_reply_bytes <= reply_budget_used <= 32768`, unchanged state on absent-current calls, and the specified completedAt update independent of text append. Prove helper clipping returns an equal byte prefix at a scalar boundary with no longer fitting scalar prefix. Prove rank selection equals the last maximum of supplied ranks 1–3 and first-defined head-field selection over candidate records. These local state/array predicates are practical; whole-import TS equivalence is tested.

### Tested rather than proved

Test full JSON/accessor semantics inherited from L3-0, exact four-pattern recognition, ECMAScript whitespace, surrogate handling, human/assistant classification, ISO calendar conversion and correspondence to TS. Prove timestamp arithmetic/ranges and output size, but do not label the civil-calendar algorithm or native-Date equivalence formally proved unless its actual contracts establish them.

Compiler correctness, z3, runtime/allocation support, G6 catalog operations and the existing UTF-8 representation adapter remain trusted. Host acquisition, prototype assumptions and reconstructed JS objects are tested boundaries. No proof of allocation success, peak resident memory, wall-clock complexity or filesystem safety is claimed. Required contracts failing or timing out block their batch; do not replace them with trusted assertions or weaker bounded-array-only success.

## Batches

Five implementation batches A0–A4, then Q. Paths below are relative to `bench/l3/claude/` unless qualified. Each batch adds only its fixture root and narrow test driver; workers run those fixtures, not repository-wide suites. All production additions remain under this directory and reuse existing JSON modules/adapters without changing their contracts. Module/test assembly can follow the L3-0/L2 harness pattern; no new package framework is needed.

| Batch | Files and functions | Tests | Checkable done criterion |
|---|---|---|---|
| A0 | `boundary.pruv`: limit functions, result records, packing/checker; `framing.pruv`: `edge_next`, `window_next`, `drop_prefix`; `a0_root.pruv`, `test_a0.py` | Empty/head/tail/window inputs, LF/CRLF, exact boundaries, initially cut ranges, incomplete EOF, line lengths cap−1/cap/cap+1 including CR, oversized trailing range; malformed output spans, widths, flags and packet lengths. | Both compilers prove bounds/progress and successful-output shape; fixed framing and packet fixtures pass on py/rust, py/llvm, rs/rust, rs/llvm. Dropped events occur once in the correct position. |
| A1 | `text.pruv`: whitespace/trim, `one_line`, `clip_bytes`, `engine_line`, `dropped_user`; `entry.pruv`: `parse_line`, typed field helpers, `human_text`, `pick_title`, `title_of`; `a1_root.pruv`, `test_a1.py` | Wrong kinds, duplicate/escaped keys, exact boolean flags, tool-result veto at each array position, empty text blocks/separators, interrupt strings, notification origin/tag combinations, raw-prefix false positives, all ECMAScript spaces, UTF-8 cuts, U+FFFD and surrogate cases. | All fixtures agree with their specified outputs on four pairs; bounds and longest-prefix contracts verify on both compilers. No regex or message classification delegated to Rust. |
| A2 | `time.pruv`: `iso_of`, `integer_time`, `canonical_iso`, `format_iso`; `import.pruv`: `read_head`, `tail_info` and selection helpers; `a2_root.pruv`, `test_a2.py` | First empty vs absent cwd/entrypoint, head early stop, all title key preferences/rank ties, nonmonotonic times, invalid times between valid ones; `-0`, signed seconds, `1e11` neighbors, safe-integer bounds, rejected fractional forms, leap days/centuries, year 0000/9999 and adjacent rejected values, extended/offset/local dates. | Four-pair fixtures pass; both compilers verify selection predicates, integer safety and 24-byte timestamp shape. Supported timestamps match native TS, unsupported cases match P4 oracle decisions. |
| A3 | `turns.pruv`: `begin`, `skip_user`, `answer`, `tool`, `finish`; `a3_root.pruv`, `test_a3.py` | Direct transition sequences: orphan answers/tools, repeated skips, prompt-clipped but reply-growing, empty text updating time, full reply updating time, separator-only partial append, multibyte saturation gap, cap±1, exactly 200/201 drafts, total-cap exact/overflow, and stop-at-first-unfit suffix. | Both compilers prove ring ordering, frame clauses, caps, maximal suffix, flags and timestamp transitions; direct fixtures pass on four pairs. Retained text uses actual lengths for total cap and a separate saturated reply counter. |
| A4 | `import.pruv`: `consume_entry`, `read_window`; `root.pruv`: three packet wrappers; `a4_root.pruv`, `test_a4.py`, `oracle.py`, `reference.mjs` | Fixed end-to-end transcripts combining malformed middle lines, dropped users, synthetic/error assistant cases, model without current draft, tools-only replies, head/tail/window disagreement and option presence. Node and Electron run the verbatim TS reference for these fixtures. | Complete pure API works on all four pairs, both compiler proofs pass, TS/Python fixed comparisons have zero unexplained differences, packet decode reconstructs the selected TS shape. No filesystem/process implementation or `lastPlan` promise is introduced. |
| Q | `q_root.pruv`, `q.py`; extend `oracle.py`, `reference.mjs`; generated evidence under `work/` | Full differential corpus, targeted mutants and measurements specified below. | At least 20,000 deterministic generated transcripts plus fixed edges complete on **each** of py/rust, py/llvm, rs/rust, rs/llvm; zero unexplained mismatches, crashes, timeouts or internal errors; required mutants rejected/detected and measurements recorded. |

If implementation reveals a real module/ownership/proof expressiveness blocker, report the minimal failing example and affected acceptance clause. Do not proactively change the language, add a general extended-value ABI or bypass verification.

### Q — reference and independent oracle

**Verbatim TS:** record hashes of the source snapshot and Node/Electron versions. The harness may transpile TypeScript, expose private functions and replace environmental dependencies at the module boundary with deterministic in-memory filesystem/line-window fixtures. Do not rewrite function bodies, `TurnCollector`, regexes, `isoOf`, or inject policy changes into the reference. Run the original `readHead`, `tailInfo`, `readClaude` loop/assembly and collector; supply one coherent virtual snapshot for head, tail and window. Exercise original `readEdgeLines`/`openLineWindow` with fake handles/stream chunks where testing acquisition semantics, including splits around the limit and within UTF-8. No real process-liveness or directory probe is needed.

For `readClaude`, plan may execute unchanged but comparison projects only turns, omittedBefore, model and title. Its existence must not alter the core comparison. Serialize optional presence separately from strings and encode TS strings as UTF-16 units so lone surrogates are visible. Do not hide P2/P3 by replacement-encoding the baseline first. Compare all core fields and intermediate A1–A3 observations for fixed boundary fixtures.

**Independent Python oracle:** use Python's strict UTF-8 decoder and JSON parser with ordered object pairs, last-wins UTF-16 key equality, and distinct raw-number wrappers (`parse_int`/`parse_float` callbacks) rather than Python float coercion. Reject non-JSON constants. Apply L3-0 resource limits independently, including object-key records. Do not import generated Pruv code, call TS for expected values or copy the implementation's ring/packet algorithm. Model drafts as an ordinary list and select its suffix from the end. Use explicit ECMAScript whitespace and surrogate-to-scalar conversion, not Python defaults. Calendar expectations use independent proleptic-Gregorian day arithmetic (including year zero) rather than reusing Pruv's civil-from-days formula; ordinary `datetime` alone cannot represent the full accepted domain.

Run two comparisons: exact TS agreement on the shared domain and exact Python-policy agreement on all inputs. For policy cases, preserve the raw TS result and attach specific P1–P5 reasons with the affected input/fields and an independently computed expected effect. A transcript merely containing a lone surrogate or unsupported timestamp is not a blanket mismatch exemption. Recompute downstream attachment, byte totals and suffix selection when policies change earlier data. Runtime differences in native `Date.parse` outside P4 are recorded; differences inside the supported domain fail Q.

### Q — corpus, mutants and measurement

Use at least 20,000 seeded generated **transcripts**, not 20,000 independent JSON lines, plus fixed cases. Vary line/block order and irrelevant fields as well as contents. Include:

- All classifier flags/types and wrong kinds, duplicate/escape-equivalent keys, nested misleading keys, tool results in every position, synthetic/API-error combinations, repeated IDs, no users and unanswered prompts.
- Title priorities/ties/fallback keys, first present-empty head fields, timestamps out of chronological order, all P4 boundaries and rejected Date forms.
- Every ECMAScript whitespace, surrogate pair/lone-half/U+FFFD combination, multibyte and newline separator cuts, prompt/reply 32 KiB boundaries, 200/201 turns, 2 MiB total boundaries and repeated ring wraparound.
- LF/CRLF, cut windows beginning exactly at LF boundaries or inside UTF-8, short reads, head/tail EOF behavior, malformed middle records, 8 KiB diagnostic-prefix edges, 1 MiB lines and 8 MiB windows at boundary values, oversized/incomplete user and tool-result lines.
- Depth 128/129, a large shallow tape, hostile invalid UTF-8 and resource-rejected records. Test unreachable parser limits at the existing JSON boundary rather than pretending an over-1-MiB window line reaches JSON parsing.

Seed targeted mutants: invert exact-true filters; remove an any-position tool-result veto; allow synthetic non-error replies; change rank `>=` to `>`; choose maximum rather than last timestamp; omit `skip_user`; count CR incorrectly; accept the short incomplete tail; remove separators; use actual reply length instead of saturated budget; block replies after prompt clipping; stop updating time when full; reverse suffix order; use `>=` at an inclusive cap; calculate omittedBefore from oversize loss; alter the signed timestamp threshold. Include an unsafe output-index/length mutation and a state-frame violation. Classify proof-rejected mutants separately from verified mutants detected by behavior tests. Every non-equivalent listed mutant must be rejected or detected; a surviving mutant fails Q and gets a narrow fixture, not a weakened contract.

Measure warm execution latency and peak RSS for small normal transcripts, an 8 MiB window of many short messages, long text near the per-line cap, large block arrays, repeated ring eviction and depth-limit input. Report parsing vs collection/packing costs where the harness permits, native TS baseline, all four pairs, build/proof time separately, repetitions and machine/runtime versions. Account for fixed workspace, JSON range/publication copies and i64 packet widening. There is no invented speedup threshold; a timeout is a failure to investigate, not an accepted policy difference.

Save seeds, corpus counts, source hashes, compiler/backend/runtime versions, verification results, mismatch classifications, smallest reproducers, mutant outcomes and measurement settings/results. Do not claim Q complete from only one compiler, only Rust emission, only Node, or a tested subset of generated transcripts. No full repository suite is part of this design task or its batch protocol.

## Deferred

- Full `ClaudePlanTracker` and its LastPlan output; other engines' plan extraction.
- General JS `Date.parse`, floating-point timestamps, arbitrary Date years and timezone/local-calendar compatibility.
- Filesystem and streaming acquisition, cancellation, process liveness, actual Lair replacement and Node bridge packaging; G10 is optional future integration.
- List discovery, folder naming/matching, identity/security checks, mtime fallback and account/source management.
- Lossless UTF-16 output ABI, general regex support, JSON parser redesign and a standard-library promotion.
- A smaller dynamically packed draft workspace, zero-copy parsing/transport, recovery from allocation failure and formal memory/time-complexity proofs. Optimize only after Q identifies a relevant cost.

## Risks

1. **Behavioral compatibility:** incomplete/oversized lines, saturated replies and optional-field presence can silently change turn attachment. Timestamp narrowing and Unicode policies also affect metadata and retained suffixes. Fixed transition fixtures and a policy-aware oracle must distinguish intentional differences from regressions; host rollout needs a separate compatibility decision.
2. **Memory and scan costs:** the 12.5 MiB collector workspace is only part of peak memory. L3-0 documents/tapes, decoder scratch, ownership copies, field scans and the widened packet can dominate. Bounded allocation is not evidence of low RSS or acceptable latency; measure the prescribed hostile shapes before integration.
3. **Proof and reference fidelity:** frame/ordering/maximal-suffix contracts may require careful invariant decomposition, while private TS functions and native Date behavior complicate a faithful harness. Keep reference bodies verbatim, record runtime/source versions and block an implementation batch on a required proof failure. No language-change blocker is currently identified.
