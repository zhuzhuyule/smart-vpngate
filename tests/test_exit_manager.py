"""Unit tests for the Exit Manager coordinator (with FakeProvider)."""

from __future__ import annotations

from smart_vpngate.config import PolicyConfig
from smart_vpngate.exit_manager import ExitManager
from smart_vpngate.models import Node
from smart_vpngate.nodepool import NodePool
from smart_vpngate.policy import CONNECT, KEEP, SWITCH, PolicyEngine
from smart_vpngate.providers.fake import FakeProvider


def _n(id, cc, latency=20, status="healthy"):
    return Node(id=id, country_short=cc, country=cc, latency_ms=latency, status=status)


def _setup(nodes, fail_ids=None, mode="locked-country", country="JP", **pol):
    pool = NodePool()
    pool.update(nodes)
    provider = FakeProvider(nodes, fail_ids=fail_ids)
    policy = PolicyEngine(PolicyConfig(mode=mode, country=country, **pol))
    clock = iter(range(1, 10_000))
    em = ExitManager(provider, policy, pool, clock=lambda: next(clock))
    return em, provider, pool


def test_initial_connect_single_exit():
    em, provider, _ = _setup([_n("jp1", "JP"), _n("jp2", "JP")])
    d = em.reconcile()
    assert d.action == CONNECT
    assert em.current.id == "jp1"
    assert em.status.connected
    assert provider.status().node_id == "jp1"


def test_reconcile_is_idempotent_keep():
    em, provider, _ = _setup([_n("jp1", "JP"), _n("jp2", "JP")])
    em.reconcile()
    provider.connect_calls.clear()
    d = em.reconcile()
    assert d.action == KEEP
    assert provider.connect_calls == []      # no reconnect churn


def test_failover_on_active_node_failure():
    em, provider, pool = _setup([_n("jp1", "JP"), _n("jp2", "JP")])
    em.reconcile()
    assert em.current.id == "jp1"
    d = em.on_health("jp1", healthy=False)    # active node dies
    assert d is not None and d.action == SWITCH
    assert em.current.id == "jp2"
    assert pool.find("jp1").status == "down"


def test_health_failure_of_inactive_node_is_noop():
    em, _, _ = _setup([_n("jp1", "JP"), _n("jp2", "JP")])
    em.reconcile()
    assert em.on_health("jp2", healthy=False) is None
    assert em.current.id == "jp1"


def test_connect_failure_marks_node_down_and_retries():
    # jp1 is the best but un-connectable; manager should end up on jp2.
    em, provider, pool = _setup([_n("jp1", "JP", latency=1), _n("jp2", "JP", latency=50)],
                                fail_ids={"jp1"})
    em.reconcile()                            # tries jp1 -> fails -> marks down
    assert pool.find("jp1").status == "down"
    d = em.reconcile()                        # now picks jp2
    assert em.current.id == "jp2"
    assert d.action in (CONNECT, SWITCH)


def test_manual_switch():
    em, _, _ = _setup([_n("jp1", "JP"), _n("jp2", "JP")])
    em.reconcile()
    d = em.switch("jp2")
    assert d.action == SWITCH
    assert em.current.id == "jp2"


def test_manual_switch_unknown_node():
    em, _, _ = _setup([_n("jp1", "JP")])
    em.reconcile()
    d = em.switch("nope")
    assert d.action == "none"
    assert em.current.id == "jp1"             # unchanged


def test_recover_reconnects_when_down():
    em, _, pool = _setup([_n("jp1", "JP"), _n("jp2", "JP")])
    em.reconcile()
    em.current.status = "down"
    pool.mark("jp1", "down")
    d = em.recover()
    assert d is not None
    assert em.current.id == "jp2"


def test_snapshot_reports_current_exit():
    em, _, _ = _setup([_n("jp1", "JP")])
    em.reconcile()
    snap = em.snapshot()
    assert snap["connected"] is True
    assert snap["node_id"] == "jp1"
    assert snap["country_short"] == "JP"
    assert snap["public_ip"]
    assert snap["provider"] == "fake"


def test_disconnect_clears_exit():
    em, provider, _ = _setup([_n("jp1", "JP")])
    em.reconcile()
    em.disconnect()
    assert em.current is None
    assert not em.status.connected
    assert not provider.status().connected
