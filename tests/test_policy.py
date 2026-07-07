"""Unit tests for the Policy Engine."""

from __future__ import annotations

from smart_vpngate.config import PolicyConfig
from smart_vpngate.models import Node
from smart_vpngate.nodepool import NodePool
from smart_vpngate.policy import CONNECT, KEEP, NONE, SWITCH, PolicyEngine


def _n(id, cc, latency=20, status="healthy"):
    return Node(id=id, country_short=cc, latency_ms=latency, status=status)


def _pool(*nodes):
    p = NodePool()
    p.update(list(nodes))
    return p


def _engine(**kw):
    return PolicyEngine(PolicyConfig(**kw))


# --- initial connect ------------------------------------------------------
def test_locked_country_initial_connect():
    pool = _pool(_n("jp1", "JP"), _n("kr1", "KR", latency=5))
    d = _engine(mode="locked-country", country="JP").select(pool, current=None)
    assert d.action == CONNECT
    assert d.node.country_short == "JP"     # locked JP even though KR is faster


def test_locked_country_empty_falls_back_to_fastest():
    # Requirement 3: locked JP has nothing -> fall back to the fastest anywhere.
    pool = _pool(_n("kr1", "KR"))
    d = _engine(mode="locked-country", country="JP").select(pool, current=None)
    assert d.action == CONNECT
    assert d.node.country_short == "KR"
    assert "fastest-anywhere" in d.reason


def test_none_when_locked_empty_and_fallback_disabled():
    pool = _pool(_n("kr1", "KR"))
    d = _engine(mode="locked-country", country="JP",
                fallback_fastest=False).select(pool, current=None)
    assert d.action == NONE


# --- stickiness / failover ------------------------------------------------
def test_stickiness_keeps_current_even_if_peer_faster():
    pool = _pool(_n("jp1", "JP", latency=50), _n("jp2", "JP", latency=1))
    cur = pool.find("jp1")
    d = _engine(mode="locked-country", country="JP").select(pool, current=cur)
    assert d.action == KEEP
    assert d.node.id == "jp1"               # do not churn for a faster peer


def test_failover_when_current_down():
    pool = _pool(_n("jp1", "JP", status="down"), _n("jp2", "JP"))
    cur = pool.find("jp1")
    d = _engine(mode="locked-country", country="JP").select(pool, current=cur)
    assert d.action == SWITCH
    assert d.node.id == "jp2"


def test_no_stickiness_rides_best():
    pool = _pool(_n("jp1", "JP", latency=50), _n("jp2", "JP", latency=1))
    cur = pool.find("jp1")
    d = _engine(mode="locked-country", country="JP", stickiness=False).select(pool, cur)
    assert d.action == SWITCH
    assert d.node.id == "jp2"


def test_keep_off_policy_current_when_nothing_allowed():
    # Locked to US, but only a healthy JP exit exists (and it is the current
    # one) — keep it rather than "switching" to the node we're already on.
    pool = _pool(_n("jp1", "JP"))
    cur = pool.find("jp1")
    d = _engine(mode="locked-country", country="US").select(pool, current=cur)
    assert d.action == KEEP
    assert d.node.id == "jp1"


def test_same_country_first_then_fastest_fallback_on_failover():
    # Requirement 3: current JP node dies. Another JP node exists -> pick it
    # (same country first), not the faster KR node.
    pool = _pool(_n("jp1", "JP", status="down"), _n("jp2", "JP", latency=80),
                 _n("kr1", "KR", latency=1))
    cur = pool.find("jp1")
    d = _engine(mode="locked-country", country="JP").select(pool, current=cur)
    assert d.action == SWITCH
    assert d.node.id == "jp2"                     # same country wins over faster KR


def test_fastest_fallback_when_whole_country_down():
    # Current JP dies and JP has no other node -> fall back to fastest (KR).
    pool = _pool(_n("jp1", "JP", status="down"), _n("kr1", "KR", latency=1),
                 _n("us1", "US", latency=200))
    cur = pool.find("jp1")
    d = _engine(mode="locked-country", country="JP").select(pool, current=cur)
    assert d.action == SWITCH
    assert d.node.country_short == "KR"           # fastest healthy anywhere
    assert "fastest-anywhere" in d.reason


def test_off_policy_switch_still_prefers_allowed_country():
    # Healthy current JP but locked KR, and KR is available -> switch to KR
    # (allowed country takes precedence over the off-policy healthy exit).
    pool = _pool(_n("jp1", "JP"), _n("kr1", "KR"))
    cur = pool.find("jp1")
    d = _engine(mode="locked-country", country="KR").select(pool, current=cur)
    assert d.action == SWITCH
    assert d.node.country_short == "KR"


def test_switch_when_current_off_policy_and_target_available():
    # Locked to KR; current is JP (off-policy) and KR is available -> switch.
    pool = _pool(_n("jp1", "JP"), _n("kr1", "KR"))
    cur = pool.find("jp1")
    d = _engine(mode="locked-country", country="KR").select(pool, current=cur)
    assert d.action == SWITCH
    assert d.node.country_short == "KR"


# --- country priority -----------------------------------------------------
def test_priority_picks_highest_available():
    pool = _pool(_n("kr1", "KR"), _n("sg1", "SG"))    # JP absent
    d = _engine(mode="priority", priority=["JP", "KR", "SG"]).select(pool, None)
    assert d.action == CONNECT
    assert d.node.country_short == "KR"               # highest available


def test_priority_moves_up_when_better_country_returns():
    # On KR, but JP (higher priority) is now available -> move up.
    pool = _pool(_n("jp1", "JP"), _n("kr1", "KR"))
    cur = pool.find("kr1")
    d = _engine(mode="priority", priority=["JP", "KR", "SG"]).select(pool, cur)
    assert d.action == SWITCH
    assert d.node.country_short == "JP"


def test_priority_stays_when_on_top_country():
    pool = _pool(_n("jp1", "JP"), _n("kr1", "KR"))
    cur = pool.find("jp1")
    d = _engine(mode="priority", priority=["JP", "KR", "SG"]).select(pool, cur)
    assert d.action == KEEP


# --- auto -----------------------------------------------------------------
def test_auto_picks_best_score_country():
    pool = _pool(_n("jp1", "JP", latency=200), _n("kr1", "KR", latency=1))
    d = _engine(mode="auto").select(pool, current=None)
    assert d.action == CONNECT
    assert d.node.country_short == "KR"               # best composite score
