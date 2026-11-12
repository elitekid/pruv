//! Recursive-descent parser (a line-by-line port of Parser in vparser.py).

use crate::ast::*;
use crate::diagnostic::PruvError;
use crate::gtype::{fn_owner, decl_owner, mk_array, mk_option, mk_param, mk_result, GType};
use crate::lexer::{lex_tagged, Kind, Tok};
use crate::pyrepr::repr_str;
use std::collections::HashMap;

type R<T> = Result<T, PruvError>;

const CMP_OPS: [&str; 6] = ["==", "!=", "<=", ">=", "<", ">"];

/// Public entry: first applies the universal newline handling of Python open().read().
pub fn parse_source(src: &str) -> R<Program> {
    Ok(parse_file(src, 0)?.prog)
}

/// One parsed source file (G4 A0): the program plus the parse-level module data (Python `Program.mods` / `has_pub` /
/// `items`, and the `pub` flag of every function / type declaration).
pub struct ParsedFile {
    pub prog: Program,
    pub mods: Vec<ModDecl>,
    pub has_pub: bool,
    pub items: Vec<Item>,
    pub fn_pub: Vec<bool>,
    pub ty_pub: Vec<bool>,
}

fn normalized_chars(src: &str) -> Vec<char> {
    let norm = src.replace("\r\n", "\n").replace('\r', "\n");
    norm.chars().collect()
}

/// Parses one file whose line numbers carry the module file number `tag` (0 = a plain, legacy-style file).
pub fn parse_file(src: &str, tag: usize) -> R<ParsedFile> {
    let chars = normalized_chars(src);
    let mut p = Parser {
        t: lex_tagged(&chars, tag)?,
        i: 0,
        depth: 0,
        scope: HashMap::new(),
        mods: Vec::new(),
        has_pub: false,
        items: Vec::new(),
        fn_pub: Vec::new(),
        ty_pub: Vec::new(),
    };
    let prog = p.program()?;
    Ok(ParsedFile { prog, mods: p.mods, has_pub: p.has_pub, items: p.items, fn_pub: p.fn_pub, ty_pub: p.ty_pub })
}

/// vparser `_sniff_explicit`: a root that failed to parse: does it use module syntax (a `mod` / `pub` token)?
/// One lexing pass: the tokens read before a lex error count, so a `pub` ahead of a bad character still counts.
pub fn sniff_explicit(src: &str) -> bool {
    let chars = normalized_chars(src);
    let mut toks: Vec<Tok> = Vec::new();
    let _ = crate::lexer::lex_into(&chars, 0, &mut toks);
    toks.iter().any(|t| t.kind == Kind::Kw && (t.val == "mod" || t.val == "pub"))
}

/// `[a-z][A-Za-z0-9_]*` (module names)
fn mod_name_ok(s: &str) -> bool {
    let mut it = s.chars();
    match it.next() {
        Some(c) if c.is_ascii_lowercase() => it.all(|c| c.is_ascii_alphanumeric() || c == '_'),
        _ => false,
    }
}

fn lower_first(s: &str) -> String {
    let mut it = s.chars();
    match it.next() {
        Some(c) => format!("{}{}", c.to_ascii_lowercase(), it.as_str()),
        None => String::new(),
    }
}

/// Decodes the raw text of a string token (quotes included, already validated by the lexer) into a UTF-8 byte sequence.
fn decode_str_lit(raw: &str) -> Vec<u8> {
    let chars: Vec<char> = raw.chars().collect();
    let mut out: Vec<u8> = Vec::new();
    let mut i = 1usize;
    let end = chars.len().saturating_sub(1);
    let mut buf = [0u8; 4];
    while i < end {
        let c = chars[i];
        if c == '\\' && i + 1 < end {
            i += 1;
            let b = match chars[i] {
                '"' => b'"',
                '\\' => b'\\',
                'n' => b'\n',
                'r' => b'\r',
                't' => b'\t',
                _ => 0u8,
            };
            out.push(b);
        } else {
            out.extend_from_slice(c.encode_utf8(&mut buf).as_bytes());
        }
        i += 1;
    }
    out
}

/// Sign negation of a decimal string for negative folding ("0" stays as is).
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
    /// Depth of the AST path being built (recursion plus binary/postfix chains that pile up to the left). Beyond MAX_DEPTH it stops with an internal error,
    /// like Python's RecursionError: an AST that deep can overflow even a 1GB stack in the recursion of the parser, checker, verifier and generator.
    depth: usize,
    /// G3: type-parameter name -> bound parameter type, inside a generic declaration (empty elsewhere).
    scope: HashMap<String, GType>,
    // ---- G4 A0 parse-level module data (see ParsedFile) ----
    mods: Vec<ModDecl>,
    has_pub: bool,
    items: Vec<Item>,
    fn_pub: Vec<bool>,
    ty_pub: Vec<bool>,
}

/// AST depth limit. Python stops with RecursionError at about 1000 levels (outside the cross-check range), so this is set much larger than that,
/// but small enough that the later stages' recursion fits in the 1GB stack (RESULTS §20).
pub const MAX_DEPTH: usize = 50_000;

impl Parser {
    // ---- helpers ----
    fn idx(&self, k: usize) -> usize {
        (self.i + k).min(self.t.len() - 1)
    }

    /// Adds one level of depth (internal error if exceeded). Undone by the paired leave.
    fn enter(&mut self, n: usize) -> R<()> {
        self.depth += n;
        if self.depth > MAX_DEPTH {
            return Err(PruvError::new("internal", 0, 0, "internal_error", "maximum recursion depth exceeded", ""));
        }
        Ok(())
    }

    // On an error exit the depth is not restored (the whole parse stops). So the subtraction is saturating.
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

    // Clone the received token only when needed (audit: removed token cloning on a hot path).
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

    // ---- program ----
    fn program(&mut self) -> R<Program> {
        let mut p = Program::default();
        while self.peek(0).kind != Kind::Eof {
            let mut pub_tok: Option<Tok> = None;
            if self.at("pub", 0) {
                // G4: visibility of the next item
                let pt = self.next();
                if self.at("pub", 0) {
                    let t = self.peek(0).clone();
                    return Err(self.visibility_syntax(&t, "`pub` is written once", "remove the second `pub`"));
                }
                if self.at("mod", 0) {
                    return Err(self.visibility_syntax(
                        &pt,
                        "`pub mod` is not supported: module namespaces have no visibility",
                        "write `mod name;`",
                    ));
                }
                pub_tok = Some(pt);
            }
            let is_pub = pub_tok.is_some();
            if self.at("mod", 0) {
                let m = self.mod_decl()?;
                self.mods.push(m);
            } else if self.at("struct", 0) {
                let d = TypeDecl::Struct(self.struct_decl()?);
                self.ty_pub.push(is_pub);
                p.types.push(d);
                self.items.push(Item::Ty(p.types.len() - 1));
            } else if self.at("enum", 0) {
                let d = TypeDecl::Enum(self.enum_decl()?);
                self.ty_pub.push(is_pub);
                p.types.push(d);
                self.items.push(Item::Ty(p.types.len() - 1));
            } else if self.peek(0).kind == Kind::Id && self.peek(0).val == "trusted" {
                // G6 A0: `trusted rust fn name(..) -> T ensures .. = "::path";`
                let t = self.peek(0).clone();
                if let Some(pt) = &pub_tok {
                    return Err(self.visibility_syntax(
                        pt,
                        "a trusted rust fn cannot be `pub`",
                        "keep it private and expose it through a public Pruv function with explicit contracts",
                    ));
                }
                if !(self.peek(1).kind == Kind::Id && self.peek(1).val == "rust" && self.at("fn", 2)) {
                    return Err(self.foreign_syntax(
                        &t,
                        "expected `rust fn` after `trusted`",
                        "write `trusted rust fn name(..) -> T ensures .. = \"::path\";`",
                    ));
                }
                self.bump();
                self.bump();
                let f = self.function(Some(t))?;
                self.fn_pub.push(false);
                p.functions.push(f);
                self.items.push(Item::Fn(p.functions.len() - 1));
            } else if self.peek(0).kind == Kind::Id && self.peek(0).val == "rust" && self.at("fn", 1) {
                let t = self.peek(0).clone();
                return Err(self.foreign_syntax(&t, "missing `trusted`", "write `trusted rust fn ...`"));
            } else {
                let f = self.function(None)?;
                self.fn_pub.push(is_pub);
                p.functions.push(f);
                self.items.push(Item::Fn(p.functions.len() - 1));
            }
            if is_pub {
                self.has_pub = true;
            }
        }
        Ok(p)
    }

    fn foreign_syntax(&self, tok: &Tok, msg: &str, fix: &str) -> PruvError {
        PruvError::new("parse", tok.line, tok.col, "foreign_syntax", msg, fix)
    }

    // ---- G4 A0: module declarations and paths ----
    fn visibility_syntax(&self, tok: &Tok, msg: &str, fix: &str) -> PruvError {
        PruvError::new("parse", tok.line, tok.col, "visibility_syntax", msg, fix)
    }

    fn module_syntax(&self, tok: &Tok, msg: &str, fix: &str) -> PruvError {
        PruvError::new("parse", tok.line, tok.col, "module_syntax", msg, fix)
    }

    fn path_syntax(&self, tok: &Tok, msg: &str) -> PruvError {
        PruvError::new("parse", tok.line, tok.col, "path_syntax", msg, "write an absolute path such as crate::math::clamp")
    }

    /// `mod name;` at top level -> ModDecl
    fn mod_decl(&mut self) -> R<ModDecl> {
        let kw = self.next();
        let t = self.peek(0).clone();
        if t.kind == Kind::Str {
            return Err(self.module_syntax(&t, "a module path cannot be a string", "write `mod name;`; the file is <name>.pruv"));
        }
        if self.at("{", 0) {
            return Err(self.module_syntax(&t, "inline modules are not supported", "move the items into <name>.pruv and write `mod name;`"));
        }
        if t.kind != Kind::Id {
            return Err(self.module_syntax(&t, "expected a module name after `mod`", "write `mod name;`"));
        }
        self.bump();
        if !mod_name_ok(&t.val) {
            return Err(self.module_syntax(
                &t,
                &format!("module name {} must match [a-z][A-Za-z0-9_]*", t.val),
                &format!("rename it, e.g. {}", lower_first(&t.val)),
            ));
        }
        if self.at("{", 0) {
            let p = self.peek(0).clone();
            return Err(self.module_syntax(
                &p,
                "inline modules are not supported",
                &format!("move the items into {}.pruv and write `mod {};`", t.val, t.val),
            ));
        }
        if !self.at(";", 0) {
            let p = self.peek(0).clone();
            return Err(self.module_syntax(&p, &format!("expected ';' after `mod {}`", t.val), &format!("write `mod {};`", t.val)));
        }
        self.bump();
        Ok(ModDecl { line: kw.line, col: kw.col, name: t.val })
    }

    /// At `crate`: `crate::a::b` -> (crate token, [segment names]); stops before a `::<` when allow_targs.
    fn crate_path(&mut self, allow_targs: bool) -> R<(Tok, Vec<String>)> {
        let t = self.next();
        let mut segs: Vec<String> = Vec::new();
        while self.at("::", 0) {
            if self.at("<", 1) {
                if allow_targs && !segs.is_empty() {
                    break;
                }
                let p1 = self.peek(1).clone();
                return Err(PruvError::new(
                    "parse",
                    p1.line,
                    p1.col,
                    "path_syntax",
                    "type arguments are not allowed here",
                    "attach type arguments to the item: crate::m::f::<T>(x)",
                ));
            }
            self.bump();
            let n = self.peek(0).clone();
            if n.kind != Kind::Id {
                let found = if n.kind == Kind::Eof { "end of file".to_string() } else { n.repr() };
                return Err(self.path_syntax(&n, &format!("expected a name after `::` in a path, found {}", found)));
            }
            segs.push(self.next().val);
        }
        if segs.is_empty() {
            let p = self.peek(0).clone();
            return Err(self.path_syntax(&p, "a path needs at least one name after `crate::`"));
        }
        Ok((t, segs))
    }

    /// A `crate::..` path in a type position -> a pseudo identifier token whose value is the full path.
    fn type_path(&mut self) -> R<Tok> {
        let (t, segs) = self.crate_path(false)?;
        Ok(Tok { kind: Kind::Id, val: format!("crate::{}", segs.join("::")), line: t.line, col: t.col, end: 0 })
    }

    fn inout_syntax(&self, tok: &Tok, msg: &str, fix: &str) -> PruvError {
        PruvError::new("parse", tok.line, tok.col, "inout_syntax", msg, fix)
    }

    /// G5: at an `inout` that marks a call argument: the token after it starts an operand (a name, number, string, or a
    /// keyword/path that can start an expression). `inout` followed by an operator, `(`, `[`, `.`, `,` or `)` stays an
    /// ordinary identifier.
    fn is_inout_marker(&self) -> bool {
        let t = self.peek(0);
        if !(t.kind == Kind::Id && t.val == "inout") {
            return false;
        }
        let n = self.peek(1);
        if n.kind == Kind::Id || n.kind == Kind::Int || n.kind == Kind::Str {
            return true;
        }
        n.kind == Kind::Kw && matches!(n.val.as_str(), "true" | "false" | "None" | "Some" | "Ok" | "Err" | "crate")
    }

    /// G5: one call argument: an expression, or the marker `inout <operand>` (one postfix expression, kept as written so
    /// the checker can reject fields, elements and calls as places).
    fn arg_expr(&mut self) -> R<Expr> {
        if self.is_inout_marker() {
            let t = self.next();
            let e = self.postfix()?;
            if !(self.at(",", 0) || self.at(")", 0)) {
                return Err(self.inout_syntax(
                    &t,
                    "malformed inout argument: the marker takes a single operand",
                    "write `inout name`; compute other values into a local first",
                ));
            }
            return Ok(Expr::InoutArg(InoutArg { line: t.line, col: t.col, expr: Box::new(e), ty: None }));
        }
        self.expr()
    }

    /// At `(`: the argument list of a call or constructor.
    fn call_args(&mut self) -> R<Vec<Expr>> {
        self.bump();
        let mut args = Vec::new();
        while !self.at(")", 0) {
            args.push(self.arg_expr()?);
            if !self.at(")", 0) {
                self.expect(",")?;
            }
        }
        self.expect(")")?;
        Ok(args)
    }

    /// At `{`: `name: expr, ...` up to and including `}`.
    fn struct_inits(&mut self) -> R<Vec<FieldInit>> {
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
        Ok(inits)
    }

    /// G4: an absolute path in an expression.
    ///   crate::m::f(args) / crate::m::Enum::Variant(args) -> Call(name = the whole path) (the resolver tells a function from a variant)
    ///   crate::m::Enum::Variant                           -> EnumCtor without arguments
    ///   crate::m::S { .. }                                -> StructLit
    ///   crate::m::f::<T>(args), crate::m::S::<A> { .. }, crate::m::E::<A>::V(args): type arguments attach to the item
    fn crate_expr(&mut self) -> R<Expr> {
        let (t, segs) = self.crate_path(true)?;
        let (line, col) = (t.line, t.col);
        let path = format!("crate::{}", segs.join("::"));
        let last_upper = segs.last().map_or(false, |s| is_upper(s));
        if self.at("::", 0) && self.at("<", 1) {
            let targs = self.expr_targs()?;
            if !(self.at("::", 0) || self.at("(", 0) || (self.at("{", 0) && last_upper)) {
                let p = self.peek(0).clone();
                return Err(self.generic_syntax(
                    &p,
                    "a type application must be followed by `(`, `{` or `::Variant`",
                    "write crate::m::f::<T>(x), crate::m::Pair::<A, B> { .. } or crate::m::Choice::<A, B>::Left(x)",
                ));
            }
            if self.at("::", 0) {
                self.bump();
                let vt = self.ident()?;
                let mut args = Vec::new();
                if self.at("(", 0) {
                    let lp = self.peek(0).clone();
                    args = self.call_args()?;
                    if args.is_empty() {
                        return Err(self.err(
                            "empty parentheses after a variant",
                            format!("write `{}::{}` for a variant without fields, or pass its fields as arguments", path, vt.val),
                            Some(&lp),
                        ));
                    }
                }
                return Ok(Expr::EnumCtor(EnumCtor { line, col, enum_name: path, variant: vt.val, args, ty: None, targs: Some(targs), inst: None }));
            }
            if self.at("{", 0) {
                let fields = self.struct_inits()?;
                return Ok(Expr::StructLit(StructLit { line, col, name: path, fields, ty: None, targs: Some(targs), inst: None }));
            }
            let args = self.call_args()?;
            return Ok(Expr::Call(Call { line, col, name: path, args, ty: None, targs: Some(targs), inst: None, old: None }));
        }
        if self.at("(", 0) {
            let args = self.call_args()?;
            return Ok(Expr::Call(Call { line, col, name: path, args, ty: None, targs: None, inst: None, old: None }));
        }
        if self.at("{", 0) && last_upper {
            let fields = self.struct_inits()?;
            return Ok(Expr::StructLit(StructLit { line, col, name: path, fields, ty: None, targs: None, inst: None }));
        }
        if segs.len() < 2 {
            return Err(PruvError::new(
                "parse",
                t.line,
                t.col,
                "path_syntax",
                "a path expression must be a call, a struct literal or an enum variant",
                "write crate::module::f(x), crate::module::S { .. } or crate::module::Enum::Variant",
            ));
        }
        let enum_name = format!("crate::{}", segs[..segs.len() - 1].join("::"));
        Ok(Expr::EnumCtor(EnumCtor {
            line,
            col,
            enum_name,
            variant: segs[segs.len() - 1].clone(),
            args: Vec::new(),
            ty: None,
            targs: None,
            inst: None,
        }))
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

    /// `name: Type, ...` up to close (close is not consumed); a trailing comma is allowed
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

    // ---- G3 A1: type parameters and type applications ----
    fn generic_syntax(&self, tok: &Tok, msg: &str, fix: &str) -> PruvError {
        PruvError::new("parse", tok.line, tok.col, "generic_syntax", msg, fix)
    }

    /// `<T, U: Element>` (the `<` is the current token). Also installs the parse scope: inside the declaration a bare
    /// parameter name is a bound parameter type (owner identity + index).
    fn type_params(&mut self, owner: &str) -> R<Vec<TParam>> {
        self.expect("<")?;
        if self.at(">", 0) {
            let t = self.peek(0).clone();
            return Err(self.generic_syntax(
                &t,
                "a type-parameter list cannot be empty",
                "remove `<>`, or declare at least one parameter, e.g. <T>",
            ));
        }
        let mut out: Vec<TParam> = Vec::new();
        loop {
            let n = self.ident()?;
            let mut bound: Option<String> = None;
            if self.at(":", 0) {
                self.bump();
                let b = self.peek(0).clone();
                if b.kind != Kind::Id {
                    return Err(self.generic_syntax(&b, "expected a bound name after ':'", "the only bound is Element: <T: Element>"));
                }
                self.bump();
                bound = Some(b.val.clone());
                if self.at("+", 0) {
                    let t = self.peek(0).clone();
                    return Err(self.generic_syntax(
                        &t,
                        "bound lists are not supported",
                        "a parameter has at most one bound: <T: Element>",
                    ));
                }
            }
            out.push(TParam { line: n.line, col: n.col, name: n.val, bound });
            if !self.at(",", 0) {
                break;
            }
            self.bump();
            if self.at(">", 0) {
                let t = self.peek(0).clone();
                return Err(self.generic_syntax(&t, "a type-parameter list has no trailing comma", "remove the last ','"));
            }
        }
        self.expect(">")?;
        self.scope = HashMap::new();
        for (i, tp) in out.iter().enumerate() {
            self.scope.entry(tp.name.clone()).or_insert_with(|| mk_param(owner, i, &tp.name));
        }
        Ok(out)
    }

    /// Type arguments after an already consumed `<`, through the closing `>`. expr: expression position,
    /// where a malformed list is a generic_syntax error.
    fn type_arg_list(&mut self, expr: bool) -> R<Vec<GType>> {
        let mut out: Vec<GType> = Vec::new();
        loop {
            if self.at(">", 0) || self.at(",", 0) {
                let t = self.peek(0).clone();
                return Err(self.generic_syntax(
                    &t,
                    "missing type argument",
                    "write a type between the angle brackets, e.g. Pair<i64, bool>",
                ));
            }
            out.push(self.type_g(false)?.0);
            if !self.at(",", 0) {
                break;
            }
            self.bump();
        }
        if !self.at(">", 0) {
            if expr {
                let t = self.peek(0).clone();
                return Err(self.generic_syntax(
                    &t,
                    "malformed type application: expected '>' after the type arguments",
                    "write f::<T>(x), Pair::<A, B> { .. } or Choice::<A, B>::Left(x)",
                ));
            }
            self.expect(">")?;
        }
        self.bump();
        Ok(out)
    }

    /// At `::` `<` in an expression: consumes `::<T, ...>`.
    fn expr_targs(&mut self) -> R<Vec<GType>> {
        self.expect("::")?;
        self.expect("<")?;
        self.type_arg_list(true)
    }

    /// n: an already consumed identifier naming a type parameter, Option/Result or a user type (no refinement;
    /// type arguments are parsed here).
    fn named_type(&mut self, n: &Tok) -> R<GType> {
        if n.val == "Option" || n.val == "Result" {
            self.expect("<")?;
            let a = self.peek(0).clone();
            if a.kind == Kind::Id && (a.val == "u8" || a.val == "i32") {
                return Err(self.unsupported(&format!("{}<{}>", n.val, a.val), &a));
            }
            let mut args = self.type_arg_list(false)?;
            if args.len() == 1 {
                let x = args.swap_remove(0);
                return Ok(if n.val == "Option" { mk_option(x) } else { mk_result(x) });
            }
            // wrong arity: the checker reports it
            return Ok(GType::new(if n.val == "Option" { "option" } else { "result" }, args));
        }
        if self.at("<", 0) {
            self.bump();
            // also a parameter applied to arguments (`T<X>`): kept unresolved, the checker reports it
            let args = self.type_arg_list(false)?;
            return Ok(GType::new(&n.val, args));
        }
        if let Some(t) = self.scope.get(&n.val) {
            return Ok(t.clone());
        }
        Ok(GType::new(&n.val, Vec::new()))
    }

    fn struct_decl(&mut self) -> R<StructDecl> {
        let kw = self.expect_tok("struct")?;
        let n = self.ident()?;
        let tparams = if self.at("<", 0) { self.type_params(&decl_owner(&n.val))? } else { Vec::new() };
        self.expect("{")?;
        let fields = self.field_list("}")?;
        self.expect("}")?;
        self.scope = HashMap::new();
        Ok(StructDecl { line: kw.line, col: kw.col, name: n.val, fields, tparams })
    }

    fn enum_decl(&mut self) -> R<EnumDecl> {
        let kw = self.expect_tok("enum")?;
        let n = self.ident()?;
        let tparams = if self.at("<", 0) { self.type_params(&decl_owner(&n.val))? } else { Vec::new() };
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
        self.scope = HashMap::new();
        Ok(EnumDecl { line: kw.line, col: kw.col, name: n.val, variants, tparams })
    }

    /// A type in a position where refinement annotations are not allowed (fields, etc.)
    fn type_(&mut self) -> R<Type> {
        Ok(self.type_r(false)?.0)
    }

    // ---- STAGE1 A: refinement annotations ----
    fn ref_position(&self, tok: &Tok) -> PruvError {
        PruvError::new(
            "parse",
            tok.line,
            tok.col,
            "refinement_position",
            "a refinement annotation is only allowed on a parameter, a return type or a let/let mut type",
            "move the condition into requires/ensures/invariant, or annotate the parameter/local instead",
        )
    }

    /// If fix is empty, the default hint text.
    fn ref_syntax(&self, tok: &Tok, msg: String, fix: &str) -> PruvError {
        let fix = if fix.is_empty() {
            "write bounds as signed decimal integer literals, e.g. -1_000_000_000..=1_000_000_000"
        } else {
            fix
        };
        PruvError::new("parse", tok.line, tok.col, "refinement_syntax", msg, fix)
    }

    /// Signed decimal integer literal (arbitrary-length normalized string; range checks are in refine.rs)
    fn ref_int(&mut self, what: &str) -> R<String> {
        let t = self.peek(0).clone();
        let mut neg = false;
        if self.at("-", 0) || self.at("+", 0) {
            neg = t.val == "-";
            self.bump();
        }
        let n = self.peek(0).clone();
        if n.kind != Kind::Int {
            let found = if n.kind == Kind::Eof { "end of file".to_string() } else { n.repr() };
            return Err(self.ref_syntax(&n, format!("refinement {} must be a decimal integer literal, found {}", what, found), ""));
        }
        self.bump();
        let nx = self.peek(0).clone();
        if nx.kind == Kind::Id && nx.line == n.line && nx.col == n.end {
            let mut cs = nx.val.chars(); // the exponent wording only for exponent notation (e/E plus digits)
            let first = cs.next();
            let fix = if matches!(first, Some('e') | Some('E')) && cs.all(|c| c.is_ascii_digit()) {
                "exponent notation is not supported: write the full decimal number, e.g. 1_000_000_000 for 1e9"
            } else {
                "only plain decimal integer literals are allowed: write the full decimal number, e.g. 16 instead of 0x10"
            };
            return Err(self.ref_syntax(
                &nx,
                format!("refinement {} must be a decimal integer literal; `{}{}` is not one", what, n.val, nx.val),
                fix,
            ));
        }
        for op in ["*", "+", "-", "/", "%"] {
            if self.at(op, 0) {
                return Err(self.ref_syntax(
                    &nx,
                    format!("refinement {} must be a single integer literal, found an expression with `{}`", what, op),
                    "bounds are integer literals only: compute the value and write it out, e.g. 0..=6 instead of 0..=2*3",
                ));
            }
        }
        Ok(if neg { negate(&n.val) } else { n.val })
    }

    /// `L..=U` after `|`
    fn ref_range(&mut self) -> R<(String, String)> {
        let lo = self.ref_int("lower bound")?;
        if !self.at("..", 0) {
            let t = self.peek(0).clone();
            return Err(self.ref_syntax(
                &t,
                "expected '..=' after the lower bound of a refinement".to_string(),
                "a value range is written closed: `L..=U` (both ends included)",
            ));
        }
        let dd = self.next();
        let eq = self.peek(0).clone();
        if !(self.at("=", 0) && eq.line == dd.line && eq.col == dd.col + 2) {
            return Err(self.ref_syntax(
                &eq,
                "expected '..=' (closed range) in a refinement, found '..'".to_string(),
                "a value range is written `L..=U`; `L..U` is only used by forall/exists/sum/count/max/min and excludes U",
            ));
        }
        self.bump();
        let hi = self.ref_int("upper bound")?;
        Ok((lo, hi))
    }

    /// `; <= N` (the `;` has not been consumed yet)
    fn ref_len(&mut self) -> R<String> {
        self.expect(";")?;
        self.expect("<=")?;
        self.ref_int("length bound")
    }

    /// -> (Type, Refinement or None). allow: whether a refinement annotation is legal in this position.
    fn type_r(&mut self, allow: bool) -> R<(Type, Option<Refinement>)> {
        let (g, r) = self.type_g(allow)?;
        Ok((g.to_key(), r))
    }

    /// The structured form of `type_r`.
    fn type_g(&mut self, allow: bool) -> R<(GType, Option<Refinement>)> {
        let t = self.peek(0).clone();
        if self.at("(", 0) {
            self.bump();
            self.expect(")")?;
            return Ok((GType::unit(), None));
        }
        if self.at("[", 0) {
            self.bump();
            let e = if self.at("crate", 0) { self.type_path()? } else { self.ident()? }; // G4: a qualified element type
            let elem: GType = if e.val == "i64" {
                GType::i64()
            } else if e.val == "u8" {
                GType::u8()
            } else if e.val == "bool" {
                GType::bool()
            } else if is_upper(&e.val) || e.val.starts_with("crate::") {
                // G3: a type parameter (the checker: needs Element); other types: the checker rejects them
                self.named_type(&e)?
            } else {
                // G2 A5: [bool] joins the element names
                return Err(self.err("only [i64], [u8] and [bool] arrays exist", "use [i64], [u8] or [bool]", Some(&e)));
            };
            // [i64]/[u8]/[bool] -> the legacy constants (G2 A5)
            let arr_ty = mk_array(elem);
            let (mut lo, mut hi, mut maxlen): (Option<String>, Option<String>, Option<String>) = (None, None, None);
            if self.at("|", 0) {
                if !allow {
                    return Err(self.ref_position(&self.peek(0).clone()));
                }
                self.bump();
                let (l, h) = self.ref_range()?;
                lo = Some(l);
                hi = Some(h);
            }
            if self.at(";", 0) && self.at("<=", 1) {
                if !allow {
                    return Err(self.ref_position(&self.peek(0).clone()));
                }
                maxlen = Some(self.ref_len()?);
            } else if lo.is_some() && self.at(";", 0) {
                let p = self.peek(0).clone();
                return Err(self.ref_syntax(&p, "expected ']' or '; <=N' after the element range".to_string(), ""));
            } else if self.at(";", 0) {
                let p = self.peek(0).clone();
                return Err(self.ref_syntax(
                    &p,
                    "expected '<=' after ';' in an array length bound".to_string(),
                    "write the length bound as `<=N`, e.g. [i64; <=8]",
                ));
            }
            self.expect("]")?;
            if lo.is_none() && maxlen.is_none() {
                return Ok((arr_ty, None));
            }
            return Ok((
                arr_ty,
                Some(Refinement { line: t.line, col: t.col, shape: "array".to_string(), base: e.val.clone(), lo, hi, maxlen }),
            ));
        }
        let n = if self.at("crate", 0) { self.type_path()? } else { self.ident()? }; // G4: a qualified type path
        let ty: GType;
        if n.val == "u8" || n.val == "i32" {
            return Err(PruvError::new(
                "parse",
                n.line,
                n.col,
                "element_storage_type",
                format!("{} is only an array element type", n.val),
                "use i64 for a scalar, or [u8] for a byte array",
            ));
        } else if n.val == "i64" {
            ty = GType::i64();
        } else if n.val == "bool" {
            ty = GType::bool();
        } else if n.val == "str" {
            ty = GType::str();
        } else {
            // Option/Result, a type parameter or a user type (G3: with optional type arguments); the checker resolves the names.
            // The lowercase spelling of a built-in Type name must not become an alias.
            if matches!(n.val.as_str(), "unit" | "array" | "option" | "result" | "array_u8" | "array_bool" | "array_i32") {
                return Err(self.err(
                    format!("unknown type {}", repr_str(&n.val)),
                    "use i64, bool, (), [i64], Option<i64>, Result<i64> or a declared struct/enum",
                    Some(&n),
                ));
            }
            ty = self.named_type(&n)?;
        }
        if self.at("|", 0) {
            if !allow {
                return Err(self.ref_position(&self.peek(0).clone()));
            }
            self.bump();
            let (lo, hi) = self.ref_range()?;
            // A base type other than i64 is reported by refine.rs as type/refinement_base
            return Ok((
                ty,
                Some(Refinement { line: t.line, col: t.col, shape: "scalar".to_string(), base: n.val, lo: Some(lo), hi: Some(hi), maxlen: None }),
            ));
        }
        Ok((ty, None))
    }

    /// foreign: the `trusted` token of a `trusted rust fn` declaration (its `rust` was consumed), else None.
    fn function(&mut self, foreign: Option<Tok>) -> R<Function> {
        let mut kw = self.expect_tok("fn")?;
        if let Some(t) = &foreign {
            kw = t.clone();
        }
        let name = self.ident()?.val;
        let tparams = if self.at("<", 0) { self.type_params(&fn_owner(&name))? } else { Vec::new() };
        self.expect("(")?;
        let mut params = Vec::new();
        while !self.at(")", 0) {
            let mut take = false;
            let mut mode_tok: Option<Tok> = None;
            let t0 = self.peek(0).clone();
            if t0.kind == Kind::Id && t0.val == "take" && self.peek(1).kind == Kind::Id {
                if self.peek(2).kind == Kind::Op && self.peek(2).val == ":" {
                    self.bump();
                    take = true;
                } else if self.peek(1).val == "inout" && self.peek(2).kind == Kind::Id {
                    // G5: `take inout name`
                    return Err(self.inout_syntax(
                        &t0,
                        "a parameter cannot be both take and inout",
                        "keep one mode: `take name: Type` or `inout name: [i64]`",
                    ));
                } else {
                    return Err(self.foreign_syntax(&t0, "malformed take parameter", "write `take name: Type`"));
                }
            } else if t0.kind == Kind::Id && t0.val == "inout" && !(self.peek(1).kind == Kind::Op && self.peek(1).val == ":") {
                // G5: contextual `inout` before a parameter name (`inout: T` is an ordinary parameter named inout)
                let mt = self.next();
                let n1 = self.peek(0).clone();
                if n1.kind != Kind::Id {
                    return Err(self.inout_syntax(&mt, "inout needs a parameter name", "write `inout name: [i64]`"));
                }
                if (n1.val == "take" || n1.val == "inout") && self.peek(1).kind == Kind::Id {
                    return Err(self.inout_syntax(
                        &n1,
                        "a parameter has at most one mode",
                        "keep one mode: `take name: Type` or `inout name: [i64]`",
                    ));
                }
                mode_tok = Some(mt);
            }
            let pn = self.ident()?.val;
            self.expect(":")?;
            let (ty, refine) = self.type_r(true)?;
            params.push(Param { name: pn, ty, refine, take, mode_pos: mode_tok.map(|t| (t.line, t.col)) });
            if !self.at(")", 0) {
                self.expect(",")?;
            }
        }
        self.expect(")")?;
        self.expect("->")?;
        let (ret, ret_refine) = self.type_r(true)?;
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
        let decreases = self.decreases_clause()?; // G9 A0: at most one measure, after all requires/ensures
        let mut info: Option<ForeignInfo> = None;
        let body;
        if foreign.is_some() {
            if self.at("{", 0) {
                let t = self.peek(0).clone();
                return Err(self.foreign_syntax(&t, "a trusted rust fn has no body", "end it with `= \"::path\";`"));
            }
            if !self.at("=", 0) {
                let t = self.peek(0).clone();
                return Err(self.foreign_syntax(&t, "missing Rust path", "write `= \"::std::cmp::min\";` after the contracts"));
            }
            self.bump();
            let pt = self.peek(0).clone();
            if pt.kind != Kind::Str {
                return Err(self.foreign_syntax(
                    &pt,
                    "missing Rust path",
                    "write the path as a string, e.g. \"::std::cmp::min\"",
                ));
            }
            self.bump();
            self.expect(";")?;
            let path = String::from_utf8_lossy(&decode_str_lit(&pt.val)).into_owned();
            info = Some(ForeignInfo { path, line: pt.line, col: pt.col });
            body = Vec::new();
        } else {
            body = self.block()?;
        }
        self.scope = HashMap::new();
        Ok(Function {
            line: kw.line, col: kw.col, name, params, ret, effects, requires: req, ensures: ens, body, ret_refine, tparams,
            foreign: info,
            decreases,
        })
    }

    fn decreases_syntax(&self, tok: &Tok, msg: &str, fix: &str) -> PruvError {
        PruvError::new("parse", tok.line, tok.col, "decreases_syntax", msg, fix)
    }

    /// G9 A0: optional `decreases Expr` of a function header (after requires/ensures, before `{` or `=`).
    /// Duplicate, empty, tuple and misplaced clauses are parse/decreases_syntax.
    fn decreases_clause(&mut self) -> R<Option<Expr>> {
        let mut expr: Option<Expr> = None;
        if self.at("decreases", 0) {
            self.bump();
            let t = self.peek(0).clone();
            if (t.kind == Kind::Op && matches!(t.val.as_str(), "{" | "=" | ";")) || t.kind == Kind::Eof {
                return Err(self.decreases_syntax(&t, "empty decreases clause", "write one scalar measure, e.g. `decreases n`"));
            }
            if self.at("(", 0) {
                // a parenthesized group with a top-level comma is a tuple measure
                let mut depth: i64 = 0;
                let mut k: usize = 0;
                loop {
                    let tk = self.peek(k).clone();
                    if tk.kind == Kind::Eof {
                        break;
                    }
                    if tk.kind == Kind::Op && (tk.val == "(" || tk.val == "[") {
                        depth += 1;
                    } else if tk.kind == Kind::Op && (tk.val == ")" || tk.val == "]") {
                        depth -= 1;
                        if depth <= 0 {
                            break;
                        }
                    } else if tk.kind == Kind::Op && tk.val == "," && depth == 1 {
                        return Err(self.decreases_syntax(
                            &tk,
                            "a decreases clause takes one scalar measure, not a tuple",
                            "combine the measures into one i64 expression, e.g. `decreases 2 * n + 1`",
                        ));
                    } else if tk.kind == Kind::Op && matches!(tk.val.as_str(), "{" | "}" | ";") {
                        break;
                    }
                    k += 1;
                }
            }
            expr = Some(self.expr()?);
            if self.at(",", 0) {
                let t = self.peek(0).clone();
                return Err(self.decreases_syntax(
                    &t,
                    "a decreases clause takes one scalar measure, not a list",
                    "combine the measures into one i64 expression, e.g. `decreases 2 * n + 1`",
                ));
            }
        }
        if self.at("decreases", 0) {
            let t = self.peek(0).clone();
            return Err(self.decreases_syntax(
                &t,
                "a function has at most one decreases clause",
                "keep a single `decreases <expr>` after requires/ensures",
            ));
        }
        if self.at("requires", 0) || self.at("ensures", 0) {
            let t = self.peek(0).clone();
            return Err(self.decreases_syntax(
                &t,
                &format!("{} must come before decreases", t.val),
                "move `decreases` after all requires/ensures clauses",
            ));
        }
        Ok(expr)
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

    // ---- statements ----
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
            let (ty, refine) = self.type_r(true)?;
            self.expect("=")?;
            let value = self.expr()?;
            self.expect(";")?;
            return Ok(Stmt::Let(Let { line: l, col: c, name: n, mutable, ty, value, refine }));
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
            return Ok(Stmt::Assert(Assert { line: l, col: c, cond: v, origin_code: None, origin_what: None }));
        }
        if self.at("match", 0) {
            self.bump();
            let scr = self.expr()?;
            self.expect("{")?;
            let mut arms = Vec::new();
            while !self.at("}", 0) {
                if self.at("crate", 0) {
                    // G4: `crate::m::Enum::Variant(x) =>`; the last segment is the variant
                    let (ct, segs) = self.crate_path(false)?;
                    if segs.len() < 2 {
                        return Err(self.path_syntax(&ct, "a variant pattern is written crate::module::Enum::Variant"));
                    }
                    let enum_path = format!("crate::{}", segs[..segs.len() - 1].join("::"));
                    let variant = segs[segs.len() - 1].clone();
                    let mut binders = Vec::new();
                    if self.at("(", 0) {
                        let lp = self.next();
                        if self.at(")", 0) {
                            return Err(self.err(
                                "a pattern lists one name per field; a variant without fields has no parentheses",
                                format!("write `{}::{} =>`", enum_path, variant),
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
                    arms.push(MatchArm { line: ct.line, col: ct.col, enum_name: Some(enum_path), ctor: variant, binders, body });
                    if self.at(",", 0) {
                        self.bump();
                    }
                    continue;
                }
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
            // It may also be an index assignment
            let save = self.i;
            let n = self.next().val;
            self.bump();
            let idx = self.expr()?;
            self.expect("]")?;
            if self.at("=", 0) {
                self.bump();
                let v = self.expr()?;
                self.expect(";")?;
                return Ok(Stmt::IndexAssign(IndexAssign { line: l, col: c, name: n, index: idx, value: v, elem_refine: None }));
            }
            self.i = save;
        }
        if t.kind == Kind::Id && self.at(".", 1) {
            // Field assignment `p.a.b = e;`, otherwise an expression statement
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
                // An else-if chain is counted as depth too (checked after the fix: outside the count, a million of them overflowed the stack)
                self.enter(1)?;
                let r = self.if_();
                self.leave(1);
                els = vec![Stmt::If(r?)];
            } else {
                els = self.block()?;
            }
        }
        Ok(If { line: t.line, col: t.col, cond, then, els })
    }

    // ---- expressions (precedence climbing) ----
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
        let mut chain = 0; // a binary chain that piles up to the left is counted as depth too
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
        let mut chain = 0; // a binary chain that piles up to the left is counted as depth too
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
        let mut chain = 0; // a binary chain that piles up to the left is counted as depth too
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
        let mut chain = 0; // a binary chain that piles up to the left is counted as depth too
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
        let mut chain = 0; // a postfix chain that piles up to the left, like a[i][j].f, is counted as depth too
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

    /// `Enum::Variant` -> (enum token, variant token); G4: also `crate::m::Enum::Variant` (enum token value = the enum's path)
    fn enum_ref(&mut self) -> R<(Tok, Tok)> {
        if self.at("crate", 0) {
            let (ct, segs) = self.crate_path(false)?;
            if segs.len() < 2 {
                return Err(self.path_syntax(&ct, "a variant is written crate::module::Enum::Variant"));
            }
            let vt = Tok { kind: Kind::Id, val: segs[segs.len() - 1].clone(), line: ct.line, col: ct.col, end: 0 };
            let en = Tok {
                kind: Kind::Id,
                val: format!("crate::{}", segs[..segs.len() - 1].join("::")),
                line: ct.line,
                col: ct.col,
                end: 0,
            };
            return Ok((en, vt));
        }
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
        if t.kind == Kind::Str {
            self.bump();
            return Ok(Expr::StrLit(StrLit { line, col, value: decode_str_lit(&t.val), ty: None }));
        }
        if t.kind == Kind::Move {
            // G6: `move name`
            self.bump();
            let n = self.peek(0).clone();
            if n.kind != Kind::Id {
                return Err(self.foreign_syntax(&t, "move takes a binding name", "write `move name`"));
            }
            self.bump();
            return Ok(Expr::Move(Move { line, col, name: n.val, ty: None }));
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
            let mut targs: Option<Vec<GType>> = None;
            if self.at("::", 0) && self.at("<", 1) {
                targs = Some(self.expr_targs()?); // G3: None::<T>
            }
            return Ok(Expr::Ctor(Ctor { line, col, name: "None".to_string(), arg: None, ty: None, targs, inst: None }));
        }
        if self.at("Some", 0) || self.at("Ok", 0) || self.at("Err", 0) {
            self.bump();
            let targs = if self.at("::", 0) && self.at("<", 1) { Some(self.expr_targs()?) } else { None }; // G3: Some::<T>(x)
            self.expect("(")?;
            let a = self.expr()?;
            self.expect(")")?;
            return Ok(Expr::Ctor(Ctor { line, col, name: t.val.clone(), arg: Some(Box::new(a)), ty: None, targs, inst: None }));
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
            return Ok(Expr::IsVariant(IsVariant { line, col, value: Box::new(v), enum_name: en.val, variant: vt.val, ty: None, enum_ty: None }));
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
                line, col, value: Box::new(v), enum_name: en.val, variant: vt.val, field: f.val, ty: None, enum_ty: None,
            }));
        }
        if self.at("crate", 0) {
            return self.crate_expr();
        }
        if t.kind == Kind::Id {
            self.bump();
            let mut targs: Option<Vec<GType>> = None;
            if self.at("::", 0) && self.at("<", 1) {
                // G3: f::<T>(x), S::<A, B> { .. }, E::<A, B>::V(x)
                targs = Some(self.expr_targs()?);
                if !(self.at("::", 0) || self.at("(", 0) || (self.at("{", 0) && is_upper(&t.val))) {
                    let p = self.peek(0).clone();
                    return Err(self.generic_syntax(
                        &p,
                        "a type application must be followed by `(`, `{` or `::Variant`",
                        "write f::<T>(x), Pair::<A, B> { .. } or Choice::<A, B>::Left(x)",
                    ));
                }
            }
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
                return Ok(Expr::EnumCtor(EnumCtor { line, col, enum_name: t.val.clone(), variant: vt.val, args, ty: None, targs, inst: None }));
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
                return Ok(Expr::StructLit(StructLit { line, col, name: t.val.clone(), fields: inits, ty: None, targs, inst: None }));
            }
            if self.at("(", 0) {
                self.bump();
                let mut args = Vec::new();
                while !self.at(")", 0) {
                    args.push(self.arg_expr()?); // G5: `inout name` marker
                    if !self.at(")", 0) {
                        self.expect(",")?;
                    }
                }
                self.expect(")")?;
                return Ok(Expr::Call(Call { line, col, name: t.val.clone(), args, ty: None, targs, inst: None, old: None }));
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
            _ => panic!("not a return"),
        }
    }

    fn int_of(e: &Expr) -> (String, i64) {
        match e {
            Expr::IntLit(i) => (i.value.clone(), i.col),
            other => panic!("not an IntLit: {:?}", other),
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
