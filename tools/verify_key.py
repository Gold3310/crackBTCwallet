#!/usr/bin/env python3
"""
verify_key.py - prove that a recovered key really belongs to a wallet.

`crackbtcshell` reports "Posible Key found" as soon as the decrypted ckey ends in
sixteen 0x10 bytes (the AES-CBC padding). That check CANNOT tell you the key is
correct: with AES-256-CBC, a wrong IV only corrupts the FIRST plaintext block, so
the padding in the last block still validates. A wrong key material would corrupt
every block, but a wrong IV silently corrupts the first 16 bytes of a 32-byte
private key while the tool still says "found".

This script closes that gap. It takes the private key you recovered, derives the
Bitcoin address(es) from it, and compares them with the address that belongs to
the wallet you are testing. If they match, the key is genuinely right.

Pure Python 3 standard library - no pip install, no OpenSSL bindings.

Examples
--------
    # derive addresses from a private key
    python3 verify_key.py --privkey 3ea5eaabe7f7b997ce732acc9cf08315a805109003ce2bd918bac1b73b82d7b7

    # assert the key belongs to a known wallet address (exit 0 = match)
    python3 verify_key.py --privkey 3ea5... --address 1FfmbHfnpaZjKFvyi1okTjJJusN455paPH

    # decode a WIF back to an address (sanity-check either WIF the tool printed)
    python3 verify_key.py --wif KyKVQiQTML68gzEEce7HsEK9S4j4XqyZWQ6GdaGrSSk8XZJHqNWe

    # derive the IV crackbtcshell wants, from a key id
    python3 verify_key.py --iv-from 0382ca08ce78b0935099c74db12873a7dc1cba10a44165ce8cc1d0602f49ee97f5
"""

import argparse
import hashlib
import sys

# --------------------------------------------------------------------------- #
# Base58Check
# --------------------------------------------------------------------------- #

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
VERSION_MAINNET_P2PKH = 0x00
VERSION_MAINNET_WIF = 0x80
VERSION_TESTNET_P2PKH = 0x6F
VERSION_TESTNET_WIF = 0xEF


def b58encode(payload: bytes) -> str:
    number = int.from_bytes(payload, "big")
    out = ""
    while number:
        number, rem = divmod(number, 58)
        out = ALPHABET[rem] + out
    pad = len(payload) - len(payload.lstrip(b"\x00"))
    return "1" * pad + out


def b58decode(text: str) -> bytes:
    number = 0
    for char in text:
        number = number * 58 + ALPHABET.index(char)
    body = number.to_bytes((number.bit_length() + 7) // 8, "big")
    pad = len(text) - len(text.lstrip("1"))
    return b"\x00" * pad + body


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def base58check(payload: bytes) -> str:
    return b58encode(payload + sha256d(payload)[:4])


def base58check_decode(text: str, expected_version=None) -> bytes:
    raw = b58decode(text)
    payload, checksum = raw[:-4], raw[-4:]
    if sha256d(payload)[:4] != checksum:
        raise ValueError("bad Base58Check checksum - is this a typo?")
    if expected_version is not None and payload[0] != expected_version:
        raise ValueError(f"unexpected version byte 0x{payload[0]:02x}")
    return payload


# --------------------------------------------------------------------------- #
# secp256k1 (decompress-free: we only need scalar multiplication of G)
# --------------------------------------------------------------------------- #

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    (x1, y1), (x2, y2) = p1, p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1) * pow(2 * y1, P - 2, P) % P
    else:
        lam = (y2 - y1) * pow(x2 - x1, P - 2, P) % P
    x3 = (lam * lam - x1 - x2) % P
    return x3, (lam * (x1 - x3) - y1) % P


def point_mul(scalar: int):
    result, addend = None, (GX, GY)
    while scalar:
        if scalar & 1:
            result = point_add(result, addend)
        addend = point_add(addend, addend)
        scalar >>= 1
    return result


def pubkey(privkey: bytes, compressed: bool) -> bytes:
    scalar = int.from_bytes(privkey, "big")
    if not 0 < scalar < N:
        raise ValueError("private key is outside the secp256k1 range")
    x, y = point_mul(scalar)
    if compressed:
        return bytes([2 + (y & 1)]) + x.to_bytes(32, "big")
    return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


def address_from_privkey(privkey: bytes, compressed: bool, testnet: bool = False) -> str:
    ripemd = hashlib.new("ripemd160")
    ripemd.update(hashlib.sha256(pubkey(privkey, compressed)).digest())
    version = VERSION_TESTNET_P2PKH if testnet else VERSION_MAINNET_P2PKH
    return base58check(bytes([version]) + ripemd.digest())


def wif_from_privkey(privkey: bytes, compressed: bool, testnet: bool = False) -> str:
    version = VERSION_TESTNET_WIF if testnet else VERSION_MAINNET_WIF
    payload = bytes([version]) + privkey + (b"\x01" if compressed else b"")
    return base58check(payload)


def hash160(data: bytes) -> bytes:
    return hashlib.new("ripemd160", hashlib.sha256(data).digest()).digest()


def privkey_from_wif(text: str):
    payload = base58check_decode(text)
    testnet = payload[0] == VERSION_TESTNET_WIF
    if payload[0] not in (VERSION_MAINNET_WIF, VERSION_TESTNET_WIF):
        raise ValueError("not a WIF (unexpected version byte)")
    body = payload[1:]
    compressed = len(body) == 33 and body[-1] == 0x01
    privkey = body[:32] if compressed else body
    if len(privkey) != 32:
        raise ValueError("malformed WIF length")
    return privkey, compressed, testnet


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Verify that a recovered Bitcoin private key belongs to a wallet.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--privkey", help="32-byte private key, hex")
    ap.add_argument("--wif", help="WIF to decode instead of --privkey")
    ap.add_argument("--address", help="expected address; exit code 0 if it matches either form")
    ap.add_argument("--testnet", action="store_true", help="derive testnet addresses/WIFs")
    ap.add_argument("--iv-from", help="print the IV crackbtcshell expects for a key id")
    ap.add_argument("--keyid-from-pubkey",
                    help="print key id + both candidate IVs for a ckey, given the public key "
                         "(compressed or uncompressed hex, as printed by get_mkey_ckey)")
    args = ap.parse_args()

    if args.keyid_from_pubkey:
        pub = bytes.fromhex(args.keyid_from_pubkey.replace("0x", ""))
        kid = hash160(pub)                                   # Core's metadata hash (20 bytes)
        kid32 = kid + b"\x00" * 12                           # left-aligned uint256 form
        print(f"public key        {pub.hex()}")
        print(f"hash160(pubkey)   {kid.hex()}   <- key id")
        print()
        print("Candidate IVs for the AES-CBC decryption of that key's ckey:")
        print(f"  A) first 16 bytes of key id          {kid[:16].hex()}")
        print(f"  B) first 16 of double-SHA256(key id) {sha256d(kid32)[:16].hex()}")
        print()
        print("Decrypt with A; check the recovered address against the one get_mkey_ckey")
        print("printed. If it does not match, repeat with B. Only one of them recovers")
        print("the real key - the tool's padding check passes either way (see docs/TESTING.md).")
        return 0

    if args.iv_from:
        key_id = bytes.fromhex(args.iv_from.replace("0x", ""))
        iv = sha256d(key_id)[:16].hex()
        print(f"key id       {key_id.hex()}")
        print(f"double sha256{sha256d(key_id).hex()}")
        print(f"IV (first 32){iv}")
        print("\nUse it as the first argument of:  aesdecrypt <IV> <KEY> <CKEY>")
        print("Cross-check against get_mkey_ckey output before trusting it.")
        return 0

    if args.wif and not args.privkey:
        privkey, compressed, testnet = privkey_from_wif(args.wif)
        args.testnet = args.testnet or testnet
        print(f"WIF              {args.wif}")
        print(f"compressed flag  {'yes' if compressed else 'no'}")
    elif args.privkey:
        privkey = bytes.fromhex(args.privkey.replace("0x", ""))
        if len(privkey) != 32:
            print(f"error: private key must be 32 bytes, got {len(privkey)}", file=sys.stderr)
            return 2
    else:
        ap.error("pass --privkey, --wif or --iv-from")

    net = "testnet" if args.testnet else "mainnet"
    variants = {}
    print(f"private key      {privkey.hex()}")
    print(f"network          {net}")
    for compressed in (True, False):
        label = "compressed" if compressed else "uncompressed"
        addr = address_from_privkey(privkey, compressed, args.testnet)
        wif = wif_from_privkey(privkey, compressed, args.testnet)
        variants[label] = addr
        print(f"{label:<13}   address {addr}   WIF {wif}")

    if args.address:
        expected = args.address.strip()


        print()
        match = [label for label, addr in variants.items() if addr == expected]
        if match:
            print(f"MATCH - the key controls {expected} ({match[0]} form).")
            print("The recovered key material is genuinely correct for this wallet.")
            return 0
        print(f"NO MATCH - neither derived address equals {expected}.")
        print("Either the key material is wrong, or the IV used for the ckey was wrong")
        print("(a wrong IV corrupts only the first 16 bytes of the key - see --iv-from).")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
