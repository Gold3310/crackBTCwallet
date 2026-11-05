#!/usr/bin/env python3
"""
verify_contract.py - prove an address is worth sending mainnet traffic to, before we do.

Pasting a contract address into a benchmark is how you end up measuring the wrong thing:
a typo lands on an address with no code, a testnet address answers nothing, a checksum
mismatch means the address is not even the one you copied. This runs *before* the policy
gate and the benchmark, and refuses to continue on a bad address.

Offline checks (always run, no network):
  1. shape          0x + 40 hex characters
  2. not zero       0x000...000 has no code and can never be a contract
  3. not precompile 0x00..0x0a are native identifiers, not contracts
  4. EIP-55         mixed case must match the Keccak-256 checksum; all-lower is accepted
                    and normalised, because that is what most tools emit
  5. chain pin      the config must say chain_id 1 (Ethereum mainnet)
  6. allowlist      if the address is known, its symbol/decimals must match ours

Live checks (--live, requires egress and ALCHEMY_URL):
  7. eth_chainId == 1
  8. eth_getCode(address) is not 0x          (it is a contract)
  9. symbol() / decimals() answer, and match the allowlist when known

Usage
-----
  python3 tools/verify_contract.py --address 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48
  python3 tools/verify_contract.py --contract-file rpc-harness/contracts.example.json
  python3 tools/verify_contract.py --address 0x... --live        # needs ALCHEMY_URL
  python3 tools/verify_contract.py --selftest                    # offline, no address needed

Exit codes: 0 = verified, 1 = invalid or mismatched, 2 = bad input,
            3 = endpoint outside policy, 4 = live probe failed.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rpc-harness"))
import keccak  # noqa: E402

KNOWN_PATH = Path(__file__).resolve().parent.parent / "contracts.known.json"
ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
PRECOMPILES = {"0x" + "0" * 39 + c for c in "0123456789a"}
ZERO_ADDRESS = "0x" + "0" * 40

# function selectors, from keccak (see tools/keccak.py --selftest)
SEL_SYMBOL = "0x" + keccak.selector("symbol()")
SEL_DECIMALS = "0x" + keccak.selector("decimals()")
SEL_NAME = "0x" + keccak.selector("name()")


# --------------------------------------------------------------------------- #
# address checks
# --------------------------------------------------------------------------- #

def to_checksum(address: str) -> str:
    """EIP-55 checksummed form of a 0x + 40 hex address."""
    body = address[2:].lower()
    digest = keccak.keccak256(body.encode()).hex()
    return "0x" + "".join(
        char.upper() if char in "abcdef" and int(digest[i], 16) >= 8 else char
        for i, char in enumerate(body)
    )


def check_address(address: str):
    """Return (ok, reason, normalised). Offline only."""
    if not isinstance(address, str) or not ADDRESS_RE.match(address):
        return False, "not 0x followed by 40 hex characters (%r)" % (address,), None
    body = address[2:]
    if address.lower() == ZERO_ADDRESS:
        return False, "zero address - has no code, cannot be a contract", None
    if address.lower() in PRECOMPILES:
        return False, "precompile address - a native identifier, not a contract", None
    if body != body.lower() and body != body.upper():
        expected = to_checksum(address)
        if address != expected:
            return False, ("EIP-55 checksum mismatch - you probably copied it from a "
                           "truncated or edited string; expected %s" % expected), None
    return True, "ok", to_checksum(address)


def known_contract(address: str, chain_id: int = 1, path: Path = KNOWN_PATH):
    """Allowlist entry for this address on this chain, or None."""
    try:
        data = json.loads(Path(path).read_text())
    except Exception:
        return None
    for addr, meta in (data.get(str(chain_id)) or {}).items():
        if addr.lower() == address.lower():
            return dict(meta, address=addr)
    return None


def offline_check(address, chain_id=1, path=KNOWN_PATH):
    """Everything that can be decided without a network. Returns a report dict."""
    ok, reason, normalised = check_address(address)
    report = {
        "address": address,
        "normalised": normalised,
        "chain_id": chain_id,
        "checks": [],
        "ok": ok,
        "known": None,
    }
    report["checks"].append({"name": "address shape/checksum", "ok": ok, "detail": reason})
    if not ok:
        return report

    chain_ok = chain_id == 1
    report["checks"].append({
        "name": "chain is Ethereum mainnet",
        "ok": chain_ok,
        "detail": "chain_id 1" if chain_ok else "chain_id %r is not mainnet (policy)" % (chain_id,),
    })
    if not chain_ok:
        report["ok"] = False
        return report

    meta = known_contract(normalised, chain_id, path)
    report["known"] = meta
    report["checks"].append({
        "name": "known-contract metadata",
        "ok": True,
        "detail": ("%s, %d decimals (allowlist)" % (meta["symbol"], meta["decimals"])) if meta
                  else "not in the allowlist - allowed, but nothing to compare against",
    })
    return report


# --------------------------------------------------------------------------- #
# live probe
# --------------------------------------------------------------------------- #

def _rpc(url, method, params, timeout=10):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read())
    if body.get("error"):
        raise RuntimeError("%s: %s" % (method, body["error"].get("message", "rpc error")))
    return body.get("result")


def decode_string(result_hex):
    """Decode a solidity `string` return value. Returns str or None."""
    if not result_hex or result_hex in ("0x", "0x0"):
        return None
    raw = bytes.fromhex(result_hex[2:])
    if len(raw) < 64:
        return None
    offset = int.from_bytes(raw[:32], "big")
    if offset + 32 > len(raw):
        return None
    length = int.from_bytes(raw[offset:offset + 32], "big")
    text = raw[offset + 32:offset + 32 + length]
    try:
        return text.decode("utf-8")
    except UnicodeDecodeError:
        return None


def decode_uint(result_hex):
    if not result_hex or result_hex in ("0x", "0x0"):
        return None
    return int(result_hex, 16)


def live_check(url, address, report, timeout=10):
    """Probe the chain. Returns the updated report."""
    def add(name, ok, detail):
        report["checks"].append({"name": name, "ok": ok, "detail": detail})
        if not ok:
            report["ok"] = False

    try:
        chain_hex = _rpc(url, "eth_chainId", [], timeout)
        chain_id = int(chain_hex, 16)
        add("live eth_chainId", chain_id == 1, "chain %d" % chain_id)
        if chain_id != 1:
            return report

        code = _rpc(url, "eth_getCode", [address, "latest"], timeout)
        has_code = bool(code) and code not in ("0x", "0x0")
        add("eth_getCode is non-empty", has_code,
            "%d bytes of code" % ((len(code) - 2) // 2) if has_code else "no code at this address")

        if report.get("known"):
            symbol = decode_string(_rpc(url, "eth_call", [{"to": address, "data": SEL_SYMBOL}, "latest"], timeout))
            add("symbol() answers", bool(symbol), repr(symbol))
            if symbol:
                add("symbol() matches allowlist", symbol == report["known"]["symbol"],
                    "%r vs %r" % (symbol, report["known"]["symbol"]))
            decimals = decode_uint(_rpc(url, "eth_call", [{"to": address, "data": SEL_DECIMALS}, "latest"], timeout))
            add("decimals() answers", decimals is not None, str(decimals))
            if decimals is not None:
                add("decimals() matches allowlist", decimals == report["known"]["decimals"],
                    "%r vs %r" % (decimals, report["known"]["decimals"]))
    except (urllib.error.URLError, RuntimeError, ValueError, OSError) as exc:
        add("live probe", False, "%s: %s" % (type(exc).__name__, exc))
        report["network_error"] = True
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def print_report(report):
    print("address: %s" % report["address"])
    if report.get("normalised") and report["normalised"].lower() != str(report["address"]).lower():
        print("checksum: %s" % report["normalised"])
    print()
    for c in report["checks"]:
        print("  %s  %-30s %s" % ("PASS" if c["ok"] else "FAIL", c["name"], c["detail"]))
    print()
    print("RESULT: %s" % ("VERIFIED" if report["ok"] else "REFUSED"))
    if report.get("network_error"):
        print("note: no network here - offline checks only. Re-run with --live where egress exists.")


def main():
    ap = argparse.ArgumentParser(
        description="Validate a contract address before sending mainnet traffic.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--address", help="the 0x address to check")
    ap.add_argument("--contract-file", help="contract config JSON (reads 'address' and 'chain_id')")
    ap.add_argument("--chain-id", type=int, help="override the chain id (default: from file, else 1)")
    ap.add_argument("--live", action="store_true", help="also probe the chain (needs ALCHEMY_URL)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="offline self-test")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    address = args.address
    chain_id = args.chain_id
    if args.contract_file:
        try:
            cfg = json.loads(Path(args.contract_file).read_text())
        except Exception as exc:
            print("cannot read %s: %s" % (args.contract_file, exc), file=sys.stderr)
            return 2
        address = address or cfg.get("address")
        if chain_id is None:
            chain_id = cfg.get("chain_id", 1)
    if not address:
        ap.error("--address or --contract-file is required")
    if chain_id is None:
        chain_id = 1

    report = offline_check(address, chain_id)
    if report["ok"] and args.live:
        import os
        url = os.environ.get("ALCHEMY_URL")
        if not url:
            print("--live needs ALCHEMY_URL (see docs/ACCESS-POLICY.md)", file=sys.stderr)
            return 2
        try:
            import policy
        except ImportError as exc:
            print("cannot load the access policy (%s) - refusing to probe" % exc, file=sys.stderr)
            return 3
        ok, reason = policy.check_endpoint(url)
        if not ok:
            print("REFUSED  %s\n         %s" % (url.split("/v2/")[0], reason), file=sys.stderr)
            return 3
        report = live_check(url, report["normalised"], report)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    if report["ok"]:
        return 0
    return 2 if report.get("network_error") else 1


# --------------------------------------------------------------------------- #
# self-test
# --------------------------------------------------------------------------- #

def _selftest():
    checks = []

    def check(name, condition, detail=""):
        checks.append((name, bool(condition), detail))

    usdc = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"

    # EIP-55
    check("checksum of the pasted USDC address round-trips", to_checksum(usdc.lower()) == usdc,
          to_checksum(usdc.lower()))
    ok, reason, norm = check_address(usdc)
    check("USDC address is valid", ok, reason)
    check("valid address normalises to its checksum", norm == usdc, norm)

    ok, _r, norm = check_address(usdc.lower())
    check("all-lowercase is accepted", ok)
    check("lowercase is normalised to checksum", norm == usdc, norm)

    wrong_case = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB49"
    ok, reason, _n = check_address(wrong_case)
    check("wrong checksum is refused", not ok, reason)
    check("refusal names EIP-55", "EIP-55" in reason, reason)

    ok, reason, _n = check_address("0x" + "0" * 40)
    check("zero address is refused", not ok and "zero" in reason, reason)

    ok, reason, _n = check_address("0x" + "0" * 39 + "4")
    check("precompile is refused", not ok and "precompile" in reason, reason)

    for bad in ["A0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "0xA0b8", "0xZZb86991c6218b36c1d19D4a2e9Eb0cE3606eB48", ""]:
        ok, _r, _n = check_address(bad)
        check("malformed %r is refused" % (bad or "<empty>"), not ok)

    # chain pinning
    rep = offline_check(usdc, chain_id=5)
    check("testnet chain id is refused", not rep["ok"])
    rep = offline_check(usdc, chain_id=1)
    check("mainnet chain id passes", rep["ok"])

    # allowlist
    meta = known_contract(usdc)
    check("USDC is in the allowlist", meta and meta["symbol"] == "USDC", str(meta))
    check("USDC decimals are 6", meta and meta["decimals"] == 6, str(meta))
    check("allowlist lookup is case-insensitive", known_contract(usdc.lower()) is not None)
    check("unknown contract yields no entry", known_contract("0x" + "11" * 20) is None)
    # the allowlist itself must be checksummed correctly, or the gate is theatre
    bad_checksums = []
    for addr in (json.loads(KNOWN_PATH.read_text()).get("1") or {}):
        ok, _r, norm = check_address(addr)
        if not ok or norm != addr:
            bad_checksums.append(addr)
    check("every allowlisted address has a valid checksum", not bad_checksums, str(bad_checksums))

    # ABI decoding
    symbol_return = "0x" + "".join([
        "%064x" % 32, "%064x" % 4, ("USDC".encode().hex() + "00" * 28),
    ])
    check("decode_string reads symbol()", decode_string(symbol_return) == "USDC", repr(decode_string(symbol_return)))
    check("decode_string handles empty", decode_string("0x") is None)
    check("decode_uint reads decimals()", decode_uint("0x" + "%064x" % 6) == 6)
    check("decode_uint handles empty", decode_uint("0x") is None)

    # selectors are what the chain expects
    check("symbol selector is 0x95d89b41", SEL_SYMBOL == "0x95d89b41", SEL_SYMBOL)
    check("decimals selector is 0x313ce567", SEL_DECIMALS == "0x313ce567", SEL_DECIMALS)

    # the live path must inherit the endpoint policy, and fail closed if it cannot load it
    try:
        import policy
        check("policy module is importable from the tool", True)
        refused, reason = policy.check_endpoint("https://eth.drpc.org")
        check("policy refuses a non-Alchemy endpoint", not refused, reason)
        allowed, _r = policy.check_endpoint("https://eth-mainnet.g.alchemy.com/v2/abcdefgh12345678")
        check("policy allows Alchemy mainnet", allowed)
    except ImportError as exc:
        check("policy module is importable from the tool", False, str(exc))

    passed = sum(1 for _n, ok, _d in checks if ok)
    for name, ok, detail in checks:
        print("%s  %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else "   <- " + detail))
    print("\npassed: %d, failed: %d (of %d checks)" % (passed, len(checks) - passed, len(checks)))
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
