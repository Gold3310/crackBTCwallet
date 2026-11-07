# Prior art: what already exists on GitHub for each piece

Searched 2026-11-05 via the GitHub search API (`gh search repos`, `gh api repos/<r>`).
Stars / last-push / licence are as returned by the API on that date.

This repo is **MIT** (`LICENSE`, Luis Alberto, 2020). That matters below: GPL-2.0 and
AGPL-3.0 projects must be **called as external tools**, never vendored or imported, or the
licence of this repo would have to change.

---

## 1. RPC endpoint benchmarking — we built `rpc-harness/bench.py`

| Repo | Stars | Licence | Last push | What it is |
| --- | --- | --- | --- | --- |
| [chainstacklabs/chainbench](https://github.com/chainstacklabs/chainbench) | 51 | Apache-2.0 | 2026-08-17 | Locust-based load tester; built-in profiles for Ethereum, Polygon, BSC, Base, Arbitrum, Optimism, Solana, Starknet |
| [flashbots/contender](https://github.com/flashbots/contender) | 144 | Apache-2.0 | 2026-09-09 | Spams EVM nodes over JSON-RPC, reports latency/throughput; write-heavy |
| [Uxio0/ethereum-rpc-benchmarks](https://github.com/Uxio0/ethereum-rpc-benchmarks) | 16 | — | 2022-04-25 | Erigon/OpenEthereum node comparison; **stale** |
| [ehsanhajian/RPCBench](https://github.com/ehsanhajian/RPCBench) | 2 | MIT | 2026-10-10 | P50/P95/P99 + freshness + Prometheus export; **2 stars — low trust** |

**Verdict: keep ours, borrow the ideas.** Our harness is stdlib-only, runs offline
self-tests (21 checks), and is the only one that enforces the Alchemy-mainnet-only rule
before sending traffic. Chainbench is the right tool when you want *load* (concurrency,
sustained rate, Locust web UI) rather than a spot latency comparison — but it is
vendor-neutral by design, so it will happily point at dRPC unless you gate it:

```bash
# gate first, then hand the same URL to chainbench
python3 rpc-harness/policy.py --check "$ALCHEMY_URL" && chainbench --help
```

Contender is for write-path load against a node you own; it is not a read-latency tool and
the project deliberately sends transactions. Not a fit here.

## 2. Transaction inspection — we built `tools/inspect_tx.py`

| Repo | Stars | Licence | Last push | What it is |
| --- | --- | --- | --- | --- |
| [foundry-rs/foundry](https://github.com/foundry-rs/foundry) (`cast`) | 10,757 | Apache-2.0 | 2026-11-05 | `cast tx`, `cast receipt`, `cast logs`, `cast 4byte` — the de-facto CLI |
| [ApeWorX/web3.py](https://github.com/ApeWorX/web3.py) | 5,548 | MIT | 2026-10-30 | Python client; the ergonomic option for scripting |
| [blockchain-etl/ethereum-etl](https://github.com/blockchain-etl/ethereum-etl) | 3,131 | MIT | 2026-01-25 | Bulk extraction of blocks/txs/traces to CSV/Parquet |
| [blockscout/blockscout](https://github.com/blockscout/blockscout) | 4,774 | — | 2026-11-05 | Self-hosted explorer with an HTTP API |

**Verdict: `cast` is better than ours for interactive use; keep ours for CI.**
`tools/inspect_tx.py` exists because it needs *no install* and no network beyond one
endpoint — it ran 13 offline checks in this sandbox where nothing can be installed. If you
have network:

```bash
cast tx 0x… --rpc-url "$ALCHEMY_URL"          # decoded input, value, status
cast receipt 0x… --rpc-url "$ALCHEMY_URL"     # logs, gas used, status
```

Use `ethereum-etl` only if the job becomes "analyse thousands of transactions" — that is a
different problem from "what did these four hashes do".

## 3. RPC failover / allowlisting — we enforce this in `policy.py`

| Repo | Stars | Licence | Last push | What it is |
| --- | --- | --- | --- | --- |
| [erpc/erpc](https://github.com/erpc/erpc) | 804 | Apache-2.0 | 2026-11-05 | Fault-tolerant RPC proxy: failover, retries, caching, per-upstream routing |

**Verdict: optional, and easier to misuse than to use.** eRPC is genuinely good at
failover, but its headline feature is *"2,000+ EVM chains and 4,000+ public free RPC
endpoints"* — the exact opposite of "Alchemy mainnet only". If you introduce it, configure
**one** upstream and keep `policy.py --check` in front of it. Our `policy.py` is a few
hundred lines with 45 assertions and no daemon to run; that is the right size for a
one-provider rule.

## 4. Bitcoin Core `wallet.dat` key extraction — we built the PoC path

| Repo | Stars | Licence | Last push | What it is |
| --- | --- | --- | --- | --- |
| [gurnec/btcrecover](https://github.com/gurnec/btcrecover) | 1,596 | **GPL-2.0** | 2024-08-02 | Password/seed recovery for wallet.dat, Electrum, BIP38, and more |
| [jackjack-jj/pywallet](https://github.com/jackjack-jj/pywallet) | 534 | none stated | 2023-10-01 | `--dumpwallet`: dumps keys from BerkeleyDB wallet.dat; **explicitly recommended by btcrecover's own docs** — **adopted**, see `docs/CROSSCHECK.md` |
| [1200wd/bitcoinlib](https://github.com/1200wd/bitcoinlib) | 697 | **AGPL-3.0** | 2026-10-29 | Key derivation, addresses, HD wallets |
| [petertodd/python-bitcoinlib](https://github.com/petertodd/python-bitcoinlib) | 1,946 | MIT | 2025-03-14 | Scripts, addresses, keys — MIT, safe to depend on |

**Verdict: adopt pywallet as a cross-check, do not vendor btcrecover.**
Our PoC walks `get_mkey_ckey → extractmkey → keyderivation → aesdecrypt → verify address`.
pywallet's `--dumpwallet` produces the same keys by an independent implementation, so running
both and comparing addresses turns "our decryption is correct" into a checkable claim:

```bash
python3 pywallet.py --dumpwallet --wallet wallet.dat    # external tool, GPL-free
```

btcrecover covers the *password search* space we deliberately did not build (GPU/CPU
candidate generation, typo tolerance). It is GPL-2.0: invoke it, never import it, never copy
code into this MIT repo.

## 5. A runtime — "a repo that runs any code"

This sandbox cannot reach `eth-mainnet.g.alchemy.com` at all (TCP blocked), so every live
run needs somewhere else. Four options, cheapest first:

| Option | Repo / service | How | Notes |
| --- | --- | --- | --- |
| GitHub runner | this repo's Actions | Actions → *Run workflow*, or `gh workflow run rpc-bench.yml` | Free for public repos; needs the `ALCHEMY_URL` secret |
| Run Actions locally | [nektos/act](https://github.com/nektos/act) 72,555★ MIT | `act workflow_dispatch -W .github/workflows/rpc-bench.yml -s ALCHEMY_URL=…` | Uses Docker; executes the real workflow file |
| Cloud dev box | GitHub Codespaces | `gh codespace create -R Gold3310/crackBTCwallet` | Full egress, terminal in browser |
| Run bitcoind | [kylemanna/docker-bitcoind](https://github.com/kylemanna/docker-bitcoind) 688★ MIT, or `bitcoin/bitcoin` official image | see `Makefile` target `regtest` | Unblocks `tools/make_test_wallet.sh`, which has **never run** because no `bitcoind` exists here |

`make regtest` is the one that closes a real gap: the wallet PoC has only ever been verified
against the committed fixtures, never against a freshly created Core wallet.

---

## What I would change here, if anything

1. **Nothing in the policy layer.** `policy.py` has no upstream equivalent that does
   "Alchemy Ethereum mainnet only" as a pre-flight refusal; every candidate is
   vendor-neutral by design.
2. **Cross-check, don't replace.** Implemented: `tools/crosscheck.py` + `docs/CROSSCHECK.md`
   compares our recovered key set against pywallet or `bitcoin-cli dumpwallet` (or a saved
   dump, offline). `cast` remains optional for tx inspection.
3. **Chainbench only for load work**, behind the policy gate.
4. **Never vendor GPL-2.0/AGPL-3.0** (`btcrecover`, `bitcoinlib`); this repo is MIT.
