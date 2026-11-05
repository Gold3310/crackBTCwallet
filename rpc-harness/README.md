# `rpc-harness` — benchmark providers with *your* contract

`rpc-benchmarks/` reviews a vendor's published numbers. This folder produces your own:
real calls, your contract, your methods, your network, your traffic mix.

## What I need from you (and what I must not receive)

| Item | Safe to paste in chat? | Notes |
| --- | --- | --- |
| Contract address | **Yes** — public | plus chain (mainnet / Base / Arbitrum / …) |
| Functions & events you call | Yes | e.g. `balanceOf`, `Transfer` logs, `eth_call` selectors |
| Block range for `getLogs` | Yes | e.g. `20000000..20001000` |
| Regions / hosting | Yes | where your app runs (affects provider choice) |
| Target QPS and p95 budget | Yes | decides request count and whether the test is meaningful |
| **Alchemy API key / endpoint URL** | **No — never** | put it in an env var on the machine that runs the test |

A provider URL *contains* your key, so it is a secret. `bench.py` only ever reads URLs from
environment variables (`ALCHEMY_URL`, `QUICKNODE_URL`, …). Nothing secret goes into a config
file, a commit, or this conversation. If a key is ever pasted here, rotate it.

## One hard limit of this sandbox

This environment has **no outbound access to Alchemy** — verified, with DNS resolving but TCP
blocked:

```
https://eth-mainnet.g.alchemy.com/v2/demo   HTTP 000 (connection fails)
https://www.alchemy.com                     HTTP 000
https://api.github.com                      HTTP 200
https://pypi.org                            HTTP 200
```

So "always with Alchemy dev" here means: build, wire, validate and review — not live calls.
Live measurements must run where egress exists (your laptop, a server, or GitHub Actions —
a ready workflow is in `.github/workflows/rpc-bench.yml`). An API key does **not** change
this: the block is at the network layer, not authentication.

## Run it

```bash
export ALCHEMY_URL='https://eth-mainnet.g.alchemy.com/v2/<key>'
export QUICKNODE_URL='https://<name>.quiknode.pro/<key>/'   # optional 2nd provider

# 1. describe your contract
cp contracts.example.json contracts.mine.json    # then edit address, block_range, methods

# 2. measure
python3 bench.py --providers providers.example.json \
                 --contract contracts.mine.json \
                 --requests 30 --out runs/2026-11-05

# 3. read
cat runs/2026-11-05/summary.md
```

Outputs:

| File | Contents |
| --- | --- |
| `results.csv` | one row per provider × method × request: latency, ok/fail, error |
| `summary.md` | pooled + per-method p50/p95/max/success table, ranked by P95 |
| `summary.json` | the same, for tooling |

## Payload placeholders

`contracts.example.json` supports `${address}`, `${from}`, `${to}` and `${topic:NAME}`.
Block numbers are converted to **hex quantities** (`0x1312d00`) because that is what real
endpoints require — an integer `fromBlock` gets a JSON-RPC error, not a result.

## Validated without network access

`python3 bench.py --selftest` starts a fake JSON-RPC server on `127.0.0.1` and checks the
harness itself — 15 assertions, all passing here:

- placeholders substituted; block range emitted as hex
- row count = providers × methods × requests
- p95 ≥ p50; success rate computed per cell
- HTTP 500s counted as failures, never silently averaged into latency
- connection-refused reported as a failure with the reason, not a crash
- a missing env var aborts with a clear message instead of producing empty results

That is the part that can be proven offline. The numbers themselves are only meaningful
from a network that can actually reach the providers.

## Why this beats the vendor benchmark

The published dataset (see `../rpc-benchmarks/`) is read-only synthetic payloads, warmed
connections, one 24-hour window, from AWS runners, published by one of the vendors. This
harness measures the methods *you* actually call, with the historical/log filters *your*
contract needs, at the concurrency *you* run — which is the only data that can settle a
procurement decision. Use both: the vendor data to shortlist, this harness to sign.
