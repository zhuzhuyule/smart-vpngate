# tests/test_snapshot_fallback.py
"""节点源兜底链：官方 API → 镜像 → 本地缓存快照 → 仓库内置快照。"""
import base64
import os
import tempfile
import unittest

os.environ.setdefault("VPNGATE_DATA_DIR", tempfile.mkdtemp())

import snapshot_utils
import vpngate_manager as m

# 一个能通过 snapshot_utils 校验的最小 OpenVPN 客户端配置
_GOOD_CONFIG = "\n".join(
    [
        "client",
        "dev tun",
        "proto udp",
        "remote 203.0.113.7 1194",
        "remote-cert-tls server",
        "<ca>",
        "Y2E=",
        "</ca>",
        "<cert>",
        "Y2VydA==",
        "</cert>",
        "<key>",
        "a2V5",
        "</key>",
    ]
)
_BAD_CONFIG = "client\nscript-security 2\nup /tmp/evil.sh\nremote 203.0.113.7 1194\n"


def _csv_row(ip: str, host: str, country: str, config_text: str) -> str:
    encoded = base64.b64encode(config_text.encode("utf-8")).decode("ascii")
    return ",".join([host, ip, "1000", "21", "100000", "Japan", country, "10", encoded])


HEADER = (
    "HostName,IP,Score,Ping,Speed,CountryLong,CountryShort,NumVpnSessions,"
    "OpenVPN_ConfigData_Base64"
)
SNAPSHOT = "\n".join(
    [
        HEADER,
        _csv_row("203.0.113.7", "host-a", "JP", _GOOD_CONFIG),
        _csv_row("203.0.113.8", "host-b", "JP", _BAD_CONFIG),
    ]
)


class TestSnapshotValidation(unittest.TestCase):
    def test_rejects_script_security(self):
        with self.assertRaises(ValueError):
            snapshot_utils.validate_openvpn_config(
                "client\nremote 1.2.3.4 443\nscript-security 2\n<ca>x</ca><cert>y</cert><key>z</key>"
            )

    def test_rejects_up_directive(self):
        with self.assertRaises(ValueError):
            snapshot_utils.validate_openvpn_config(
                "client\nremote 1.2.3.4 443\nup /tmp/evil.sh\n<ca>x</ca><cert>y</cert><key>z</key>"
            )

    def test_accepts_normal_client_config(self):
        snapshot_utils.validate_openvpn_config(_GOOD_CONFIG)

    def test_parse_skips_unsafe_rows(self):
        rows = snapshot_utils.parse_and_validate_snapshot(SNAPSHOT)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["IP"], "203.0.113.7")


class TestFallbackChain(unittest.TestCase):
    def setUp(self):
        self.data_dir = os.environ["VPNGATE_DATA_DIR"]
        m.API_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        m.API_CACHE_FILE.write_text(SNAPSHOT, encoding="utf-8")
        self.orig_fetch = m.fetch_api_text

    def tearDown(self):
        m.fetch_api_text = self.orig_fetch
        if m.API_CACHE_FILE.exists():
            m.API_CACHE_FILE.unlink()

    def test_falls_back_to_local_snapshot_when_network_down(self):
        def boom(*_args, **_kwargs):
            raise RuntimeError("network unreachable")

        m.fetch_api_text = boom
        candidates = m.fetch_candidates()
        self.assertEqual(len(candidates), 1, "应只接受通过安全校验的那一行")
        self.assertEqual(candidates[0]["ip"], "203.0.113.7")
        state = m.get_state()
        self.assertEqual(state.get("last_fetch_status"), "cached")
        self.assertEqual(state.get("last_fetch_source"), "local_cache")

    def test_mirror_urls_are_attempted(self):
        tried = []
        orig = m.MIRROR_URLS
        m.MIRROR_URLS = ["https://mirror.example/vpngate.csv"]

        def fake_fetch(url, use_ssl_verify=True):
            tried.append(url)
            raise RuntimeError("blocked")

        m.fetch_api_text = fake_fetch
        try:
            m.fetch_candidates()
        finally:
            m.MIRROR_URLS = orig
        self.assertIn("https://mirror.example/vpngate.csv", tried)
        self.assertTrue(any("vpngate.net" in u for u in tried), "官方 API 应排在镜像之前")


if __name__ == "__main__":
    unittest.main()
