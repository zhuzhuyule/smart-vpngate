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
        # New design: the brain drives the OLD proven engine (OpenVPN + hardened
        # routing). Use the minimal built-in connector only if explicitly asked.
        # Public-IP query routes through the gateway (exit IP, not VPS IP),
        # unless the proxy is disabled.
        proxy_url = (None if getattr(args, "no_proxy", False)
                     else f"http://{getattr(args, 'proxy_host', '127.0.0.1')}:"
                          f"{getattr(args, 'proxy_port', 7928)}")
        if getattr(args, "minimal_connector", False):
            provider = VPNGateProvider(api_url=args.url, proxy_url=proxy_url)
        else:
            from .providers.legacy import LegacyEngineConnector
            provider = VPNGateProvider(connector=LegacyEngineConnector(),
                                       api_url=args.url, proxy_url=proxy_url)
        fetcher = http_fetcher(args.url)
        probe = tcp_probe()
    return SmartExitManager.build(config, provider=provider, fetcher=fetcher,
                                  probe=probe, cache_path=args.cache)


def _maybe_start_gateway(args: argparse.Namespace) -> None:
    """Start the legacy 7928 proxy gateway for real (vpngate) runs."""
    if args.provider != "vpngate" or getattr(args, "no_proxy", False):
        return
    try:
        from .gateway import start_proxy_gateway
        start_proxy_gateway(args.proxy_host, args.proxy_port)
        print(f"proxy gateway (SOCKS5/HTTP) on {args.proxy_host}:{args.proxy_port}")
    except Exception as exc:  # noqa: BLE001 - proxy is best-effort
        print(f"warning: could not start proxy gateway: {exc}", file=sys.stderr)


def _cmd_run(args: argparse.Namespace) -> int:
    app = _build_app(args)
    _maybe_start_gateway(args)
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
# web
# --------------------------------------------------------------------------- #
def _build_auth(args: argparse.Namespace):
    """Build the dashboard Auth, or None. Default: on for vpngate, off for fake."""
    from .auth import Auth, generate_password, generate_secret_path
    if getattr(args, "no_auth", False):
        return None
    want = getattr(args, "auth", False) or args.provider == "vpngate"
    password = getattr(args, "password", None) or ""
    secret = getattr(args, "secret_path", None) or ""
    if not want and not password:
        return None
    if not password or not secret:
        # Reuse the legacy credentials so it's the same login as before.
        try:
            import vpngate_manager as eng
            cfg = eng.load_ui_config()
            password = password or (cfg.get("password") or "")
            secret = secret or (cfg.get("secret_path") or "")
        except Exception:  # noqa: BLE001 - legacy config optional
            pass
    if not password:
        password = generate_password()
    if not secret:
        secret = generate_secret_path()
    return Auth(password=password, secret_path=secret)


def _cmd_web(args: argparse.Namespace) -> int:
    from .web import DashboardServer
    app = _build_app(args)
    _maybe_start_gateway(args)
    auth = _build_auth(args)
    server = DashboardServer(app, host=args.host, port=args.port,
                             tick_interval=args.tick_interval, auth=auth)
    shown_host = "[::]" if args.host in ("::", "") else args.host
    base = f"http://{shown_host}:{args.port}"
    if auth is not None and auth.enabled:
        print(f"Smart VPNGate dashboard: {base}{auth.prefix}/  (provider={args.provider})")
        print(f"  login password: {auth.password}")
    else:
        print(f"Smart VPNGate dashboard: {base}/  (provider={args.provider}, no auth)")
    print("Ctrl-C to stop.")
    try:
        server.start(serve=True)
    except OSError as exc:
        print(f"failed to start server: {exc}", file=sys.stderr)
        return 1
    print("\nstopped.")
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
def _add_engine_args(p: argparse.ArgumentParser) -> None:
    """Engine/gateway options shared by 'run' and 'web' (real vpngate runs)."""
    p.add_argument("--minimal-connector", action="store_true",
                   help="use the built-in minimal OpenVPN starter instead of the "
                        "legacy engine (no hardened routing / proxy)")
    p.add_argument("--no-proxy", action="store_true",
                   help="do not start the 7928 SOCKS5/HTTP proxy gateway")
    p.add_argument("--proxy-host", default="127.0.0.1",
                   help="proxy gateway bind host (default: 127.0.0.1)")
    p.add_argument("--proxy-port", type=int, default=7928,
                   help="proxy gateway bind port (default: 7928)")


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
    _add_engine_args(r)
    r.set_defaults(func=_cmd_run)

    w = sub.add_parser("web", help="serve the web dashboard (current exit + node table)")
    w.add_argument("-c", "--config", default="config.yaml", help=common_config[2]["help"])
    w.add_argument(common_cache[0], **common_cache[1])
    w.add_argument("--provider", choices=["vpngate", "fake"], default="vpngate",
                   help="exit provider (fake = offline in-memory demo)")
    w.add_argument("--url", default=DEFAULT_API_URL, help="VPNGate API URL")
    w.add_argument("--host", default="::", help="bind host (default: :: = all)")
    w.add_argument("--port", type=int, default=8686, help="bind port (default: 8686)")
    w.add_argument("--tick-interval", type=float, default=None,
                   help="seconds between background health/policy ticks "
                        "(default: health.interval from config)")
    w.add_argument("--auth", action="store_true",
                   help="require login (default: on for vpngate, off for fake)")
    w.add_argument("--no-auth", action="store_true", help="disable login")
    w.add_argument("--password", default=None,
                   help="dashboard password (default: reuse legacy config / random)")
    w.add_argument("--secret-path", default=None,
                   help="URL secret path prefix (default: reuse legacy / random)")
    _add_engine_args(w)
    w.set_defaults(func=_cmd_web)

    s = sub.add_parser("status", help="print the dashboard from the last cache")
    s.add_argument(common_cache[0], **common_cache[1])
    s.set_defaults(func=_cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
