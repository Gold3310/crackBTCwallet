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
