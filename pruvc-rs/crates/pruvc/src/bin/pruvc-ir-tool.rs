//! Dev-only tool: .ll → object, embedded runtime extraction, system link,
//! i128 helper-symbol scan. Not shipped; never marks IR as verified Pruv.

use pruvc::abi_lower::{self, InputAbi};
use pruvc::link::{self, RuntimeChoice};
use pruvc::runtime::{self, Variant};
use pruvc::target::{Cpu, Target};
use pruvc::{llvm, Error};
use std::path::PathBuf;
use std::process::exit;

const USAGE: &str = "usage:
  pruvc-ir-tool obj IN.ll -o OUT.o [--target TRIPLE] [-mcpu=generic|native|NAME] [--input-abi legacy|target]
  pruvc-ir-tool runtime -o OUT.o [--variant malloc|rust] [--count-allocs] [--target TRIPLE]
  pruvc-ir-tool link OBJ... -o EXE [--target TRIPLE] [--runtime malloc|malloc-count|none]
  pruvc-ir-tool undef OBJ...
  pruvc-ir-tool --version";

fn usage(msg: &str) -> ! {
    eprintln!("pruvc-ir-tool: {msg}\n{USAGE}");
    exit(2)
}

fn fail(e: Error) -> ! {
    // one line on stderr (linker stderr may be multi-line; keep it verbatim)
    eprintln!("pruvc-ir-tool: {e}");
    exit(1)
}

#[derive(Default)]
struct Opts {
    positional: Vec<String>,
    output: Option<String>,
    target: Option<String>,
    mcpu: Option<String>,
    input_abi: Option<String>,
    variant: Option<String>,
    runtime: Option<String>,
    count_allocs: bool,
}

fn parse_opts(args: &[String]) -> Opts {
    let mut o = Opts::default();
    let mut i = 0;
    let mut value = |i: &mut usize, name: &str| -> String {
        *i += 1;
        match args.get(*i) {
            Some(v) => v.clone(),
            None => usage(&format!("{name} needs a value")),
        }
    };
    while i < args.len() {
        let a = args[i].as_str();
        match a {
            "-o" => o.output = Some(value(&mut i, "-o")),
            "--target" => o.target = Some(value(&mut i, "--target")),
            "--input-abi" => o.input_abi = Some(value(&mut i, "--input-abi")),
            "--variant" => o.variant = Some(value(&mut i, "--variant")),
            "--runtime" => o.runtime = Some(value(&mut i, "--runtime")),
            "--count-allocs" => o.count_allocs = true,
            _ if a.starts_with("-mcpu=") => o.mcpu = Some(a["-mcpu=".len()..].to_string()),
            _ if a.starts_with('-') && a.len() > 1 => usage(&format!("unknown option {a}")),
            _ => o.positional.push(a.to_string()),
        }
        i += 1;
    }
    o
}

fn resolve_target(o: &Opts) -> Target {
    match &o.target {
        Some(t) => Target::parse(t).unwrap_or_else(|e| fail(e)),
        None => Target::host().unwrap_or_else(|e| fail(e)),
    }
}

fn cmd_obj(o: Opts) {
    if o.positional.len() != 1 {
        usage("obj takes exactly one input .ll");
    }
    let out = o.output.clone().unwrap_or_else(|| usage("obj needs -o OUT.o"));
    let abi = match o.input_abi.as_deref() {
        None => InputAbi::Legacy,
        Some(s) => InputAbi::parse(s).unwrap_or_else(|| usage("--input-abi must be legacy or target")),
    };
    let cpu = Cpu::parse(o.mcpu.as_deref().unwrap_or("generic"));
    let target = resolve_target(&o);
    let input = &o.positional[0];
    let ir = std::fs::read(input).unwrap_or_else(|e| fail(Error::new("io", format!("{input}: {e}"))));
    abi_lower::check(&ir, abi, &target).unwrap_or_else(|e| fail(e));
    llvm::compile_ir_to_object(&ir, input, &target, &cpu, std::path::Path::new(&out), )
        .unwrap_or_else(|e| fail(e));
}

fn cmd_runtime(o: Opts) {
    if !o.positional.is_empty() {
        usage("runtime takes no positional arguments");
    }
    let out = o.output.clone().unwrap_or_else(|| usage("runtime needs -o OUT.o"));
    let variant = match o.variant.as_deref() {
        None => Variant::Malloc,
        Some(s) => Variant::parse(s).unwrap_or_else(|| usage("--variant must be malloc or rust")),
    };
    let target = resolve_target(&o);
    let bytes = runtime::object(&target, variant, o.count_allocs).unwrap_or_else(|e| fail(e));
    std::fs::write(&out, bytes).unwrap_or_else(|e| fail(Error::new("io", format!("{out}: {e}"))));
}

fn cmd_link(o: Opts) {
    if o.positional.is_empty() {
        usage("link needs at least one object");
    }
    let exe = o.output.clone().unwrap_or_else(|| usage("link needs -o EXE"));
    let rt = match o.runtime.as_deref() {
        None | Some("malloc") => RuntimeChoice::Malloc,
        Some("malloc-count") => RuntimeChoice::MallocCount,
        Some("none") => RuntimeChoice::None,
        Some(_) => usage("--runtime must be malloc, malloc-count or none"),
    };
    let target = resolve_target(&o);
    let objs: Vec<PathBuf> = o.positional.iter().map(PathBuf::from).collect();
    link::link(&objs, std::path::Path::new(&exe), &target, rt).unwrap_or_else(|e| fail(e));
}

/// i128 compiler-rt helper names (without any platform underscore prefix).
fn is_i128_helper(name: &str) -> bool {
    const NAMES: [&str; 22] = [
        "__divti3", "__modti3", "__multi3", "__udivti3", "__umodti3", "__muloti4",
        "__udivmodti4", "__ashlti3", "__ashrti3", "__lshrti3", "__negti2", "__popcountti2",
        "__clzti2", "__ctzti2", "__fixdfti", "__fixsfti", "__fixunsdfti", "__fixunssfti",
        "__floattidf", "__floattisf", "__floatuntidf", "__floatuntisf",
    ];
    let n = name.strip_prefix('_').filter(|r| r.starts_with("__")).unwrap_or(name);
    NAMES.contains(&n)
}

fn cmd_undef(o: Opts) {
    if o.positional.is_empty() {
        usage("undef needs at least one object");
    }
    let mut seen: Vec<String> = Vec::new();
    for p in &o.positional {
        let bytes = std::fs::read(p).unwrap_or_else(|e| fail(Error::new("io", format!("{p}: {e}"))));
        for s in llvm::undefined_symbols(&bytes, p).unwrap_or_else(|e| fail(e)) {
            if is_i128_helper(&s) && !seen.contains(&s) {
                seen.push(s);
            }
        }
    }
    for s in seen {
        println!("{s}");
    }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let Some(cmd) = args.first() else { usage("missing subcommand") };
    match cmd.as_str() {
        "--version" | "-V" => {
            println!("pruvc-ir-tool {} (LLVM {})", env!("CARGO_PKG_VERSION"), llvm::llvm_version());
        }
        "-h" | "--help" => println!("{USAGE}"),
        "obj" => cmd_obj(parse_opts(&args[1..])),
        "runtime" => cmd_runtime(parse_opts(&args[1..])),
        "link" => cmd_link(parse_opts(&args[1..])),
        "undef" => cmd_undef(parse_opts(&args[1..])),
        other => usage(&format!("unknown subcommand '{other}'")),
    }
}
