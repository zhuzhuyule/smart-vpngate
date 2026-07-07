"""Local proxy gateway — reuses the legacy SOCKS5/HTTP proxy server.

The 7928 proxy (what users actually route traffic through) is part of the
engine, so we reuse it as-is rather than reimplement it. This module just runs
the legacy ``proxy_server.start_proxy_server`` in a background daemon thread so
the single new service exposes the same gateway.

The proxy binds through ``tun0`` (via ``SO_BINDTODEVICE``); it is harmless to
start before a tunnel exists — it simply relays once the exit is up.
"""

from __future__ import annotations

import threading
from typing import Callable


def start_proxy_gateway(
    host: str = "127.0.0.1",
    port: int = 7928,
    server: Callable[[str, int], None] | None = None,
) -> threading.Thread:
    """Start the proxy gateway in a daemon thread and return it.

    ``server`` is injectable for tests; by default it lazily imports the legacy
    ``proxy_server.start_proxy_server``.
    """
    if server is None:
        from proxy_server import start_proxy_server as server  # lazy import

    def run() -> None:
        server(host, port)

    thread = threading.Thread(target=run, name="proxy-gateway", daemon=True)
    thread.start()
    return thread
