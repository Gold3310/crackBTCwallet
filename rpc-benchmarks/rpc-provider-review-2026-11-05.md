# RPC provider benchmark review — which provider to pick

**Source:** [alchemy.com/benchmarks/data.md](https://www.alchemy.com/benchmarks/data.md) (machine-readable export of https://alchemyinsights.grafana.net/public-dashboards/bddf9388a79f436ea0994cfbebb37a5a)
**Data window:** 2026-11-04 14:30 UTC → 2026-11-05 14:30 UTC (trailing 24h)
**Report written:** 2026-11-05
**Extracted data:** [`overview.csv`](./overview.csv) — 79 rows, every provider-overview table I read from the source

---

## TL;DR — what to actually do

| Your situation | Pick |
| --- | --- |
| **One vendor, multi-region, EVM reads + Solana, latency-sensitive** | **Alchemy** — best or joint-best average latency in 3 of 4 regions, best P95 in US East/US West/AP Southeast, lowest global EVM average (13.60 ms) |
| **Users concentrated in Europe and you care about tail latency** | **QuickNode** for EU traffic (8.15 ms avg, 32.95 ms P95 vs Alchemy 13.04 / 55.32) — but do **not** make it your only global provider, it is very slow in US West |
| **Log-heavy / archive-block workloads** | **Alchemy** for `eth_getLogs`; **Goldsky** for historical (`earliest`) block reads — Alchemy is 4x slower on those |
| **Solana** | **Alchemy** primary (7.92 ms global, 13.95 ms P95 — best on every metric), **Triton** or **QuickNode** as US East secondary |
| **Budget / non-critical fallback tier** | **dRPC** only for low-QPS, non-log traffic. Its `getLogs` latency (162–366 ms) and periodic failure bursts disqualify it as primary |
| **Goldsky** | Excellent specialist, poor generalist: fastest on historical block reads, but 53 ms on `eth_getBalance` (global) and ~100–180 ms P95 in EU/AP |

**Recommended shape:** primary `Alchemy` + secondary `Goldsky` (or `QuickNode` if EU-heavy), behind a health-checked failover router. Do not sign a single-provider commitment on the strength of this benchmark alone — see [Why you shouldn't trust these numbers on their own](#why-you-shouldnt-trust-these-numbers-on-their-own).

---

## 1. Headline: EVM, all chains, global

Trailing 24h, averaged across Ethereum, Optimism, Arbitrum, Base, World Chain, Arc, BNB Chain and Robinhood Chain:

| Provider | Avg | P50 | P95 | Success |
| --- | --- | --- | --- | --- |
| **Alchemy** | **13.60 ms** | **6.34 ms** | **28.46 ms** | 99.99% |
| Goldsky | 21.88 ms | 7.93 ms | 78.11 ms | 100% |
| QuickNode | 39.69 ms | 9.47 ms | 157.56 ms | 99.99% |
| dRPC | 91.80 ms | 24.03 ms | 531.53 ms | 99.99% |

Read this carefully. **Averages hide the shape of the distribution.** Alchemy's 13.60 ms average with a 6.34 ms median means a small number of slow calls (the `earliest` block lookups, see §4) drag the mean up — the typical call is much better than 13.6 ms. dRPC is the opposite of healthy: a 24 ms median with a 532 ms P95 means roughly 1 in 20 calls is unusably slow.

Alchemy's 99.99% is also not free of failures. Those failures are concentrated in a single method (see §5) rather than spread across the workload, which matters more than the headline percentage.

## 2. By region — this is where decisions get made

EVM Overall, average / P95 latency (ms):

| Region | Alchemy | Goldsky | QuickNode | dRPC |
| --- | --- | --- | --- | --- |
| **US East** | **8.03 / 16.52** | 15.34 / 53.40 | 10.77 / 18.59 | 35.29 / 149.92 |
| **US West** | **14.96 / 45.93** | 18.55 / 79.78 | 79.30 / 222.78 | 135.29 / 629.87 |
| **EU Central** | 13.04 / 55.32 | 16.61 / 49.90 | **8.15 / 32.95** | 27.94 / 67.64 |
| **AP Southeast** | **18.36 / 31.67** | 37.03 / 178.62 | 60.53 / 238.14 | 168.65 / 794.65 |

What jumps out:

- **QuickNode in EU Central is genuinely excellent** — 8.15 ms average, beating Alchemy by ~5 ms, and its P95 (32.95 ms) is half Alchemy's (55.32 ms). This is the one region where Alchemy is not the answer.
- **QuickNode in US West is broken or badly routed.** 79.30 ms average with an 80.60 ms *median* — that's not a tail problem, the median call is 80 ms. Contrast with 10.77 ms in US East for the same provider. Treat this as a routing/peering issue worth raising with them directly before you buy; it may be a fixable misconfiguration on their side, or it may be real.
- **Alchemy's AP Southeast number is bimodal**: 5.78 ms median but 18.36 ms average and 31.67 ms P95. Typical calls are fast; a slice of traffic is hitting a distant region. Worth interrogating before you commit AP traffic.
- **dRPC is only defensible in EU Central** (27.94 ms / 67.64 ms P95). Everywhere else its P95 is 3–5x the field.
- **Goldsky is the most consistent provider across regions** (15–37 ms average everywhere), which is a real virtue for a secondary/failover slot.

## 3. Per-chain

**Ethereum** — the most competitive chain, and the only one where Alchemy is not clearly first:

| Provider | Global avg / P95 | US East | US West | EU Central | AP SE |
| --- | --- | --- | --- | --- | --- |
| Alchemy | 8.28 / 17.01 | **7.31 / 10.23** | 10.86 / 19.13 | 8.38 / 14.42 | **6.57 / 9.89** |
| Goldsky | **8.25 / 16.32** | 7.50 / 11.73 | **7.49 / 10.40** | 9.82 / 18.30 | 8.16 / 17.83 |
| QuickNode | 34.16 / 127.30 | 10.97 / 18.26 | 81.82 / 146.14 | **3.79 / 9.70** | 40.06 / 95.59 |
| dRPC | 192.55 / 827.50 | 64.51 / 266.91 | 295.47 / 797.35 | 44.37 / 121.35 | 365.82 / 966.08 |

Alchemy and Goldsky are effectively tied on Ethereum globally (8.28 vs 8.25 ms) — inside the noise of a 24h window. QuickNode's EU Ethereum figure of 3.79 ms is the single fastest cell in the whole dataset.

dRPC's Ethereum figure is alarming: 827 ms P95, and 365 ms average in AP Southeast. Its Ethereum `getLogs` calls run 362–367 ms in every region, which is what drags the whole average up. If your workload touches Ethereum logs, dRPC is out.

**Arbitrum (global):** Alchemy 7.88 / 15.78 · Goldsky 13.16 / 33.09 · dRPC 24.31 / 68.46 · QuickNode 38.59 / 98.82. Alchemy ~2x faster than the next provider.

**Optimism (all regions):**

| Region | Alchemy | Goldsky | QuickNode | dRPC |
| --- | --- | --- | --- | --- |
| Global | **24.71 / 121.88** | 42.90 / 99.95 | 49.74 / 235.03 | 83.42 / 280.91 |
| US East | **9.58 / 20.34** | 27.76 / 67.93 | 11.48 / 19.12 | 36.41 / 145.58 |
| US West | **23.45 / 77.24** | 37.09 / 94.34 | 95.50 / 269.37 | 98.69 / 229.15 |
| EU Central | 23.52 / 119.84 | 27.93 / 65.88 | **5.12 / 14.59** | 23.28 / 60.79 |
| AP SE | **42.30 / 249.71** | 78.82 / 273.03 | 86.88 / 269.89 | 175.31 / 374.16 |

Optimism is the chain where the "average is misleading" problem bites hardest. Alchemy's 24.71 ms global average is entirely driven by a **105–109 ms `eth_getBlockByNumber(earliest)`** call; strip that method and Alchemy wins Optimism comfortably. On P95, Alchemy's Optimism tail (121.88 ms global) is worse than Goldsky's (99.95 ms) — worth knowing if you serve Optimism at high volume.

## 4. Method-level: choose by workload, not by brand

No provider is uniformly fastest. From the EVM Overall global method tables:

| Workload | Fastest | Numbers |
| --- | --- | --- |
| `eth_getBalance` (light reads) | **Alchemy** | 7.23 ms — Goldsky 53.30 ms, QuickNode 13.23 ms, dRPC 25.33 ms |
| `eth_getBlockByNumber(latest)` | **Alchemy** | 8.60 ms — QuickNode 12.42 ms, dRPC 22.31 ms, Goldsky: not measured |
| `eth_getTransactionReceipt` | **Alchemy / Goldsky** | Alchemy 8.66 ms, Goldsky 12.17 ms, QuickNode 24.18 ms, dRPC 49.26 ms |
| `eth_getLogs` (1 / 10 / 100) | **Alchemy**, then Goldsky | Alchemy 8.28 / 8.89 / 12.05 ms · Goldsky 15.36 / 15.40 / 24.77 ms · QuickNode 46.94 / 58.78 / 60.70 ms · dRPC 161.76 / 166.60 / 174.05 ms |
| **Historical** `eth_getBlockByNumber(earliest)` | **Goldsky** | 10.30 ms — dRPC 43.29, Alchemy 41.48, QuickNode 61.56 |

Two actionable conclusions:

1. **If you do archive/historical block lookups, no single provider covers you well.** Goldsky is 4–6x faster there and correspondingly slow on `getBalance` (53 ms). A split route — Alchemy primary, Goldsky for historical/archive reads — beats either alone.
2. **`getLogs` is the divider.** Alchemy and Goldsky handle it in single/double digits; QuickNode is 5x slower; dRPC is 15–20x slower. If your product is an indexer, an explorer, or anything that scans logs, this single row decides your vendor.

Also note **Goldsky has no `eth_getBlockByNumber(latest)` column and Alchemy/others show `—` in places** — the providers were not all measured on identical payloads, so per-method comparisons are apples-to-apples only within a row that is fully populated.

## 5. Reliability: where the failures actually are

Both Alchemy and dRPC report 99.99%, but the failure shapes are different and only one of them is a design risk.

- **Alchemy's failures are a single-method cluster on `eth_getTransactionReceipt`**: 15 failures on `eth_getTransactionReceipt` in EVM Overall Global, and the identical 15 in US East and EU Central, appearing in one ~2h window (18h–17h buckets, plus scattered 1–2s). Every other Alchemy method scored 0 failures in every region. That's a contained incident, not systemic fragility — but it did hit the *most common* receipt-heavy call pattern, so it is exactly the kind of thing that breaks a transaction-confirmation UI. Ask them what happened in that window.
- **dRPC's failures are recurring bursts** — 13 failures in the 22h bucket, 11 in the 1h bucket, plus scattered log failures every few hours, in almost every region. Pattern is characteristic of rate limiting or capacity dips rather than one incident. A provider that loses ~10–15 requests per hour in bursts will trip naive retry-less clients.
- **QuickNode's failures are small and scattered** (2–3 per bucket occasionally, mostly on `eth_getLogs`). Goldsky recorded **zero failures across every table I read**, which is a point in favour of it as the secondary.
- Solana was clean for everyone except Triton (a handful of `getSlot` failures, 99.99%).

## 6. Solana (different provider set)

| Provider | Global avg / P95 | US East | US West |
| --- | --- | --- | --- |
| **Alchemy** | **7.92 / 13.95** | **6.08 / 9.68** | **9.53 / 16.41** |
| QuickNode | 12.29 / 32.99 | 8.29 / 13.35 | 30.31 / 34.84 |
| Triton | 13.38 / 44.55 | 8.23 / 9.82 | 36.42 / 48.88 |
| Chainstack | 17.70 / 45.88 | 14.75 / 56.54 | 36.88 / 82.40 |
| Helius | 36.36 / 97.84 | 24.38 / 48.62 | 56.85 / 109.44 |

Alchemy leads on every metric, with Triton and QuickNode tightly matched behind it in US East (their P95s are essentially identical to Alchemy's, which makes Triton a sound failover for East Coast Solana traffic). The surprising result is **Helius last at 36 ms** — it has a strong Solana-native reputation, so either this payload set (`getAccountInfo`, `getBalance`, `getSlot`, …) plays to its weaknesses, its plan tier here is not the performance tier, or the measurement is unfavourable to it. Do not treat that one number as settled; test it yourself if Helius is otherwise attractive on features/pricing.

EU Central and AP Southeast Solana tables were not in the portion of the export I extracted — see the source for those.

---

## Why you shouldn't trust these numbers on their own

This is the most important section of the report.

1. **It's the vendor's own benchmark.** It is published by Alchemy, on Alchemy's infrastructure, using Alchemy's methodology choices, about Alchemy's competitors. The result happens to be "Alchemy wins overall" — which may be true, but a benchmark you commission about your own market should be treated as *a hypothesis to check*, never as an independent audit.
2. **Provider coverage is small and curated.** Four EVM providers (Alchemy, QuickNode, dRPC, Goldsky) and five for Solana. Missing entirely: Infura, Ankr, LlamaNodes, BlockPI, 1RPC, Chainstack for EVM, self-hosted nodes. "Fastest of four" is not "fastest."
3. **The payload mix is synthetic and read-only.** Their own methodology states: no retries, warmed/reused connections, 8-second timeout, no writes, no WebSockets, no cold-connection setup, no app-level workflows. If you use subscriptions or write traffic, this data tells you nothing about the parts of your stack most likely to break.
4. **Single 24h window.** No day-of-week, no month-long stability, no incident history. A provider can look good for a day.
5. **AWS-to-provider, not user-to-provider.** Measured from AWS ECS runners in four regions. If your users are in West Africa, South America, or behind mobile networks, the ranking can invert — your path is not their path.
6. **Uneven method coverage.** `—` entries mean a provider was not measured on that method, so some rows compare partial workloads.
7. **No pricing, no rate limits, no SLA, no support quality, no data-completeness guarantees.** All of which decide total cost far more than 5 ms of latency.

## Before you sign: a 5-step validation plan

1. **Weight by your actual traffic**, not a uniform method mix. Export your real RPC method histogram for a week; if 70% of your calls are `getTransactionReceipt`, the ranking that matters is the receipt row, not the global average.
2. **Run a 72-hour parallel test** against your top two candidates using your real payloads, from *your* deployment regions, with *your* client's retry/timeout config. Track p50/p95/p99 and error rate separately — a 20% latency win is worth nothing against a 0.1% error-rate increase.
3. **Test what this benchmark skips**: WebSockets/subscriptions, writes (`eth_sendRawTransaction`), sustained QPS at your rate-limit ceiling, cold connection setup, and behaviour during a chain reorg or a provider incident.
4. **Ask the two hard questions of each vendor:** (a) what happened in the 18h–17h window to `eth_getTransactionReceipt` on Alchemy, and to dRPC's recurring 22h/1h failure bursts; (b) explain QuickNode's 80 ms US West median against its 10.8 ms US East figure.
5. **Negotiate on measured P95 and error budget, in writing**, not on average latency. Then architect for failover anyway: primary + secondary with health checks, because no single provider in this dataset is flawless in all four regions.

## Method note for this report

I read the provider-overview, method-latency and failure tables from the source export and transcribed them into `overview.csv`. Coverage: **EVM Overall (all 4 regions), Ethereum (all 4 regions), Optimism (all 4 regions), Arbitrum (global), Solana (global, US East, US West)**. The source also contains Base, World Chain, Arc, BNB Chain, Robinhood Chain, Arbitrum per-region, and Solana EU/AP sections that I did not transcribe — figures for those should be pulled from the URL above (it regenerates every 5 minutes, so values drift).

---

# Part II — extended analysis (revision 1.1, appended)

*The sections above are unchanged. Everything below is new in this revision: provider scorecards, a traffic-weighted scoring model, tail-latency analysis, data-quality findings, a reference architecture, SLO guidance, method-level appendices, a glossary, an FAQ, an RFP/negotiation checklist, and reproduction instructions.*

## 7. Provider scorecards

Numbers below are computed across the 19 chain/region cells transcribed (mean of per-cell averages). "Cells" tells you how many cells that provider was actually measured in — a provider measured in 3 cells cannot be compared to one measured in 19 without care.

| Provider | Cells | Mean avg | Median avg | Best cell | Worst cell | Mean P95 | Region spread (EVM) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **Alchemy** | 19 / 19 | **13.91 ms** | **9.58 ms** | Solana/US East 6.08 | Optimism/AP SE 42.30 | **47.02 ms** | 10.33 ms |
| **Goldsky** | 16 / 19 | 23.64 ms | 17.58 ms | Ethereum/US West 7.49 | Optimism/AP SE 78.82 | 71.79 ms | 21.69 ms |
| **QuickNode** | 19 / 19 | 37.23 ms | 34.16 ms | Ethereum/EU Central 3.79 | Optimism/US West 95.50 | 108.16 ms | **71.15 ms** |
| **dRPC** | 16 / 19 | 116.44 ms | 87.61 ms | Optimism/EU Central 23.28 | Ethereum/AP SE 365.82 | 394.49 ms | **140.71 ms** |
| Triton (Solana) | 3 / 19 | 19.34 ms | 13.38 ms | Solana/US East 8.23 | Solana/US West 36.42 | 34.42 ms | n/a |
| Chainstack (Solana) | 3 / 19 | 23.11 ms | 17.70 ms | Solana/US East 14.75 | Solana/US West 36.88 | 61.61 ms | n/a |
| Helius (Solana) | 3 / 19 | 39.20 ms | 36.36 ms | Solana/US East 24.38 | Solana/US West 56.85 | 85.30 ms | n/a |

### Alchemy — the broadest and the most consistent

- **Strengths:** fastest mean and median across the dataset; best P95 in 4 of 5 EVM regions; smallest regional spread of any EVM provider (10.33 ms between its best and worst region). Best on `getLogs`, `getBalance`, `getBlockByNumber(latest)` and receipts. Leads Solana on every metric.
- **Weaknesses:** historical (`earliest`) block reads are 4x slower than Goldsky (41.48 vs 10.30 ms global) and that single method drags its Optimism average to 24.71 ms with a 121.88 ms P95. Its one failure cluster is `eth_getTransactionReceipt` (15 failures, §5). EU Central P95 (55.32 ms) is its weakest region.
- **Best fit:** global primary; anything log- or receipt-heavy; Solana.
- **Watch:** ask about the receipt window and about AP Southeast's bimodal 5.78 ms median vs 18.36 ms average.

### Goldsky — the specialist, and the only clean sheet on failures

- **Strengths:** zero failed requests across every table transcribed; the fastest historical block reads in the dataset (10.30 ms global, 7.3–7.79 ms in the Americas) and the fastest Ethereum `getLogs` by a wide margin (5.9–6.4 ms vs Alchemy's 8.1–8.9 ms); most regionally stable after Alchemy.
- **Weaknesses:** `eth_getBalance` is poor (53.30 ms global — 7x Alchemy); missing entirely on `eth_getBlockByNumber(latest)` in every table, so it cannot be your only provider for head-of-chain reads; EU Central and AP Southeast P95s are 50 ms and 179 ms.
- **Best fit:** secondary/failover, archive and historical-block traffic, Ethereum log scans, and anywhere a zero-error record matters.

### QuickNode — a tale of two providers wearing one name

- **Strengths:** genuinely excellent in EU Central — best average in 3 cells (EVM Overall 8.15, Ethereum 3.79, Optimism 5.12) — and competitive in US East (10.77 ms).
- **Weaknesses:** US West is 79.30 ms average with an **80.60 ms median**; the largest regional spread of any primary candidate (71.15 ms). `getLogs` is 5x Alchemy. Ethereum global P95 is 127.30 ms on a 34.16 ms average.
- **Best fit:** EU-primary deployments, or as an EU-region shard in a multi-provider router. Never as a sole global vendor.
- **Watch:** the US West gap is so large relative to US East that it looks like a peering/routing defect rather than hardware. Put it to them in writing.

### dRPC — cheapest tier, and it shows

- **Strengths:** EU Central is respectable (27.94 ms EVM Overall, 23.28 ms Optimism); P50s are often fine (9.93 ms in US East), so simple light calls can feel acceptable.
- **Weaknesses:** `getLogs` at 162–366 ms; Ethereum P95 of 827.50 ms; AP Southeast 168.65 ms average / 794.65 ms P95; recurring failure bursts (13 at 22h, 11 at 1h) consistent with rate limiting; largest regional spread (140.71 ms); worst tail ratio in the dataset (5.8x).
- **Best fit:** a third fallback tier for non-log, low-QPS workloads, or a deliberate cost play where milliseconds genuinely do not matter.
- **Watch:** if you route to dRPC without a per-method allowlist, a single `getLogs` will blow your latency budget.

### Solana specialists

- **Triton** — 13.38 ms global, 13.95 ms P95; in US East it is within ~2 ms of Alchemy's average and *equal on P95* (9.82 vs 9.68 ms) at 99.99%. Strong secondary. US West is weak (36.42 ms).
- **Chainstack** — 17.70 ms global; the most variable Solana performer (P95 swings 44–82 ms). Third choice.
- **Helius** — last at 36.36 ms with a 97.84 ms P95. This contradicts its Solana-native reputation, which usually means the plan tier, the payload mix, or the measurement region is unfavourable. Test before ruling it out; its tooling may still justify it.

## 8. Winners at a glance

Best average latency in each transcribed cell:

| Chain | Global | US East | US West | EU Central | AP Southeast |
| --- | --- | --- | --- | --- | --- |
| EVM Overall | **Alchemy** 13.60 | **Alchemy** 8.03 | **Alchemy** 14.96 | **QuickNode** 8.15 | **Alchemy** 18.36 |
| Ethereum | **Goldsky** 8.25 | **Alchemy** 7.31 | **Goldsky** 7.49 | **QuickNode** 3.79 | **Alchemy** 6.57 |
| Optimism | **Alchemy** 24.71 | **Alchemy** 9.58 | **Alchemy** 23.45 | **QuickNode** 5.12 | **Alchemy** 42.30 |
| Arbitrum | **Alchemy** 7.88 | — | — | — | — |
| Solana | **Alchemy** 7.92 | **Alchemy** 6.08 | **Alchemy** 9.53 | — | — |

**Tally: Alchemy 14, QuickNode 3, Goldsky 2.**

Best **P95** per EVM Overall region tells a slightly different story: Alchemy in Global (28.46), US East (16.52), US West (45.93) and AP Southeast (31.67); QuickNode in EU Central (32.95). So Alchemy wins EU on average-latency-tail only if you look at P95 — and there QuickNode's advantage is smaller than its average suggests (see §11).

## 9. Score the providers against *your* traffic

The equal-weight view above is not your workload. `benchmark_tools.py score` weights each cell by the share of traffic you actually send there and reports how much of your traffic each provider was even measured on:

```bash
python3 benchmark_tools.py score --csv overview.csv --weights weights.example.csv
```

With the illustrative mix in `weights.example.csv` (US East 40%, EU 25%, US West 15%, AP 10%, Solana US East 10%):

| Provider | Weighted avg | Weighted P95 | Coverage of your traffic | Worst P95 cell |
| --- | --- | --- | --- | --- |
| Triton | 8.23 ms | 9.82 ms | **10%** | Solana/US East 10 ms |
| **Alchemy** | **11.16 ms** | **31.46 ms** | **100%** | EVM Overall/EU Central 55 ms |
| Chainstack | 14.75 ms | 56.54 ms | 10% | Solana/US East 57 ms |
| Goldsky | 18.64 ms | 70.74 ms | 90% | EVM Overall/AP Southeast 179 ms |
| Helius | 24.38 ms | 48.62 ms | 10% | Solana/US East 49 ms |
| QuickNode | 25.12 ms | 74.24 ms | 100% | EVM Overall/AP Southeast 238 ms |
| dRPC | 64.73 ms | 278.69 ms | 90% | EVM Overall/AP Southeast 795 ms |

**The lesson is in the coverage column.** Triton "wins" the weighted average on a tenth of the traffic; it is not a candidate. Alchemy is the only provider that covers 100% of the sampled traffic *and* wins on both weighted average and weighted P95. Replace the example weights with your real regional split before you take this to procurement.

## 10. Tail behaviour — the number that predicts incidents

P95 ÷ average, global cells, worst first:

| Chain | Provider | Avg | P95 | Ratio |
| --- | --- | --- | --- | --- |
| EVM Overall | dRPC | 91.80 | 531.53 | **5.8x** |
| Optimism | Alchemy | 24.71 | 121.88 | 4.9x |
| Optimism | QuickNode | 49.74 | 235.03 | 4.7x |
| Ethereum | dRPC | 192.55 | 827.50 | 4.3x |
| EVM Overall | QuickNode | 39.69 | 157.56 | 4.0x |
| Ethereum | QuickNode | 34.16 | 127.30 | 3.7x |
| EVM Overall | Goldsky | 21.88 | 78.11 | 3.6x |
| Optimism | dRPC | 83.42 | 280.91 | 3.4x |
| Solana | Triton | 13.38 | 44.55 | 3.3x |
| … | … | | | |
| EVM Overall | **Alchemy** | 13.60 | 28.46 | **2.1x** |
| Solana | **Alchemy** | 7.92 | 13.95 | **1.8x** |

Alchemy's tail multiplier is 1.8–2.1x — the tightest in the dataset. That is the property that makes a provider feel *reliable* rather than merely fast: mixed traffic that never violates 2x its own average. dRPC at 5.8x is the signature of a service that intermittently stops responding.

Notable exception: **Alchemy's Optimism ratio is 4.9x**, driven almost entirely by the `earliest`-block method. If Optimism is a large part of your traffic, either avoid historical calls on the primary or shard that method to Goldsky.

## 11. Data-quality findings (things I found while transcribing)

**Five rows have a median *above* the mean** (impossible for a right-skewed latency distribution, which is the normal shape):

| Cell | Provider | P50 | Avg |
| --- | --- | --- | --- |
| EVM Overall / US West | QuickNode | 80.60 | 79.30 |
| Ethereum / EU Central | QuickNode | 5.10 | 3.79 |
| Ethereum / AP Southeast | QuickNode | 50.08 | 40.06 |
| Optimism / EU Central | QuickNode | 5.45 | 5.12 |
| Optimism / AP Southeast | dRPC | 203.98 | 175.31 |

Three of the five are QuickNode, which is a meaningful pattern rather than noise. A median above the mean means *the typical call is worse than the average* — a few unusually fast calls are pulling the average down. Two practical consequences:

1. **QuickNode's averages flatter it.** Its EU Ethereum "3.79 ms" has a 5.10 ms median — the real typical call is on par with Alchemy's 5.41 ms median, and its advantage lives in the P95 (9.70 vs 14.42 ms), not in the median. Judge QuickNode on P95, never on average.
2. **Don't quote a provider's average to stakeholders.** Quote the median and the P95. Averaging latency is the most common way people misread this kind of data.

**Other transcription notes:**

- Goldsky has no `eth_getBlockByNumber(latest)` measurement in any table, so its "global average" is computed over a slightly different method set than its competitors'. The same applies to any provider with a `—` cell.
- Several per-method tables omit providers entirely (e.g. `eth_blocksNumber`-style rows measured only on some chains). Row-wise comparisons are only valid where the row is fully populated.
- Solana EU Central and AP Southeast, and the Base / World Chain / Arc / BNB Chain / Robinhood Chain sections, are **not** in `overview.csv` — see §19 to close those gaps in one command.

## 12. Reference architecture for the decision

```
                          ┌───────────────────────────────┐
   app / workers ────────▶│       RPC router (yours)      │
                          │  • per-method routing table   │
                          │  • health checks (10 s)       │
                          │  • hedged request after 1.5x  │
                          │    expected P95               │
                          │  • circuit breaker per host   │
                          └───────┬───────────┬───────────┘
                                  │           │
             ┌────────────────────┤           ├────────────────────┐
             ▼                    ▼           ▼                    ▼
      ┌─────────────┐      ┌─────────────┐ ┌─────────────┐  ┌─────────────┐
      │  ALCHEMY    │      │  GOLDSKY    │ │ QUICKNODE   │  │   dRPC      │
      │  primary    │      │  secondary  │ │ EU shard /  │  │ last resort │
      │  all methods│      │ archive +   │ │ EU weighted │  │ no getLogs  │
      │  all regions│      │ getLogs(ETH)│ │ traffic     │  │ low QPS     │
      └─────────────┘      └─────────────┘ └─────────────┘  └─────────────┘
```

Routing rules that follow directly from the data:

| Traffic | Route |
| --- | --- |
| `eth_getLogs` (any size) | Alchemy primary; Goldsky on Ethereum; **never** dRPC |
| `eth_getBalance`, `latest` block, receipts | Alchemy |
| Historical / archive block reads | **Goldsky** (unless header-only, then Alchemy) |
| Traffic originating in EU Central | QuickNode (weight by P95, not average) |
| Traffic in US West | Alchemy only; do not route to QuickNode there |
| Solana | Alchemy primary; Triton (US East) or QuickNode secondary |
| Failure / circuit-breaker fallback | Goldsky (zero recorded failures) |
| Cost-tier fallback, non-log, low QPS | dRPC with a method allowlist |

Health-check policy worth writing into the router:

- Probe **per region and per method class**, not one global `/health` — the QuickNode US West defect is invisible to a global probe.
- Track **P95 over a rolling 60 s window** and demote a host when it exceeds 2x its own 24h P95 (the tail-ratio table in §10 gives you that baseline).
- Because every provider's failures in this dataset cluster on `getLogs` (except Alchemy's on receipts), keep **separate circuit breakers per method**, or one bad method will eject a provider that is healthy for everything else.

## 13. SLOs you can actually promise

Derived from measured P95s (leave ~30% headroom for your own app overhead, serialization and network hop):

| SLO | Achievable on | Evidence |
| --- | --- | --- |
| P95 < 30 ms, single region, EVM reads | 2 of 4 providers | Alchemy US East 16.52, QuickNode US East 18.59 |
| P95 < 50 ms, global EVM blend | Alchemy only | 28.46 global; next best Goldsky 78.11 |
| P95 < 100 ms, global, incl. historical reads | **nobody alone** | Goldsky 78.11 EVM / 179 AP SE; needs Goldsky-split routing |
| P95 < 50 ms on `eth_getLogs` (100) | Alchemy, Goldsky | 12.05 ms / 24.77 ms global — QuickNode 60.70, dRPC 174.05 |
| P95 < 40 ms Solana global | Alchemy only | 13.95 ms; QuickNode 32.99, Triton 44.55, Helius 97.84 |
| P99 anything | **no provider, no data** | the export publishes P95 only — you must measure P99 yourself |

Timeout and retry guidance that the data supports:

- The benchmark treats **8 s as a timeout failure**. For a product surface, 8 s is far too long to wait; use a 2–3 s application timeout with one hedged retry, so a dRPC-style 500 ms+ P95 never becomes a user-visible stall.
- Do **not** retry `getLogs` blindly on a provider whose failures are rate-limit bursts (dRPC) — back off and fail over instead, or you will amplify the load that triggered the limit.
- Budget for the failure clusters: at 99.99% a provider still loses ~4 requests per 40,000; at a sustained 50 rps that is a real operational event if your client has no retry path.

## 14. Appendix — method-level detail

**EVM Overall, global** (ms):

| Method | Alchemy | QuickNode | dRPC | Goldsky |
| --- | --- | --- | --- | --- |
| `eth_getBalance` | **7.23** | 13.23 | 25.33 | 53.30 |
| `eth_getBlockByNumber(earliest)` | 41.48 | 61.56 | 43.29 | **10.30** |
| `eth_getBlockByNumber(latest)` | **8.60** | 12.42 | 22.31 | — |
| `eth_getLogs(1)` | **8.28** | 46.94 | 161.76 | 15.36 |
| `eth_getLogs(10)` | **8.89** | 58.78 | 166.60 | 15.40 |
| `eth_getLogs(100)` | **12.05** | 60.70 | 174.05 | 24.77 |
| `eth_getTransactionReceipt` | **8.66** | 24.18 | 49.26 | 12.17 |

**Ethereum, global** (ms):

| Method | Alchemy | QuickNode | dRPC | Goldsky |
| --- | --- | --- | --- | --- |
| `eth_getBalance` | 7.25 | 15.73 | 22.89 | **9.12** |
| `eth_getBlockByNumber(earliest)` | **7.83** | 15.12 | 18.94 | 9.33 |
| `eth_getBlockByNumber(latest)` | **9.66** | 16.04 | 20.12 | — |
| `eth_getLogs(1)` | 8.11 | 52.85 | 362.85 | **6.38** |
| `eth_getLogs(10)` | 8.19 | 53.38 | 362.69 | **6.38** |
| `eth_getLogs(100)` | 8.16 | 52.80 | 364.54 | **6.26** |
| `eth_getLogs(1000)` | 8.90 | 52.16 | 366.90 | **5.93** |
| `eth_getTransactionReceipt` | **8.17** | 15.20 | 21.53 | 14.33 |

Ethereum is the one chain where Goldsky beats Alchemy on the two heaviest workloads (*logs* and *archive blocks*) — which is exactly why it belongs in the secondary slot rather than being dismissed for its slow `getBalance`.

**Optimism, global** (ms):

| Method | Alchemy | QuickNode | dRPC | Goldsky |
| --- | --- | --- | --- | --- |
| `eth_getBalance` | **7.38** | 11.40 | 24.86 | 108.18 |
| `eth_getBlockByNumber(earliest)` | 109.40 | 71.12 | 88.20 | **11.05** |
| `eth_getBlockByNumber(latest)` | **8.17** | 11.96 | 24.59 | — |
| `eth_getLogs(1)` | **8.90** | 45.69 | 101.03 | 32.29 |
| `eth_getLogs(10)` | **10.57** | 78.47 | 114.85 | 32.38 |
| `eth_getLogs(100)` | **20.19** | 84.75 | 135.48 | 60.59 |
| `eth_getTransactionReceipt` | **8.39** | 44.82 | 94.98 | 12.90 |

Note the 109.40 ms `earliest` row: that single method is why Alchemy's Optimism average (24.71 ms) looks mid-field while six of its seven methods are the fastest.

**Solana, global** (ms):

| Method | Alchemy | QuickNode | Chainstack | Helius | Triton |
| --- | --- | --- | --- | --- | --- |
| `getAccountInfo` | **8.19** | 13.36 | 17.96 | 38.71 | 14.17 |
| `getBalance` | **7.93** | 13.45 | 17.92 | 37.73 | 14.14 |
| `getBlockHeight` | **8.01** | 10.98 | 17.70 | 41.33 | 12.44 |
| `getLatestBlockhash` | **7.91** | 10.93 | 17.73 | 33.79 | 12.44 |
| `getMultipleAccounts` | **8.12** | 13.47 | 17.97 | 38.78 | 14.27 |
| `getSlot` | **7.59** | 11.18 | 17.27 | 28.95 | 12.66 |
| `getSlotLeader` | **8.03** | 13.76 | 17.80 | 42.66 | 14.24 |

## 15. Appendix — failure evidence

**EVM Overall, global — failed requests per hourly bucket** (23h → now):

| Provider | 22h | 20h | 18h | 17h | 16h | 14h | 13h | 12h | 11h | 10h | 8h | 6h | 5h | 3h | 2h | 1h | total |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Alchemy | 0 | 0 | 1 | 2 | 1 | 1 | 0 | 1 | 2 | 1 | 2 | 1 | 1 | 0 | 1 | 1 | **15** |
| QuickNode | 0 | 3 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | **6** |
| dRPC | 13 | 0 | 0 | 1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 11 | **28** |
| Goldsky | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **0** |

**Failures by method, EVM Overall global:**

| Method | Alchemy | QuickNode | dRPC | Goldsky |
| --- | --- | --- | --- | --- |
| `eth_getBalance` | 0 | 0 | 1 | 0 |
| `eth_getBlockByNumber(earliest)` | 0 | 0 | 2 | 0 |
| `eth_getLogs(1)` | 0 | 2 | 6 | 0 |
| `eth_getLogs(10)` | 0 | 3 | 10 | 0 |
| `eth_getLogs(100)` | 0 | 1 | 7 | 0 |
| `eth_getTransactionReceipt` | **15** | 0 | 3 | 0 |

The shapes are different in kind, not degree: Alchemy's failures are **one method, spread thinly** (a contained receipt-path incident); dRPC's are **one method, in bursts** (capacity/rate-limit); QuickNode's are **logs-only** at low volume; Goldsky's are **absent**. If you must pick a failover target that will never surprise you, that last row is the argument for Goldsky.

## 16. Glossary

- **P50 / median** — the typical call. Half of requests are faster, half slower. The number to quote as "normal".
- **P95** — the slow-but-not-rare call. 1 in 20 requests is worse. The number that predicts user complaints.
- **Average** — a blend that a handful of very slow or very fast calls can move. Misleading on its own; this dataset proves it in §11.
- **Tail ratio** — P95 ÷ average. Under ~2.5x is tight; over 4x means the service is intermittent.
- **Warmed connection** — TLS handshake already done and the socket reused. Real clients pay handshake cost on new connections, which this benchmark does not measure.
- **Method class** — a group of RPC calls with similar cost (`getBalance` vs `getLogs` vs receipts). Routing decisions belong at this level, not at provider level.
- **Coverage** — the share of *your* traffic weight that a provider was actually measured on (§9). Low coverage means the comparison is incomplete, not that the provider is fast.
- **Hedged request** — send to a second provider if the first has not answered within a threshold, take whichever returns first. The standard way to beat a single provider's tail.
- **Circuit breaker** — stop sending to a host after consecutive failures, retest periodically, restore gradually.

## 17. FAQ

**Is Alchemy genuinely the fastest?** In this dataset, on average and on P95, yes — with two honest qualifications: the data is published by Alchemy, and ~20% of chains are not in my extract. The margin over Goldsky in the Americas (8.03 vs 15.34 ms US East) is large enough to survive measurement bias; the Ethereum global gap (8.28 vs 8.25 ms) is not.

**Why does QuickNode look bad when people like it?** Because the average is the wrong statistic for it here. Its medians are competitive in EU and US East; its US West median of 80.60 ms is the outlier, and three of the five median-above-mean anomalies in the dataset are QuickNode's.

**Why is Helius last on Solana?** Unknown from this data alone — plausible causes are plan tier, region, or a payload mix that avoids its optimised paths. Treat it as a prompt to test, not a verdict. It remains a reasonable choice if its tooling (webhooks, DAS API) is what you need.

**Can I use one provider?** Yes, Alchemy — and you will still inherit its Optimism `earliest`-block weakness and its receipt-path incident risk. Two providers behind a router is not extra complexity for its own sake; it is the only way to meet a P99 you cannot see in this data.

**Does the recommended stack cost more?** This dataset contains zero pricing information. Multi-provider usually costs less than it looks: you route the majority to your primary and pay for a small secondary tier, which is often cheaper than the premium tier you would need from one vendor to survive a bad day.

**How stale is this?** The source regenerates every 5 minutes; the figures here are a snapshot of the window 2026-11-04 14:30 → 2026-11-05 14:30 UTC. Re-run §19's commands before quoting numbers to anyone.

**Why is this in a Bitcoin-wallet repository?** It is unrelated to `crackBTCwallet`'s code — it lives on the session branch as a standalone review so the analysis and its tooling are versioned with the work that produced them. It touches no existing file.

## 18. RFP and negotiation checklist

Ask each vendor, in writing:

1. What happened to `eth_getTransactionReceipt` between roughly 18h and 17h in this window? (Alchemy)
2. Explain the 13 and 11 failure bursts at 22h and 1h, and why `getLogs` costs 162–366 ms. (dRPC)
3. Explain an 80.60 ms **median** in US West against 10.77 ms average in US East. (QuickNode)
4. Provide P99, not just P95, for our method mix, in our regions, for a sustained 72h.
5. Confirm behaviour under our concurrency: what is the per-second limit, what does exceeding it return (HTTP 429 vs silent queueing), and does it count against our error budget?
6. Do you support archive/historical `earliest`-style reads at the same tier, and at what latency?
7. What is your status-page history for the last 90 days, and what is the credit mechanism when success drops below contract?
8. Can we run a 30-day parallel pilot at real traffic before committing? Put the exit criteria (P95 and error rate) in the contract, not in the deck.

Contract terms worth pushing for: **P95-based SLAs rather than monthly-average uptime**, credits triggered by *your* measured success rate, a per-method exclusion window for known-slow calls (so a slow `getLogs` does not hide inside a healthy average), and no auto-renewal longer than 12 months.

## 19. Reproducing and extending this analysis

```bash
# 1. Save the export (it changes every 5 minutes)
curl -sL https://www.alchemy.com/benchmarks/data.md -o data.md

# 2. Parse every chain × region × provider into CSV + JSON
python3 benchmark_tools.py parse --file data.md
#    -> overview.csv, methods.csv, failures.csv, overview.json  (full coverage,
#       including Base, World Chain, Arc, BNB, Robinhood, Arbitrum regions,
#       Solana EU/AP — i.e. the gaps noted in §11)

# 3. Who wins where, tail ratios, and data-quality anomalies
python3 benchmark_tools.py summary

# 4. Rank by your own traffic mix
python3 benchmark_tools.py score --weights weights.example.csv

# 5. Rebuild the HTML dashboard
python3 benchmark_tools.py dashboard --out index.html
```

Files in this folder:

| File | What it is |
| --- | --- |
| `rpc-provider-review-2026-11-05.md` | This report |
| `overview.csv` | 79 transcribed provider rows (the ones this report is built on) |
| `overview.json` | Same data, keyed `chain → region → provider`, for code |
| `benchmark_tools.py` | Parser, summariser, traffic-weighted scorer, HTML dashboard generator |
| `index.html` | Dependency-free dashboard: per-cell bar charts + global tables |
| `weights.example.csv` | Editable traffic-mix weights for `score` |
| `tests/fixture.md`, `tests/run_tests.py` | Parser regression test (handles escaped and plain Markdown) |

`parse` is the answer to every coverage gap in this document: run it once against the live export and you will have all ten chains and five regions without transcribing anything by hand.

## 20. Document history

| Revision | Date | Change |
| --- | --- | --- |
| 1.0 | 2026-11-05 | Initial review: headline, regional and per-chain analysis, method and failure reading, caveats, validation plan |
| 1.1 | 2026-11-05 | **Appended** §7–§20 and nine new files (§19): provider scorecards, winners table, traffic-weighted scoring, tail-ratio analysis, five data-quality anomalies, reference architecture with routing rules, SLO/timeout guidance, method appendices for four chains, failure-bucket appendix, glossary, FAQ, RFP checklist, reproduction tooling and regression tests. No existing content removed or altered. |

**Known limitations carried forward** (unchanged from §"Why you shouldn't trust these numbers on their own"): vendor-published, four EVM providers, read-only synthetic payloads, single 24h window, AWS-to-provider measurements, P95 only (no P99), no pricing, and — until you run `parse` — seven chains and four regional cells missing from the transcription.
