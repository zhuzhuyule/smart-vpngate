# Smart VPNGate — V2 Design Draft

> **A Free Policy-Driven Smart Exit Manager**

---

## Vision

Smart VPNGate is **not a VPNGate client**.

Its goal is also **not**:

> Automatically connect to the fastest VPNGate node.

Instead, it is:

> **A free, extensible, policy-driven exit scheduling system (Smart Exit Manager).**

VPNGate is only the first Provider. In the future it can support:

- VPNGate
- WireGuard
- WARP
- OpenVPN
- SOCKS5
- HTTP Proxy
- Other free exit providers

The system is only ever responsible for one thing:

> **Selecting the free exit that best matches the current policy** — not the fastest one.

---

## Goals

### V2

Build a system that is:

- Free
- Stable
- Auto-switching
- Auto-recovering
- Observable
- Extensible

### Future

- Multiple providers
- ISP identification
- ASN classification
- IP reputation
- Residential classification
- Exit plugins
- API
- SDK

---

## Core Philosophy

Do not:

> Find Fastest Node

Instead:

> Find Best Exit

**Best** does not mean lowest ping. It is determined jointly by:

- Country
- ISP
- Stability
- Packet loss
- Speed
- Health
- Reputation

---

## Architecture

```
                        +----------------------+
                        |      Dashboard       |
                        +----------+-----------+
                                   |
                                   |
                        +----------v-----------+
                        |     Exit Manager     |
                        +----------+-----------+
                                   |
                     +-------------v--------------+
                     |      Policy Engine         |
                     +-------------+--------------+
                                   |
                    +--------------v-------------+
                    |        Country Pool        |
                    +--------------+-------------+
                                   |
                      +------------v------------+
                      |      Discovery Layer    |
                      +------------+------------+
                                   |
                      +------------v------------+
                      |     Provider Layer      |
                      +------------+------------+
                                   |
               +-------------------+-------------------+
               |                   |                   |
           VPNGate             WireGuard            WARP
```

The system flow is always:

```
Discovery → NodePool → Policy → Exit → Dashboard
```

Five independent layers.

---

## Design Principles

### Principle 1 — Single Active Exit

The system always has exactly **one Active Exit**.

```
Current Exit → JP → tun0
```

Not:

```
tun0
tun1
tun2
```

This lowers complexity and raises stability.

### Principle 2 — Discovery Is Passive

Discovery is only responsible for:

```
Discover → Filter → Cache
```

It must **not** connect, select, or schedule.

### Principle 3 — Policy Owns Decisions

The Policy Engine has the **sole** authority over exit decisions.

```
Discovery → Node Pool → Policy → JP02 → Exit
```

A Provider must never decide the exit.

### Principle 4 — Providers Are Thin

A Provider is only responsible for:

```
Connect / Disconnect / Status
```

It must not perform Policy, Discovery, or Dashboard work.

### Principle 5 — Dashboard Goes Through Exit Manager

The Dashboard must **not** access a Provider directly. All state must pass through the Exit Manager.

---

## Discovery

### Responsibility

Discover VPNGate nodes:

```
VPNGate API → Download → Parse → Normalize → Cache
```

### Filters

- **Country allowlist:** JP, KR, US, SG, TW, HK
- **Blacklist:** CN, RU
- **Protocol:** TCP, UDP
- **Minimum score**
- **Minimum speed**
- **Maximum ping**

### Refresh

Supported refresh triggers:

```
Startup / Manual / Timer
```

For example, refresh nodes every `30min`.

---

## Node Pool

Not a single flat list:

```
[]
```

But per-country pools:

```
JP Pool
KR Pool
US Pool
```

Each pool maintains a `Top50` and is responsible for:

- Sorting
- Deletion
- Updating
- Caching
- Lifecycle
- Eviction
- Standby nodes

---

## Policy Engine

This is the **most core module** of the entire system.

### Lock Country

Example: `JP`.

The current exit is JP. Even if KR is faster, it will not switch.

### Country Priority

```
JP → KR → SG → US
```

If JP is available, never fall down to KR.

### Stickiness

If the current node is `JP01` and it is not broken, do not switch — even if `JP02` is 5ms faster. This avoids switching dozens of times per day.

### Failover

Switch **only** on:

```
Disconnect / Health Fail / Packet Loss / Timeout
```

### Manual Switch

The Dashboard supports:

```
Switch → JP05
```

which switches immediately.

---

## Node Score

Score is **not** ping. It is a composite:

```
Score = Latency + Speed + Loss + Health + ISP + ASN + Reputation
```

In the future, IP reputation will be added.

---

## Health Check

A background task continuously checks:

```
Ping / Loss / Download / Upload / Handshake / Public IP
```

For example, once every `5min`.

---

## Dashboard

### Current Exit

```
Country / ISP / ASN / Ping / Connected / Traffic / Public IP / Health
```

### Node Table

```
Country / City / ISP / ASN / Latency / Loss / Download / Upload /
Score / Status / Current / Last Check / Protocol
```

Supports sorting, filtering, searching, and manual switching.

---

## Config

Everything is YAML.

```yaml
discovery:
  countries:
    - JP
    - KR
    - US

  max_nodes_per_country: 100

policy:
  mode: locked-country

  country: JP

health:
  interval: 300

dashboard:
  auto_refresh: true
```

---

## Exit Manager

The **only** owner of the `Current Exit`. Responsible for:

```
Connect / Disconnect / Switch / Recover
```

The Dashboard must not connect directly.

---

## Provider

A unified interface:

```go
type Provider interface {
    Discover()
    Connect()
    Disconnect()
    Status()
    PublicIP()
}
```

VPNGate is just one implementation.

---

## AI Development Rules

All AI contributions must obey:

- Discovery must not Connect.
- Provider must not do Policy.
- Dashboard must not access Provider.
- Policy must not operate the Dashboard.
- Exit Manager is the sole coordinator of all modules.

---

## V2 Scope

### Included

- ✅ Discovery
- ✅ Country Pool
- ✅ Policy Engine
- ✅ Exit Manager
- ✅ Dashboard
- ✅ Health Check
- ✅ Single Exit

### Not Included

- ❌ Residential
- ❌ ISP Classification
- ❌ ASN Detection
- ❌ GeoIP
- ❌ Multi User
- ❌ Multi Tunnel
- ❌ Commercial Proxy

---

## V3

- ISP classification
- ASN classification
- GeoIP
- Residential detection
- Reputation
- Multi Provider
- Plugin System
- REST API
- WebSocket
- Metrics
- Prometheus
- Grafana

---

## Success Criteria

The project succeeds when it can:

- Stably maintain a free exit.
- Lock the exit by country.
- Automatically switch failed nodes.
- Automatically recover.
- Clearly display exit status.
- Easily extend to new providers.

---

## One Sentence

> **Smart VPNGate does not chase the fastest node — it pursues the most stable, most goal-aligned free exit under the current policy.**
