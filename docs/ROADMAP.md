# Smart VPNGate V2 Roadmap

## Vision
Transform the project from a simple VPNGate client into a Smart Exit Manager.

## Goals
- Country-aware discovery
- Node pools per country
- Policy-based exit selection
- Automatic failover
- Latency and ISP visualization
- Provider abstraction for future expansion

## Milestones
1. Discovery
   - Country filters
   - Max nodes per country
   - Score filters
2. Node Pool
   - JP/KR/US pools
   - Background refresh
3. Policy Engine
   - Locked country
   - Country priority
   - Stickiness
4. Dashboard
   - Ping
   - ISP
   - ASN
   - Public IP
   - Current exit
5. Health Check
   - Periodic testing
   - Automatic failover
6. Provider abstraction
   - VPNGate first
   - WARP/WireGuard later

## Design Notes
- Keep one active exit tunnel.
- Prefer staying within the same country.
- Switch only on failure or policy trigger.
- Separate discovery, pool and policy layers.
