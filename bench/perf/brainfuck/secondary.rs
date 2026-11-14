// kostya bf.rs as published (tree of boxed slices), single-threaded, QUIET; secondary baseline.
enum Op {
    Dec,
    Inc,
    Prev,
    Next,
    Print,
    Loop(Box<[Op]>),
}

struct Tape {
    pos: usize,
    tape: Vec<i32>,
}

impl Tape {
    fn new() -> Self {
        Self {
            pos: 0,
            tape: vec![0],
        }
    }

    fn current_cell(&self) -> i32 {
        // SAFETY: `self.pos` is already checked in `self.next()`.
        unsafe { *self.tape.get_unchecked(self.pos) }
    }

    fn inc(&mut self, x: i32) {
        // SAFETY: `self.pos` is already checked in `self.next()`.
        unsafe {
            let cell = self.tape.get_unchecked_mut(self.pos);
            *cell = cell.wrapping_add(x);
        }
    }

    fn prev(&mut self) {
        self.pos -= 1;
    }

    fn next(&mut self) {
        self.pos += 1;
        if self.pos >= self.tape.len() {
            self.tape.resize(self.pos * 2, 0);
        }
    }
}

struct Printer {
    sum1: i32,
    sum2: i32,
    out_len: i64,
}

impl Printer {
    fn print(&mut self, n: i32) {
        // Widen the addition to match Pruv's overflow-free i64 arithmetic.
        self.sum1 = ((self.sum1 as i64 + n as i64) % 255) as i32;
        self.sum2 = (self.sum2 + self.sum1) % 255;
        self.out_len += 1;
    }
}
fn run(program: &[Op], tape: &mut Tape, printer: &mut Printer) {
    for op in program {
        match op {
            Op::Dec => tape.inc(-1),
            Op::Inc => tape.inc(1),
            Op::Prev => tape.prev(),
            Op::Next => tape.next(),
            Op::Print => printer.print(tape.current_cell()),
            Op::Loop(program) => {
                while tape.current_cell() > 0 {
                    run(program, tape, printer);
                }
            }
        }
    }
}

fn parse(iter: &mut impl Iterator<Item = u8>) -> Box<[Op]> {
    let mut buf = vec![];
    while let Some(byte) = iter.next() {
        buf.push(match byte {
            b'-' => Op::Dec,
            b'+' => Op::Inc,
            b'<' => Op::Prev,
            b'>' => Op::Next,
            b'.' => Op::Print,
            b'[' => Op::Loop(parse(iter)),
            b']' => break,
            _ => continue,
        });
    }
    buf.into_boxed_slice()
}

struct Program {
    ops: Box<[Op]>,
}

impl Program {
    fn new(code: impl IntoIterator<Item = u8>) -> Self {
        Self {
            ops: parse(&mut code.into_iter()),
        }
    }

    fn run(&self, printer: &mut Printer) {
        let mut tape = Tape::new();
        run(&self.ops, &mut tape, printer);
    }
}

pub fn bench(data: &[u8], _n: i64) -> Vec<i64> {
    let mut printer = Printer {
        sum1: 0,
        sum2: 0,
        out_len: 0,
    };
    Program::new(data.iter().copied()).run(&mut printer);
    vec![
        ((printer.sum2 << 8) | printer.sum1) as i64,
        printer.out_len,
    ]
}
