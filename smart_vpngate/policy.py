"""Policy Engine — the sole owner of exit decisions.

Given the Node Pool and the currently active node, the Policy Engine decides
what the Exit Manager should do. It implements the design's four behaviours:

* **Lock Country** — stay in one country even if another is faster.
* **Country Priority** — prefer higher-priority countries when (re)selecting.
* **Stickiness** — keep the current node once it is healthy; never churn for a
  marginally faster peer in the same country.
* **Failover** — only leave a node when it is down / failed.

No other layer selects nodes. Providers connect what they are told; the Exit
Manager coordinates; the Dashboard triggers manual switches through the Exit
Manager. The engine itself is pure: it reads state and returns a
:class:`Decision`, it never touches a provider or a tunnel.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import PolicyConfig
from .models import Node
from .nodepool import NodePool

# Decision actions.
KEEP = "keep"          # current node is fine — do nothing
CONNECT = "connect"    # no current exit — connect to node
SWITCH = "switch"      # replace current exit with node
NONE = "none"          # nothing to do and nothing available


@dataclass
class Decision:
    action: str
    node: Node | None
    reason: str

    @property
    def changes_exit(self) -> bool:
        return self.action in (CONNECT, SWITCH)


class PolicyEngine:
    def __init__(self, config: PolicyConfig) -> None:
        self.config = config.normalized()

    # -- Country ordering ---------------------------------------------------
    def candidate_countries(self, pool: NodePool) -> list[str]:
        """Ordered list of countries the policy is willing to use.

        * ``locked-country`` → just the locked country.
        * ``priority``       → the configured priority order (only those with
          candidates), then any remaining pool countries as a safety net.
        * ``auto``           → every pool country, best-score first.
        """
        mode = self.config.mode
        if mode == "locked-country":
            return [self.config.country] if self.config.country else []

        if mode == "priority":
            ordered = [c for c in self.config.priority if pool.has_candidates(c)]
            # Safety net: append any other available countries not listed.
            for c in pool.countries():
                if c not in self.config.priority and pool.has_candidates(c):
                    ordered.append(c)
            return ordered

        # auto: rank available countries by their best node's score.
        available = [c for c in pool.countries() if pool.has_candidates(c)]
        available.sort(key=lambda c: pool.best(c).score, reverse=True)
        return available

    def target_country(self, pool: NodePool) -> str | None:
        for country in self.candidate_countries(pool):
            if pool.has_candidates(country):
                return country
        return None

    @staticmethod
    def _global_best(pool: NodePool, exclude: str | None = None) -> Node | None:
        """Highest-scoring viable node across *all* countries (the fastest exit)."""
        best: Node | None = None
        for node in pool.all():
            if node.status == "down" or node.id == exclude:
                continue
            if best is None or node.score > best.score:
                best = node
        return best

    # -- Decision -----------------------------------------------------------
    def select(self, pool: NodePool, current: Node | None) -> Decision:
        """Decide what the Exit Manager should do next."""
        allowed = self.candidate_countries(pool)
        target = self.target_country(pool)

        current_ok = current is not None and current.status != "down"
        current_allowed = (
            current is not None
            and any(current.matches_country(c) for c in allowed)
        )

        # --- Stickiness / failover: keep a healthy, still-allowed current. ---
        if current_ok and current_allowed:
            cur_code = current.country_short.upper()
            if self.config.stickiness:
                # In priority mode, move up if a strictly higher-priority
                # country became available (a policy trigger, not churn).
                if self.config.mode == "priority" and target and target != cur_code:
                    if _rank(self.config.priority, target) < _rank(self.config.priority, cur_code):
                        node = pool.best(target)
                        if node:
                            return Decision(SWITCH, node,
                                            f"higher-priority country {target} available")
                return Decision(KEEP, current, "current node healthy and allowed")
            # No stickiness: always ride the best node in the target country.
            best = pool.best(target) if target else None
            if best and best.id != current.id:
                return Decision(SWITCH, best, "best node changed (stickiness off)")
            return Decision(KEEP, current, "current node is already best")

        # --- Need a (re)selection: same/preferred country first. ---
        node = pool.best(target) if target else None

        # No viable node in any allowed country -> fastest-anywhere fallback.
        if node is None:
            if self.config.fallback_fastest:
                node = self._global_best(pool)
                if node is not None:
                    if current is not None and node.id == current.id:
                        return Decision(KEEP, current,
                                        "already on the fastest available exit")
                    action = CONNECT if current is None else SWITCH
                    return Decision(action, node,
                                    "no node in preferred country; "
                                    f"fastest-anywhere fallback -> {node.country_short}")
            # Fallback disabled or nothing viable at all: keep a live exit if we
            # have one, otherwise nothing to do.
            if current_ok:
                return Decision(KEEP, current,
                                "no allowed candidates; retaining current exit")
            return Decision(NONE, None, "no candidate nodes available")

        if current is None:
            return Decision(CONNECT, node, f"initial exit -> {target}")
        reason = (
            "current exit down" if not current_ok else "current exit off-policy"
        )
        return Decision(SWITCH, node, f"{reason}; selecting {target}")


def _rank(priority: list[str], country: str) -> int:
    """Index of ``country`` in the priority list; large if absent (lowest)."""
    try:
        return priority.index(country)
    except ValueError:
        return len(priority) + 1
