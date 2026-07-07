"""VPNGate provider — the first concrete :class:`Provider`.

Discovers VPNGate nodes and establishes a single OpenVPN exit. The OpenVPN
mechanics are delegated to an injectable :class:`OpenVPNConnector`, and the
public-IP lookup to an injectable callable, so:

* on a real VPS the defaults shell out to ``openvpn`` and query an IP echo
  service (needs root + a TUN device, exactly like the legacy manager), and
* in tests a fake connector/lookup drives every branch offline.

Per the design, this provider is **thin**: it connects exactly the node the
Policy Engine picked and reports status. It never filters, ranks or schedules.
"""

from __future__ import annotations

import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Callable, Protocol

from ..discovery import parse_rows, row_to_node
from ..fetch import DEFAULT_API_URL, http_fetcher
from ..models import Node
from ..provider import Provider, ProviderStatus


class OpenVPNConnector(Protocol):
    """Abstracts starting/stopping an OpenVPN tunnel for one node."""

    def start(self, config_text: str, node_id: str) -> object: ...
    def stop(self, handle: object) -> None: ...
    def is_ready(self, handle: object) -> bool: ...


class SubprocessOpenVPNConnector:
    """Default connector: launches the real ``openvpn`` binary.

    Best-effort and deliberately small — a production VPS already runs the
    legacy manager's hardened routing. This exists so ``VPNGateProvider`` works
    standalone; heavy lifting (policy routing, rp_filter fixes) can be layered
    on later. Requires root and a TUN device.
    """

    def __init__(self, openvpn_cmd: str = "openvpn", ready_timeout: int = 60,
                 dev: str = "tun0") -> None:
        self.openvpn_cmd = openvpn_cmd
        self.ready_timeout = ready_timeout
        self.dev = dev

    def start(self, config_text: str, node_id: str) -> object:
        tmp = Path(tempfile.gettempdir()) / f"smart_vpngate_{node_id}.ovpn"
        tmp.write_text(config_text, encoding="utf-8")
        proc = subprocess.Popen(
            [self.openvpn_cmd, "--config", str(tmp), "--dev", self.dev],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        return {"proc": proc, "config": tmp, "ready": self._await_ready(proc)}

    def _await_ready(self, proc: subprocess.Popen) -> bool:
        deadline = time.monotonic() + self.ready_timeout
        assert proc.stdout is not None
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    return False
                continue
            if "Initialization Sequence Completed" in line:
                return True
        return False

    def is_ready(self, handle: object) -> bool:
        h = handle  # type: ignore[assignment]
        proc = h["proc"]
        return bool(h.get("ready")) and proc.poll() is None

    def stop(self, handle: object) -> None:
        h = handle  # type: ignore[assignment]
        proc = h.get("proc")
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        cfg = h.get("config")
        if isinstance(cfg, Path):
            cfg.unlink(missing_ok=True)


def _default_ip_lookup(
    proxy_url: str | None = None,
    opener_factory: Callable[..., object] = urllib.request.build_opener,
) -> str:
    """Return the observed public egress IP.

    When ``proxy_url`` is set (the running 7928 gateway), the query is routed
    **through the tunnel** via that proxy, so it reflects the exit IP rather than
    the VPS's own IP — the default route does not go through ``tun0`` under
    ``--route-nopull``. ``opener_factory`` is injected for tests.
    """
    handlers = []
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    opener = opener_factory(*handlers)
    for url in ("https://api.ipify.org", "http://api.ipify.org"):
        try:
            with opener.open(url, timeout=10) as resp:
                return resp.read().decode().strip()
        except Exception:  # noqa: BLE001 - try the next endpoint
            continue
    return ""


class VPNGateProvider(Provider):
    name = "vpngate"

    def __init__(
        self,
        connector: OpenVPNConnector | None = None,
        fetcher: Callable[[], str] | None = None,
        ip_lookup: Callable[[], str] | None = None,
        api_url: str = DEFAULT_API_URL,
        proxy_url: str | None = "http://127.0.0.1:7928",
    ) -> None:
        self._connector = connector or SubprocessOpenVPNConnector()
        self._fetcher = fetcher or http_fetcher(api_url)
        # Route the public-IP query through the local gateway so it reports the
        # exit IP (through the tunnel), not the VPS IP.
        self._ip_lookup = ip_lookup or (lambda: _default_ip_lookup(proxy_url))
        self._handle: object | None = None
        self._current: Node | None = None
        self._public_ip: str = ""
        self._since: float = 0.0

    def discover(self) -> list[Node]:
        """Return raw (unfiltered) VPNGate candidates — filtering is Discovery's job."""
        text = self._fetcher()
        nodes: list[Node] = []
        seen: set[str] = set()
        for row in parse_rows(text):
            node = row_to_node(row, self.name)
            if node is None or node.ip in seen:
                continue
            seen.add(node.ip)
            nodes.append(node)
        return nodes

    def connect(self, node: Node) -> ProviderStatus:
        if self._handle is not None:
            self.disconnect()
        if not node.config_text:
            return ProviderStatus(connected=False, node_id=node.id,
                                  message="node has no OpenVPN config")
        handle = self._connector.start(node.config_text, node.id)
        if not self._connector.is_ready(handle):
            self._connector.stop(handle)
            return ProviderStatus(connected=False, node_id=node.id,
                                  message="OpenVPN failed to initialize")
        self._handle = handle
        self._current = node
        self._public_ip = self._ip_lookup() or ""
        self._since = 0.0
        return ProviderStatus(connected=True, node_id=node.id,
                              public_ip=self._public_ip, since=self._since,
                              message="connected")

    def disconnect(self) -> None:
        if self._handle is not None:
            self._connector.stop(self._handle)
        self._handle = None
        self._current = None
        self._public_ip = ""

    def status(self) -> ProviderStatus:
        if self._handle is None or self._current is None:
            return ProviderStatus(connected=False)
        alive = self._connector.is_ready(self._handle)
        if not alive:
            return ProviderStatus(connected=False, node_id=self._current.id,
                                  message="tunnel dropped")
        return ProviderStatus(connected=True, node_id=self._current.id,
                              public_ip=self._public_ip, since=self._since)

    def public_ip(self) -> str | None:
        if self._handle is None:
            return None
        return self._public_ip or None
