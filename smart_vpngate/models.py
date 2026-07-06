"""Data models shared across the Smart Exit Manager layers.

The :class:`Node` is the normalized representation of a candidate exit,
independent of which Provider produced it. Discovery emits ``Node`` objects,
the Node Pool stores them, Health Check updates their live metrics, and the
Policy Engine ranks them via :attr:`Node.score`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Node:
    """A single candidate exit node.

    Fields mirror the Dashboard "Node Table" in ``docs/DESIGN.md``. Discovery
    fills the static/identity fields; Health Check keeps the live metric fields
    (``latency_ms``, ``loss``, ``download``, ``upload``, ``status``,
    ``last_check``) up to date.
    """

    # --- Identity ---------------------------------------------------------
    id: str
    provider: str = "vpngate"
    ip: str = ""
    host_name: str = ""

    # --- Geo / network (V2: from provider data; V3: enriched via GeoIP) ---
    country: str = ""           # human-readable, possibly localized
    country_short: str = ""     # ISO-3166 alpha-2, e.g. "JP"
    city: str = ""
    isp: str = ""
    asn: str = ""

    # --- Connection config ------------------------------------------------
    protocol: str = "unknown"   # "tcp" | "udp"
    remote_host: str = ""
    remote_port: int = 0
    config_text: str = ""       # raw provider config (e.g. OpenVPN .ovpn)

    # --- Static provider-reported metrics ---------------------------------
    vpngate_score: int = 0      # VPNGate's own score (raw provider signal)
    sessions: int = 0

    # --- Live health metrics (owned by Health Check) ----------------------
    latency_ms: int = 0
    ping: int = 0
    loss: float = 0.0           # packet loss ratio 0.0..1.0
    download: float = 0.0       # Mbps
    upload: float = 0.0         # Mbps
    reputation: float = 0.0     # reserved for V3 IP reputation
    status: str = "unknown"     # "healthy" | "degraded" | "down" | "unknown"

    # --- Bookkeeping ------------------------------------------------------
    fetched_at: float = field(default_factory=time.time)
    last_check: float = 0.0

    @property
    def score(self) -> float:
        """Composite score used by the Policy Engine.

        Per the design, score is **not** ping. It blends latency, speed, loss,
        health and the provider's own signal. This is a deliberately simple,
        transparent V2 formula; ISP/ASN/reputation weighting arrives in V3.
        Higher is better.
        """
        score = 0.0

        # Provider-reported score (normalized into a modest band).
        score += min(self.vpngate_score / 1_000_000.0, 50.0)

        # Throughput: download in Mbps contributes directly (capped).
        score += min(self.download, 100.0)

        # Latency: lower is better. Use the freshest signal available.
        latency = self.latency_ms or self.ping
        if latency > 0:
            score += max(0.0, 50.0 - latency / 10.0)

        # Packet loss penalty.
        score -= self.loss * 100.0

        # Health status modifier.
        score += {
            "healthy": 25.0,
            "degraded": -10.0,
            "down": -1000.0,
        }.get(self.status, 0.0)

        return round(score, 3)

    def matches_country(self, target: str) -> bool:
        """True if this node belongs to ``target`` (ISO code or name)."""
        target = (target or "").strip().lower()
        if not target:
            return False
        return target in (
            self.country_short.strip().lower(),
            self.country.strip().lower(),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["score"] = self.score
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Node":
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        return cls(**known)
