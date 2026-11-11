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
     "flags": ["--infer", "--show-inferred"],  (생략 가능)
     "note": "무엇을 보는 시험인지"}

- `expect ok`: 종료 0. 객체: 종료 1 이고 그 stage/code 오류가 하나 이상.
- `kept`: 각 문자열이 어떤 레코드의 `invariants` 안 `invariant TEXT` 와 정확히 같다.
- `dropped`: 각 문자열이 어떤 레코드 `dropped[].text` 와 같다.
- `status`: 그 함수의 모든 레코드 `status` 가 해당 값 하나.
- `noinfer`: `--infer` 없이 다시 컴파일해 `ok`(종료 0) 또는 `reject`(종료 1).

기대값은 문서의 후보 규칙을 손으로 따라가 적은 것이라, 실제 실행과 다르면 추론기가 아니라 기대값이 틀렸는지 먼저 본다.
