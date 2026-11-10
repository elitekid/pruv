# tests/abi — Windows x64 외부 wrapper(sret) 표본

## 목적
`docs/M3_C4_SPEC.md` 7절: Windows x64 에서는 16바이트 Option/Result 반환을 `{i64,i64}` 값 반환이 아니라
`void` + 첫 숨은 `ptr sret({i64,i64}) align 8` 로 **처음부터** 출력해야 한다. 이 폴더는 그 기대 IR 표본과,
이 맥에서 가능한 검사(교차 COFF 객체화, verify, 기호, C 기준 서명 비교)를 둔다.
이름·인자 순서는 `pruvc/llvmgen.py` `abi_of`(1214~1285줄)를 따르고 반환만 바꿨다.

## 실행
```
.venv/bin/python tests/abi/check_abi.py [--ir-tool PATH]     # 환경변수 PRUV_IR_TOOL 도 가능
```
- `--ir-tool` 이 있으면 `PATH obj IN.ll -o OUT.o --target x86_64-pc-windows-msvc`(받은 IR 을 그대로 객체화),
  없으면 `llc -mtriple=x86_64-pc-windows-msvc -filetype=obj -O2`.
- 주의: Python 판(legacy) IR 의 Windows 객체화는 지원하지 않는다(Option/Result 를 `{i64,i64}` 값으로 반환해 MSVC ABI 와 어긋남). `abi_lower` 검사는 2026-11-11 제거. Windows 대상 IR 은 Rust 판 `pruvc --target` 으로 만든다.
- 도구는 `/opt/homebrew/opt/llvm@22/bin` 우선, 없으면 PATH.
- 하나라도 실패하면 exit 1. 마지막 줄은 항상 `Windows 실행 ABI 는 이 맥에서 확인 불가: Windows CI 필요`.

## 표본이 확인하는 경계
| 파일 | 경계 |
|---|---|
| `win_x64/opt_ret.ll` | Option 반환: void + 첫 숨은 sret align 8, tag zext + payload 저장, Some/None 두 경로 |
| `win_x64/res_ret.ll` | Result 반환(ok/err), 같은 sret 모양 |
| `win_x64/args_0_1_5.ll` | 인자 0/1/5개 + sret. sret 가 RCX 를 차지하므로 사용자 인자 3개까지 레지스터, 이후 스택 |
| `win_x64/arr_ret.ll` | 배열 반환: 마지막 out 포인터 + void, sret 없음 |
| `win_x64/struct_opt.ll` | 사용자 구조체(Option 필드 포함): word 배열 포인터 인자/마지막 out 포인터, sret 없음 |
| `win_x64/ref.c` | clang 이 C 의 2×int64 반환을 어떻게 하강하는지 기준(declare 와 define 서명) |
| `win_x64/rust_extern.rs` | Windows CI 에서 실행할 Rust extern 호출 드라이버 |

## Windows CI 에서 할 일 (이 맥에서는 불가)
1. 표본·실제 생성 IR 을 객체화해 MSVC 링커로 `rust_extern.rs` 및 C 호출자와 링크, 실행.
2. 네이티브 실행: Some/None, Ok/Err, i64 MIN/MAX, 인자 0·1·5개, 반복 호출(10만 회 이상),
   구조체 내부 Option, 배열 반환.
3. cl/clang-cl 이 만든 2×int64 반환 IR 과 우리 서명 비교(이 폴더 check_abi.py 도 CI 에서 함께 실행).

## core/abi.rs 이식 계획 (초안)
```rust
pub enum Target { MacArm64, MacX64, LinuxX64, WinX64 }

pub enum RetPlan {
    Void,
    Scalar,            // i64 / bool(zext)
    TaggedRegs,        // { i64, i64 } 값 반환 (macOS, Linux x64)
    TaggedSret,        // void + 첫 숨은 ptr sret({i64,i64}) align 8 (Windows x64)
    OutPtr,            // 마지막 명시 out 포인터 + void (배열, 사용자 타입)
}

pub enum ParamPlan { Scalar, Bool, Array /* ptr,n */, Tagged /* tag,v */, UserWords /* ptr */ }

pub struct AbiPlan { pub name: String, pub params: Vec<ParamPlan>, pub ret: RetPlan }

pub fn plan_abi(f: &FnSig, target: Target) -> AbiPlan;
pub fn emit_wrapper(plan: &AbiPlan, f: &FnSig, tt: &TypeTable, out: &mut String);
```
- `plan_abi` 는 Option/Result 반환만 target 으로 갈라 `TaggedRegs`/`TaggedSret` 선택, 나머지는 target 무관.
- `emit_wrapper` 는 entry 호출 후 `{i1,i64}` 를 tag zext 두 i64 로 만든다. `TaggedSret` 는 sret 포인터의 두 슬롯에 저장하고 `ret void`.
- 선언·정의·IR call site 의 sret 속성을 같은 plan 에서 만들어 일치시킨다.

## 확인 안 된 가정
이 표본들은 작성만 했고 실행해 보지 못했다(셸 없음). LLVM 22 문법·datalayout 문자열,
clang 이 내는 sret 속성 모양, Result 의 tag 의미는 첫 실행 때 확인해야 한다.
