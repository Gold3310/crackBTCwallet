#!/usr/bin/env python3
"""
make_test_vector.py - build a self-contained ckey/mkey test vector.

You do not need Bitcoin Core, a wallet.dat, or any funds to exercise crackbtcshell.
This script fabricates a ckey exactly the way Bitcoin Core lays one out:

    plaintext = private key (32 bytes) || 0x10 x 16   (AES-CBC padding to 48 bytes)
    AES key   = "master key" material (32 bytes)
    IV        = first 16 bytes of double-SHA256(key id)   <- what crackbtcshell expects
    ckey      = AES-256-CBC(plaintext, key, IV)           no padding flag; plaintext is pre-padded

It then prints the exact crackBTC shell commands that must recover the private key,
so the tool can be tested against data you generated yourself and whose answer you
already know.

Requires the `openssl` CLI for AES (present on virtually every Linux/macOS box) or the
`cryptography` module if installed.

Usage
-----
    python3 make_test_vector.py                     # random vector
    python3 make_test_vector.py --seed demo-1       # reproducible vector
    python3 make_test_vector.py --seed demo-1 --commands   # only the shell script
"""

import argparse
import hashlib
import shutil
import subprocess
import sys


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256d(data: bytes) -> bytes:
    return sha256(sha256(data))


def aes256cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    """AES-256-CBC with the padding already applied by the caller."""
    if shutil.which("openssl"):
        result = subprocess.run(
            ["openssl", "enc", "-aes-256-cbc", "-nopad",
             "-K", key.hex(), "-iv", iv.hex()],
            input=plaintext, capture_output=True, check=True,
        )
        return result.stdout
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        sys.exit("need either the openssl CLI or the `cryptography` module")
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", help="deterministic seed string (default: random)")
    ap.add_argument("--commands", action="store_true", help="print only the shell script")
    args = ap.parse_args()

    if args.seed:
        base = args.seed.encode()
        key_material = sha256(b"key/" + base)
        privkey = sha256(b"priv/" + base)
        key_id = sha256(b"keyid/" + base)
    else:
        import os
        key_material, privkey, key_id = os.urandom(32), os.urandom(32), os.urandom(32)

    iv = sha256d(key_id)[:16]
    plaintext = privkey + b"\x10" * 16          # 32 + 16 = 48 bytes, matches Core's ckey
    ckey = aes256cbc_encrypt(key_material, iv, plaintext)

    commands = f"""set quiet 0
load ckey {ckey.hex()}
try key {key_material.hex()}
doublesha256 {key_id.hex()}
aesdecrypt {iv.hex()} {key_material.hex()} {ckey.hex()}
privatekeytowif {privkey.hex()}
exit"""

    if args.commands:
        print(commands)
        return 0

    print("=== test vector ===")
    print(f"private key (answer) : {privkey.hex()}")
    print(f"master key material  : {key_material.hex()}")
    print(f"key id               : {key_id.hex()}")
    print(f"IV                   : {iv.hex()}")
    print(f"ckey (48 bytes)      : {ckey.hex()}")
    print()
    print("=== expected result ===")
    print(f"try key          -> Posible Key found")
    print(f"doublesha256     -> {sha256d(key_id).hex()}")
    print(f"decypted ckey    -> {privkey.hex()}" + "10" * 16)
    print()
    print("=== crackBTC shell commands ===")
    print(commands)
    print()
    print("Pipe them straight in:")
    print("  python3 make_test_vector.py --seed demo-1 --commands | ./crackbtcshell")
    return 0


if __name__ == "__main__":
    sys.exit(main())
