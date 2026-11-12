extern "C" {
    fn pruv_abi_run(a: *const i64, len: i64, out: *mut sol::Pruv__Array);
    fn pruv_free(data: *mut i64, len: i64);
}

fn main() {
    // Free through the C ABI so PRUV_COUNT_ALLOCS observes both sides of the
    // ownership transfer. Typed Vec return/drop is also exercised by g8_r12.
    for _ in 0..32 {
        let mut input = vec![11, -4, 0, 19];
        let mut result = sol::Pruv__Array { data: std::ptr::null_mut(), len: 0 };
        unsafe { pruv_abi_run(input.as_ptr(), input.len() as i64, &mut result); }
        assert_eq!(result.len, 4);
        assert_ne!(result.data, input.as_mut_ptr());
        let output = unsafe { std::slice::from_raw_parts_mut(result.data, 4) };
        input[0] = 99;
        assert_eq!(output, &[19, 0, -4, 11]);
        output[0] = 77;
        assert_eq!(input, vec![99, -4, 0, 19]);
        drop(input);
        assert_eq!(output, &[77, 0, -4, 11]);
        unsafe { pruv_free(result.data, result.len); }
        let mut empty = sol::Pruv__Array { data: std::ptr::null_mut(), len: 0 };
        unsafe { pruv_abi_run(std::ptr::null(), 0, &mut empty); }
        assert_eq!(empty.len, 0);
        unsafe { pruv_free(empty.data, empty.len); }
    }
}
