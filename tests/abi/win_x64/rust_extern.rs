// Windows CI driver: links and runs the Pruv wrapper objects (opt_ret.ll etc. -> .obj).
// It cannot be run on this Mac (the Windows execution ABI is only verified on Windows CI).
//
// Build example (x86_64-pc-windows-msvc; build the objects beforehand the same way check_abi.py does):
//   rustc --edition 2021 rust_extern.rs -C link-arg=opt_ret.obj -C link-arg=args_0_1_5.obj -o rust_extern.exe
//
// Expected output:
//   get_opt(5)  = (1, 5)
//   get_opt(-3) = (0, 0)
//   get_opt(MAX)= (1, 9223372036854775807)
//   f0()        = (0, 0)
//   f1(7)       = (1, 7)
//   f5(1,2,3,4,5) = (1, 15)
//   f5(-1,-2,-3,-4,-5) = (0, 0)
//   repeat ok
//   OK

#[repr(C)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct PruvTagged {
    tag: i64,
    payload: i64,
}

extern "C" {
    fn pruv_abi_get_opt(x: i64) -> PruvTagged;
    fn pruv_abi_f0() -> PruvTagged;
    fn pruv_abi_f1(a: i64) -> PruvTagged;
    fn pruv_abi_f5(a: i64, b: i64, c: i64, d: i64, e: i64) -> PruvTagged;
}

fn check(name: &str, got: PruvTagged, tag: i64, payload: i64) {
    println!("{} = ({}, {})", name, got.tag, got.payload);
    assert_eq!(got, PruvTagged { tag, payload }, "{}", name);
}

fn main() {
    unsafe {
        check("get_opt(5) ", pruv_abi_get_opt(5), 1, 5);
        check("get_opt(-3)", pruv_abi_get_opt(-3), 0, 0);
        check("get_opt(MAX)", pruv_abi_get_opt(i64::MAX), 1, i64::MAX);
        check("f0()       ", pruv_abi_f0(), 0, 0);
        check("f1(7)      ", pruv_abi_f1(7), 1, 7);
        check("f5(1,2,3,4,5)", pruv_abi_f5(1, 2, 3, 4, 5), 1, 15);
        check("f5(-1,-2,-3,-4,-5)", pruv_abi_f5(-1, -2, -3, -4, -5), 0, 0);
        for i in 0..100_000i64 {
            let r = pruv_abi_get_opt(i - 50_000);
            let want = if i > 50_000 { (1, i - 50_000) } else { (0, 0) };
            assert_eq!((r.tag, r.payload), want);
        }
    }
    println!("repeat ok");
    println!("OK");
}
