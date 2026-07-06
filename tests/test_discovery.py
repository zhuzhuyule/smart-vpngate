"""Unit tests for the Discovery layer (offline, no network)."""

from __future__ import annotations

import base64

from smart_vpngate.config import DiscoveryConfig
from smart_vpngate.discovery import Discovery, parse_rows, row_to_node


def _ovpn(remote_host: str, port: int, proto: str) -> str:
    cfg = f"client\ndev tun\nproto {proto}\nremote {remote_host} {port}\n"
    return base64.b64encode(cfg.encode()).decode()


HEADER = (
    "#HostName,IP,Score,Ping,Speed,CountryLong,CountryShort,"
    "NumVpnSessions,OpenVPN_ConfigData_Base64"
)


def _feed(rows: list[str]) -> str:
    # VPNGate feeds start with a "*vpn_servers" marker line and end with "*".
    return "\n".join(["*vpn_servers", HEADER, *rows, "*"])


def _row(host, ip, score, ping, country_long, country_short, proto="tcp", port=443):
    return ",".join(
        [
            host,
            ip,
            str(score),
            str(ping),
            "1000000",  # Speed
            country_long,
            country_short,
            "10",       # NumVpnSessions
            _ovpn(ip, port, proto),
        ]
    )


SAMPLE = _feed(
    [
        _row("jp1", "1.1.1.1", 900000, 20, "Japan", "JP", "tcp", 443),
        _row("jp2", "1.1.1.2", 800000, 30, "Japan", "JP", "udp", 1194),
        _row("kr1", "2.2.2.2", 700000, 40, "Korea Republic of", "KR", "tcp", 443),
        _row("cn1", "3.3.3.3", 950000, 10, "China", "CN", "tcp", 443),  # blacklisted
        _row("de1", "4.4.4.4", 600000, 50, "Germany", "DE", "tcp", 443),  # not allowlisted
    ]
)


def test_parse_rows_strips_markers_and_header_hash():
    rows = parse_rows(SAMPLE)
    assert len(rows) == 5
    assert rows[0]["HostName"] == "jp1"
    assert rows[0]["CountryShort"] == "JP"


def test_row_to_node_extracts_remote_and_proto():
    rows = parse_rows(SAMPLE)
    node = row_to_node(rows[1])  # jp2, udp/1194
    assert node is not None
    assert node.country_short == "JP"
    assert node.protocol == "udp"
    assert node.remote_port == 1194
    assert node.provider == "vpngate"


def test_row_to_node_rejects_missing_config():
    assert row_to_node({"IP": "5.5.5.5", "CountryShort": "JP"}) is None
    assert row_to_node({"OpenVPN_ConfigData_Base64": "x", "CountryShort": "JP"}) is None


def _discovery(tmp_path, **overrides):
    cfg = DiscoveryConfig(**overrides)
    return Discovery(cfg, fetcher=lambda: SAMPLE, cache_path=tmp_path / "nodes.json")


def test_allowlist_and_blacklist(tmp_path):
    d = _discovery(tmp_path, countries=["JP", "KR", "US"], blacklist=["CN", "RU"])
    nodes = d.refresh()
    codes = sorted({n.country_short for n in nodes})
    assert codes == ["JP", "KR"]  # CN blacklisted, DE not allowlisted


def test_protocol_filter(tmp_path):
    d = _discovery(tmp_path, countries=["JP"], protocols=["udp"])
    nodes = d.refresh()
    assert [n.host_name for n in nodes] == ["jp2"]


def test_min_score_filter(tmp_path):
    d = _discovery(tmp_path, countries=["JP", "KR"], min_score=850000)
    nodes = d.refresh()
    assert [n.host_name for n in nodes] == ["jp1"]


def test_max_ping_filter(tmp_path):
    d = _discovery(tmp_path, countries=["JP", "KR"], max_ping=25)
    nodes = d.refresh()
    assert [n.host_name for n in nodes] == ["jp1"]


def test_per_country_cap_and_ordering(tmp_path):
    d = _discovery(tmp_path, countries=["JP"], max_nodes_per_country=1)
    nodes = d.refresh()
    assert len(nodes) == 1
    assert nodes[0].host_name == "jp1"  # highest VPNGate score wins


def test_empty_allowlist_allows_all_except_blacklist(tmp_path):
    d = _discovery(tmp_path, countries=[], blacklist=["CN"])
    codes = sorted({n.country_short for n in d.refresh()})
    assert codes == ["DE", "JP", "KR"]


def test_cache_roundtrip(tmp_path):
    d = _discovery(tmp_path, countries=["JP", "KR"])
    refreshed = d.refresh()
    cached = d.cached()
    assert [n.id for n in cached] == [n.id for n in refreshed]
    assert cached and cached[0].config_text  # config text survives the cache


def test_cached_empty_when_no_file(tmp_path):
    d = _discovery(tmp_path)
    assert d.cached() == []


def test_due_respects_interval(tmp_path):
    d = _discovery(tmp_path, refresh_interval=100)
    d.refresh()
    assert not d.due(now=d.last_refresh + 50)
    assert d.due(now=d.last_refresh + 150)
