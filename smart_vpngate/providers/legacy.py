"""Bridge that lets the new brain drive the *old* proven engine.

Per the agreed design there is **one engine, one brain**: the brain (the
``smart_vpngate`` policy/scheduling/UI) decides *which* node to use; the engine
(the legacy ``vpngate_manager`` — OpenVPN launch + hardened policy routing +
the 7928 proxy gateway) actually establishes it. This connector plugs the old
engine into the new :class:`~smart_vpngate.providers.vpngate.VPNGateProvider`
via its ``OpenVPNConnector`` seam, so we reuse the battle-tested networking
without reimplementing (or modifying) it.

Only the *mechanical* engine functions are used
(``ensure_dirs`` / ``run_openvpn_until_ready`` / ``setup_policy_routing`` /
``cleanup_policy_routing`` / ``stop_process``) — the legacy engine's own
scheduler and routing *policy* are bypassed, because policy now lives in the
brain. The ``engine`` object is injectable so this is unit-testable without the
monolith (and without root/OpenVPN).
"""

from __future__ import annotations

import tempfile
from pathlib import Path


def _safe(node_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in node_id)


class LegacyEngineConnector:
    """Implements the ``OpenVPNConnector`` protocol by delegating to the engine.

    Parameters
    ----------
    engine:
        The legacy engine module (defaults to lazily importing
        ``vpngate_manager``). Injected in tests as a fake exposing the handful
        of functions used here.
    dev:
        TUN device name (default ``tun0``, matching the engine's routing).
    route_nopull:
        Pass ``--route-nopull`` so the brain, not the server, owns routing.
    """

    def __init__(self, engine: object | None = None, dev: str = "tun0",
                 route_nopull: bool = True) -> None:
        self._engine = engine
        self.dev = dev
        self.route_nopull = route_nopull

    @property
    def engine(self):
        if self._engine is None:
            import vpngate_manager as engine  # lazy: only needed for real runs
            self._engine = engine
        return self._engine

    def _config_path(self, node_id: str) -> Path:
        base = getattr(self.engine, "CONFIG_DIR", None) or Path(tempfile.gettempdir())
        base = Path(base)
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{_safe(node_id)}.ovpn"

    def start(self, config_text: str, node_id: str) -> dict:
        eng = self.engine
        # Ensure the engine's data dir + OpenVPN auth file exist.
        ensure = getattr(eng, "ensure_dirs", None)
        if callable(ensure):
            ensure()

        cfg = self._config_path(node_id)
        cfg.write_text(config_text, encoding="utf-8")

        ok, message, process = eng.run_openvpn_until_ready(
            str(cfg), keep_alive=True, route_nopull=self.route_nopull, dev=self.dev)

        ready = bool(ok and process is not None)
        if ready:
            # Hardened policy routing (table 100 + rp_filter loose) via the engine.
            try:
                eng.setup_policy_routing(self.dev)
            except Exception:  # noqa: BLE001 - routing is best-effort
                pass
        return {"process": process, "config": cfg, "ok": ready, "message": message}

    def is_ready(self, handle: object) -> bool:
        h = handle  # type: ignore[assignment]
        proc = h.get("process")
        return bool(h.get("ok")) and proc is not None and proc.poll() is None

    def stop(self, handle: object) -> None:
        eng = self.engine
        h = handle  # type: ignore[assignment]
        proc = h.get("process")
        if proc is not None:
            try:
                eng.stop_process(proc)
            except Exception:  # noqa: BLE001
                pass
        try:
            eng.cleanup_policy_routing()
        except Exception:  # noqa: BLE001
            pass
        cfg = h.get("config")
        if isinstance(cfg, Path):
            try:
                cfg.unlink(missing_ok=True)
            except OSError:
                pass
