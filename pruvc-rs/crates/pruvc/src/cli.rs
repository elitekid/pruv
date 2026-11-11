//! Command-line parsing. The same options and messages as Python `pruvc.py` (argparse), plus --emit/--target/-mcpu.
//! A usage error is returned as `Err(message)`, and the output (one usage line + stderr + exit 2) is produced by `usage_error`.

use pruvc::target::{Cpu, Target};
use std::path::{Component, Path, PathBuf};

// The usage line on stdout is kept the same as Python pruvc.py (except for the executable name) (audit must-fix 3). New options are reported on stderr.
pub const USAGE: &str = "usage: pruvc in.pruv -o OUT [--no-verify] [--trust-callers] [--backend rust|llvm] [--rust-bindings PATH] [--infer [--show-inferred]] [--rust-extern NAME=PATH] [--rust-search PATH] [--foreign-checks requires|all|off]";
pub const USAGE_MORE: &str = "       [--emit exe|obj|ll|rs] [--target TRIPLE] [-mcpu=CPU]";

/// Internal output kind (the result of the backend x emit decision table).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Rs,
    Ll,
    Obj,
    Exe,
}

impl Kind {
    fn name(self) -> &'static str {
        match self {
            Kind::Rs => "rs",
            Kind::Ll => "ll",
            Kind::Obj => "obj",
            Kind::Exe => "exe",
        }
    }
}

/// Fully parsed arguments. The values have also passed the path-rule checks.
#[derive(Debug)]
pub struct Args {
    pub input: String,
    /// For exe, if -o was omitted, the value filled in from the input stem.
    pub out: String,
    pub kind: Kind,
    pub verify: bool,
    pub trust_callers: bool,
    /// --infer: turns on Houdini invariant inference.
    pub infer: bool,
    /// --show-inferred: prints the per-loop inference record to stderr (requires --infer).
    pub show_inferred: bool,
    /// G6: crate names given with --rust-extern NAME=PATH (A0: only NAME is used, the file is not opened).
    pub rust_extern: Vec<String>,
    /// G6: --rust-search PATH values (recorded only in A0).
    pub rust_search: Vec<String>,
    /// G6: --foreign-checks requires|all|off (default requires).
    pub foreign_checks: String,
    pub budget: u64,
    /// ll: always Some (default included), obj: only when given explicitly, None for the rest.
    pub bindings: Option<String>,
    /// The driver reads it once stage 7 (the Rust-source backend) arrives. For now it only keeps the validated path pair.
    pub also_llvm: Option<(String, String)>,
    /// obj/exe are always Some (default host). rs/ll only when --target was given (validated but not used).
    pub target: Option<Target>,
    pub cpu: Cpu,
}

/// Reports a usage error in the same format as Python: USAGE on stdout, details on stderr, exit code 2.
pub fn usage_error(msg: &str) -> i32 {
    println!("{USAGE}");
    eprintln!("{USAGE_MORE}");
    eprintln!("pruvc: error: {msg}");
    2
}

// Option names and the number of values they take. The declaration order is also the order of argparse's abbreviation-ambiguity message.
static OPTS: [(&str, usize); 14] = [
    ("-o", 1),
    ("--no-verify", 0),
    ("--trust-callers", 0),
    ("--backend", 1),
    ("--rust-bindings", 1),
    ("--infer", 0),
    ("--show-inferred", 0),
    ("--rust-extern", 1),
    ("--rust-search", 1),
    ("--foreign-checks", 1),
    ("--contract-budget", 1),
    ("--also-llvm", 2),
    ("--emit", 1),
    ("--target", 1),
];

#[derive(Default)]
struct Raw {
    input: Option<String>,
    extras: Vec<String>,
    out: Option<String>,
    no_verify: bool,
    trust_callers: bool,
    infer: bool,
    show_inferred: bool,
    backend: Option<&'static str>,
    rust_bindings: Option<String>,
    rust_extern: Vec<String>,
    rust_search: Vec<String>,
    foreign_checks: Option<&'static str>,
    budget: Option<i128>,
    also_llvm: Option<(String, String)>,
    emit: Option<Kind>,
    target: Option<String>,
    mcpu: Option<String>,
}

/// argparse's negative-number test (`^-\d+$|^-\d*\.\d+$`): treated as a value, not an option.
fn is_neg_number(s: &str) -> bool {
    let Some(r) = s.strip_prefix('-') else { return false };
    match r.split_once('.') {
        None => !r.is_empty() && r.bytes().all(|b| b.is_ascii_digit()),
        Some((a, b)) => {
            a.bytes().all(|c| c.is_ascii_digit()) && !b.is_empty() && b.bytes().all(|c| c.is_ascii_digit())
        }
    }
}

fn known_head(s: &str) -> bool {
    let head = s.split('=').next().unwrap_or(s);
    s.starts_with("-mcpu=") || OPTS.iter().any(|o| o.0 == head)
}

/// Whether to treat this token as an option (a simplified version of argparse's rule): an unfamiliar token containing a space, and a negative number, are values.
fn is_option_like(s: &str) -> bool {
    if !s.starts_with('-') || s.len() == 1 || is_neg_number(s) {
        return false;
    }
    if s.contains(' ') {
        return known_head(s);
    }
    true
}

type Resolved = Option<(&'static str, Option<String>)>;

/// Option token -> (option name, value after `=`). None if unknown (= a leftover argument). Long options allow a unique prefix abbreviation.
fn resolve_option(a: &str) -> Result<Resolved, String> {
    let (head, eq) = match a.find('=') {
        Some(p) => (&a[..p], Some(a[p + 1..].to_string())),
        None => (a, None),
    };
    if let Some(o) = OPTS.iter().find(|o| o.0 == head) {
        return Ok(Some((o.0, eq)));
    }
    if a.starts_with("--") {
        let m: Vec<&(&str, usize)> = OPTS.iter().filter(|o| o.0.starts_with("--") && o.0.starts_with(head)).collect();
        return match m.len() {
            0 => Ok(None),
            1 => Ok(Some((m[0].0, eq))),
            _ => Err(format!(
                "ambiguous option: {} could match {}",
                a,
                m.iter().map(|o| o.0).collect::<Vec<_>>().join(", ")
            )),
        };
    }
    // -oOUT
    if a.starts_with("-o") && a.len() > 2 {
        return Ok(Some(("-o", Some(a[2..].to_string()))));
    }
    Ok(None)
}

fn expected(name: &str, n: usize) -> String {
    if n == 1 {
        format!("argument {name}: expected one argument")
    } else {
        format!("argument {name}: expected {n} arguments")
    }
}

fn take_values(
    argv: &[String],
    i: &mut usize,
    name: &str,
    n: usize,
    explicit: Option<String>,
) -> Result<Vec<String>, String> {
    if let Some(e) = explicit {
        if n != 1 {
            return Err(expected(name, n));
        }
        return Ok(vec![e]);
    }
    let mut vals = Vec::new();
    while vals.len() < n {
        match argv.get(*i) {
            Some(v) if !is_option_like(v) => {
                vals.push(v.clone());
                *i += 1;
            }
            _ => return Err(expected(name, n)),
        }
    }
    Ok(vals)
}

/// Python int()'s decimal syntax (sign, surrounding whitespace, underscore separators) into i128. Numbers that are too large saturate.
fn parse_py_int(s: &str) -> Option<i128> {
    let t = s.trim();
    let (neg, digits) = match t.strip_prefix('-') {
        Some(r) => (true, r),
        None => (false, t.strip_prefix('+').unwrap_or(t)),
    };
    if digits.is_empty() || digits.starts_with('_') || digits.ends_with('_') || digits.contains("__") {
        return None;
    }
    let mut v: i128 = 0;
    for b in digits.bytes() {
        if b == b'_' {
            continue;
        }
        if !b.is_ascii_digit() {
            return None;
        }
        v = v.saturating_mul(10).saturating_add((b - b'0') as i128);
    }
    Some(if neg { -v } else { v })
}

fn parse_raw(argv: &[String]) -> Result<Raw, String> {
    let mut r = Raw::default();
    let mut i = 0;
    let mut only_pos = false;
    while i < argv.len() {
        let a = argv[i].clone();
        i += 1;
        if only_pos || !is_option_like(&a) {
            if r.input.is_none() {
                r.input = Some(a);
            } else {
                r.extras.push(a);
            }
            continue;
        }
        if a == "--" {
            only_pos = true;
            continue;
        }
        if let Some(v) = a.strip_prefix("-mcpu=") {
            r.mcpu = Some(v.to_string());
            continue;
        }
        let Some((name, explicit)) = resolve_option(&a)? else {
            r.extras.push(a);
            continue;
        };
        let n = OPTS.iter().find(|o| o.0 == name).map_or(0, |o| o.1);
        if n == 0 {
            if let Some(e) = explicit {
                return Err(format!("argument {name}: ignored explicit argument '{e}'"));
            }
            match name {
                "--no-verify" => r.no_verify = true,
                "--infer" => r.infer = true,
                "--show-inferred" => r.show_inferred = true,
                _ => r.trust_callers = true,
            }
            continue;
        }
        let mut vals = take_values(argv, &mut i, name, n, explicit)?;
        match name {
            "-o" => r.out = vals.pop(),
            "--rust-bindings" => r.rust_bindings = vals.pop(),
            "--rust-extern" => r.rust_extern.extend(vals.pop()),
            "--rust-search" => r.rust_search.extend(vals.pop()),
            "--foreign-checks" => {
                let v = vals.pop().unwrap_or_default();
                r.foreign_checks = Some(match v.as_str() {
                    "requires" => "requires",
                    "all" => "all",
                    "off" => "off",
                    _ => {
                        return Err(format!(
                            "argument --foreign-checks: invalid choice: '{v}' (choose from 'requires', 'all', 'off')"
                        ))
                    }
                });
            }
            "--target" => r.target = vals.pop(),
            "--backend" => {
                let v = vals.pop().unwrap_or_default();
                r.backend = Some(match v.as_str() {
                    "rust" => "rust",
                    "llvm" => "llvm",
                    _ => return Err(format!("argument --backend: invalid choice: '{v}' (choose from 'rust', 'llvm')")),
                });
            }
            "--emit" => {
                let v = vals.pop().unwrap_or_default();
                r.emit = Some(match v.as_str() {
                    "exe" => Kind::Exe,
                    "obj" => Kind::Obj,
                    "ll" => Kind::Ll,
                    "rs" => Kind::Rs,
                    _ => {
                        return Err(format!(
                            "argument --emit: invalid choice: '{v}' (choose from 'exe', 'obj', 'll', 'rs')"
                        ))
                    }
                });
            }
            "--contract-budget" => {
                let v = vals.pop().unwrap_or_default();
                match parse_py_int(&v) {
                    Some(b) => r.budget = Some(b),
                    None => return Err(format!("argument --contract-budget: invalid int value: '{v}'")),
                }
            }
            _ => {
                // --also-llvm LL RS
                let rs = vals.pop().unwrap_or_default();
                let ll = vals.pop().unwrap_or_default();
                r.also_llvm = Some((ll, rs));
            }
        }
    }
    Ok(r)
}

/// The backend x emit decision table (design §3).
fn resolve_kind(backend: Option<&str>, emit: Option<Kind>) -> Result<Kind, String> {
    match (backend, emit) {
        (None, None) => Ok(Kind::Rs),
        (None, Some(k)) => Ok(k),
        (Some("rust"), None) | (Some("rust"), Some(Kind::Rs)) => Ok(Kind::Rs),
        (Some("rust"), Some(k)) => Err(format!("--backend rust cannot be combined with --emit {}", k.name())),
        (Some("llvm"), None) => Ok(Kind::Ll),
        (Some("llvm"), Some(Kind::Rs)) => Err("--backend llvm cannot be combined with --emit rs".to_string()),
        (Some("llvm"), Some(k)) => Ok(k),
        (Some(b), _) => Err(format!("unknown backend {b}")),
    }
}

/// Python os.path.splitext(p)[0]: up to the last dot of the last component (leading dots are not extension separators).
fn splitext_root(p: &str) -> String {
    let sep = p.rfind(|c: char| c == '/' || (cfg!(windows) && c == '\\')).map_or(0, |i| i + 1);
    let base = &p[sep..];
    let stripped = base.trim_start_matches('.');
    let lead = base.len() - stripped.len();
    match stripped.rfind('.') {
        Some(d) => p[..sep + lead + d].to_string(),
        None => p.to_string(),
    }
}

fn lexical_normalize(p: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for c in p.components() {
        match c {
            Component::CurDir => {}
            Component::ParentDir => {
                if !out.pop() && !out.has_root() {
                    out.push("..");
                }
            }
            other => out.push(other.as_os_str()),
        }
    }
    out
}

/// Path comparison key: absolute and normalized, the real path with symbolic links resolved if it exists (aliases of an existing file), lowercase on Windows.
fn path_key(p: &str) -> String {
    let abs = std::path::absolute(Path::new(p)).unwrap_or_else(|_| PathBuf::from(p));
    let norm = lexical_normalize(&abs);
    let resolved = match std::fs::canonicalize(&norm) {
        Ok(c) => c,
        Err(_) => match (norm.parent().and_then(|d| std::fs::canonicalize(d).ok()), norm.file_name()) {
            (Some(d), Some(n)) => d.join(n),
            _ => norm,
        },
    };
    let s = resolved.to_string_lossy().into_owned();
    if cfg!(windows) {
        s.to_lowercase()
    } else {
        s
    }
}

fn same_path(a: &str, b: &str) -> bool {
    path_key(a) == path_key(b)
}

/// Whether all the paths differ from one another.
fn pairwise_distinct(paths: &[&str]) -> bool {
    let keys: Vec<String> = paths.iter().map(|p| path_key(p)).collect();
    for i in 0..keys.len() {
        for j in i + 1..keys.len() {
            if keys[i] == keys[j] {
                return false;
            }
        }
    }
    true
}

/// argv (without the program name) -> Args. Err is a usage error message.
pub fn parse(argv: &[String]) -> Result<Args, String> {
    let r = parse_raw(argv)?;
    let kind_res = resolve_kind(r.backend, r.emit);

    // Required arguments: -o may be omitted only for exe
    let mut missing: Vec<&str> = Vec::new();
    if r.input.is_none() {
        missing.push("input");
    }
    if r.out.is_none() && !matches!(kind_res, Ok(Kind::Exe)) {
        missing.push("-o");
    }
    if !missing.is_empty() {
        return Err(format!("the following arguments are required: {}", missing.join(", ")));
    }
    if !r.extras.is_empty() {
        return Err(format!("unrecognized arguments: {}", r.extras.join(" ")));
    }
    let kind = kind_res?;
    let input = r.input.clone().ok_or_else(|| "the following arguments are required: input".to_string())?;

    // The first check of pruvc.py main: --show-inferred requires --infer
    if r.show_inferred && !r.infer {
        return Err("--show-inferred requires --infer".to_string());
    }
    // The order below is the same as pruvc.py main: also-llvm -> budget -> rust-bindings -> bindings path
    if let Some((ll, rs)) = &r.also_llvm {
        if kind != Kind::Rs {
            return Err(if r.backend == Some("llvm") {
                "--also-llvm requires --backend rust".to_string()
            } else {
                "--also-llvm requires Rust source output (--emit rs)".to_string()
            });
        }
        let out = r.out.as_deref().unwrap_or("");
        if !pairwise_distinct(&[out, ll, rs]) {
            return Err("-o, --also-llvm LL and RS paths must be pairwise distinct".to_string());
        }
    }
    let budget: u64 = match r.budget {
        None => 1 << 30,
        Some(b) if (1..=(1i128 << 62)).contains(&b) => b as u64,
        Some(_) => return Err("--contract-budget must be in 1..2**62".to_string()),
    };
    if r.rust_bindings.is_some() {
        match kind {
            Kind::Ll | Kind::Obj => {}
            Kind::Exe => return Err("--rust-bindings cannot be used with --emit exe".to_string()),
            Kind::Rs => return Err("--rust-bindings requires --backend llvm".to_string()),
        }
    }
    // G6 (same order as pruvc.py main): --foreign-checks off needs verification, then the --rust-extern specs, then --rust-search
    let foreign_checks = r.foreign_checks.unwrap_or("requires");
    if foreign_checks == "off" && r.no_verify {
        return Err("--foreign-checks off requires verification (not allowed with --no-verify)".to_string());
    }
    let mut rust_extern: Vec<String> = Vec::new();
    for spec in &r.rust_extern {
        let (name, xpath) = match spec.split_once('=') {
            Some((n, x)) => (n, x),
            None => (spec.as_str(), ""),
        };
        let has_sep = spec.contains('=');
        let ident = {
            let mut cs = name.chars();
            match cs.next() {
                Some(c) if c.is_ascii_alphabetic() || c == '_' => cs.all(|c| c.is_ascii_alphanumeric() || c == '_'),
                _ => false,
            }
        };
        if !has_sep || xpath.is_empty() || !ident || name == "std" || pruv_core::lexer::RUST_KEYWORDS.contains(&name) {
            return Err(format!(
                "invalid --rust-extern {}: expected NAME=PATH with a Rust identifier NAME other than std",
                pruv_core::pyrepr::repr_str(spec)
            ));
        }
        if rust_extern.iter().any(|x| x == name) {
            return Err(format!("duplicate --rust-extern name {name}"));
        }
        rust_extern.push(name.to_string());
    }
    if r.rust_search.iter().any(|p| p.is_empty()) {
        return Err("--rust-search needs a non-empty PATH".to_string());
    }

    // Target and CPU
    let target = match (&r.target, kind) {
        (Some(t), _) => Some(Target::parse(t).map_err(|e| format!("argument --target: {}", e.message))?),
        (None, Kind::Obj) | (None, Kind::Exe) => Some(Target::host().map_err(|e| e.message)?),
        (None, _) => None,
    };
    if r.mcpu.as_deref() == Some("") {
        return Err("-mcpu= needs a CPU name".to_string());
    }
    let cpu = Cpu::parse(r.mcpu.as_deref().unwrap_or("generic"));
    if cpu == Cpu::Native {
        if let Some(t) = &target {
            if !t.is_host() {
                return Err("-mcpu=native is only valid for the host target".to_string());
            }
        }
    }

    // Output paths
    let out = match r.out.clone() {
        Some(o) => o,
        None => {
            let stem = splitext_root(&input);
            if target.as_ref().map_or(false, |t| t.is_windows()) {
                format!("{stem}.exe")
            } else {
                stem
            }
        }
    };
    let bindings = match kind {
        Kind::Ll => Some(r.rust_bindings.clone().unwrap_or_else(|| format!("{}.rs", splitext_root(&out)))),
        Kind::Obj => r.rust_bindings.clone(),
        _ => None,
    };
    if let Some(b) = &bindings {
        if same_path(b, &out) {
            return Err("--rust-bindings path must differ from -o path".to_string());
        }
    }
    // Reject duplicate input and output paths
    let mut outs: Vec<(&str, &str)> = vec![("-o", out.as_str())];
    if let Some(b) = &bindings {
        outs.push(("--rust-bindings", b.as_str()));
    }
    if let Some((ll, rs)) = &r.also_llvm {
        outs.push(("--also-llvm LL", ll.as_str()));
        outs.push(("--also-llvm RS", rs.as_str()));
    }
    for (label, p) in outs {
        if same_path(&input, p) {
            return Err(format!("{label} path must differ from the input path"));
        }
    }

    Ok(Args {
        input,
        out,
        kind,
        verify: !r.no_verify,
        trust_callers: r.trust_callers,
        infer: r.infer,
        show_inferred: r.show_inferred,
        rust_extern,
        rust_search: r.rust_search,
        foreign_checks: foreign_checks.to_string(),
        budget,
        bindings,
        also_llvm: r.also_llvm,
        target,
        cpu,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn p(a: &[&str]) -> Result<Args, String> {
        let v: Vec<String> = a.iter().map(|s| s.to_string()).collect();
        parse(&v)
    }

    #[test]
    fn required_and_extras() {
        assert_eq!(p(&[]).unwrap_err(), "the following arguments are required: input, -o");
        assert_eq!(p(&["a.pruv"]).unwrap_err(), "the following arguments are required: -o");
        assert_eq!(p(&["a.pruv", "-o", "x.rs", "b"]).unwrap_err(), "unrecognized arguments: b");
    }

    #[test]
    fn table() {
        assert_eq!(p(&["a.pruv", "-o", "x.rs"]).unwrap().kind, Kind::Rs);
        assert_eq!(p(&["a.pruv", "-o", "x.ll", "--backend", "llvm"]).unwrap().kind, Kind::Ll);
        assert!(p(&["a.pruv", "-o", "x", "--backend", "rust", "--emit", "ll"]).is_err());
        assert!(p(&["a.pruv", "-o", "x", "--backend", "llvm", "--emit", "rs"]).is_err());
    }

    #[test]
    fn bindings_rules() {
        assert_eq!(
            p(&["a.pruv", "-o", "x.rs", "--rust-bindings", "y.rs"]).unwrap_err(),
            "--rust-bindings requires --backend llvm"
        );
        assert_eq!(
            p(&["a.pruv", "-o", "x.rs", "--backend", "llvm"]).unwrap_err(),
            "--rust-bindings path must differ from -o path"
        );
        let a = p(&["a.pruv", "-o", "x.ll", "--backend", "llvm"]).unwrap();
        assert_eq!(a.bindings.as_deref(), Some("x.rs"));
    }

    #[test]
    fn budget_and_also() {
        assert_eq!(
            p(&["a.pruv", "-o", "x.rs", "--contract-budget", "0"]).unwrap_err(),
            "--contract-budget must be in 1..2**62"
        );
        assert_eq!(
            p(&["a.pruv", "-o", "x.rs", "--also-llvm", "x.rs", "y.rs"]).unwrap_err(),
            "-o, --also-llvm LL and RS paths must be pairwise distinct"
        );
        assert_eq!(
            p(&["a.pruv", "-o", "x.ll", "--backend", "llvm", "--also-llvm", "b.ll", "b.rs"]).unwrap_err(),
            "--also-llvm requires --backend rust"
        );
    }

    #[test]
    fn exe_default_out() {
        let a = p(&["a.pruv", "--emit", "exe", "--target", "x86_64-unknown-linux-gnu"]).unwrap();
        assert_eq!(a.out, "a");
        assert_eq!(splitext_root("d/.x"), "d/.x");
        assert_eq!(splitext_root("d.e/x.y.z"), "d.e/x.y");
    }
}
