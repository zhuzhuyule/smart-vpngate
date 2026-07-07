"""Node Pool layer.

Not a single flat list but **per-country pools**, each keeping the best ``top_n``
candidates. Responsibilities (from ``docs/DESIGN.md``): sorting, updating,
caching, lifecycle, eviction and standby nodes.

The pool is fed by Discovery and read by the Policy Engine. When Discovery
refreshes, live health metrics measured by Health Check are **preserved** for
nodes that still exist, so a refresh never wipes out what we've learned.
"""

from __future__ import annotations

import time
from typing import Callable, Iterable

from .models import Node

# Health fields owned by Health Check — carried across Discovery refreshes.
_HEALTH_FIELDS = (
    "latency_ms",
    "ping",
    "loss",
    "download",
    "upload",
    "reputation",
    "status",
    "last_check",
)


class NodePool:
    """Maintains independent, score-sorted candidate pools per country."""

    def __init__(self, top_n: int = 50) -> None:
        self.top_n = max(1, int(top_n))
        # country_short -> list[Node] (sorted best-first, capped at top_n)
        self._pools: dict[str, list[Node]] = {}
        # id -> Node (fast lookup, shares objects with _pools)
        self._by_id: dict[str, Node] = {}
        self.updated_at: float = 0.0

    # -- Ingestion ----------------------------------------------------------
    def update(self, nodes: Iterable[Node]) -> None:
        """Replace the candidate set, preserving health metrics by node id.

        Nodes absent from ``nodes`` are dropped (Discovery is the source of
        truth for *which* candidates exist); surviving nodes keep their measured
        health so the pool stays warm across refreshes.
        """
        merged: list[Node] = []
        for node in nodes:
            prev = self._by_id.get(node.id)
            if prev is not None:
                for f in _HEALTH_FIELDS:
                    setattr(node, f, getattr(prev, f))
            merged.append(node)
        self._rebuild(merged)
        self.updated_at = time.time()

    def _rebuild(self, nodes: list[Node]) -> None:
        pools: dict[str, list[Node]] = {}
        for node in nodes:
            pools.setdefault(node.country_short.upper(), []).append(node)
        self._by_id = {}
        for code, group in pools.items():
            group.sort(key=lambda n: n.score, reverse=True)
            del group[self.top_n:]
            for node in group:
                self._by_id[node.id] = node
        self._pools = pools

    def resort(self) -> None:
        """Re-sort every country pool (call after health metrics change)."""
        self._rebuild(list(self._by_id.values()))

    # -- Queries ------------------------------------------------------------
    def countries(self) -> list[str]:
        """Country codes that currently have at least one candidate."""
        return sorted(self._pools.keys())

    def get(self, country: str) -> list[Node]:
        """All candidates for ``country`` (best-first). Empty if none."""
        return list(self._pools.get((country or "").upper(), []))

    def find(self, node_id: str) -> Node | None:
        return self._by_id.get(node_id)

    def all(self) -> list[Node]:
        """Every candidate across all countries, best-first within country."""
        out: list[Node] = []
        for code in self.countries():
            out.extend(self._pools[code])
        return out

    def __len__(self) -> int:
        return len(self._by_id)

    def best(
        self,
        country: str,
        exclude: str | None = None,
        include_down: bool = False,
    ) -> Node | None:
        """Highest-scoring viable node in ``country``.

        Skips nodes marked ``down`` (unless ``include_down``) and the ``exclude``
        id. Returns ``None`` when the country has no viable candidate.
        """
        for node in self._pools.get((country or "").upper(), []):
            if node.id == exclude:
                continue
            if not include_down and node.status == "down":
                continue
            return node
        return None

    def has_candidates(self, country: str) -> bool:
        return self.best(country) is not None

    # -- Lifecycle ----------------------------------------------------------
    def mark(self, node_id: str, status: str) -> bool:
        """Set a node's health status (e.g. after a failed connect). """
        node = self._by_id.get(node_id)
        if node is None:
            return False
        node.status = status
        node.last_check = time.time()
        return True

    def evict(self, predicate: Callable[[Node], bool]) -> list[Node]:
        """Remove and return nodes matching ``predicate`` (e.g. stale/down)."""
        removed = [n for n in self._by_id.values() if predicate(n)]
        if removed:
            remaining = [n for n in self._by_id.values() if not predicate(n)]
            self._rebuild(remaining)
        return removed

    def evict_stale(self, max_age: float, now: float | None = None) -> list[Node]:
        """Evict nodes not health-checked within ``max_age`` seconds.

        Nodes never checked (``last_check == 0``) are treated as fresh — they
        simply haven't had their turn yet.
        """
        now = time.time() if now is None else now
        return self.evict(lambda n: n.last_check and (now - n.last_check) > max_age)
