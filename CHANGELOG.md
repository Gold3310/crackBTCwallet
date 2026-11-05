Unreleased - contract pre-flight before mainnet
- tools/keccak.py: Keccak-256 (Ethereum padding) because hashlib only ships NIST SHA3;
  verified against published selectors and event topics (11 checks)
- tools/verify_contract.py: address gate run before any request - shape, zero address,
  precompile, EIP-55 checksum, chain pin, allowlist, optional live probe (29 checks).
  Exit 4 stops a benchmark before traffic starts; wired into run-bench.sh and bench.py.
  The live path inherits the endpoint policy and FAILS CLOSED if policy.py cannot be imported
  (a silent bypass was found and fixed during testing: off-policy URLs reported a network error)
- contracts.known.json: USDC/USDT/WETH/DAI on chain 1, authored here with provenance
  checked against trustwallet/assets (MIT) via the GitHub API
- BUG FIX: bench.py main() passed `calls` without building it - the first live run would
  have died with NameError. Now builds calls and the self-test pins it (25 checks, was 21)
- tests/runner-guard.sh: +2 checks (pre-flight refuses a precompile, USDC passes)

Unreleased - cross-check against a second implementation
- tools/crosscheck.py: compares the keys we recover with pywallet --dumpwallet, bitcoin-cli
  dumpwallet, or a saved dump; names compression-flag differences specifically; --address
  catches "keys agree but control the wrong address"; --strict available; 20 offline checks
- tests/crosscheck-e2e.sh: 11 checks over the CLI exit codes with synthetic fixtures
- docs/CROSSCHECK.md: semantics, honest limits, and the fact it was validated against
  pywallet's source structure and fixtures, not a live pywallet run (no bsddb3/bitcoind here)
- verify-all.sh now runs 8 suites; tasks.mk gains `make crosscheck`

Unreleased - prior art survey, Makefile entry points, regtest runtime
- docs/PRIOR-ART.md: searched GitHub for projects covering each component we built
  (benchmarking, tx inspection, RPC failover, wallet.dat extraction, runtimes) with
  stars/licence/last-push, a keep/adopt verdict per component, and MIT-vs-GPL notes
- tasks.mk: one-word entry points (verify, policy, bench, inspect, regtest, act, wallets),
  included from the PoC Makefile with -include; no existing target replaced
- tests/runner-guard.sh: +3 guards (PoC make targets intact, Makefile includes tasks.mk)
- docs/PRIOR-ART.md documents running this on act / Codespaces / a regtest container,
  since the sandbox cannot reach Alchemy

Unreleased - runnable everywhere, placeholder-proof
- Added run-bench.sh: one command (policy gate -> benchmark -> summary), distinct exit
  codes for unset (2), off-policy (3) and no-measurements (1)
- Workflow gains an opt-in 6-hourly schedule (repository variable RPC_BENCH_SCHEDULE=on),
  a concurrency group, timeouts, default inputs for scheduled runs, and calls run-bench.sh
- policy.py now rejects documentation placeholders and markdown-wrapped URLs before the
  key-length check, so the error names the real mistake (45 assertions)
- Added tests/runner-guard.sh (6 checks); verify-all.sh now runs 6 suites

Unreleased - access policy (Alchemy mainnet only)
- Added rpc-harness/policy.py: https + *.alchemy.com + eth-mainnet host + /v2/<key> +
  chain_id 1, enforced before any request; 37 self-test assertions
- bench.py exits 3 and lists offenders; loopback allowed only in --selftest
- tools/inspect_tx.py now defaults to ALCHEMY_URL instead of public endpoints and
  refuses off-policy hosts
- providers.example.json reduced to a single Alchemy entry; workflow gains an
  explicit policy step and drops the second-vendor secret
- Added docs/ACCESS-POLICY.md and verify-all.sh (5 suites, offline)

Unreleased (verification + tooling)
- Verified the README reference vector end to end on a fresh build; no changes needed
- `make noaesni` builds with gcc only (no yasm); its command set is complete, unlike TODO.md suggests
- Added tools/make_test_vector.py: generates a ckey/mkey test vector with a known answer
- Added tools/verify_key.py: independent secp256k1/Base58Check address + WIF verification
- Added tools/make_test_wallet.sh: isolated testnet legacy wallet for real-wallet testing
- Added tools/run_verification.sh + docs/TESTING.md: 26 automated checks, with a log
- Documented a defect: aesdecrypt accepts a wrong IV silently, corrupting the first
  16 bytes of the recovered private key while the padding check still passes

Version 0.1.20210204
- Added an extra tool get_mkey_ckey to extract the ckey and mkey from the wallet.dat file
- Added rmd160 for hash 
- Added some changes to noaesni version
- Added some memory checks for malloc returned values
- Added all the commands to the noaesni version, thanks Liam i hope this changes were useful to you

Version 0.1.20210102
- Added a precalculated value for expected AES Block decrypted.
  This method skip last XOR of CBC, keeping only the ECB part of AES256
  This save some ~2% of CPU in AESni mode  and ~5% on Lagacy mode

Version 0.1.20211228
- Added missing save range in legacy/mixed mode, file is saved in tested32.bin
