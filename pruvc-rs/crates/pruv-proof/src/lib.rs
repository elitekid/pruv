//! pruv-proof: Python `pruvc/verify.py` 의 z3 층을 옮긴 크레이트.
//!
//! 구성(verify.py 와 같은 구조):
//! - `sys`        : z3-sys 위의 작은 래퍼. **unsafe 는 이 모듈에만** 있다(아래 `deny`).
//! - `model`      : `Opt`/`Res` Datatype, 사용자 struct/enum `Model`, `_MODEL_SEQ`
//! - `symbolic`   : `State`/`Arr`/`FnVerifier`: fresh, wf, havoc, 집계 보조정리, 식 `ev`, 정의역 `dom`, 문 `exec`, `run`
//! - `obligation` : `prove`(pc → guard → (lemmas) → Not(ob), timeout 8000ms, seen 키), 반례 `cex`/`fmt_val`, trace
//! - `samples`    : 표본 .pruv 6개의 의무를 손으로 옮긴 빌더(0B 시제품; `pruv-proof-spike` 가 쓴다)
//!
//! 공개 진입은 [`verify_program`]. 같은 입력에서 의무마다 z3 에 넘기는 SMT-LIB 텍스트·판정·오류 JSON 이
//! Python 과 바이트 동일해야 한다(SPEC 6절).
//!
//! 왜 고수준 `z3` 크레이트 대신 sys 를 직접 쓰는가: z3py 와 SMT 텍스트가 글자 단위로 같아야 하는데
//! (SPEC 6절) 고수준 크레이트는 양화 weight/qid, Datatype 생성 호출 방식 등이 z3py 와 다를 수 있다.
//! `z3` 의존은 `vendored` 로 z3-sys/z3-src 를 끌어오는 용도로 둔다.
#![deny(unsafe_code)]

#[allow(unsafe_code)]
pub mod sys;

pub mod infer;
pub mod model;
pub mod obligation;
pub mod samples;
pub mod symbolic;

use pruv_core::ast::Program;
use pruv_core::diagnostic::PruvError;
use pruv_core::typeinfo::TypeTable;

use crate::model::{decls_from_ast, next_seq, Model, Prelude};
use crate::obligation::Trace;
use crate::symbolic::FnVerifier;
use crate::sys::Z3;

/// 실행 중인 libz3 의 전체 버전 문자열(Python `z3.get_full_version()` 대응).
pub fn z3_full_version() -> String {
    sys::full_version()
}

/// verify.py `verify_program(prog)` (864행). 검사를 통과한 프로그램의 증명 오류를 함수·의무 순서대로 돌려준다.
///
/// - Python 은 프로그램 전체에 `Model` 하나(`_MODEL_SEQ` 한 번 증가)를 만들고 모든 함수가 공유한다. 여기서는
///   순번을 한 번만 받고, 함수마다 새 z3 컨텍스트에 같은 순번으로 `Model` 을 다시 만든다(식 텍스트가 같다).
/// - `tt` 는 쓰지 않는다: Python 도 `Model(prog)` 안에서 `TypeTable(prog)` 를 새로 만든다(검사기가 만든 것과 같은 표).
/// - `rec`: 어댑터 trace 기록(`Trace::adapter()`). None 이면 기록하지 않는다.
/// - Python 의 예외(내부 실패)는 `Err(메시지)` — 그때까지 모은 오류는 버려진다(Python 도 예외로 반환값이 없다).
pub fn verify_program(prog: &Program, tt: &TypeTable, rec: Option<&mut Trace>) -> Result<Vec<PruvError>, String> {
    verify_program_opts(prog, tt, rec, &VerifyOptions { infer: false }, None)
}

/// STAGE1 B2 옵션.
#[derive(Clone, Copy, Debug, Default)]
pub struct VerifyOptions {
    /// `--infer`: 함수마다 템플릿 Houdini 불변식 추론(infer.rs) 뒤 살아남은 후보와 함께 검증한다.
    pub infer: bool,
}

/// verify.py `verify_program(prog, rec, infer, report)`. `infer=false` 는 기존 경로 그대로.
/// `report` 가 Some 이면 루프별 보고 레코드(docs/STAGE1_B_INFER.md 5절)를 함수 순서·루프 번호 순으로 push 한다
/// (함수 하나를 끝낼 때마다: 뒤 함수에서 내부 실패가 나도 앞 함수의 레코드는 남는다).
/// 추론 모드에서는 함수마다 탐색 회차마다·최종 검증마다 새 z3 컨텍스트(+Prelude, 같은 seq 의 Model)를 만든다.
pub fn verify_program_opts(
    prog: &Program,
    _tt: &TypeTable,
    rec: Option<&mut Trace>,
    opts: &VerifyOptions,
    mut report: Option<&mut Vec<pruv_core::pyjson::Json>>,
) -> Result<Vec<PruvError>, String> {
    // G2: [i64] 밖의 배열 타입은 증명 층이 아직 없다. z3 컨텍스트·순번을 만들기 전에 막는다.
    if let Some(e) = pruv_core::typeinfo::g2_unimplemented_error(prog, "verify") {
        return Ok(vec![e]);
    }
    let mut local = Trace::off();
    let trace: &mut Trace = match rec {
        Some(t) => t,
        None => &mut local,
    };
    let decls = decls_from_ast(&prog.types);
    let seq = next_seq();
    {
        // Python 은 함수 수와 상관없이 Model 을 먼저 만든다: 모델 구성 실패는 함수가 없어도 난다.
        let z = Z3::new();
        let pre = Prelude::new(&z);
        Model::with_seq(&z, &pre, &decls, seq)?;
    }
    let mut errors: Vec<PruvError> = Vec::new();
    if opts.infer {
        for f in &prog.functions {
            let res = infer::infer_function(prog, f, &decls, seq, &mut *trace)?;
            let before = errors.len();
            if res.status == infer::InferStatus::Timeout {
                errors.push(PruvError {
                    stage: "verify".to_string(),
                    line: f.line,
                    col: f.col,
                    code: "inference_timeout".to_string(),
                    message: format!(
                        "invariant inference for {} hit the time safety limit (5 s per function, 500 ms per query)",
                        f.name
                    ),
                    fix: "write the loop invariants explicitly, or compile without --infer".to_string(),
                    counterexample: None,
                });
            } else {
                let z = Z3::new();
                let pre = Prelude::new(&z);
                let model = Model::with_seq(&z, &pre, &decls, seq)?;
                let mut fv = FnVerifier::for_function(&z, &pre, &model, &mut *trace, prog, f);
                fv.set_extra(res.extra());
                fv.run()?;
                errors.append(&mut fv.errors);
            }
            if let Some(rep) = report.as_mut() {
                rep.extend(res.records(errors.len() - before));
            }
        }
        return Ok(errors);
    }
    for f in &prog.functions {
        // 함수마다 새 컨텍스트(논-rc 컨텍스트는 AST 를 지우지 않으므로 함수가 끝나면 통째로 버린다).
        // 반례 모델 값은 Python 과 다를 수 있다(SMT 텍스트·판정은 같음). 원인 추정: z3py 는 rc 컨텍스트라 AST 번호가 재사용돼
        // 고르는 모델이 달라진다(프로그램당 컨텍스트 하나로 바꿔도 반례 차이는 그대로였음, RESULTS 18절).
        let z = Z3::new();
        let pre = Prelude::new(&z);
        let model = Model::with_seq(&z, &pre, &decls, seq)?;
        let mut fv = FnVerifier::for_function(&z, &pre, &model, &mut *trace, prog, f);
        fv.run()?;
        errors.append(&mut fv.errors);
    }
    Ok(errors)
}
