# Vow

AI가 코드를 쓰고, 사람은 약속(계약)만 읽고, 컴파일러가 그 코드가 약속을 지킨다고 증명하는 언어.
증명된 안전장치(범위 검사, 오버플로 검사)는 지워서 빠르게 돌린다.

- 언어 명세: [SPEC.md](SPEC.md)
- 청사진(목표·단계 계획): [BLUEPRINT.md](BLUEPRINT.md)
- 실험 결과: [RESULTS.md](RESULTS.md)

## 지금 상태 (시제품 v0.1)
컴파일러 `vowc/`는 Python 3.9 + z3 시제품이다: 파서 → 타입·효과 검사 → z3 증명 → Rust 코드 생성 → rustc.
단기 목표는 Python·rustc 없이 실행 파일 하나로 쓰는 독립 컴파일러다(BLUEPRINT 4절).

```
python3 -m venv .venv && .venv/bin/pip install z3-solver
.venv/bin/python vowc/vowc.py examples/sum.vow -o sum.rs && rustc -O sum.rs
```
