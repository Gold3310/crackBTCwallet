# Cross-checking our decryption against a second implementation

The PoC's chain is long: `get_mkey_ckey` → `extractmkey` → `keyderivation` → AES decrypt →
address derivation. Any of those can be subtly wrong and still produce a plausible-looking
key. The defence is a second implementation of the same wallet producing the same keys by a
different route.

`tools/crosscheck.py` does the comparison. It does **not** re-implement decryption — it
extracts, normalises and compares.

## Run it

```bash
# against a saved dump (offline, CI-friendly)
python3 tools/crosscheck.py --ours <WIF-or-hex> --from-dump theirs.txt

# against pywallet directly
python3 tools/crosscheck.py --ours <WIF> \
  --from-cmd "python3 pywallet.py --dumpwallet --wallet wallet.dat"

# against Bitcoin Core itself
python3 tools/crosscheck.py --ours <WIF> --from-cmd "bitcoin-cli dumpwallet -" --address <addr>

# via make
make crosscheck OURS=<WIF> FROM="python3 pywallet.py --dumpwallet --wallet wallet.dat"
```

Exit codes: **0** = our key set is confirmed, **1** = mismatch, **2** = unusable input.

## What counts as a match

Every key *we* recovered must appear in the other implementation's output, with the same
compression flag. Extra keys on their side are **normal** — a wallet has change addresses
and reserve (pool) keys that the PoC may never have touched — so they are reported as
`EXTRA`, not as a failure. `--strict` turns that into a failure too.

Two specific failure modes get named rather than lumped together:

- `FLAG` — the same secret appears on both sides with a different compression flag. The
  arithmetic is right but the address will not be; this is exactly the class of bug the
  engine's AES-NI/BE path can introduce.
- `--address` — if you say which address the wallet spends from, the tool checks that some
  key in the dump actually controls it. A matching key set that controls the *wrong* address
  still exits 1.

## Honest limits

- It proves agreement **between two implementations**, not correctness in the abstract. Two
  tools sharing the same misconception would agree.
- It was validated here against fixtures and against pywallet's *source structure*
  (`json_db['keys']` / `pool`, each entry carrying `addr`, `private_key`, `reserve`), not
  against a live pywallet run: this sandbox has no `bsddb3`, no `bitcoind` and no Docker.
- Feeding it a real wallet means handling a secret. Use a throwaway wallet only.

## Verification

`python3 tools/crosscheck.py --selftest` → 20 checks (parsing, comparison, compression
flags, `--strict`, subset semantics, regression that a matched key is never also reported as
a compression difference).

`./tests/crosscheck-e2e.sh` → 11 checks covering every exit code through the CLI, including
`--from-cmd` with a failing command, `--address` for an address no dumped key controls, and
`--json`.
