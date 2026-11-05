# Access policy — Alchemy Ethereum mainnet only

Every runtime network call in this repository is restricted to **Alchemy, Ethereum
mainnet**. This is enforced in code (`rpc-harness/policy.py`), not by convention, and it
fires before a single request is sent.

## The rule

An endpoint is allowed only if **all** of these hold:

| Requirement | Enforced because |
| --- | --- |
| scheme is `https` | plaintext would expose the API key on the wire |
| host ends in `.alchemy.com` | one vendor, one contract, one bill |
| host is `eth-mainnet.g.alchemy.com` | mainnet only — no Sepolia, Holesky, Goerli, hoodi |
| path contains `/v2/<key>` | keyless/public URLs are not attributable to your project |
| `chain_id` is `1` | a mainnet endpoint with a testnet chain id is a config error |

Refused, with a message naming the reason: QuickNode, dRPC, Goldsky, PublicNode, 1RPC,
Cloudflare, Infura, Ankr, LlamaNodes, Blast, BlockPI, legacy `alchemyapi.io`, loopback
nodes (outside self-tests), plaintext `http://`, and any Alchemy testnet host.

## Where it is enforced

| Entry point | Behaviour on violation |
| --- | --- |
| `rpc-harness/bench.py` | exits **3** before sending traffic, listing every offending endpoint |
| `rpc-harness/bench.py --selftest` | loopback explicitly allowed, so the harness stays testable offline |
| `tools/inspect_tx.py` | refuses the endpoint; with no `ALCHEMY_URL` set it prints the export line to use |
| `.github/workflows/rpc-bench.yml` | dedicated step runs `policy.py --check "$ALCHEMY_URL"` and fails the job |
| `rpc-harness/policy.py --check URL` | standalone verification, exit 1 on refusal |

## Verify it yourself

```bash
python3 rpc-harness/policy.py --self-test          # 37 assertions
python3 rpc-harness/policy.py --check "$ALCHEMY_URL"
python3 rpc-harness/bench.py --selftest            # includes policy-gate checks
python3 tools/inspect_tx.py --selftest
```

## The one escape hatch

`RPC_ALLOW_NON_ALCHEMY=1` permits any endpoint, prints `ALLOWED BY ESCAPE HATCH` and marks
the reason string. It exists so a broken key does not block an emergency diagnosis. Any
result produced under it is **outside policy** and must not be quoted as project data.

## What this does *not* restrict

`rpc-benchmarks/` contains a **comparative analysis** of the public vendor benchmark
(Alchemy vs QuickNode, dRPC, Goldsky). That is published data being reviewed, not network
access — nothing in this repository calls those providers. The analysis is kept because it
is the evidence behind the provider decision; the *access* policy is what is enforced here.

## Why a code-level gate

A convention dies the first time someone pastes a QuickNode URL into a config to "just test
something", and then the result gets compared against Alchemy numbers measured on a
different chain. The gate makes that a loud failure instead of a silent, wrong number.

## Where it runs (added)

| Trigger | How | Notes |
| --- | --- | --- |
| Manual, local | `./run-bench.sh` | one command: policy gate → benchmark → summary; refuses unset/placeholder endpoints with exit 2, off-policy with exit 3 |
| Manual, runner | Actions → *Run workflow*, or `gh workflow run rpc-bench.yml` | inputs default to USDC mainnet + block 20000000–20001000 |
| Timer, runner | set repository **variable** `RPC_BENCH_SCHEDULE=on` | then every 6 hours; opt-in so a missing secret cannot create failing runs nobody asked for |

A **placeholder guard** was added after a near-miss: a markdown-wrapped URL
(`[https://…/v2/<key>](https://…/v2/<key>)`) or a documentation placeholder would previously
have been stored as the secret and failed deep inside the run. Both are now refused up front,
by `policy.py` and again by `run-bench.sh`, with an error that names the real problem.

`tests/runner-guard.sh` locks that behaviour in — six checks covering unset, placeholder,
markdown link, off-policy vendor, Alchemy testnet, and executability.

## Contract pre-flight (runs before anything touches mainnet)

The policy gate answers *"is this endpoint allowed?"*. It does not answer *"is this address
worth sending traffic to?"* — and a pasted address is the easiest thing to get wrong. So a
second gate runs first, in `tools/verify_contract.py`, called by `run-bench.sh` and by
`bench.py` (exit **4**, before the first request).

Offline, always:

| Check | Refuses |
| --- | --- |
| shape | not `0x` + 40 hex |
| zero address | has no code, can never be a contract |
| precompile | `0x00..0x0a` are native identifiers, not contracts |
| EIP-55 | mixed case that does not match the Keccak-256 checksum (all-lower is accepted and normalised) |
| chain pin | anything but `chain_id: 1` |
| allowlist | a known symbol/decimals that does not match `contracts.known.json` |

Live, with `--live` and egress: `eth_chainId == 1`, `eth_getCode` non-empty, and
`symbol()`/`decimals()` answering — compared against the allowlist when the address is known.

Ethereum's Keccak-256 is implemented in `tools/keccak.py` because Python's `hashlib` only
offers NIST SHA3 (same permutation, different padding — unusable for EIP-55). It is checked
against published selectors (`symbol()` = `95d89b41`, `decimals()` = `313ce567`) and event
topics, so a silently wrong hash cannot make the checksum check pass.

The address you pasted, `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48`, verifies as USDC with
6 decimals. Metadata was cross-checked against `trustwallet/assets` (MIT) via the GitHub API;
`contracts.known.json` is authored here, not vendored.
