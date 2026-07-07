"""Command-line interface for the Smart VPNGate V2 Smart Exit Manager.

Subcommands:

    discover   fetch, filter and cache candidate exit nodes (Discovery only)
    run        run the full Smart Exit Manager loop (all layers)
    status     print the current dashboard snapshot from the last cache

Examples::

    python -m smart_vpngate discover --from-file feed.csv
    python -m smart_vpngate run --provider fake --once        # offline demo
    python -m smart_vpngate run --provider vpngate            # real VPS run
    python -m smart_vpngate status
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

from .config import Config
from .dashboard import node_row
from .discovery import Discovery
from .fetch import DEFAULT_API_URL, http_fetcher
from .manager import SmartExitManager
from .models import Node
from .probes import null_probe, tcp_probe


# --------------------------------------------------------------------------- #
# discover
# --------------------------------------------------------------------------- #
def _print_table(nodes: list[Node]) -> None:
    if not nodes:
        print("(no nodes matched the current discovery filters)")
        return
    header = f"{'COUNTRY':<8}{'PROTO':<6}{'SCORE':>10}  {'PING':>5}  {'ID'}"
    print(header)
    print("-" * len(header))
    for n in nodes:
        print(f"{n.country_short:<8}{n.protocol:<6}{n.vpngate_score:>10}  "
              f"{n.ping:>5}  {n.id}")
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
        fetcher = lambda: text  # noqa: E731
    else:
        fetcher = http_fetcher(args.url)

    discovery = Discovery(config.discovery, fetcher=fetcher, cache_path=args.cache)
    try:
        nodes = discovery.refresh()
    except Exception as exc:  # noqa: BLE001
        print(f"discovery failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([n.to_dict() for n in nodes], ensure_ascii=False, indent=2))
    else:
        _print_table(nodes)
        print(f"cached -> {discovery.cache_path}")
    return 0


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #
def _demo_feed() -> str:
    """A synthetic VPNGate CSV feed for offline demos (`--provider fake`)."""
    def ovpn(ip, port, proto):
        return base64.b64encode(
            f"client\nproto {proto}\nremote {ip} {port}\n".encode()).decode()

    header = ("#HostName,IP,Score,Ping,Speed,CountryLong,CountryShort,"
              "NumVpnSessions,OpenVPN_ConfigData_Base64")
    rows = [
        ("jp1", "203.0.113.11", 9_000_000, 18, "Japan", "JP", "tcp", 443),
        ("jp2", "203.0.113.12", 8_200_000, 25, "Japan", "JP", "tcp", 443),
        ("kr1", "203.0.113.21", 7_500_000, 30, "Korea Republic of", "KR", "tcp", 443),
        ("us1", "203.0.113.31", 6_800_000, 120, "United States", "US", "tcp", 443),
    ]
    lines = ["*vpn_servers", header]
    for h, ip, sc, pg, cl, cs, pr, po in rows:
        lines.append(",".join([h, ip, str(sc), str(pg), "1000000", cl, cs, "5",
                               ovpn(ip, po, pr)]))
    lines.append("*")
    return "\n".join(lines)


def _print_dashboard(snap: dict) -> None:
    cur = snap["current_exit"]
    print("=== Current Exit ===")
    if cur["connected"]:
        print(f"  provider : {cur['provider']}")
        print(f"  node     : {cur['node_id']} ({cur['country_short']})")
        print(f"  protocol : {cur['protocol']}   health: {cur['health']}")
        print(f"  public IP: {cur['public_ip']}")
        print(f"  uptime   : {cur['connected_seconds']}s")
    else:
        print(f"  (not connected){'  ' + cur['last_error'] if cur['last_error'] else ''}")
    if cur.get("last_decision"):
        d = cur["last_decision"]
        print(f"  policy   : {d['action']} — {d['reason']}")

    print(f"\n=== Node Table ({snap['total_nodes']} nodes, "
          f"{len(snap['countries'])} countries) ===")
    header = f"{'CUR':<4}{'COUNTRY':<8}{'PROTO':<6}{'STATUS':<10}{'SCORE':>9}  {'ID'}"
    print(header)
    print("-" * len(header))
    for r in snap["nodes"]:
        mark = "->" if r["current"] else ""
        print(f"{mark:<4}{r['country_short']:<8}{r['protocol']:<6}"
              f"{r['status']:<10}{r['score']:>9}  {r['id']}")


def _build_app(args: argparse.Namespace) -> SmartExitManager:
    config = Config.load(args.config)
    if args.provider == "fake":
        from .providers.fake import FakeProvider
        # Seed the fake provider from the same synthetic feed the pool will use.
        from .discovery import parse_rows, row_to_node
        nodes = [n for n in (row_to_node(r, "fake") for r in parse_rows(_demo_feed()))
                 if n is not None]
        provider = FakeProvider(nodes)
        fetcher = _demo_feed
        probe = null_probe
    else:
        from .providers.vpngate import VPNGateProvider
        provider = VPNGateProvider(api_url=args.url)
        fetcher = http_fetcher(args.url)
        probe = tcp_probe()
    return SmartExitManager.build(config, provider=provider, fetcher=fetcher,
                                  probe=probe, cache_path=args.cache)


def _cmd_run(args: argparse.Namespace) -> int:
    app = _build_app(args)
    try:
        if args.once:
            app.run(once=True)
            _print_dashboard(app.dashboard())
            return 0
        print(f"Smart Exit Manager running (provider={args.provider}, "
              f"health interval={app.config.health.interval}s). Ctrl-C to stop.")
        app.run(max_ticks=args.max_ticks)
    except KeyboardInterrupt:
        app.stop()
        app.exit.disconnect()
        print("\nstopped.")
    except Exception as exc:  # noqa: BLE001
        print(f"run failed: {exc}", file=sys.stderr)
        return 1
    return 0


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
def _cmd_status(args: argparse.Namespace) -> int:
    cache = Path(args.cache)
    if not cache.exists():
        print(f"no cache at {cache}; run 'discover' or 'run' first.", file=sys.stderr)
        return 1
    payload = json.loads(cache.read_text(encoding="utf-8"))
    nodes = [Node.from_dict(d) for d in payload.get("nodes", [])]
    rows = [node_row(n, None) for n in nodes]
    snap = {
        "current_exit": {"connected": False, "last_error": "", "provider": "",
                         "node_id": "", "country_short": "", "protocol": "",
                         "health": "", "public_ip": "", "connected_seconds": 0,
                         "last_decision": None},
        "nodes": rows,
        "countries": sorted({n.country_short for n in nodes}),
        "total_nodes": len(nodes),
    }
    print(f"(cache from {cache}, cached_at epoch {payload.get('cached_at', 0)})")
    _print_dashboard(snap)
    return 0


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smart_vpngate",
        description="Smart VPNGate V2 — policy-driven Smart Exit Manager",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common_cache = ("--cache", {"default": "vpngate_data/smart_nodes.json",
                                "help": "node cache path"})
    common_config = ("-c", "--config", {"default": "config.yaml",
                     "help": "YAML config path (missing = defaults)"})

    d = sub.add_parser("discover", help="fetch, filter and cache candidate nodes")
    d.add_argument("-c", "--config", default="config.yaml", help=common_config[2]["help"])
    d.add_argument(common_cache[0], **common_cache[1])
    d.add_argument("--url", default=DEFAULT_API_URL, help="VPNGate API URL")
    d.add_argument("--from-file", metavar="PATH", help="read feed from a local CSV file")
    d.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    d.set_defaults(func=_cmd_discover)

    r = sub.add_parser("run", help="run the full Smart Exit Manager loop")
    r.add_argument("-c", "--config", default="config.yaml", help=common_config[2]["help"])
    r.add_argument(common_cache[0], **common_cache[1])
    r.add_argument("--provider", choices=["vpngate", "fake"], default="vpngate",
                   help="exit provider (fake = offline in-memory demo)")
    r.add_argument("--url", default=DEFAULT_API_URL, help="VPNGate API URL")
    r.add_argument("--once", action="store_true",
                   help="run a single tick then print the dashboard and exit")
    r.add_argument("--max-ticks", type=int, default=None,
                   help="stop after N ticks (default: run forever)")
    r.set_defaults(func=_cmd_run)

    s = sub.add_parser("status", help="print the dashboard from the last cache")
    s.add_argument(common_cache[0], **common_cache[1])
    s.set_defaults(func=_cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
