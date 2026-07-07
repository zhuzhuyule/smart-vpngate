"""Smart Exit Manager application — wires the five layers into a running system.

    Discovery -> NodePool -> HealthCheck -> PolicyEngine -> ExitManager
                                                                 |
                                                             Dashboard

This is the top-level orchestrator a deployment runs. It owns the supervise loop
(``run``) and a single ``tick`` step that refreshes discovery when due,
health-checks nodes, and lets the Exit Manager reconcile the active exit against
policy. The heavy dependencies (provider, feed fetcher, health probe) are
injected so the whole thing runs end-to-end with fakes in tests.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .config import Config
from .discovery import Discovery
from .exit_manager import ExitManager
from .health import HealthCheck, Probe
from .nodepool import NodePool
from .policy import PolicyEngine
from .provider import Provider


class SmartExitManager:
    def __init__(
        self,
        config: Config,
        provider: Provider,
        discovery: Discovery,
        pool: NodePool,
        health: HealthCheck,
        exit_manager: ExitManager,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.provider = provider
        self.discovery = discovery
        self.pool = pool
        self.health = health
        self.exit = exit_manager
        self._sleeper = sleeper
        self._stop = False

    # -- Construction -------------------------------------------------------
    @classmethod
    def build(
        cls,
        config: Config,
        provider: Provider,
        fetcher: Callable[[], str],
        probe: Probe,
        cache_path: str | Path = "vpngate_data/smart_nodes.json",
        pool_top_n: int = 50,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> "SmartExitManager":
        discovery = Discovery(config.discovery, fetcher=fetcher,
                              cache_path=cache_path, provider_name=provider.name)
        pool = NodePool(top_n=pool_top_n)
        health = HealthCheck(probe=probe, interval=config.health.interval)
        policy = PolicyEngine(config.policy)
        exit_manager = ExitManager(provider, policy, pool)
        return cls(config, provider, discovery, pool, health, exit_manager, sleeper)

    # -- Lifecycle ----------------------------------------------------------
    def bootstrap(self) -> None:
        """First discovery + initial exit selection.

        Tolerant of a failed first discovery (e.g. a transient network error at
        boot): the service still starts and the next tick retries.
        """
        try:
            self._refresh_discovery()
        except Exception as exc:  # noqa: BLE001 - keep booting; tick will retry
            self.exit.last_error = f"initial discovery failed: {exc}"
        self.exit.reconcile()

    def _refresh_discovery(self) -> None:
        nodes = self.discovery.refresh()
        self.pool.update(nodes)

    def tick(self) -> None:
        """One supervise step: refresh (if due) → health-check → reconcile."""
        if self.discovery.due():
            try:
                self._refresh_discovery()
            except Exception as exc:  # noqa: BLE001 - keep running on refresh error
                self.exit.last_error = f"discovery refresh failed: {exc}"

        active = self.exit.current

        # Health-check the active exit first; failover immediately if it died.
        if active is not None:
            result = self.health.check(active)
            if not result.ok:
                self.exit.on_health(active.id, healthy=False)
                active = self.exit.current  # may have changed

        # Health-check any other candidate that is due (bounded work per tick).
        for node in self.pool.all():
            if active is not None and node.id == active.id:
                continue
            if self.health.due(node):
                self.health.check(node)

        self.pool.resort()
        self.exit.reconcile()

    def run(self, once: bool = False, max_ticks: int | None = None) -> None:
        """Run the supervise loop. ``once``/``max_ticks`` bound it for tests."""
        self.bootstrap()
        if once:
            self.tick()
            return
        ticks = 0
        while not self._stop:
            self.tick()
            ticks += 1
            if max_ticks is not None and ticks >= max_ticks:
                break
            self._sleeper(self.config.health.interval)

    def stop(self) -> None:
        self._stop = True

    # -- Views --------------------------------------------------------------
    def dashboard(self) -> dict:
        from .dashboard import snapshot
        return snapshot(self.exit, self.pool)
