#!/usr/bin/env bash
# Run every suite in the repository. Exit 0 only if all of them pass.
# Live network calls are excluded by design: runtime access is Alchemy mainnet only
# and this sandbox has no egress to it, so everything here is offline-verifiable.
set -uo pipefail
cd "$(dirname "$0")"

pass=0; fail=0; failed_names=()

run() {
  local name="$1"; shift
  printf '\n\033[1m== %s ==\033[0m\n' "$name"
  if "$@" >/tmp/verify_out 2>&1; then
    tail -1 /tmp/verify_out | sed 's/^/   /'
    pass=$((pass+1))
  else
    echo "   FAILED"; tail -6 /tmp/verify_out | sed 's/^/   /'
    fail=$((fail+1)); failed_names+=("$name")
  fi
}

run "access policy (Alchemy mainnet only)"        python3 rpc-harness/policy.py --self-test
run "rpc-harness benchmark"                       python3 rpc-harness/bench.py --selftest
run "transaction inspector"                       python3 tools/inspect_tx.py --selftest
run "benchmark data tooling"                      python3 rpc-benchmarks/tests/run_tests.py
run "wallet PoC verification (26 checks)"         ./tools/run_verification.sh

printf '\n\033[1m== summary ==\033[0m\n%d suite(s) passed, %d failed\n' "$pass" "$fail"
if [ "$fail" -gt 0 ]; then
  printf 'failed: %s\n' "${failed_names[*]}"
  exit 1
fi
