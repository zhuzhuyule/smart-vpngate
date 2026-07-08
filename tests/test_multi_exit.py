# tests/test_multi_exit.py
import os, tempfile, unittest

os.environ.setdefault("VPNGATE_DATA_DIR", tempfile.mkdtemp(prefix="vgt_test_"))
import vpngate_manager as vm


class TestExitResources(unittest.TestCase):
    def test_default_derivation(self):
        r0 = vm.exit_resources(0)
        self.assertEqual(r0["exit_id"], 0)
        self.assertEqual(r0["proxy_port"], vm.BASE_PROXY_PORT)
        self.assertEqual(r0["tun_dev"], "svtun0")
        self.assertEqual(r0["route_table"], 100)

    def test_offsets(self):
        r2 = vm.exit_resources(2)
        self.assertEqual(r2["proxy_port"], vm.BASE_PROXY_PORT + 2)
        self.assertEqual(r2["tun_dev"], "svtun2")
        self.assertEqual(r2["route_table"], 102)

    def test_custom_prefix(self):
        r1 = vm.exit_resources(1, tun_prefix="wgx")
        self.assertEqual(r1["tun_dev"], "wgx1")


class TestConfigMigration(unittest.TestCase):
    def test_fresh_config_gets_default_slots(self):
        cfg = {}
        out = vm.migrate_legacy_exits(cfg, slots=3)
        self.assertEqual(len(out["exits"]), 3)
        self.assertEqual(out["exits"][0]["mode"], "auto")
        self.assertEqual(out["exits"][0]["routing_ip_type"], "all")
        self.assertFalse(out["exits"][0]["region_fail_fallback"])

    def test_legacy_fixed_region_migrates_to_exit0(self):
        cfg = {"routing_mode": "fixed_region", "force_country": "Japan",
               "routing_ip_type": "residential", "region_fail_fallback": True}
        out = vm.migrate_legacy_exits(cfg, slots=3)
        self.assertEqual(out["exits"][0]["mode"], "fixed_region")
        self.assertEqual(out["exits"][0]["force_country"], "Japan")
        self.assertEqual(out["exits"][0]["routing_ip_type"], "residential")
        self.assertTrue(out["exits"][0]["region_fail_fallback"])
        self.assertEqual(out["exits"][1]["mode"], "auto")

    def test_legacy_fixed_ip_downgrades_to_auto(self):
        cfg = {"routing_mode": "fixed_ip", "fixed_node_id": "x"}
        out = vm.migrate_legacy_exits(cfg, slots=3)
        self.assertEqual(out["exits"][0]["mode"], "auto")

    def test_existing_exits_are_kept(self):
        cfg = {"exits": [{"mode": "fixed_region", "force_country": "Korea",
                          "routing_ip_type": "all", "region_fail_fallback": False}]}
        out = vm.migrate_legacy_exits(cfg, slots=3)
        self.assertEqual(out["exits"][0]["force_country"], "Korea")
        self.assertEqual(len(out["exits"]), 3)


if __name__ == "__main__":
    unittest.main()
