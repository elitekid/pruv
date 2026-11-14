struct Sudoku {
	r: [[u16; 9]; 324],
	c: [[u16; 4]; 729]
}

impl Sudoku {
	pub fn new() -> Sudoku {
		let mut s = Sudoku { r: [[0u16; 9]; 324], c: [[0u16; 4]; 729] };
		let mut nr = [0; 324];
		let mut r = 0;
		for i in 0..9 {
			for j in 0..9 {
				for k in 0..9 {
					s.c[r][0] = 9 * i + j;
					s.c[r][1] = (i/3*3 + j/3) * 9 + k + 81;
					s.c[r][2] = 9 * i + k + 162;
					s.c[r][3] = 9 * j + k + 243;
					r += 1;
				}
			}
		}
		for r in 0..729 {
			for c2 in 0..4 {
				let k = s.c[r][c2] as usize;
				s.r[k][nr[k]] = r as u16;
				nr[k] += 1;
			}
		}
		return s;
	}
	#[inline(always)]
	fn forward(&self, sr: &mut [i8], sc: &mut [u8], c: u16, min: &mut u8, min_c: &mut u16) {
		for rr in self.r[c as usize] {
			let srrr = &mut sr[rr as usize];
			*srrr += 1;
			if *srrr == 1 {
				for cc in self.c[rr as usize] {
					let sccc = &mut sc[cc as usize];
					*sccc = sccc.wrapping_sub(1);
					if *sccc < *min {
						*min = *sccc;
						*min_c = cc;
					}
				}
			}
		}
	}
	#[inline(always)]
	fn revert(&self, sr: &mut [i8], sc: &mut [u8], c: u16) {
		for rr in self.r[c as usize] {
			let srrr = &mut sr[rr as usize];
			*srrr -= 1;
			if *srrr == 0 {
				for i in self.c[rr as usize] {
					sc[i as usize] += 1;
				}
			}
		}
	}
	#[inline(always)]
	fn update(&self, sr: &mut [i8], sc: &mut [u8], r: u16, v: i32) -> i32 {
		let mut min = 10;
		let mut min_c = 0;
		for i in self.c[r as usize] {
			sc[i as usize] = sc[i as usize].wrapping_add((v<<7) as u8);
		}
		for c in self.c[r as usize] {
			if v > 0 {
				self.forward(sr, sc, c, &mut min, &mut min_c);
			} else {
				self.revert(sr, sc, c);
			}
		}
		return (min as i32)<<16 | min_c as i32;
	}
	pub fn solve(&self, inp: &[u8]) -> (i64, i64) {
        let mut count = 0;
        let mut checksum = 0;
		let mut sc = [9u8; 324];
		let mut sr = [0i8; 729];
		let mut cr = [-1i8; 81];
		let mut cc = [-1i16; 81];
		let mut s = [-1i8; 81];
		let mut s8 = [48u8; 81];
		let mut hints = 0;
		for i in 0..81 {
			let c = inp[i] as i8;
			if c >= '1' as i8 && c <= '9' as i8 {
				s[i] = c - '1' as i8;
				self.update(&mut sr, &mut sc, (i * 9 + s[i] as usize) as u16, 1);
				hints += 1;
				s8[i] = c as u8;
			}
		}
		let mut i = 0i32;
		let mut dir = 1;
		let mut cand: i32 = 10<<16|0;
		loop {
			while i >= 0 && i < 81 - hints {
				if dir == 1 {
					let mut min = (cand>>16) as u8;
					cc[i as usize] = (cand & 0xffff) as i16;
					if min > 1 {
						for c in 0..324 {
							if sc[c] < min {
								min = sc[c];
								cc[i as usize] = c as i16;
								if min <= 1 {
									break;
								}
							}
						}
					}
					if min == 0 || min == 10 {
						cr[i as usize] = -1;
						i -= 1;
						dir = -1;
					}
				}
				if i < 0 { break; }
                let c = cc[i as usize] as usize;
				if dir == -1 && cr[i as usize] >= 0 {
					self.update(&mut sr, &mut sc, self.r[c][cr[i as usize] as usize], -1);
				}
				let mut r2 = (cr[i as usize] as usize) + 1;
				while r2 < 9 && sr[self.r[c][r2] as usize] != 0 {
					r2 += 1;
				}
				if r2 < 9 {
					cand = self.update(&mut sr, &mut sc, self.r[c][r2], 1);
					cr[i as usize] = r2 as i8;
					i += 1;
					dir = 1;
				} else {
					cr[i as usize] = -1;
					i -= 1;
					dir = -1;
				}
			}
			if i < 0 {
				break;
			}
			for j in 0 .. (i as usize) {
				let r = self.r[cc[j] as usize][cr[j] as usize];
				s8[(r/9) as usize] = (r%9 + '1' as u16) as u8;
			}
			count += 1;
            checksum += s8.iter().enumerate().map(|(p, &d)| (d - 48) as i64 * (p as i64 + 1)).sum::<i64>();
			i -= 1; dir = -1;
		}
        (count, checksum)
	}
}


pub fn bench(data: &[u8], n: i64) -> Vec<i64> {
    let sudoku = Sudoku::new();
    let mut total = [0i64; 2];
    for _ in 0..n {
        for puzzle in data.split(|&b| b == 10).filter(|p| p.len() == 81) {
            let (count, checksum) = sudoku.solve(puzzle);
            total[0] += count;
            total[1] += checksum;
        }
    }
    total.to_vec()
}
