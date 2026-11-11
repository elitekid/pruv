# G2 B1 구현 명세: `str` 증명 — 두 판 공통

이 명세는 Python 판(`pruvc/`)과 Rust 판(`pruvc-rs/`)이 **같은 SMT·같은 의무 순서·같은 문구**를 내도록 고정한 것이다. 근거: `docs/G2_SPEC.md` 0.0절 결정 2·4·11·13·16, 4.3~4.5절, 6.1·6.3절, 7.5절. 앞 묶음: `docs/G2_A2_IMPL.md`(u8 증명), `docs/G2_A5_IMPL.md` 2절(bool 증명), `docs/G2_B0_IMPL.md`(str 앞단).

## 0. 범위와 결정

- 증명 층이 `str` 을 받는다. 생성 층(Rust·LLVM)은 계속 `unsupported_type`(stage `codegen`)으로 막는다(B2에서 연다).
- **표현:** 기호 `str` 값은 새 형태를 만들지 않고 **원소 타입 U8 인 기호 배열**(Py `Arr`, Rs `Val::Arr(Arr)`, `elem = U8`)이다. SMT 는 `Array(Int, Int)` + 길이 Int. 그래서
  - 함수 진입·사용자 함수 호출 결과·루프 havoc 세 곳의 바이트 범위 가정(결정 2)은 지금 있는 `u8_dom` 길이 그대로 붙는다(새 코드 없음).
  - `len`·코드 읽기 `s[i]`(index_oob, `in_range` 가정 그대로)·계약 읽기(contract_domain)·`copy`·재바인딩·`ensures` 의 `result`·반례 JSON(`{"len": n, "first": [..]}`, 정수)은 배열 길이 그대로다.
- 리터럴은 상수 항, `substr` 결과는 새 기호 값 + 길이·바이트 관계 가정이다. 두 경우 모두 **범위 가정을 따로 넣지 않는다**: 리터럴 바이트는 상수(0..255)이고, `substr` 바이트는 원래 `s` 의 바이트와 같으므로 이미 성립한다(결정 2의 "리터럴·copy·substr 결과"는 이것으로 충족).
- UTF-8 유효성 공리는 넣지 않는다(결정 13: 과대 근사). **SMT 반례의 str 바이트는 유효 UTF-8 이 아닐 수 있다.** 이 뜻을 `substr` 두 의무의 FIX 글자에 적는다(3절).
- `--infer`: 새 후보 없음. `string_slice_range`·`utf8_boundary` 는 `cand` 없이(None) 증명해 탐색에서는 생략되고 최종 전체 검증에서만 판정된다(결정 4). `infer.py`/`infer.rs` 는 고치지 않는다(조사 결과 StrLit 순회는 이미 안전: Py `show` 가 `_Skip`, Rs `show` 가 None).
- G2를 쓰지 않는 입력의 SMT·fresh 번호·의무 순서는 바뀌면 안 된다(기존 SMT 231 바이트 불변).

## 1. 타입과 fresh

### Py `pruvc/verify.py`
- import 에 `STR` 이 들어오는지 확인(`from vast import *` 로 이미 들어오면 그대로).
- `fresh(base, ty)`: `is_array(ty)` 분기 **바로 앞**에
  ```python
  if ty == STR:   # G2 B1: str = U8 byte array
      return mk_arr(z3.Array(n, z3.IntSort(), z3.IntSort()), z3.Int(n + ".len"), base, U8)
  ```
  (카운터 `s.k += 1` 과 이름 `n` 은 함수 첫머리 그대로 — 배열과 같은 이름 규칙 `base!k`, `base!k.len`.)
- `wf(STR, ..)` 는 닿지 않는다(호출부가 모두 `isinstance(v, Arr)` 를 먼저 본다).

### Rs `pruvc-rs/crates/pruv-proof/src/model.rs`
- `enum Ty` 에 `Str` 변형을 더한다(`Array(Elem)` 다음). `from_name("str") => Ty::Str`(배열 이름 판정보다 먼저), `name(): Ty::Str => "str"`. `is_array()`·`array_elem()` 은 **바꾸지 않는다**(str 은 배열이 아님; false/None).
- `Ty::Array(_)` 를 매칭하는 곳(model.rs 413 근처 `Ty::Unit | Ty::Array(_) => Err(..)`, symbolic.rs 349·581 근처)에 `Ty::Str` 을 **Array 와 같은 팔**로 더한다. 와일드카드로 흡수하지 말고 명시한다.
- model.rs 시험(`mod tests`)에 `assert_eq!(Ty::from_name("str"), Ty::Str); assert_eq!(Ty::Str.name(), "str");` 를 더한다.

### Rs `symbolic.rs` `try_fresh`
- `Ty::Str` 팔: `Ty::Array(Elem::U8)` 와 똑같이 만든다(같은 이름 규칙, int sort 원소, `elem = Elem::U8`, 카운터 한 번).

## 2. 식 평가

### 2.1 문자열 리터럴 `StrLit`(코드·계약 모두, 같은 항)
Py `ev` 의 `IntLit`/`BoolLit` 분기 다음:
```python
if isinstance(e, StrLit):   # G2 B1: constant byte array, no counter, no assumption
    a = z3.K(z3.IntSort(), z3.IntVal(0))
    for i, b in enumerate(e.value):
        a = z3.Store(a, z3.IntVal(i), z3.IntVal(b))
    return mk_arr(a, z3.IntVal(len(e.value)), "literal", U8)
```
- 상수 배열 기본값 `0`, 색인 0부터 차례로 `Store`(바깥이 마지막 바이트). 길이는 `IntVal(바이트 수)`. 이름 `"literal"`.
- 카운터를 건드리지 않고 의무·가정도 없다. Rs `symbolic.rs` `ev` 의 `Expr::StrLit` 팔(지금 `Err(..)`)을 같은 항으로 바꾼다(`K` 는 alloc 이 쓰는 상수 배열 생성 함수, Store 는 IndexAssign 이 쓰는 것을 쓴다).

### 2.2 경계 판정 `boundary(arr, i)`
Py 모듈 함수(`u8_dom` 옆):
```python
def str_boundary(arr, i):
    """G2 B1 (G2_SPEC 4.4): i is a UTF-8 character boundary of byte array arr (total, no domain)."""
    b = z3.Select(arr.a, i)
    return z3.Or(i == 0, i == arr.n, z3.And(i > 0, i < arr.n, z3.Or(b < 128, b >= 192)))
```
- 글자 그대로: `Or` 세 인자 순서, `i > 0`(Py `0 < i` 가 아님), `i < arr.n`, `b < 128`, `b >= 192`. 상수는 정수 0·128·192.
- Rs `symbolic.rs` 에 같은 식을 만드는 `fn str_boundary(&self, arr: &Arr, i: &Ast) -> Ast`(u8_dom 옆). `or([eq(i,0), eq(i,n), and([gt(i,0), lt(i,n), or([lt(b,128), ge(b,192)])])])` — z3 AST 가 Py 와 같도록(`i > 0` 은 `(> i 0)`).

### 2.3 builtin `is_char_boundary(s, i)`(코드·계약)
Py `call` 의 `copy` 분기 다음, `print` 분기 앞:
```python
if n == "is_char_boundary":
    return str_boundary(args[0], args[1])
```
- 인자는 이미 앞에서 차례로 평가됐다(`args = [...]`). 의무·가정 없음. 계약 정의역 `dom` 은 바꾸지 않는다(Call 이면 인자 정의역만 모음 — 지금 코드 그대로가 4.4절 "인자 식 자체의 정의역만 검사").
- Rs `call` 의 내장 이름 매칭에 같은 자리·같은 동작으로(`Val::Bool(..)`).

### 2.4 builtin `substr(s, lo, hi)`(코드만; 계약은 검사기가 거부)
Py, `is_char_boundary` 분기 다음:
```python
if n == "substr":   # G2 B1 (G2_SPEC 4.4): range -> boundary -> fresh result
    sv, lo, hi = args
    s.prove(st, g, z3.And(lo >= 0, lo <= hi, hi <= sv.n), e, "string_slice_range",
            "substr range 0 <= lo <= hi <= len(%s)" % sv.name)
    s.prove(st, g, z3.And(str_boundary(sv, lo), str_boundary(sv, hi)), e, "utf8_boundary",
            "substr cuts of %s at UTF-8 character boundaries" % sv.name)
    res = s.fresh("substr", STR)
    s.assume(st, g, res.n == hi - lo)
    k = z3.Int("str!k")
    s.assume(st, g, z3.ForAll([k], z3.Implies(z3.And(k >= 0, k < res.n),
                                               z3.Select(res.a, k) == z3.Select(sv.a, lo + k))))
    return res
```
- 순서 고정: 인자 평가(기존) → `string_slice_range` → `utf8_boundary` → fresh(카운터 1) → 길이 가정 → 바이트 관계 가정.
- node = substr Call 식(두 의무 같은 node, 코드가 달라 중복 제거 키가 다르다). key_extra 없음, cand 없음.
- 묶인 변수는 고정 이름 정수 상수 **`str!k`**(카운터 안 씀). patterns 없음. `lo + k` 는 `lo + k` 순서.
- 길이 가정은 `res.n == hi - lo` 한 항(`res.n >= 0` 이나 MAX_LEN 가정·`u8_dom` 을 따로 넣지 않는다).
- `s.assume(st, g, ..)` 는 호출 결과 가정과 같은 헬퍼(g 가 있으면 함의). Rs 도 같은 `assume`.
- 실패 처리는 기존 `prove` 그대로(파생 중복 제거 규칙을 새로 만들지 않음, 결정 8).
- Rs `call` 내장 매칭에 같은 자리·같은 순서로.

### 2.5 그 밖
- `len`·`copy`·Index·재바인딩·return·ensures·havoc·반례: 바꾸지 않는다(배열 길로 그대로 처리됨). 다만 Rs 에서 `Ty::Str`/`Val::Arr` 를 거부하는 매칭이 있으면 배열과 같게 고친다.
- Py `ev` 맨 끝 예외·Rs 다른 `Err` 문구는 그대로.

## 3. FIX 표

Py `FIX` 딕셔너리에서 `elem_range` 다음, Rs `obligation.rs` `fix_for` 같은 자리에 두 줄(글자 그대로):

```
string_slice_range: keep 0 <= lo <= hi <= len(s) for substr(s, lo, hi): bound lo and hi with requires, an if, or a loop invariant (a counterexample str may not be valid UTF-8)
utf8_boundary: cut a str only at character boundaries: require or check is_char_boundary(s, lo) and is_char_boundary(s, hi) (a counterexample str may not be valid UTF-8)
```

진단 message 는 기존 형식 `cannot prove <what> in <fn>`. 예: `cannot prove substr range 0 <= lo <= hi <= len(literal) in f`, `cannot prove substr cuts of s at UTF-8 character boundaries in f`.

## 4. 가드

- 증명 층 가드 skip 에 `"str"` 을 더한다: Py `verify.verify_program` 맨 앞 `g2_unimplemented_error(prog, "verify", skip=("array_u8", "array_bool", "str"))`, Rs `lib.rs` `verify_program_opts` 맨 앞 `&["array_u8", "array_bool", "str"]`. 주석은 `G2 B1`.
  - 이제 skip 이 모든 G2 타입을 덮으므로 이 가드는 항상 None 이다. 그래도 지우지 않는다(A6 i32 가 오면 다시 쓴다).
- 생성 층 가드 6곳은 바꾸지 않는다(str 은 stage `codegen` 으로 막힌다; driver 가드는 verify 성공 뒤에도 돈다).

## 5. 표본(시험 작업자, `tests/must_reject/`)

`.json` 키: `stage`, `code`, 선택 `flags`, 선택 `cex_contains`(stdout+stderr 부분 문자열). 각 표본은 목표 오류 앞의 다른 의무가 모두 성립하게 쓴다. 문법: `while` 은 `decreases` 필수, 식 문장은 호출만, 모든 경로 `return`, 식별자에 `__` 금지, 같은 스코프 가림 금지, 리터럴을 코드에 쓰면 함수에 `! alloc`.

### 5.1 B0 가드 표본 옮기기(증명 통과 → 생성 층 거부)
`g2b_b0_verify_layer`, `g2b_b0_literal_verify`, `g2b_b0_infer_layer`(flags `--infer` 유지), `g2b_b0_guard_order`(cex `"line": 5, "col": 5` 유지), `g2b_b0_guard_lit_first`(cex `"line": 4, "col": 20` 유지): `.json` 의 `stage` 를 `"verify"` → `"codegen"`. `.pruv` 첫 줄 주석을 "B1부터 증명은 통과하고 생성 층이 거부" 뜻으로 고친다(프로그램 본문은 그대로). 예외: `g2b_b0_guard_lit_first` 의 `return k + len(s) + n;` 은 증명이 돌면서 범위를 모르는 `n` 때문에 overflow 가 먼저 나므로 `return k + len(s);` 로 고쳤다(위치 4:20 은 그대로).

### 5.2 G2_SPEC 6.3 verify 표본(새로)
| 이름 | 내용 | stage/code |
|---|---|---|
| `g2b_slice_range` | `substr("abc", 2, 1)` (lo > hi, 두 경계는 성립) | verify / `string_slice_range` |
| `g2b_slice_start` | `substr("é", 1, 2)` | verify / `utf8_boundary` |
| `g2b_slice_end` | `substr("é", 0, 1)` | verify / `utf8_boundary` |
| `g2b_index` | `let s: str = "ab"; return s[len(s)];` | verify / `index_oob` |
| `g2b_contract_index` | `fn f(s: str) -> i64 requires s[len(s)] >= 0` | verify / `contract_domain` |

### 5.3 B1 양성 증명 표본(증명 통과 → stage `codegen` / `unsupported_type`)
이름 `g2b_b1_ok_*`. 증명이 통과해야 codegen 단계까지 간다.
- `g2b_b1_ok_len`: assert 로 바이트 길이 `len("")==0`, `len("a")==1`, `len("é")==2`, `len("안")==3`, `len("😀")==4`, `len("\0")==1`, `len("a\0b")==3`, `len("안녕")==6`, 그리고 바이트 값 `"é"[0]==195`, `"é"[1]==169`, `"\0"[0]==0`, `"안"[0]==236`.
- `g2b_b1_ok_boundary`: assert 로 `is_char_boundary("é",0)`, `!is_char_boundary("é",1)`, `is_char_boundary("é",2)`, `!is_char_boundary("é",-1)`, `!is_char_boundary("é",3)`, `is_char_boundary("",0)`, `is_char_boundary("abc",1)`, `!is_char_boundary("😀",1)`·`2`·`3`, `is_char_boundary("😀",4)`, `is_char_boundary("안a",3)`.
- `g2b_b1_ok_flow`: 리터럴 → copy → substr → 함수 반환 → 호출자. 예: `fn head(s: str, i: i64) -> str ! alloc requires 0 <= i && i <= len(s) requires is_char_boundary(s, i) ensures len(result) == i ensures forall k in 0..i: result[k] == s[k]` 본문 `let c: str = copy(s); let d: str = substr(c, 0, i); return d;` 그리고 `fn use(..) -> i64 ! alloc` 에서 `let a: str = "안녕"; let b: str = head(a, 3); assert len(b) == 3; assert b[0] == 236;` 와 `let t: str = substr("héllo", 1, 3); assert len(t) == 2 && t[0] == 195 && t[1] == 169;`.
- `g2b_b1_ok_param`: str 매개변수 바이트 범위 가정(진입·호출 결과): `requires len(s) > 0` 에서 `let b: i64 = s[0]; assert b >= 0 && b <= 255;`, 그리고 str 을 돌려주는 함수를 부른 결과의 첫 바이트도 같은 assert.
- `g2b_b1_ok_loop`: 루프 안에서 다시 대입하는 `let mut t: str` (havoc) 뒤 바이트 범위 assert, 그리고 `while` 로 `s` 의 바이트를 세는 정상 루프(invariant·decreases 포함).
- `g2b_b1_ok_contract`: 계약에서 `is_char_boundary`·`len`·`s[i]`·리터럴: 예 `fn g(s: str, i: i64) -> bool ensures result == is_char_boundary(s, i) { return is_char_boundary(s, i); }`, `requires len(s) >= len("ab")` 와 `requires len(s) > 0 ==> s[0] >= 0`.
- `g2b_b1_ok_infer`(flags `["--infer"]`): 불변식 없이는 증명 안 되고 `--infer` 가 찾는 기존 템플릿(예: `0 <= i && i <= len(s)`) 으로 되는 str 루프. 추론이 못 찾으면 이 표본 대신 불변식을 적은 루프를 쓰고, 그 사실을 첫 줄 주석에 적는다.

### 5.4 B1 거부 표본(증명이 실제로 판정하는지, 공허하지 않은지)
| 이름 | 내용 | stage/code |
|---|---|---|
| `g2b_b1_bad_len` | `assert len("안") == 2;` | verify / `assert` |
| `g2b_b1_bad_boundary` | `assert is_char_boundary("é", 1);` | verify / `assert` |
| `g2b_b1_bad_byte` | `assert "é"[1] == 168;` | verify / `assert` |
| `g2b_b1_param_boundary` | `fn f(s: str, i: i64) -> str ! alloc requires 0 <= i && i <= len(s) { return substr(s, 0, i); }` — cex_contains `"first"` (str 반례가 배열 모양) | verify / `utf8_boundary` |
| `g2b_b1_param_range` | `requires 0 <= i` 만 두고 `substr(s, i, len(s))` (i > len(s) 가능) — 첫 진단이 `string_slice_range` | verify / `string_slice_range` |
| `g2b_b1_infer_boundary` (flags `["--infer"]`) | 정상 `while` 루프(불변식 적음) 뒤 경계를 모르는 `substr(s, 0, i)` 를 반환 — `--infer` 에서도 `utf8_boundary` 로 거부 | verify / `utf8_boundary` |
| `g2b_b1_substr_bytes` | `let t: str = substr("héllo", 1, 3); assert t[0] == 104;`(실제 195) | verify / `assert` |
| `g2b_b1_ensures_len` | `fn h(s: str) -> str ! alloc requires len(s) >= 2 && is_char_boundary(s, 1) ensures len(result) == 2 { return substr(s, 0, 1); }` | verify / `ensures` |

### 5.5 감사 뒤 더한 표본
- `g2b_b1_ok_boundary2`(양성): 내부 선행 바이트 194·195·236 은 경계, continuation 191 은 아님, `substr("é",0,0)`, 3바이트 `substr("안녕",3,6)`, 4바이트 `substr("😀a",0,4)` `"a~"`(126) 내부 ASCII — 192 문턱을 191 로 내리는 변이, 128 문턱을 올리는 변이(`ok_boundary` 의 😀 3번=128), 127 미만으로 내리는 변이(126)를 잡는다. 127(DEL)은 리터럴에 쓸 수 없어 `b<127` 변이는 표본이 없다.
- `g2b_b1_bad_cont`(assert), `g2b_b1_slice_mid_empty`(`substr("é",1,1)` → utf8_boundary), `g2b_b1_slice_neg`(음수 lo → string_slice_range), `g2b_b1_slice_over`(hi > len → string_slice_range, 뒤에 utf8_boundary 도 남).

- run_all·diff_compilers 는 기대 code 가 진단 중에 **있는지**만 본다. 의무 순서(range → boundary)는 메인이 두 판을 직접 실행해 확인했다(자동 검사 아님).

### 5.6 알려진 한계
- `--infer` 후보는 리터럴이 든 식을 만들지 않는다(Py `show` 의 `_Skip`, Rs `show` None). 그래서 `while i < len("abcd")` 처럼 루프 조건에 리터럴이 있으면 경계 후보가 없어 추론이 못 한다(완전성 한계, 두 판 같음). 불변식을 적거나 길이를 변수에 담아 쓴다.
- SMT 가 같아도 str(배열) 반례 값이 두 판에서 다를 수 있다(z3 모델 선택; diff_trace `cex_only`). 결정 11 에 따라 새 표본은 `same` 이어야 하므로, 표본의 `cex_contains` 는 반례 값에 기대지 않는다.

## 6. 확인(메인)

- 빌드, `run_all --backend both`(행 목록 갱신 `--list-rows`), SMT 231 cmp, 새 표본 `diff_trace`(플래그 없음·`--flags=--infer`, same 만), `diff_parse`·`diff_compilers --only must_reject --backend both`, `m3_all`, `cli_also_llvm`, `inference --regress`, 퍼저, cargo 시험.
