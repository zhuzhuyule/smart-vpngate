"""In-memory provider for tests, demos and dry runs.

Simulates connecting/disconnecting without touching the network or OpenVPN, so
the whole scheduler (Discovery → Pool → Health → Policy → Exit Manager) can be
exercised deterministically. ``fail_ids`` lets a test mark specific nodes as
un-connectable to drive failover paths.
"""

from __future__ import annotations

import itertools

from ..models import Node
from ..provider import Provider, ProviderStatus


class FakeProvider(Provider):
    name = "fake"

    def __init__(self, nodes: list[Node] | None = None, fail_ids: set[str] | None = None):
        self._nodes = list(nodes or [])
        self.fail_ids = set(fail_ids or ())
        self._current: Node | None = None
        self._ip_counter = itertools.count(1)
        self._public_ip = ""
        self.connect_calls: list[str] = []
        self.disconnect_calls = 0

    def discover(self) -> list[Node]:
        return list(self._nodes)

    def connect(self, node: Node) -> ProviderStatus:
        # Single active exit: drop the previous one first.
        if self._current is not None:
            self.disconnect()
        self.connect_calls.append(node.id)
        if node.id in self.fail_ids:
            self._current = None
            self._public_ip = ""
            return ProviderStatus(connected=False, node_id=node.id,
                                  message="simulated connect failure")
        self._current = node
        self._public_ip = f"203.0.113.{next(self._ip_counter)}"
        return ProviderStatus(connected=True, node_id=node.id,
                              public_ip=self._public_ip, since=0.0,
                              message="connected")

    def disconnect(self) -> None:
        if self._current is not None:
            self.disconnect_calls += 1
        self._current = None
        self._public_ip = ""

    def status(self) -> ProviderStatus:
        if self._current is None:
            return ProviderStatus(connected=False)
        return ProviderStatus(connected=True, node_id=self._current.id,
                              public_ip=self._public_ip)

    def public_ip(self) -> str | None:
        return self._public_ip or None
