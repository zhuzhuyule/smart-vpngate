"""Integration tests for the web dashboard (real HTTP on an ephemeral port)."""

from __future__ import annotations

import json
import urllib.request

import pytest

from smart_vpngate.config import Config
from smart_vpngate.health import HealthResult
from smart_vpngate.manager import SmartExitManager
from smart_vpngate.providers.fake import FakeProvider
from smart_vpngate.web import DashboardServer
from tests.test_manager import FEED, _nodes_from_feed


def _app():
    cfg = Config.load(None)  # locked-country JP by default
    provider = FakeProvider(_nodes_from_feed(FEED))
    return SmartExitManager.build(
        cfg, provider=provider, fetcher=lambda: FEED,
        probe=lambda n: HealthResult(ok=True, latency_ms=n.ping, loss=0.0),
        cache_path="/tmp/smart_web_test.json", sleeper=lambda s: None,
    )


@pytest.fixture()
def server():
    # Loopback + port 0 -> OS picks a free port; long tick so it won't churn.
    srv = DashboardServer(_app(), host="127.0.0.1", port=0, tick_interval=3600)
    srv.start(serve=False)          # bootstrap + bind, but don't block
    import threading
    t = threading.Thread(target=srv._httpd.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.stop()


def _get(srv, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}{path}", timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def _post(srv, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{srv.port}{path}",
        data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def test_index_serves_html(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=5) as r:
        body = r.read().decode()
    assert r.status == 200
    assert "Smart VPNGate" in body
    assert "api/status" in body            # the page wires up to the API


def test_api_status_returns_snapshot(server):
    code, snap = _get(server, "/api/status")
    assert code == 200
    assert snap["current_exit"]["connected"] is True
    assert snap["current_exit"]["country_short"] == "JP"    # locked JP
    assert snap["total_nodes"] >= 2
    assert any(row["current"] for row in snap["nodes"])


def test_api_switch_changes_exit(server):
    _, snap = _get(server, "/api/status")
    other = next(n["id"] for n in snap["nodes"] if not n["current"])
    code, after = _post(server, "/api/switch", {"node_id": other})
    assert code == 200
    assert after["current_exit"]["node_id"] == other
    current_rows = [r for r in after["nodes"] if r["current"]]
    assert len(current_rows) == 1 and current_rows[0]["id"] == other


def test_api_switch_requires_node_id(server):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.port}/api/switch",
        data=b"{}", method="POST", headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=5)
        assert False, "expected HTTP 400"
    except urllib.error.HTTPError as e:
        assert e.code == 400


def test_unknown_path_404(server):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{server.port}/nope", timeout=5)
        assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404


# --- authenticated server -------------------------------------------------
@pytest.fixture()
def authed_server():
    from smart_vpngate.auth import Auth
    srv = DashboardServer(_app(), host="127.0.0.1", port=0, tick_interval=3600,
                          auth=Auth(password="secret", secret_path="zzz"))
    srv.start(serve=False)
    import threading
    threading.Thread(target=srv._httpd.serve_forever, daemon=True).start()
    yield srv
    srv.stop()


def _base(srv):
    return f"http://127.0.0.1:{srv.port}"


def test_auth_status_requires_login(authed_server):
    try:
        urllib.request.urlopen(f"{_base(authed_server)}/zzz/api/status", timeout=5)
        assert False, "expected 401"
    except urllib.error.HTTPError as e:
        assert e.code == 401


def test_auth_root_off_prefix_is_404(authed_server):
    try:
        urllib.request.urlopen(f"{_base(authed_server)}/api/status", timeout=5)
        assert False, "expected 404 (off secret prefix)"
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_auth_login_flow(authed_server):
    b = _base(authed_server)
    # Wrong password -> 401, login page.
    req = urllib.request.Request(f"{b}/zzz/login",
                                 data=b"password=wrong", method="POST")
    try:
        urllib.request.urlopen(req, timeout=5)
        assert False, "expected 401"
    except urllib.error.HTTPError as e:
        assert e.code == 401

    # Correct password -> 303 + Set-Cookie; then status works with that cookie.
    opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
    req = urllib.request.Request(f"{b}/zzz/login",
                                 data=b"password=secret", method="POST")

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    op = urllib.request.build_opener(_NoRedirect())
    try:
        op.open(req, timeout=5)
        cookie = None
    except urllib.error.HTTPError as e:
        assert e.code == 303
        cookie = e.headers.get("Set-Cookie")
    assert cookie and cookie.startswith("session=")

    token = cookie.split(";", 1)[0]
    sreq = urllib.request.Request(f"{b}/zzz/api/status", headers={"Cookie": token})
    with urllib.request.urlopen(sreq, timeout=5) as r:
        assert r.status == 200
        snap = json.loads(r.read().decode())
    assert snap["current_exit"]["country_short"] == "JP"
