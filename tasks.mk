# Entry points for the RPC harness, docs and runtime helpers.
# Included from the PoC Makefile via `-include tasks.mk`; it deliberately defines no
# target that already exists there (default/noaesni/clean/libaesni/testaes are untouched).
# Run `make help` to list them.

ALCHEMY_URL ?= $(shell printenv ALCHEMY_URL)
TX ?=
CONTRACT ?= rpc-harness/contracts.example.json
OUT ?= runs/$(shell date -u +%Y%m%dT%H%M%SZ)
RPC_USER ?= poctest
RPC_PASS ?= poctest
CONTAINER ?= btc-regtest

.PHONY: help verify contract policy bench inspect regtest regtest-stop regtest-wallet cast act wallets crosscheck clean-runs

help:
	@printf '%s\n' \
	  '  make verify            all offline suites (no network, no keys)' \
	  '  make policy            check $$ALCHEMY_URL against the mainnet-only rule' \
	  '  make bench             policy gate -> benchmark -> summary (needs egress)' \
	  '  make inspect TX=0x…    inspect one transaction' \
	  '  make cast  TX=0x…      same, via foundry cast if installed' \
	  '  make regtest           start Bitcoin Core regtest in Docker' \
	  '  make regtest-wallet    copy wallet.dat out of the regtest node' \
	  '  make act               execute the workflow locally via nektos/act' \
	  '  make wallets           generate a throwaway wallet dump' \
	  '  make crosscheck OURS=… FROM=…   compare against pywallet / bitcoin-cli' \
	  '  make contract ADDR=0x…  validate a contract address before mainnet traffic' \
	  '  make clean-runs        remove local benchmark output' \
	  '' \
	  '  (PoC build targets are unchanged: default, noaesni, libaesni, testaes, clean)'

verify:
	./verify-all.sh

policy:
	@test -n "$(ALCHEMY_URL)" || { echo "export ALCHEMY_URL first (see docs/ACCESS-POLICY.md)"; exit 2; }
	python3 rpc-harness/policy.py --check "$(ALCHEMY_URL)"

bench:
	./run-bench.sh $(CONTRACT) $(OUT)

inspect:
	@test -n "$(TX)" || { echo "usage: make inspect TX=0x…"; exit 2; }
	python3 tools/inspect_tx.py $(foreach t,$(TX),--tx $(t))

cast:
	@command -v cast >/dev/null || { echo "cast not installed: curl -L https://foundry.paradigm.xyz | bash"; exit 1; }
	cast tx $(TX) --rpc-url "$(ALCHEMY_URL)"

regtest:
	@command -v docker >/dev/null || { echo "docker is required for this target"; exit 1; }
	@docker rm -f $(CONTAINER) >/dev/null 2>&1 || true
	docker run -d --name $(CONTAINER) -p 18443:18443 bitcoin/bitcoin:latest \
	  bitcoind -regtest -server=1 -txindex=1 -fallbackfee=0.0001 \
	  -rpcuser=$(RPC_USER) -rpcpassword=$(RPC_PASS) -rpcallowip=0.0.0.0/0
	@echo "waiting for RPC..."
	@for i in $$(seq 1 30); do \
	  if docker exec $(CONTAINER) bitcoin-cli -regtest -rpcuser=$(RPC_USER) -rpcpassword=$(RPC_PASS) getblockchaininfo >/dev/null 2>&1; then \
	    echo "ready after $$i s"; break; fi; sleep 1; done
	@docker exec $(CONTAINER) bitcoin-cli -regtest -rpcuser=$(RPC_USER) -rpcpassword=$(RPC_PASS) createwallet poctest >/dev/null || true
	@echo "node up on 127.0.0.1:18443 (regtest, throwaway credentials)"
	@echo "next: make regtest-wallet"

regtest-wallet:
	docker cp $(CONTAINER):/home/bitcoin/.bitcoin/regtest/wallets/poctest/wallet.dat ./wallet.dat
	@echo "wallet.dat copied to the repo root"

regtest-stop:
	-docker rm -f $(CONTAINER)

act:
	@command -v act >/dev/null || { echo "act not installed: see github.com/nektos/act"; exit 1; }
	@test -n "$(ALCHEMY_URL)" || { echo "export ALCHEMY_URL first"; exit 2; }
	act workflow_dispatch -W .github/workflows/rpc-bench.yml -s ALCHEMY_URL="$(ALCHEMY_URL)"

contract:          ## make contract ADDR=0x…   pre-flight an address before benchmarking
	@test -n "$(ADDR)" || { echo "usage: make contract ADDR=0x…"; exit 2; }
	python3 tools/verify_contract.py --address "$(ADDR)"

crosscheck:        ## make crosscheck FROM="python3 pywallet.py --dumpwallet --wallet wallet.dat" OURS=<wif>
	@test -n "$(OURS)" || { echo "usage: make crosscheck OURS=<wif> FROM=\"<external dump command>\""; exit 2; }
	@test -n "$(FROM)" || { echo "usage: make crosscheck OURS=<wif> FROM=\"<external dump command>\""; exit 2; }
	python3 tools/crosscheck.py --ours "$(OURS)" --from-cmd "$(FROM)"

wallets:
	bash tools/make_test_wallet.sh

clean-runs:
	rm -rf runs/ contracts.ci.json
