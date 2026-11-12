//! pruv-core: the frontend (AST, lexer, parser, typeinfo, check) and the shared code-generation parts.
//!
//! M3 stage 1: porting of ast, diagnostic, lexer, parser, dump (test schema) is complete. Module plan (docs/M3_C4_SPEC.md §2 table):
//!
//! | Module          | Python counterpart | Responsibility                               |
//! |-----------------|--------------------|----------------------------------------------|
//! | `ast`           | `vast.py`          | 14 expressions, 10 statements, 9 declarations/helpers = 33 nodes, Type is a single name |
//! | `diagnostic`    | `vast.PruvError`   | error format, line/col are 1-based in Unicode characters |
//! | `lexer`/`parser`| `vparser.py`       | tokens, positions, recursive descent, negative-literal folding |
//! | `typeinfo`      | `typeinfo.py`      | nominal types, declaration order, stable dependency order |
//! | `check`         | `check.py`         | types, effects, ownership, recursion ban, first-error order |
//! | `codegen`       | `codegen.py`       | Rust output (final stage)                    |
//! | `llvmgen`/`abi` | `llvmgen.py`       | LLVM IR text, target wrapper                 |
//!
//! Rule: the AST is read-only after checking. If a traversal result goes into the output, define its order.

/// Schema identifier of the AST dump (JSON).
pub const SCHEMA_AST: &str = "pruv-ast-v1";

pub mod abi;
pub mod ast;
pub mod bindings;
pub mod check;
pub mod codegen;
pub mod diagnostic;
pub mod dump;
pub mod emit_common;
pub mod foreign;
pub mod foreign_codegen;
pub mod foreign_shim;
pub mod gtype;
pub mod lexer;
pub mod llvmgen;
pub mod modules;
pub mod mono;
pub mod parser;
pub mod parallel_shim;
pub mod pyio;
pub mod pyjson;
pub mod pyrepr;
pub mod pyrepr_table;
pub mod refine;
pub mod typeinfo;

/// Public entry: parses a source string (including newline normalization).
pub fn parse(src: &str) -> Result<ast::Program, diagnostic::PruvError> {
    parser::parse_source(src)
}
