#!/usr/bin/env python3
"""
benchmark_tools.py - parse, analyse and visualise the Alchemy RPC benchmark export.

The public export at https://www.alchemy.com/benchmarks/data.md is a Markdown
document that regenerates every 5 minutes. This script turns it into data you can
sort, diff, chart and version-control.

Usage
-----
    # Parse a local copy of the export (after saving the page to data.md)
    python3 benchmark_tools.py parse --file data.md

    # Fetch directly (requires outbound network to www.alchemy.com)
    python3 benchmark_tools.py parse --url https://www.alchemy.com/benchmarks/data.md

    # Show who wins where, plus data-quality anomalies
    python3 benchmark_tools.py summary --csv overview.csv

    # Build a dependency-free HTML dashboard from the CSV
    # Weight the benchmark by your own traffic mix
    python3 benchmark_tools.py score --csv overview.csv --weights weights.example.csv

    # Build a dependency-free HTML dashboard from the CSV
    python3 benchmark_tools.py dashboard --csv overview.csv --out index.html

Outputs (defaults, override with --out)
---------------------------------------
    overview.csv   one row per (chain, region, provider): avg / p50 / p95 / success
    methods.csv    one row per (chain, region, method, provider): avg latency
    failures.csv   one row per (chain, region, method, provider): failed requests
    overview.json  overview.csv as JSON, keyed by chain -> region -> provider

No third-party dependencies. Python 3.8+.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
from collections import OrderedDict, defaultdict

# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

SECTION_RE = re.compile(r"^#{2,4}\s*(?P<chain>[^#—–-]+?)\s*[—–]\s*(?P<region>[^#]+?)\s*$")
TABLE_TITLE_RE = re.compile(r"^#{3,5}\s*(?P<title>[^#]+?)\s*$")
NUM_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")

REGION_CANON = {
    "global": "Global",
    "us east": "US East",
    "us west": "US West",
    "eu central": "EU Central",
    "eu west": "EU West",
    "ap southeast": "AP Southeast",
    "ap south east": "AP Southeast",
}

CHAIN_CANON = {
    "evm overall": "EVM Overall",
    "worldchain": "World Chain",
    "world chain": "World Chain",
    "bnb": "BNB Chain",
    "bnb chain": "BNB Chain",
    "robinhood": "Robinhood Chain",
    "robinhood chain": "Robinhood Chain",
}


def unescape(text: str) -> str:
    """The export is sometimes delivered with backslash-escaped Markdown punctuation."""
    for a, b in (("\\|", "|"), ("\\#", "#"), ("\\_", "_"), ("\\-", "-"), ("\\*", "*")):
        text = text.replace(a, b)
    return text


def num(cell: str):
    """'13.60 ms' -> 13.60 ; '99.99%' -> 99.99 ; '—' -> None"""
    if not cell:
        return None
    m = NUM_RE.search(cell)
    return float(m.group(0)) if m else None


def split_row(line: str):
    line = line.strip()
    if not line.startswith("|"):
        return None
    body = line.strip("|")
    cells = [c.strip().strip("\\") for c in body.split("|")]
    # separator row: every non-empty cell is dashes / colons
    if cells and all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
        return None
    return None if not any(cells) else cells


def canon_chain(name: str) -> str:
    key = name.strip().lower()
    return CHAIN_CANON.get(key, name.strip())


def canon_region(name: str) -> str:
    key = name.strip().lower()
    return REGION_CANON.get(key, name.strip())


def parse_markdown(text: str):
    """Return (overview_rows, method_rows, failure_rows)."""
    text = unescape(text)
    lines = text.splitlines()

    chain = region = None
    table = None          # current table title, lowercased
    header = None         # current table header cells
    overview, methods, failures = [], [], []

    for raw in lines:
        line = raw.rstrip()

        sec = SECTION_RE.match(line.lstrip())
        if sec:
            chain = canon_chain(sec.group("chain"))
            region = canon_region(sec.group("region").strip("* "))
            table, header = None, None
            continue

        title = TABLE_TITLE_RE.match(line.lstrip())
        if title:
            t = title.group("title").strip("* ").lower()
            if "provider overview" in t:
                table = "overview"
            elif "average latency by method" in t:
                table = "method_avg"
            elif "failed requests by method" in t:
                table = "method_fail"
            elif t.startswith(("summary stats",)):
                table = "summary"
            else:
                table = None
            header = None
            continue

        cells = split_row(line)
        if cells is None or chain is None or region is None or table is None:
            continue

        if header is None:
            if cells[0].strip().lower() in ("provider", "method"):
                header = [c.lower() for c in cells]
                continue
            continue

        if table == "overview" and len(cells) >= 5:
            provider = cells[0].strip()
            if not provider or provider.lower() == "provider" or set(provider) <= {"-", ":"}:
                continue
            overview.append({
                "chain": chain,
                "region": region,
                "provider": provider,
                "avg_ms": num(cells[1]),
                "p50_ms": num(cells[2]),
                "p95_ms": num(cells[3]),
                "success_pct": num(cells[4]),
            })
        elif table in ("method_avg", "method_fail") and len(cells) >= 3:
            method = cells[0].strip()
            if not method or method.lower() == "method" or set(method) <= {"-", ":"}:
                continue
            for provider, value in zip(header[1:], cells[1:]):
                row = {
                    "chain": chain,
                    "region": region,
                    "method": method,
                    "provider": provider,
                    "value": num(value),
                }
                (methods if table == "method_avg" else failures).append(row)

    return overview, methods, failures


# --------------------------------------------------------------------------- #
# IO helpers
# --------------------------------------------------------------------------- #

def write_csv(path: str, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fields})
    print(f"wrote {path} ({len(rows)} rows)")


def read_overview(path: str):
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        for key in ("avg_ms", "p50_ms", "p95_ms", "success_pct"):
            row[key] = float(row[key]) if row.get(key) else None
    return rows


# --------------------------------------------------------------------------- #
# Analysis
# --------------------------------------------------------------------------- #

def group(rows, *keys):
    out = OrderedDict()
    for row in rows:
        k = tuple(row[key] for key in keys)
        out.setdefault(k, []).append(row)
    return out


def cmd_summary(args):
    rows = read_overview(args.csv)
    by_cell = group(rows, "chain", "region")

    print(f"\n=== Winners by average latency ({len(by_cell)} chain/region cells) ===")
    wins = defaultdict(int)
    for (chain, region), cellrows in by_cell.items():
        ranked = sorted(cellrows, key=lambda r: (r["avg_ms"] is None, r["avg_ms"] or 0))
        best = ranked[0]
        wins[best["provider"]] += 1
        runner = ranked[1] if len(ranked) > 1 else None
        gap = f" (+{runner['avg_ms'] - best['avg_ms']:.2f} ms over {runner['provider']})" if runner else ""
        print(f"{chain:<14} {region:<13} {best['provider']:<10} {best['avg_ms']:>7.2f} ms{gap}")
    print("\nWin tally:", dict(sorted(wins.items(), key=lambda kv: -kv[1])))

    print("\n=== Tail behaviour (P95 / average multiplier, global rows) ===")
    for row in sorted((r for r in rows if r["region"] == "Global"),
                      key=lambda r: -(r["p95_ms"] or 0) / max(r["avg_ms"] or 1, 0.01)):
        ratio = (row["p95_ms"] or 0) / max(row["avg_ms"] or 0.01, 0.01)
        print(f"{row['chain']:<12} {row['provider']:<10} avg {row['avg_ms']:>7.2f}  "
              f"p95 {row['p95_ms']:>8.2f}  ratio {ratio:>5.1f}x")

    print("\n=== Data-quality flags ===")
    flags = 0
    for row in rows:
        if row["p50_ms"] and row["avg_ms"] and row["p50_ms"] > row["avg_ms"]:
            print(f"  median exceeds mean: {row['chain']}/{row['region']}/{row['provider']} "
                  f"p50 {row['p50_ms']} > avg {row['avg_ms']}")
            flags += 1
        if row["p95_ms"] and row["p50_ms"] and row["p95_ms"] < row["p50_ms"]:
            print(f"  p95 below p50: {row['chain']}/{row['region']}/{row['provider']}")
            flags += 1
    print(f"  {flags} anomaly row(s) out of {len(rows)}")


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #

PROVIDER_COLOURS = ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#ec4899"]


def svg_bars(cellrows, metric: str, width: int = 560, bar_h: int = 14, gap: int = 6) -> str:
    ranked = sorted(cellrows, key=lambda r: (r[metric] is None, r[metric] or 0))
    top = max((r[metric] or 0) for r in ranked) or 1
    label_w, value_w = 96, 74
    plot_w = width - label_w - value_w
    height = len(ranked) * (bar_h + gap) + gap
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
             f'role="img" aria-label="{html.escape(metric)} comparison">']
    for i, row in enumerate(ranked):
        y = gap + i * (bar_h + gap)
        value = row[metric] or 0
        bar_w = max(2, round(plot_w * value / top))
        colour = PROVIDER_COLOURS[i % len(PROVIDER_COLOURS)]
        parts.append(
            f'<rect x="{label_w}" y="{y}" width="{bar_w}" height="{bar_h}" rx="3" fill="{colour}" opacity="0.85"/>'
        )
        parts.append(
            f'<text x="{label_w - 8}" y="{y + bar_h - 3}" text-anchor="end" '
            f'font-family="ui-sans-serif,system-ui,sans-serif" font-size="11" fill="#334155">'
            f'{html.escape(row["provider"])}</text>'
        )
        parts.append(
            f'<text x="{label_w + bar_w + 6}" y="{y + bar_h - 3}" '
            f'font-family="ui-monospace,SFMono-Regular,monospace" font-size="11" fill="#475569">'
            f'{value:.2f}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def cmd_dashboard(args):
    rows = read_overview(args.csv)
    chains = OrderedDict()
    for row in rows:
        chains.setdefault(row["chain"], OrderedDict()).setdefault(row["region"], []).append(row)

    source = args.source or "https://www.alchemy.com/benchmarks/data.md"
    out = [
        "<!doctype html><meta charset='utf-8'>",
        "<title>RPC provider benchmarks - extracted view</title>",
        "<style>",
        ":root{color-scheme:light dark}",
        "body{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;max-width:1180px;"
        "margin:0 auto;padding:32px 20px 72px;color:#0f172a;background:#fff;line-height:1.5}",
        "h1{font-size:30px;margin:0 0 6px}",
        "h2{font-size:21px;margin:44px 0 4px;border-bottom:2px solid #e2e8f0;padding-bottom:6px}",
        "h3{font-size:15px;margin:24px 0 6px;color:#334155;text-transform:uppercase;"
        "letter-spacing:.06em;font-weight:600}",
        ".meta{color:#64748b;font-size:13px;margin-bottom:22px}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:18px 34px}",
        ".card{border:1px solid #e2e8f0;border-radius:10px;padding:14px 16px 8px;background:#fcfdff}",
        ".card h4{margin:0 0 2px;font-size:14px}",
        ".card .sub{color:#94a3b8;font-size:11px;margin-bottom:10px}",
        "table{border-collapse:collapse;width:100%;font-size:13px;margin:8px 0 20px}",
        "th,td{text-align:left;padding:6px 10px;border-bottom:1px solid #eef2f7}",
        "th{background:#f8fafc;font-weight:600;font-size:12px;text-transform:uppercase;"
        "letter-spacing:.04em;color:#475569}",
        "td.num{font-variant-numeric:tabular-nums;font-family:ui-monospace,SFMono-Regular,monospace}",
        ".best{background:#ecfdf5;font-weight:600}",
        ".warn{color:#b45309}",
        "code{background:#f1f5f9;padding:1px 5px;border-radius:4px;font-size:12px}",
        "@media (prefers-color-scheme:dark){body{background:#0b1120;color:#e2e8f0}"
        "h2{border-color:#1e293b}.card{background:#111a2e;border-color:#1e293b}"
        ".card .sub,.meta{color:#94a3b8}th{background:#111a2e;color:#cbd5e1}"
        "td,th{border-color:#1e293b}.best{background:#052e21}code{background:#1e293b}}",
        "</style>",
        "<h1>RPC provider benchmarks — extracted view</h1>",
        f"<p class='meta'>Source: <a href='{html.escape(source)}'>{html.escape(source)}</a> · "
        f"{len(rows)} provider rows · generated by <code>benchmark_tools.py</code>. "
        "Latency in milliseconds, lower is better.</p>",
    ]

    # Global comparison table
    out.append("<h2>Global overview</h2>")
    globals_ = [r for r in rows if r["region"] == "Global"]
    if globals_:
        chains_seen = list(OrderedDict.fromkeys(r["chain"] for r in globals_))
        for chain in chains_seen:
            out.append(f"<h3>{html.escape(chain)}</h3><table><tr><th>Provider</th>"
                       "<th>Average</th><th>P50</th><th>P95</th><th>Success</th>"
                       "<th>P95 ÷ avg</th></tr>")
            cell = [r for r in globals_ if r["chain"] == chain]
            best_avg = min((r["avg_ms"] for r in cell if r["avg_ms"] is not None), default=None)
            for r in sorted(cell, key=lambda x: x["avg_ms"] or 1e9):
                klass = " class='best'" if r["avg_ms"] == best_avg else ""
                ratio = (r["p95_ms"] / r["avg_ms"]) if r["avg_ms"] else 0
                out.append(
                    f"<tr{klass}><td>{html.escape(r['provider'])}</td>"
                    f"<td class='num'>{r['avg_ms']:.2f}</td>"
                    f"<td class='num'>{r['p50_ms']:.2f}</td>"
                    f"<td class='num'>{r['p95_ms']:.2f}</td>"
                    f"<td class='num'>{r['success_pct']:.2f}%</td>"
                    f"<td class='num'>{ratio:.1f}x</td></tr>"
                )
            out.append("</table>")

    # Per chain: regional bar charts
    for chain, regions in chains.items():
        out.append(f"<h2>{html.escape(chain)}</h2>")
        out.append("<div class='grid'>")
        for region, cellrows in regions.items():
            out.append("<div class='card'>")
            out.append(f"<h4>{html.escape(region)}</h4>")
            out.append("<div class='sub'>average latency (ms)</div>")
            out.append(svg_bars(cellrows, "avg_ms"))
            out.append("<div class='sub' style='margin-top:10px'>P95 latency (ms)</div>")
            out.append(svg_bars(cellrows, "p95_ms"))
            out.append("</div>")
        out.append("</div>")

    out.append("<h2>Notes</h2><p class='meta'>Published by Alchemy about its own market; "
               "read-only synthetic payloads, warmed connections, single trailing 24h window, "
               "measured AWS-to-provider. Treat as a hypothesis to verify, not an audit. "
               "See the accompanying report for methodology caveats and a validation plan.</p>")

    path = args.out
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print(f"wrote {path} ({len(out)} blocks)")



def cmd_score(args):
    """Weight the benchmark by your own traffic mix and rank providers."""
    rows = read_overview(args.csv)
    cells = group(rows, "chain", "region")

    weights = {}
    if args.weights:
        with open(args.weights, newline="", encoding="utf-8") as fh:
            for w in csv.DictReader(fh):
                weights[(canon_chain(w["chain"]), canon_region(w["region"]))] = float(w["weight"])
    total_w = sum(weights.values()) if weights else 0.0

    if not weights:
        print("no --weights file supplied; scoring every cell with equal weight")
        weights = {cell: 1.0 for cell in cells}
        total_w = float(len(cells))

    providers = sorted({r["provider"] for r in rows})
    scoreboard = []
    for provider in providers:
        wavg = wp95 = used = 0.0
        worst = None
        missing = []
        for cell, weight in weights.items():
            cellrows = {r["provider"]: r for r in cells.get(cell, [])}
            row = cellrows.get(provider)
            if row is None or row["avg_ms"] is None:
                missing.append(f"{cell[0]}/{cell[1]}")
                continue
            wavg += weight * row["avg_ms"]
            wp95 += weight * (row["p95_ms"] or row["avg_ms"])
            used += weight
            if worst is None or row["p95_ms"] > worst["p95_ms"]:
                worst = {"chain": cell[0], "region": cell[1], "p95_ms": row["p95_ms"]}
        if not used:
            continue
        share = used / total_w if total_w else 1.0
        scoreboard.append({
            "provider": provider,
            "weighted_avg": wavg / used,
            "weighted_p95": wp95 / used,
            "coverage": share,
            "worst": worst,
            "missing": missing,
        })

    if not scoreboard:
        sys.exit("no provider had data for the requested cells")

    scoreboard.sort(key=lambda r: r["weighted_avg"])
    print(f"\n{'provider':<12}{'w.avg':>9}{'w.p95':>9}{'coverage':>10}   worst P95 cell")
    for row in scoreboard:
        worst = row["worst"]
        print(f"{row['provider']:<12}{row['weighted_avg']:>8.2f}ms{row['weighted_p95']:>8.2f}ms"
              f"{row['coverage']*100:>9.0f}%   {worst['chain']}/{worst['region']} {worst['p95_ms']:.0f}ms")
        if row["missing"]:
            print(f"{'':<12}not measured in: {', '.join(row['missing'])}")

    print("\nReminder: 'coverage' is the share of YOUR traffic weight a provider was actually "
          "measured on. A provider measured on 40% of your traffic is not a drop-in primary.")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def cmd_parse(args):
    if args.file:
        with open(args.file, encoding="utf-8") as fh:
            text = fh.read()
    elif args.url:
        import urllib.request
        with urllib.request.urlopen(args.url, timeout=60) as resp:
            text = resp.read().decode("utf-8", "replace")
    else:
        sys.exit("pass --file or --url")

    overview, methods, failures = parse_markdown(text)
    if not overview:
        sys.exit("no provider-overview tables found - did the export format change?")

    base = args.out_prefix
    write_csv(f"{base}overview.csv", overview,
              ["chain", "region", "provider", "avg_ms", "p50_ms", "p95_ms", "success_pct"])
    write_csv(f"{base}methods.csv", methods, ["chain", "region", "method", "provider", "value"])
    write_csv(f"{base}failures.csv", failures, ["chain", "region", "method", "provider", "value"])

    nested = defaultdict(lambda: defaultdict(OrderedDict))
    for row in overview:
        nested[row["chain"]][row["region"]][row["provider"]] = {
            "avg_ms": row["avg_ms"], "p50_ms": row["p50_ms"],
            "p95_ms": row["p95_ms"], "success_pct": row["success_pct"],
        }
    with open(f"{base}overview.json", "w", encoding="utf-8") as fh:
        json.dump(nested, fh, indent=2)
    print(f"wrote {base}overview.json ({len(overview)} rows)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("parse", help="parse the Markdown export into CSV/JSON")
    p.add_argument("--file")
    p.add_argument("--url")
    p.add_argument("--out-prefix", default="")
    p.set_defaults(func=cmd_parse)

    s = sub.add_parser("summary", help="who wins where, plus data-quality flags")
    s.add_argument("--csv", default="overview.csv")
    s.set_defaults(func=cmd_summary)

    sc = sub.add_parser("score", help="rank providers against your own traffic weights")
    sc.add_argument("--csv", default="overview.csv")
    sc.add_argument("--weights", default=None, help="CSV: chain,region,weight")
    sc.set_defaults(func=cmd_score)

    d = sub.add_parser("dashboard", help="build a standalone HTML dashboard")
    d.add_argument("--csv", default="overview.csv")
    d.add_argument("--out", default="index.html")
    d.add_argument("--source", default=None)
    d.set_defaults(func=cmd_dashboard)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
