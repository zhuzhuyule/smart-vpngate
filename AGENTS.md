# AGENTS

## Mission
Build Smart VPNGate as a policy-driven Smart Exit Manager.

## Architecture Rules
- Discovery, NodePool, PolicyEngine, Provider and Dashboard are independent modules.
- Provider must not contain scheduling logic.
- PolicyEngine owns all exit decisions.
- Support 1-10 concurrent exit tunnels. Each exit owns one proxy port
  (`BASE_PROXY_PORT + exit_id`, default 7928+) and one TUN device
  (`svtun<exit_id>`), plus an independent route table (`100 + exit_id`).
- Failover is per-exit: switching one exit must never disturb the others.

## Development Order
1. Discovery
2. NodePool
3. HealthCheck
4. PolicyEngine
5. ExitManager
6. Dashboard

## Coding Rules
- Small PRs
- Unit tests for scheduler
- Config-first design
- Provider interface before implementation

## Future Providers
VPNGate, WARP, WireGuard, SOCKS5.
