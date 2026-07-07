"""Tests for the zero-dependency stdlib YAML fallback parser."""

from __future__ import annotations

from pathlib import Path

from smart_vpngate import _yaml
from smart_vpngate.config import Config


SAMPLE = """
discovery:
  countries:
    - JP
    - KR
  blacklist: [CN, RU]
  max_nodes_per_country: 100
  min_score: 0
  refresh_interval: 1800   # 30 min
policy:
  mode: locked-country
  country: JP
  priority:
    - JP
    - KR
  stickiness: true
health:
  interval: 300
dashboard:
  auto_refresh: false
"""


def test_parses_nested_maps_and_block_lists():
    data = _yaml.safe_load(SAMPLE)
    assert data["discovery"]["countries"] == ["JP", "KR"]
    assert data["discovery"]["max_nodes_per_country"] == 100
    assert data["policy"]["priority"] == ["JP", "KR"]


def test_parses_flow_list():
    data = _yaml.safe_load(SAMPLE)
    assert data["discovery"]["blacklist"] == ["CN", "RU"]


def test_parses_scalars_and_bools():
    data = _yaml.safe_load(SAMPLE)
    assert data["policy"]["mode"] == "locked-country"
    assert data["policy"]["stickiness"] is True
    assert data["dashboard"]["auto_refresh"] is False
    assert data["health"]["interval"] == 300


def test_strips_inline_comments():
    data = _yaml.safe_load(SAMPLE)
    assert data["discovery"]["refresh_interval"] == 1800  # comment removed


def test_empty_text_is_none():
    assert _yaml.safe_load("\n# only a comment\n\n") is None


def test_matches_pyyaml_on_example_file():
    example = Path(__file__).resolve().parent.parent / "config.example.yaml"
    text = example.read_text(encoding="utf-8")
    stdlib_parsed = _yaml.safe_load(text)
    # Feed the stdlib-parsed mapping through Config: must yield the same result
    # as loading the file (which uses PyYAML here).
    from_stdlib = Config.from_mapping(stdlib_parsed)
    from_file = Config.load(example)
    assert from_stdlib == from_file


def test_config_from_stdlib_parsed_mapping(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(SAMPLE, encoding="utf-8")
    # Regardless of which parser backs Config.load, the result is well-formed.
    cfg = Config.load(p)
    assert cfg.discovery.countries == ["JP", "KR"]
    assert cfg.policy.country == "JP"
    assert cfg.dashboard.auto_refresh is False
