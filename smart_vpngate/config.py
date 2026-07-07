"""Config-first configuration for Smart VPNGate.

Everything is YAML (see ``config.example.yaml``). This module defines typed
dataclasses for each section of the design's config schema, loads a YAML file
on top of sane defaults, and normalizes/validates the result.

The project ships zero-dependency: PyYAML is used when installed, otherwise a
tiny stdlib fallback (:mod:`smart_vpngate._yaml`) parses the config subset. So
loading works on a stock ``python3`` with no pip packages.

Loading never raises on a missing file — defaults are returned — so the system
can boot with zero configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

try:  # Prefer PyYAML when available; fall back to the stdlib subset parser.
    import yaml as _yaml
    _YAMLError: type[Exception] = getattr(_yaml, "YAMLError", ValueError)

    def _yaml_load(text: str) -> Any:
        return _yaml.safe_load(text)
except ImportError:  # pragma: no cover - exercised on stock installs
    from . import _yaml as _stdlib_yaml
    _YAMLError = ValueError

    def _yaml_load(text: str) -> Any:
        return _stdlib_yaml.safe_load(text)


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    return [str(v).strip() for v in value if str(v).strip()]


@dataclass
class DiscoveryConfig:
    """Discovery layer settings (allowlist, blacklist, filters, refresh)."""

    countries: list[str] = field(default_factory=lambda: ["JP", "KR", "US"])
    blacklist: list[str] = field(default_factory=lambda: ["CN", "RU"])
    protocols: list[str] = field(default_factory=lambda: ["tcp", "udp"])
    max_nodes_per_country: int = 100
    # Optional per-country overrides of max_nodes_per_country, e.g. {"JP": 50}.
    # Countries not listed fall back to max_nodes_per_country.
    per_country_limits: dict[str, int] = field(default_factory=dict)
    min_score: int = 0
    min_speed: int = 0          # bytes/sec, as reported by VPNGate
    max_ping: int = 9999        # ms
    refresh_interval: int = 1800  # seconds (design example: 30min)

    def limit_for(self, country: str) -> int:
        """Node quota for ``country`` (per-country override or the global max)."""
        return self.per_country_limits.get((country or "").upper(),
                                            self.max_nodes_per_country)

    def normalized(self) -> "DiscoveryConfig":
        limits: dict[str, int] = {}
        for code, value in (self.per_country_limits or {}).items():
            try:
                limits[str(code).strip().upper()] = max(1, int(value))
            except (TypeError, ValueError):
                continue
        return replace(
            self,
            countries=[c.upper() for c in _as_str_list(self.countries)],
            blacklist=[c.upper() for c in _as_str_list(self.blacklist)],
            protocols=[p.lower() for p in _as_str_list(self.protocols)] or ["tcp", "udp"],
            max_nodes_per_country=max(1, int(self.max_nodes_per_country)),
            per_country_limits=limits,
            min_score=max(0, int(self.min_score)),
            min_speed=max(0, int(self.min_speed)),
            max_ping=max(1, int(self.max_ping)),
            refresh_interval=max(60, int(self.refresh_interval)),
        )


@dataclass
class PolicyConfig:
    """Policy Engine settings (mode, locked country, priority, stickiness)."""

    mode: str = "locked-country"   # "locked-country" | "priority" | "auto"
    country: str = "JP"            # used when mode == locked-country
    priority: list[str] = field(default_factory=lambda: ["JP", "KR", "SG", "US"])
    stickiness: bool = True
    # When the preferred country has no viable node, fall back to the globally
    # fastest healthy node instead of having no exit at all.
    fallback_fastest: bool = True

    def normalized(self) -> "PolicyConfig":
        return replace(
            self,
            mode=(self.mode or "locked-country").strip().lower(),
            country=(self.country or "").strip().upper(),
            priority=[c.upper() for c in _as_str_list(self.priority)],
            stickiness=bool(self.stickiness),
            fallback_fastest=bool(self.fallback_fastest),
        )


@dataclass
class HealthConfig:
    """Health Check settings."""

    interval: int = 300   # seconds (design example: 5min)

    def normalized(self) -> "HealthConfig":
        return replace(self, interval=max(30, int(self.interval)))


@dataclass
class DashboardConfig:
    """Dashboard settings."""

    auto_refresh: bool = True

    def normalized(self) -> "DashboardConfig":
        return replace(self, auto_refresh=bool(self.auto_refresh))


@dataclass
class Config:
    """Top-level Smart VPNGate configuration."""

    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)

    def normalized(self) -> "Config":
        return Config(
            discovery=self.discovery.normalized(),
            policy=self.policy.normalized(),
            health=self.health.normalized(),
            dashboard=self.dashboard.normalized(),
        )

    # ------------------------------------------------------------------ #
    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "Config":
        data = data or {}

        def section(name: str, klass: type) -> Any:
            raw = data.get(name) or {}
            if not isinstance(raw, dict):
                raw = {}
            known = {k: raw[k] for k in klass.__dataclass_fields__ if k in raw}
            return klass(**known)

        return cls(
            discovery=section("discovery", DiscoveryConfig),
            policy=section("policy", PolicyConfig),
            health=section("health", HealthConfig),
            dashboard=section("dashboard", DashboardConfig),
        ).normalized()

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        """Load config from ``path``. Missing/empty file → defaults."""
        if path is None:
            return cls().normalized()
        p = Path(path)
        if not p.exists():
            return cls().normalized()
        try:
            raw = _yaml_load(p.read_text(encoding="utf-8")) or {}
        except _YAMLError as exc:
            raise ValueError(f"Invalid YAML config at {p}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"Config root must be a mapping, got {type(raw).__name__}")
        return cls.from_mapping(raw)
