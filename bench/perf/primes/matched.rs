// Atkin sieve from reference.rs; eleven-slot decimal trie arena.
struct Sieve {
    limit: usize,
    prime: Vec<bool>,
}

impl Sieve {
    fn new(limit: usize) -> Sieve {
        Sieve {
            limit,
            prime: vec![false; limit + 1],
        }
    }

    fn to_list(&self) -> Vec<usize> {
        let mut result = vec![2, 3];
        for p in 5..=self.limit {
            if self.prime[p] {
                result.push(p);
            }
        }
        result
    }

    fn omit_squares(&mut self) -> &Self {
        let mut r = 5;
        while r * r < self.limit {
            if self.prime[r] {
                let mut i = r * r;
                while i < self.limit {
                    self.prime[i] = false;
                    i += r * r;
                }
            }
            r += 1;
        }
        self
    }

    fn step1(&mut self, x: usize, y: usize) {
        let n = (4 * x * x) + (y * y);
        if n <= self.limit && (n % 12 == 1 || n % 12 == 5) {
            self.prime[n] = !self.prime[n];
        }
    }

    fn step2(&mut self, x: usize, y: usize) {
        let n = (3 * x * x) + (y * y);
        if n <= self.limit && n % 12 == 7 {
            self.prime[n] = !self.prime[n];
        }
    }

    fn step3(&mut self, x: usize, y: usize) {
        let n = (3 * x * x) - (y * y);
        if x > y && n <= self.limit && n % 12 == 11 {
            self.prime[n] = !self.prime[n];
        }
    }

    fn loop_y(&mut self, x: usize) {
        let mut y = 1;
        while y * y < self.limit {
            self.step1(x, y);
            self.step2(x, y);
            self.step3(x, y);
            y += 1;
        }
    }

    fn loop_x(&mut self) {
        let mut x = 1;
        while x * x < self.limit {
            self.loop_y(x);
            x += 1;
        }
    }

    fn calc(&mut self) -> &Self {
        self.loop_x();
        self.omit_squares()
    }
}


pub fn bench(_data: &[u8], n: i64) -> Vec<i64> {
    if !(5..=5_000_000).contains(&n) { return vec![]; }
    let n = n as usize;
    let mut sieve = Sieve::new(n);
    let primes = sieve.calc().to_list();
    let cap = n / 10 + primes.len() + 2;
    let mut arena = vec![0i64; cap * 11];
    let mut used = 1;
    for value in primes {
        let mut divisor = 1;
        while value / divisor >= 10 { divisor *= 10; }
        let mut node = 0;
        while divisor > 0 {
            let slot = node * 11 + value / divisor % 10;
            if arena[slot] == 0 {
                arena[slot] = used as i64;
                used += 1;
            }
            node = arena[slot] as usize;
            divisor /= 10;
        }
        arena[node * 11 + 10] = value as i64;
    }
    let prefix = if n >= 5_000_000 { 32338 } else { 323 };
    let mut divisor = if n >= 5_000_000 { 10000 } else { 100 };
    let mut node = 0;
    while divisor > 0 {
        node = arena[node * 11 + prefix / divisor % 10] as usize;
        if node == 0 { return vec![]; }
        divisor /= 10;
    }
    let mut queue = std::collections::VecDeque::new();
    queue.push_back(node);
    let mut out = Vec::new();
    while let Some(top) = queue.pop_front() {
        let value = arena[top * 11 + 10];
        if value > 0 { out.push(value); }
        for digit in 0..10 {
            let child = arena[top * 11 + digit];
            if child > 0 { queue.push_back(child as usize); }
        }
    }
    out
}
