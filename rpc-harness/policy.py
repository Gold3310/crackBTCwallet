#!/usr/bin/env python3
"""
policy.py - access policy: Alchemy mainnet only.

Every endpoint this repository talks to must be:

  * https
  * a host under `*.alchemy.com`
  * an **Ethereum mainnet** host (`eth-mainnet.g.alchemy.com`)
  * a URL carrying a real API key (`/v2/<key>`), so requests are attributable
  * paired with chain id 1

Anything else is refused before a single request is sent: public RPCs
(drpc, publicnode, 1rpc, cloudflare-eth), other vendors (QuickNode, Goldsky,
dRPC, Infura, Ankr), local or test nodes, and Alchemy testnets (Sepolia,
Holesky, Goerli). Loopback endpoints are permitted only when the caller says it
is running a self-test, so the harness itself stays testable offline.

The escape hatch (`RPC_ALLOW_NON_ALCHEMY=1`) exists for emergencies only, prints
a loud warning, and is documented as a policy violation.

CLI
---
    python3 policy.py --check https://eth-mainnet.g.alchemy.com/v2/abc123
    python3 policy.py --check https://eth-sepolia.g.alchemy.com/v2/abc123
    python3 policy.py --self-test
"""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import urlparse

MAINNET_HOST = "eth-mainnet.g.alchemy.com"
ALCHEMY_SUFFIX = ".alchemy.com"
MAINNET_CHAIN_IDS = {1}

TESTNET_MARKERS = (
    "sepolia", "holesky", "goerli", "rinkeby", "ropsten", "kovan",
    "testnet", "devnet", "mumbai", "fuji", "amoy",
)

NON_ALCHEMY_HINTS = {
    "quiknode.pro": "QuickNode",
    "drpc.org": "dRPC",
    "goldsky": "Goldsky",
    "publicnode.com": "PublicNode",
    "1rpc.io": "1RPC",
    "cloudflare-eth.com": "Cloudflare",
    "infura.io": "Infura",
    "ankr.com": "Ankr",
    "llamarpc.com": "LlamaNodes",
    "blastapi.io": "Blast",
    "blockpi.network": "BlockPI",
    "alchemyapi.io": "legacy Alchemy host (use *.alchemy.com)",
}

ESCAPE_HATCH = "RPC_ALLOW_NON_ALCHEMY"


class PolicyError(RuntimeError):
    pass


def escape_hatch_enabled() -> bool:
    return os.environ.get(ESCAPE_HATCH, "").strip() in ("1", "true", "yes", "on")


def is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1", "[::1]")


def check_endpoint(url: str, allow_loopback: bool = False):
    """Return (allowed: bool, reason: str). Reasons are written for humans."""
    if not url:
        return False, "empty endpoint (set ALCHEMY_URL to your mainnet https://eth-mainnet.g.alchemy.com/v2/<key>)"

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    scheme = (parsed.scheme or "").lower()

    if not host:
        return False, "not a URL: %r" % url

    if allow_loopback and is_loopback(host):
        return True, "loopback endpoint allowed for self-test"
    if is_loopback(host):
        return False, "loopback endpoint refused outside self-test"

    if scheme != "https":
        return False, "plaintext %s refused; the API key would travel in the clear - use https" % scheme

    for needle, vendor in NON_ALCHEMY_HINTS.items():
        if needle in host:
            if escape_hatch_enabled():
                return True, "ALLOWED BY ESCAPE HATCH (%s=%s): %s is outside policy" % (
                    ESCAPE_HATCH, os.environ.get(ESCAPE_HATCH), vendor)
            return False, "%s endpoint refused: policy is Alchemy mainnet only (set %s=1 to override)" % (
                vendor, ESCAPE_HATCH)

    if not host.endswith(ALCHEMY_SUFFIX):
        return False, "host %r is not under %s" % (host, ALCHEMY_SUFFIX)

    if host != MAINNET_HOST:
        for marker in TESTNET_MARKERS:
            if marker in host:
                return False, "%s is a %s network; policy is Ethereum mainnet (%s)" % (
                    host, marker.capitalize(), MAINNET_HOST)
        if host.split(".")[0] not in ("eth-mainnet", "eth-mainnet"):
            return False, "%s is not the Ethereum mainnet host; expected %s" % (host, MAINNET_HOST)

    path = parsed.path or ""
    if "/v2/" not in path:
        return False, "no /v2/<key> path: public or keyless URLs are not attributable - use your project endpoint"
    key = path.split("/v2/", 1)[1].strip("/")

    # Catch the mistake people actually make first: pasting a documentation
    # placeholder or a markdown-wrapped URL, so the message names the real problem.
    if any(char in key for char in "<>[](){} \t\n") or key.lower() in (
            "key", "your-key", "yourkey", "api-key", "apikey", "your_api_key", "demo"):
        return False, ("API key looks like a placeholder (%r). Use your real project URL "
                       "https://eth-mainnet.g.alchemy.com/v2/<40-char-key>" % key[:24])

    if len(key) < 8:
        return False, "API key in the URL looks too short (%d chars)" % len(key)

    return True, "ok: Alchemy Ethereum mainnet"


def check_chain_id(chain_id) -> None:
    if int(chain_id) not in MAINNET_CHAIN_IDS:
        raise PolicyError(
            "chain_id %s refused: policy is Ethereum mainnet (chain id 1)" % chain_id)


def enforce_endpoints(urls, allow_loopback: bool = False):
    """Validate a mapping/list of URLs; raise PolicyError listing every violation."""
    problems, notes = [], []
    for name, url in urls:
        allowed, reason = check_endpoint(url, allow_loopback=allow_loopback)
        if allowed:
            notes.append("%s: %s" % (name, reason))
        else:
            problems.append("%s: %s" % (name, reason))
    if problems:
        raise PolicyError("access policy violation:\n  - " + "\n  - ".join(problems))
    return notes


# --------------------------------------------------------------------------- #

def self_test() -> int:
    failures = 0
    total = 0

    def check(label, condition, detail=""):
        nonlocal failures, total
        total += 1
        print(("[PASS] " if condition else "[FAIL] ") + label + ("" if condition else " - %s" % (detail,)))
        if not condition:
            failures += 1

    ok_url = "https://eth-mainnet.g.alchemy.com/v2/abcdefgh12345678"
    check("mainnet alchemy accepted", check_endpoint(ok_url)[0], check_endpoint(ok_url))
    check("reason mentions mainnet", "mainnet" in check_endpoint(ok_url)[1], check_endpoint(ok_url))

    rejected = {
        "sepolia testnet": "https://eth-sepolia.g.alchemy.com/v2/abcdefgh12345678",
        "holesky testnet": "https://eth-holesky.g.alchemy.com/v2/abcdefgh12345678",
        "quicknode": "https://example.quiknode.pro/abcdef123456/",
        "drpc": "https://eth.drpc.org",
        "publicnode": "https://ethereum-rpc.publicnode.com",
        "1rpc": "https://1rpc.io/eth",
        "cloudflare": "https://cloudflare-eth.com",
        "infura": "https://mainnet.infura.io/v3/abcdef123456",
        "plain http": "http://eth-mainnet.g.alchemy.com/v2/abcdefgh12345678",
        "keyless alchemy": "https://eth-mainnet.g.alchemy.com/v2/",
        "short key": "https://eth-mainnet.g.alchemy.com/v2/abc",
        "placeholder <key>": "https://eth-mainnet.g.alchemy.com/v2/<key>",
        "placeholder your-key": "https://eth-mainnet.g.alchemy.com/v2/your-key",
        "markdown-wrapped URL": "https://eth-mainnet.g.alchemy.com/v2/[https://eth-mainnet.g.alchemy.com/v2/abc]",
        "space in key": "https://eth-mainnet.g.alchemy.com/v2/abc def ghi jkl",
        "loopback": "http://127.0.0.1:8545",
        "empty": "",
    }
    for label, url in rejected.items():
        allowed, reason = check_endpoint(url)
        check("refused: %s" % label, not allowed, "was allowed: %r" % url)
        check("reason given: %s" % label, bool(reason), reason)

    allowed, reason = check_endpoint("http://127.0.0.1:9999", allow_loopback=True)
    check("loopback allowed for selftest", allowed, reason)

    try:
        check_chain_id(1)
        check("chain id 1 accepted", True)
    except PolicyError:
        check("chain id 1 accepted", False)
    for bad in (5, 137, 42161, 8453, 11155111):
        try:
            check_chain_id(bad)
            check("chain id %s refused" % bad, False, "was accepted")
        except PolicyError:
            check("chain id %s refused" % bad, True)

    try:
        enforce_endpoints([("a", ok_url), ("b", "https://eth.drpc.org")])
        check("enforce_endpoints raises on a violation", False)
    except PolicyError as exc:
        check("enforce_endpoints raises on a violation", "dRPC" in str(exc), str(exc))

    os.environ[ESCAPE_HATCH] = "1"
    hatched, reason = check_endpoint("https://eth.drpc.org")
    check("escape hatch allows other vendors", hatched and "ESCAPE HATCH" in reason, reason)
    os.environ.pop(ESCAPE_HATCH, None)

    print()
    print("passed: %d, failed: %d (of %d checks)" % (total - failures, failures, total))
    return 0 if failures == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Check endpoints against the Alchemy-mainnet-only access policy.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--check", metavar="URL", action="append", default=[],
                    help="endpoint to validate (repeatable)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if not args.check:
        ap.error("pass --check URL (repeatable) or --self-test")

    exit_code = 0
    for url in args.check:
        allowed, reason = check_endpoint(url)
        status = "ALLOWED" if allowed else "REFUSED"
        print("%-8s %s\n         %s" % (status, url, reason))
        if not allowed:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
