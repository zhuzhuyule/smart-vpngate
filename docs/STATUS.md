# Smart VPNGate — 状态与待办清单

> 一套完整系统:分层的 `smart_vpngate`(发现/池/健康/策略/出口/仪表盘/鉴权)驱动
> 底层 OpenVPN 引擎(连接 + 策略路由)并复用 `127.0.0.1:7928` 代理网关,单进程、
> 单服务、单个带鉴权的网页面板。本文件记录**已完成**、**待你上机验证**、以及
> **仍未做**的部分。

最后更新对应测试:`python3 -m pytest -q` → **121 passed**。

> ✅ **2026-07-07 已在真实 VPS 上完整验证一次**（Ubuntu 24.04，root+TUN，`install.sh` 全流程，
> 真实 VPNGate 节点）。发现并修复了两个只有真机才会暴露的 bug（见下）。之前"待你上机验证"
> 的 6 项全部走通：真实隧道✅、策略路由✅、7928 代理转发✅（出口 IP 与所连节点一致）、
> 仪表盘出口 IP 显示✅、故障自动切换✅（约 250s 内切到同国健康节点）、install.sh 端到端✅。

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

## ✅ 已在真机上验证过(2026-07-07，Ubuntu 24.04 VPS)

1. **真实 OpenVPN 隧道** ✅ —— `run_openvpn_until_ready` 真实连上 VPNGate 节点，
   `tun0` 建立点对点 IP，`Initialization Sequence Completed`。
2. **策略路由生效** ✅ —— `ip route show table 100` / `ip rule` 正确指向 `tun0`，
   `rp_filter=2` 生效。
3. **7928 代理转发** ✅ —— `curl -x http://127.0.0.1:7928 https://api.ipify.org`
   返回的 IP 与所连 VPNGate 节点一致（非 VPS 自身 IP）。
4. **出口 IP 显示** ✅ —— 仪表盘 `current_exit.public_ip` 与实测代理出口 IP 一致；
   `sv` 菜单的"出口 IP (出站)"字段也正确。
5. **故障自动切换** ✅ —— `kill -9` 掉 openvpn 进程后，约 250s 内（对应默认
   `health.interval=300s` 的下一个 tick）自动切换到同国的另一个健康节点。
6. **install.sh 端到端** ✅ —— 全新 VPS 上跑通一键部署、systemd 服务、`sv`/`ml` 命令、
   网页仪表盘登录、8787 对公网可达（经密码鉴权）。

真机测试过程中发现并修复了两个只有真实网络环境才会暴露的 bug——见下方"已修复的真机 bug"。

> 之前建议的手动验证方式仍适用于后续复测：
> `sudo python3 -m smart_vpngate web --provider vpngate --port 8787`（在仓库根目录），
> 浏览器开 `http://<vps>:8787/<secret>/`，密码见启动日志。

### 🐞 已修复的真机 bug（离线单测覆盖不到，只有真实部署才会暴露）

1. **IPv6 通配地址绑定崩溃**：`install.sh` 用 `--host ::` 启动服务，但
   `ThreadingHTTPServer` 硬编码 `address_family=AF_INET`，绑定 `"::"` 直接抛
   `OSError: [Errno -9] Address family for hostname not supported`，导致整个
   进程崩溃、systemd 无限重启循环（重连节点→建路由→绑端口崩溃→重来）。参照旧引擎
   已有的 `DualStackHTTPServer` 模式，在 `smart_vpngate/web.py` 新增等价的
   `_DualStackHTTPServer` 修复。**所有离线测试都用 `host="127.0.0.1"`，从未测过
   `"::"` 绑定，这正是它没被发现的原因**——已补充回归测试
   `test_binds_ipv6_wildcard_host_without_crashing`。
2. **健康探针测不出本地隧道已死**：默认 `tcp_probe` 连的是节点的**公网端口**（测
   "这个 VPNGate 服务器还能不能连"），而不是"我们自己的隧道进程是否还活着"——杀掉本地
   openvpn 进程后，远程服务器的端口仍然对任何新连接开放，探针会一直误报 healthy。
   真机上实测：`kill -9` 掉 openvpn 后等了 6 分钟仍显示"健康"。修复：
   `manager.py` 的 `tick()` 现在额外核对 `provider.status()`（真实检查 OpenVPN
   子进程是否存活），任一信号说"死了"就触发故障转移。已补充回归测试
   `test_failover_when_provider_reports_dead_tunnel_but_probe_still_ok`。
3. **`public_ip.txt` 语义冲突**：该文件本意是"VPS 自身公网 IP"（`install.sh` 装机时
   写一次，供 `sv`/`ml` 拼登录地址用），但 `compat.py` 曾经每个 tick 都把"隧道出口
   IP"写进同一个文件，覆盖掉 VPS 真实 IP——导致 `sv status` 打印出的"网页登录地址"
   变成隧道出口 IP（打不开）。修复：`compat.write_legacy_status` 不再碰这个文件，
   出口 IP 只通过 `state.json` 的 `proxy_ip` 字段传递（`sv` 菜单本就读这个字段）。

### ⚠️ 真机测试中发现的已知局限（不是 bug，暂未修）

- **健康探针测不出"隧道握手成功但数据面不通"**。默认 `tcp_probe` 只测节点的公网
  控制端口是否可连；真机测试中遇到一个免费 VPNGate 节点（`219.100.37.11`）握手
  完全正常（`Initialization Sequence Completed`、策略路由生效），但实际数据面
  完全不通（无论走 7928 代理还是直接经 `tun0` 访问外网都超时）——这类"控制通道活着、
  数据通道死了"的节点，探针会一直判定为 healthy，不会触发自动切换。手动切换到另一个
  节点（不同主机）后立即恢复正常，证明这是**该免费节点本身的问题**，不是我们代码的
  缺陷；但要自动兜住这种情况，需要更深的健康检查（例如周期性地真的经隧道发一次真实
  请求测数据面，而不只是测控制端口能否连接）——这是比修 bug 更大的设计改动，本次
  未做，先记录。当前的缓解方式：仪表盘手动 switch 始终可用。

---

## ❌ 仍未做(功能缺口 / 可选)

1. ~~`ml` 交互菜单未接新服务~~ ✅ **已接并在真机验证过**:命令更名为 **`sv`**(保留
   `ml` 别名);新服务每个 tick 通过 `compat.write_legacy_status` 回写
   `state.json`/`nodes.json`,菜单据此显示当前节点、出口 IP、健康;进程检测也已
   识别 `smart_vpngate`。
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
