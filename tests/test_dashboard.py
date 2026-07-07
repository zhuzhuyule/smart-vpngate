"""Unit tests for the Dashboard snapshot assembly."""

from __future__ import annotations

from smart_vpngate.config import PolicyConfig
from smart_vpngate.dashboard import node_row, snapshot
from smart_vpngate.exit_manager import ExitManager
from smart_vpngate.models import Node
from smart_vpngate.nodepool import NodePool
from smart_vpngate.policy import PolicyEngine
from smart_vpngate.providers.fake import FakeProvider


def test_node_row_has_all_design_columns():
    n = Node(id="jp1", country="Japan", country_short="JP", protocol="tcp",
             latency_ms=20, download=30.0, status="healthy")
    row = node_row(n, current_id="jp1")
    for col in ("country", "city", "isp", "asn", "latency_ms", "loss",
                "download", "upload", "score", "status", "current",
                "last_check", "protocol"):
        assert col in row
    assert row["current"] is True
    assert row["score"] == n.score


def test_snapshot_marks_current_and_counts():
    nodes = [Node(id="jp1", country_short="JP", country="Japan", status="healthy"),
             Node(id="kr1", country_short="KR", country="Korea", status="healthy")]
    pool = NodePool()
    pool.update(nodes)
    provider = FakeProvider(nodes)
    em = ExitManager(provider, PolicyEngine(PolicyConfig(country="JP")), pool)
    em.reconcile()

    snap = snapshot(em, pool)
    assert snap["total_nodes"] == 2
    assert set(snap["countries"]) == {"JP", "KR"}
    assert snap["current_exit"]["connected"] is True
    current_rows = [r for r in snap["nodes"] if r["current"]]
    assert len(current_rows) == 1
    assert current_rows[0]["country_short"] == "JP"
