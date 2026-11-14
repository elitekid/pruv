// kostya bf.rs with the program held the way the Pruv port holds it: one opcode per command in a flat array with
// paired bracket targets, instead of a tree of boxed slices (Pruv has no arrays of enum values). Cells are the
// reference's wrapping i32; the checksum is widened to i64 like Pruv's overflow-free arithmetic.
pub fn bench(data: &[u8], _n: i64) -> Vec<i64> {
    let mut ops: Vec<u8> = Vec::new();
    let mut jumps: Vec<usize> = Vec::new();
    let mut stack: Vec<usize> = Vec::new();
    for &c in data {
        let code = match c {
            b'+' => 0,
            b'-' => 1,
            b'<' => 2,
            b'>' => 3,
            b'.' => 4,
            b'[' => 5,
            b']' => 6,
            _ => continue,
        };
        let k = ops.len();
        ops.push(code);
        jumps.push(0);
        if code == 5 {
            stack.push(k);
        }
        if code == 6 {
            let s = stack.pop().unwrap();
            jumps[s] = k;
            jumps[k] = s;
        }
    }
    let mut tape: Vec<i32> = vec![0];
    let (mut pos, mut pc) = (0usize, 0usize);
    let (mut sum1, mut sum2, mut out_len) = (0i64, 0i64, 0i64);
    while pc < ops.len() {
        match ops[pc] {
            0 => tape[pos] = tape[pos].wrapping_add(1),
            1 => tape[pos] = tape[pos].wrapping_sub(1),
            2 => pos -= 1,
            3 => {
                pos += 1;
                if pos >= tape.len() {
                    tape.resize(pos * 2, 0);
                }
            }
            4 => {
                sum1 = (sum1 + tape[pos] as i64) % 255;
                sum2 = (sum2 + sum1) % 255;
                out_len += 1;
            }
            5 => {
                if tape[pos] <= 0 {
                    pc = jumps[pc];
                }
            }
            _ => {
                if tape[pos] > 0 {
                    pc = jumps[pc];
                }
            }
        }
        pc += 1;
    }
    vec![if sum1 < 0 { sum1 } else { (sum2 << 8) | sum1 }, out_len]
}
