#!/usr/bin/env bash
# Guards on run-bench.sh: it must refuse to run before it can waste a request,
# and it must never accept a placeholder or a pasted markdown link as an endpoint.
set -uo pipefail
cd "$(dirname "$0")/.."

pass=0; fail=0
check_exit() { # check_exit <description> <expected> <actual>
  if [ "$2" = "$3" ]; then pass=$((pass+1)); echo "PASS  $1";
  else fail=$((fail+1)); echo "FAIL  $1 (expected exit $2, got $3)"; fi
}

env -u ALCHEMY_URL ./run-bench.sh >/dev/null 2>&1
check_exit "unset ALCHEMY_URL is refused" 2 $?

env ALCHEMY_URL='https://eth-mainnet.g.alchemy.com/v2/<key>' ./run-bench.sh >/dev/null 2>&1
check_exit "documentation placeholder is refused" 2 $?

env ALCHEMY_URL='[https://eth-mainnet.g.alchemy.com/v2/<key>](x)' ./run-bench.sh >/dev/null 2>&1
check_exit "markdown-wrapped link is refused" 2 $?

env ALCHEMY_URL='https://eth.drpc.org' ./run-bench.sh >/dev/null 2>&1
check_exit "off-policy vendor is refused" 3 $?

env ALCHEMY_URL='https://eth-sepolia.g.alchemy.com/v2/abcdefgh12345678' ./run-bench.sh >/dev/null 2>&1
check_exit "Alchemy testnet is refused" 3 $?

[ -x run-bench.sh ]; check_exit "run-bench.sh is executable" 0 $?

echo
echo "passed: $pass, failed: $fail"
[ "$fail" -eq 0 ]
