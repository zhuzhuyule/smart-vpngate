# Smart VPNGate Architecture

## Vision
Smart VPNGate is designed as a Smart Exit Manager instead of a simple VPNGate client.

## Core Principles
- One active exit tunnel.
- Separate discovery, scheduling and provider logic.
- Country-first scheduling.
- Automatic failover.
- Extensible provider architecture.

## Architecture
Client -> VLESS/Reality -> VPS -> Exit Manager -> VPNGate(OpenVPN) -> Internet

Modules:
1. Discovery Service
2. Country Node Pool
3. Policy Engine
4. Health Checker
5. Exit Manager
6. Dashboard

## Discovery
Responsible for collecting VPNGate nodes, filtering by country, score and protocol.

## Node Pool
Maintain independent candidate pools for JP/KR/US etc. Refresh in background.

## Policy Engine
Supports:
- Locked Country
- Country Priority
- Stickiness
- Auto Failover

## Exit Manager
Maintains exactly one active exit tunnel. Switches only when health policy requires.

## Dashboard
Display:
- Current Country
- ISP
- ASN
- Ping
- Download Speed
- Public IP
- Connected Duration

## Future
Provider abstraction allows adding WARP, WireGuard and SOCKS5 without changing scheduler.