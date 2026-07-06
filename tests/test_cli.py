"""Unit tests for the CLI wiring (offline, via --from-file)."""

from __future__ import annotations

import base64
import json

from smart_vpngate.cli import main


def _ovpn(ip, port, proto):
    return base64.b64encode(
        f"client\nproto {proto}\nremote {ip} {port}\n".encode()
    ).decode()


HEADER = (
    "#HostName,IP,Score,Ping,Speed,CountryLong,CountryShort,"
    "NumVpnSessions,OpenVPN_ConfigData_Base64"
)
FEED = "\n".join(
    [
        "*vpn_servers",
        HEADER,
        f"jp1,1.1.1.1,900000,20,1000000,Japan,JP,10,{_ovpn('1.1.1.1', 443, 'tcp')}",
        f"cn1,3.3.3.3,950000,10,1000000,China,CN,10,{_ovpn('3.3.3.3', 443, 'tcp')}",
        "*",
    ]
)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_discover_from_file_caches_and_filters(tmp_path, capsys):
    feed = _write(tmp_path, "feed.csv", FEED)
    cache = tmp_path / "nodes.json"
    rc = main(["discover", "--config", str(tmp_path / "missing.yaml"),
               "--from-file", str(feed), "--cache", str(cache)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "JP" in out and "CN" not in out           # CN blacklisted by default
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["count"] == 1
    assert payload["nodes"][0]["country_short"] == "JP"


def test_discover_json_output(tmp_path, capsys):
    feed = _write(tmp_path, "feed.csv", FEED)
    rc = main(["discover", "--from-file", str(feed),
               "--cache", str(tmp_path / "n.json"), "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert isinstance(data, list) and len(data) == 1
    assert data[0]["provider"] == "vpngate"
    assert "score" in data[0]
