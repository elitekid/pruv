//! pruv-core: 앞단(AST·lexer·parser·typeinfo·check)과 코드 생성 공통부.
//!
//! M3 1단계: ast·diagnostic·lexer·parser·dump(시험 스키마) 이식 완료. 모듈 계획(docs/M3_C4_SPEC.md 2절 표):
//!
//! | 모듈            | Python 대응        | 담당                                         |
//! |-----------------|--------------------|----------------------------------------------|
//! | `ast`           | `vast.py`          | 식 14·문 10·선언/보조 9 = 33 노드, Type 은 이름 하나 |
//! | `diagnostic`    | `vast.PruvError`   | 오류 형식, line/col 은 1부터 유니코드 문자 단위  |
//! | `lexer`/`parser`| `vparser.py`       | 토큰·위치·재귀 하강·음수 리터럴 접기             |
//! | `typeinfo`      | `typeinfo.py`      | 명목 타입·선언 순서·안정적 의존 순서             |
//! | `check`         | `check.py`         | 타입·효과·소유·재귀 금지·첫 오류 순서            |
//! | `codegen`       | `codegen.py`       | Rust 출력(마지막 단계)                          |
//! | `llvmgen`/`abi` | `llvmgen.py`       | LLVM IR 텍스트, 대상 wrapper                    |
//!
//! 규칙: 검사 뒤 AST 는 읽기 전용. 순회 결과가 출력에 들어가면 순서를 정의한다.

/// AST 덤프(JSON)의 스키마 식별자.
pub const SCHEMA_AST: &str = "pruv-ast-v1";

pub mod abi;
pub mod ast;
pub mod bindings;
pub mod check;
pub mod diagnostic;
pub mod dump;
pub mod emit_common;
pub mod lexer;
pub mod llvmgen;
pub mod parser;
pub mod pyjson;
pub mod pyrepr;
pub mod pyrepr_table;
pub mod typeinfo;

/// 공개 진입: 소스 문자열을 파싱한다(개행 정규화 포함).
pub fn parse(src: &str) -> Result<ast::Program, diagnostic::PruvError> {
    parser::parse_source(src)
}
