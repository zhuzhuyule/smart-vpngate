"""Tests for the legacy status mirroring used by the sv/ml menu."""

from __future__ import annotations

import json

from smart_vpngate.compat import write_legacy_status
from smart_vpngate.config import Config
from smart_vpngate.health import HealthResult
from smart_vpngate.manager import SmartExitManager
from smart_vpngate.providers.fake import FakeProvider
from tests.test_manager import FEED, _nodes_from_feed


def _app(tmp_path):
    cfg = Config.load(None)   # locked JP
    provider = FakeProvider(_nodes_from_feed(FEED))
    app = SmartExitManager.build(
        cfg, provider=provider, fetcher=lambda: FEED,
        probe=lambda n: HealthResult(ok=True, latency_ms=n.ping, loss=0.0),
        cache_path=tmp_path / "cache.json", sleeper=lambda s: None,
    )
    app.discovery.cache_path = tmp_path / "cache.json"
    app.bootstrap()
    return app


def test_writes_state_nodes_public_ip(tmp_path):
    app = _app(tmp_path)
    write_legacy_status(app, proxy_port=7928, data_dir=tmp_path)

    state = json.loads((tmp_path / "state.json").read_text())
    assert state["active_openvpn_node_id"] == app.exit.current.id
    assert state["proxy_ok"] is True
    assert state["local_proxy"] == "http://127.0.0.1:7928"
    assert state["proxy_ip"]                       # exit IP mirrored

    nodes = json.loads((tmp_path / "nodes.json").read_text())
    active = [n for n in nodes if n["active"]]
    assert len(active) == 1 and active[0]["id"] == app.exit.current.id
    assert active[0]["country"]

    assert (tmp_path / "public_ip.txt").read_text().strip() == state["proxy_ip"]


def test_disconnected_state(tmp_path):
    app = _app(tmp_path)
    app.exit.disconnect()
    write_legacy_status(app, proxy_port=7928, data_dir=tmp_path)
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["active_openvpn_node_id"] == ""
    assert state["proxy_ok"] is False


def test_never_raises_on_bad_input():
    # Must swallow errors so the supervise loop is never broken.
    write_legacy_status(object(), proxy_port=7928, data_dir="/nonexistent/xyz")
