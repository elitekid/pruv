"""G7 synchronous LLVM callback bridge, included only in par programs' bindings."""
import os


def build_shim():
    hook = os.environ.get("PRUV_G7_TEST_HOOK")
    instrument = hook in ("spawn", "panic", "overlap")
    gate = 'let gate = &(::std::sync::Mutex::new((false, 0usize, 0usize)), ::std::sync::Condvar::new());' if instrument else ''
    wait = '''let mut g = gate.0.lock().unwrap();
                    g.1 += 1; gate.1.notify_all();
                    while !g.0 || g.1 < g.2 { g = gate.1.wait(g).unwrap(); }
                    ::std::mem::drop(g);''' if instrument else ''
    release = '''{ let mut g = gate.0.lock().unwrap();
                g.0 = true; g.2 = handles.len(); gate.1.notify_all(); }''' if instrument else ''
    spawn = 'if i == 1 { spawn_failed = true; break; }' if hook == 'spawn' else ''
    panic = 'if i == 0 { ::std::panic!("pruv test worker panic"); }' if hook == 'panic' else ''
    joined = '::std::eprintln!("pruv test joined");' if instrument else ''
    return '''
mod pruv_g7_shim {
    #[repr(C)]
    #[derive(Clone, Copy)]
    struct Job {
        callback: unsafe extern "C" fn(*mut ::std::ffi::c_void),
        ctx: *mut ::std::ffi::c_void,
    }
    struct SendJob(Job);
    // Only descriptors cross threads: compiler disjointness excludes mutable aliases;
    // shared inputs are immutable. Synchronous joins keep every stack context alive.
    unsafe impl ::std::marker::Send for SendJob {}
    impl SendJob {
        unsafe fn run(self) { (self.0.callback)(self.0.ctx); }
    }
    #[no_mangle]
    unsafe extern "C" fn pruv_g7_v1_run(jobs: *const Job, count: i64) {
        let result = ::std::panic::catch_unwind(::std::panic::AssertUnwindSafe(|| {
            GATE
            ::std::thread::scope(|scope| {
                let mut handles = ::std::vec::Vec::with_capacity(count as usize);
                let mut spawn_failed = false;
                for i in 0..count as usize {
                    SPAWN
                    let job = SendJob(*jobs.add(i));
                    match ::std::thread::Builder::new().spawn_scoped(scope, move || {
                        WAIT
                        PANIC
                        job.run();
                    }) {
                        ::std::result::Result::Ok(h) => handles.push(h),
                        ::std::result::Result::Err(_) => { spawn_failed = true; break; }
                    }
                }
                RELEASE
                let mut panicked = false;
                for h in handles {
                    if h.join().is_err() { panicked = true; }
                    JOINED
                }
                if spawn_failed {
                    ::std::eprintln!("pruv: parallel spawn failed");
                    ::std::process::exit(101);
                }
                if panicked { ::std::process::exit(101); }
            });
        }));
        if result.is_err() { ::std::process::exit(101); }
    }
}
'''.replace('GATE', gate).replace('WAIT', wait).replace('RELEASE', release).replace('SPAWN', spawn).replace('PANIC', panic).replace('JOINED', joined)
