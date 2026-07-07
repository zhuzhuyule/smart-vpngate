"""Concrete health probes used by the Health Check layer at runtime.

These are the real-world :data:`smart_vpngate.health.Probe` implementations.
They are kept out of :mod:`smart_vpngate.health` so that module stays free of
sockets and easy to unit-test with fakes.
"""

from __future__ import annotations

import socket
import time

from .health import HealthResult
from .models import Node


def tcp_probe(connect_timeout: float = 5.0):
    """Return a probe that TCP-connects to a node's OpenVPN endpoint.

    A successful connection to ``remote_host:remote_port`` is a cheap liveness
    signal that works without bringing the tunnel up, and the round-trip time is
    a usable latency estimate. UDP-only nodes (no listening TCP socket) will
    report down under this probe — a deployment can supply a richer probe.
    """

    def probe(node: Node) -> HealthResult:
        host = node.remote_host or node.ip
        port = node.remote_port or 443
        if not host:
            return HealthResult(ok=False, message="no endpoint")
        start = time.monotonic()
        try:
            with socket.create_connection((host, port), timeout=connect_timeout):
                latency_ms = int((time.monotonic() - start) * 1000)
                return HealthResult(ok=True, latency_ms=latency_ms, loss=0.0)
        except OSError as exc:
            return HealthResult(ok=False, message=f"tcp connect failed: {exc}")

    return probe


def null_probe(node: Node) -> HealthResult:
    """A probe that reports everything healthy (useful for dry runs)."""
    return HealthResult(ok=True, latency_ms=node.ping or 0, loss=0.0)
