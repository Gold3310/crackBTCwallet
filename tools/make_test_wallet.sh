#!/usr/bin/env bash
#
# make_test_wallet.sh - create YOUR OWN throwaway Bitcoin Core wallet for testing
# crackbtcshell, with a passphrase you know, on testnet, in an isolated datadir.
#
# Nothing here touches your existing wallets, your mainnet node or your funds.
# Run it on a machine that has Bitcoin Core installed (bitcoind + bitcoin-cli).
#
#   ./tools/make_test_wallet.sh                 # testnet, throwaway datadir in /tmp
#   ./tools/make_test_wallet.sh --keep          # keep the node running afterwards
#   ./tools/make_test_wallet.sh --datadir DIR   # use a specific datadir
#   ./tools/make_test_wallet.sh --passphrase 'x'  # non-interactive (CI)
#
# Outputs: <datadir>/wallet.dat  plus the exact crackBTC commands to run next.
#
set -euo pipefail

PASSPHRASE=""
DATADIR=""
KEEP=0
RPC_PORT=18332
P2P_PORT=18333

while [ $# -gt 0 ]; do
  case "$1" in
    --passphrase) PASSPHRASE="${2:?}"; shift 2 ;;
    --datadir)    DATADIR="${2:?}"; shift 2 ;;
    --keep)       KEEP=1; shift ;;
    -h|--help)    sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

# ---------------------------------------------------------------- preflight ---
for bin in bitcoind bitcoin-cli; do
  if ! command -v "$bin" >/dev/null 2>&1; then
    cat >&2 <<EOF
ERROR: '$bin' not found.

This script needs Bitcoin Core on the machine you run it from. Install it first:

  Ubuntu/Debian   sudo add-apt-repository ppa:bitcoin/bitcoin && sudo apt install bitcoind
  macOS           brew install bitcoin
  Windows         download the installer from bitcoincore.org
  Docker          docker run -d --name btc -p 18332:18332 ruimarinho/bitcoin-core \\
                    -testnet -rpcuser=u -rpcpassword=p -rpcallowip=0.0.0.0/0 -fallbackfee=0.0001

Note: the analysis in docs/TESTING.md does NOT require Bitcoin Core - the
self-generated test vector (tools/make_test_vector.py) covers the whole pipeline.
EOF
    exit 1
  fi
done

DATADIR="${DATADIR:-$(mktemp -d /tmp/crackbtc-wallet-XXXXXX)}"
mkdir -p "$DATADIR"
CONF="$DATADIR/bitcoin.conf"
WALLET="crackbtc_test"

if [ -z "$PASSPHRASE" ]; then
  PASSPHRASE="$(head -c 18 /dev/urandom | base64 | tr -d '\n=+/' | cut -c1-16)"
  GENERATED=1
else
  GENERATED=0
fi

cat > "$CONF" <<EOF
testnet=1
server=1
rpcuser=crackbtc
rpcpassword=$(head -c 24 /dev/urandom | base64 | tr -d '\n')
rpcport=$RPC_PORT
port=$P2P_PORT
fallbackfee=0.0001
EOF

BTC="bitcoin-cli -datadir=$DATADIR -testnet"

cleanup() {
  if [ "$KEEP" -eq 0 ] && [ -n "${BITCOIND_PID:-}" ]; then
    echo "stopping bitcoind (pid $BITCOIND_PID)..."
    $BTC stop >/dev/null 2>&1 || true
    wait "${BITCOIND_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

echo "datadir : $DATADIR"
echo "starting bitcoind (isolated, testnet)..."
bitcoind -datadir="$DATADIR" -testnet -daemon=0 -printtoconsole=0 >/dev/null 2>"$DATADIR/bitcoind.err" &
BITCOIND_PID=$!

for _ in $(seq 1 60); do
  if $BTC getblockchaininfo >/dev/null 2>&1; then break; fi
  sleep 1
done
if ! $BTC getblockchaininfo >/dev/null 2>&1; then
  echo "ERROR: bitcoind did not come up. See $DATADIR/bitcoind.err" >&2
  exit 1
fi

CORE_VERSION="$($BTC getnetworkinfo | tr -d ' ' | grep -m1 '"subversion"' || true)"
echo "core    : $CORE_VERSION"

# ------------------------------------------------------- create legacy wallet ---
# get_mkey_ckey only parses the OLD BerkeleyDB wallet format, so descriptors=false
# (legacy) is required. Newer Core releases warn about, and eventually drop, it.
echo "creating legacy (BerkeleyDB) wallet '$WALLET' encrypted with a known passphrase..."
if ! $BTC createwallet "$WALLET" false false "$PASSPHRASE" false false 2>"$DATADIR/createwallet.err"; then
  cat >&2 <<EOF

ERROR: could not create a legacy wallet. Bitcoin Core said:

$(cat "$DATADIR/createwallet.err")

Your Core release may no longer support the legacy (BerkeleyDB) wallet, which is
the only format get_mkey_ckey can read. Options:
  * use Bitcoin Core 0.21 - 28 built with BerkeleyDB support
    (official Linux tarballs historically included it)
  * or skip Bitcoin Core entirely: tools/make_test_vector.py exercises the same
    code paths with a ckey you generate yourself
EOF
  exit 1
fi

ADDRESS="$($BTC -rpcwallet="$WALLET" getnewaddress '' legacy)"
WALLET_FILE="$DATADIR/testnet3/wallets/$WALLET/wallet.dat"
[ -f "$WALLET_FILE" ] || WALLET_FILE="$DATADIR/testnet3/wallet.dat"

# Verify it is really BerkeleyDB (magic 0x00000001) and not SQLite.
HEAD_BYTES="$(od -An -tx1 -N16 "$WALLET_FILE" | tr -d ' \n')"
if [ "${HEAD_BYTES:0:8}" = "53514c69" ]; then
  echo "ERROR: $WALLET_FILE is SQLite, not BerkeleyDB. get_mkey_ckey cannot parse it." >&2
  echo "       Recreate with: bitcoin-cli -rpcwallet=... or use Core <= 28." >&2
  exit 1
fi

echo
echo "================ wallet ready ================"
echo "wallet.dat    : $WALLET_FILE"
echo "network       : testnet"
echo "address       : $ADDRESS"
echo "passphrase    : $PASSPHRASE$([ "$GENERATED" -eq 1 ] && echo '   (generated for you - save it)')"
echo "wallet header : $HEAD_BYTES (BerkeleyDB)"
echo
echo "Next steps (run from the repository root):"
echo
echo "  ./get_mkey_ckey \"$WALLET_FILE\""
echo "  ./crackbtcshell <<'CMDS'"
echo "  extractmkey \"$WALLET_FILE\"          # mkey + salt + nDerivations"
echo "  keyderivation <nDerivations> <salt> '$PASSPHRASE'   # -> Key: <master key>"
echo "  load mkey <mkey from extractmkey>"
echo "  try key <Key from keyderivation>"
echo "  CMDS"
echo
echo "Then prove the recovered key owns '$ADDRESS':"
echo "  python3 tools/verify_key.py --privkey <decrypted ckey> --address $ADDRESS"
echo
echo "Clean up when done:  rm -rf $DATADIR"
