# OPEN_QUESTIONS.md

## 1. Purpose

This file records questions that remain **unresolved or insufficiently evidenced** by `OCTAVIA_ARCHITECTURE.md` and `LOXILB_ARCHITECTURE.md`.

These are not implementation assumptions. They should be answered through:

```text
official API/source inspection
+
version-pinned standalone LoxiLB validation
+
OpenStack integration tests
+
HA/BGP lab tests where applicable
```

Each resolved question should eventually become one of:

```text
capability decision
ADR
test evidence
provider validation rule
status-mapping rule
```

---

# 2. Highest-priority blockers before implementation

## Q1. What exact LoxiLB version will be the provider contract target?

**Why it matters**

The architecture note explicitly warns that version pinning matters and that some current source flags are experimental.

**Need to establish**

```text
release/tag
container image digest
API schema version
Linux/kernel requirements
tested OpenStack/Octavia release
Python/octavia-lib version
```

**Required evidence**

Pinned release + recorded digest/commit + exported API schema.

---

## Q2. What is the exact REST identity of one LoxiLB service?

The source proves service create/get/delete surfaces and examples based on frontend data, but does not establish the final identity scheme needed by Octavia.

**Questions**

- Is a service uniquely identified by:
  - name,
  - `externalIP + protocol + port`,
  - another key?
- Can two services share the same VIP with different ports?
- Can two services share VIP+port with different protocol?
- Can a service carry provider-owned metadata or an Octavia UUID?
- How are duplicate creates reported?
- How is delete-not-found reported?

**Why it matters**

This determines idempotency and the mapping for `listener_id` / `pool_id`.

---

## Q3. What update operations are actually atomic and stable?

The architecture note explicitly does not assume first-class `PUT/PATCH` semantics for every field.

**Validate separately**

```text
change algorithm
add member
remove member
change member port
change member weight
change health monitor
change frontend port
change protocol
change VIP
```

**Questions**

- Is in-place update supported?
- Does the service need delete+recreate?
- Is replacement traffic-disruptive?
- Is there a safe read-modify-write model?
- What happens if a request times out after the backend already changed?

**Output**

A per-field update strategy:

```text
PATCH
replace service
reject immutable change
```

---

## Q4. Who owns the Neutron VIP port?

Octavia supports two architectural choices.

```text
A. Octavia creates/manages VIP port
B. LoxiLB provider creates/manages VIP port
```

**Need to validate**

- target Neutron topology,
- VIP reachability to LoxiLB nodes,
- allowed-address-pair / routing requirements,
- BGP advertisement model,
- tenant network connectivity,
- delete/failure cleanup.

**Output**

Architecture Decision Record before Provider Driver implementation.

---

## Q5. What does one Octavia LoadBalancer correspond to operationally?

The sources explicitly reject the assumption that one LB must equal one VM.

Candidate models:

```text
A. one Octavia LB → one LoxiLB appliance
B. many Octavia LBs → shared LoxiLB cluster
C. many Octavia LBs → placement across LoxiLB node pools
D. hybrid sharding + replication
```

The recommended architecture leans toward a shared external node pool, but the concrete placement model remains provider design work.

**Need to establish**

- tenant isolation,
- capacity model,
- failure blast radius,
- service count limits,
- placement metadata,
- reconciliation ownership.

---

# 3. Resource mapping questions

## Q6. Can multiple Octavia Listeners safely share one VIP?

Expected conceptual model:

```text
VIP 10.10.0.100
  ├── TCP:80  → service rule A
  ├── TCP:443 → service rule B
  └── UDP:53  → service rule C
```

**Verify**

- tuple uniqueness,
- API create/delete behavior,
- rule collision behavior,
- BGP/VIP advertisement behavior when one of several services is removed.

---

## Q7. Is one default Pool per Listener the only safe initial mapping?

The LoxiLB core service model is flatter than Octavia.

**Questions**

- Is there any standalone backend-group object independent of a frontend service?
- Can one endpoint group be reused by multiple frontend services?
- Does changing Pool membership require rewriting the whole service?
- Can an Octavia Pool without a Listener be represented meaningfully?

**MVP expectation**

Use one Listener → one default Pool → one LoxiLB service rule unless stronger API evidence is found.

---

## Q8. How should Octavia UUIDs be correlated with LoxiLB state?

Need durable mappings for:

```text
loadbalancer_id
listener_id
pool_id
member_id
healthmonitor_id
```

**Questions**

- Can UUIDs be stored in LoxiLB object names/metadata?
- Is frontend tuple identity sufficient?
- What if a user updates fields that are part of identity?
- Can state be fully reconstructed from Octavia desired state + live LoxiLB state?
- Is any provider database required?

**Constraint**

Do not make process-local JSON the sole authoritative source.

---

# 4. Listener capability questions

## Q9. Which Listener protocols are supported by the pinned target end-to-end?

LoxiLB architecture evidence supports L4 TCP/UDP/SCTP, but the provider must validate both sides.

**Test matrix**

```text
TCP
UDP
SCTP
HTTP
HTTPS
TERMINATED_HTTPS
```

**Expected initial decision**

```text
TCP → support
UDP → validate then support
SCTP → defer
HTTP/HTTPS as L7 semantics → defer
TERMINATED_HTTPS → reject initially
```

---

## Q10. Does LoxiLB have exact equivalents for Listener controls?

Fields needing validation:

```text
connection_limit
allowed_cidrs
timeouts
admin_state_up
```

For each, determine:

```text
native
adapter
unsupported
```

Do not emulate `admin_state_up=False` as deletion unless that semantic choice is explicitly designed and accepted.

---

# 5. Pool and algorithm questions

## Q11. What exactly does LoxiLB `persist` guarantee?

The source describes source-IP affinity.

Need to validate:

- persistence key,
- persistence lifetime,
- behavior after member failure,
- behavior after member recovery,
- behavior across LoxiLB node failure,
- whether persistence state is local or synchronized.

**Why it matters**

Only then can Octavia `SOURCE_IP` be exposed safely.

---

## Q12. Is LoxiLB `hash` equivalent to Octavia `SOURCE_IP_PORT`?

Current evidence says LoxiLB hashes the incoming **5-tuple**, so equivalence is not established.

**Expected default**

Reject `SOURCE_IP_PORT` unless exact Octavia semantics can be preserved.

---

## Q13. How do member weights interact with `rr` and `wrr`?

Need to establish:

- Does any non-default weight automatically require `wrr`?
- Does `rr` ignore endpoint weights?
- What is the accepted weight range?
- What does weight `0` mean?
- How do weight changes affect existing connections?
- How does this map to Octavia's Member `weight` contract?

Until answered, weighted Members should not be advertised as supported.

---

# 6. Member questions

## Q14. What is the stable identity of a LoxiLB endpoint?

Possible identity:

```text
endpointIP + targetPort
```

Need to test:

- duplicate endpoint behavior,
- same IP with multiple ports,
- changing port/address,
- endpoint deletion behavior,
- whether endpoint order matters.

---

## Q15. How should `admin_state_up=False` work for a Member?

Possible semantics:

```text
disable endpoint but retain config
drain existing connections
remove endpoint from selection
delete endpoint
```

The source does not establish a 1:1 primitive.

Do not expose this until exact behavior is defined.

---

## Q16. Is Octavia Member `backup` representable?

No equivalent is established in the source material.

Determine whether LoxiLB has:

```text
backup-only endpoint
priority endpoint
primary/secondary backend semantics
```

If not, reject the option.

---

## Q17. How do `subnet_id` and `vnic_type` affect backend reachability?

These are not direct LoxiLB endpoint fields but may be critical in OpenStack.

Validate:

- route path from each LoxiLB node to Members,
- tenant isolation,
- overlapping tenant CIDRs,
- VLAN/VXLAN/Geneve topology,
- security groups,
- MTU,
- provider networks,
- supported vNIC types.

This is a provider-infrastructure/networking concern, not a field to silently discard.

---

# 7. HealthMonitor questions

## Q18. What exact REST fields configure LoxiLB probes?

Need version-pinned API evidence for:

```text
probe type
period
timeout
retries
request/path
expected response
probe port
enable/disable monitoring
```

CLI/documentation terminology is not enough for a production REST client contract.

---

## Q19. How do LoxiLB retry semantics map to Octavia rise/fall semantics?

Octavia distinguishes:

```text
max_retries
max_retries_down
```

The LoxiLB documentation establishes `retries` but not a clean distinct pair.

Need to determine:

- failures before DOWN,
- successes before UP,
- whether thresholds are independently configurable,
- state-transition timing.

If not independently configurable, document the semantic gap and restrict accepted options.

---

## Q20. What is the exact timeout semantic?

The architecture note states timeout logic exists but no clean 1:1 CLI/API field was established.

Validate:

- per probe timeout,
- connection timeout versus total request timeout,
- units,
- defaults,
- relationship with probe period.

---

## Q21. How should HTTP `expected_codes` map?

LoxiLB documentation mentions a custom expected/response string, not clearly Octavia's HTTP status-code syntax/ranges.

Need to test:

```text
200
200,202
200-204
301
body string versus status code
```

Do not expose Octavia `expected_codes` until exact equivalence is known.

---

## Q22. Can `monitor_address` differ from Member `address`?

Octavia can model an alternate monitoring address.

Need to prove whether LoxiLB can probe:

```text
traffic endpoint = 10.0.1.11
monitor endpoint = 10.0.2.11
```

independently.

If not, reject alternate `monitor_address`.

---

## Q23. What are UDP-CONNECT success semantics?

LoxiLB has a `udp` probe, but equivalence with Octavia UDP-CONNECT is not established.

Need packet-level validation.

---

## Q24. Is TLS-HELLO supported by any standalone primitive?

Current architecture says no exact documented probe type.

Expected decision: reject unless direct source/API evidence is found.

---

# 8. Provisioning and operating status questions

## Q25. What exact condition means `provisioning_status=ACTIVE`?

Required design rule:

```text
HTTP 2xx accepted
    ≠ ACTIVE

desired service verified on required LoxiLB node(s)
    = ACTIVE
```

Need to define consistency by topology:

```text
single node:
  verified on node 1

active-backup:
  verified on active + required standby?

active-active:
  verified on all assigned nodes?
  quorum?
```

This directly affects Octavia lifecycle semantics.

---

## Q26. How should LoxiLB endpoint health map to Member operating status?

Need an explicit table for:

```text
healthy
unhealthy
unknown
monitor disabled
probe initializing
administratively disabled
```

to Octavia values such as:

```text
ONLINE
OFFLINE
ERROR
NO_MONITOR
DRAINING
```

Use only statuses supported by the target Octavia contract.

---

## Q27. How should status aggregate upward?

Define deterministic rules for:

```text
Members → Pool
Pool → Listener
Listeners → LoadBalancer
```

Examples to decide:

- one of three Members unhealthy,
- all Members unhealthy,
- no HealthMonitor configured,
- service configured on only one of two required LoxiLB nodes,
- BGP route withdrawn but service rule still present.

---

# 9. Idempotency and reconciliation questions

## Q28. What happens after an ambiguous API timeout?

Scenario:

```text
Provider → create service
LoxiLB successfully creates it
response is lost
Provider retries
```

Need to prove the retry does not create duplicate or conflicting state.

Test this for:

```text
create
update/replace
delete
member changes
health-monitor changes
```

---

## Q29. Can desired state be fully reconstructed?

Preferred model:

```text
Octavia = desired state
LoxiLB   = realized state
```

Need to prove the provider can recover after:

```text
provider restart
driver-agent restart
local cache loss
LoxiLB node restart
partial node failure
```

without a fragile mapping file as sole source of truth.

---

## Q30. How is drift detected across multiple LoxiLB nodes?

For shared/HA deployment:

```text
node 1: correct service
node 2: stale service
node 3: missing service
```

Need to define:

- observed-state collection,
- desired fan-out,
- retry policy,
- repair ordering,
- Octavia provisioning/operating status during partial drift.

---

# 10. HA, BGP and scale-out questions

## Q31. Which HA profile will be the first supported deployment profile?

Candidates from the LoxiLB architecture:

```text
single node
active-backup
BGP active-backup
BGP ECMP active-active
```

The resource mapping should remain the same; the provider infrastructure changes.

Need an ADR choosing the first production-oriented profile.

---

## Q32. Who owns HA role election in OpenStack?

The documented Kubernetes scenarios assign some role/health behavior to `kube-loxilb`.

Without Kubernetes, define who performs:

```text
node health
active role selection
fencing
service placement
config replication
failover workflow
```

Candidate answer: provider cluster manager / external HA manager.

This must not be assumed to be automatic LoxiLB core behavior.

---

## Q33. Who configures BGP peers and VIP advertisements?

BGP is core-capable, but automatic K8s peering is Kubernetes-specific.

Define:

- pre-provisioned BGP versus provider-managed BGP,
- peer credentials/config,
- route-policy ownership,
- service/VIP advertisement lifecycle,
- route withdrawal on delete/failure.

---

## Q34. What happens to existing TCP flows when an active-active node fails?

The LoxiLB architecture explicitly says active-active ECMP does **not** prove connection-state synchronization among all active nodes.

Measure:

```text
new-flow continuity
existing-flow reset rate
packet loss
BGP convergence
ECMP rehash behavior
```

Do not claim hitless active-active failover before this test.

---

## Q35. What exactly is synchronized in active-backup mode?

Separate:

```text
desired service configuration
HA role state
connection/conntrack state
```

The source only establishes connection synchronization in documented external active-backup deployments; it is not a generic distributed configuration database.

Need to verify topology, NAT-mode and peer requirements.

---

## Q36. How will service placement and capacity work in a shared cluster?

For a cloud-scale provider, eventually define:

```text
which LB goes to which nodes
how many nodes per LB
capacity limits
tenant isolation
failure domains
AZ awareness
rebalance behavior
node add/remove behavior
```

Kubernetes service sharding should not be treated as a standalone OpenStack scheduler.

---

# 11. Security and management-plane questions

## Q37. What exact LoxiLB API authentication model will be used?

The source says the API is HTTP by default and current source includes authentication/user-management and TLS options.

Need to define:

```text
HTTPS configuration
certificate trust
credential storage
rotation
API user permissions
network ACL/security-group policy
```

Port `11111` must not be exposed to tenant networks.

---

## Q38. Is API TLS mutual authentication supported/required?

Need exact version-pinned evidence.

If not, determine acceptable OpenStack management-plane controls.

---

# 12. L7 and deferred capability questions

## Q39. Is there a stable standalone API for HTTP/HTTPS routing equivalent to Octavia L7Policy/L7Rule?

Current evidence only establishes L7 functionality clearly through Kubernetes Gateway API/Ingress components.

Need to investigate later:

```text
host routing
path routing
redirect
TLS termination
certificate lifecycle
header matching/modification
backend TLS
```

Until then:

```text
L7Policy/L7Rule = unsupported
```

---

## Q40. Can any Kubernetes-centric L7 component be reused without Kubernetes?

Do not assume yes.

This is a separate research phase, not part of the L4 MVP.

---

# 13. Statistics questions

## Q41. Which Octavia listener statistics can LoxiLB expose reliably?

Octavia `DriverLibrary` can accept:

```text
active_connections
bytes_in
bytes_out
request_errors
total_connections
```

Need to establish:

- what LoxiLB REST API exposes,
- per-service granularity,
- counter reset semantics,
- multi-node aggregation,
- polling cost.

Statistics are not required for the first semantic vertical slice but should be designed before benchmark/control-plane work.

---

# 14. Test matrix required before enabling a capability

Every candidate feature should graduate through:

```text
1. API/source evidence
2. standalone functional test
3. negative/invalid-input test
4. duplicate/retry/idempotency test
5. read-back/reconciliation test
6. Octavia end-to-end test
7. failure/restart test
8. HA test if multi-node behavior is relevant
```

A feature should be advertised by the Provider Driver only after this matrix proves semantic equivalence.

---

# 15. Recommended resolution order

Resolve in this order:

```text
1.  Q1  target versions
2.  Q2  service identity
3.  Q3  update semantics
4.  Q4  VIP ownership
5.  Q5  LB-to-cluster placement model
6.  Q8  UUID correlation
7.  Q6/Q7 Listener-Pool synthesis
8.  Q11-Q13 algorithms/weights
9.  Q18-Q24 health-monitor semantics
10. Q25-Q27 status semantics
11. Q28-Q30 idempotency/reconciliation
12. Q31-Q36 HA/BGP/scale-out
13. Q37-Q38 management security
14. Q39-Q40 L7
15. Q41 statistics
```

The first ten items are sufficient to begin a safe P0 Provider Driver implementation.

---

# 16. Exit criteria for this open-question phase

Before coding the core Provider Driver, the following must no longer be open:

```text
target versions
service identity
CRUD/update semantics
VIP ownership
first deployment/placement model
Octavia UUID correlation strategy
TCP service mapping
ROUND_ROBIN mapping
Member endpoint mapping
TCP HealthMonitor mapping
provisioning_status rule
basic operating_status rule
retry/idempotency behavior
management API security
```

Everything else can remain explicitly deferred as long as the Provider Driver rejects unsupported options correctly.
