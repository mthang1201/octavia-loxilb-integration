# Upstream feature matrix

Status meanings follow `SOURCE.md`. A **verified** entry means the source path
or isolated test behavior was observed; it does not mean it passed a live
OpenStack/LoxiLB test.

| Capability | Status | Evidence and limitation |
|---|---|---|
| TCP listener/service mapping | verified | Maps to LoxiLB `tcp` in `common/constants.py:79-86` and `resource_mapping/mapper.py:368-386`; no functional traffic test. |
| UDP listener/service mapping | verified | Maps to `udp`; no functional traffic test. |
| HTTP | partial | Mapped to TCP only; no HTTP-aware Octavia policy behavior verified. |
| HTTPS pass-through | partial | Mapped to TCP; transport forwarding may be possible, but was not tested. |
| TERMINATED_HTTPS / TLS termination | not implemented | References are stored/mapped, but there is no Barbican retrieval, key material installation, or validated LoxiLB TLS lifecycle. |
| Host/path routing | not implemented | No effective API mapping or tests. |
| L7Policy / L7Rule CRUD | not implemented | Provider emits RPC and calls no-op subdriver methods; queue endpoints explicitly raise `NotImplementedError`. |
| LoadBalancer create | partial | Synchronous VM/AAP TaskFlow exists, then duplicate RPC orchestration; no live validation. |
| LoadBalancer update | partial | RPC path exists; lower layers commonly use delete/recreate behavior. |
| LoadBalancer delete | partial | Synchronous delete flow plus RPC exists; VIP-port deletion ownership is risky and untested. |
| LoadBalancer failover | not implemented | Provider calls absent `LoadBalancerDriver.failover()` (`provider_driver.py:299-326`). |
| Listener create/update/delete | partial | Provider/worker/subdriver paths exist; direct fallback and service recreation produce inconsistent semantics. |
| Pool create/update/delete | partial | Metadata and listener-service recreation paths exist; unit failures expose drift. |
| Member create/update/delete | partial | Metadata/endpoint/service-recreation paths exist; seven related unit failures. |
| Batch member update | partial | Provider, worker, flow, and task surfaces exist; no live or focused successful evidence. |
| Health Monitor | partial | Validation/probe code exists, but response schemas drift, coordination methods are absent, and status is hard-coded. |
| SOURCE_IP persistence | partial | Translated to hash selection; no dataplane validation. |
| HTTP_COOKIE / APP_COOKIE persistence | unsupported | Silently substituted with source-IP hash (`mapper.py:443-471`), which changes requested semantics. |
| Round robin | partial | Mapping exists; no traffic-distribution evidence. |
| Least connections | partial | Mapping exists; no traffic-distribution evidence. |
| Source-IP / source-IP-port algorithms | partial | Mapping exists; no traffic-distribution evidence. |
| Unknown algorithms/options | unsupported | Algorithm silently falls back to round-robin and protocol to TCP instead of explicit rejection. |
| Statistics | not implemented | Provider invokes absent `LoadBalancerDriver.get_stats()`; client has metrics-shaped calls without integration evidence. |
| Provisioning status | partial | DB tasks write lifecycle states, but mixed orchestration and async failures can make accepted operations diverge from actual state. |
| Operating status | unsupported | Health-monitor logic always returns `ONLINE`; no authoritative dataplane health reconciliation. |
| Persistent mapping | partial | Local JSON persistence exists, but lacks transactions, distributed locking, and multi-controller ownership. |
| Reconciliation | not implemented | Orphan scan is TODO/`pass`; members are assumed present. |
| SINGLE topology | partial | One VM per LB is source-verified; not functionally tested. |
| ACTIVE_STANDBY | claimed but unverified | Advertised/configurable, but the provisioning flow creates one VM. |
| ACTIVE_ACTIVE | claimed but unverified | Config choice exists, but no multi-node provisioning or lifecycle implementation was found. |
| BGP | claimed but unverified | Documentation/configuration references exist; no BGP neighbor/route lifecycle is implemented or tested. |
| ECMP | not implemented | No ECMP programming, placement, or convergence logic found. |
| BFD | not implemented | No BFD lifecycle or failure test found. |
| Connection synchronization | unknown | No driver-side connection-state synchronization mechanism or test found; target LoxiLB behavior is unverified. |
| Horizontal scale-out | claimed but unverified | Documentation claims scaling; no shared-node placement or N-node test evidence. |
| eBPF/XDP performance | claimed but unverified | Upstream README claims performance characteristics; Phase A has no throughput/CPS/RPS/latency/resource evidence. |
| Functional/E2E operation | unknown | Four functional tests collect but were marked `NOT EXECUTED`; no OpenStack/LoxiLB environment was available. |

## Conclusion

The defensible implemented surface is a set of L4-oriented mappings and
orchestration/client building blocks. Production readiness, HA, scale-out,
BGP/ECMP, complete status, statistics, and L7 functionality are not supported
by the Phase A evidence.
