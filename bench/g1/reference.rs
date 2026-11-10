// Trusted reference implementations for the G1 problems (same type names and shapes as the Vow declarations,
// so Debug output of results is comparable with the generated `sol` module).
#![allow(dead_code)]

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Point { pub x: i64, pub y: i64 }
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Rect { pub lo: Point, pub hi: Point }

pub fn overlap_area(a: Rect, b: Rect) -> i64 {
    let w = a.hi.x.min(b.hi.x) - a.lo.x.max(b.lo.x);
    let h = a.hi.y.min(b.hi.y) - a.lo.y.max(b.lo.y);
    if w <= 0 || h <= 0 { 0 } else { w * h }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Acc { pub value: i64, pub steps: i64 }
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Op { Add(i64), Mul(i64), Neg, Clear }

pub fn apply(acc: Acc, op: Op) -> Acc {
    let value = match op {
        Op::Add(v) => acc.value + v,
        Op::Mul(v) => acc.value * v,
        Op::Neg => -acc.value,
        Op::Clear => 0,
    };
    Acc { value, steps: acc.steps + 1 }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Stats { pub count: i64, pub sum: i64, pub min: Option<i64>, pub max: Option<i64> }

pub fn stats(a: &[i64]) -> Stats {
    Stats {
        count: a.len() as i64,
        sum: a.iter().sum(),
        min: a.iter().copied().min(),
        max: a.iter().copied().max(),
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Measure { pub area: i64, pub perimeter: i64 }
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Shape { Circle(i64), Rect(i64, i64), Tri(i64, i64, i64, i64) }

pub fn measure(s: Shape) -> Measure {
    match s {
        Shape::Circle(r) => Measure { area: 3 * r * r, perimeter: 6 * r },
        Shape::Rect(w, h) => Measure { area: w * h, perimeter: 2 * (w + h) },
        Shape::Tri(a, b, c, h) => Measure { area: c * h / 2, perimeter: a + b + c },
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Found { Nothing, At(i64, i64) }

pub fn first_negative(a: &[i64]) -> Found {
    match a.iter().position(|&v| v < 0) {
        Some(i) => Found::At(i as i64, a[i]),
        None => Found::Nothing,
    }
}
