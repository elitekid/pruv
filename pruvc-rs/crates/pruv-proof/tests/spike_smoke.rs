//! 형식 스모크: 판정 값은 단언하지 않는다(z3 버전·시간에 좌우). 구조와 순서 규칙만 확인한다.

use pruv_proof::samples::{run_sample, sample_names};
use serde_json::Value;

#[test]
fn every_sample_has_well_formed_trace() {
    for name in sample_names() {
        let v = run_sample(name).expect("sample");
        assert_eq!(v["sample"], name);
        assert!(v["z3_version"].as_str().is_some_and(|s| !s.is_empty()));
        let obs = v["obligations"].as_array().expect("obligations");
        assert!(!obs.is_empty(), "{name}: no obligations");
        for (i, o) in obs.iter().enumerate() {
            assert_eq!(o["seq"], (i + 1) as u64);
            assert!(o["fn"].as_str().is_some());
            assert!(o["line"].as_u64().is_some() && o["col"].as_u64().is_some());
            assert!(o["code"].as_str().is_some());
            let attempts = o["attempts"].as_array().expect("attempts");
            assert!(matches!(attempts.len(), 1 | 2), "{name}: attempts {}", attempts.len());
            // 첫 시도는 lemmas=false, 둘째가 있으면 lemmas=true
            assert_eq!(attempts[0]["lemmas"], Value::Bool(false));
            if attempts.len() == 2 {
                assert_eq!(attempts[1]["lemmas"], Value::Bool(true));
                assert_ne!(attempts[0]["result"], "unsat", "unsat 뒤에는 재시도하지 않는다");
            }
            for a in attempts {
                assert!(a["smt2"].as_str().unwrap().starts_with("(set-option :timeout 8000)\n"));
                assert!(matches!(a["result"].as_str().unwrap(), "sat" | "unsat" | "unknown"));
            }
        }
    }
}
