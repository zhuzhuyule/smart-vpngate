# 多出口(统一 N 出口模型)设计文档

> 状态：已通过 brainstorming 评审，待写实现计划。
> 目标分支：`feat/multi-exit`。
> 基线：`vpngate_manager.py` 单文件引擎（回退后的 main 线），当前为"唯一活动出口"模型。

## 1. 目标与范围

把当前"唯一活动出口"的状态模型，重构为支持 **N 个并发活动出口**的统一模型。每个出口锁定/自动选择一个国家，对应一个本地代理端口，统一在同一个 Web 面板管理。默认提供 3 个出口槽（可配 1~N），单出口即 `N=1` 的特例。

**核心诉求**：用户希望对外同时提供三个代理端口，每个端口的出口是某个指定国家（例如 7928→日本、7929→美国、7930→韩国）。

### 明确不做（Out of Scope）
- **Docker 打包**：本设计只做功能本身，用现有 `install.sh` 在真实 VPS（root + TUN）验证。Docker 化作为正交的后续独立步骤。
- **每出口的固定 IP / 收藏模式**：每个出口只支持 `auto` 与 `fixed_region` 两种模式，不含 `fixed_ip`、`favorites`。
- **运行时动态增删出口**：出口数量在配置层确定；不提供 Web 面板上动态加/减出口的能力。
- **GeoIP / ISP / ASN 富化、多 Provider**：属于更远期的 V3 范畴。

## 2. 设计决策记录（来自评审）

| 决策点 | 结论 |
|---|---|
| 每出口配置丰富度 | 固定三槽 + `auto`/`fixed_region` 双模 + IP 类型过滤 + 跨国兜底开关 |
| 节点池策略 | **共享单一节点池**：一次拉取 + 测试，三个出口从同一池按各自策略挑选，自动保证互不重复 |
| 重构策略 | **统一 N 出口模型**：单数活动状态重构为出口列表，单出口 = N=1 特例，全系统一套调度路径 |
| 实现范围 | 只做多出口功能，裸机验证；Docker 后续 |
| tun 设备命名 | **专属前缀 `svtun`**（可配），避免与用户自有 `tun0` 冲突 |

## 3. 数据模型与资源分配

### 3.1 Exit（出口）抽象

每个出口捆绑三类信息：

**资源（按 `exit_id` 派生，固定不变）**

| exit_id | proxy_port | tun_dev | route_table |
|---|---|---|---|
| 0 | 7928 | `svtun0` | 100 |
| 1 | 7929 | `svtun1` | 101 |
| 2 | 7930 | `svtun2` | 102 |

- `proxy_port = BASE_PROXY_PORT + exit_id`（默认基 7928）
- `tun_dev = f"{TUN_PREFIX}{exit_id}"`（默认前缀 `svtun`）
- `route_table = TABLE_BASE + exit_id`（默认基 100）

**配置（用户可改，持久化到 `ui_auth.json`）**
- `mode`：`auto` | `fixed_region`
- `force_country`：`fixed_region` 时的锁定国家
- `routing_ip_type`：`all` | `residential` | `hosting`
- `region_fail_fallback`：布尔，锁定国家无可用节点时是否允许临时跨国（复用已实现的语义）

**运行时状态（内存 + `state.json`）**
- `active_node_id`、`process`（Popen）、`is_connecting`、`latency`、`proxy_ok`、`proxy_ip`、`last_message`

### 3.2 tun 设备命名（避免与用户自有服务冲突）

技术前提已确认：`openvpn_command()` 使用 `--dev <名字> --dev-type tun`，`--dev-type tun` 使 OpenVPN 接受**任意设备名**，不局限于系统默认的 `tunN` 编号。

- 出口设备：`svtun0` / `svtun1` / `svtun2`（前缀 = smart-vpngate）
- 测试隧道：从现有 `tun2`~`tun99` 改为 **`svtst2`~`svtst99`**（独立前缀，与出口设备零重叠）
- 前缀可配：新增全局设置 `tun_prefix`（默认 `svtun`）；万一撞车用户可改
- 设备名长度：Linux `IFNAMSIZ` 上限 15 字符，`svtun99` 仅 7 字符，安全

专属前缀顺带解决三个隐患：
1. 不碰用户自己的 `tun0`（用户若已跑别的 OpenVPN/WireGuard 不受影响）；
2. 启动清理时可精准匹配"仅属于本程序的前缀"，绝不误删用户设备；
3. `ip link` 中出口设备（`svtun`）与探测设备（`svtst`）前缀不同，一眼可辨。

### 3.3 配置存储（`ui_auth.json`）

新增 `exits` 数组，每项含 4 个配置字段。以下保持**全局单份**：`secret_path`、`password`、`username`、`port`（Web 端口）、`proxy_port`（改为基端口 `BASE_PROXY_PORT`）、`discovery_countries`（共享拉取范围）、`tun_prefix`。

**向后兼容迁移**：加载配置时若检测到旧的单出口字段（`routing_mode`/`force_country`/`routing_ip_type`/`region_fail_fallback`）且不存在 `exits`，自动生成 `exits[0]`（`mode` 由旧 `routing_mode` 映射：`fixed_region`→`fixed_region`，其余→`auto`；`fixed_ip`/`favorites` 降级为 `auto` 并记录一条日志）。老用户升级无感。

### 3.4 运行时状态（`state.json`）

新增 `exits` 状态数组（每出口的 `active_node_id`/`proxy_ok`/`proxy_ip`/`latency`/`is_connecting`/`last_message`）。拉取相关全局状态（`last_fetch_at`/`last_fetch_status`/`valid_nodes` 等）保持全局，因为节点池共享。

`set_state`/`get_state` 增加按出口读写的辅助（`set_exit_state(exit_id, **kw)`），底层仍写同一个 `state.json`。

### 3.5 共享节点池与互斥

仍是单一 `nodes.json`。把节点的 `active`（布尔）升级为 **`active_exit`**（int 或 null，表示被哪个出口占用）：

- 任一出口选点时，排除 `active_exit` 为其他出口的节点；
- 三个出口自动分到不同节点（即使都锁日本，也各拿一个不同的日本节点）；
- 出口断开/切换时释放旧节点（`active_exit` 置 null）；
- 兼容：读取旧 `nodes.json` 时把 `active=true` 视作 `active_exit=0`。

## 4. 代理层多实例

现状：`proxy_server.start_proxy_server(host, port)` 出站 `SO_BINDTODEVICE` 绑死 `b"tun0"`（`create_connection` 第 207 行、`dns_query_over_tun0` 第 112 行）。

改造：
- `start_proxy_server(host, port, tun_dev)` 增加设备参数；
- 把 `tun_dev` 穿过调用链：`proxy_client` → `http_client`/`socks5_client` → `create_connection` / `resolve_dns_over_tun0` / `dns_query_over_tun0`；
- 每个出口在后台起一个独立的代理服务线程，绑定各自设备：7928 绑 `svtun0`、7929 绑 `svtun1`、7930 绑 `svtun2`；
- 健康检查里对 `/sys/class/net/tun0` 的存在性判断改为按出口设备名。

效果：流量在 socket 层被隔离——发到 7929 的请求必然经美国隧道出去。N 个出口 = N 个代理线程监听 N 个端口。

## 5. 调度与后台线程

三个后台线程从"操作单一活动连接"改为"遍历所有出口"：

- **拉取 + 测试（`collector_loop` / `maintain_valid_nodes`）**：共享池的一次拉取不变；快速首连测试的候选集合改为**所有出口锁定国家的并集**（保证每个出口的目标国家都有节点被测到）。测试完成后遍历每个出口，各自按策略选一个"未被别的出口占用"的最佳节点并连接。
- **健康检查（`background_proxy_checker`）**：从检查单一代理改为遍历每个出口，各自检查各自端口 + 设备；某出口代理/隧道失败只触发**该出口**的切换（遵守它自己的 `mode`/`force_country`/`region_fail_fallback`），并释放它占用的节点。
- **延迟（`active_node_pinger`）**：遍历出口，更新各自延迟。

**并发**：每个出口的连接/切换用**各自的锁**（`exit.lock`），互不阻塞；共享的 `maintenance_lock` 仍守护拉取 + 测试周期。一个出口在切换不影响另外两个继续服务。选点 + 占用（`active_exit` 写入）在全局 `lock` 下原子完成，防止两个出口同时抢同一节点。

选点复用已实现的 `filter_switch_candidates`（含跨国兜底），额外叠加"排除被其他出口占用"的过滤。

## 6. UI 重排

- 单一"当前出口"面板 → **N 张出口卡片**：每张显示国家 / 当前节点 / 出口 IP / 延迟 / 状态，以及该出口的设置入口（模式 / 国家 / IP 类型 / 兜底开关）。
- 节点表：保留已实现的延迟列、国旗、多选国家筛选、单节点测试按钮；新增"被哪个出口占用"标识列。
- 设置面板：每个出口独立的 模式/国家/IP类型/兜底；全局设置（Web 端口、密钥路径、拉取国家范围、`tun_prefix`、基代理端口）保持一处。
- `N=1` 时视觉退化为单卡片，接近当前体验。

## 7. 错误处理、清理与故障隔离

- **启动清理**：只清理匹配本程序前缀的残留设备（`svtun*` / `svtst*`）和对应路由表，绝不触碰用户的 `tun0` 或其他设备。
- **停止清理**：按出口逐个清各自的路由表和设备。
- **rp_filter**：为每个出口设备分别设置 loose 模式（复用现有逻辑，参数化设备名）。
- **故障隔离**：一个出口崩（进程 / 隧道 / 代理线程）不波及其他——独立进程、独立表、独立设备、独立代理线程、独立锁。
- **路由表 / 设备泄漏防护**：`setup_policy_routing(interface, table)` 和 `cleanup_policy_routing(table)` 参数化表号（现硬编码 100）。

## 8. 测试策略（三层）

1. **离线单元测试**（纯函数，无需 root/网络）：
   - 配置迁移（旧单出口 → `exits[0]`，各 `routing_mode` 映射）；
   - 选点互斥（三出口从共享池选到互不重复节点；被占用节点被正确排除）；
   - 资源派生（`exit_id` → port/tun/table，含自定义 `tun_prefix`）；
   - 跨国兜底与选点过滤的组合（复用现有 `filter_switch_candidates` 断言）。
2. **本地 HTTP 冒烟**（起服务、登录、真实请求）：多出口 `state`/配置的读写与持久化、旧客户端兼容。
3. **真实 VPS**（root + TUN，`install.sh` 全流程）：三条隧道（`svtun0/1/2`）+ 三个代理端口，各自 `curl -x` 验证出口 IP 落在正确国家；杀掉一个出口的 openvpn 验证只有该出口切换、另两个不受影响。

## 9. 主要改动面清单（供实现计划参考）

| 区域 | 文件 | 改动性质 |
|---|---|---|
| 全局状态 → 出口列表 | `vpngate_manager.py` :136-140 | 重构 |
| 配置加载 + 迁移 | `vpngate_manager.py` `load_ui_config` | 扩展 |
| 状态读写按出口 | `vpngate_manager.py` `set_state`/`get_state` | 扩展 |
| 资源派生常量 | `vpngate_manager.py` 顶部常量 | 新增 `TUN_PREFIX`/`TABLE_BASE`/`BASE_PROXY_PORT` |
| 连接/停止/健康 按出口 | `vpngate_manager.py` `connect_node`/`stop_active_openvpn`/`auto_switch_node` | 重构（加 `exit_id`） |
| 策略路由参数化表号 | `vpngate_manager.py` `setup_policy_routing`/`cleanup_policy_routing` | 扩展 |
| 三个后台线程遍历出口 | `vpngate_manager.py` `collector_loop`/`background_proxy_checker`/`active_node_pinger` | 重构 |
| 节点互斥 `active`→`active_exit` | `vpngate_manager.py` 选点/合并逻辑 | 重构 |
| 代理多实例绑设备 | `proxy_server.py` :112/:207 + 调用链 | 扩展（加 `tun_dev` 参数） |
| 测试隧道前缀 | `vpngate_manager.py` `get_free_test_index`/`test_*` | 改前缀 `svtst` |
| UI 多出口卡片 + 设置 | `vpngate_manager.py` `INDEX_HTML` + JS | 重构 |
| 出口相关 API | `vpngate_manager.py` `/api/update_settings` 等 | 扩展 |
