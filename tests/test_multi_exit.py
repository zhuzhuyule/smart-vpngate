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


if __name__ == "__main__":
    unittest.main()
