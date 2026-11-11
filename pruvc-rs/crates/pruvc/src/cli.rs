//! 명령줄 해석. Python `pruvc.py`(argparse)와 같은 옵션·문장에 --emit/--target/-mcpu 를 더한 것.
//! 사용법 오류는 `Err(메시지)` 로 돌려주고, 출력(usage 한 줄 + stderr + exit 2)은 `usage_error` 가 한다.

use pruvc::target::{Cpu, Target};
use std::path::{Component, Path, PathBuf};

// stdout 의 usage 줄은 Python pruvc.py 와 (실행 파일 이름만 빼고) 같게 둔다(감사 필수 3). 새 옵션은 stderr 에 알린다.
pub const USAGE: &str = "usage: pruvc in.pruv -o OUT [--no-verify] [--trust-callers] [--backend rust|llvm] [--rust-bindings PATH] [--infer [--show-inferred]]";
pub const USAGE_MORE: &str = "       [--emit exe|obj|ll|rs] [--target TRIPLE] [-mcpu=CPU]";

/// 내부 출력 종류(backend×emit 결정표의 결과).
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

/// 해석이 끝난 인자. 경로 규칙 검사까지 통과한 값이다.
#[derive(Debug)]
pub struct Args {
    pub input: String,
    /// exe 에서 -o 를 생략했으면 입력 stem 으로 채워진 값.
    pub out: String,
    pub kind: Kind,
    pub verify: bool,
    pub trust_callers: bool,
    /// --infer: Houdini 불변식 추론을 켠다.
    pub infer: bool,
    /// --show-inferred: 루프별 추론 기록을 stderr 에(--infer 필요).
    pub show_inferred: bool,
    pub budget: u64,
    /// ll: 항상 Some(기본값 포함), obj: 명시했을 때만, 나머지 None.
    pub bindings: Option<String>,
    /// 7단계(Rust 소스 뒷단)가 들어오면 driver 가 읽는다. 지금은 검증된 경로 쌍만 보관.
    pub also_llvm: Option<(String, String)>,
    /// obj/exe 는 항상 Some(기본 호스트). rs/ll 은 --target 을 줬을 때만(검증만 하고 쓰지 않음).
    pub target: Option<Target>,
    pub cpu: Cpu,
}

/// 사용법 오류를 Python 과 같은 형식으로 낸다: stdout 에 USAGE, stderr 에 상세, 종료 코드 2.
pub fn usage_error(msg: &str) -> i32 {
    println!("{USAGE}");
    eprintln!("{USAGE_MORE}");
    eprintln!("pruvc: error: {msg}");
    2
}

// 옵션 이름과 받는 값 개수. 선언 순서는 argparse 의 약어 모호성 메시지 순서이기도 하다.
static OPTS: [(&str, usize); 11] = [
    ("-o", 1),
    ("--no-verify", 0),
    ("--trust-callers", 0),
    ("--backend", 1),
    ("--rust-bindings", 1),
    ("--infer", 0),
    ("--show-inferred", 0),
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
    budget: Option<i128>,
    also_llvm: Option<(String, String)>,
    emit: Option<Kind>,
    target: Option<String>,
    mcpu: Option<String>,
}

/// argparse 의 음수 판별(`^-\d+$|^-\d*\.\d+$`): 옵션이 아니라 값으로 본다.
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

/// 이 토큰을 옵션으로 볼지(argparse 규칙의 단순판): 공백이 든 낯선 토큰과 음수는 값.
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

/// 옵션 토큰 -> (옵션 이름, `=` 뒤 값). 모르면 None(= 남는 인자). 긴 옵션은 유일한 접두 약어를 허용.
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

/// Python int() 의 십진 문법(부호·앞뒤 공백·밑줄 구분)을 i128 로. 너무 큰 수는 포화.
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

/// backend×emit 결정표(설계 3절).
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

/// Python os.path.splitext(p)[0]: 마지막 성분의 마지막 점 앞까지(앞쪽 점들은 확장자 구분이 아님).
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

/// 경로 비교 키: 절대·정규화, 있으면 심볼릭 링크까지 푼 실제 경로(기존 파일 별칭), Windows 는 소문자.
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

/// 경로들이 서로 모두 다른지.
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

/// argv(프로그램 이름 제외) -> Args. Err 는 사용법 오류 메시지.
pub fn parse(argv: &[String]) -> Result<Args, String> {
    let r = parse_raw(argv)?;
    let kind_res = resolve_kind(r.backend, r.emit);

    // 필수 인자: -o 는 exe 에서만 생략 가능
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

    // pruvc.py main 의 첫 검사: --show-inferred 는 --infer 가 있어야 한다
    if r.show_inferred && !r.infer {
        return Err("--show-inferred requires --infer".to_string());
    }
    // 이 아래 순서는 pruvc.py main 과 같다: also-llvm → 예산 → rust-bindings → 바인딩 경로
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

    // 대상·CPU
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

    // 출력 경로
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
    // 입력과 출력 경로 중복 거부
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
