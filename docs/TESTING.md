# Testing `crackBTCwallet` with a wallet you own

**Short answer to "I need a wallet to connect with":** two options, and only one of them
needs Bitcoin Core.

| Path | Needs | Time | Proves |
| --- | --- | --- | --- |
| **A. Self-generated vector** (`tools/make_test_vector.py`) | gcc only | ~2 min | The whole AES/IV/decrypt/WIF pipeline, end to end, with an answer you already know |
| **B. Your own `wallet.dat`** (`tools/make_test_wallet.sh`) | Bitcoin Core installed **on your machine** | ~10 min | The real thing: `wallet.dat` → `mkey`/`ckey` extraction → passphrase derivation → recovered key matches your address |

Both were exercised below. Everything in Path A was verified inside this repository's
sandbox (Bitcoin Core is not installable there — no network path to `bitcoincore.org` or
the distro mirrors — so Path B's script is written and dry-run checked, but the Core part
must run on your machine).

> **Safety.** Only ever point this at a wallet **you created and own**, on **testnet**,
> holding **no funds**. A tool that recovers a key can also be pointed at someone else's
> wallet, which is a crime in most jurisdictions. Never share a real `wallet.dat`, its
> passphrase, or a recovered key. Delete the test wallet when you are done.

---

## Build

Two builds are possible; only one needs `yasm`:

```bash
make            # AES-NI version - needs yasm (not installed in the sandbox)
make noaesni    # legacy AES via ctaes - gcc only
```

Verified in this environment with **`make noaesni`**: builds `crackbtcshell` and
`get_mkey_ckey` with no warnings-as-errors, no yasm and no external libraries.

Contrary to `TODO.md`, the `noaesni` build registers the **full** command set:

```
start pause continue stats exit about help version
extractmkey doublesha256 privatekeytowif
load set try
keyderivation aesdecrypt
```

`noaesni` is slower per tested key, but every command you need to *verify* a wallet
(`try key`, `keyderivation`, `extractmkey`, `aesdecrypt`, `privatekeytowif`) is present.

---

## Path A — self-generated vector, no wallet file needed

`tools/make_test_vector.py` fabricates a `ckey` exactly the way Bitcoin Core lays one out:

```
plaintext = private key (32 bytes) || 0x10 x 16     (48 bytes, pre-padded)
AES key   = "master key" material (32 bytes)
IV        = first 16 bytes of double-SHA256(key id)  <- the convention this shell expects
ckey      = AES-256-CBC(plaintext, AES key, IV)
```

### Run it

```bash
python3 tools/make_test_vector.py --seed demo-1 --commands | ./crackbtcshell
```

### Observed output (verified)

```
crackBTC > Expected block: f0d170def2c9b1d232fa80a859027c15
Adding 7ad287e43fe46cdc291233d0e50cef84e0c160cee2d9a1c222ea90b849126c05b119fed3f8f03dc06f04e9b5fc0265cd to the list
crackBTC > Posible Key found
key_material: 81eefdbd01a97771c159aaf79ad9b5b8040829faddb2ec1ef1f1bf26627bfa4e
crackBTC > double sha256: 42eb6fd318fe4cfdad6baf6b624d9294b04d995ad38aa0456c7ad02911ec6ebd
crackBTC > decrypt_iv 42eb6fd318fe4cfdad6baf6b624d9294
decrypt_key 81eefdbd01a97771c159aaf79ad9b5b8040829faddb2ec1ef1f1bf26627bfa4e
len: 48
Decrypted: 31c011efa9fffbcee0c065c359d8fb07d6cfab0c69eadb095d9267261514daa710101010101010101010101010101010
crackBTC > Private KEY uncompressed 5JCCPK19uuHcesLPWw1PbeGN7bkUcn62nb8KMvx3aXyBHxpee7n
Private KEY compressed KxtRFUTgLVnLN9AaP7NijuUpC8Nttv1CtDdJ3P7xP1gxRfKx4RLt
```

The decrypted value is **byte-for-byte the private key the generator started with**
(`31c011…daa7` + sixteen `10` padding bytes), and both WIFs match an independent
implementation (`tools/verify_key.py`, which derives them with its own secp256k1 +
Base58Check code, no OpenSSL bindings).

### Also reproduced: the README's reference vector

The example in `README.md` still holds exactly on this build:

| Command | Result |
| --- | --- |
| `try key 563758…da2e` on ckey `2e24da…3155` | `Posible Key found` |
| `doublesha256 0382ca…97f5` | `35fc5f8253f1bcf2c185571a35413f1f…` |
| `aesdecrypt 35fc5f82… 563758… 2e24da…` | `3ea5eaab…d7b7` + sixteen `10` |
| `privatekeytowif 3ea5ea…d7b7` | `5JHsqscg3o1iAWjRP83nWWJFbgMrjnXwVQoxejtAqp4t6cCVgbo` / `KyKVQiQTML68gzEEce7HsEK9S4j4XqyZWQ6GdaGrSSk8XZJHqNWe` |

### Negative test (verified)

Two wrong keys — all-zeros-plus-one and a one-bit variant of the correct key — produced
**zero** `Posible Key found` lines. The key-material check does not false-positive.

---

## Path B — your own wallet, with Bitcoin Core

On a machine with Bitcoin Core installed:

```bash
./tools/make_test_wallet.sh
```

The script is deliberately conservative:

- runs **testnet** only, in its own throwaway `-datadir` (never touches your real wallets);
- creates a **legacy BerkeleyDB** wallet (`descriptors=false`) because `get_mkey_ckey`
  only understands the old format;
- generates a random passphrase for you (or takes `--passphrase`);
- refuses to continue if the resulting file is **SQLite** (Core ≥ 0.21 default), with an
  explanation of what to do instead;
- prints the exact `crackBTC` commands, filled in, at the end.

### The full sequence it prepares

```bash
# 1. pull the encrypted pieces out of the wallet file
./get_mkey_ckey wallet.dat
#    Mkey_encrypted: <96 hex chars>
#    encrypted ckey: <96 hex chars>
#    public key    : <compressed or uncompressed hex>
#    public address: <the address this key controls>     <- your ground truth

# 2. mkey + salt + iteration count
./crackbtcshell
crackBTC > extractmkey wallet.dat
#    mkey: <96 hex chars>
#    salt: <16 hex chars>
#    nDerivations: 25000        (value varies by Core version and encryption)

# 3. turn the passphrase into the master key (this is a verification step, not a crack)
crackBTC > keyderivation 25000 <salt> 'your passphrase'
#    Key: <32-byte master key>
#    IV : <16 bytes>

# 4. confirm that master key really decrypts the wallet's mkey
crackBTC > load mkey <mkey from step 2>
crackBTC > try key <Key from step 3>
#    Posible Key found            <- the passphrase you typed is the wallet's passphrase
```

Then recover a private key and **prove it belongs to the wallet**:

```bash
# 5. decrypt the ckey (IV depends on the key id, see the next section)
crackBTC > doublesha256 <key id>
crackBTC > aesdecrypt <first 32 hex of that hash> <master key> <encrypted ckey>

# 6. derive addresses and compare with the address from step 1
python3 tools/verify_key.py --privkey <32-byte key from step 5> --address <address from step 1>
#    MATCH - the key controls 1... (compressed form).
```

`tools/verify_key.py` needs nothing but Python 3: it implements secp256k1 point
multiplication, Base58Check and both address forms itself.

---

## Why "Posible Key found" is not the end of the test — a real defect found here

`try key` validates the **key material** by checking the expected final AES block (that is
the "Expected block:" line printed when a ckey is loaded). That check does not involve the
IV, and it is sound: the negative test above shows no false positives.

But `aesdecrypt` accepts the IV from you, and a wrong IV is **silently accepted**. In
AES-CBC only the first plaintext block depends on the IV, so the padding in the last block
verifies no matter what IV you pass. Verified in this sandbox — decrypting the same ckey
with the correct key but an all-zero IV:

```
correct answer : 31c011efa9fffbcee0c065c359d8fb07d6cfab0c69eadb095d9267261514daa7
IV = 0000...   : 732b7e3cb101b7334dabcaa83b956993 d6cfab0c69eadb095d9267261514daa7
                 \________ corrupted _______________/ \________ still correct ________/
```

The tail is right, the padding is right, the tool prints `Decrypted:` — and **the first
16 bytes of the private key are garbage.** Anyone who stopped there would produce a WIF
that controls nothing, with no error message anywhere.

**Therefore, for any real wallet: verify the address, not the message.** Two candidate IV
derivations exist in the wild, and the tool cannot tell you which is correct:

```bash
python3 tools/verify_key.py --keyid-from-pubkey <public key from get_mkey_ckey>
#  A) first 16 bytes of key id           <- try this first
#  B) first 16 of double-SHA256(key id)  <- and this if A does not match the address
```

Try A, run the address comparison. If it reports NO MATCH, repeat with B. Whichever
produces the wallet's own address is the right one for that wallet. (`README.md`'s example
uses the double-SHA256 form, which is why `--iv-from` and `doublesha256` exist.)

---

## Verified results from this sandbox

| # | Test | Result |
| --- | --- | --- |
| 1 | `make noaesni` with gcc only (no yasm) | builds `crackbtcshell` + `get_mkey_ckey` |
| 2 | Command set in the `noaesni` build | all 17 commands present (TODO.md is stale) |
| 3 | README reference vector | key found, IV, decrypt, both WIFs — exact match |
| 4 | Self-generated vector (`--seed demo-1`) | recovered key identical to the original |
| 5 | WIFs cross-checked by independent implementation | exact match, both forms |
| 6 | Two wrong keys | 0 false positives |
| 7 | Wrong IV with correct key | padding passes, first 16 bytes of the key corrupted (defect, documented above) |
| 8 | `tools/verify_key.py` hash160 / address logic | round-trips: `hash160(pubkey)` equals the address payload |
| 9 | `tools/make_test_wallet.sh` preflight without Core | fails fast with install instructions |
| 10 | `wallet.dat` format sniffing (BDB vs SQLite) | implemented; SQLite wallets rejected with explanation |

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `There is no mkey string in the file` | Wallet is SQLite (Core ≥ 0.21 default) or not a wallet | Recreate with `descriptors=false` (Core ≤ 28), or unload the descriptor wallet and use a legacy one |
| `There is no Master Key in the file` | Wallet was never encrypted | `encryptwallet` first — an unencrypted wallet has no `mkey` to crack |
| `nDerivations cannot be less than 25000` | Non-standard/legacy iteration count | Lower the guard in `crackbtcshell.c` or use a wallet encrypted with default settings |
| `try key` never finds the key | Wrong passphrase, or wrong salt/iteration count | Re-read salt + `nDerivations` with `extractmkey`; confirm the passphrase exactly |
| `Decrypted:` looks plausible but the address does not match | Wrong IV (see above) | Try the other IV derivation; then verify with `verify_key.py --address` |
| `yasm: command not found` | AES-NI build requires yasm | `make noaesni`, or install yasm (`apt install yasm` / `brew install yasm`) |

---

## A reality check on `start`

`try key` and `keyderivation` **verify** a key you already have. `start` actually
brute-forces the 256-bit AES key: 2²⁵⁶ candidates at ~150 million keys/s is ~10⁶⁹ years on
the hardware in `README.md`. The PoC demonstrates that the decryption path is correct; it
is not a recovery route for a wallet whose passphrase you have lost. What
`docs/TESTING.md` shows is the honest, useful part: given the passphrase or key, the
tooling recovers and validates the private key correctly.

---

## What to do next

1. **Path A first** — 2 minutes, proves the binary on your machine.
2. **Path B** if you want the real `wallet.dat` path end to end (testnet, throwaway wallet).
3. If any step disagrees with this document, that is a finding: the exact command, the
   observed output and the expected output are enough to turn it into a test case.
