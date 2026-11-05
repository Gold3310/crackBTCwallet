# RPC provider benchmarks — review, data and tooling

A self-contained review of the Alchemy RPC benchmark export
([alchemy.com/benchmarks/data.md](https://www.alchemy.com/benchmarks/data.md)),
done to support a provider-selection decision.

**This folder is independent of the `crackBTCwallet` C code.** It was produced on the same
branch so the analysis and its tooling are versioned with the work; it changes no existing file.

## Start here

| If you want… | Open |
| --- | --- |
| The decision and the evidence | [`rpc-provider-review-2026-11-05.md`](./rpc-provider-review-2026-11-05.md) |
| Charts, at a glance | [`index.html`](./index.html) — open in a browser, no assets or network needed |
| The numbers in a spreadsheet | [`overview.csv`](./overview.csv) — 79 rows, one per chain × region × provider |
| To score providers against *your* traffic | [`weights.example.csv`](./weights.example.csv) + `benchmark_tools.py score` |
| To refresh everything from the live source | `benchmark_tools.py parse --url …` (see below) |

## The answer, in one table

| Situation | Provider |
| --- | --- |
| One vendor, multi-region, EVM + Solana | **Alchemy** (best average and P95 in 3 of 4 EVM regions; wins 14 of 19 measured cells) |
| EU Central traffic | **QuickNode** (8.15 ms vs Alchemy 13.04 ms — but judge it on P95, see report §11) |
| Logs and archive/historical block reads | **Alchemy** for logs, **Goldsky** for historical blocks (4x faster) |
| Solana | **Alchemy**; Triton or QuickNode as US East secondary |
| Failover that never surprises you | **Goldsky** — zero failed requests in every table reviewed |
| Cheapest tier, non-log, low QPS | **dRPC**, with a method allowlist (its `getLogs` runs 162–366 ms) |

Recommended shape: **Alchemy primary + Goldsky secondary** behind a per-method, per-region
health-checked router. Nothing in this dataset justifies a single-provider commitment — it is
published by one of the vendors about its own market. See the report's
*"Why you shouldn't trust these numbers on their own"* before quoting any figure upward.

## Files

| File | Purpose |
| --- | --- |
| `rpc-provider-review-2026-11-05.md` | The report. §1–§6 findings, §7–§20 appendices, scorecards, architecture, SLOs, RFP checklist |
| `overview.csv` | Transcribed provider rows: `chain,region,provider,avg_ms,p50_ms,p95_ms,success_pct` |
| `overview.json` | Same data nested `chain → region → provider`, for scripts |
| `benchmark_tools.py` | `parse` (Markdown → CSV/JSON), `summary` (winners, tails, anomalies), `score` (traffic-weighted ranking), `dashboard` (HTML) |
| `index.html` | Generated dashboard: 38 inline-SVG charts + global tables, light/dark, zero dependencies |
| `weights.example.csv` | Editable traffic mix for `score` — replace with your real regional split |
| `tests/fixture.md`, `tests/run_tests.py` | Parser regression test, covers both escaped and plain Markdown flavours |

## Quickstart

```bash
cd rpc-benchmarks

# refresh all data from the live export (full 10-chain coverage)
curl -sL https://www.alchemy.com/benchmarks/data.md -o data.md
python3 benchmark_tools.py parse --file data.md

# analysis
python3 benchmark_tools.py summary                          # winners, tail ratios, anomalies
python3 benchmark_tools.py score --weights weights.example.csv
python3 benchmark_tools.py dashboard --out index.html

# tests
python3 tests/run_tests.py
```

Only `curl` + Python 3.8+ standard library. No `pip install` step.

## Scope and provenance

- **Source window:** 2026-11-04 14:30 UTC → 2026-11-05 14:30 UTC (trailing 24h). The source
  regenerates every 5 minutes, so numbers drift; re-run `parse` before quoting them.
- **Transcribed in `overview.csv`:** EVM Overall, Ethereum and Optimism (all four regions),
  Arbitrum (global), Solana (global, US East, US West) — 19 cells, 79 rows.
- **Not transcribed, but one command away:** Base, World Chain, Arc, BNB Chain,
  Robinhood Chain, Arbitrum's other regions, Solana EU/AP.
- **Known gaps in the source itself:** P95 only (no P99), read-only synthetic payloads,
  warmed connections, no WebSockets or writes, no pricing, four EVM providers.

## Relationship to the access policy

This folder is **published-data analysis**, not network access: nothing here contacts
QuickNode, dRPC or Goldsky. Runtime access in this repository is restricted to Alchemy
Ethereum mainnet — see [`../docs/ACCESS-POLICY.md`](../docs/ACCESS-POLICY.md). The
comparison stays because it is the evidence behind the provider decision.
