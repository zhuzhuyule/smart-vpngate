"""Unit tests for the Node Pool layer."""

from __future__ import annotations

from smart_vpngate.models import Node
from smart_vpngate.nodepool import NodePool


def _n(id, cc, score=0, status="unknown", latency=0):
    return Node(id=id, country_short=cc, vpngate_score=score, status=status, latency_ms=latency)


def test_groups_by_country_and_sorts_by_score():
    pool = NodePool()
    pool.update([
        _n("jp_a", "JP", 100),
        _n("jp_b", "JP", 300),
        _n("kr_a", "KR", 200),
    ])
    assert pool.countries() == ["JP", "KR"]
    assert [n.id for n in pool.get("JP")] == ["jp_b", "jp_a"]  # higher score first
    assert len(pool) == 3


def test_top_n_cap_per_country():
    pool = NodePool(top_n=2)
    pool.update([_n(f"jp_{i}", "JP", score=i * 100) for i in range(5)])
    jp = pool.get("JP")
    assert len(jp) == 2
    assert [n.id for n in jp] == ["jp_4", "jp_3"]


def test_best_skips_down_and_excluded():
    pool = NodePool()
    pool.update([
        _n("jp_a", "JP", 300, status="down"),
        _n("jp_b", "JP", 200, status="healthy"),
        _n("jp_c", "JP", 100, status="healthy"),
    ])
    assert pool.best("JP").id == "jp_b"                 # jp_a is down -> skipped
    assert pool.best("JP", exclude="jp_b").id == "jp_c"


def test_best_none_when_all_down():
    pool = NodePool()
    pool.update([_n("jp_a", "JP", 300, status="down"),
                 _n("jp_b", "JP", 100, status="down")])
    assert pool.best("JP") is None                      # all down -> no viable node
    assert not pool.has_candidates("JP")
    # include_down still ranks by score; jp_a outscores jp_b among the down set.
    assert pool.best("JP", include_down=True).id == "jp_a"


def test_update_preserves_health_metrics():
    pool = NodePool()
    pool.update([_n("jp_a", "JP", 300)])
    pool.mark("jp_a", "healthy")
    pool.find("jp_a").latency_ms = 42
    # Discovery refresh returns a fresh Node object for the same id.
    pool.update([_n("jp_a", "JP", 300), _n("jp_b", "JP", 100)])
    kept = pool.find("jp_a")
    assert kept.status == "healthy"     # preserved across refresh
    assert kept.latency_ms == 42


def test_update_drops_missing_nodes():
    pool = NodePool()
    pool.update([_n("jp_a", "JP"), _n("jp_b", "JP")])
    pool.update([_n("jp_a", "JP")])     # jp_b gone from feed
    assert pool.find("jp_b") is None
    assert len(pool) == 1


def test_resort_reflects_new_scores():
    pool = NodePool()
    pool.update([_n("jp_a", "JP", latency=200, status="healthy"),
                 _n("jp_b", "JP", latency=10, status="healthy")])
    # jp_b has lower latency -> higher composite score after resort
    pool.resort()
    assert pool.get("JP")[0].id == "jp_b"


def test_mark_updates_status():
    pool = NodePool()
    pool.update([_n("jp_a", "JP")])
    assert pool.mark("jp_a", "down")
    assert pool.find("jp_a").status == "down"
    assert not pool.mark("nope", "down")


def test_evict_predicate():
    pool = NodePool()
    pool.update([_n("jp_a", "JP", status="down"), _n("jp_b", "JP", status="healthy")])
    removed = pool.evict(lambda n: n.status == "down")
    assert [n.id for n in removed] == ["jp_a"]
    assert pool.find("jp_a") is None
    assert len(pool) == 1


def test_evict_stale():
    pool = NodePool()
    pool.update([_n("jp_a", "JP"), _n("jp_b", "JP")])
    pool.find("jp_a").last_check = 1000.0
    pool.find("jp_b").last_check = 0.0     # never checked -> treated fresh
    removed = pool.evict_stale(max_age=100, now=2000.0)
    assert [n.id for n in removed] == ["jp_a"]
    assert pool.find("jp_b") is not None
