// The Computer Language Benchmarks Game
// https://salsa.debian.org/benchmarksgame-team/benchmarksgame/
//
// contributed by the Rust Project Developers
// contributed by Cristi Cobzarenco
// contributed by TeXitoi
// contributed by Matt Brubeck
// contributed by Tianyi Shi

use std::{cmp::min, mem::replace};

const TABLE: [u8; 122] = *b"                                                                 \
   TVGH  CD  M KN   YSAABW R       TVGH  CD  M KN   YSAABW R";
// ABCDEFGHIJKLMNOPQRSTUVWXYZ      abcdefghijklmnopqrstuvwxyz

// Sequential reference algorithm; copy input once and return the complete FASTA.
pub fn bench(data: &[u8], _n: i64) -> Vec<u8> {
    let mut out = data.to_vec();
    let mut pos = 0;
    while pos < out.len() {
        let start = pos + out[pos..].iter().position(|&b| b == 10).unwrap() + 1;
        let end = start + out[start..].iter().position(|&b| b == 62).unwrap_or(out.len() - start);
        if start < end {
            reverse_complement(&mut out[start..end]);
        }
        pos = end;
    }
    out
}

/// Compute the reverse complement of one sequence.
fn reverse_complement(seq: &mut [u8]) {
    let len = seq.len() - 1;
    let seq = &mut seq[..len]; // Drop the last newline
    let trailing_len = len % LINE_LEN;
    let (left, right) = seq.split_at_mut(len / 2);
    reverse_complement_left_right(left, right, trailing_len);
}

/// Length of a normal line including the terminating \n.
const LINE_LEN: usize = 61;

/// Compute the reverse complement on chunks from opposite ends of a sequence.
///
/// `left` must start at the beginning of a line. If there are an odd number of
/// bytes, `right` will initially be 1 byte longer than `left`; otherwise they
/// will have equal lengths.
fn reverse_complement_left_right(mut left: &mut [u8], mut right: &mut [u8], trailing_len: usize) {
    // Each iteration swaps one line from the start of the sequence with one
    // from the end.
    while left.len() > 0 || right.len() > 0 {
        // Get the chunk up to the newline in `right`.
        let mut a = left.split_off_left(trailing_len);
        let mut b = right.split_off_right(trailing_len);
        right.split_off_right(1); // Skip the newline in `right`.

        // If we've reached the middle of the sequence here and there is an
        // odd number of bytes remaining, the odd one will be on the right.
        if b.len() > a.len() {
            let mid = b.split_off_left(1);
            mid[0] = TABLE[mid[0] as usize];
        }

        reverse_chunks(a, b);

        // Get the chunk up to the newline in `left`.
        let n = LINE_LEN - 1 - trailing_len;
        a = left.split_off_left(n);
        b = right.split_off_right(n);
        left.split_off_left(1); // Skip the newline in `left`.

        // If we've reached the middle of the sequence and there is an odd
        // number of bytes remaining, the odd one will now be on the left.
        if a.len() > b.len() {
            let mid = a.split_off_right(1);
            mid[0] = TABLE[mid[0] as usize]
        }

        reverse_chunks(a, b);
    }
}

/// Compute the reverse complement for two contiguous chunks without line breaks.
fn reverse_chunks(left: &mut [u8], right: &mut [u8]) {
    for (x, y) in left.iter_mut().zip(right.iter_mut().rev()) {
        *y = TABLE[replace(x, TABLE[*y as usize]) as usize];
    }
}

/// Utilities for splitting chunks off of slices.
trait SplitOff {
    fn split_off_left(&mut self, n: usize) -> Self;
    fn split_off_right(&mut self, n: usize) -> Self;
}
impl<'a, T> SplitOff for &'a mut [T] {
    /// Split the left `n` items from self and return them as a separate slice.
    fn split_off_left(&mut self, n: usize) -> Self {
        let n = min(self.len(), n);
        let data = replace(self, &mut []);
        let (left, data) = data.split_at_mut(n);
        *self = data;
        left
    }
    /// Split the right `n` items from self and return them as a separate slice.
    fn split_off_right(&mut self, n: usize) -> Self {
        let len = self.len();
        let n = min(len, n);
        let data = replace(self, &mut []);
        let (data, right) = data.split_at_mut(len - n);
        *self = data;
        right
    }
}
