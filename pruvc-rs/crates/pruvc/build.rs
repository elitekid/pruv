//! Compiles the original `pruvc/runtime.c` (read in place, never copied) for
//! the cargo TARGET in four variants and leaves one object per variant in
//! OUT_DIR: rt_malloc.o, rt_malloc_count.o, rt_rust.o, rt_rust_count.o.
//! On MSVC the count variants use GCC `__attribute__((constructor))`, so they
//! are not built; an empty file is written instead and runtime.rs treats an
//! empty object as "missing" (target_runtime_missing).

use std::env;
use std::fs;
use std::path::PathBuf;

const RUNTIME_C: &str = "../../../pruvc/runtime.c";

fn build_variant(out: &PathBuf, name: &str, defines: &[&str]) {
    let dest = out.join(format!("rt_{name}.o"));
    // One private out_dir per variant: object file names derive from the
    // source path, so variants would otherwise overwrite each other.
    let work = out.join(format!("rt_work_{name}"));
    fs::create_dir_all(&work).expect("create variant dir");
    let mut b = cc::Build::new();
    b.file(RUNTIME_C)
        .out_dir(&work)
        .opt_level(2)
        .warnings(false)
        .cargo_metadata(false)
        .pic(true);
    if b.get_compiler().is_like_msvc() {
        b.flag("/std:c11");
    } else {
        b.flag("-std=c11");
    }
    for d in defines {
        b.define(d, None);
    }
    let objs = b.compile_intermediates();
    assert_eq!(objs.len(), 1, "runtime.c must yield exactly one object");
    fs::copy(&objs[0], &dest).expect("copy runtime object");
}

fn main() {
    println!("cargo:rerun-if-changed={RUNTIME_C}");
    println!("cargo:rerun-if-changed=build.rs");
    let out = PathBuf::from(env::var_os("OUT_DIR").expect("OUT_DIR"));
    let target = env::var("TARGET").expect("TARGET");
    println!("cargo:rustc-env=PRUVC_RT_TARGET={target}");
    let msvc = target.ends_with("-msvc");

    build_variant(&out, "malloc", &[]);
    build_variant(&out, "rust", &["PRUV_RUST_ALLOCATOR"]);
    if msvc {
        fs::write(out.join("rt_malloc_count.o"), b"").unwrap();
        fs::write(out.join("rt_rust_count.o"), b"").unwrap();
    } else {
        build_variant(&out, "malloc_count", &["PRUV_COUNT_ALLOCS"]);
        build_variant(&out, "rust_count", &["PRUV_RUST_ALLOCATOR", "PRUV_COUNT_ALLOCS"]);
    }
}
