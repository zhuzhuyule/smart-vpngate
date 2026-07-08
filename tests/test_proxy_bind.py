# tests/test_proxy_bind.py
import inspect, unittest
import proxy_server as ps


class TestProxyDeviceParam(unittest.TestCase):
    def test_start_accepts_tun_dev(self):
        sig = inspect.signature(ps.start_proxy_server)
        self.assertIn("tun_dev", sig.parameters)

    def test_create_connection_accepts_tun_dev(self):
        sig = inspect.signature(ps.create_connection)
        self.assertIn("tun_dev", sig.parameters)


if __name__ == "__main__":
    unittest.main()
