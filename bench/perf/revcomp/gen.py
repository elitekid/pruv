#!/usr/bin/env python3
"""Exact fasta_reference.rs output: f32 thresholds, periodic integer LCG."""
import math
import struct
import sys

IM = 139968
ALU = (b"GGCCGGGCGCGGTGGCTCACGCCTGTAATCCCAGCACTTTGG"
       b"GAGGCCGAGGCGGGCGGATCACCTGAGGTCAGGAGTTCGAGA"
       b"CCAGCCTGGCCAACATGGTGAAACCCCGTCTCTACTAAAAAT"
       b"ACAAAAATTAGCCGGGCGTGGTGGCGCGCGCCTGTAATCCCA"
       b"GCTACTCGGGAGGCTGAGGCAGGAGAATCGCTTGAACCCGGG"
       b"AGGCGGAGGTTGCAGTGAGCCGAGATCGCGCCACTGCACTCC"
       b"AGCCTGGGCGACAGAGCGAGACTCCGTCTCAAAAA")
IUB = list(zip(b"acgtBDHKMNRSVWY", [.27, .12, .12, .27] + [.02] * 11))
HOMO = list(zip(b"acgt", [.3029549426680, .1979883004921,
                         .1975473066391, .3015094502008]))


def f32(x):
    return struct.unpack("f", struct.pack("f", x))[0]


def random_period(seed, probabilities):
    cumulative = 0.0
    thresholds = []
    for ch, probability in probabilities:
        cumulative = f32(cumulative + f32(probability))
        thresholds.append((int(f32(cumulative * f32(IM))), ch))
    out = bytearray()
    state = seed
    for _ in range(IM):
        state = (state * 3877 + 29573) % IM
        out.append(next(ch for threshold, ch in thresholds if threshold >= state))
    assert state == seed
    return bytes(out)


def write_sequence(out, header, period, count):
    out.write(header)
    # A whole block preserves both the LCG period and the 60-column phase.
    size = math.lcm(len(period), 60)
    raw = period * (size // len(period))
    block = b"".join(raw[i:i+60] + b"\n" for i in range(0, size, 60))
    whole, tail = divmod(count, size)
    for _ in range(whole):
        out.write(block)
    for i in range(0, tail, 60):
        out.write(raw[i:min(i + 60, tail)] + b"\n")


def generate(n, path):
    seed = 42
    iub = random_period(seed, IUB)
    for _ in range((3 * n) % IM):
        seed = (seed * 3877 + 29573) % IM
    homo = random_period(seed, HOMO)
    with open(path, "wb") as out:
        write_sequence(out, b">ONE Homo sapiens alu\n", ALU, 2 * n)
        write_sequence(out, b">TWO IUB ambiguity codes\n", iub, 3 * n)
        write_sequence(out, b">THREE Homo sapiens frequency\n", homo, 5 * n)


if __name__ == "__main__":
    mode, path = sys.argv[1:]
    generate({"dev": 250000, "full": 25000000}[mode], path)
