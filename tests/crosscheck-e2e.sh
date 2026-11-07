#!/usr/bin/env bash
# End-to-end checks for tools/crosscheck.py against synthetic dumps.
# No wallet, node, network or pywallet install needed: the fixtures are throwaway keys
# (0x01, 0x02) and the exit codes are the contract.
set -uo pipefail
cd "$(dirname "$0")/.."

PY=python3
WIF1=$($PY -c "import sys; sys.path.insert(0,'tools'); import verify_key as vk; print(vk.wif_from_privkey(bytes.fromhex('00'*31+'01'), True))")
WIF1U=$($PY -c "import sys; sys.path.insert(0,'tools'); import verify_key as vk; print(vk.wif_from_privkey(bytes.fromhex('00'*31+'01'), False))")
WIF2=$($PY -c "import sys; sys.path.insert(0,'tools'); import verify_key as vk; print(vk.wif_from_privkey(bytes.fromhex('00'*31+'02'), True))")
WIF3=$($PY -c "import sys; sys.path.insert(0,'tools'); import verify_key as vk; print(vk.wif_from_privkey(bytes.fromhex('00'*31+'03'), True))")

PK=1BgGZ9tcN4rm9KBzDn7KprQz87SZ26SAMH     # address of key 0x01 (in the fixtures)
# address of key 0x03: deliberately absent from every fixture, so no dumped key controls it
OUTSIDE=$($PY -c "import sys; sys.path.insert(0,'tools'); import verify_key as vk; print(vk.address_from_privkey(bytes.fromhex('00'*31+'03'), True))")

pass=0; fail=0
check_exit() { # check_exit <description> <expected> <actual>
  if [ "$2" = "$3" ]; then pass=$((pass+1)); echo "PASS  $1";
  else fail=$((fail+1)); echo "FAIL  $1 (expected exit $2, got $3)"; fi
}

$PY tools/crosscheck.py --ours "$WIF1" --from-dump tests/fixtures/xc-pywallet.txt >/dev/null 2>&1
check_exit "subset of a pywallet dump matches" 0 $?

$PY tools/crosscheck.py --ours "$WIF1" --ours "$WIF2" --from-dump tests/fixtures/xc-core.txt >/dev/null 2>&1
check_exit "both keys via bitcoin-cli dumpwallet shape match" 0 $?

$PY tools/crosscheck.py --ours "$WIF3" --from-dump tests/fixtures/xc-pywallet.txt >/dev/null 2>&1
check_exit "a key nobody else has is a MISMATCH" 1 $?

$PY tools/crosscheck.py --ours "$WIF1" --from-dump tests/fixtures/xc-pywallet.txt --strict >/dev/null 2>&1
check_exit "--strict rejects extra keys in the dump" 1 $?

$PY tools/crosscheck.py --ours "$WIF1U" --from-dump tests/fixtures/xc-pywallet.txt >/dev/null 2>&1
check_exit "compression-flag difference is a MISMATCH" 1 $?

$PY tools/crosscheck.py --ours "$WIF1" --from-dump tests/fixtures/xc-empty.txt >/dev/null 2>&1
check_exit "a dump with no keys is refused" 2 $?

$PY tools/crosscheck.py --ours "$WIF1" --from-dump tests/fixtures/xc-pywallet.txt --address "$PK" >/dev/null 2>&1
check_exit "correct --address is confirmed" 0 $?

$PY tools/crosscheck.py --ours "$WIF1" --from-dump tests/fixtures/xc-pywallet.txt --address "$OUTSIDE" >/dev/null 2>&1
check_exit "--address no dumped key controls is a MISMATCH" 1 $?

$PY tools/crosscheck.py --ours "$WIF1" --from-cmd "cat tests/fixtures/xc-pywallet.txt" >/dev/null 2>&1
check_exit "--from-cmd parses external output" 0 $?

$PY tools/crosscheck.py --ours "$WIF1" --from-cmd "false" >/dev/null 2>&1
check_exit "a failing external command is refused" 1 $?

json=$($PY tools/crosscheck.py --ours "$WIF1" --from-dump tests/fixtures/xc-pywallet.txt --json 2>/dev/null)
echo "$json" | $PY -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d['ok'] and d['matched'] else 1)" 2>/dev/null
check_exit "--json reports ok and matched keys" 0 $?

echo
echo "passed: $pass, failed: $fail"
[ "$fail" -eq 0 ]
