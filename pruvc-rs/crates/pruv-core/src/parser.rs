//! 재귀 하강 파서 (vparser.py 의 Parser 를 한 줄씩 옮김).

use crate::ast::*;
use crate::diagnostic::PruvError;
use crate::lexer::{lex, Kind, Tok};
use crate::pyrepr::repr_str;

type R<T> = Result<T, PruvError>;

const CMP_OPS: [&str; 6] = ["==", "!=", "<=", ">=", "<", ">"];

/// 공개 진입: Python open().read() 의 universal newline 을 먼저 적용한다.
pub fn parse_source(src: &str) -> R<Program> {
    let norm = src.replace("\r\n", "\n").replace('\r', "\n");
    let chars: Vec<char> = norm.chars().collect();
    let mut p = Parser { t: lex(&chars)?, i: 0, depth: 0 };
    p.program()
}

/// 음수 접기용 십진 문자열 부호 반전("0" 은 그대로).
fn negate(v: &str) -> String {
    if v == "0" {
        "0".to_string()
    } else if let Some(rest) = v.strip_prefix('-') {
        rest.to_string()
    } else {
        format!("-{}", v)
    }
}

fn is_upper(s: &str) -> bool {
    s.chars().next().map_or(false, |c| c.is_ascii_uppercase())
}

struct Parser {
    t: Vec<Tok>,
    i: usize,
    /// 지금 만드는 AST 경로의 깊이(재귀 + 왼쪽으로 쌓이는 이항·접미 사슬). MAX_DEPTH 를 넘으면 Python 의
    /// RecursionError 처럼 내부 오류로 멈춘다: 넘는 AST 는 파서·검사·검증·생성의 재귀가 1GB 스택도 넘길 수 있다.
    depth: usize,
}

/// AST 깊이 한도. Python 은 약 1000 단계에서 RecursionError 로 멈추므로(비교 범위 밖) 이보다 훨씬 크게,
/// 그러나 뒤 단계 재귀가 1GB 스택 안에 들도록 정했다(RESULTS 20절).
pub const MAX_DEPTH: usize = 50_000;

impl Parser {
    // ---- 보조 ----
    fn idx(&self, k: usize) -> usize {
        (self.i + k).min(self.t.len() - 1)
    }

    /// 깊이 한 단계 더하기(넘으면 내부 오류). 짝인 leave 로 되돌린다.
    fn enter(&mut self, n: usize) -> R<()> {
        self.depth += n;
        if self.depth > MAX_DEPTH {
            return Err(PruvError::new("internal", 0, 0, "internal_error", "maximum recursion depth exceeded", ""));
        }
        Ok(())
    }

    // 오류로 빠져나갈 때는 깊이를 되돌리지 않는다(파싱 전체가 멈추므로). 그래서 빼기는 포화로.
    fn leave(&mut self, n: usize) {
        self.depth = self.depth.saturating_sub(n);
    }

    fn peek(&self, k: usize) -> &Tok {
        &self.t[self.idx(k)]
    }

    fn at(&self, val: &str, k: usize) -> bool {
        let t = &self.t[self.idx(k)];
        (t.kind == Kind::Op || t.kind == Kind::Kw) && t.val == val
    }

    fn next(&mut self) -> Tok {
        let t = self.t[self.idx(0)].clone();
        self.i += 1;
        t
    }

    fn err<M: Into<String>, F: Into<String>>(&self, msg: M, fix: F, tok: Option<&Tok>) -> PruvError {
        let t = match tok {
            Some(t) => t,
            None => self.peek(0),
        };
        PruvError::new("parse", t.line, t.col, "syntax", msg, fix)
    }

    fn expect(&mut self, val: &str) -> R<()> {
        if !self.at(val, 0) {
            let t = self.peek(0);
            let found = if t.kind == Kind::Eof { "end of file".to_string() } else { t.repr() };
            return Err(self.err(format!("expected '{}' but found {}", val, found), format!("insert '{}'", val), None));
        }
        self.bump();
        Ok(())
    }

    // 받은 토큰이 필요할 때만 복제한다(감사: 자주 도는 경로의 토큰 복제 제거).
    fn expect_tok(&mut self, val: &str) -> R<Tok> {
        self.expect(val)?;
        Ok(self.t[self.i - 1].clone())
    }

    fn bump(&mut self) {
        self.i += 1;
    }

    fn ident(&mut self) -> R<Tok> {
        let t = self.peek(0);
        if t.kind != Kind::Id {
            return Err(self.err(format!("expected identifier, found {}", t.repr()), "", None));
        }
        Ok(self.next())
    }

    // ---- 프로그램 ----
    fn program(&mut self) -> R<Program> {
        let mut p = Program::default();
        while self.peek(0).kind != Kind::Eof {
            if self.at("struct", 0) {
                p.types.push(TypeDecl::Struct(self.struct_decl()?));
            } else if self.at("enum", 0) {
                p.types.push(TypeDecl::Enum(self.enum_decl()?));
            } else {
                p.functions.push(self.function()?);
            }
        }
        Ok(p)
    }

    fn unsupported(&self, what: &str, tok: &Tok) -> PruvError {
        PruvError::new(
            "parse",
            tok.line,
            tok.col,
            "unsupported_type",
            format!("{} is not supported", what),
            "arrays hold i64 and Option/Result hold i64; user types can only be used directly",
        )
    }

    fn field_decl(&mut self) -> R<FieldDecl> {
        let n = self.ident()?;
        self.expect(":")?;
        let ty = self.type_()?;
        Ok(FieldDecl { line: n.line, col: n.col, name: n.val, ty })
    }

    /// `name: Type, ...` 를 close 앞까지(close 는 소비 안 함); 끝 쉼표 허용
    fn field_list(&mut self, close: &str) -> R<Vec<FieldDecl>> {
        let mut out = Vec::new();
        while !self.at(close, 0) {
            out.push(self.field_decl()?);
            if !self.at(close, 0) {
                self.expect(",")?;
            }
        }
        Ok(out)
    }

    fn struct_decl(&mut self) -> R<StructDecl> {
        let kw = self.expect_tok("struct")?;
        let n = self.ident()?;
        self.expect("{")?;
        let fields = self.field_list("}")?;
        self.expect("}")?;
        Ok(StructDecl { line: kw.line, col: kw.col, name: n.val, fields })
    }

    fn enum_decl(&mut self) -> R<EnumDecl> {
        let kw = self.expect_tok("enum")?;
        let n = self.ident()?;
        self.expect("{")?;
        let mut variants = Vec::new();
        while !self.at("}", 0) {
            let v = self.ident()?;
            let mut fields = Vec::new();
            if self.at("(", 0) {
                let lp = self.next();
                if self.at(")", 0) {
                    return Err(self.err(
                        "a variant without fields is written without parentheses",
                        format!("write `{}` instead of `{}()`", v.val, v.val),
                        Some(&lp),
                    ));
                }
                fields = self.field_list(")")?;
                self.expect(")")?;
            }
            variants.push(VariantDecl { line: v.line, col: v.col, name: v.val, fields });
            if !self.at("}", 0) {
                self.expect(",")?;
            }
        }
        self.expect("}")?;
        Ok(EnumDecl { line: kw.line, col: kw.col, name: n.val, variants })
    }

    fn type_(&mut self) -> R<Type> {
        if self.at("(", 0) {
            self.bump();
            self.expect(")")?;
            return Ok("unit".to_string());
        }
        if self.at("[", 0) {
            self.bump();
            let e = self.ident()?;
            if e.val != "i64" {
                if is_upper(&e.val) {
                    return Err(self.unsupported(&format!("[{}]", e.val), &e));
                }
                return Err(self.err("only [i64] arrays exist", "use [i64]", Some(&e)));
            }
            self.expect("]")?;
            return Ok("array".to_string());
        }
        let n = self.ident()?;
        if n.val == "i64" {
            return Ok("i64".to_string());
        }
        if n.val == "bool" {
            return Ok("bool".to_string());
        }
        if n.val == "Option" || n.val == "Result" {
            self.expect("<")?;
            let e = self.ident()?;
            if e.val != "i64" {
                if is_upper(&e.val) {
                    return Err(self.unsupported(&format!("{}<{}>", n.val, e.val), &e));
                }
                return Err(self.err(format!("{} only holds i64", n.val), format!("use {}<i64>", n.val), Some(&e)));
            }
            self.expect(">")?;
            let name = if n.val == "Option" { "option" } else { "result" };
            return Ok(name.to_string());
        }
        // 사용자 타입: 이름 해석은 검사기가 한다. 내장 Type 이름의 소문자 철자는 별칭이 되면 안 된다.
        if matches!(n.val.as_str(), "unit" | "array" | "option" | "result") {
            return Err(self.err(
                format!("unknown type {}", repr_str(&n.val)),
                "use i64, bool, (), [i64], Option<i64>, Result<i64> or a declared struct/enum",
                Some(&n),
            ));
        }
        Ok(n.val)
    }

    fn function(&mut self) -> R<Function> {
        let kw = self.expect_tok("fn")?;
        let name = self.ident()?.val;
        self.expect("(")?;
        let mut params = Vec::new();
        while !self.at(")", 0) {
            let pn = self.ident()?.val;
            self.expect(":")?;
            let ty = self.type_()?;
            params.push(Param { name: pn, ty });
            if !self.at(")", 0) {
                self.expect(",")?;
            }
        }
        self.expect(")")?;
        self.expect("->")?;
        let ret = self.type_()?;
        let mut effects = Vec::new();
        if self.at("!", 0) {
            self.bump();
            loop {
                let e = self.ident()?;
                if e.val != "io" && e.val != "alloc" {
                    return Err(self.err(format!("unknown effect {}", repr_str(&e.val)), "effects are io, alloc", Some(&e)));
                }
                effects.push(e.val);
                if !self.at(",", 0) {
                    break;
                }
                self.bump();
            }
        }
        let (mut req, mut ens) = (Vec::new(), Vec::new());
        while self.at("requires", 0) || self.at("ensures", 0) {
            let k = self.next().val;
            let e = self.expr()?;
            if k == "requires" {
                req.push(e);
            } else {
                ens.push(e);
            }
        }
        let body = self.block()?;
        Ok(Function { line: kw.line, col: kw.col, name, params, ret, effects, requires: req, ensures: ens, body })
    }

    fn block(&mut self) -> R<Vec<Stmt>> {
        self.enter(1)?;
        let r = self.block_inner();
        self.leave(1);
        r
    }

    fn block_inner(&mut self) -> R<Vec<Stmt>> {
        self.expect("{")?;
        let mut out = Vec::new();
        while !self.at("}", 0) {
            if self.peek(0).kind == Kind::Eof {
                return Err(self.err("unclosed block", "add '}'", None));
            }
            out.push(self.stmt()?);
        }
        self.expect("}")?;
        Ok(out)
    }

    // ---- 문 ----
    fn stmt(&mut self) -> R<Stmt> {
        let t = self.peek(0).clone();
        let (l, c) = (t.line, t.col);
        if self.at("let", 0) {
            self.bump();
            let mut mutable = false;
            if self.at("mut", 0) {
                self.bump();
                mutable = true;
            }
            let n = self.ident()?.val;
            if !self.at(":", 0) {
                return Err(self.err("let needs a type annotation", format!("write `let {}: i64 = ...;`", n), None));
            }
            self.bump();
            let ty = self.type_()?;
            self.expect("=")?;
            let value = self.expr()?;
            self.expect(";")?;
            return Ok(Stmt::Let(Let { line: l, col: c, name: n, mutable, ty, value }));
        }
        if self.at("if", 0) {
            return Ok(Stmt::If(self.if_()?));
        }
        if self.at("while", 0) {
            self.bump();
            let cond = self.expr()?;
            let mut invs = Vec::new();
            let mut dec: Option<Expr> = None;
            while self.at("invariant", 0) || self.at("decreases", 0) {
                let k = self.next();
                if k.val == "invariant" {
                    invs.push(self.expr()?);
                } else {
                    if dec.is_some() {
                        return Err(self.err("only one decreases clause", "", Some(&k)));
                    }
                    dec = Some(self.expr()?);
                }
            }
            let dec = match dec {
                Some(d) => d,
                None => {
                    return Err(self.err(
                        "while loop needs a `decreases <expr>` clause",
                        "add `decreases n - i` before '{'",
                        None,
                    ))
                }
            };
            let body = self.block()?;
            return Ok(Stmt::While(While { line: l, col: c, cond, invariants: invs, decreases: dec, body }));
        }
        if self.at("return", 0) {
            self.bump();
            if self.at(";", 0) {
                self.bump();
                return Ok(Stmt::Return(Return { line: l, col: c, value: None }));
            }
            let v = self.expr()?;
            self.expect(";")?;
            return Ok(Stmt::Return(Return { line: l, col: c, value: Some(v) }));
        }
        if self.at("assert", 0) {
            self.bump();
            let v = self.expr()?;
            self.expect(";")?;
            return Ok(Stmt::Assert(Assert { line: l, col: c, cond: v }));
        }
        if self.at("match", 0) {
            self.bump();
            let scr = self.expr()?;
            self.expect("{")?;
            let mut arms = Vec::new();
            while !self.at("}", 0) {
                let ct = self.next();
                if ct.kind == Kind::Id && self.at("::", 0) {
                    self.bump();
                    let vt = self.ident()?;
                    let mut binders = Vec::new();
                    if self.at("(", 0) {
                        let lp = self.next();
                        if self.at(")", 0) {
                            return Err(self.err(
                                "a pattern lists one name per field; a variant without fields has no parentheses",
                                format!("write `{}::{} =>`", ct.val, vt.val),
                                Some(&lp),
                            ));
                        }
                        loop {
                            binders.push(self.ident()?.val);
                            if !self.at(",", 0) {
                                break;
                            }
                            self.bump();
                        }
                        self.expect(")")?;
                    }
                    self.expect("=>")?;
                    let body = self.block()?;
                    arms.push(MatchArm { line: ct.line, col: ct.col, enum_name: Some(ct.val.clone()), ctor: vt.val, binders, body });
                } else {
                    let is_ctor = ct.kind != Kind::Int && matches!(ct.val.as_str(), "Some" | "None" | "Ok" | "Err");
                    if !is_ctor {
                        return Err(self.err(
                            "match arm must be Some(x), None, Ok(x), Err(x) or Enum::Variant(...)",
                            "",
                            Some(&ct),
                        ));
                    }
                    let mut binders = Vec::new();
                    if ct.val != "None" {
                        self.expect("(")?;
                        binders = vec![self.ident()?.val];
                        self.expect(")")?;
                    }
                    self.expect("=>")?;
                    let body = self.block()?;
                    arms.push(MatchArm { line: ct.line, col: ct.col, enum_name: None, ctor: ct.val.clone(), binders, body });
                }
                if self.at(",", 0) {
                    self.bump();
                }
            }
            self.expect("}")?;
            return Ok(Stmt::Match(Match { line: l, col: c, scrutinee: scr, arms }));
        }
        if t.kind == Kind::Id && self.at("=", 1) {
            let n = self.next().val;
            self.bump();
            let v = self.expr()?;
            self.expect(";")?;
            return Ok(Stmt::Assign(Assign { line: l, col: c, name: n, value: v }));
        }
        if t.kind == Kind::Id && self.at("[", 1) {
            // 인덱스 대입일 수도 있다
            let save = self.i;
            let n = self.next().val;
            self.bump();
            let idx = self.expr()?;
            self.expect("]")?;
            if self.at("=", 0) {
                self.bump();
                let v = self.expr()?;
                self.expect(";")?;
                return Ok(Stmt::IndexAssign(IndexAssign { line: l, col: c, name: n, index: idx, value: v }));
            }
            self.i = save;
        }
        if t.kind == Kind::Id && self.at(".", 1) {
            // 필드 대입 `p.a.b = e;`, 아니면 식 문
            let save = self.i;
            let n = self.next().val;
            let mut path = Vec::new();
            while self.at(".", 0) {
                self.bump();
                path.push(self.ident()?.val);
            }
            if self.at("=", 0) {
                self.bump();
                let v = self.expr()?;
                self.expect(";")?;
                return Ok(Stmt::FieldAssign(FieldAssign { line: l, col: c, name: n, fields: path, value: v }));
            }
            self.i = save;
        }
        let e = self.expr()?;
        self.expect(";")?;
        Ok(Stmt::ExprStmt(ExprStmt { line: l, col: c, expr: e }))
    }

    fn if_(&mut self) -> R<If> {
        let t = self.expect_tok("if")?;
        let cond = self.expr()?;
        let then = self.block()?;
        let mut els = Vec::new();
        if self.at("else", 0) {
            self.bump();
            if self.at("if", 0) {
                els = vec![Stmt::If(self.if_()?)];
            } else {
                els = self.block()?;
            }
        }
        Ok(If { line: t.line, col: t.col, cond, then, els })
    }

    // ---- 식 (우선순위 상승) ----
    fn bin(t: &Tok, op: &str, l: Expr, r: Expr) -> Expr {
        Expr::Binary(Binary { line: t.line, col: t.col, op: op.to_string(), left: Box::new(l), right: Box::new(r), ty: None })
    }

    fn expr(&mut self) -> R<Expr> {
        self.enter(1)?;
        let r = self.implies();
        self.leave(1);
        r
    }

    fn implies(&mut self) -> R<Expr> {
        let l = self.or_()?;
        if self.at("==>", 0) {
            let t = self.next();
            self.enter(1)?;
            let r = self.implies();
            self.leave(1);
            return Ok(Self::bin(&t, "==>", l, r?));
        }
        Ok(l)
    }

    fn or_(&mut self) -> R<Expr> {
        let mut l = self.and_()?;
        let mut chain = 0; // 왼쪽으로 쌓이는 이항 사슬도 깊이로 센다
        while self.at("||", 0) {
            let t = self.next();
            if let Err(e) = self.enter(1) {
                self.leave(chain + 1);
                return Err(e);
            }
            chain += 1;
            let r = match self.and_() {
                Ok(r) => r,
                Err(e) => {
                    self.leave(chain);
                    return Err(e);
                }
            };
            l = Self::bin(&t, "||", l, r);
        }
        self.leave(chain);
        Ok(l)
    }

    fn and_(&mut self) -> R<Expr> {
        let mut l = self.cmp()?;
        let mut chain = 0; // 왼쪽으로 쌓이는 이항 사슬도 깊이로 센다
        while self.at("&&", 0) {
            let t = self.next();
            if let Err(e) = self.enter(1) {
                self.leave(chain + 1);
                return Err(e);
            }
            chain += 1;
            let r = match self.cmp() {
                Ok(r) => r,
                Err(e) => {
                    self.leave(chain);
                    return Err(e);
                }
            };
            l = Self::bin(&t, "&&", l, r);
        }
        self.leave(chain);
        Ok(l)
    }

    fn cmp(&mut self) -> R<Expr> {
        let l = self.add()?;
        for op in CMP_OPS.iter() {
            if self.at(op, 0) {
                let t = self.next();
                let r = self.add()?;
                for op2 in CMP_OPS.iter() {
                    if self.at(op2, 0) {
                        return Err(self.err("comparisons cannot be chained", "use `a < b && b < c`", None));
                    }
                }
                return Ok(Self::bin(&t, op, l, r));
            }
        }
        Ok(l)
    }

    fn add(&mut self) -> R<Expr> {
        let mut l = self.mul()?;
        let mut chain = 0; // 왼쪽으로 쌓이는 이항 사슬도 깊이로 센다
        while self.at("+", 0) || self.at("-", 0) {
            let t = self.next();
            if let Err(e) = self.enter(1) {
                self.leave(chain + 1);
                return Err(e);
            }
            chain += 1;
            let r = match self.mul() {
                Ok(r) => r,
                Err(e) => {
                    self.leave(chain);
                    return Err(e);
                }
            };
            l = Self::bin(&t, &t.val, l, r);
        }
        self.leave(chain);
        Ok(l)
    }

    fn mul(&mut self) -> R<Expr> {
        let mut l = self.unary()?;
        let mut chain = 0; // 왼쪽으로 쌓이는 이항 사슬도 깊이로 센다
        while self.at("*", 0) || self.at("/", 0) || self.at("%", 0) {
            let t = self.next();
            if let Err(e) = self.enter(1) {
                self.leave(chain + 1);
                return Err(e);
            }
            chain += 1;
            let r = match self.unary() {
                Ok(r) => r,
                Err(e) => {
                    self.leave(chain);
                    return Err(e);
                }
            };
            l = Self::bin(&t, &t.val, l, r);
        }
        self.leave(chain);
        Ok(l)
    }

    fn unary(&mut self) -> R<Expr> {
        if self.at("-", 0) || self.at("!", 0) {
            let t = self.next();
            self.enter(1)?;
            let o = self.unary();
            self.leave(1);
            let o = o?;
            if t.val == "-" {
                if let Expr::IntLit(il) = &o {
                    return Ok(Expr::IntLit(IntLit { line: t.line, col: t.col, value: negate(&il.value), ty: None }));
                }
            }
            return Ok(Expr::Unary(Unary { line: t.line, col: t.col, op: t.val, operand: Box::new(o), ty: None }));
        }
        self.postfix()
    }

    fn postfix(&mut self) -> R<Expr> {
        let mut e = self.primary()?;
        let mut chain = 0; // a[i][j].f 처럼 왼쪽으로 쌓이는 접미 사슬도 깊이로 센다
        loop {
            if self.at("[", 0) {
                let t = self.next();
                let i = self.expr()?;
                self.expect("]")?;
                e = Expr::Index(Index { line: t.line, col: t.col, array: Box::new(e), index: Box::new(i), ty: None });
            } else if self.at(".", 0) {
                self.bump();
                let f = self.ident()?;
                e = Expr::FieldAccess(FieldAccess { line: e.line(), col: e.col(), base: Box::new(e), field: f.val, ty: None });
            } else {
                break;
            }
            self.enter(1)?;
            chain += 1;
        }
        self.leave(chain);
        Ok(e)
    }

    /// `Enum::Variant` -> (enum 토큰, variant 토큰)
    fn enum_ref(&mut self) -> R<(Tok, Tok)> {
        let en = self.ident()?;
        self.expect("::")?;
        let vt = self.ident()?;
        Ok((en, vt))
    }

    fn primary(&mut self) -> R<Expr> {
        let t = self.peek(0).clone();
        let (line, col) = (t.line, t.col);
        if t.kind == Kind::Int {
            self.bump();
            return Ok(Expr::IntLit(IntLit { line, col, value: t.val, ty: None }));
        }
        if self.at("true", 0) || self.at("false", 0) {
            self.bump();
            return Ok(Expr::BoolLit(BoolLit { line, col, value: t.val == "true", ty: None }));
        }
        if self.at("(", 0) {
            self.bump();
            let e = self.expr()?;
            self.expect(")")?;
            return Ok(e);
        }
        if self.at("None", 0) {
            self.bump();
            return Ok(Expr::Ctor(Ctor { line, col, name: "None".to_string(), arg: None, ty: None }));
        }
        if self.at("Some", 0) || self.at("Ok", 0) || self.at("Err", 0) {
            self.bump();
            self.expect("(")?;
            let a = self.expr()?;
            self.expect(")")?;
            return Ok(Expr::Ctor(Ctor { line, col, name: t.val, arg: Some(Box::new(a)), ty: None }));
        }
        if self.at("result", 0) {
            self.bump();
            return Ok(Expr::Var(Var { line, col, name: "result".to_string(), ty: None }));
        }
        if self.at("forall", 0) || self.at("exists", 0) {
            self.bump();
            let v = self.ident()?.val;
            self.expect("in")?;
            let lo = self.add()?;
            self.expect("..")?;
            let hi = self.add()?;
            self.expect(":")?;
            let body = self.expr()?;
            return Ok(Self::quant(&t, v, lo, hi, body));
        }
        if t.kind == Kind::Id
            && matches!(t.val.as_str(), "sum" | "count" | "max" | "min")
            && self.at("(", 1)
            && self.peek(2).kind == Kind::Id
            && self.at("in", 3)
        {
            self.bump();
            self.bump();
            let v = self.ident()?.val;
            self.expect("in")?;
            let lo = self.add()?;
            self.expect("..")?;
            let hi = self.add()?;
            self.expect(":")?;
            let body = self.expr()?;
            self.expect(")")?;
            return Ok(Self::quant(&t, v, lo, hi, body));
        }
        if self.at("is_variant", 0) {
            self.bump();
            self.expect("(")?;
            let v = self.expr()?;
            self.expect(",")?;
            let (en, vt) = self.enum_ref()?;
            self.expect(")")?;
            return Ok(Expr::IsVariant(IsVariant { line, col, value: Box::new(v), enum_name: en.val, variant: vt.val, ty: None }));
        }
        if self.at("variant_field", 0) {
            self.bump();
            self.expect("(")?;
            let v = self.expr()?;
            self.expect(",")?;
            let (en, vt) = self.enum_ref()?;
            self.expect(",")?;
            let f = self.ident()?;
            self.expect(")")?;
            return Ok(Expr::VariantField(VariantField {
                line, col, value: Box::new(v), enum_name: en.val, variant: vt.val, field: f.val, ty: None,
            }));
        }
        if t.kind == Kind::Id {
            self.bump();
            if self.at("::", 0) {
                self.bump();
                let vt = self.ident()?;
                let mut args = Vec::new();
                if self.at("(", 0) {
                    let lp = self.next();
                    if self.at(")", 0) {
                        return Err(self.err(
                            "empty parentheses after a variant",
                            format!(
                                "write `{}::{}` for a variant without fields, or pass its fields as arguments",
                                t.val, vt.val
                            ),
                            Some(&lp),
                        ));
                    }
                    while !self.at(")", 0) {
                        args.push(self.expr()?);
                        if !self.at(")", 0) {
                            self.expect(",")?;
                        }
                    }
                    self.expect(")")?;
                }
                return Ok(Expr::EnumCtor(EnumCtor { line, col, enum_name: t.val, variant: vt.val, args, ty: None }));
            }
            if is_upper(&t.val) && self.at("{", 0) {
                self.bump();
                let mut inits = Vec::new();
                while !self.at("}", 0) {
                    let fname = self.ident()?;
                    self.expect(":")?;
                    let value = self.expr()?;
                    inits.push(FieldInit { line: fname.line, col: fname.col, name: fname.val, value });
                    if !self.at("}", 0) {
                        self.expect(",")?;
                    }
                }
                self.expect("}")?;
                return Ok(Expr::StructLit(StructLit { line, col, name: t.val, fields: inits, ty: None }));
            }
            if self.at("(", 0) {
                self.bump();
                let mut args = Vec::new();
                while !self.at(")", 0) {
                    args.push(self.expr()?);
                    if !self.at(")", 0) {
                        self.expect(",")?;
                    }
                }
                self.expect(")")?;
                return Ok(Expr::Call(Call { line, col, name: t.val, args, ty: None }));
            }
            return Ok(Expr::Var(Var { line, col, name: t.val, ty: None }));
        }
        Err(self.err(format!("expected an expression, found {}", t.repr()), "", None))
    }

    fn quant(t: &Tok, var: String, lo: Expr, hi: Expr, body: Expr) -> Expr {
        Expr::Quant(Quant {
            line: t.line, col: t.col, kind: t.val.clone(), var,
            lo: Box::new(lo), hi: Box::new(hi), body: Box::new(body), ty: None,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ret_expr(src: &str) -> Expr {
        let p = parse_source(&format!("fn f() -> i64 {{ return {}; }}", src)).unwrap();
        match &p.functions[0].body[0] {
            Stmt::Return(Return { value: Some(e), .. }) => e.clone(),
            _ => panic!("return 아님"),
        }
    }

    fn int_of(e: &Expr) -> (String, i64) {
        match e {
            Expr::IntLit(i) => (i.value.clone(), i.col),
            other => panic!("IntLit 아님: {:?}", other),
        }
    }

    #[test]
    fn negative_folding() {
        assert_eq!(int_of(&ret_expr("--5")).0, "5");
        assert_eq!(int_of(&ret_expr("-(5)")).0, "-5");
        assert_eq!(int_of(&ret_expr("-0")).0, "0");
        assert_eq!(int_of(&ret_expr("-9223372036854775808")), ("-9223372036854775808".to_string(), 24));
        assert!(matches!(ret_expr("!5"), Expr::Unary(_)));
        assert_eq!(int_of(&ret_expr("340282366920938463463374607431768211456")).0, "340282366920938463463374607431768211456");
    }

    #[test]
    fn unicode_column_and_errors() {
        let e = parse_source("fn // éé").unwrap_err();
        assert_eq!((e.line, e.col), (1, 9));
        assert_eq!(e.message, "expected identifier, found None");
        let e = parse_source("fn f() -> i64 {\r\n  return 1\r\n}").unwrap_err();
        assert_eq!((e.line, e.col), (3, 1));
        assert_eq!(e.message, "expected ';' but found '}'");
        assert_eq!(e.fix, "insert ';'");
    }

    #[test]
    fn crlf_and_cr() {
        let e = parse_source("fn f() -> i64 {\r  @").unwrap_err();
        assert_eq!((e.code.as_str(), e.line, e.col), ("bad_char", 2, 3));
    }
}
