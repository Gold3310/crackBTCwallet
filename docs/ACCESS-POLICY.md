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
