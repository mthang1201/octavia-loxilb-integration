# Reuse matrix

These decisions apply to the next design phase; they do not authorize Phase B
or Provider Driver implementation in this baseline.

| Upstream component | Decision | Reason and boundary |
|---|---|---|
| Provider Driver interface skeleton | REUSE | Retain the external `octavia-lib` method/exception patterns and provider entry-point concept. Do not copy mixed dispatch behavior. |
| `octavia-lib` models/constants/errors | REUSE | These are the correct Octavia-facing interface vocabulary. Pin a compatible Octavia release and test it. |
| Apache-2.0 implementation concepts | REUSE | Interface patterns and algorithms may be reused with attribution and license review; the upstream distribution declares Apache-2.0. |
| LoxiLB HTTP client structure | ADAPT | Keep typed operations, pooling, timeouts, TLS/auth, and endpoint failover concepts; align to the target API schema and idempotency rules. |
| Retry handling | ADAPT | Retain bounded retries, but use one explicit policy per operation and avoid retrying unsafe writes without idempotency. |
| Resource translators | ADAPT | Extract pure, validated translators from the large mapper; reject unsupported protocols, algorithms, persistence, and L7/TLS requests. |
| Configuration | ADAPT | Keep `oslo.config`, secret flags, TLS verification, timeouts, and endpoint lists; remove inconsistent/unregistered keys and insecure defaults. |
| VIP/AAP networking | ADAPT | The Neutron AAP pattern is useful, but port ownership, cleanup, multi-node AAP, and routed VIP behavior need target architecture semantics. |
| Unit tests and fixtures | ADAPT | Preserve useful mapping/client/error cases after correcting schema assumptions; add contract, idempotency, and reconciliation tests. |
| Mixed synchronous TaskFlow + RPC orchestration | REPLACE | Choose one authoritative async control path with explicit durable operation state and failure reporting. |
| Per-LB VM provisioning | REPLACE | It conflicts with the preferred shared-infrastructure-cluster hypothesis and does not implement the claimed HA topologies. Retain only as an ADR comparison option. |
| Local JSON ID/metadata state | REPLACE | It is not safe for multiple workers/controllers and cannot provide transactional reconciliation. |
| Health and status logic | REPLACE | Hard-coded `ONLINE`, missing member checks, and incomplete orphan detection cannot represent actual state. |
| Delete-and-recreate updates | REPLACE | Causes avoidable downtime and weak rollback; target API capabilities must define safe patch/reconcile behavior. |
| L7 provider surfaces | REPLACE | Current methods can report dispatch success while lower endpoints are no-ops or `NotImplemented`; target must explicitly reject unsupported L7. |
| Shared-cluster placement | NEW | Select one or more infrastructure LoxiLB nodes per VIP/service with capacity, failure-domain, tenancy, and ownership rules. |
| HA/BGP/ECMP control | NEW | Add route advertisement/withdrawal, node health, convergence, and split-brain behavior only after capability validation. |
| Robust reconciliation | NEW | Add desired/actual inventory, durable identity, periodic/event-driven repair, orphan policy, and safe retries. |
| Standalone capability suite | NEW | Validate target LoxiLB API request/response schemas, isolation, VIP behavior, health checks, and failure semantics before integration. |
| Functional/E2E/failure suite | NEW | Exercise real Octavia, Neutron, LoxiLB, traffic, backend failure, and node failure with captured evidence. |
| Benchmark harness | NEW | Add reproducible throughput/CPS/RPS/latency/CPU/memory comparisons; never seed it with claimed results. |

## Decision summary

- **REUSE:** Octavia interfaces, `octavia-lib` conventions, and license-safe
  implementation concepts.
- **ADAPT:** API client, retry policy, translators, configuration, AAP
  networking, and useful tests.
- **REPLACE:** mixed orchestration, per-LB provisioning for the preferred
  target, JSON state, status/health logic, destructive updates, and false L7
  surfaces.
- **NEW:** shared placement, HA/BGP/ECMP, robust reconciliation, standalone
  validation, E2E/failure coverage, and benchmarks.
