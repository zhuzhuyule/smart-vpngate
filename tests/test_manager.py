"""End-to-end pipeline tests: Discovery -> Pool -> Health -> Policy -> Exit."""

from __future__ import annotations

import base64

from smart_vpngate.config import Config
from smart_vpngate.discovery import parse_rows, row_to_node
from smart_vpngate.health import HealthResult
from smart_vpngate.manager import SmartExitManager
from smart_vpngate.providers.fake import FakeProvider


def _ovpn(ip, port, proto):
    return base64.b64encode(
        f"client\nproto {proto}\nremote {ip} {port}\n".encode()).decode()


HEADER = ("#HostName,IP,Score,Ping,Speed,CountryLong,CountryShort,"
          "NumVpnSessions,OpenVPN_ConfigData_Base64")


def _feed(rows):
    lines = ["*vpn_servers", HEADER]
    for h, ip, sc, pg, cl, cs, pr, po in rows:
        lines.append(",".join([h, ip, str(sc), str(pg), "1000000", cl, cs, "5",
                               _ovpn(ip, po, pr)]))
    lines.append("*")
    return "\n".join(lines)


FEED = _feed([
    ("jp1", "203.0.113.11", 9_000_000, 18, "Japan", "JP", "tcp", 443),
    ("jp2", "203.0.113.12", 8_000_000, 25, "Japan", "JP", "tcp", 443),
    ("kr1", "203.0.113.21", 7_000_000, 30, "Korea Republic of", "KR", "tcp", 443),
    ("cn1", "203.0.113.99", 9_900_000, 5, "China", "CN", "tcp", 443),   # blacklisted
])


def _nodes_from_feed(feed, provider="fake"):
    return [n for n in (row_to_node(r, provider) for r in parse_rows(feed))
            if n is not None]


def _build(config, feed=FEED, probe=None, fail_ids=None):
    provider = FakeProvider(_nodes_from_feed(feed), fail_ids=fail_ids)
    probe = probe or (lambda n: HealthResult(ok=True, latency_ms=n.ping, loss=0.0))
    return SmartExitManager.build(
        config, provider=provider, fetcher=lambda: feed, probe=probe,
        cache_path="/tmp/does-not-matter-overridden",
        sleeper=lambda s: None,
    )


def _config(tmp_path, **policy):
    p = Config.load(None)
    p.policy.mode = policy.get("mode", "locked-country")
    p.policy.country = policy.get("country", "JP")
    p.policy = p.policy.normalized()
    return p


def test_bootstrap_connects_locked_country(tmp_path):
    app = _build(_config(tmp_path, country="JP"))
    app.discovery.cache_path = tmp_path / "n.json"
    app.bootstrap()
    assert app.exit.current is not None
    assert app.exit.current.country_short == "JP"      # locked JP
    # CN was blacklisted by default discovery filters.
    assert "CN" not in app.pool.countries()


def test_end_to_end_failover_on_active_probe_failure(tmp_path):
    # Probe fails only for jp1 -> manager must fail over to jp2 within a tick.
    def probe(n):
        return HealthResult(ok=(n.id != "JP_203.0.113.11_443_tcp"),
                            latency_ms=n.ping)

    app = _build(_config(tmp_path, country="JP"), probe=probe)
    app.discovery.cache_path = tmp_path / "n.json"
    app.bootstrap()
    first = app.exit.current.id
    app.tick()
    assert app.exit.current is not None
    assert app.exit.current.id != first                # switched away from failed node
    assert app.exit.current.country_short == "JP"      # still within locked country


def test_failover_falls_back_to_fastest_when_country_exhausted(tmp_path):
    # Locked JP with a single JP node; when it fails and no other JP exists,
    # the manager must fall back to the fastest node anywhere (KR here).
    feed = _feed([
        ("jp1", "203.0.113.11", 9_000_000, 18, "Japan", "JP", "tcp", 443),
        ("kr1", "203.0.113.21", 7_000_000, 30, "Korea Republic of", "KR", "tcp", 443),
    ])
    jp_id = "JP_203.0.113.11_443_tcp"

    def probe(n):
        return HealthResult(ok=(n.id != jp_id), latency_ms=n.ping)

    app = _build(_config(tmp_path, country="JP"), feed=feed, probe=probe)
    app.discovery.cache_path = tmp_path / "n.json"
    app.bootstrap()
    assert app.exit.current.id == jp_id           # starts on JP
    app.tick()                                     # JP probe fails -> failover
    assert app.exit.current is not None
    assert app.exit.current.country_short == "KR"  # fastest-anywhere fallback


def test_run_once_produces_dashboard(tmp_path):
    app = _build(_config(tmp_path, country="JP"))
    app.discovery.cache_path = tmp_path / "n.json"
    app.run(once=True)
    snap = app.dashboard()
    assert snap["current_exit"]["connected"] is True
    assert snap["current_exit"]["country_short"] == "JP"
    assert any(row["current"] for row in snap["nodes"])
    assert snap["total_nodes"] >= 2


def test_run_max_ticks_terminates(tmp_path):
    app = _build(_config(tmp_path, country="JP"))
    app.discovery.cache_path = tmp_path / "n.json"
    app.run(max_ticks=3)                                # must not loop forever
    assert app.exit.current is not None


def test_priority_mode_end_to_end(tmp_path):
    cfg = Config.load(None)
    cfg.policy.mode = "priority"
    cfg.policy.priority = ["JP", "KR"]
    cfg.policy = cfg.policy.normalized()
    app = _build(cfg)
    app.discovery.cache_path = tmp_path / "n.json"
    app.bootstrap()
    assert app.exit.current.country_short == "JP"       # highest priority available
