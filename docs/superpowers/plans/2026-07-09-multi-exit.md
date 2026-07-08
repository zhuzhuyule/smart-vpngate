# 多出口(统一 N 出口模型)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `vpngate_manager.py` 的"唯一活动出口"重构为支持 N 个并发活动出口(默认 3),每个出口锁定/自动选一个国家、对应一个本地代理端口,统一在一个 Web 面板管理。

**Architecture:** 单文件引擎内部把 5 个单数活动状态全局变量(`active_openvpn_process`/`active_openvpn_node_id`/`is_connecting`/`last_active_latency`/`last_active_ping_time`)重构为按 `exit_id` 索引的运行时结构;资源(端口/设备/路由表)按 `exit_id` 派生;节点池共享,用节点上的 `active_exit` 字段做互斥;三个后台线程从"操作单一连接"改为"遍历所有出口";代理层每出口起一个绑定专属 `svtun{id}` 设备的实例。单出口 = N=1 特例。

**Tech Stack:** Python 3.11 标准库(http.server / socket / subprocess / threading);OpenVPN + iproute2 策略路由;stdlib `unittest`(零依赖,VPS 上也能跑)。

**参考设计:** `docs/superpowers/specs/2026-07-09-multi-exit-design.md`

**测试约定:**
- 测试放 `tests/`,文件名 `test_*.py`(`.gitignore` 已加 `!tests/**` 例外)。
- 运行:`python3 -m unittest discover -s tests -v`。
- 每个测试在 `setUp` 里设 `os.environ["VPNGATE_DATA_DIR"]` 指向临时目录,避免污染真实数据;导入 `vpngate_manager` 只加载模块(服务器由 `if __name__ == "__main__"` 守护,不会启动)。
- 有状态逻辑用 monkeypatch(`vm.read_nodes = lambda: [...]`)注入,已验证可行。

---

## Phase 0 — 纯函数地基(离线可单测,不改运行路径)

### Task 1: 资源派生常量与 `exit_resources`

**Files:**
- Modify: `vpngate_manager.py`(顶部常量区,约 :107-126 附近)
- Test: `tests/test_multi_exit.py`(新建)

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_multi_exit -v`
Expected: FAIL,`AttributeError: module 'vpngate_manager' has no attribute 'exit_resources'`

- [ ] **Step 3: 实现常量与函数**

在 `vpngate_manager.py` 顶部常量区(`LOCAL_PROXY_PORT` 定义之后)加入:

```python
TUN_PREFIX = os.environ.get("TUN_PREFIX", "svtun")   # 出口设备名前缀,避免与用户自有 tun0 冲突
TEST_TUN_PREFIX = "svtst"                             # 测试隧道前缀,与出口设备零重叠
TABLE_BASE = 100                                      # 出口路由表基号:exit_id -> 100 + id
BASE_PROXY_PORT = LOCAL_PROXY_PORT                    # 出口代理基端口:exit_id -> BASE + id
DEFAULT_EXIT_COUNT = env_int("EXIT_COUNT", 3, 1, 8)   # 出口槽数量,可配


def exit_resources(exit_id: int, tun_prefix: str = TUN_PREFIX) -> dict[str, Any]:
    """按 exit_id 派生固定资源(端口/设备/路由表)。"""
    return {
        "exit_id": exit_id,
        "proxy_port": BASE_PROXY_PORT + exit_id,
        "tun_dev": f"{tun_prefix}{exit_id}",
        "route_table": TABLE_BASE + exit_id,
    }
```

> 注:`env_int` 已在文件中定义(用于 `UI_PORT`),复用它。

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_multi_exit -v`
Expected: PASS(3 tests)

- [ ] **Step 5: 提交**

```bash
git add vpngate_manager.py tests/test_multi_exit.py
git commit -m "feat(multi-exit): add exit resource derivation constants + exit_resources()"
```

---

### Task 2: 配置迁移 `migrate_legacy_exits`

**Files:**
- Modify: `vpngate_manager.py`(在 `load_ui_config` 之前加纯函数)
- Test: `tests/test_multi_exit.py`

- [ ] **Step 1: 写失败测试**(追加到 `tests/test_multi_exit.py`)

```python
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
        # 其余槽为默认 auto
        self.assertEqual(out["exits"][1]["mode"], "auto")

    def test_legacy_fixed_ip_downgrades_to_auto(self):
        cfg = {"routing_mode": "fixed_ip", "fixed_node_id": "x"}
        out = vm.migrate_legacy_exits(cfg, slots=3)
        self.assertEqual(out["exits"][0]["mode"], "auto")

    def test_existing_exits_are_kept(self):
        cfg = {"exits": [{"mode": "fixed_region", "force_country": "Korea",
                          "routing_ip_type": "all", "region_fail_fallback": False}]}
        out = vm.migrate_legacy_exits(cfg, slots=3)
        # 已有 exits 不被覆盖,但补齐到 slots 数量
        self.assertEqual(out["exits"][0]["force_country"], "Korea")
        self.assertEqual(len(out["exits"]), 3)
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_multi_exit -v`
Expected: FAIL,`AttributeError: ... 'migrate_legacy_exits'`

- [ ] **Step 3: 实现**

在 `load_ui_config` 定义之前加入:

```python
def default_exit_config() -> dict[str, Any]:
    return {"mode": "auto", "force_country": "", "routing_ip_type": "all", "region_fail_fallback": False}


def migrate_legacy_exits(cfg: dict[str, Any], slots: int = DEFAULT_EXIT_COUNT) -> dict[str, Any]:
    """确保 cfg['exits'] 存在且长度为 slots。
    无 exits 时:从旧单出口字段迁移出 exits[0](fixed_ip/favorites 降级为 auto)。
    有 exits 时:保留,并补齐/截断到 slots 长度。
    """
    exits = cfg.get("exits")
    if not isinstance(exits, list) or not exits:
        mode = cfg.get("routing_mode", "auto")
        if mode not in ("auto", "fixed_region"):
            if mode in ("fixed_ip", "favorites"):
                log_to_json("INFO", "Migration", f"旧路由模式 {mode} 不支持多出口,已降级为 auto")
            mode = "auto"
        exits = [{
            "mode": mode,
            "force_country": cfg.get("force_country", ""),
            "routing_ip_type": cfg.get("routing_ip_type", "all"),
            "region_fail_fallback": bool(cfg.get("region_fail_fallback", False)),
        }]
    # 归一化每一项 + 补齐/截断
    normalized: list[dict[str, Any]] = []
    for i in range(slots):
        src = exits[i] if i < len(exits) else default_exit_config()
        item = default_exit_config()
        item["mode"] = "fixed_region" if src.get("mode") == "fixed_region" else "auto"
        item["force_country"] = str(src.get("force_country") or "")
        rit = src.get("routing_ip_type", "all")
        item["routing_ip_type"] = rit if rit in ("all", "residential", "hosting") else "all"
        item["region_fail_fallback"] = bool(src.get("region_fail_fallback", False))
        normalized.append(item)
    cfg["exits"] = normalized
    return cfg
```

> 注:`log_to_json` 已在文件中定义。若测试环境下它写日志文件失败,应被其内部 try/except 吞掉;若未吞,测试里可 monkeypatch `vm.log_to_json = lambda *a, **k: None`。

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_multi_exit -v`
Expected: PASS(全部)

- [ ] **Step 5: 提交**

```bash
git add vpngate_manager.py tests/test_multi_exit.py
git commit -m "feat(multi-exit): add legacy->exits config migration"
```

---

### Task 3: 出口路由视图 + 互斥选点

**Files:**
- Modify: `vpngate_manager.py`(在 `filter_switch_candidates` 之后)
- Test: `tests/test_multi_exit.py`

- [ ] **Step 1: 写失败测试**(追加)

```python
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
        # 出口 0 占用 n0 后,出口 1 必须拿到另一个日本节点
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
        taken = {"jp1": 0, "jp2": 1}  # 日本都被占,允许兜底
        picked = vm.select_exit_node(nodes, cfg, exit_id=2, taken=taken)
        self.assertIsNotNone(picked)
        self.assertEqual(picked["id"], "us1")
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_multi_exit -v`
Expected: FAIL,`... 'exit_routing_view'`

- [ ] **Step 3: 实现**

在 `filter_switch_candidates` 之后加入:

```python
def exit_routing_view(exit_cfg: dict[str, Any]) -> dict[str, Any]:
    """把每出口配置映射成 filter_switch_candidates 认识的 routing 视图。"""
    return {
        "routing_mode": "fixed_region" if exit_cfg.get("mode") == "fixed_region" else "auto",
        "force_country": exit_cfg.get("force_country", ""),
        "routing_ip_type": exit_cfg.get("routing_ip_type", "all"),
        "region_fail_fallback": bool(exit_cfg.get("region_fail_fallback", False)),
    }


def select_exit_node(
    nodes: list[dict[str, Any]],
    exit_cfg: dict[str, Any],
    exit_id: int,
    taken: dict[str, int],
) -> dict[str, Any] | None:
    """为某出口从共享池选一个"可用且未被别的出口占用"的最佳节点。
    taken: node_id -> 占用它的 exit_id。
    """
    free = [
        n for n in nodes
        if n.get("probe_status") == "available"
        and taken.get(str(n.get("id"))) in (None, exit_id)
    ]
    view = exit_routing_view(exit_cfg)
    candidates, _ = filter_switch_candidates(free, view)
    candidates.sort(key=lambda n: (parse_int(n.get("latency_ms")) or 999999, -parse_int(n.get("score"))))
    return candidates[0] if candidates else None
```

> `filter_switch_candidates`、`parse_int` 已存在。`region_fail_fallback` 的跨国兜底逻辑内置于 `filter_switch_candidates`(锁定国家无候选且开关开时放宽国家);但注意 `region_fallback_enabled` 内部读的是 `routing_mode=="fixed_region"`,`exit_routing_view` 已保证这一点。

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_multi_exit -v`
Expected: PASS(全部)

- [ ] **Step 5: 提交**

```bash
git add vpngate_manager.py tests/test_multi_exit.py
git commit -m "feat(multi-exit): add per-exit routing view + mutex node selection"
```

**检查点 A:** Phase 0 完成。所有纯函数逻辑有单测覆盖,运行路径尚未改动,现有单出口功能不受影响。运行全套:`python3 -m unittest discover -s tests -v`,应全绿;`python3 -m py_compile vpngate_manager.py` 应通过。

---

## Phase 1 — 配置与运行时状态模型

### Task 4: `load_ui_config` 接入 exits + 默认三槽

**Files:**
- Modify: `vpngate_manager.py` `load_ui_config`(约 :215-260)、升级 key 列表(:239)
- Test: `tests/test_multi_exit.py`

- [ ] **Step 1: 写失败测试**(追加)

```python
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
        self.assertEqual(cfg.get("tun_prefix", "svtun"), "svtun")
```

> 注:`setUp` reload 让 `DATA_DIR` 指向新临时目录。若 reload 带来副作用,替代方案是直接删掉 `DATA_DIR/ui_auth.json` 后调用。

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_multi_exit.TestLoadConfigExits -v`
Expected: FAIL,`KeyError/AssertionError: 'exits' not in cfg`

- [ ] **Step 3: 实现**

在 `load_ui_config` 的默认 `config` 字典(:217-232)加入 `"exits"` 与 `"tun_prefix"`:

```python
            "region_fail_fallback": False,
            "tun_prefix": TUN_PREFIX,
            "exits": [],
            "discovery_countries": []
```

在升级 key 列表(:239)追加 `"tun_prefix"`, `"exits"`:

```python
                for key in ["host", "port", "proxy_port", "routing_mode", "force_country", "routing_ip_type", "connection_enabled", "fixed_node_id", "favorite_node_ids", "fav_fail_fallback", "region_fail_fallback", "tun_prefix", "exits", "discovery_countries"]:
```

在 `load_ui_config` 返回 `config` 之前(写回 auth_file 之后或之前均可,但要在 return 前),调用迁移:

```python
        config = migrate_legacy_exits(config, slots=DEFAULT_EXIT_COUNT)
```

> 放在 `if not config.get("username")` 等补齐逻辑之后、`return config` 之前。确保每次加载后 `exits` 恒为长度 `DEFAULT_EXIT_COUNT`。

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_multi_exit.TestLoadConfigExits -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add vpngate_manager.py tests/test_multi_exit.py
git commit -m "feat(multi-exit): load_ui_config exposes exits[] + tun_prefix with migration"
```

---

### Task 5: 出口运行时结构 + state.json 出口数组

**Files:**
- Modify: `vpngate_manager.py` 全局变量区(:136-140)、`get_state`(:354+)
- Test: `tests/test_multi_exit.py`

- [ ] **Step 1: 写失败测试**(追加)

```python
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
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_multi_exit.TestExitRuntime -v`
Expected: FAIL,`... 'get_exit_runtime'`

- [ ] **Step 3: 实现**

在全局变量区(保留旧的 `active_openvpn_*` 暂不删除,以免中途破坏未改造的引用)新增:

```python
# 每出口运行时(内存,不落盘的部分)
exit_runtime: dict[int, dict[str, Any]] = {}
exit_runtime_lock = threading.Lock()


def get_exit_runtime(exit_id: int) -> dict[str, Any]:
    with exit_runtime_lock:
        rt = exit_runtime.get(exit_id)
        if rt is None:
            rt = {"process": None, "node_id": "", "is_connecting": False,
                  "lock": threading.RLock(), "latency": 0, "last_ping_time": 0.0}
            exit_runtime[exit_id] = rt
        return rt
```

新增按出口读写 state 的辅助(放在 `set_state` 附近):

```python
def default_exit_state() -> dict[str, Any]:
    return {"active_node_id": "", "is_connecting": False, "latency": 0,
            "proxy_ok": False, "proxy_ip": "-", "proxy_latency_ms": 0,
            "proxy_error": "", "last_message": ""}


def set_exit_state(exit_id: int, **updates: Any) -> None:
    with lock:
        state = read_json(STATE_FILE, {})
        exits = state.get("exits")
        if not isinstance(exits, list):
            exits = []
        while len(exits) <= exit_id:
            exits.append(default_exit_state())
        exits[exit_id].update(updates)
        state["exits"] = exits
        write_json(STATE_FILE, state)
```

在 `get_state`(:354)里,注入每出口的运行时快照(node_id/is_connecting 来自内存 runtime,其余来自落盘 state):

```python
    # 多出口:合成 exits 状态数组
    ui_cfg_exits = ui_cfg.get("exits", []) if isinstance(ui_cfg.get("exits"), list) else []
    persisted_exits = state.get("exits", [])
    merged_exits = []
    for i in range(len(ui_cfg_exits)):
        base = persisted_exits[i] if i < len(persisted_exits) and isinstance(persisted_exits[i], dict) else default_exit_state()
        rt = get_exit_runtime(i)
        res = exit_resources(i, ui_cfg.get("tun_prefix", TUN_PREFIX))
        base = dict(base)
        base["active_node_id"] = rt["node_id"]
        base["is_connecting"] = rt["is_connecting"]
        base["proxy_port"] = res["proxy_port"]
        base["tun_dev"] = res["tun_dev"]
        base["config"] = ui_cfg_exits[i]
        merged_exits.append(base)
    state["exits"] = merged_exits
```

> 放在 `get_state` 已有的 `ui_cfg = load_ui_config()` 之后(该行在 :371 附近)。注意 `get_state` 里 `ui_cfg` 变量已存在,复用它。

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_multi_exit.TestExitRuntime -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add vpngate_manager.py tests/test_multi_exit.py
git commit -m "feat(multi-exit): per-exit runtime struct + set_exit_state/get_state exits[]"
```

**检查点 B:** Phase 1 完成。配置与状态模型已支持出口数组,但连接/代理/调度仍走旧单出口路径(旧全局变量仍在)。`python3 -m unittest discover -s tests -v` 全绿;启动服务(`sudo python3 vpngate_manager.py`,非 root 环境仅验证不崩)`/api/nodes` 的 `state.exits` 应返回三个出口的配置与资源。

---

## Phase 2 — 管道参数化(保持单出口行为不破)

### Task 6: 策略路由表号参数化

**Files:**
- Modify: `vpngate_manager.py` `setup_policy_routing`(:1099)、`cleanup_policy_routing`(:1131)

- [ ] **Step 1: 改造签名与实现**

`setup_policy_routing(interface="tun0")` → `setup_policy_routing(interface="tun0", table=TABLE_BASE)`,把函数体内所有 `"100"` 字面量替换为 `str(table)`;`cleanup_policy_routing()` → `cleanup_policy_routing(table=TABLE_BASE)`,同样替换。

具体:把 `["ip", "rule", "del", "table", "100"]`、`["ip", "route", "flush", "table", "100"]`、`["ip", "route", "add", "default", "dev", interface, "table", "100"]`、`["ip", "rule", "add", "oif", interface, "table", "100"]` 中的 `"100"` 全改为 `str(table)`。日志里的 `table 100` 改为 `table {table}`。

- [ ] **Step 2: 编译校验**

Run: `python3 -m py_compile vpngate_manager.py`
Expected: 无输出(通过)

- [ ] **Step 3: 验证旧调用点仍工作**

`connect_node`(:1709 附近)调用 `setup_policy_routing("tun0")` 保持不变(默认 table=100,行为等价)。确认没有其他调用点因签名变化报错:`grep -n "setup_policy_routing\|cleanup_policy_routing" vpngate_manager.py`,确认所有调用都兼容默认参数。

- [ ] **Step 4: 提交**

```bash
git add vpngate_manager.py
git commit -m "refactor(multi-exit): parameterize route table number in policy routing"
```

---

### Task 7: 代理层 `tun_dev` 参数穿链

**Files:**
- Modify: `proxy_server.py` `dns_query_over_tun0`(:112)、`resolve_dns_over_tun0`(:181)、`create_connection`(:194-207)、`proxy_client`(:378)、`http_client`(:297)、`socks5_client`(:236)、`start_proxy_server`(:395)
- Test: `tests/test_proxy_bind.py`(新建,轻量)

- [ ] **Step 1: 写失败测试**(验证签名支持设备参数,不实际绑定)

```python
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
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_proxy_bind -v`
Expected: FAIL,`'tun_dev' not in parameters`

- [ ] **Step 3: 实现穿链**

把 `create_connection(address, timeout=20)` 改为 `create_connection(address, timeout=20, tun_dev="tun0")`,函数体内 `b"tun0"` 改为 `tun_dev.encode()`,错误信息里的 `tun0` 改为 `{tun_dev}`;`resolve_dns_over_tun0(host, ...)`→ 加 `tun_dev="tun0"` 参数并传给 `dns_query_over_tun0`;`dns_query_over_tun0(...)` 里 `SO_BINDTODEVICE, b"tun0"` 改 `tun_dev.encode()`。

调用链传递:`start_proxy_server(host, port, tun_dev="tun0")` → 在每个新连接的 handler 线程里把 `tun_dev` 传给 `proxy_client(client, address, tun_dev)` → 传给 `http_client`/`socks5_client` → 传给 `create_connection(..., tun_dev=tun_dev)` 与 `resolve_dns_over_tun0(host, tun_dev=tun_dev)`。

> 因 handler 是闭包/线程函数,最简做法:在 `start_proxy_server` 里用闭包捕获 `tun_dev`,或把 `tun_dev` 作为 `proxy_client` 的参数逐层传下去。逐层传参更显式,优先。

- [ ] **Step 4: 运行,确认通过**

Run: `python3 -m unittest tests.test_proxy_bind -v`
Expected: PASS

- [ ] **Step 5: 验证向后兼容**

`vpngate_manager.py` 中启动代理处(:5969)`start_proxy_server(LOCAL_PROXY_HOST, LOCAL_PROXY_PORT)` 暂不改(默认 tun_dev="tun0",行为等价)。`python3 -m py_compile proxy_server.py` 通过。

- [ ] **Step 6: 提交**

```bash
git add proxy_server.py tests/test_proxy_bind.py
git commit -m "refactor(multi-exit): thread tun_dev through proxy server bind chain"
```

---

### Task 8: 测试隧道前缀改 `svtst`

**Files:**
- Modify: `vpngate_manager.py` 测试隧道命名处(:1403 `dev=f"tun{idx}"`、:1494 `dev_name = f"tun{tun_idx}"`)

- [ ] **Step 1: 改设备名前缀**

把测试/探测隧道的 `f"tun{idx}"` / `f"tun{tun_idx}"` 改为 `f"{TEST_TUN_PREFIX}{idx}"` / `f"{TEST_TUN_PREFIX}{tun_idx}"`。

- [ ] **Step 2: 编译校验**

Run: `python3 -m py_compile vpngate_manager.py`
Expected: 通过

- [ ] **Step 3: 确认无残留 `tun{` 拼接指向测试隧道**

Run: `grep -n 'f"tun{' vpngate_manager.py`
Expected: 无输出(测试隧道已全部改前缀;出口设备将在 Phase 3 用 `exit_resources` 生成)

- [ ] **Step 4: 提交**

```bash
git add vpngate_manager.py
git commit -m "refactor(multi-exit): rename probe tunnels to svtst prefix (isolate from exits)"
```

**检查点 C:** Phase 2 完成。所有底层管道(路由表/代理设备/测试隧道)已参数化,但仍以 tun0/table100 的默认值运行,单出口行为完全不变。此时应在真机快速冒烟一次(见检查点 E 的简化版):启动服务,确认 exit 0 仍能正常连接、代理出口 IP 正确。`python3 -m unittest discover -s tests -v` 全绿。

---

## Phase 3 — 连接/停止/切换 按出口

### Task 9: `connect_node` / 停止 支持 exit_id + `active_exit` 互斥

**Files:**
- Modify: `vpngate_manager.py` `connect_node`(:1633)、`stop_active_openvpn`(:1139)、节点合并逻辑(`maintain_valid_nodes` 内 `active` 字段处理)
- Test: `tests/test_multi_exit.py`

- [ ] **Step 1: 写失败测试**(验证 `active_exit` 读写辅助)

```python
class TestActiveExit(unittest.TestCase):
    def test_taken_map_from_nodes(self):
        nodes = [
            {"id": "a", "active_exit": 0},
            {"id": "b", "active_exit": None},
            {"id": "c", "active_exit": 2},
        ]
        taken = vm.taken_exits_map(nodes)
        self.assertEqual(taken, {"a": 0, "c": 2})

    def test_legacy_active_bool_maps_to_exit0(self):
        nodes = [{"id": "a", "active": True}, {"id": "b", "active": False}]
        taken = vm.taken_exits_map(nodes)
        self.assertEqual(taken.get("a"), 0)
```

- [ ] **Step 2: 运行,确认失败**

Run: `python3 -m unittest tests.test_multi_exit.TestActiveExit -v`
Expected: FAIL,`... 'taken_exits_map'`

- [ ] **Step 3: 实现辅助 + 改造 connect/stop**

新增:

```python
def taken_exits_map(nodes: list[dict[str, Any]]) -> dict[str, int]:
    """从节点列表构造 node_id -> 占用 exit_id 的映射。兼容旧 active 布尔(视为 exit 0)。"""
    taken: dict[str, int] = {}
    for n in nodes:
        nid = str(n.get("id") or "")
        if not nid:
            continue
        ae = n.get("active_exit")
        if isinstance(ae, int):
            taken[nid] = ae
        elif ae is None and n.get("active"):
            taken[nid] = 0
    return taken


def set_node_active_exit(node_id: str, exit_id: int | None) -> None:
    with lock:
        nodes = read_nodes()
        for n in nodes:
            if str(n.get("id")) == str(node_id):
                n["active_exit"] = exit_id
                n["active"] = exit_id is not None  # 兼容旧 UI 读 active
        write_json(NODES_FILE, nodes)
```

`connect_node(node_id)` → `connect_node(node_id, exit_id=0)`:函数内所有对全局 `active_openvpn_process`/`active_openvpn_node_id`/`is_connecting` 的读写改为操作 `get_exit_runtime(exit_id)` 的对应字段;`setup_policy_routing("tun0")` 改为 `setup_policy_routing(res["tun_dev"], res["route_table"])`(`res = exit_resources(exit_id, load_ui_config().get("tun_prefix", TUN_PREFIX))`);`run_openvpn_until_ready(..., dev="tun0")` 改为 `dev=res["tun_dev"]`;成功后 `set_node_active_exit(node_id, exit_id)` 与 `set_exit_state(exit_id, active_node_id=node_id, ...)`;`check_proxy_health()` 调用改为按出口端口/设备(见 Task 12 一并处理,本任务先用 exit 0 默认值保证不破)。

`stop_active_openvpn()` → `stop_exit(exit_id=0)`:操作对应出口的 runtime process,`cleanup_policy_routing(res["route_table"])`,释放该出口占用的节点(`set_node_active_exit(old_node_id, None)`)。保留一个 `stop_active_openvpn()` 薄封装 = `stop_exit(0)` 供未改造调用点过渡。

`maintain_valid_nodes` 内合并节点时,把保留字段列表加入 `"active_exit"`,并把"活动节点"判断从 `active_openvpn_node_id` 改为"任一出口的 runtime.node_id"(过渡期可先保留旧逻辑 + 附加,Phase 4 统一)。

- [ ] **Step 4: 运行,确认通过 + 编译**

Run: `python3 -m unittest tests.test_multi_exit -v && python3 -m py_compile vpngate_manager.py`
Expected: PASS + 编译通过

- [ ] **Step 5: 提交**

```bash
git add vpngate_manager.py tests/test_multi_exit.py
git commit -m "feat(multi-exit): connect_node/stop_exit take exit_id; active_exit mutex on nodes"
```

---

### Task 10: `auto_switch_node` 按出口切换

**Files:**
- Modify: `vpngate_manager.py` `auto_switch_node`(:1566)

- [ ] **Step 1: 改造签名与选点**

`auto_switch_node(attempt=0)` → `auto_switch_node(exit_id=0, attempt=0)`。把选点逻辑改为:

```python
    ui_cfg = load_ui_config()
    exit_cfg = ui_cfg["exits"][exit_id]
    with lock:
        nodes = read_nodes()
        taken = taken_exits_map(nodes)
        # 释放自己旧占用,避免把自己算进"被占"
        rt = get_exit_runtime(exit_id)
        taken.pop(str(rt["node_id"]), None)
        next_node = select_exit_node(nodes, exit_cfg, exit_id, taken)
    if next_node:
        connect_node(next_node["id"], exit_id)
        ...
    else:
        # 该出口无候选:清理该出口 + 后台补齐(不影响其他出口)
        ...
```

保留 `connection_enabled` 检查;把日志/`set_state` 改为 `set_exit_state(exit_id, ...)`;递归重试 `auto_switch_node(exit_id, attempt+1)`;后台补齐线程只针对该出口。移除对全局单出口路径的假设(如 `routing_mode == "fixed_ip"` 早退——多出口无 fixed_ip 模式,可删该分支)。

- [ ] **Step 2: 编译 + 单测回归**

Run: `python3 -m py_compile vpngate_manager.py && python3 -m unittest discover -s tests -v`
Expected: 通过 + 全绿

- [ ] **Step 3: 提交**

```bash
git add vpngate_manager.py
git commit -m "feat(multi-exit): auto_switch_node switches a specific exit using mutex selection"
```

**检查点 D:** Phase 3 完成。连接/停止/切换均可按 exit_id 操作,节点互斥生效。此时单出口(exit 0)路径仍应端到端可用。真机快速验证:手动触发 exit 0 连接,确认 `ip link` 出现 `svtun0`、`ip rule` 有 table 100、`curl -x http://127.0.0.1:7928` 出口 IP 正确。

---

## Phase 4 — 后台线程遍历出口 + N 代理线程

### Task 11: `maintain_valid_nodes` 测国家并集 + 逐出口连接

**Files:**
- Modify: `vpngate_manager.py` `maintain_valid_nodes`(:1764)

- [ ] **Step 1: 改造**

- 快速首连候选:把 `apply_routing_filters(fast_candidates, ui_cfg, ...)` 改为"所有出口锁定国家并集"的候选(遍历 `ui_cfg["exits"]`,对每个出口用 `exit_routing_view` 过滤后取并集去重)。
- 测试完成后:遍历每个出口 `for exit_id in range(len(ui_cfg["exits"]))`,若该出口 runtime 未连接则 `auto_switch_node(exit_id)`;选点用共享 `taken_exits_map` 保证互斥(注意每次连接后 taken 更新,顺序处理)。
- 返回消息汇总各出口连接结果。

新增小工具:

```python
def union_country_candidates(nodes, ui_cfg):
    seen, out = set(), []
    for ex in ui_cfg.get("exits", []):
        cands, _ = filter_switch_candidates(nodes, exit_routing_view(ex), include_unknown_ip_type=True)
        for n in cands:
            if n["id"] not in seen:
                seen.add(n["id"]); out.append(n)
    return out
```

- [ ] **Step 2: 编译 + 单测**

Run: `python3 -m py_compile vpngate_manager.py && python3 -m unittest discover -s tests -v`
Expected: 通过 + 全绿

- [ ] **Step 3: 提交**

```bash
git add vpngate_manager.py
git commit -m "feat(multi-exit): maintenance tests union of exit countries, connects each exit"
```

---

### Task 12: 健康检查 / 延迟线程遍历出口 + `check_proxy_health` 按出口

**Files:**
- Modify: `vpngate_manager.py` `check_proxy_health`(:5039)、`background_proxy_checker`(:5167)、`active_node_pinger`(:5223)

- [ ] **Step 1: 改造 `check_proxy_health`**

`check_proxy_health()` → `check_proxy_health(exit_id=0)`:用 `res = exit_resources(exit_id, ...)` 得到该出口端口/设备,把硬编码 `LOCAL_PROXY_PORT` 改 `res["proxy_port"]`、`/sys/class/net/tun0` 改 `/sys/class/net/{res['tun_dev']}`、curl 代理端口改 `res["proxy_port"]`。

- [ ] **Step 2: 改造两个后台线程遍历出口**

`background_proxy_checker`:外层 `while True` 内 `for exit_id in range(len(load_ui_config()["exits"]))`,对每个出口 `check_proxy_health(exit_id)`,失败则 `set_exit_state(exit_id, proxy_ok=False, ...)` + 拉黑该出口当前节点 + `set_node_active_exit(node_id, None)` + `auto_switch_node(exit_id)`;成功则 `set_exit_state(exit_id, proxy_ok=True, proxy_ip=..., ...)`。移除 fixed_ip 分支。

`active_node_pinger`:遍历出口,更新每个出口 runtime 的 latency 并 `set_exit_state(exit_id, latency=...)`。

- [ ] **Step 3: 编译 + 单测**

Run: `python3 -m py_compile vpngate_manager.py && python3 -m unittest discover -s tests -v`
Expected: 通过 + 全绿

- [ ] **Step 4: 提交**

```bash
git add vpngate_manager.py
git commit -m "feat(multi-exit): proxy health + pinger iterate all exits; check_proxy_health per exit"
```

---

### Task 13: main() 启动 N 个代理线程 + 启动清理专属前缀设备

**Files:**
- Modify: `vpngate_manager.py` 服务启动区(:5969 起代理线程处、:6014-6016 后台线程)、启动清理

- [ ] **Step 1: 启动 N 个代理线程**

把单个 `start_proxy_server(LOCAL_PROXY_HOST, LOCAL_PROXY_PORT)` 改为遍历出口:

```python
    ui_cfg = load_ui_config()
    prefix = ui_cfg.get("tun_prefix", TUN_PREFIX)
    for exit_id in range(len(ui_cfg["exits"])):
        res = exit_resources(exit_id, prefix)
        threading.Thread(
            target=proxy_server.start_proxy_server,
            args=(LOCAL_PROXY_HOST, res["proxy_port"], res["tun_dev"]),
            daemon=True,
        ).start()
```

- [ ] **Step 2: 启动清理只清专属前缀**

在启动早期(启动代理线程前)新增清理函数并调用:

```python
def cleanup_stale_exit_devices() -> None:
    """启动时清理仅属于本程序前缀(svtun*/svtst*)的残留设备与路由表,绝不碰用户 tun0。"""
    try:
        out = subprocess.run(["ip", "-o", "link"], capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return
    for line in out.splitlines():
        for pfx in (TUN_PREFIX, TEST_TUN_PREFIX):
            if f" {pfx}" in line:
                name = line.split(":")[1].strip().split("@")[0]
                if name.startswith(pfx):
                    subprocess.run(["ip", "link", "delete", name], capture_output=True, timeout=3)
    for exit_id in range(DEFAULT_EXIT_COUNT + 4):
        subprocess.run(["ip", "rule", "del", "table", str(TABLE_BASE + exit_id)], capture_output=True, timeout=2)
        subprocess.run(["ip", "route", "flush", "table", str(TABLE_BASE + exit_id)], capture_output=True, timeout=2)
```

- [ ] **Step 3: 编译 + 单测**

Run: `python3 -m py_compile vpngate_manager.py && python3 -m unittest discover -s tests -v`
Expected: 通过 + 全绿

- [ ] **Step 4: 提交**

```bash
git add vpngate_manager.py
git commit -m "feat(multi-exit): start N proxy threads + cleanup only svtun*/svtst* on boot"
```

**检查点 E(真机):** Phase 4 完成,后端多出口应完整可用。在 VPS(root+TUN)上:配置 exits 为 [日本, 美国, 韩国],重启服务,确认:①`ip link` 出现 `svtun0/1/2`;②三个端口 `curl -x http://127.0.0.1:7928/7929/7930 https://api.ipify.org` 出口 IP 分属三国;③`kill -9` 掉 svtun1 的 openvpn,只有 exit 1 切换,exit 0/2 不受影响。

---

## Phase 5 — API 与 UI

### Task 14: `/api/update_settings` 与出口配置 API

**Files:**
- Modify: `vpngate_manager.py` `/api/update_settings`(:5688)、必要时新增 `/api/update_exit`

- [ ] **Step 1: 接受 exits 数组**

在 `/api/update_settings` 的 payload 解析里,接受可选的 `exits` 数组(每项 mode/force_country/routing_ip_type/region_fail_fallback),校验后写入 `ui_cfg["exits"]`;`tun_prefix`、基端口也可在此更新(改动需重启,复用现有 restart 逻辑)。对每个变更的出口调用 `enforce_active_node_allowed_by_routing` 的多出口版本(检查该出口当前节点是否仍合规,不合规则触发该出口切换)。

保留对旧单出口字段的接受(写入 exits[0]),保证旧前端不破。

- [ ] **Step 2: 编译 + HTTP 冒烟(见 Task 16 复用)**

Run: `python3 -m py_compile vpngate_manager.py`
Expected: 通过

- [ ] **Step 3: 提交**

```bash
git add vpngate_manager.py
git commit -m "feat(multi-exit): update_settings accepts per-exit exits[] config"
```

---

### Task 15: UI 出口卡片 + 每出口设置 + 节点表占用列

**Files:**
- Modify: `vpngate_manager.py` `INDEX_HTML`(当前出口面板、设置 modal、节点表 render JS)

- [ ] **Step 1: 出口卡片区**

把单一"当前出口"面板替换为遍历 `state.exits` 渲染的 N 张卡片,每张显示:国旗+国家(或"自动")、当前节点、出口 IP、延迟、状态圆点、以及"设置"按钮(打开该出口的配置)。

- [ ] **Step 2: 每出口设置**

设置 modal 支持选择"当前编辑哪个出口",每个出口独立的 模式(自动/锁定地区)/国家下拉/IP类型/兜底开关(复用已实现的控件);全局区保留 Web 端口/密钥/拉取国家范围/tun 前缀。保存时把 `exits` 数组 POST 到 `/api/update_settings`。

- [ ] **Step 3: 节点表占用列**

`render()` 里给每行加"占用出口"标识:节点 `active_exit` 非空时显示 `出口{active_exit} · {国家}` 徽章。保留已实现的延迟列/国旗/多选筛选/单节点测试按钮。

- [ ] **Step 4: 编译校验(HTML 内嵌于字符串,py_compile 即可)**

Run: `python3 -m py_compile vpngate_manager.py`
Expected: 通过

- [ ] **Step 5: 提交**

```bash
git add vpngate_manager.py
git commit -m "feat(multi-exit): UI exit cards, per-exit settings, node occupancy badge"
```

---

## Phase 6 — 集成验证

### Task 16: 本地 HTTP 冒烟(多出口)

**Files:**
- Create: `tests/smoke_multi_exit.py`(独立脚本,非 unittest,起真实服务)

- [ ] **Step 1: 写冒烟脚本**

参照本会话已用过的模式(起服务 → 读 `ui_auth.json` → 登录 → 调 API):
- 起服务(`UI_PORT=18787 VPNGATE_DATA_DIR=<tmp>`);
- 登录;
- `GET /api/nodes` → 断言 `state.exits` 长度为 3,每个含 `proxy_port`(7928/7929/7930)、`tun_dev`(svtun0/1/2)、`config`;
- `POST /api/update_settings` 带 `exits:[{mode:fixed_region,force_country:Japan},{mode:auto},{mode:fixed_region,force_country:Korea}]` → 断言 200;
- 再 `GET /api/nodes` → 断言持久化;断言磁盘 `ui_auth.json` 的 `exits` 已更新;
- 关闭服务。

- [ ] **Step 2: 运行**

Run: `python3 tests/smoke_multi_exit.py`
Expected: `MULTI-EXIT SMOKE: ALL PASSED`

- [ ] **Step 3: 提交**

```bash
git add tests/smoke_multi_exit.py
git commit -m "test(multi-exit): HTTP smoke for exits state + per-exit config persistence"
```

---

### Task 17: 真机 VPS 验证(手动清单)

**Files:** 无(操作性验证,记录到 PR 描述)

- [ ] **Step 1: 部署**

在 VPS 上 `git pull` 到 `feat/multi-exit`,重启服务(或跑 `install.sh` 流程)。

- [ ] **Step 2: 配置三出口**

面板设 exit0=日本(锁定地区)、exit1=美国、exit2=韩国,保存。

- [ ] **Step 3: 验证隧道与出口**

```bash
ip link | grep -E 'svtun|svtst'       # 出现 svtun0/1/2
ip rule ; ip route show table 100     # 三张表 100/101/102 指向各自设备
for p in 7928 7929 7930; do curl -s -x http://127.0.0.1:$p https://api.ipify.org; echo; done
```
Expected: 三个 IP 分属日/美/韩(用 ipinfo 核对国家)。

- [ ] **Step 4: 验证故障隔离**

`pkill -f 'svtun1'` 掉美国出口的 openvpn,观察日志:仅 exit 1 切换,exit 0/2 的 curl 持续可用。

- [ ] **Step 5: 验证不碰用户 tun0**

若 VPS 上预先手动 `ip tuntap add tun0 mode tun`,重启服务后确认 `tun0` 仍在(未被清理),仅 `svtun*` 被管理。

- [ ] **Step 6: 记录结果**

把上述结果写入最终提交/PR 描述。

**检查点 F:** 全部完成。合并前跑一次全套 `python3 -m unittest discover -s tests -v` + `python3 tests/smoke_multi_exit.py` + 真机清单。

---

## Self-Review 结果

- **Spec 覆盖**:数据模型(Task 1-5)、tun 命名(Task 1/8/13)、代理多实例(Task 7/13)、调度线程(Task 11-13)、节点互斥(Task 3/9)、向后兼容迁移(Task 2/4)、UI(Task 15)、错误处理与清理(Task 13)、测试三层(Task 1-6 单测 / Task 16 冒烟 / Task 17 真机)——spec 各节均有对应任务。
- **类型/命名一致性**:`exit_resources`/`migrate_legacy_exits`/`exit_routing_view`/`select_exit_node`/`taken_exits_map`/`set_exit_state`/`get_exit_runtime`/`set_node_active_exit`/`union_country_candidates`/`cleanup_stale_exit_devices` 在定义与后续调用间一致;`active_exit`(节点字段)、`exit_id`(参数)、`tun_dev`/`route_table`/`proxy_port`(资源键)全程统一。
- **过渡安全**:旧 `active_openvpn_*` 全局与 `stop_active_openvpn()` 薄封装在 Phase 3 保留,单出口路径在每个检查点仍可端到端运行,降低大重构中途破坏的风险;Phase 4 收口后可在后续清理任务移除死代码(非本计划必需)。
