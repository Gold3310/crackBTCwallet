#!/usr/bin/env bash
#
# run-bench.sh - one command: validate the endpoint, benchmark it, show the summary.
#
# Access policy: Alchemy Ethereum mainnet only (rpc-harness/policy.py). The URL -
# which contains your API key - comes from the environment, never from a file.
#
#   export ALCHEMY_URL='https://eth-mainnet.g.alchemy.com/v2/<your-key>'
#   ./run-bench.sh                                        # example contract
#   ./run-bench.sh my-contract.json runs/today            # contract config + output dir
#   REQUESTS=60 ./run-bench.sh                            # more samples
#
# Exit codes: 2 = the URL is unset or still a placeholder, 3 = off-policy endpoint,
#             1 = benchmark produced no usable measurements, 0 = success.
set -euo pipefail
cd "$(dirname "$0")"

CONTRACT="${1:-rpc-harness/contracts.example.json}"
OUT="${2:-runs/$(date -u +%Y%m%dT%H%M%SZ)}"
REQUESTS="${REQUESTS:-30}"

if [ -z "${ALCHEMY_URL:-}" ]; then
  cat >&2 <<'MSG'
ALCHEMY_URL is not set.

  export ALCHEMY_URL='https://eth-mainnet.g.alchemy.com/v2/<your-key>'

Get the URL from your Alchemy dashboard (Ethereum -> Mainnet -> your app -> HTTPS).
Do not commit it, paste it in chat, or put it in a config file.
MSG
  exit 2
fi

# Catch a documentation placeholder or a markdown-wrapped URL before the policy gate,
# so the error names the real problem instead of a confusing key-length message.
case "$ALCHEMY_URL" in
  *"<key>"* | *"your-key"* | *"["* | *"]"* | *" "*)
    echo "ALCHEMY_URL still contains a placeholder or pasted link markup:" >&2
    echo "  ${ALCHEMY_URL}" >&2
    echo "Set it to your real project URL: https://eth-mainnet.g.alchemy.com/v2/<40-char-key>" >&2
    exit 2
    ;;
esac

echo "== access policy =="
if ! python3 rpc-harness/policy.py --check "$ALCHEMY_URL"; then
  echo "Refusing to send traffic: endpoint is outside policy (Alchemy Ethereum mainnet only)." >&2
  exit 3
fi

echo
echo "== benchmark =="
python3 rpc-harness/bench.py \
  --providers rpc-harness/providers.example.json \
  --contract "$CONTRACT" \
  --requests "$REQUESTS" \
  --out "$OUT"

echo
echo "== summary =="
cat "$OUT/summary.md"
echo
echo "results: $OUT/results.csv  summary: $OUT/summary.md  json: $OUT/summary.json"
