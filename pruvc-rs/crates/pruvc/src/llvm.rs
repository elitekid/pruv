//! RAII wrappers over the llvm-sys (LLVM 22) C API. All `unsafe` lives here.
//!
//! Ownership rules used throughout:
//! * `char*` messages returned through out-parameters or by `LLVMGet*` APIs
//!   that allocate are copied into a `String` and released with
//!   `LLVMDisposeMessage` immediately (`take_message`).
//! * `Module` borrows its `Context` (lifetime), so it is always dropped first.
//! * A `TargetMachine` is independent of the context.

use crate::target::{triples_compatible, Cpu, Target};
use crate::{Error, Result};
use llvm_sys::analysis::{LLVMVerifierFailureAction, LLVMVerifyModule};
use llvm_sys::core::*;
use llvm_sys::error::{LLVMDisposeErrorMessage, LLVMGetErrorMessage};
use llvm_sys::ir_reader::LLVMParseIRInContext2;
use llvm_sys::object::*;
use llvm_sys::prelude::*;
use llvm_sys::target::*;
use llvm_sys::target_machine::*;
use llvm_sys::transforms::pass_builder::*;
use std::ffi::{CStr, CString};
use std::marker::PhantomData;
use std::os::raw::c_char;
use std::path::Path;
use std::ptr;
use std::sync::Once;

static INIT: Once = Once::new();

/// Initialise only the X86 and AArch64 backends (idempotent).
pub fn init_targets() {
    INIT.call_once(|| {
        // SAFETY: these are process-global, side-effect-only registration calls
        // with no arguments; Once guarantees single execution.
        unsafe {
            LLVMInitializeX86TargetInfo();
            LLVMInitializeX86Target();
            LLVMInitializeX86TargetMC();
            LLVMInitializeX86AsmPrinter();
            LLVMInitializeAArch64TargetInfo();
            LLVMInitializeAArch64Target();
            LLVMInitializeAArch64TargetMC();
            LLVMInitializeAArch64AsmPrinter();
        }
    });
}

/// Copy a LLVM-allocated C string into a String and free it. Null → "".
///
/// # Safety
/// `p` must be null or a NUL-terminated string allocated by LLVM and not yet disposed.
unsafe fn take_message(p: *mut c_char) -> String {
    if p.is_null() {
        return String::new();
    }
    // SAFETY: per the contract above, p is valid until disposed below.
    let s = CStr::from_ptr(p).to_string_lossy().into_owned();
    LLVMDisposeMessage(p);
    s
}

fn cstring(s: &str, what: &str) -> Result<CString> {
    CString::new(s).map_err(|_| Error::new("invalid_argument", format!("{what} contains a NUL byte")))
}

/// Version of the linked LLVM as "major.minor.patch".
pub fn llvm_version() -> String {
    let (mut a, mut b, mut c) = (0u32, 0u32, 0u32);
    // SAFETY: three valid out-pointers to local u32s.
    unsafe { LLVMGetVersion(&mut a, &mut b, &mut c) };
    format!("{a}.{b}.{c}")
}

/// No longer used for target selection (Target::host uses the public TABLE); kept for diagnostics.
#[allow(dead_code)]
pub fn default_target_triple() -> String {
    // SAFETY: LLVMGetDefaultTargetTriple returns a fresh malloc'd string we own.
    unsafe { take_message(LLVMGetDefaultTargetTriple()) }
}

pub fn host_cpu_name() -> String {
    // SAFETY: returns a fresh string we own (documented: caller disposes).
    unsafe { take_message(LLVMGetHostCPUName()) }
}

pub fn host_cpu_features() -> String {
    // SAFETY: as above.
    unsafe { take_message(LLVMGetHostCPUFeatures()) }
}

// ---------------------------------------------------------------- Context

pub struct Context(LLVMContextRef);

impl Context {
    pub fn new() -> Context {
        init_targets();
        // SAFETY: creates a new context owned by this wrapper; disposed in Drop.
        Context(unsafe { LLVMContextCreate() })
    }
}

impl Default for Context {
    fn default() -> Self {
        Self::new()
    }
}

impl Drop for Context {
    fn drop(&mut self) {
        // SAFETY: sole owner; every Module borrowing it has already been dropped.
        unsafe { LLVMContextDispose(self.0) }
    }
}

// ----------------------------------------------------------- MemoryBuffer

pub struct MemoryBuffer(LLVMMemoryBufferRef);

impl MemoryBuffer {
    /// Copies `data` into a new buffer (so `data` need not outlive it).
    pub fn copy_of(data: &[u8], name: &str) -> Result<MemoryBuffer> {
        let n = cstring(name, "buffer name")?;
        // SAFETY: the Copy variant duplicates [data, data+len); name is read during the call.
        let p = unsafe { LLVMCreateMemoryBufferWithMemoryRangeCopy(data.as_ptr() as *const c_char, data.len(), n.as_ptr()) };
        if p.is_null() {
            return Err(Error::new("llvm_error", "cannot create memory buffer"));
        }
        Ok(MemoryBuffer(p))
    }

    /// Hands ownership to the caller (for APIs that consume the buffer).
    fn into_raw(self) -> LLVMMemoryBufferRef {
        let p = self.0;
        std::mem::forget(self);
        p
    }
}

impl Drop for MemoryBuffer {
    fn drop(&mut self) {
        // SAFETY: sole owner (into_raw forgets self when ownership moves away).
        unsafe { LLVMDisposeMemoryBuffer(self.0) }
    }
}

// ----------------------------------------------------------------- Module

pub struct Module<'c> {
    raw: LLVMModuleRef,
    _ctx: PhantomData<&'c Context>,
}

impl<'c> Module<'c> {
    /// Parse textual IR (LLVMParseIRInContext2: does not consume the buffer).
    pub fn parse(ctx: &'c Context, name: &str, text: &[u8]) -> Result<Module<'c>> {
        let buf = MemoryBuffer::copy_of(text, name)?;
        let mut m: LLVMModuleRef = ptr::null_mut();
        let mut err: *mut c_char = ptr::null_mut();
        // SAFETY: ctx and buf are live; out-pointers are valid locals. The buffer stays
        // owned by `buf` (Parse…2 does not take it); on success `m` is owned by the Module.
        let failed = unsafe { LLVMParseIRInContext2(ctx.0, buf.0, &mut m, &mut err) };
        if failed != 0 || m.is_null() {
            // SAFETY: err is null or an LLVM-allocated message.
            let msg = unsafe { take_message(err) };
            return Err(Error::new("ir_parse", msg.trim_end().to_string()));
        }
        Ok(Module { raw: m, _ctx: PhantomData })
    }

    pub fn triple(&self) -> String {
        // SAFETY: returns a pointer into the module (not owned); copied at once.
        unsafe { CStr::from_ptr(LLVMGetTarget(self.raw)).to_string_lossy().into_owned() }
    }

    pub fn data_layout(&self) -> String {
        // SAFETY: as triple().
        unsafe { CStr::from_ptr(LLVMGetDataLayoutStr(self.raw)).to_string_lossy().into_owned() }
    }

    pub fn set_triple(&self, t: &str) -> Result<()> {
        let c = cstring(t, "triple")?;
        // SAFETY: LLVM copies the string.
        unsafe { LLVMSetTarget(self.raw, c.as_ptr()) };
        Ok(())
    }

    pub fn set_data_layout(&self, d: &str) -> Result<()> {
        let c = cstring(d, "datalayout")?;
        // SAFETY: LLVM copies the string.
        unsafe { LLVMSetDataLayout(self.raw, c.as_ptr()) };
        Ok(())
    }

    pub fn verify(&self, stage: &str) -> Result<()> {
        let mut err: *mut c_char = ptr::null_mut();
        // SAFETY: module is live; ReturnStatusAction never aborts; err freed by take_message.
        let bad = unsafe {
            LLVMVerifyModule(self.raw, LLVMVerifierFailureAction::LLVMReturnStatusAction, &mut err)
        };
        // SAFETY: err is null or LLVM-allocated.
        let msg = unsafe { take_message(err) };
        if bad != 0 {
            return Err(Error::new("ir_verify", format!("{stage}: {}", msg.trim_end())));
        }
        Ok(())
    }

    pub fn run_passes(&self, tm: &TargetMachine, pipeline: &str) -> Result<()> {
        let p = cstring(pipeline, "pipeline")?;
        // SAFETY: options are created and disposed here; module/tm are live; the
        // returned LLVMErrorRef (null = success) is consumed by LLVMGetErrorMessage.
        unsafe {
            let opts = LLVMCreatePassBuilderOptions();
            let e = LLVMRunPasses(self.raw, p.as_ptr(), tm.raw, opts);
            LLVMDisposePassBuilderOptions(opts);
            if !e.is_null() {
                let m = LLVMGetErrorMessage(e); // consumes e
                let s = CStr::from_ptr(m).to_string_lossy().into_owned();
                LLVMDisposeErrorMessage(m);
                return Err(Error::new("llvm_passes", s));
            }
        }
        Ok(())
    }

    pub fn emit_object(&self, tm: &TargetMachine, path: &Path) -> Result<()> {
        let p = cstring(&path.to_string_lossy(), "output path")?;
        let mut err: *mut c_char = ptr::null_mut();
        // SAFETY: filename is read-only despite the *mut in the C signature; module and
        // tm are live; err is freed by take_message.
        let bad = unsafe {
            LLVMTargetMachineEmitToFile(
                tm.raw,
                self.raw,
                p.as_ptr() as *mut c_char,
                LLVMCodeGenFileType::LLVMObjectFile,
                &mut err,
            )
        };
        // SAFETY: err null or LLVM-allocated.
        let msg = unsafe { take_message(err) };
        if bad != 0 {
            return Err(Error::new("llvm_emit", msg.trim_end().to_string()));
        }
        Ok(())
    }
}

impl Drop for Module<'_> {
    fn drop(&mut self) {
        // SAFETY: sole owner; the context outlives the module by lifetime.
        unsafe { LLVMDisposeModule(self.raw) }
    }
}

// ---------------------------------------------------------- TargetMachine

pub struct TargetMachine {
    raw: LLVMTargetMachineRef,
}

impl TargetMachine {
    /// PIC relocation model, default code model, default (O2-equivalent) codegen level.
    pub fn new(llvm_triple: &str, cpu: &str, features: &str) -> Result<TargetMachine> {
        init_targets();
        let t = cstring(llvm_triple, "triple")?;
        let c = cstring(cpu, "cpu")?;
        let f = cstring(features, "features")?;
        let mut target: LLVMTargetRef = ptr::null_mut();
        let mut err: *mut c_char = ptr::null_mut();
        // SAFETY: valid C strings and out-pointers; `target` is owned by LLVM (static registry).
        let bad = unsafe { LLVMGetTargetFromTriple(t.as_ptr(), &mut target, &mut err) };
        if bad != 0 {
            // SAFETY: err null or LLVM-allocated.
            let msg = unsafe { take_message(err) };
            return Err(Error::new("llvm_target", format!("{llvm_triple}: {}", msg.trim_end())));
        }
        // SAFETY: all pointers valid; the machine is owned by the wrapper (disposed in Drop).
        let raw = unsafe {
            LLVMCreateTargetMachine(
                target,
                t.as_ptr(),
                c.as_ptr(),
                f.as_ptr(),
                LLVMCodeGenOptLevel::LLVMCodeGenLevelDefault,
                LLVMRelocMode::LLVMRelocPIC,
                LLVMCodeModel::LLVMCodeModelDefault,
            )
        };
        if raw.is_null() {
            return Err(Error::new("llvm_target", format!("cannot create target machine for {llvm_triple}")));
        }
        Ok(TargetMachine { raw })
    }

    /// Textual data layout of this machine.
    pub fn data_layout(&self) -> String {
        // SAFETY: the TargetData is created, read and disposed here; the string is
        // LLVM-allocated and freed by take_message.
        unsafe {
            let td = LLVMCreateTargetDataLayout(self.raw);
            let s = take_message(LLVMCopyStringRepOfTargetData(td));
            LLVMDisposeTargetData(td);
            s
        }
    }
}

impl Drop for TargetMachine {
    fn drop(&mut self) {
        // SAFETY: sole owner.
        unsafe { LLVMDisposeTargetMachine(self.raw) }
    }
}

// ------------------------------------------------------------ high level

/// `obj` pipeline: parse → triple/datalayout → verify → default<O2> → verify → object file.
pub fn compile_ir_to_object(ir: &[u8], name: &str, target: &Target, cpu: &Cpu, out: &Path) -> Result<()> {
    let ctx = Context::new();
    let module = Module::parse(&ctx, name, ir)?;
    let (cpu_name, features) = cpu.resolve(target)?;
    let tm = TargetMachine::new(&target.llvm_triple, &cpu_name, &features)?;

    let have = module.triple();
    if have.is_empty() {
        module.set_triple(&target.llvm_triple)?;
    } else if !triples_compatible(&have, &target.llvm_triple) {
        return Err(Error::new(
            "target_mismatch",
            format!("input triple '{have}' differs from target '{}'", target.public),
        ));
    } else {
        // Compatible (same arch/OS/env, version suffix may differ): normalise to the table's triple.
        module.set_triple(&target.llvm_triple)?;
    }
    let want_dl = tm.data_layout();
    let have_dl = module.data_layout();
    if have_dl.is_empty() {
        module.set_data_layout(&want_dl)?;
    } else if have_dl != want_dl {
        return Err(Error::new(
            "target_mismatch",
            format!("input datalayout '{have_dl}' differs from target '{want_dl}'"),
        ));
    }

    module.verify("before optimization")?;
    module.run_passes(&tm, "default<O2>")?;
    module.verify("after optimization")?;
    module.emit_object(&tm, out)
}

/// Unresolved (undefined) symbol names of an object file, in symbol-table order.
pub fn undefined_symbols(object: &[u8], name: &str) -> Result<Vec<String>> {
    let buf = MemoryBuffer::copy_of(object, name)?;
    // SAFETY: LLVMCreateObjectFile takes ownership of the buffer on both success and
    // failure paths of the C wrapper as used here, so we give it up via into_raw and
    // never touch it again. The object, symbol and section iterators are disposed below;
    // names are copied before the iterator advances.
    unsafe {
        let obj = LLVMCreateObjectFile(buf.into_raw());
        if obj.is_null() {
            return Err(Error::new("object_read", format!("{name}: not a readable object file")));
        }
        let sym = LLVMGetSymbols(obj);
        let sect = LLVMGetSections(obj);
        let mut out = Vec::new();
        while LLVMIsSymbolIteratorAtEnd(obj, sym) == 0 {
            LLVMMoveToContainingSection(sect, sym);
            if LLVMIsSectionIteratorAtEnd(obj, sect) != 0 {
                let p = LLVMGetSymbolName(sym);
                if !p.is_null() {
                    let s = CStr::from_ptr(p).to_string_lossy().into_owned();
                    if !s.is_empty() {
                        out.push(s);
                    }
                }
            }
            LLVMMoveToNextSymbol(sym);
        }
        LLVMDisposeSectionIterator(sect);
        LLVMDisposeSymbolIterator(sym);
        LLVMDisposeObjectFile(obj);
        Ok(out)
    }
}

/// Defined global function symbol names of an object file (used to find `main`).
pub fn defined_symbols(object: &[u8], name: &str) -> Result<Vec<String>> {
    let buf = MemoryBuffer::copy_of(object, name)?;
    // SAFETY: same ownership protocol as undefined_symbols.
    unsafe {
        let obj = LLVMCreateObjectFile(buf.into_raw());
        if obj.is_null() {
            return Err(Error::new("object_read", format!("{name}: not a readable object file")));
        }
        let sym = LLVMGetSymbols(obj);
        let sect = LLVMGetSections(obj);
        let mut out = Vec::new();
        while LLVMIsSymbolIteratorAtEnd(obj, sym) == 0 {
            LLVMMoveToContainingSection(sect, sym);
            if LLVMIsSectionIteratorAtEnd(obj, sect) == 0 {
                let p = LLVMGetSymbolName(sym);
                if !p.is_null() {
                    out.push(CStr::from_ptr(p).to_string_lossy().into_owned());
                }
            }
            LLVMMoveToNextSymbol(sym);
        }
        LLVMDisposeSectionIterator(sect);
        LLVMDisposeSymbolIterator(sym);
        LLVMDisposeObjectFile(obj);
        Ok(out)
    }
}
