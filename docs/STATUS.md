# Smart VPNGate — 状态与待办清单

> 一套完整系统:分层的 `smart_vpngate`(发现/池/健康/策略/出口/仪表盘/鉴权)驱动
> 底层 OpenVPN 引擎(连接 + 策略路由)并复用 `127.0.0.1:7928` 代理网关,单进程、
> 单服务、单个带鉴权的网页面板。本文件记录**已完成**、**待你上机验证**、以及
> **仍未做**的部分。

最后更新对应测试:`python3 -m pytest -q` → **115 passed**。

---

## ✅ 已完成并有单元测试(离线可验证)

- **Config**：YAML 配置(discovery/policy/health/dashboard),类型校验/归一化/默认值;
  零依赖(有 PyYAML 用之,无则内置最小解析器)。
- **Models**：`Node` + 综合评分(延迟/速度/丢包/健康/provider 信号,非单纯 ping)。
- **Discovery**：拉取 → 解析 → 归一化 → 过滤 → 缓存;被动,不连接/不选择。
- **NodePool**：分国家池、Top-N、按分排序、健康指标跨刷新保留、淘汰。
- **HealthCheck**：可注入探针,更新指标 + 健康分级(healthy/degraded/down)。
- **PolicyEngine**：锁国家 / 优先级 / auto、粘性、仅故障切换。
  - 需求①拉取数量自定义(`max_nodes_per_country`)。
  - 需求②按国家分别配额(`per_country_limits`)。
  - 需求③失效切换:同国优先 → 该国无节点则全局最快兜底(`fallback_fastest`)。
- **ExitManager**：唯一活动出口不变量;connect/switch/recover + 故障转移。
- **Provider 接口** + `FakeProvider`(离线端到端) + `VPNGateProvider`。
- **引擎对接**：`LegacyEngineConnector` 通过 `ensure_dirs`/`run_openvpn_until_ready`/
  `setup_policy_routing`/`cleanup_policy_routing`/`stop_process` 驱动底层引擎。
- **代理网关**：复用 `proxy_server.start_proxy_server`,后台线程起 7928 SOCKS5/HTTP。
- **出口 IP 修正**：仪表盘 Public IP 现经 7928 代理查询(反映出口 IP,而非 VPS IP)。
- **Web 仪表盘**：当前出口面板 + 节点表(排序/过滤/搜索/手动切换/国旗),5s 自动刷新。
- **鉴权**：随机密钥路径 `/…/` + 密码登录 + session cookie(沿用旧凭据);未登录 API 401,
  路径外 404。
- **单一服务部署**：`install.sh` 的 systemd/OpenRC 启动新服务;首次安装从
  `config.example.yaml` 生成 `config.yaml`;`bootstrap` 容忍首次发现失败。

---

## ⏳ 待你上机验证(沙盒无 root/TUN/openvpn/外网,无法在此验证)

这些**代码已就绪**,但真实行为只能在 VPS 上确认:

1. **真实 OpenVPN 隧道**:`run_openvpn_until_ready` 能否用 VPNGate 节点建连(需 openvpn、
   TUN、root、能访问 vpngate.net)。
2. **策略路由生效**:`setup_policy_routing` 的路由表 100 + `rp_filter=2` 是否让流量正确
   走 tun0。
3. **7928 代理转发**:通过 `curl -x http://127.0.0.1:7928 https://ifconfig.me` 验证真实
   翻墙出口。
4. **出口 IP 显示**:仪表盘 Public IP 是否显示节点所在国 IP(依赖 1–3 成立)。
5. **故障自动切换**:主动 `kill` 掉 openvpn 或断网,观察是否按"同国优先→最快兜底"自动切。
6. **install.sh 端到端**:在干净 VPS 上跑一次一键脚本,确认服务起来、8787 登录页可访问、
   连上节点、代理可用。

> 建议先不经 install.sh、手动验证:
> `sudo python3 -m smart_vpngate web --provider vpngate --port 8787`(在仓库根目录),
> 浏览器开 `http://<vps>:8787/<secret>/`,密码见启动日志。

---

## ❌ 仍未做(功能缺口 / 可选)

1. ~~`ml` 交互菜单未接新服务~~ ✅ **已接**:命令更名为 **`sv`**(保留 `ml` 别名);新服务
   每个 tick 通过 `compat.write_legacy_status` 回写 `state.json`/`nodes.json`/`public_ip.txt`,
   菜单据此显示当前节点、出口 IP、健康;进程检测也已识别 `smart_vpngate`。
   (仍待真机验证真实数值。)
2. **日志面板**。旧 UI 有分类日志查看/导出;新仪表盘暂无日志页(仅有出口面板 + 节点表)。
3. **上游代理拉取**。旧引擎支持 API 域名被墙时走上游代理拉节点;新 Discovery 的
   `http_fetcher` 走系统 `HTTPS_PROXY` 环境变量,但没有 UI 配置项。
4. **管理操作**。新仪表盘目前只有"手动切换";旧 UI 的"更新节点/立即补齐/收藏/安全设置"
   等管理动作尚未在新 UI 提供(底层能力在,缺 UI 入口)。
5. **UDP-only 节点健康探测**。默认 `tcp_probe` 用 TCP 连接测活;纯 UDP 节点会被判 down,
   需更贴合的探针。
6. **V3 富化**(设计里明确属 V3):GeoIP / ISP 分类 / ASN / IP 信誉 / 多 Provider /
   Prometheus 等。

---

## 已知取舍 / 注意

- 新服务**不启动**旧引擎自己的调度线程(`collector_loop`/`auto_switch_node`/
  `maintain_valid_nodes` 等);发现与调度全由新调度层负责,旧引擎只当执行器。
- 端口:UI 沿用 `8787`,代理沿用 `7928`(与 install.sh 防火墙/安全组说明一致)。
- 鉴权凭据默认复用旧 `ui_auth.json`(secret_path + password);首次由旧引擎的
  `load_ui_config()` 生成。
