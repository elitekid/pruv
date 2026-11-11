# 1단계 B2 `--infer` 시험

명세: `docs/STAGE1_B_INFER.md`. 각 `inf_*.pruv` 옆에 같은 이름 `.json`(기대값)이 있다.

## 실행

    .venv/bin/python tests/inference/run.py --compiler py|rs [--regress] [--jobs N] [이름 ...]

- `--compiler`/`--compiler-path`: `tests/compiler_driver.py` 와 같다(기본 rs).
- 각 `.pruv` 를 `--backend rust` + json 의 `flags`(기본 `["--infer", "--show-inferred"]`)로 컴파일한다.
  stdout 의 JSON 줄은 오류, stderr 의 JSON 줄은 `--show-inferred` 레코드로 읽는다.
- `--regress`: 추가로 `tests/must_reject/*.pruv` 가 `--infer` 에서도 여전히 거부되는지(옆 json 의 stage/code 포함),
  `exit` 키가 있는 `examples/`·`tests/runtime/` 시험과 `bench/solutions/pruv_agg/*.pruv` 가
  `--infer` 로도 컴파일 성공하는지 본다.
- 끝에 `TOTAL 통과/전체` 와 실패 목록을 찍고, 모두 통과면 종료 0, 아니면 1.

## json 형식

    {"expect": "ok" | {"stage": "verify", "code": "..."},
     "noinfer": "ok" | "reject",          (생략 가능)
     "kept": ["..."], "dropped": ["..."],  (생략 가능)
     "dropped_round": {"TEXT": 회차},      (생략 가능: 그 후보가 그 회차에 빠졌는지)
     "status": {"<fn>": "verified|selected|budget_exhausted|timeout|none"},  (생략 가능)
     "absent": ["..."],                    (생략 가능: 생성되지 않아야 하는 후보)
     "fallback": {"<fn>": true | false},   (생략 가능: 버전 1 되돌림 여부)
     "flags": ["--infer", "--show-inferred"],  (생략 가능)
     "note": "무엇을 보는 시험인지"}

- `expect ok`: 종료 0. 객체: 종료 1 이고 그 stage/code 오류가 하나 이상.
- `kept`: 각 문자열이 어떤 레코드의 `invariants` 안 `invariant TEXT` 와 정확히 같다.
- `dropped`: 각 문자열이 어떤 레코드 `dropped[].text` 와 같다.
- `status`: 그 함수의 모든 레코드 `status` 가 해당 값 하나.
- `absent`: 각 문자열이 어떤 레코드의 `invariants` 안 `invariant TEXT` 에도, `dropped[].text` 에도 없다(= 보고에 나오지 않음; `capped` 로 잘린 후보와 되돌림이 지운 첫 탐색 기록은 원래 보이지 않으므로 "생성 안 됨"의 완전한 증명은 아니다).
- `fallback`: 함수 이름 → true/false. 그 함수 레코드에 `"fallback": "v1"` 키가 있는지(true: 모든 레코드에 있음, false: 어느 레코드에도 없음).
- `noinfer`: `--infer` 없이 다시 컴파일해 `ok`(종료 0) 또는 `reject`(종료 1).

## B+ 표본(종류 12·13·14, 명세 3.7)

- `inf_range_gcd`: 종류 12. `x = a; y = b` 의 하한 `x >= 0`·`y >= 0` 이 남아 `result >= 0` 증명(noinfer reject).
- `inf_prefix_store`: 종류 13. 뒤집기의 `forall k in 0..i: out[k] == a[n - 1 - k]` 와 `len(out) == n` 이 남아 ok(noinfer reject).
- `inf_early_return`: 종류 14. 정렬 판정의 `forall k in 1..i: !(a[k - 1] > a[k])` 가 남아 ok(noinfer reject).
- `inf_rej_range_wrong`: 종류 12 거짓 후보 `x >= 0` 이 보존에서 탈락하고 참인 `x <= 100` 만 남아 ok.
- `inf_rej_early_domain`: 종류 14 후보가 정의역에서 탈락(나눗셈 `10 / a[k]` 의 `a[k] > 0` 은 루프 조건으로 현재 i 에만 알려짐). 함수는 후보 없이 ok.
- `inf_rej_prefix_wrong_post`: 종류 13 후보는 남지만 ensures(`result[j] == a[j]`)가 틀려 `ensures` 오류.
- `inf_budget_fallback`: 버전 1 되돌림(명세 4.1). 종류 12 후보 사슬 `a0 = a1; … a19 = i + 1`(20개)이 첫 탐색 질의 512 를 소진 → 종류 1~11 만으로 다시 탐색해 `0 <= i`·`i <= n` 이 남아 ok(noinfer reject). `fallback {"chain": true}`. absent 의 `a0 >= 0` 등은 첫 탐색에서는 생성되지만 되돌림이 그 기록을 지우므로, 여기서는 "되돌림 결과(남은 불변식·탈락 기록)에 종류 12 가 없다"는 뜻이다.
- `inf_range_strict`: 종류 12 의 `srng`. 엄격 부등호(`a > -5` → 하한 -4, `a < 100` → 상한 99)·`-리터럴`·괄호 속 중첩 `&&`(`_conj_terms` 재귀)를 본다. `x >= -4`·`x <= 99` 가 남아 ok(noinfer reject).
- `inf_prefix_copy`: 종류 13 의 시작값이 `copy(a)` 인 경우. `forall k in 0..i: out[k] == a[k] * 2` 와 `len(out) == len(a)` 가 남아 ok(noinfer reject).
- `inf_absent_shapes`: 생성되지 않아야 하는 꼴 셋(absent): else 가 있는 조기 반환 `if`, 증가폭 2 카운터 앞의 `out[i] = 7`, then 이 두 문장인 `if`. 함수는 종류 1 의 `0 <= i` 로 ok(noinfer reject).
- ensures 의 묶인 이름을 `j` 로 써서 후보의 묶인 이름이 `k` 가 되게 했다(함수 안에 `k` 가 있으면 `k_1`).

기대값은 문서의 후보 규칙을 손으로 따라가 적은 것이라, 실제 실행과 다르면 추론기가 아니라 기대값이 틀렸는지 먼저 본다.
