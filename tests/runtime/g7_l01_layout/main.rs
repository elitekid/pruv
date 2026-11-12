fn main() { layout(); for flag in [false, true] { let a = sol::run(flag); assert_eq!(a, sol::sequential(flag)); assert_eq!(a, if flag { vec![7, 9] } else { vec![0, 0] }); } }

#[repr(C)] struct Job { callback: unsafe extern "C" fn(*mut std::ffi::c_void), ctx: *mut std::ffi::c_void }
#[repr(C)] struct Ctx { dst: *mut i64, len: i64, n: i64, flag: u8, byte: i64, src: *const u8, src_len: i64, bits: *const u8, bits_len: i64 }
fn layout() {
 assert_eq!(std::mem::size_of::<Job>(),16); assert_eq!(std::mem::align_of::<Job>(),8);
 assert_eq!(std::mem::offset_of!(Job,ctx),8);
 assert_eq!(std::mem::size_of::<Ctx>(),72); assert_eq!(std::mem::align_of::<Ctx>(),8);
 assert_eq!(std::mem::offset_of!(Ctx,flag),24); assert_eq!(std::mem::offset_of!(Ctx,byte),32);
 assert_eq!(std::mem::offset_of!(Ctx,src),40); assert_eq!(std::mem::offset_of!(Ctx,bits_len),64);
}
