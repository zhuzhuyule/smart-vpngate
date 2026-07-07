"""Unit tests for providers (Fake + VPNGate with a fake connector)."""

from __future__ import annotations

import base64

from smart_vpngate.models import Node
from smart_vpngate.providers.fake import FakeProvider
from smart_vpngate.providers.vpngate import VPNGateProvider


# --- FakeProvider ---------------------------------------------------------
def test_fake_connect_disconnect_cycle():
    n1, n2 = Node(id="jp1", country_short="JP"), Node(id="jp2", country_short="JP")
    p = FakeProvider([n1, n2])
    st = p.connect(n1)
    assert st.connected and st.node_id == "jp1"
    assert p.public_ip()
    # Connecting a second node drops the first (single active exit).
    p.connect(n2)
    assert p.status().node_id == "jp2"
    assert p.disconnect_calls == 1
    p.disconnect()
    assert not p.status().connected
    assert p.public_ip() is None


def test_fake_simulated_failure():
    n = Node(id="bad", country_short="JP")
    p = FakeProvider([n], fail_ids={"bad"})
    st = p.connect(n)
    assert not st.connected
    assert not p.status().connected


# --- VPNGateProvider (with fakes) -----------------------------------------
class _FakeConnector:
    def __init__(self, ready=True):
        self.ready = ready
        self.started, self.stopped = [], 0

    def start(self, config_text, node_id):
        self.started.append(node_id)
        return {"node": node_id}

    def is_ready(self, handle):
        return bool(self.ready)

    def stop(self, handle):
        self.stopped += 1


def _node(id="jp1"):
    cfg = "client\nproto tcp\nremote 1.1.1.1 443\n"
    return Node(id=id, country_short="JP", config_text=cfg)


def test_vpngate_connect_success():
    conn = _FakeConnector(ready=True)
    p = VPNGateProvider(connector=conn, ip_lookup=lambda: "198.51.100.7")
    st = p.connect(_node())
    assert st.connected
    assert st.public_ip == "198.51.100.7"
    assert p.public_ip() == "198.51.100.7"
    assert conn.started == ["jp1"]


def test_vpngate_connect_failure_when_not_ready():
    conn = _FakeConnector(ready=False)
    p = VPNGateProvider(connector=conn, ip_lookup=lambda: "x")
    st = p.connect(_node())
    assert not st.connected
    assert conn.stopped == 1              # cleaned up the failed attempt
    assert p.public_ip() is None


def test_vpngate_connect_rejects_empty_config():
    p = VPNGateProvider(connector=_FakeConnector(), ip_lookup=lambda: "x")
    st = p.connect(Node(id="jp1", country_short="JP", config_text=""))
    assert not st.connected
    assert "config" in st.message


def test_vpngate_single_active_exit():
    conn = _FakeConnector(ready=True)
    p = VPNGateProvider(connector=conn, ip_lookup=lambda: "1.2.3.4")
    p.connect(_node("jp1"))
    p.connect(_node("jp2"))
    assert conn.stopped == 1              # previous tunnel torn down first
    assert p.status().node_id == "jp2"


def test_vpngate_status_detects_drop():
    conn = _FakeConnector(ready=True)
    p = VPNGateProvider(connector=conn, ip_lookup=lambda: "1.2.3.4")
    p.connect(_node())
    conn.ready = False                    # tunnel dies underneath us
    assert not p.status().connected


def test_ip_lookup_routes_through_proxy():
    from smart_vpngate.providers.vpngate import _default_ip_lookup
    import urllib.request

    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"203.0.113.55\n"

    class _Opener:
        def open(self, url, timeout=0): return _Resp()

    def factory(*handlers):
        captured["handlers"] = handlers
        return _Opener()

    ip = _default_ip_lookup("http://127.0.0.1:7928", opener_factory=factory)
    assert ip == "203.0.113.55"
    # A ProxyHandler must have been installed (so the query goes via the tunnel).
    assert any(isinstance(h, urllib.request.ProxyHandler) for h in captured["handlers"])


def test_ip_lookup_direct_when_no_proxy():
    from smart_vpngate.providers.vpngate import _default_ip_lookup

    captured = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b"198.51.100.1"

    def factory(*handlers):
        captured["handlers"] = handlers
        return type("O", (), {"open": lambda self, url, timeout=0: _Resp()})()

    ip = _default_ip_lookup(None, opener_factory=factory)
    assert ip == "198.51.100.1"
    assert captured["handlers"] == ()          # no proxy handler when direct


def test_vpngate_discover_parses_feed():
    cfg = base64.b64encode(b"proto tcp\nremote 1.1.1.1 443\n").decode()
    header = ("#HostName,IP,Score,Ping,Speed,CountryLong,CountryShort,"
              "NumVpnSessions,OpenVPN_ConfigData_Base64")
    feed = "\n".join(["*x", header, f"jp1,1.1.1.1,900000,20,1000,Japan,JP,10,{cfg}", "*"])
    p = VPNGateProvider(connector=_FakeConnector(), fetcher=lambda: feed)
    nodes = p.discover()
    assert len(nodes) == 1
    assert nodes[0].country_short == "JP"
    assert nodes[0].provider == "vpngate"
