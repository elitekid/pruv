// Sequential fannkuch-redux (Benchmarks Game), same algorithm as reference.rs without rayon.
// Result: [checksum, maxflips].

pub fn bench(_data: &[u8], n: i64) -> Vec<i64> {
    let n = n as usize;
    let mut factorials = [1i64; 16];
    for i in 1..=n {
        factorials[i] = factorials[i - 1] * i as i64;
    }
    let perm_max = factorials[n];

    let mut count = [0i64; 16];
    let mut temp = [0i64; 16];
    let mut current = [0i64; 16];
    for (i, v) in current.iter_mut().enumerate() {
        *v = i as i64;
    }

    let mut checksum: i64 = 0;
    let mut maxflips: i64 = 0;
    let mut permutation_index: i64 = 0;
    loop {
        if current[0] > 0 {
            temp.copy_from_slice(&current);
            let mut flip_count: i64 = 1;
            let mut first_value = current[0] as usize;
            while temp[first_value] != 0 {
                let new_first_value = std::mem::replace(&mut temp[first_value], first_value as i64);
                if first_value > 2 {
                    temp[1..first_value].reverse();
                }
                first_value = new_first_value as usize;
                flip_count += 1;
            }
            checksum += if permutation_index % 2 == 0 { flip_count } else { -flip_count };
            if flip_count > maxflips {
                maxflips = flip_count;
            }
        }

        if permutation_index >= perm_max - 1 {
            return vec![checksum, maxflips];
        }
        permutation_index += 1;

        let mut first_value = current[1];
        current[1] = current[0];
        current[0] = first_value;
        let mut i = 1usize;
        while count[i] >= i as i64 {
            count[i] = 0;
            i += 1;
            let new_first_value = current[1];
            current[0] = new_first_value;
            for j in 1..i {
                current[j] = current[j + 1];
            }
            current[i] = std::mem::replace(&mut first_value, new_first_value);
        }
        count[i] += 1;
    }
}
