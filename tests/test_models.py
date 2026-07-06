"""Unit tests for the Node model and its composite score."""

from __future__ import annotations

from smart_vpngate.models import Node


def test_matches_country_by_code_and_name():
    n = Node(id="x", country="Japan", country_short="JP")
    assert n.matches_country("JP")
    assert n.matches_country("jp")
    assert n.matches_country("japan")
    assert not n.matches_country("KR")
    assert not n.matches_country("")


def test_score_prefers_lower_latency():
    fast = Node(id="a", latency_ms=10, status="healthy")
    slow = Node(id="b", latency_ms=300, status="healthy")
    assert fast.score > slow.score


def test_score_penalizes_loss():
    clean = Node(id="a", latency_ms=20, loss=0.0, status="healthy")
    lossy = Node(id="b", latency_ms=20, loss=0.5, status="healthy")
    assert clean.score > lossy.score


def test_down_node_is_heavily_penalized():
    up = Node(id="a", latency_ms=20, status="healthy")
    down = Node(id="b", latency_ms=20, status="down")
    assert down.score < 0 < up.score


def test_score_rewards_throughput():
    slow = Node(id="a", download=1.0, status="healthy")
    fast = Node(id="b", download=80.0, status="healthy")
    assert fast.score > slow.score


def test_dict_roundtrip_preserves_fields_and_score():
    n = Node(
        id="jp_1",
        country_short="JP",
        protocol="tcp",
        remote_port=443,
        latency_ms=25,
        status="healthy",
    )
    data = n.to_dict()
    assert data["score"] == n.score
    restored = Node.from_dict(data)
    assert restored.id == n.id
    assert restored.remote_port == 443
    assert restored.score == n.score


def test_from_dict_ignores_unknown_keys():
    restored = Node.from_dict({"id": "x", "unexpected": 1})
    assert restored.id == "x"
