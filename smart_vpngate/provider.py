"""Provider abstraction — the seam that lets Smart VPNGate stay multi-provider.

Per the design, a Provider is **thin**: it only Connects, Disconnects, reports
Status and its Public IP, and Discovers candidate nodes. It must not perform
Policy, scheduling or Dashboard work — the Exit Manager and Policy Engine own
those. VPNGate is simply the first implementation of this interface; WireGuard,
WARP, SOCKS5 etc. can be added later without touching the scheduler.

This is the Python translation of the ``Provider`` interface sketched in Go in
``docs/DESIGN.md``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .models import Node


@dataclass
class ProviderStatus:
    """A snapshot of a provider's current connection state."""

    connected: bool = False
    node_id: str = ""
    public_ip: str = ""
    since: float = 0.0          # epoch seconds the current connection began
    message: str = ""
    extra: dict = field(default_factory=dict)


class Provider(ABC):
    """Abstract base every exit provider implements.

    Implementations MUST remain policy-free: given a :class:`Node` chosen by the
    Policy Engine, ``connect`` establishes exactly that exit and nothing else.
    """

    #: Stable provider identifier, e.g. ``"vpngate"``. Used to tag nodes.
    name: str = "provider"

    @abstractmethod
    def discover(self) -> list[Node]:
        """Return the raw candidate nodes this provider can offer.

        Discovery only *discovers* — filtering, ranking and selection happen in
        the Discovery layer and Policy Engine, never here.
        """

    @abstractmethod
    def connect(self, node: Node) -> ProviderStatus:
        """Establish the single active exit to ``node`` and return its status."""

    @abstractmethod
    def disconnect(self) -> None:
        """Tear down the active exit, if any."""

    @abstractmethod
    def status(self) -> ProviderStatus:
        """Return the current connection status without side effects."""

    @abstractmethod
    def public_ip(self) -> str | None:
        """Return the observed public egress IP, or ``None`` if unknown."""
