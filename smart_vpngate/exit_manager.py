"""Exit Manager — the sole coordinator, owner of the single active exit.

Everything flows through here (Design Principle 5): the Dashboard never touches a
provider directly. The Exit Manager asks the Policy Engine what to do, then uses
the Provider to Connect / Disconnect / Switch / Recover, maintaining the
invariant that **exactly one exit is active at a time**.
"""

from __future__ import annotations

import time
from typing import Callable

from .models import Node
from .nodepool import NodePool
from .policy import CONNECT, KEEP, NONE, SWITCH, Decision, PolicyEngine
from .provider import Provider, ProviderStatus


class ExitManager:
    def __init__(
        self,
        provider: Provider,
        policy: PolicyEngine,
        pool: NodePool,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.provider = provider
        self.policy = policy
        self.pool = pool
        self._clock = clock

        self.current: Node | None = None
        self.status: ProviderStatus = ProviderStatus(connected=False)
        self.connected_since: float = 0.0
        self.last_decision: Decision | None = None
        self.last_error: str = ""

    # -- Core loop ----------------------------------------------------------
    def reconcile(self) -> Decision:
        """Ask the Policy Engine for the desired state and converge to it.

        Called on startup and on every health tick. Idempotent: when the policy
        says KEEP, nothing happens.
        """
        decision = self.policy.select(self.pool, self.current)
        self.last_decision = decision

        if decision.action in (CONNECT, SWITCH) and decision.node is not None:
            self._establish(decision.node)
        elif decision.action == NONE and self.current is None:
            pass  # nothing to do, nothing available
        # KEEP: leave the active exit untouched.
        return decision

    def _establish(self, node: Node) -> ProviderStatus:
        """Bring up exactly ``node`` as the single active exit."""
        status = self.provider.connect(node)
        if status.connected:
            self.current = node
            self.status = status
            self.connected_since = self._clock()
            self.last_error = ""
            self.pool.mark(node.id, "healthy")
        else:
            # Connect failed: mark the node down so policy avoids it next round.
            self.last_error = status.message or "connect failed"
            self.pool.mark(node.id, "down")
            if self.current is node:
                self.current = None
                self.status = ProviderStatus(connected=False)
        return status

    # -- Event hooks --------------------------------------------------------
    def on_health(self, node_id: str, healthy: bool) -> Decision | None:
        """Feed a health result in. A failing *active* node triggers failover."""
        if self.current is not None and node_id == self.current.id and not healthy:
            self.pool.mark(node_id, "down")
            self.current.status = "down"
            return self.reconcile()
        return None

    def switch(self, node_id: str) -> Decision:
        """Manual immediate switch (Dashboard action)."""
        node = self.pool.find(node_id)
        if node is None:
            decision = Decision(NONE, None, f"unknown node {node_id}")
            self.last_decision = decision
            return decision
        self._establish(node)
        decision = Decision(SWITCH, node, "manual switch")
        self.last_decision = decision
        return decision

    def recover(self) -> Decision | None:
        """Re-establish an exit if the current one is down/absent."""
        if self.current is None or self.current.status == "down":
            return self.reconcile()
        return None

    def disconnect(self) -> None:
        self.provider.disconnect()
        self.current = None
        self.status = ProviderStatus(connected=False)
        self.connected_since = 0.0

    # -- Introspection ------------------------------------------------------
    def snapshot(self) -> dict:
        """Current-exit state for the Dashboard (values, not provider access)."""
        node = self.current
        connected = self.status.connected and node is not None
        uptime = (self._clock() - self.connected_since) if connected else 0.0
        return {
            "connected": connected,
            "provider": self.provider.name,
            "node_id": node.id if node else "",
            "country": node.country if node else "",
            "country_short": node.country_short if node else "",
            "isp": node.isp if node else "",
            "asn": node.asn if node else "",
            "protocol": node.protocol if node else "",
            "ping": node.ping if node else 0,
            "latency_ms": node.latency_ms if node else 0,
            "health": node.status if node else "unknown",
            "public_ip": self.status.public_ip if connected else "",
            "connected_seconds": round(uptime, 1),
            "last_error": self.last_error,
            "last_decision": (
                {"action": self.last_decision.action, "reason": self.last_decision.reason}
                if self.last_decision else None
            ),
        }
