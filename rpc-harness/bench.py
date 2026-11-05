#!/usr/bin/env python3
"""
bench.py - measure YOUR provider endpoints with YOUR contract, from YOUR network.

This is the independent replacement for the vendor-published benchmark: same idea,
your payloads, your regions, your method mix. Pure Python 3 standard library.

Endpoints (and therefore API keys) are read from environment variables, never from
a file and never from the command line, so nothing secret lands in your repo:

    export ALCHEMY_URL='https://eth-mainnet.g.alchemy.com/v2/<your-key>'
    export QUICKNODE_URL='https://<name>.quiknode.pro/<your-key>/'

Usage
-----
    python3 bench.py --providers providers.example.json \
                     --contract contracts.example.json \
                     --requests 30 --out runs/local

    # smoke-test the harness with no network at all (starts its own fake RPC)
    python3 bench.py --selftest

Outputs
-------
    runs/<ts>/results.csv     one row per provider x method x request
    runs/<ts>/summary.md      p50/p95/max/success per provider x method
    runs/<ts>/summary.json    same, for tooling

Never commit a file containing a real endpoint URL: treat the URL as the secret.
"""

from __future__ import annotations

import argparse
import csv
import http.server
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


# --------------------------------------------------------------------------- #
# Payload templates
# --------------------------------------------------------------------------- #

def substitute(value, ctx):
    """Recursively replace ${address}, ${from}, ${to}, ${topic:NAME} placeholders."""
    if isinstance(value, dict):
        return {k: substitute(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, ctx) for v in value]
    if not isinstance(value, str):
        return value

    if value.startswith("${") and value.endswith("}") and value.count("}") == 1:
        key = value[2:-1]
        if key.startswith("topic:"):
            return ctx["topics"][key.split(":", 1)[1]]
        return ctx[key]

    out = value
    for key in ("address", "from", "to"):
        out = out.replace("${%s}" % key, str(ctx[key]))
    for name, topic in ctx["topics"].items():
        out = out.replace("${topic:%s}" % name, topic)
    return out


def hex_quantity(value):
    """Block numbers must go on the wire as hex quantities ("0x1312d00"), not ints."""
    if isinstance(value, str):
        return value if value.startswith("0x") or value in ("latest", "earliest", "pending",
                                                           "safe", "finalized") else hex(int(value))
    return hex(int(value))


def build_calls(contract, chain_id):
    block_range = contract.get("block_range", [0, 0])
    ctx = {
        "address": contract["address"],
        "from": hex_quantity(block_range[0]),
        "to": hex_quantity(block_range[1]),
        "topics": contract.get("topics", {}),
    }
    calls = []
    for spec in contract["methods"]:
        params = substitute(spec.get("params", []), ctx)
        calls.append({
            "label": spec["name"],
            "method": spec.get("method", spec["name"]),
            "params": params,
        })
    if not calls:
        raise SystemExit("contract config defines no methods")
    return calls


# --------------------------------------------------------------------------- #
# One JSON-RPC call
# --------------------------------------------------------------------------- #

def rpc_call(url, method, params, timeout):
    """Return (latency_ms, ok, note)."""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
    }).encode()
    request = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
        elapsed = (time.perf_counter() - started) * 1000.0
        parsed = json.loads(body or b"{}")
        if "error" in parsed:
            return elapsed, False, "jsonrpc error: %s" % parsed["error"].get("message", "")[:80]
        if "result" not in parsed:
            return elapsed, False, "no result field"
        return elapsed, True, ""
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000.0
        return elapsed, False, "http %s" % exc.code
    except urllib.error.URLError as exc:
        elapsed = (time.perf_counter() - started) * 1000.0
        return elapsed, False, "network: %s" % str(exc.reason)[:80]
    except Exception as exc:                                        # noqa: BLE001
        elapsed = (time.perf_counter() - started) * 1000.0
        return elapsed, False, "%s: %s" % (type(exc).__name__, str(exc)[:80])


# --------------------------------------------------------------------------- #
# Benchmark driver
# --------------------------------------------------------------------------- #

def run(providers, calls, requests, timeout, pacing, outdir, verbose):
    os.makedirs(outdir, exist_ok=True)
    rows = []
    started_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for name, spec in providers.items():
        env_name = spec.get("url_env")
        url = os.environ.get(env_name, "") if env_name else spec.get("url", "")
        if not url:
            print("skip %-11s (%s is not set)" % (name, env_name), file=sys.stderr)
            continue
        if url.rstrip("/").endswith("/demo"):
            print("warn %-11s using a public/demo endpoint - results are not representative"
                  % name, file=sys.stderr)

        for call in calls:
            for i in range(requests):
                latency, ok, note = rpc_call(url, call["method"], call["params"], timeout)
                rows.append({
                    "provider": name,
                    "method": call["label"],
                    "rpc_method": call["method"],
                    "request": i + 1,
                    "latency_ms": round(latency, 3),
                    "ok": 1 if ok else 0,
                    "note": note,
                })
                if verbose:
                    print("  %-11s %-28s %8.2f ms %s" % (name, call["label"], latency,
                                                         "ok" if ok else "FAIL " + note))
                if pacing:
                    time.sleep(pacing)

    if not rows:
        raise SystemExit("no measurements collected - check your *_URL environment variables")

    csv_path = os.path.join(outdir, "results.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary = summarise(rows)
    summary["meta"] = {"started": started_iso, "requests_per_method": requests,
                       "timeout_s": timeout, "rows": len(rows)}

    with open(os.path.join(outdir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)

    markdown = render_markdown(summary)
    with open(os.path.join(outdir, "summary.md"), "w", encoding="utf-8") as fh:
        fh.write(markdown)

    print()
    print(markdown)
    print("wrote %s, summary.md, summary.json" % csv_path)
    return summary


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def summarise(rows):
    by_cell = {}
    for row in rows:
        by_cell.setdefault((row["provider"], row["method"]), []).append(row)

    cells = []
    for (provider, method), cell_rows in sorted(by_cell.items()):
        oks = [r["latency_ms"] for r in cell_rows if r["ok"]]
        fails = [r["note"] for r in cell_rows if not r["ok"]]
        cells.append({
            "provider": provider,
            "method": method,
            "requests": len(cell_rows),
            "ok": len(oks),
            "failed": len(fails),
            "success_pct": round(100.0 * len(oks) / len(cell_rows), 2),
            "avg_ms": round(statistics.mean(oks), 2) if oks else None,
            "p50_ms": round(percentile(oks, 0.50), 2) if oks else None,
            "p95_ms": round(percentile(oks, 0.95), 2) if oks else None,
            "max_ms": round(max(oks), 2) if oks else None,
            "errors": sorted(set(fails))[:3],
        })

    overall = []
    by_provider = {}
    for row in rows:
        by_provider.setdefault(row["provider"], []).append(row)
    for provider, provider_rows in sorted(by_provider.items()):
        oks = [r["latency_ms"] for r in provider_rows if r["ok"]]
        overall.append({
            "provider": provider,
            "requests": len(provider_rows),
            "success_pct": round(100.0 * len(oks) / len(provider_rows), 2),
            "avg_ms": round(statistics.mean(oks), 2) if oks else None,
            "p50_ms": round(percentile(oks, 0.50), 2) if oks else None,
            "p95_ms": round(percentile(oks, 0.95), 2) if oks else None,
        })
    overall.sort(key=lambda r: (r["p95_ms"] is None, r["p95_ms"] or 0))
    return {"cells": cells, "overall": overall}


def render_markdown(summary):
    lines = ["# Local RPC benchmark", "",
             "Tail latency is what matters; `p95` decides the ranking.", "",
             "## By provider (all methods pooled)", "",
             "| Provider | Requests | Success | Avg | P50 | P95 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for row in summary["overall"]:
        lines.append("| %s | %d | %.2f%% | %s | %s | %s |" % (
            row["provider"], row["requests"], row["success_pct"],
            _fmt(row["avg_ms"]), _fmt(row["p50_ms"]), _fmt(row["p95_ms"])))
    lines += ["", "## By method", "",
              "| Provider | Method | n | Success | P50 | P95 | Max | First error |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for cell in summary["cells"]:
        lines.append("| %s | %s | %d | %.1f%% | %s | %s | %s | %s |" % (
            cell["provider"], cell["method"], cell["requests"], cell["success_pct"],
            _fmt(cell["p50_ms"]), _fmt(cell["p95_ms"]), _fmt(cell["max_ms"]),
            (cell["errors"][0] if cell["errors"] else "")))
    return "\n".join(lines) + "\n"


def _fmt(value):
    return "-" if value is None else "%.2f" % value


# --------------------------------------------------------------------------- #
# Self-test with a fake RPC server (no network required)
# --------------------------------------------------------------------------- #

class _FakeRPC(http.server.BaseHTTPRequestHandler):
    fail_rate = 0.0
    base_delay = 0.005

    def do_POST(self):                                              # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        time.sleep(self.base_delay + random.random() * self.base_delay)
        if random.random() < self.fail_rate:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")
            return
        payload = {"jsonrpc": "2.0", "id": body.get("id", 1), "result": "0x0"}
        data = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):                                    # silence
        pass


def selftest():
    failures = 0
    total = 0

    def check(label, condition, detail=""):
        nonlocal failures, total
        total += 1
        print(("[PASS] " if condition else "[FAIL] ") + label +
              ("" if condition else " - " + str(detail)))
        if not condition:
            failures += 1

    contract = {
        "address": "0x0000000000000000000000000000000000000001",
        "block_range": [100, 200],
        "topics": {"Transfer": "0x" + "ab" * 32},
        "methods": [
            {"name": "eth_getBalance", "params": ["${address}", "latest"]},
            {"method": "eth_getLogs", "name": "logs_transfer",
             "params": [{"address": "${address}", "fromBlock": "${from}",
                         "toBlock": "${to}", "topics": ["${topic:Transfer}"]}]},
        ],
    }

    calls = build_calls(contract, 1)
    check("two calls built", len(calls) == 2, len(calls))
    check("address substituted", calls[0]["params"][0] == contract["address"], calls[0])
    check("block range sent as hex quantities",
          calls[1]["params"][0]["fromBlock"] == "0x64" and calls[1]["params"][0]["toBlock"] == "0xc8",
          calls[1]["params"])
    check("hex_quantity passes tags and hex through",
          hex_quantity("latest") == "latest" and hex_quantity("0x10") == "0x10"
          and hex_quantity(16) == "0x10", hex_quantity(16))
    check("topic substituted",
          calls[1]["params"][0]["topics"][0] == contract["topics"]["Transfer"],
          calls[1]["params"])

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FakeRPC)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    url = "http://127.0.0.1:%d" % port

    try:
        # 1. happy path
        _FakeRPC.fail_rate = 0.0
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["SELFTEST_URL"] = url
            summary = run({"fake": {"url_env": "SELFTEST_URL"}}, calls,
                          requests=8, timeout=5, pacing=0, outdir=tmp, verbose=False)
            check("rows = providers x methods x requests",
                  summary["meta"]["rows"] == 1 * 2 * 8, summary["meta"]["rows"])
            check("all succeeded", all(c["success_pct"] == 100.0 for c in summary["cells"]),
                  [c["success_pct"] for c in summary["cells"]])
            check("p95 >= p50", all(c["p95_ms"] >= c["p50_ms"] for c in summary["cells"]))
            check("csv written", os.path.exists(os.path.join(tmp, "results.csv")))
            check("markdown written", os.path.exists(os.path.join(tmp, "summary.md")))

        # 2. failures are counted, not hidden
        _FakeRPC.fail_rate = 1.0
        with tempfile.TemporaryDirectory() as tmp:
            summary = run({"fake": {"url_env": "SELFTEST_URL"}}, calls,
                          requests=4, timeout=5, pacing=0, outdir=tmp, verbose=False)
            check("all requests counted as failures",
                  all(c["failed"] == 4 and c["success_pct"] == 0.0 for c in summary["cells"]),
                  summary["cells"])
            check("no latency emitted for failed-only cells",
                  all(c["p95_ms"] is None for c in summary["cells"]), summary["cells"])

        # 3. unreachable host is reported, not raised
        os.environ["SELFTEST_URL"] = "http://127.0.0.1:1"
        with tempfile.TemporaryDirectory() as tmp:
            summary = run({"fake": {"url_env": "SELFTEST_URL"}}, calls[:1],
                          requests=2, timeout=2, pacing=0, outdir=tmp, verbose=False)
            check("connection refused is a failure, not a crash",
                  summary["cells"][0]["success_pct"] == 0.0, summary["cells"])
            check("reason is captured", bool(summary["cells"][0]["errors"]),
                  summary["cells"][0]["errors"])

        # 4. missing env var is skipped cleanly
        os.environ.pop("SELFTEST_URL", None)
        with tempfile.TemporaryDirectory() as tmp:
            try:
                run({"fake": {"url_env": "SELFTEST_URL"}}, calls[:1], requests=1,
                    timeout=2, pacing=0, outdir=tmp, verbose=False)
                check("missing endpoint aborts with a message", False, "no exception")
            except SystemExit:
                check("missing endpoint aborts with a message", True)
    finally:
        server.shutdown()

    print()
    print("passed: %d, failed: %d (of %d checks)" % (total - failures, failures, total))
    return 0 if failures == 0 else 1


# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description="Benchmark RPC providers with your own contract payloads.",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--providers", help="providers JSON (URLs via env vars)")
    ap.add_argument("--contract", help="contract/payload JSON")
    ap.add_argument("--requests", type=int, default=30, help="requests per method per provider")
    ap.add_argument("--timeout", type=float, default=8.0, help="per-request timeout (s)")
    ap.add_argument("--pacing", type=float, default=0.0, help="seconds to sleep between requests")
    ap.add_argument("--out", default="runs/latest", help="output directory")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="run offline self-tests and exit")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if not (args.providers and args.contract):
        ap.error("--providers and --contract are required (or use --selftest)")

    with open(args.providers, encoding="utf-8") as fh:
        providers = json.load(fh)
    with open(args.contract, encoding="utf-8") as fh:
        contract = json.load(fh)

    calls = build_calls(contract, contract.get("chain_id", 1))
    run(providers, calls, args.requests, args.timeout, args.pacing, args.out, args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
