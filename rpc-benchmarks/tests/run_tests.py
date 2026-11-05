#!/usr/bin/env python3
"""Regression test for benchmark_tools.py's Markdown parser.

The Alchemy export arrives in two flavours depending on how it is fetched:
plain Markdown tables (`| a | b |`) and backslash-escaped tables (`\\| a \\| b \\|`).
Both must parse identically.

Run:  python3 tests/run_tests.py
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(ROOT, "benchmark_tools.py")
FIXTURE = os.path.join(HERE, "fixture.md")

EXPECTED_OVERVIEW = [
    ("Ethereum", "US East", "Alchemy", 7.31, 5.27, 10.23, 100.0),
    ("Ethereum", "US East", "Goldsky", 7.50, 5.31, 11.73, 100.0),
    ("Solana", "Global", "Alchemy", 7.92, 5.39, 13.95, 100.0),
]

failure = 0


def check(label, condition, detail=""):
    global failure
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        failure += 1


def parse(markdown_path, workdir):
    prefix = os.path.join(workdir, "out_")
    result = subprocess.run(
        [sys.executable, TOOL, "parse", "--file", markdown_path, "--out-prefix", prefix],
        capture_output=True, text=True,
    )
    check(f"parser exits 0 for {os.path.basename(markdown_path)}", result.returncode == 0, result.stderr)
    rows = []
    csv_path = prefix + "overview.csv"
    if os.path.exists(csv_path):
        import csv
        with open(csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                rows.append((row["chain"], row["region"], row["provider"],
                             float(row["avg_ms"]), float(row["p50_ms"]),
                             float(row["p95_ms"]), float(row["success_pct"])))
    return rows, prefix


def main():
    with tempfile.TemporaryDirectory() as workdir:
        # 1. escaped flavour
        escaped, prefix = parse(FIXTURE, workdir)
        check("escaped export yields 3 provider rows", len(escaped) == 3, f"got {len(escaped)}")
        check("escaped export matches expected values", escaped == EXPECTED_OVERVIEW, str(escaped))

        # 2. plain flavour (same document, backslashes stripped)
        plain_path = os.path.join(workdir, "plain.md")
        with open(FIXTURE, encoding="utf-8") as fh:
            text = fh.read()
        for token in ("\\|", "\\#", "\\_", "\\-"):
            text = text.replace(token, token[1])
        with open(plain_path, "w", encoding="utf-8") as fh:
            fh.write(text)
        plain, _ = parse(plain_path, workdir)
        check("plain export parses identically to escaped", plain == escaped, str(plain))

        # 3. method table captured
        methods_csv = prefix + "methods.csv"
        with open(methods_csv, encoding="utf-8") as fh:
            lines = [line for line in fh.read().splitlines() if line.strip()]
        check("method table captured (header + 2 rows)", len(lines) == 3, str(lines))
        check("method name unescaped",
              any("eth_getBalance" in line for line in lines),
              "escaped underscores were not normalised")

        # 4. description strings do not leak into data rows
        check("no separator rows leaked into overview",
              all("---" not in provider for _, _, provider, *_ in escaped),
              str([r[2] for r in escaped]))

        # 5. summary and score run against the fixture without crashing
        for sub in (["summary", "--csv", prefix + "overview.csv"],
                    ["score", "--csv", prefix + "overview.csv"]):
            result = subprocess.run([sys.executable, TOOL, *sub], capture_output=True, text=True)
            check(f"`{sub[0]}` runs on fixture data", result.returncode == 0, result.stderr)

    print()
    if failure:
        print(f"{failure} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
