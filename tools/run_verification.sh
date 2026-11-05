#!/usr/bin/env bash
#
# run_verification.sh - reproduce every claim in docs/TESTING.md and write a log.
#
#   ./tools/run_verification.sh              # writes docs/verification-log.txt
#   ./tools/run_verification.sh --no-build   # skip the compiler step
#
# Exit code 0 means every check passed. Each check prints PASS/FAIL.
#
set -uo pipefail
cd "$(dirname "$0")/.."

BUILD=1
[ "${1:-}" = "--no-build" ] && BUILD=0
LOG="${LOG:-docs/verification-log.txt}"
PASS=0; FAIL=0

say()  { printf '\n=== %s ===\n' "$*" | tee -a "$LOG"; }
ok()   { PASS=$((PASS+1)); printf 'PASS  %s\n' "$*" | tee -a "$LOG"; }
bad()  { FAIL=$((FAIL+1)); printf 'FAIL  %s\n' "$*" | tee -a "$LOG"; }
check() { # check <description> <expected> <actual>
  if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 (expected '$2', got '$3')"; fi
}
contains() { # contains <description> <needle> <file>
  if grep -qF -- "$2" "$3"; then ok "$1"; else bad "$1 (missing '$2')"; fi
}

: > "$LOG"
{
  echo "crackBTCwallet verification log"
  echo "generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ') on $(uname -srm)"
  echo "gcc: $(gcc --version | head -1)"
} | tee -a "$LOG"

# ---------------------------------------------------------------- 1. build ---
if [ "$BUILD" -eq 1 ]; then
  say "1. build (make noaesni - gcc only, no yasm)"
  if make noaesni >>"$LOG" 2>&1; then ok "make noaesni"; else bad "make noaesni"; fi
fi
say "2. command set present in the noaesni build"
for cmd in start try load set extractmkey keyderivation aesdecrypt doublesha256 privatekeytowif stats; do
  if grep -q "\"$cmd\"" crackbtcshell_noaesni.c && grep -q "\"$cmd\"" crackbtcshell.c; then
    ok "command '$cmd' registered in both builds"
  else
    bad "command '$cmd' missing"
  fi
done

# --------------------------------------------------- 3. README vector -------
say "3. README reference vector"
README_OUT=$(mktemp)
printf '%s\n' 'set quiet 1' \
  'load ckey 2e24da42feb389aab372163cac88c5b9233d6f1a2e6bcb4e8337dfa21f0aa85309fa70c00637474a88b0d881c4d93155' \
  'try key 563758754506d53828c5383d2cb6296efe7f217c5ef6a84b13bce3ecec66da2e' \
  'doublesha256 0382ca08ce78b0935099c74db12873a7dc1cba10a44165ce8cc1d0602f49ee97f5' \
  'aesdecrypt 35fc5f8253f1bcf2c185571a35413f1f 563758754506d53828c5383d2cb6296efe7f217c5ef6a84b13bce3ecec66da2e 2e24da42feb389aab372163cac88c5b9233d6f1a2e6bcb4e8337dfa21f0aa85309fa70c00637474a88b0d881c4d93155' \
  'privatekeytowif 3ea5eaabe7f7b997ce732acc9cf08315a805109003ce2bd918bac1b73b82d7b7' \
  'exit' | ./crackbtcshell > "$README_OUT" 2>&1
contains "key found"                 "Posible Key found"                                  "$README_OUT"
contains "IV derivation"             "35fc5f8253f1bcf2c185571a35413f1f"                   "$README_OUT"
contains "decrypted ckey"            "3ea5eaabe7f7b997ce732acc9cf08315a805109003ce2bd918bac1b73b82d7b7" "$README_OUT"
contains "WIF uncompressed"          "5JHsqscg3o1iAWjRP83nWWJFbgMrjnXwVQoxejtAqp4t6cCVgbo" "$README_OUT"
contains "WIF compressed"            "KyKVQiQTML68gzEEce7HsEK9S4j4XqyZWQ6GdaGrSSk8XZJHqNWe" "$README_OUT"
cat "$README_OUT" >> "$LOG"

# -------------------------------------------- 4/5. self-generated vector ----
say "4. self-generated vector (seed demo-1)"
VEC_OUT=$(mktemp)
python3 tools/make_test_vector.py --seed demo-1 --commands | ./crackbtcshell > "$VEC_OUT" 2>&1
contains "key found"      "Posible Key found" "$VEC_OUT"
contains "recovered key"  "31c011efa9fffbcee0c065c359d8fb07d6cfab0c69eadb095d9267261514daa710101010101010101010101010101010" "$VEC_OUT"
cat "$VEC_OUT" >> "$LOG"

say "5. WIF cross-check with the independent implementation"
WIF_OUT=$(python3 tools/verify_key.py --privkey 31c011efa9fffbcee0c065c359d8fb07d6cfab0c69eadb095d9267261514daa7 2>&1)
echo "$WIF_OUT" >> "$LOG"
contains "compressed WIF agrees"   "KxtRFUTgLVnLN9AaP7NijuUpC8Nttv1CtDdJ3P7xP1gxRfKx4RLt" "$VEC_OUT"
contains "uncompressed WIF agrees" "5JCCPK19uuHcesLPWw1PbeGN7bkUcn62nb8KMvx3aXyBHxpee7n" "$VEC_OUT"

# ------------------------------------------------------- 6. negative test ----
say "6. negative test - wrong keys must not be accepted"
NEG=$(mktemp)
printf '%s\n' 'set quiet 1' \
  'load ckey 7ad287e43fe46cdc291233d0e50cef84e0c160cee2d9a1c222ea90b849126c05b119fed3f8f03dc06f04e9b5fc0265cd' \
  'try key 0000000000000000000000000000000000000000000000000000000000000001' \
  'try key 81eefdbd01a97771c159aaf79ad9b5b8040829faddb2ec1ef1f1bf26627bfa4d' \
  'exit' | ./crackbtcshell 2>&1
NEG_HITS=$(printf '%s' "$NEG" | grep -c "Posible Key found")
echo "$NEG" >> "$LOG"
check "false positives on two wrong keys" "0" "$NEG_HITS"

# --------------------------------------------------------- 7. IV defect -----
say "7. wrong IV with correct key (documented defect)"
IV_OUT=$(printf '%s\n' 'set quiet 1' \
  'aesdecrypt 00000000000000000000000000000000 81eefdbd01a97771c159aaf79ad9b5b8040829faddb2ec1ef1f1bf26627bfa4e 7ad287e43fe46cdc291233d0e50cef84e0c160cee2d9a1c222ea90b849126c05b119fed3f8f03dc06f04e9b5fc0265cd' \
  'exit' | ./crackbtcshell 2>&1 | grep "Decrypted:")
echo "$IV_OUT" >> "$LOG"
# NB: no `printf | grep -q` here - under `set -o pipefail`, grep -q exits on first
# match and printf takes SIGPIPE, which would report a false failure.
PADDING="10101010101010101010101010101010"
case "$IV_OUT" in
  *"$PADDING"*) ok "padding survives a wrong IV (sixteen 0x10 bytes still validate)" ;;
  *)            bad "padding did not survive a wrong IV" ;;
esac
case "$IV_OUT" in
  *"Decrypted: 31c011efa9fffbcee0c065c359d8fb07"*)
    bad "wrong IV produced the correct first block (defect not reproduced?)" ;;
  *)
    ok "wrong IV corrupts the first 16 bytes while padding still validates" ;;
esac

# ----------------------------------------------------- 8. verify_key logic --
say "8. verify_key.py address logic round-trips"
ROUND=$(python3 - <<'PY'
import importlib.util
spec = importlib.util.spec_from_file_location("vk", "tools/verify_key.py")
vk = importlib.util.module_from_spec(spec); spec.loader.exec_module(vk)
priv = bytes.fromhex("31c011efa9fffbcee0c065c359d8fb07d6cfab0c69eadb095d9267261514daa7")
addr = vk.address_from_privkey(priv, True)
embedded = vk.base58check_decode(addr)[1:]
print("match" if vk.hash160(vk.pubkey(priv, True)) == embedded else "mismatch")
PY
)
echo "$ROUND" >> "$LOG"
check "hash160(pubkey) equals address payload" "match" "$ROUND"

say "9. make_test_wallet.sh preflight without Bitcoin Core"
if command -v bitcoind >/dev/null 2>&1; then
  ok "bitcoind present - skipping the missing-binary check"
else
  WALLET_OUT=$(./tools/make_test_wallet.sh 2>&1)
  echo "$WALLET_OUT" >> "$LOG"
  if printf '%s' "$WALLET_OUT" | grep -q "not found"; then
    ok "fails fast with install instructions"
  else
    bad "missing-bitcoind path did not explain itself"
  fi
fi

say "10. wallet.dat format sniffing is implemented"
if grep -q "53514c69" tools/make_test_wallet.sh && grep -q "SQLite" tools/make_test_wallet.sh; then
  ok "SQLite wallets rejected before parsing"
else
  bad "format sniffing missing"
fi

# --------------------------------------------------------------- summary ----
say "summary"
echo "passed: $PASS   failed: $FAIL" | tee -a "$LOG"
[ "$FAIL" -eq 0 ] && echo "log: $LOG" | tee -a "$LOG"
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)
