"""Health Check layer.

Continuously probes nodes (Ping / Loss / Download / Upload / Handshake /
Public IP per the design) and folds the results back into each
:class:`~smart_vpngate.models.Node` so the Node Pool and Policy Engine always
rank on fresh signal.

The actual probing mechanism is injected as a ``probe`` callable so this layer
is fully unit-testable offline and transport-agnostic — a real deployment plugs
in an ICMP/HTTP probe, tests plug in a deterministic fake. Health Check never
connects an exit or makes policy decisions; it only measures and classifies.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from .models import Node


@dataclass
class HealthResult:
    """Outcome of probing a single node."""

    ok: bool
    latency_ms: int = 0
    loss: float = 0.0          # 0.0 .. 1.0
    download: float = 0.0      # Mbps
    upload: float = 0.0        # Mbps
    public_ip: str = ""
    message: str = ""
    extra: dict = field(default_factory=dict)


#: A probe takes a node and returns how healthy it currently is.
Probe = Callable[[Node], HealthResult]


def classify(result: HealthResult, degraded_loss: float = 0.5) -> str:
    """Map a probe result to a node status string.

    * ``down``     — probe failed outright.
    * ``degraded`` — reachable but lossy (``loss >= degraded_loss``).
    * ``healthy``  — reachable and clean.
    """
    if not result.ok:
        return "down"
    if result.loss >= degraded_loss:
        return "degraded"
    return "healthy"


class HealthCheck:
    """Runs probes and updates node health in place."""

    def __init__(
        self,
        probe: Probe,
        interval: int = 300,
        degraded_loss: float = 0.5,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.probe = probe
        self.interval = max(1, int(interval))
        self.degraded_loss = degraded_loss
        self._clock = clock

    def check(self, node: Node) -> HealthResult:
        """Probe one node and write the metrics + status back onto it."""
        try:
            result = self.probe(node)
        except Exception as exc:  # noqa: BLE001 - a raising probe means "down"
            result = HealthResult(ok=False, message=f"probe error: {exc}")

        node.status = classify(result, self.degraded_loss)
        node.last_check = self._clock()
        if result.ok:
            node.latency_ms = result.latency_ms
            if result.latency_ms:
                node.ping = result.latency_ms
            node.loss = result.loss
            node.download = result.download
            node.upload = result.upload
        else:
            node.loss = 1.0
        return result

    def check_all(self, nodes: Iterable[Node]) -> dict[str, HealthResult]:
        """Probe every node; return ``{node_id: HealthResult}``."""
        return {node.id: self.check(node) for node in nodes}

    def due(self, node: Node, now: float | None = None) -> bool:
        """True if ``node`` hasn't been checked within ``interval`` seconds."""
        now = self._clock() if now is None else now
        if not node.last_check:
            return True
        return (now - node.last_check) >= self.interval
