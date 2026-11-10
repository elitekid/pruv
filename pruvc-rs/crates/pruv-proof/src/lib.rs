//! pruv-proof: Python `pruvc/verify.py` 의 z3 층을 옮기는 크레이트(0B 시제품 단계).
//!
//! 구성(verify.py 와 같은 구조):
//! - `sys`        : z3-sys 위의 작은 래퍼. **unsafe 는 이 모듈에만** 있다(아래 `deny`).
//! - `model`      : `Opt`/`Res` Datatype, 사용자 struct/enum `Model`, `_MODEL_SEQ`
//! - `symbolic`   : `State`/`Arr`/`FnVerifier`: fresh, wf, havoc, 집계 보조정리, 양화 조각
//! - `obligation` : `prove`(pc → guard → (lemmas) → Not(ob), timeout 8000ms, seen 키)와 trace JSON
//! - `samples`    : 표본 .pruv 6개의 의무를 손으로 옮긴 빌더(파서 없음)
//!
//! 왜 고수준 `z3` 크레이트 대신 sys 를 직접 쓰는가: z3py 와 SMT 텍스트가 글자 단위로 같아야 하는데
//! (SPEC 6절) 고수준 크레이트는 양화 weight/qid, Datatype 생성 호출 방식 등이 z3py 와 다를 수 있다.
//! `z3` 의존은 `vendored` 로 z3-sys/z3-src 를 끌어오는 용도로 둔다.
#![deny(unsafe_code)]

#[allow(unsafe_code)]
pub mod sys;

pub mod model;
pub mod obligation;
pub mod samples;
pub mod symbolic;

/// 실행 중인 libz3 의 전체 버전 문자열(Python `z3.get_full_version()` 대응).
pub fn z3_full_version() -> String {
    sys::full_version()
}
