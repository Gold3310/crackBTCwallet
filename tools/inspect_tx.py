#!/usr/bin/env python3
"""
inspect_tx.py - inspect Ethereum transactions across several public RPC endpoints,
falling back automatically when one is rate-limited, unreachable or inconsistent.

No API key required. Standard library only. Useful for checking a batch of hashes
without trusting a single public endpoint.

Usage
-----
    python3 tools/inspect_tx.py --tx 0xabc... --tx 0xdef...

    # endpoint comes from ALCHEMY_URL (Alchemy Ethereum mainnet only)
    export ALCHEMY_URL='https://eth-mainnet.g.alchemy.com/v2/<key>'
    python3 tools/inspect_tx.py --tx 0xabc...

    # machine-readable output
    python3 tools/inspect_tx.py --tx 0xabc... --json out.json

    # verify the tool itself, with no network at all
    python3 tools/inspect_tx.py --selftest

What it reports per transaction
-------------------------------
block number, block timestamp (UTC), from, to (or CONTRACT CREATION), value in ETH,
input selector, receipt status (success / reverted), log count, and which endpoint
answered. Pending transactions and missing receipts are reported, not skipped silently.

Exit codes: 0 all transactions resolved, 1 some failed, 2 bad usage.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

# Access policy: Alchemy Ethereum mainnet only (see rpc-harness/policy.py).
# The endpoint - and therefore the API key - comes from the environment.
DEFAULT_ENV_VAR = "ALCHEMY_URL"

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "rpc-harness"))

# Module-level switch so the self-test can point every call at a local server.
ENDPOINTS_OVERRIDE = None


def policy_check(endpoints, allow_loopback=False):
    """Import lazily so the tool still works if rpc-harness/policy.py is absent."""
    try:
        import policy
    except ImportError:
        for url in endpoints:
            if "alchemy.com" not in url and not allow_loopback:
                raise SystemExit(
                    "off-policy endpoint %r and rpc-harness/policy.py is missing; "
                    "policy is Alchemy Ethereum mainnet only" % url)
        return
    policy.enforce_endpoints([("endpoint", url) for url in endpoints],
                             allow_loopback=allow_loopback)


# --------------------------------------------------------------------------- #
# Transport
# --------------------------------------------------------------------------- #

def rpc(endpoint, method, params, timeout=20.0, attempts=2):
    """One JSON-RPC call with a small retry. Raises RuntimeError on failure."""
    payload = json.dumps({"jsonrpc": "2.0", "method": method,
                          "params": params, "id": 1}).encode()
    last_error = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            endpoint, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "inspect_tx/1.0"},
            method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read() or b"{}")
            if "error" in body:
                raise RuntimeError("jsonrpc: %s" % str(body["error"].get("message"))[:90])
            return body.get("result")
        except Exception as exc:                                    # noqa: BLE001
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.4 * (attempt + 1))
    raise RuntimeError("%s: %s" % (type(last_error).__name__, str(last_error)[:110]))


def endpoints_from(args):
    if ENDPOINTS_OVERRIDE:
        return list(ENDPOINTS_OVERRIDE)
    if args.endpoint:
        out = []
        for item in args.endpoint:
            out.extend(part.strip() for part in item.split(",") if part.strip())
        return out
    from_env = os.environ.get(DEFAULT_ENV_VAR, "").strip()
    if from_env:
        return [from_env]
    raise SystemExit(
        "no endpoint. Policy is Alchemy Ethereum mainnet only, so set your project URL:\n"
        "  export %s='https://eth-mainnet.g.alchemy.com/v2/<your-key>'\n"
        "or pass --endpoint with another mainnet Alchemy URL." % DEFAULT_ENV_VAR)


# --------------------------------------------------------------------------- #
# Decoding
# --------------------------------------------------------------------------- #

def to_int(value):
    if value is None:
        return None
    return int(value, 16) if isinstance(value, str) else int(value)


def wei_to_eth(wei):
    """Fixed 18 decimals, so 1 wei shows as 0.000000000000000001 instead of rounding away."""
    if wei is None:
        return None
    return format(Decimal(wei) / Decimal(10 ** 18), ".18f")


def iso_utc(timestamp):
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


def describe(tx, receipt, block):
    """Turn raw RPC objects into the flat record we print."""
    if not tx:
        return None
    data = tx.get("input") or tx.get("data") or "0x"
    block_number = to_int(tx.get("blockNumber"))
    timestamp = to_int(block.get("timestamp")) if block else None
    status_raw = receipt.get("status") if receipt else None
    return {
        "block": block_number,
        "timestamp": iso_utc(timestamp),
        "from": tx.get("from"),
        "to": tx.get("to") or "CONTRACT CREATION",
        "value_eth": wei_to_eth(to_int(tx.get("value"))),
        "selector": data[:10] if data and data != "0x" and len(data) >= 10 else "(none)",
        "input_bytes": (len(data) - 2) // 2 if data and data.startswith("0x") else 0,
        "status": None if status_raw is None else ("success" if to_int(status_raw) == 1 else "reverted"),
        "logs": len(receipt.get("logs", [])) if receipt else None,
        "gas_used": to_int(receipt.get("gasUsed")) if receipt else None,
        "pending": block_number is None,
    }


def inspect(tx_hash, endpoints, verbose=False):
    """Try endpoints in order until one answers the whole query."""
    errors = []
    for endpoint in endpoints:
        try:
            tx = rpc(endpoint, "eth_getTransactionByHash", [tx_hash])
            if tx is None:
                errors.append("%s: transaction not found" % endpoint)
                continue
            receipt = rpc(endpoint, "eth_getTransactionReceipt", [tx_hash])
            block = None
            if tx.get("blockNumber"):
                block = rpc(endpoint, "eth_getBlockByNumber", [tx["blockNumber"], False])
            record = describe(tx, receipt, block)
            record["hash"] = tx_hash
            record["endpoint"] = endpoint
            if receipt is None:
                errors.append("%s: answered tx, no receipt yet" % endpoint)
                record["note"] = "receipt not available yet"
            return record, errors
        except Exception as exc:                                    # noqa: BLE001
            errors.append("%s: %s" % (endpoint, str(exc)[:110]))
            if verbose:
                print("  ! %s" % errors[-1], file=sys.stderr)
    return None, errors


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def print_table(records):
    if not records:
        print("no transactions resolved")
        return
    header = ("hash", "block", "time (UTC)", "from", "to", "value ETH", "selector", "status", "logs")
    rows = []
    for rec in records:
        rows.append((
            rec["hash"][:18] + "..",
            "-" if rec["block"] is None else str(rec["block"]),
            rec["timestamp"] or ("pending" if rec["pending"] else "-"),
            (rec["from"] or "")[:12],
            (rec["to"] or "")[:12],
            rec["value_eth"],
            rec["selector"],
            rec["status"] or "-",
            "-" if rec["logs"] is None else str(rec["logs"]),
        ))
    widths = [max(len(str(row[i])) for row in [header] + rows) for i in range(len(header))]
    line = "  ".join(str(header[i]).ljust(widths[i]) for i in range(len(header)))
    print(line)
    print("-" * len(line))
    for row in rows:
        print("  ".join(str(row[i]).ljust(widths[i]) for i in range(len(header))))


# --------------------------------------------------------------------------- #
# Self-test (no network)
# --------------------------------------------------------------------------- #

def selftest():
    import http.server
    import threading

    calls = []
    sample = {
        "eth_getTransactionByHash": {
            "hash": "0x" + "11" * 32,
            "blockNumber": "0x1312d00",                      # 20000000
            "from": "0x" + "aa" * 20,
            "to": "0x" + "bb" * 20,
            "value": "0xde0b6b3a7640000",                    # 1 ETH
            "input": "0xa9059cbb" + "00" * 64,
        },
        "eth_getTransactionReceipt": {
            "status": "0x1",
            "gasUsed": "0x5208",
            "logs": [{"address": "0x" + "bb" * 20}, {"address": "0x" + "cc" * 20}],
        },
        "eth_getBlockByNumber": {"timestamp": "0x65000000"},
    }

    class Handler(http.server.BaseHTTPRequestHandler):
        mode = "ok"

        def do_POST(self):                                       # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            calls.append(body.get("method"))
            if Handler.mode == "down":
                self.send_response(503)
                self.end_headers()
                return
            result = sample.get(body.get("method"))
            payload = json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = "http://127.0.0.1:%d" % server.server_address[1]

    failures = 0
    total = 0

    def check(label, condition, detail=""):
        nonlocal failures, total
        total += 1
        print(("[PASS] " if condition else "[FAIL] ") + label + ("" if condition else " - %s" % (detail,)))
        if not condition:
            failures += 1

    global ENDPOINTS_OVERRIDE
    policy_check([url], allow_loopback=True)
    try:
        record, errors = inspect("0x" + "11" * 32, [url])
        check("transaction resolved", record is not None, errors)
        check("block number decoded", record and record["block"] == 20000000, record and record["block"])
        check("value converted to 1.000000 ETH", record and record["value_eth"] == "1.000000000000000000",
              record and record["value_eth"])
        check("selector extracted", record and record["selector"] == "0xa9059cbb", record and record["selector"])
        check("status decoded", record and record["status"] == "success", record and record["status"])
        check("logs counted", record and record["logs"] == 2, record and record["logs"])
        check("timestamp formatted", record and record["timestamp"] == "2023-09-12 06:06:56Z",
              record and record["timestamp"])
        check("endpoint recorded", record and record["endpoint"] == url)

        ENDPOINTS_OVERRIDE = [url, url]
        Handler.mode = "ok"
        calls.clear()
        record, _ = inspect("0x" + "11" * 32, ENDPOINTS_OVERRIDE)
        check("three RPC methods issued per transaction", calls == [
            "eth_getTransactionByHash", "eth_getTransactionReceipt", "eth_getBlockByNumber"], calls)

        Handler.mode = "down"
        record, errors = inspect("0x" + "11" * 32, [url, url])
        check("unreachable endpoints produce no record", record is None)
        check("every attempt is reported", len(errors) == 2, errors)
        check("error text names the endpoint", all(url in e for e in errors), errors)
        Handler.mode = "ok"

        ENDPOINTS_OVERRIDE = [url]
        missing = json.loads(json.dumps(sample))
        missing["eth_getTransactionByHash"] = None
        original = dict(sample)
        sample.update(missing)
        record, errors = inspect("0x" + "22" * 32, [url])
        check("unknown hash reported as not found", record is None and any("not found" in e for e in errors),
              errors)
        sample.update(original)
    finally:
        server.shutdown()
        ENDPOINTS_OVERRIDE = None

    print()
    print("passed: %d, failed: %d (of %d checks)" % (total - failures, failures, total))
    return 0 if failures == 0 else 1


# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description="Inspect Ethereum transactions across public RPC endpoints.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--tx", action="append", default=[], help="transaction hash (repeatable)")
    ap.add_argument("--endpoint", action="append", default=[],
                    help="RPC endpoint (repeatable or comma separated); overrides defaults")
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--json", dest="json_out", help="write records to this JSON file")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="run offline self-tests and exit")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not args.tx:
        ap.error("pass at least one --tx, or use --selftest")

    endpoints = endpoints_from(args)
    try:
        policy_check(endpoints)
    except SystemExit:
        raise
    except Exception as exc:                                        # noqa: BLE001
        raise SystemExit("access policy: %s" % exc)
    print("endpoints: %s" % ", ".join(endpoints))

    records, all_errors = [], []
    for tx_hash in args.tx:
        record, errors = inspect(tx_hash, endpoints, verbose=args.verbose)
        all_errors.extend(errors)
        if record:
            records.append(record)
        else:
            print("FAILED  %s" % tx_hash)
            for error in errors:
                print("        %s" % error)

    print()
    print_table(records)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"records": records, "errors": all_errors}, fh, indent=2)
        print("\nwrote %s (%d records, %d errors)" % (args.json_out, len(records), len(all_errors)))

    return 0 if len(records) == len(args.tx) else 1


if __name__ == "__main__":
    sys.exit(main())
