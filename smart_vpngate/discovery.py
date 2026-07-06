"""Discovery layer.

Responsibility (and *only* this): **discover, filter, cache**.

    VPNGate API -> Download -> Parse -> Normalize -> Filter -> Cache

Per Design Principle 2, Discovery is passive. It never connects, never selects
an exit, and never schedules. It turns a provider's raw feed into a filtered,
de-duplicated list of :class:`~smart_vpngate.models.Node` objects and caches
them to disk. The Node Pool and Policy Engine consume that cache.
"""

from __future__ import annotations

import base64
import csv
import json
import time
from pathlib import Path
from typing import Callable, Iterable

from .config import DiscoveryConfig
from .models import Node


def _decode_config(encoded: str) -> str:
    return base64.b64decode(encoded.encode("ascii"), validate=False).decode(
        "utf-8", errors="replace"
    )


def _parse_remote(config_text: str, fallback_ip: str = "") -> tuple[str, int, str]:
    """Extract (remote_host, remote_port, proto) from an OpenVPN config.

    Kept local so the ``smart_vpngate`` package stays self-contained and unit
    testable without the legacy modules. Mirrors ``vpn_utils.parse_remote``.
    """
    remote_host, remote_port, proto = fallback_ip, 0, "unknown"
    for raw_line in config_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";")):
            continue
        parts = line.split()
        if parts[0].lower() == "proto" and len(parts) >= 2:
            proto = parts[1].lower()
        elif parts[0].lower() == "remote" and len(parts) >= 3:
            remote_host = parts[1]
            remote_port = int(parts[2]) if parts[2].isdigit() else 0
            if len(parts) >= 4:
                proto = parts[3].lower()
    # Normalize openvpn proto variants (tcp-client/tcp4/...) to tcp/udp.
    if proto.startswith("tcp"):
        proto = "tcp"
    elif proto.startswith("udp"):
        proto = "udp"
    return remote_host, remote_port, proto


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)


def _parse_int(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def parse_rows(text: str) -> list[dict[str, str]]:
    """Parse the VPNGate CSV feed into raw row dicts."""
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("*")]
    if lines and lines[0].startswith("#"):
        lines[0] = lines[0][1:]
    return list(csv.DictReader(lines))


def row_to_node(row: dict[str, str], provider: str = "vpngate") -> Node | None:
    """Normalize one VPNGate CSV row into a :class:`Node` (or ``None``)."""
    ip = (row.get("IP") or "").strip()
    encoded = row.get("OpenVPN_ConfigData_Base64") or ""
    if not ip or not encoded:
        return None
    try:
        config_text = _decode_config(encoded)
    except Exception:
        return None

    country_short = (row.get("CountryShort") or "").strip()
    remote_host, remote_port, proto = _parse_remote(config_text, ip)
    node_id = _safe_name("_".join([country_short or "XX", ip, str(remote_port), proto]))

    return Node(
        id=node_id,
        provider=provider,
        ip=ip,
        host_name=(row.get("HostName") or "").strip(),
        country=(row.get("CountryLong") or "").strip(),
        country_short=country_short,
        protocol=proto,
        remote_host=remote_host,
        remote_port=remote_port,
        config_text=config_text,
        vpngate_score=_parse_int(row.get("Score")),
        ping=_parse_int(row.get("Ping")),
        sessions=_parse_int(row.get("NumVpnSessions")),
        fetched_at=time.time(),
    )


class Discovery:
    """Discovers and caches candidate nodes for one provider's feed.

    Parameters
    ----------
    config:
        The :class:`DiscoveryConfig` filters to apply.
    fetcher:
        Callable returning the raw feed text. Injected so tests (and alternate
        transports) can run without network access. Only called by
        :meth:`refresh`.
    cache_path:
        Where the filtered node list is persisted as JSON.
    provider_name:
        Tag applied to every produced node.
    """

    def __init__(
        self,
        config: DiscoveryConfig,
        fetcher: Callable[[], str],
        cache_path: str | Path,
        provider_name: str = "vpngate",
    ) -> None:
        self.config = config.normalized()
        self._fetcher = fetcher
        self.cache_path = Path(cache_path)
        self.provider_name = provider_name
        self.last_refresh: float = 0.0

    # -- Core pipeline ------------------------------------------------------
    def normalize(self, text: str) -> list[Node]:
        """Parse + normalize the raw feed into nodes (no filtering yet)."""
        nodes: list[Node] = []
        seen_ip: set[str] = set()
        for row in parse_rows(text):
            node = row_to_node(row, self.provider_name)
            if node is None or node.ip in seen_ip:
                continue
            seen_ip.add(node.ip)
            nodes.append(node)
        return nodes

    def filter(self, nodes: Iterable[Node]) -> list[Node]:
        """Apply allowlist/blacklist/protocol/threshold filters + per-country cap.

        Country allowlist takes precedence: if ``countries`` is non-empty only
        those are kept; the blacklist removes countries regardless.
        """
        cfg = self.config
        allow = set(cfg.countries)
        deny = set(cfg.blacklist)
        protos = set(cfg.protocols)

        kept: list[Node] = []
        for node in nodes:
            code = node.country_short.upper()
            if deny and code in deny:
                continue
            if allow and code not in allow:
                continue
            if protos and node.protocol not in protos:
                continue
            if node.vpngate_score < cfg.min_score:
                continue
            if node.ping and node.ping > cfg.max_ping:
                continue
            # VPNGate feed has no per-row speed column; min_speed is enforced by
            # the Node Pool once Health Check measures throughput. Kept here as a
            # no-op placeholder to honor the config contract.
            kept.append(node)

        # Highest VPNGate score first, then cap per country.
        kept.sort(key=lambda n: n.vpngate_score, reverse=True)
        per_country: dict[str, int] = {}
        capped: list[Node] = []
        for node in kept:
            code = node.country_short.upper()
            count = per_country.get(code, 0)
            if count >= cfg.max_nodes_per_country:
                continue
            per_country[code] = count + 1
            capped.append(node)
        return capped

    def refresh(self) -> list[Node]:
        """Fetch → normalize → filter → cache. Returns the cached nodes.

        This is the single side-effecting entry point, triggered on startup,
        manually, or by a timer (the design's three refresh triggers).
        """
        text = self._fetcher()
        nodes = self.filter(self.normalize(text))
        self._write_cache(nodes)
        self.last_refresh = time.time()
        return nodes

    def due(self, now: float | None = None) -> bool:
        """True if ``refresh_interval`` has elapsed since the last refresh."""
        now = time.time() if now is None else now
        return (now - self.last_refresh) >= self.config.refresh_interval

    # -- Cache --------------------------------------------------------------
    def _write_cache(self, nodes: list[Node]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "provider": self.provider_name,
            "cached_at": time.time(),
            "count": len(nodes),
            "nodes": [n.to_dict() for n in nodes],
        }
        tmp = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.cache_path)

    def cached(self) -> list[Node]:
        """Return nodes from the on-disk cache (empty if none/unreadable)."""
        if not self.cache_path.exists():
            return []
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return [Node.from_dict(d) for d in payload.get("nodes", [])]
