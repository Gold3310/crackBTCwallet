#!/usr/bin/env python3
"""
crosscheck.py - check our wallet.dat decryption against a second implementation.

The point: our PoC decrypts the master key with AES, derives the ckey and reports an
address. That chain has many places to be subtly wrong. A second implementation
(pywallet --dumpwallet, or Bitcoin Core's own dumpwallet) produces private keys for the
same wallet by a different code path. If the key sets are equal, the decryption is right;
if they differ, one of us is wrong and the diff says where.

Nothing here re-implements decryption - it only extracts, normalises and compares.

Usage
-----
  # against a saved dump (works offline, ideal for CI)
  python3 tools/crosscheck.py --ours <WIF-or-hex> --from-dump theirs.txt

  # against a live external tool
  python3 tools/crosscheck.py --ours <WIF> \
      --from-cmd "python3 pywallet.py --dumpwallet --wallet wallet.dat"

  # several of our keys, and check the address they must belong to
  python3 tools/crosscheck.py --ours-file mine.txt --from-cmd "bitcoin-cli dumpwallet -" \
      --address 1ExampleAddress...

Exit codes: 0 = key sets match, 1 = they differ, 2 = bad input.

Only ever use throwaway wallets: an encrypted wallet.dat is a secret, and a real one has
no business in a test run.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_key  # noqa: E402  (shared EC / Base58Check / WIF helpers)

# WIF is unambiguous: its prefix plus length cannot be confused with anything else.
WIF_RE = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[5KLc9][1-9A-HJ-NP-Za-km-z]{50,51}(?![1-9A-HJ-NP-Za-km-z])")
HEX64_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")
ADDR_RE = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[13mn2][1-9A-HJ-NP-Za-km-z]{25,39}(?![1-9A-HJ-NP-Za-km-z])")

# A bare 64-hex string is ambiguous (transaction ids look identical), so only trust one
# when its own line says it is a key.
KEYWORD_RE = re.compile(r"private_?key|privkey|priv key|secret|masterkey|ckey|key\s*[=:]", re.I)


class Key:
    __slots__ = ("hex", "compressed", "origin")

    def __init__(self, hexstr, compressed, origin="dump"):
        self.hex = hexstr.lower()
        self.compressed = compressed
        self.origin = origin

    @property
    def id(self):
        return (self.hex, self.compressed)

    def __eq__(self, other):
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return "<Key %s… %s>" % (self.hex[:12], "compressed" if self.compressed else "uncompressed")


def keys_from_text(text, origin="dump"):
    """Pull every plausible private key out of a dump, WIF first, then labelled hex."""
    found = []
    for line in text.splitlines():
        for m in WIF_RE.finditer(line):
            try:
                privkey, compressed, _testnet = verify_key.privkey_from_wif(m.group(0))
            except Exception:
                continue
            found.append(Key(privkey.hex(), compressed, origin))
        if KEYWORD_RE.search(line):
            for m in HEX64_RE.finditer(line):
                found.append(Key(m.group(0), True, origin))  # Core keys are compressed
    return found


def addresses_from_text(text):
    return ADDR_RE.findall(text)


def key_address(key):
    """Address this key controls, in both compression variants."""
    raw = bytes.fromhex(key.hex)
    return {
        "compressed": verify_key.address_from_privkey(raw, True),
        "uncompressed": verify_key.address_from_privkey(raw, False),
    }


def dedupe(keys):
    seen, out = set(), []
    for k in keys:
        if k.id not in seen:
            seen.add(k.id)
            out.append(k)
    return out


def compare(ours, theirs):
    ours_map = {(k.hex, k.compressed): k for k in ours}
    theirs_map = {(k.hex, k.compressed): k for k in theirs}
    matched = [theirs_map[i] for i in theirs_map if i in ours_map]
    only_theirs = [theirs_map[i] for i in theirs_map if i not in ours_map]
    only_ours = [ours_map[i] for i in ours_map if i not in theirs_map]
    # Same secret, different compression flag: a real failure, but a specific one.
    # Keys that matched on (hex, flag) are excluded, otherwise every match would be
    # reported as a flag difference too.
    matched_hex = {k.hex for k in matched}
    ours_hex, theirs_hex = {k.hex for k in ours}, {k.hex for k in theirs}
    compression_only = sorted((ours_hex & theirs_hex) - matched_hex)
    return matched, only_theirs, only_ours, compression_only


def read_source(args):
    if args.from_dump:
        return Path(args.from_dump).read_text(errors="replace"), args.from_dump
    proc = subprocess.run(args.from_cmd, shell=True, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("external command failed (%d): %s" % (proc.returncode, proc.stderr.strip()[:300]))
    return proc.stdout, args.from_cmd


def gather_ours(args):
    keys = []
    for wif in args.ours or []:
        if re.fullmatch(r"[0-9a-fA-F]{64}", wif.strip()):
            keys.append(Key(wif.strip(), True, "ours"))
        else:
            privkey, compressed, _ = verify_key.privkey_from_wif(wif.strip())
            keys.append(Key(privkey.hex(), compressed, "ours"))
    if args.ours_file:
        for line in Path(args.ours_file).read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if re.fullmatch(r"[0-9a-fA-F]{64}", line):
                keys.append(Key(line, True, "ours"))
            else:
                privkey, compressed, _ = verify_key.privkey_from_wif(line)
                keys.append(Key(privkey.hex(), compressed, "ours"))
    return dedupe(keys)


def report(args):
    ours = gather_ours(args)
    if not ours:
        print("no keys supplied: use --ours or --ours-file", file=sys.stderr)
        return 2

    text, origin = read_source(args)
    theirs = dedupe(keys_from_text(text, origin))
    if not theirs:
        print("no private keys found in %s - wrong format, or the wallet is encrypted "
              "and needs unlocking first" % origin, file=sys.stderr)
        return 2

    matched, only_theirs, only_ours, compression_only = compare(ours, theirs)

    addr_results = []
    dumps_addresses = set(addresses_from_text(text))
    for key in theirs:
        derived = key_address(key)
        variant = "compressed" if key.compressed else "uncompressed"
        addr_results.append({
            "key": key.hex,
            "variant": variant,
            "address": derived[variant],
            "in_dump": derived[variant] in dumps_addresses,
            "expected_match": (args.address == derived[variant]) if args.address else None,
        })

    result = {
        "ours_count": len(ours),
        "theirs_count": len(theirs),
        "matched": [{"key": k.hex, "variant": "compressed" if k.compressed else "uncompressed"} for k in matched],
        "only_in_theirs": [{"key": k.hex, "address": key_address(k)["compressed"]} for k in only_theirs],
        "only_in_ours": [{"key": k.hex, "address": key_address(k)["compressed"]} for k in only_ours],
        "compression_only_differences": compression_only,
        "addresses": addr_results,
        "verified_against_address": args.address,
        "strict": bool(args.strict),
        # Every key we claim must be confirmed by the second implementation. Extra keys
        # on their side are normal - a wallet has change addresses and reserves we may
        # not have attacked - so they only fail under --strict.
        "ok": not only_ours and not compression_only and (not args.strict or not only_theirs),
    }
    # An expected address that no key controls is a failure even if the sets match.
    if args.address and not any(a["expected_match"] for a in addr_results):
        result["ok"] = False
        result["reason"] = "no key in the dump controls %s" % args.address

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("ours: %d key(s)   theirs: %d key(s)   matched: %d" % (len(ours), len(theirs), len(matched)))
        for k in matched:
            print("  MATCH   %s  (%s)" % (k.hex, "compressed" if k.compressed else "uncompressed"))
        for k in only_theirs:
            print("  EXTRA   %s  address %s" % (k.hex, key_address(k)["compressed"]))
        for k in only_ours:
            print("  OURS    %s  address %s" % (k.hex, key_address(k)["compressed"]))
        for hexstr in compression_only:
            print("  FLAG    %s appears on both sides with different compression" % hexstr)
        if args.address:
            hit = [a for a in addr_results if a["expected_match"]]
            if hit:
                print("  address %s is controlled by %s" % (args.address, hit[0]["key"]))
            else:
                print("  address %s is not controlled by any key in the dump" % args.address)
        print()
        if only_theirs and not args.strict:
            print("note: %d extra key(s) in the dump, not claimed by us "
                  "(expected if the wallet has other addresses; --strict fails on this)"
                  % len(only_theirs))
        print("RESULT: %s" % ("MATCH - two implementations agree" if result["ok"]
                              else "MISMATCH - " + result.get("reason", "key sets differ")))

    return 0 if result["ok"] else 1


# --------------------------------------------------------------------------- #
# self-test: proves the comparison logic without a wallet, a node or a network
# --------------------------------------------------------------------------- #

def _selftest():
    checks = []

    def check(name, condition, detail=""):
        checks.append((name, bool(condition), detail))

    # Known-good pair: private key 0x01 compressed -> 1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH
    priv1 = bytes.fromhex("0000000000000000000000000000000000000000000000000000000000000001")
    wif1c = verify_key.wif_from_privkey(priv1, True)
    wif1u = verify_key.wif_from_privkey(priv1, False)
    priv2 = bytes.fromhex("00" * 31 + "02")
    wif2c = verify_key.wif_from_privkey(priv2, True)
    addr1c = verify_key.address_from_privkey(priv1, True)

    check("WIF test vector decodes", verify_key.privkey_from_wif(wif1c)[0] == priv1)
    check("compressed flag survives WIF", verify_key.privkey_from_wif(wif1c)[1] is True)
    check("uncompressed flag survives WIF", verify_key.privkey_from_wif(wif1u)[1] is False)
    check("test vector address", addr1c == "1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH", addr1c)

    pywallet_style = '"%s" : {"public_key": "...", "private_key": "%s", "reserve": 0},\n' % (addr1c, priv1.hex())
    keys = keys_from_text(pywallet_style)
    check("pywallet-style line yields one key", len(keys) == 1, str(keys))

    core_style = "%s 2024-05-01T00:00:00Z label= # addr=%s hdkeypath=m/0'/0'/0'\n" % (wif1c, addr1c)
    keys = keys_from_text(core_style)
    check("bitcoin-cli dumpwallet line yields one key", len(keys) == 1, str(keys))
    check("WIF in a dump keeps compression", keys and keys[0].compressed)

    txid_noise = 'txid: %s (this is not a key)\n' % ("ab" * 32)
    check("bare txid is not mistaken for a key", keys_from_text(txid_noise) == [])

    labelled_hex = 'private_key = "%s"\n' % ("cd" * 32)
    check("labelled 64-hex is accepted", len(keys_from_text(labelled_hex)) == 1)

    ours = [Key(priv1.hex(), True, "ours")]
    matched, only_theirs, only_ours, _c = compare(ours, dedupe(keys_from_text(pywallet_style)))
    check("identical sets match", len(matched) == 1 and not only_theirs and not only_ours)

    other = Key("11" * 32, True, "theirs")
    matched, only_theirs, only_ours, _c = compare(ours, [other])
    check("different key is reported as theirs-only", len(only_theirs) == 1 and len(only_ours) == 1)

    both_flags = dedupe(keys_from_text(pywallet_style + core_style.replace(wif1c, wif1u)))
    check("same secret with two flags is two distinct entries", len(both_flags) == 2, str(both_flags))

    ours_u = [Key(priv1.hex(), False, "ours")]
    _m, _t, _o, compression = compare(ours_u, [Key(priv1.hex(), True, "theirs")])
    check("compression-only difference is named", compression == [priv1.hex()])

    dupes = keys_from_text(pywallet_style + pywallet_style)
    check("duplicates are collapsed", len(dedupe(dupes)) == 1)

    derived = key_address(Key(priv1.hex(), True, "x"))
    check("derived compressed address is correct", derived["compressed"] == addr1c)
    check("derived uncompressed address differs",
          derived["uncompressed"] != addr1c and derived["uncompressed"].startswith("1"))

    garbage = "not a key at all\n12345\n\x00\x01binary\xff\n"
    check("garbage yields nothing", keys_from_text(garbage) == [])

    found_addrs = addresses_from_text(core_style)
    check("addresses are extractable from a dump", addr1c in found_addrs, str(found_addrs))

    # subset semantics: we confirm one key, they list two -> still a MATCH
    subset_matched, subset_theirs, subset_ours, subset_c = compare(
        [Key(priv1.hex(), True, "ours")], dedupe(keys_from_text(pywallet_style + core_style.replace(wif1c, wif2c))))
    check("subset of the dump still matches", not subset_ours and not subset_c and len(subset_theirs) >= 1,
          "theirs=%d ours=%d c=%s" % (len(subset_theirs), len(subset_ours), subset_c))

    # regression: a key that matched must never also be reported as a flag difference
    m2, _t2, _o2, c2 = compare([Key(priv1.hex(), True, "ours")], [Key(priv1.hex(), True, "theirs")])
    check("matched key is not reported as a compression difference", len(m2) == 1 and c2 == [])

    passed = sum(1 for _n, ok, _d in checks if ok)
    for name, ok, detail in checks:
        print("%s  %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "   <- " + detail))
    print()
    print("passed: %d, failed: %d (of %d checks)" % (passed, len(checks) - passed, len(checks)))
    return 0 if passed == len(checks) else 1


def main():
    ap = argparse.ArgumentParser(
        description="Compare our wallet.dat decryption against pywallet or bitcoin-cli.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--ours", action="append", metavar="WIF|HEX", help="a key we recovered (repeatable)")
    ap.add_argument("--ours-file", metavar="FILE", help="file with one key per line")
    ap.add_argument("--from-dump", metavar="FILE", help="saved pywallet/bitcoin-cli dump")
    ap.add_argument("--from-cmd", metavar="CMD", help="run this command and parse its stdout")
    ap.add_argument("--address", metavar="ADDR", help="address the wallet actually spends from")
    ap.add_argument("--strict", action="store_true",
                    help="require identical key sets (default: extra keys in the dump are allowed)")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--selftest", action="store_true", help="verify this tool offline (no wallet needed)")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if not (args.from_dump or args.from_cmd):
        ap.error("one of --from-dump or --from-cmd is required")
    if not (args.ours or args.ours_file):
        ap.error("one of --ours or --ours-file is required")
    return report(args)


if __name__ == "__main__":
    sys.exit(main())
