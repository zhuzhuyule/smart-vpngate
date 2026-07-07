"""Dashboard layer — read-only state assembly.

The Dashboard never touches a Provider (Design Principle 5); it reads everything
through the Exit Manager and the Node Pool and returns plain values. This module
produces the two views from the design: the **Current Exit** panel and the
**Node Table**. Rendering (web/CLI) is a thin consumer of :func:`snapshot`.
"""

from __future__ import annotations

from .exit_manager import ExitManager
from .models import Node
from .nodepool import NodePool


def node_row(node: Node, current_id: str | None) -> dict:
    """One Node Table row, matching the columns in ``docs/DESIGN.md``."""
    return {
        "id": node.id,
        "country": node.country,
        "country_short": node.country_short,
        "city": node.city,
        "isp": node.isp,
        "asn": node.asn,
        "latency_ms": node.latency_ms,
        "loss": node.loss,
        "download": node.download,
        "upload": node.upload,
        "score": node.score,
        "status": node.status,
        "current": node.id == current_id,
        "last_check": node.last_check,
        "protocol": node.protocol,
    }


def snapshot(exit_manager: ExitManager, pool: NodePool) -> dict:
    """Full dashboard state: current exit + node table + summary."""
    current_id = exit_manager.current.id if exit_manager.current else None
    rows = [node_row(n, current_id) for n in pool.all()]
    return {
        "current_exit": exit_manager.snapshot(),
        "nodes": rows,
        "countries": pool.countries(),
        "total_nodes": len(pool),
    }
