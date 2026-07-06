# AGENTS

## Mission
Build Smart VPNGate as a policy-driven Smart Exit Manager.

## Architecture Rules
- Discovery, NodePool, PolicyEngine, Provider and Dashboard are independent modules.
- Provider must not contain scheduling logic.
- PolicyEngine owns all exit decisions.
- Maintain only one active exit tunnel.

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
