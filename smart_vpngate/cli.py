"""Command-line interface for the Smart VPNGate V2 modules.

Currently exposes the **Discovery** layer end-to-end (the first implemented
layer). As NodePool / Policy / Exit Manager land, they will get their own
subcommands here.

Usage::

    python -m smart_vpngate discover                 # fetch live, filter, cache
    python -m smart_vpngate discover --config config.yaml
    python -m smart_vpngate discover --from-file feed.csv   # offline, no network
    python -m smart_vpngate discover --json          # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Config
from .discovery import Discovery
from .fetch import DEFAULT_API_URL, http_fetcher
from .models import Node


def _print_table(nodes: list[Node]) -> None:
    if not nodes:
        print("(no nodes matched the current discovery filters)")
        return
    header = f"{'COUNTRY':<8}{'PROTO':<6}{'SCORE':>10}  {'PING':>5}  {'ID'}"
    print(header)
    print("-" * len(header))
    for n in nodes:
        print(
            f"{n.country_short:<8}{n.protocol:<6}{n.vpngate_score:>10}  "
            f"{n.ping:>5}  {n.id}"
        )
    # Per-country summary.
    counts: dict[str, int] = {}
    for n in nodes:
        counts[n.country_short] = counts.get(n.country_short, 0) + 1
    summary = ", ".join(f"{c}={counts[c]}" for c in sorted(counts))
    print("-" * len(header))
    print(f"total {len(nodes)} nodes  [{summary}]")


def _cmd_discover(args: argparse.Namespace) -> int:
    config = Config.load(args.config)

    if args.from_file:
        text = Path(args.from_file).read_text(encoding="utf-8")
        fetcher = lambda: text  # noqa: E731 - trivial injected fetcher
    else:
        fetcher = http_fetcher(args.url)

    discovery = Discovery(config.discovery, fetcher=fetcher, cache_path=args.cache)
    try:
        nodes = discovery.refresh()
    except Exception as exc:  # noqa: BLE001 - surface a clean CLI error
        print(f"discovery failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([n.to_dict() for n in nodes], ensure_ascii=False, indent=2))
    else:
        _print_table(nodes)
        print(f"cached -> {discovery.cache_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smart_vpngate",
        description="Smart VPNGate V2 — policy-driven Smart Exit Manager (dev preview)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="fetch, filter and cache candidate exit nodes")
    d.add_argument("-c", "--config", default="config.yaml",
                   help="path to YAML config (default: config.yaml; missing = defaults)")
    d.add_argument("--cache", default="vpngate_data/smart_nodes.json",
                   help="where to write the filtered node cache")
    d.add_argument("--url", default=DEFAULT_API_URL,
                   help="VPNGate API URL to fetch from")
    d.add_argument("--from-file", metavar="PATH",
                   help="read the feed from a local CSV file instead of the network")
    d.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    d.set_defaults(func=_cmd_discover)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
