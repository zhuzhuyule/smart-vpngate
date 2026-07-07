# AimiliVPN 🌐

Bilingual: [中文](#中文) | [English](#english)

---

<a name="中文"></a>
## 中文 (Chinese)

AimiliVPN 是一款基于官方 VPNGate 开放协议的策略驱动智能出口管理器（Smart Exit Manager）。它以纯 Python 标准库编写（零依赖），部署为**单一服务**：自动发现并筛选 VPNGate 节点、按策略（锁定国家/优先级/故障自动切换）维持唯一活跃出口、通过加固的 OpenVPN 连接与策略路由建立隧道，并提供本机 SOCKS5/HTTP 代理网关与一个带鉴权的网页仪表盘。

---

### 🌟 VPS 优选推荐：跑 AimiliVPN 更稳更省心
[![BandwagonHost 顶级三网优化](https://img.shields.io/badge/BandwagonHost-%E9%A1%B6%E7%BA%A7%E4%B8%89%E7%BD%91%E4%BC%98%E5%8C%96-red?style=for-the-badge)](https://bandwagonhost.com/aff.php?aff=81790)
[![RackNerd 6000GB 流量](https://img.shields.io/badge/RackNerd-6000GB%2F%E6%9C%88%20%E5%A4%A7%E6%B5%81%E9%87%8F-blue?style=for-the-badge)](https://my.racknerd.com/aff.php?aff=18708)

| 推荐 | 适合谁 | 亮点 | 入口 |
| --- | --- | --- | --- |
| **BandwagonHost 搬瓦工** | 更看重国内访问质量、延迟和线路上限的用户 | **顶级三网优化线路**，适合对网络体验、跨境访问质量和长期稳定性要求更高的场景 | [立即查看](https://bandwagonhost.com/aff.php?aff=81790) |
| **RackNerd** | 想低成本部署、测试、长期挂机的用户 | **每月 6000GB 流量**，价格实惠、配置给得足，适合入门部署和性价比优先的 VPS 需求 | [立即查看](https://my.racknerd.com/aff.php?aff=18708) |

---

### 📢 官方交流与反馈
[![Telegram](https://img.shields.io/badge/TG交流群-arestemple-2CA5E0?style=flat-square&logo=telegram&logoColor=white)](https://t.me/arestemple)
[![Forum](https://img.shields.io/badge/交流论坛-339936.xyz-orange?style=flat-square&logo=discourse&logoColor=white)](https://339936.xyz)
[![YouTube](https://img.shields.io/badge/视频教程-YouTube-red?style=flat-square&logo=youtube&logoColor=white)](https://www.youtube.com/watch?v=s-ATfXR8BpI)
[![Email](https://img.shields.io/badge/Bug反馈-yaohunse7@gmail.com-red?style=flat-square&logo=gmail&logoColor=white)](mailto:yaohunse7@gmail.com)

---

### 🚀 一键极速部署 (支持 Debian/Ubuntu/CentOS/Alpine 等 Linux 系统)

在您的 Linux VPS 上以 root 用户执行以下对应命令：

#### 🌟 正式稳定版本 (main 分支)
```bash
bash <(curl -Ls https://raw.githubusercontent.com/baoweise-bot/aimili-vpngate/main/install.sh)
```
> 💡 **小贴士**：部署完成后，终端会输出网页仪表盘的专属链接（含随机安全后缀）和登录密码，例如 `http://your_vps_ip:8787/u71e9IXp4TPx/`。在终端中输入 **`sv`** 命令（旧命令 `ml` 仍可用）可以随时调出交互式命令行管理菜单，查看当前状态、密码、日志等。

一键脚本会安装并启动**一套单一服务**：发现/调度/策略/出口全部由这套服务负责，OpenVPN 连接、策略路由与本机 `7928` 代理网关都在同一个进程里；服务由 systemd/OpenRC 托管，开机自启。

---

### 💡 快速使用指南 (小白必看)

部署成功后，如何使用它进行科学上网？

#### 第一步：登录网页仪表盘
打开浏览器，访问部署完成时提示的专属地址（含随机安全后缀），输入密码登录。

#### 第二步：查看与切换出口
- **Current Exit 面板**：当前出口的国家、节点、协议、健康状态、公网 IP、在线时长，以及策略引擎最近一次的决策原因。
- **Node Table 节点表**：所有候选节点，支持点击表头排序、关键字搜索、按国家/健康状态过滤；对任意节点点击 **switch** 即可立即手动切换出口。
- 服务默认每隔一段时间自动做健康检查与策略复核；当前出口故障时会**自动**在同一国家内寻找替补节点，若同国已无可用节点，则回退到全局最快的健康节点，确保始终有出口可用。

#### 第三步：按需调整策略（可选）
默认策略是锁定日本（JP）出口。如需修改国家锁定、优先级顺序、每国节点数量、故障切换行为等，编辑安装目录下的 `config.yaml`（首次安装会自动从 `config.example.yaml` 生成），然后执行 `sv restart` 使配置生效。常用字段：

- `policy.mode` + `policy.country`：锁定单一国家出口。
- `policy.mode: priority` + `policy.priority`：按国家优先级自动选择，高优先级国家恢复可用时自动切回。
- `discovery.countries` / `discovery.per_country_limits`：允许的国家范围，以及各国分别保留多少候选节点。
- `policy.fallback_fastest`：同国无可用节点时是否回退到全局最快节点（默认开启）。

也可以不改配置，直接在网页仪表盘上手动 **switch** 到任意节点——只要该节点保持健康，策略的粘性机制会尽量维持在这个节点上。

#### 第四步：使用本机代理 (核心步骤)
为了防止代理端口暴露至公网被恶意扫描和滥用，AimiliVPN 的双效代理服务（默认端口 **`7928`**，自适应支持 SOCKS5 和 HTTP 协议）**默认仅绑定在本地回环地址（`127.0.0.1`）**，只接收 VPS 本机上的流量，不对外机提供代理。

* **🐍 Python 脚本中使用代理**:
  ```python
  import requests
  proxies = {
      "http": "http://127.0.0.1:7928",
      "https": "http://127.0.0.1:7928",
  }
  response = requests.get("https://www.google.com", proxies=proxies)
  ```
* **🐚 Shell 终端环境中使用代理**:
  在命令行执行以下命令，可以让当前终端的后续命令（如 `curl`、`wget` 等）走代理出口：
  ```bash
  export http_proxy="http://127.0.0.1:7928"
  export https_proxy="http://127.0.0.1:7928"
  ```
* **⚙️ 本地其他服务配置**:
  将本机的其他代理工具、爬虫框架或服务的出战代理设置为 `127.0.0.1:7928`。

> 💡 **小贴士**：如果您确实需要对公网其他设备开放此代理端口，可以通过设置环境变量 `export LOCAL_PROXY_HOST="::"` 重新启动服务以允许公网接入。

---

### 🛠️ 核心功能与操作说明

* **智能出口调度**：按策略（锁定国家/国家优先级/自动）在候选节点中选择唯一活跃出口；节点故障时自动在同国节点间切换，同国无可用节点时回退到全局最快的健康节点，全程无需人工干预。
* **网页仪表盘**：Current Exit 面板 + Node Table（排序/过滤/搜索/手动切换），每 5 秒自动刷新；登录需随机密钥路径 + 密码，未登录无法访问。
* **终端管理菜单 (`sv` / `ml`)**：查看服务状态、当前节点与出口 IP、启动/停止/重启服务、查看实时日志、重新配置网页端口与密码、一键更新、一键卸载。
* **本机代理网关**：默认仅监听 `127.0.0.1:7928`，自适应 SOCKS5/HTTP，避免代理端口被公网扫描滥用。
* **按需配置**：通过 `config.yaml` 精细控制国家白名单/黑名单、每国候选节点数量、协议、故障切换策略等（见上文"第三步"与 [`config.example.yaml`](config.example.yaml)）。

> 📋 尚未支持、正在规划中的功能（日志查看面板、网页端上游代理配置、更新节点等管理动作的网页入口、UDP-only 节点的专用健康探测等）见 [`docs/STATUS.md`](docs/STATUS.md)。

---

### ⚠️ 小白安装与运行常见问题 (FAQ)

#### 1. 提示 `Cannot allocate tun` 或 `Cannot open tun/tap dev`
* **原因**：VPS 宿主机未启用虚拟网卡（TUN/TAP 设备）。这种情况常见于 LXC 或 OpenVZ 架构的轻量 VPS。
* **解决办法**：请登录您的 VPS 服务商控制面板（如 SolusVM/Proxmox），找到 **Enable TUN/TAP** / **开启 TUN** 选项并启用，然后重启 VPS。如无此选项，请工单联系客服开启。

#### 2. 网页仪表盘无法打开（链接超时或拒绝连接）
* **原因 1**：VPS 本身自带防火墙（如 UFW、firewalld 或 iptables）阻断了管理端口（默认 `8787`）或代理端口（默认 `7928`）。
* **解决办法 1**：请在终端放行对应端口：
  * **UFW (Ubuntu/Debian)**: `ufw allow 8787/tcp && ufw allow 7928/tcp`
  * **Firewalld (CentOS/RHEL)**: `firewall-cmd --zone=public --add-port=8787/tcp --permanent && firewall-cmd --zone=public --add-port=7928/tcp --permanent && firewall-cmd --reload`
* **原因 2**：云服务商的“安全组”或“网络访问控制列表 (ACL)”未放行端口。
* **解决办法 2**：**非常重要！** 登录云服务商控制台（如阿里云、腾讯云、AWS、Oracle Cloud等），找到您 VPS 实例的 **安全组规则 (Security Group)**，在入站规则中添加：
  - **协议类型**: `TCP`
  - **端口范围**: `8787` (网页仪表盘) 和 `7928` (代理端口)
  - **授权对象/源IP**: `0.0.0.0/0` (允许所有人，或指定您自己的家庭公网 IP 提高安全性)

#### 3. 节点表显示为空，或候选节点数为 0
* **原因**：您的 VPS DNS 解析异常，或者官方 VPNGate 域名遭防火墙拦截污染，导致无法下载节点列表。
* **解决办法**：
  * **设置上游代理**：在 `config.yaml` 所在目录设置标准环境变量 `HTTPS_PROXY`（供发现层拉取节点列表使用），然后 `sv restart`。
  * **修改 DNS 解析器**：在终端修改 `/etc/resolv.conf`，将域名服务器替换为公共 DNS（如 `nameserver 8.8.8.8` 和 `nameserver 1.1.1.1`）。

#### 4. VPN 已成功连接，但客户端设置代理后无法上网 (无流量)
* **原因**：部分系统启用了严格的反向路径过滤（`rp_filter`），导致策略路由的入站/出站数据包被系统误判丢弃。
* **解决办法**：服务连接节点时会自动尝试将 `rp_filter` 配置为宽松模式（值为 `2`）；如仍有问题，可在终端输入 `sv` 命令打开交互菜单进一步检查服务与日志状态。

---

### ⚙️ 技术架构与命令行参考

系统按 [`docs/DESIGN.md`](docs/DESIGN.md) 的设计分层实现（发现 → 节点池 → 健康检查 → 策略引擎 → 出口管理 → 仪表盘），代码在 `smart_vpngate/` 包内，全部分层均已实现并通过 **118 项单元测试**（`python3 -m pytest -q`）。真实的 OpenVPN 连接、策略路由与 `7928` 代理网关复用同一套已验证的引擎逻辑（`LegacyEngineConnector` 驱动），因此**只有一套系统、一套服务、一个进程**，不存在"新旧并行"的两套后端。

进度与已知缺口（日志面板、网页端上游代理配置、UDP 专用探针等）见 [`docs/STATUS.md`](docs/STATUS.md)。

#### 配置文件

复制模板并按需修改（缺省项自动回退到默认值）：

```bash
cp config.example.yaml config.yaml
```

关键字段：`discovery.countries`（国家白名单）、`discovery.blacklist`（黑名单）、`discovery.protocols`、`discovery.max_nodes_per_country` / `per_country_limits`（每国候选节点数量，可分国配置）、`policy.mode`（`locked-country`/`priority`/`auto`）、`policy.country`、`policy.fallback_fastest`（同国无节点时回退全局最快）、`health.interval`。完整示例见 [`config.example.yaml`](config.example.yaml)。

> 🧩 **零依赖**：系统保持"纯标准库"。已安装 PyYAML 时优先使用，未安装时自动回退到内置的最小 YAML 解析器，因此在 `install.sh` 部署出的 stock `python3` 上无需 pip 即可运行。

#### 命令行用法

`install.sh` 部署的单一服务等价于：

```bash
python3 -m smart_vpngate web --provider vpngate --host :: --port 8787 --config config.yaml
```

其他常用子命令：

```bash
# 只跑发现层：拉取、过滤、缓存节点（不连接、不起服务）
python3 -m smart_vpngate discover --config config.yaml
python3 -m smart_vpngate discover --from-file feed.csv   # 离线，从本地 CSV 读取

# 离线演示：内存版 fake provider，无需 root/联网/真实 VPS
python3 -m smart_vpngate web --provider fake --port 8686
python3 -m smart_vpngate run --provider fake --once

# 打印上次缓存的面板快照（无需起服务）
python3 -m smart_vpngate status
```

`web` 子命令关键参数：`--auth/--no-auth`、`--password`、`--secret-path`（鉴权配置，默认对 `vpngate` provider 开启并复用已有凭据）、`--minimal-connector`（退回内置最小 OpenVPN 启动器，不走加固路由/代理）、`--no-proxy`（不启动 7928 网关）、`--proxy-host`/`--proxy-port`。完整参数见 `python3 -m smart_vpngate web --help`。

#### 运行测试

```bash
python3 -m pytest -q      # 118 项离线单元测试（六层 + 端到端 + Web UI + 引擎对接 + 鉴权）
```

---

### 🎁 捐赠支持项目开发

如果您觉得这个项目对您有所帮助，欢迎捐赠支持我们的后续开发与维护：

* **BNB (BSC / BEP20)**: `0xB6d78c42CEB0687A31B8cfEBE4b51b6eB8953C17`
* **TRX (TRC20)**: `TSdzCW6JvsrqcppodYjhSrku4mYmDJ9pxf`

感谢您的慷慨与支持！❤️

---

<a name="english"></a>
## English

AimiliVPN is a policy-driven Smart Exit Manager built on the official VPNGate protocol. Written entirely in Python's standard library (zero dependencies), it deploys as **one single service**: it discovers and filters VPNGate nodes, maintains exactly one active exit according to policy (locked country / priority / automatic failover), establishes the tunnel via a hardened OpenVPN connection with policy routing, and exposes a local SOCKS5/HTTP proxy gateway plus one authenticated web dashboard.

### 🌟 Recommended VPS Deals
[![BandwagonHost Premium Optimized Routes](https://img.shields.io/badge/BandwagonHost-Premium%20Optimized%20Routes-red?style=for-the-badge)](https://bandwagonhost.com/aff.php?aff=81790)
[![RackNerd 6000GB Bandwidth](https://img.shields.io/badge/RackNerd-6000GB%2Fmonth%20Bandwidth-blue?style=for-the-badge)](https://my.racknerd.com/aff.php?aff=18708)

| Pick | Best for | Highlights | Link |
| --- | --- | --- | --- |
| **BandwagonHost** | Users who care most about China connectivity, latency, and route quality | **Premium China Telecom/Unicom/Mobile optimized routes**, ideal for demanding cross-border networking and long-term use | [View deals](https://bandwagonhost.com/aff.php?aff=81790) |
| **RackNerd** | Budget deployments, testing, and long-running lightweight services | **6000GB monthly bandwidth**, affordable pricing, and generous specs for value-focused VPS use | [View deals](https://my.racknerd.com/aff.php?aff=18708) |


### 📢 Community & Feedback
- **Telegram Group**: [arestemple](https://t.me/arestemple)
- **Discussion Forum**: [339936.xyz](https://339936.xyz)
- **Video Tutorial**: [YouTube Guide](https://www.youtube.com/watch?v=s-ATfXR8BpI)
- **Email Contact**: yaohunse7@gmail.com

---

### 🚀 One-Click Installation

Run the corresponding command on your Linux VPS as root:

#### 🌟 Stable Release (main branch)
```bash
bash <(curl -Ls https://raw.githubusercontent.com/baoweise-bot/aimili-vpngate/main/install.sh)
```

> 💡 **Quick Note**: Once installed, the terminal prints the dashboard's URL (with a random secret path) and login password, e.g. `http://your_vps_ip:8787/u71e9IXp4TPx/`. Type **`sv`** (legacy `ml` still works) any time to open the interactive management menu.

The installer sets up and starts **one single service**: discovery, scheduling, policy and exit management all run in it, together with the OpenVPN connection, policy routing, and the local `7928` proxy gateway — all in the same process, managed by systemd/OpenRC with auto-start on boot.

---

### 💡 Quick Start Guide

#### Step 1: Log in to the web dashboard
Open your browser and go to the printed URL (with its secret path suffix), then log in with the printed password.

#### Step 2: View and switch the exit
- **Current Exit panel**: the active exit's country, node, protocol, health, public IP, uptime, and the policy engine's latest decision.
- **Node Table**: every candidate node — click column headers to sort, search by keyword, filter by country/health, and click **switch** on any row to manually change the exit immediately.
- The service periodically health-checks and re-evaluates policy in the background. If the active exit fails, it **automatically** picks the next healthy node in the same country; if that country has none left, it falls back to the fastest healthy node anywhere, so there's always an exit.

#### Step 3: Tune the policy (optional)
The default policy locks the exit to Japan (JP). To change the locked country, priority order, per-country node counts, or failover behavior, edit `config.yaml` in the install directory (auto-generated from `config.example.yaml` on first install), then run `sv restart`. Common fields:

- `policy.mode` + `policy.country`: lock to a single country.
- `policy.mode: priority` + `policy.priority`: prefer higher-priority countries, moving back up automatically once they become available again.
- `discovery.countries` / `discovery.per_country_limits`: allowed countries, and how many candidates to keep per country.
- `policy.fallback_fastest`: fall back to the fastest node anywhere when the preferred country has none left (on by default).

You can also skip config edits and just click **switch** on any node in the dashboard — stickiness will keep you there as long as it stays healthy.

#### Step 4: Use the Local Proxy (Core Step)
To prevent unauthorized scanning and abuse of the proxy port on the public internet, the built-in HTTP/SOCKS5 proxy server (default port **`7928`**) **binds to localhost (`127.0.0.1`) by default**. It is designed to route traffic generated locally on the VPS, rather than acting as a public proxy server.

* **🐍 Proxy in Python**:
  ```python
  import requests
  proxies = {
      "http": "http://127.0.0.1:7928",
      "https": "http://127.0.0.1:7928",
  }
  response = requests.get("https://www.google.com", proxies=proxies)
  ```
* **🐚 Proxy in Shell terminal**:
  ```bash
  export http_proxy="http://127.0.0.1:7928"
  export https_proxy="http://127.0.0.1:7928"
  ```
* **⚙️ Other local services**:
  Configure your scrapers, frameworks, or utility tools on this VPS to send traffic via `127.0.0.1:7928`.

> 💡 **Quick Note**: If you really need to open this proxy port to the public internet, you can set the environment variable `export LOCAL_PROXY_HOST="::"` before restarting the service.

---

### 🛠️ Core Features

* **Smart exit scheduling**: picks a single active exit by policy (locked country / country priority / auto); on failure it auto-switches to a healthy node in the same country first, falling back to the fastest healthy node anywhere if that country is exhausted — no manual intervention needed.
* **Web dashboard**: Current Exit panel + Node Table (sort/filter/search/manual switch), auto-refreshing every 5s; gated by a secret URL path + password login.
* **Terminal menu (`sv` / `ml`)**: service status, active node and exit IP, start/stop/restart, live logs, reconfigure port/credentials, one-click update, one-click uninstall.
* **Local proxy gateway**: binds to `127.0.0.1:7928` by default (SOCKS5/HTTP auto-detect), avoiding public exposure/abuse.
* **Config-driven tuning**: country allow/deny lists, per-country node quotas, protocols, failover behavior — all via `config.yaml` (see Step 3 above and [`config.example.yaml`](config.example.yaml)).

> 📋 Roadmap items not yet available (a log viewer panel, upstream-proxy configuration in the web UI, web-UI entry points for admin actions like "refresh nodes now", a dedicated UDP-only health probe) are tracked in [`docs/STATUS.md`](docs/STATUS.md).

---

### ⚠️ Common Troubleshooting (FAQ)

#### 1. Error: `Cannot allocate tun` or `Cannot open tun/tap dev`
* **Reason**: Virtual network adapter (TUN/TAP device) is disabled. This is common in OpenVZ/LXC VPS instances.
* **Solution**: Enable **TUN/TAP** in your VPS SolusVM/KiwiVM control panel, or submit a support ticket to your hosting provider.

#### 2. Cannot open the web dashboard in the browser
* **Reason 1**: The built-in firewall (UFW or firewalld) is blocking ports `8787` (dashboard) and `7928` (proxy).
* **Solution 1**: Allow the ports in your OS firewall:
  * **UFW**: `ufw allow 8787/tcp && ufw allow 7928/tcp`
  * **Firewalld**: `firewall-cmd --add-port=8787/tcp --permanent && firewall-cmd --add-port=7928/tcp --permanent && firewall-cmd --reload`
* **Reason 2**: Service provider security group blocking ports.
* **Solution 2**: **Crucial!** Log in to your cloud provider console (AWS, Aliyun, Oracle Cloud, etc.), locate the **Security Group** for your instance, and add an inbound TCP rule to allow ports `8787` and `7928` from `0.0.0.0/0`.

#### 3. Node Table is empty, or candidate count is 0
* **Reason**: The official VPNGate domain is blocked or DNS resolution failed on your VPS.
* **Solution**: Set the standard `HTTPS_PROXY` environment variable for the service (used by the discovery layer to fetch the node list) and run `sv restart`, or configure public DNS in `/etc/resolv.conf` (e.g., `nameserver 8.8.8.8`).

#### 4. VPN connected, but no traffic through the proxy
* **Reason**: Some systems enable strict reverse-path filtering (`rp_filter`), which silently drops policy-routed packets.
* **Solution**: The service automatically attempts to relax `rp_filter` (to mode `2`) when connecting a node. If issues persist, run `sv` to open the management menu and inspect service/log status.

---

### ⚙️ Architecture & CLI Reference

The system is implemented per the layered design in [`docs/DESIGN.md`](docs/DESIGN.md) (Discovery → Node Pool → Health Check → Policy Engine → Exit Manager → Dashboard), living in the `smart_vpngate/` package. All layers are implemented and covered by **118 unit tests** (`python3 -m pytest -q`). The real OpenVPN connection, policy routing, and the `7928` proxy gateway reuse the same proven engine logic (driven via `LegacyEngineConnector`) — so this is **one system, one service, one process**, not two parallel backends.

Progress and known gaps (log panel, upstream-proxy web UI, a dedicated UDP probe, etc.) are tracked in [`docs/STATUS.md`](docs/STATUS.md).

**Configure** (copy the template; omitted keys fall back to defaults):

```bash
cp config.example.yaml config.yaml
```

**The single service `install.sh` deploys is equivalent to:**

```bash
python3 -m smart_vpngate web --provider vpngate --host :: --port 8787 --config config.yaml
```

**Other useful subcommands:**

```bash
# Discovery only: fetch, filter, cache nodes (no connection, no service)
python3 -m smart_vpngate discover --config config.yaml
python3 -m smart_vpngate discover --from-file feed.csv   # offline, from a local CSV

# Offline demo: in-memory fake provider, no root/network/real VPS needed
python3 -m smart_vpngate web --provider fake --port 8686
python3 -m smart_vpngate run --provider fake --once

# Print the last cached dashboard snapshot (no running service needed)
python3 -m smart_vpngate status
```

Key `web` flags: `--auth/--no-auth`, `--password`, `--secret-path` (auth is on by default for the `vpngate` provider and reuses existing credentials), `--minimal-connector` (fall back to the built-in minimal OpenVPN starter, skipping hardened routing/proxy), `--no-proxy` (don't start the 7928 gateway), `--proxy-host`/`--proxy-port`. Full flag list: `python3 -m smart_vpngate web --help`.

**Run tests:** `python3 -m pytest -q` (118 offline unit tests).

---

### 🎁 Donation Support

If you find this project helpful, you can support its development and maintenance via donation:

* **BNB (BSC / BEP20)**: `0xB6d78c42CEB0687A31B8cfEBE4b51b6eB8953C17`
* **TRX (TRC20)**: `TSdzCW6JvsrqcppodYjhSrku4mYmDJ9pxf`

Thank you for your generosity and support! ❤️
