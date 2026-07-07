"""Unit tests for the Health Check layer."""

from __future__ import annotations

from smart_vpngate.health import HealthCheck, HealthResult, classify
from smart_vpngate.models import Node


def test_classify():
    assert classify(HealthResult(ok=True, loss=0.0)) == "healthy"
    assert classify(HealthResult(ok=True, loss=0.6)) == "degraded"
    assert classify(HealthResult(ok=False)) == "down"


def test_check_writes_metrics_on_success():
    node = Node(id="jp_a", country_short="JP")
    hc = HealthCheck(
        probe=lambda n: HealthResult(ok=True, latency_ms=25, loss=0.0, download=42.0),
        clock=lambda: 1000.0,
    )
    result = hc.check(node)
    assert result.ok
    assert node.status == "healthy"
    assert node.latency_ms == 25
    assert node.ping == 25
    assert node.download == 42.0
    assert node.last_check == 1000.0


def test_check_marks_down_on_failure():
    node = Node(id="jp_a", country_short="JP", status="healthy")
    hc = HealthCheck(probe=lambda n: HealthResult(ok=False, message="timeout"))
    hc.check(node)
    assert node.status == "down"
    assert node.loss == 1.0


def test_check_treats_raising_probe_as_down():
    node = Node(id="jp_a", country_short="JP")

    def boom(n):
        raise RuntimeError("network gone")

    hc = HealthCheck(probe=boom)
    result = hc.check(node)
    assert not result.ok
    assert "network gone" in result.message
    assert node.status == "down"


def test_degraded_on_high_loss():
    node = Node(id="jp_a", country_short="JP")
    hc = HealthCheck(probe=lambda n: HealthResult(ok=True, latency_ms=30, loss=0.7))
    hc.check(node)
    assert node.status == "degraded"


def test_check_all_returns_per_node_results():
    nodes = [Node(id="a", country_short="JP"), Node(id="b", country_short="KR")]
    hc = HealthCheck(probe=lambda n: HealthResult(ok=(n.id == "a"), latency_ms=10))
    results = hc.check_all(nodes)
    assert results["a"].ok and not results["b"].ok
    assert nodes[0].status == "healthy"
    assert nodes[1].status == "down"


def test_due_respects_interval():
    hc = HealthCheck(probe=lambda n: HealthResult(ok=True), interval=100)
    node = Node(id="a", country_short="JP")
    assert hc.due(node)                       # never checked
    node.last_check = 1000.0
    assert not hc.due(node, now=1050.0)
    assert hc.due(node, now=1200.0)
