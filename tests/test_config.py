"""Unit tests for YAML config loading and normalization."""

from __future__ import annotations

import pytest

from smart_vpngate.config import Config


def test_defaults_when_no_path():
    cfg = Config.load(None)
    assert cfg.discovery.countries == ["JP", "KR", "US"]
    assert cfg.policy.mode == "locked-country"
    assert cfg.policy.country == "JP"
    assert cfg.health.interval == 300
    assert cfg.dashboard.auto_refresh is True


def test_defaults_when_file_missing(tmp_path):
    cfg = Config.load(tmp_path / "does-not-exist.yaml")
    assert cfg.discovery.max_nodes_per_country == 100


def test_load_and_normalize(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
discovery:
  countries: [jp, kr]
  blacklist: [cn]
  protocols: [TCP]
  refresh_interval: 10   # below floor, should clamp to 60
policy:
  mode: PRIORITY
  country: sg
  priority: [sg, jp]
  stickiness: false
health:
  interval: 10           # below floor, clamps to 30
""",
        encoding="utf-8",
    )
    cfg = Config.load(p)
    assert cfg.discovery.countries == ["JP", "KR"]
    assert cfg.discovery.blacklist == ["CN"]
    assert cfg.discovery.protocols == ["tcp"]
    assert cfg.discovery.refresh_interval == 60
    assert cfg.policy.mode == "priority"
    assert cfg.policy.country == "SG"
    assert cfg.policy.priority == ["SG", "JP"]
    assert cfg.policy.stickiness is False
    assert cfg.health.interval == 30


def test_partial_config_keeps_defaults(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("policy:\n  country: US\n", encoding="utf-8")
    cfg = Config.load(p)
    assert cfg.policy.country == "US"
    assert cfg.discovery.countries == ["JP", "KR", "US"]  # untouched default


def test_unknown_keys_ignored(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("discovery:\n  bogus_key: 1\n  countries: [jp]\n", encoding="utf-8")
    cfg = Config.load(p)
    assert cfg.discovery.countries == ["JP"]


def test_invalid_root_raises(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Config.load(p)


def test_invalid_yaml_raises(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("discovery: [unclosed\n", encoding="utf-8")
    with pytest.raises(ValueError):
        Config.load(p)
