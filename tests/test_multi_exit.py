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


class TestExitSelection(unittest.TestCase):
    def _nodes(self):
        return [
            {"id": "jp1", "country": "Japan", "probe_status": "available", "ip_type": "residential", "active_exit": None},
            {"id": "jp2", "country": "Japan", "probe_status": "available", "ip_type": "residential", "active_exit": None},
            {"id": "us1", "country": "United States", "probe_status": "available", "ip_type": "residential", "active_exit": None},
        ]

    def test_view_maps_exit_cfg(self):
        v = vm.exit_routing_view({"mode": "fixed_region", "force_country": "Japan",
                                  "routing_ip_type": "residential", "region_fail_fallback": True})
        self.assertEqual(v["routing_mode"], "fixed_region")
        self.assertEqual(v["force_country"], "Japan")
        self.assertTrue(v["region_fail_fallback"])

    def test_two_japan_exits_get_different_nodes(self):
        nodes = self._nodes()
        cfg = {"mode": "fixed_region", "force_country": "Japan",
               "routing_ip_type": "all", "region_fail_fallback": False}
        n0 = vm.select_exit_node(nodes, cfg, exit_id=0, taken={})
        self.assertEqual(n0["country"], "Japan")
        n1 = vm.select_exit_node(nodes, cfg, exit_id=1, taken={n0["id"]: 0})
        self.assertEqual(n1["country"], "Japan")
        self.assertNotEqual(n1["id"], n0["id"])

    def test_no_free_node_returns_none(self):
        nodes = self._nodes()
        cfg = {"mode": "fixed_region", "force_country": "Japan",
               "routing_ip_type": "all", "region_fail_fallback": False}
        taken = {"jp1": 0, "jp2": 1}
        self.assertIsNone(vm.select_exit_node(nodes, cfg, exit_id=2, taken=taken))

    def test_fallback_crosses_country_when_enabled(self):
        nodes = self._nodes()
        cfg = {"mode": "fixed_region", "force_country": "Japan",
               "routing_ip_type": "all", "region_fail_fallback": True}
        taken = {"jp1": 0, "jp2": 1}
        picked = vm.select_exit_node(nodes, cfg, exit_id=2, taken=taken)
        self.assertIsNotNone(picked)
        self.assertEqual(picked["id"], "us1")


class TestLoadConfigExits(unittest.TestCase):
    def setUp(self):
        import importlib, tempfile
        os.environ["VPNGATE_DATA_DIR"] = tempfile.mkdtemp(prefix="vgt_cfg_")
        importlib.reload(vm)

    def test_fresh_load_has_exits(self):
        cfg = vm.load_ui_config()
        self.assertIn("exits", cfg)
        self.assertEqual(len(cfg["exits"]), vm.DEFAULT_EXIT_COUNT)

    def test_tun_prefix_default(self):
        cfg = vm.load_ui_config()
        self.assertIn("tun_prefix", cfg)
        self.assertEqual(cfg["tun_prefix"], "svtun")


class TestExitRuntime(unittest.TestCase):
    def test_runtime_initialized_per_exit(self):
        rt = vm.get_exit_runtime(0)
        self.assertIn("lock", rt)
        self.assertIsNone(rt["process"])
        self.assertEqual(rt["node_id"], "")

    def test_set_and_read_exit_state(self):
        vm.set_exit_state(1, active_node_id="us1", proxy_ok=True, latency=42)
        st = vm.get_state()
        self.assertEqual(st["exits"][1]["active_node_id"], "us1")
        self.assertTrue(st["exits"][1]["proxy_ok"])
        self.assertEqual(st["exits"][1]["latency"], 42)


class TestActiveExitMutex(unittest.TestCase):
    def test_taken_map_from_nodes(self):
        nodes = [
            {"id": "a", "active_exit": 0},
            {"id": "b", "active_exit": None},
            {"id": "c", "active_exit": 2},
        ]
        self.assertEqual(vm.taken_exits_map(nodes), {"a": 0, "c": 2})

    def test_legacy_active_bool_maps_to_exit0(self):
        nodes = [{"id": "a", "active": True}, {"id": "b", "active": False}]
        self.assertEqual(vm.taken_exits_map(nodes).get("a"), 0)

    def test_bool_active_exit_is_ignored(self):
        # active_exit 不应被误当作 int(bool 是 int 子类)
        nodes = [{"id": "a", "active_exit": True}]
        self.assertEqual(vm.taken_exits_map(nodes), {})

    def test_accessor_mirrors_exit0_to_globals(self):
        vm.set_exit_node_id(0, "n0")
        self.assertEqual(vm.active_openvpn_node_id, "n0")
        vm.set_exit_node_id(0, "")
        # 非 0 出口不镜像全局
        vm.set_exit_node_id(1, "n1")
        self.assertEqual(vm.get_exit_runtime(1)["node_id"], "n1")
        self.assertEqual(vm.active_openvpn_node_id, "")


if __name__ == "__main__":
    unittest.main()
