# MVP_SCOPE.md

## 1. Objective

Define the smallest defensible **Octavia LoxiLB Provider Driver MVP** that proves the Octavia-to-LoxiLB semantic contract without claiming unsupported Amphora feature parity.

The MVP should prove:

```text
OpenStack user
   ↓
Octavia API
   ↓
provider=loxilb
   ↓
Octavia logical resources
   ↓
LoxiLB Provider Driver
   ↓
LoxiLB service rule(s)
   ↓
backend traffic
   ↓
health/status synchronized back to Octavia
```

The priority is correctness, explicit capability validation, idempotent reconciliation and status semantics—not feature breadth.

---

# 2. MVP principles

## 2.1 L4 first

The architecture evidence is strongest for LoxiLB's standalone L4 service model.

Initial scope:

```text
VIP
TCP
UDP after target-release validation
default Pool
Members
supported algorithms
supported active health probes
status reconciliation
```

Do **not** represent TCP forwarding of HTTP/HTTPS traffic as Octavia L7 support.

## 2.2 One semantic path first

The first vertical slice should be:

```text
LoadBalancer
  └── TCP Listener
        └── default Pool
              ├── Member A
              ├── Member B
              └── TCP HealthMonitor
```

with:

```text
ROUND_ROBIN
```

Only after that path is stable should additional algorithms, UDP and richer probes be enabled.

## 2.3 Desired-state reconciliation over thin CRUD

Because the Octavia hierarchy is flattened into a LoxiLB service rule and the examined API evidence does not establish atomic update operations for every field, each mutation should conceptually:

```text
recompute desired service
→ compare with observed LoxiLB state
→ create/replace/reconcile
→ verify
→ report status
```

## 2.4 Explicit rejection over silent approximation

Unsupported Octavia options must be rejected using the provider contract, especially `UnsupportedOptionError` or `NotImplementedError` as appropriate.

Never silently convert:

```text
SOURCE_IP_PORT → SOURCE_IP
TLS-HELLO → TCP
cookie persistence → source-IP persistence
unsupported expected_codes → any HTTP response
unsupported L7 → TCP pass-through
```

---

# 3. Core resource scope

The practical CRUD surface from the Octavia architecture is 15 callbacks.

## LoadBalancer

```text
loadbalancer_create
loadbalancer_update
loadbalancer_delete
```

## Listener

```text
listener_create
listener_update
listener_delete
```

## Pool

```text
pool_create
pool_update
pool_delete
```

## Member

```text
member_create
member_update
member_delete
```

## HealthMonitor

```text
health_monitor_create
health_monitor_update
health_monitor_delete
```

Also strongly recommended early:

```text
member_batch_update
```

because a LoxiLB service naturally contains an endpoint set and reconciliation is safer when desired membership can be processed as a whole.

---

# 4. Feature priority

## P0 — mandatory first vertical slice

| Feature | Decision | Rationale |
|---|---|---|
| `LoadBalancer` VIP intent | **Support** | Required ownership/top-level Octavia resource. |
| TCP Listener | **Support** | Strongest L4 mapping. |
| One default Pool per Listener | **Support** | Clean mapping to one LoxiLB service rule. |
| Member address + port | **Support** | Strong direct endpoint mapping. |
| `ROUND_ROBIN` | **Support** | Direct `rr` mapping. |
| TCP HealthMonitor | **Support after exact API validation** | Closest health-monitor mapping. |
| Create / update / delete | **Support** | Required lifecycle. |
| Status callbacks | **Support** | Required semantic contract. |
| Reconciliation/idempotency | **Support** | Required for safe retries and flattened service model. |
| LoxiLB management over TLS/auth | **Support as deployment requirement** | Source notes API is HTTP by default; production integration must secure it. |
| Durable Octavia↔LoxiLB identity correlation | **Support** | Required for restart/recovery and status mapping. |

### P0 acceptance scenario

```text
1. Create LB with provider=loxilb.
2. Create TCP listener.
3. Create ROUND_ROBIN pool.
4. Add two members.
5. Create TCP health monitor.
6. Traffic reaches both members.
7. Stop one backend.
8. LoxiLB stops selecting the unhealthy member.
9. Octavia operating status reflects observed health.
10. Update a member and verify desired state.
11. Delete resources and verify backend state is removed.
12. Repeat/retry operations without duplicate LoxiLB state.
```

---

## P1 — enable after the P0 semantic path is stable

| Feature | Decision | Verification required |
|---|---|---|
| UDP Listener | **Support** | Confirm target Octavia release/provider model and LoxiLB UDP behavior. |
| `LEAST_CONNECTIONS` | **Support** | Validate `lc` API value and behavior. |
| `SOURCE_IP` persistence | **Support conditionally** | Verify LoxiLB `persist` semantics and persistence timeout/behavior. |
| PING HealthMonitor | **Support conditionally** | Confirm exact Octavia exposure and status semantics. |
| HTTP HealthMonitor | **Support conditionally** | Verify `url_path`, response success criteria, timeout and retries. |
| HTTPS HealthMonitor | **Support conditionally** | Verify TLS behavior plus HTTP semantics. |
| Member weight / WRR | **Support conditionally** | Verify algorithm activation, weight interpretation and weight=0. |
| Multiple listeners on one VIP | **Support conditionally** | Verify service identity and coexistence of multiple frontend tuples. |
| `member_batch_update` | **Support** | Validate whole-endpoint-set replacement/reconciliation. |

---

# 5. Explicitly out of MVP

The initial Provider Driver should reject/defer the following unless later validation proves a stable standalone mapping.

| Feature | MVP decision | Reason |
|---|---|---|
| Octavia `L7Policy` / `L7Rule` | **Out** | Generic standalone mapping is not established; documented L7 path is Kubernetes-centric. |
| HTTP cookie persistence | **Out** | LoxiLB source-IP persistence is not cookie persistence. |
| `SOURCE_IP_PORT` | **Out initially** | LoxiLB `hash` is described as full 5-tuple hashing, not proven equivalent. |
| TLS-HELLO HealthMonitor | **Out** | No direct documented probe type. |
| TLS termination / `TERMINATED_HTTPS` | **Out** | No generic standalone Octavia mapping established. |
| Listener `connection_limit` | **Out until verified** | No equivalent established. |
| Listener `allowed_cidrs` | **Out until verified** | No equivalent established in examined core service mapping. |
| Listener timeout semantics | **Out until verified** | No exact mapping established. |
| Member `backup` | **Out until verified** | No equivalent established. |
| Member alternate `monitor_address` | **Out until verified** | Independent probe-address semantics not proven. |
| Flavor support | **Out** | No provider metadata model designed yet. |
| Availability-zone support | **Out** | Could map to placement later, but not established. |
| Generic automatic horizontal scaling | **Out as a driver claim** | Requires provider placement/capacity/reconciliation infrastructure. |
| Hitless active-active existing-flow failover | **Out as a claim** | Not evidenced by the active-active HA documentation. |

---

# 6. MVP deployment assumptions

The resource mapper should not hard-code a per-LB VM architecture.

The source material recommends treating LoxiLB as a shared external dataplane with provider-side orchestration. The MVP implementation should therefore keep this boundary:

```text
Octavia
   ↓
LoxiLB Provider Driver
   ↓
provider desired-state / reconciliation layer
   ↓
preconfigured LoxiLB node or node pool
```

For the **first functional vertical slice**, it is acceptable to validate against a single preconfigured LoxiLB instance as long as the code and data model do not assume:

```text
one Octavia LoadBalancer = one LoxiLB VM
```

The later HA acceptance profile can use:

```text
active-active BGP/ECMP
```

or:

```text
active-backup
```

as an explicit provider-infrastructure topology.

BGP, ECMP, node placement and connection synchronization are not Octavia `Pool`/`Member` resources and should remain outside the resource translators.

---

# 7. VIP ownership decision required before coding

The MVP must explicitly choose one of the designs documented by the Octavia architecture.

## Option A — Octavia owns the Neutron VIP port

```text
Octavia
   ↓
Neutron VIP port
```

The LoxiLB Provider Driver does not implement provider-specific `create_vip_port()` behavior and uses the VIP supplied by Octavia.

## Option B — provider owns the Neutron VIP port

```text
LoxiLB Provider
   ↓
Neutron VIP port
```

This requires explicit provider networking logic.

### Recommended MVP bias

Prefer the architecture with the **least provider-specific Neutron ownership** unless the target LoxiLB topology proves it cannot work. The final decision must be validated in the OpenStack lab and recorded as an ADR.

Do not let VIP ownership emerge accidentally from code.

---

# 8. Status contract is part of the MVP

The driver is incomplete if traffic works but Octavia statuses are wrong.

## Provisioning status

Represents whether desired configuration was realized:

```text
PENDING_CREATE / PENDING_UPDATE / PENDING_DELETE
        ↓
backend reconciliation
        ↓
ACTIVE or ERROR
```

Do not mark `ACTIVE` merely because an HTTP request was accepted.

`ACTIVE` should mean the provider has verified the intended LoxiLB configuration according to its defined consistency model.

## Operating status

Represents observed health.

Examples:

```text
Member configured and healthy:
provisioning_status = ACTIVE
operating_status    = ONLINE

Member configured but probe failing:
provisioning_status = ACTIVE
operating_status    = ERROR/OFFLINE
```

The provider must define aggregation from Members to Pool, Listener and LoadBalancer.

---

# 9. Capability-validation contract

Before enabling an option, the provider must be able to answer:

```text
Can LoxiLB represent it?
Can the representation preserve Octavia semantics?
Can the provider observe/verify the realized state?
Can the provider recover idempotently after an ambiguous failure?
Can the provider report correct provisioning and operating status?
```

If any answer is no or unknown, the option stays unsupported.

---

# 10. MVP definition of done

The Provider Driver MVP is complete when all of the following are reproducibly demonstrated.

## Control plane

- `provider=loxilb` is selectable in Octavia.
- The five target resource types can be created, updated and deleted for the supported subset.
- Unsupported combinations are explicitly rejected.
- Operations tolerate retries without creating duplicate backend state.
- Desired state can be reconstructed without relying on a fragile process-local mapping only.
- LoxiLB state is verified before final Octavia provisioning status is reported.

## Dataplane

- TCP VIP traffic reaches the configured backend Members.
- Round Robin behaves as expected.
- Member add/remove/update changes realized traffic behavior.
- A supported health monitor removes an unhealthy backend from selection.

## Status

- Provisioning success/failure is reported correctly.
- Member health is reflected in operating status.
- Aggregate Pool/Listener/LB status rules are documented and tested.

## Management plane

- LoxiLB API is reachable only through the intended management path.
- TLS/authentication are enabled for the provider integration.
- Timeouts, retries and ambiguous outcomes are handled through reconciliation.

## Architecture

- The implementation does not assume a 1:1 Octavia resource ↔ LoxiLB object model.
- The implementation does not assume one LoxiLB VM per Octavia LB.
- BGP/ECMP/HA logic is kept as provider infrastructure, not mis-modeled as Octavia resources.

---

# 11. Recommended implementation order

```text
1. Pin LoxiLB + OpenStack/Octavia target versions.
2. Validate LoxiLB REST service CRUD and read-back behavior.
3. Decide VIP ownership.
4. Define deterministic synthesized-service identity.
5. Implement/read LoxiLB client contract.
6. Implement desired-service translator for:
      LB VIP + TCP Listener + RR Pool + Members.
7. Implement reconciliation + verification.
8. Implement Octavia status callbacks.
9. Add TCP HealthMonitor.
10. Add delete/update/idempotency failure tests.
11. Add member_batch_update.
12. Add UDP.
13. Add LC.
14. Add SOURCE_IP only after persistence validation.
15. Add HTTP/HTTPS HM only after semantic validation.
16. Add HA/BGP/ECMP provider-infrastructure profile.
```

---

# 12. Final MVP statement

The recommended first Provider Driver should be intentionally narrow:

> **An L4 Octavia provider that maps a LoadBalancer VIP + TCP/UDP Listener + default Pool + Members + a validated HealthMonitor subset into reconciled LoxiLB service rules, supports explicit compatible algorithms, and correctly synchronizes provisioning/operating status.**

The MVP should optimize for semantic correctness and recoverability, not Amphora feature parity.
