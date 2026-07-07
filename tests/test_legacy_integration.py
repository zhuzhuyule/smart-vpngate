"""Unit tests for the brain->old-engine bridge (fake engine, no root/OpenVPN)."""

from __future__ import annotations

from pathlib import Path

from smart_vpngate.gateway import start_proxy_gateway
from smart_vpngate.models import Node
from smart_vpngate.providers.legacy import LegacyEngineConnector
from smart_vpngate.providers.vpngate import VPNGateProvider


class _FakeProc:
    def __init__(self, alive=True):
        self._alive = alive

    def poll(self):
        return None if self._alive else 1


class _FakeEngine:
    """Stand-in for vpngate_manager exposing only the mechanical functions."""

    def __init__(self, tmp: Path, ok=True):
        self.CONFIG_DIR = tmp / "configs"
        self._ok = ok
        self.calls = []
        self.proc = _FakeProc(alive=ok)

    def ensure_dirs(self):
        self.calls.append("ensure_dirs")
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def run_openvpn_until_ready(self, config_file, keep_alive, route_nopull, dev="tun0"):
        self.calls.append(("run", config_file, keep_alive, route_nopull, dev))
        if self._ok:
            return True, "connected", self.proc
        return False, "ovpn failed", None

    def setup_policy_routing(self, dev):
        self.calls.append(("routing", dev))

    def cleanup_policy_routing(self):
        self.calls.append("cleanup_routing")

    def stop_process(self, proc):
        self.calls.append("stop_process")
        proc._alive = False


def test_connector_start_success_sets_routing(tmp_path):
    eng = _FakeEngine(tmp_path, ok=True)
    conn = LegacyEngineConnector(engine=eng)
    handle = conn.start("client\nremote 1.1.1.1 443\n", "JP_1")
    assert conn.is_ready(handle)
    assert "ensure_dirs" in eng.calls
    assert ("routing", "tun0") in eng.calls
    # config written under the engine's CONFIG_DIR
    assert (tmp_path / "configs" / "JP_1.ovpn").exists()
    assert any(c[0] == "run" and c[3] is True for c in eng.calls if isinstance(c, tuple))


def test_connector_start_failure_not_ready_no_routing(tmp_path):
    eng = _FakeEngine(tmp_path, ok=False)
    conn = LegacyEngineConnector(engine=eng)
    handle = conn.start("cfg", "JP_1")
    assert not conn.is_ready(handle)
    assert not any(isinstance(c, tuple) and c[0] == "routing" for c in eng.calls)


def test_connector_stop_cleans_up(tmp_path):
    eng = _FakeEngine(tmp_path, ok=True)
    conn = LegacyEngineConnector(engine=eng)
    handle = conn.start("cfg", "JP_1")
    conn.stop(handle)
    assert "stop_process" in eng.calls
    assert "cleanup_routing" in eng.calls
    assert not (tmp_path / "configs" / "JP_1.ovpn").exists()   # config removed


def test_vpngate_provider_over_legacy_connector(tmp_path):
    # The real provider driving the (fake) legacy engine end to end.
    eng = _FakeEngine(tmp_path, ok=True)
    provider = VPNGateProvider(connector=LegacyEngineConnector(engine=eng),
                               ip_lookup=lambda: "198.51.100.9")
    node = Node(id="JP_1", country_short="JP",
                config_text="client\nproto tcp\nremote 1.1.1.1 443\n")
    st = provider.connect(node)
    assert st.connected
    assert st.public_ip == "198.51.100.9"
    assert provider.status().node_id == "JP_1"
    provider.disconnect()
    assert not provider.status().connected


def test_gateway_starts_thread_with_injected_server():
    started = {}

    def fake_server(host, port):
        started["host"] = host
        started["port"] = port

    t = start_proxy_gateway("127.0.0.1", 7928, server=fake_server)
    t.join(timeout=2)
    assert started == {"host": "127.0.0.1", "port": 7928}
