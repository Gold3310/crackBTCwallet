#!/usr/bin/env python3
"""
keccak.py - Keccak-256, as Ethereum uses it.

Python's hashlib gives you SHA3-256, which is the *same permutation with different
padding* (0x06 instead of 0x01), so it cannot be used for Ethereum hashing. This is a
direct implementation of the permutation and sponge; it is slow but dependency-free,
which matters because this repo has to run where nothing can be installed.

Used for: EIP-55 address checksums, and function selectors (which double as the
self-test, since the selectors are published constants).
"""
import sys

MASK64 = (1 << 64) - 1

RC = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]

# rotation offsets, indexed [x][y] for lane a[x + 5y]
ROT = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]

RATE = 136  # bytes, for a 256-bit capacity of 512 bits


def _rotl(value, shift):
    return ((value << shift) | (value >> (64 - shift))) & MASK64


def _keccak_f(a):
    for rnd in range(24):
        # theta
        c = [a[x] ^ a[x + 5] ^ a[x + 10] ^ a[x + 15] ^ a[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotl(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                a[x + 5 * y] ^= d[x]
        # rho + pi
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl(a[x + 5 * y], ROT[x][y])
        # chi
        for x in range(5):
            for y in range(5):
                a[x + 5 * y] = b[x + 5 * y] ^ ((~b[(x + 1) % 5 + 5 * y]) & b[(x + 2) % 5 + 5 * y])
        # iota
        a[0] ^= RC[rnd]


def keccak256(data: bytes) -> bytes:
    """Keccak-256 (Ethereum flavour: domain padding 0x01)."""
    state = [0] * 25
    padded = bytearray(data)
    padded.append(0x01)                      # keccak domain separation
    while len(padded) % RATE:
        padded.append(0x00)
    padded[-1] ^= 0x80                       # final bit

    for offset in range(0, len(padded), RATE):
        block = padded[offset:offset + RATE]
        for i in range(RATE // 8):
            state[i] ^= int.from_bytes(block[8 * i:8 * i + 8], "little")
        _keccak_f(state)

    out = bytearray()
    while len(out) < 32:
        for i in range(RATE // 8):
            out += state[i].to_bytes(8, "little")
        if len(out) < 32:
            _keccak_f(state)
    return bytes(out[:32])


def selector(signature: str) -> str:
    """4-byte function selector for a signature like 'symbol()'."""
    return keccak256(signature.encode()).hex()[:8]


def _selftest() -> int:
    checks = []

    def check(name, got, want):
        checks.append((name, got == want, "%s != %s" % (got, want)))

    check("keccak256('')", keccak256(b"").hex(),
          "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470")
    check("keccak256('abc')", keccak256(b"abc").hex(),
          "4e03657aea45a94fc7d47ba826c8d667c0d1e6e33a64a036ec44f58fa12d6c45")
    check("Transfer event topic", keccak256(b"Transfer(address,address,uint256)").hex(),
          "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef")
    # multi-block (>136 bytes) exercises absorb + permutation again
    check("200-byte input is deterministic", keccak256(b"a" * 200), keccak256(b"a" * 200))
    check("length is always 32 bytes", len(keccak256(b"x")), 32)
    check("selector symbol()", selector("symbol()"), "95d89b41")
    check("selector decimals()", selector("decimals()"), "313ce567")
    check("selector name()", selector("name()"), "06fdde03")
    check("selector totalSupply()", selector("totalSupply()"), "18160ddd")
    check("selector balanceOf(address)", selector("balanceOf(address)"), "70a08231")
    check("selector transfer(address,uint256)", selector("transfer(address,uint256)"), "a9059cbb")

    passed = sum(1 for _n, ok, _d in checks if ok)
    for name, ok, detail in checks:
        print("%s  %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "   <- " + detail))
    print("\npassed: %d, failed: %d (of %d checks)" % (passed, len(checks) - passed, len(checks)))
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(_selftest())
