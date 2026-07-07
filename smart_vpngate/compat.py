"""Legacy status compatibility for the `sv` / `ml` terminal menu.

The management menu reads the engine's ``state.json`` / ``nodes.json`` /
``public_ip.txt``. The scheduling layer keeps its own state, so to make the
menu reflect the single service we mirror the current exit into those legacy
files each tick. This is a thin, best-effort adapter — it never affects
scheduling and failures are swallowed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _data_dir(explicit: str | Path | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    try:  # reuse the engine's resolved data dir so paths always match
        import vpngate_manager as eng
        return Path(eng.DATA_DIR)
    except Exception:  # noqa: BLE001
        env = os.environ.get("VPNGATE_DATA_DIR")
        return Path(env).resolve() if env else Path("vpngate_data")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_legacy_status(app, proxy_port: int = 7928,
                        data_dir: str | Path | None = None) -> None:
    """Mirror the current exit into the legacy status files the menu reads."""
    try:
        d = _data_dir(data_dir)
        snap = app.exit.snapshot()
        current = app.exit.current
        connected = bool(snap.get("connected"))
        public_ip = snap.get("public_ip") or ""
        latency = snap.get("latency_ms") or snap.get("ping") or 0

        state = {
            "active_openvpn_node_id": snap.get("node_id", "") if connected else "",
            "is_connecting": False,
            "active_node_latency": (f"{latency} ms" if latency else "测试中...")
                                   if connected else "无活动连接",
            "proxy_ok": bool(connected and public_ip),
            "proxy_ip": public_ip or "-",
            "proxy_latency_ms": latency,
            "proxy_error": snap.get("last_error", "") or "",
            "last_check_message": (snap.get("last_decision") or {}).get("reason", ""),
            "local_proxy": f"http://127.0.0.1:{proxy_port}",
        }
        _write_json(d / "state.json", state)

        # Minimal legacy-shaped node list (menu needs ip + location of active).
        nodes = []
        for n in app.pool.all():
            nodes.append({
                "id": n.id,
                "ip": n.ip,
                "remote_host": n.remote_host,
                "country": n.country or n.country_short,
                "location": n.country or n.country_short,
                "active": bool(current and n.id == current.id),
            })
        _write_json(d / "nodes.json", nodes)

        if public_ip:
            (d / "public_ip.txt").write_text(public_ip, encoding="utf-8")
    except Exception:  # noqa: BLE001 - status mirroring must never break the loop
        pass
