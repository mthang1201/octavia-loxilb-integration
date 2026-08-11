# RESOURCE_MAPPING.md

## 1. Purpose

This document defines a **conceptual mapping** between the Octavia logical resource model and the LoxiLB service/API model described in:

- `OCTAVIA_ARCHITECTURE.md`
- `LOXILB_ARCHITECTURE.md`

It deliberately does **not** define implementation code or assume LoxiLB objects that are not evidenced by the source material.

The most important architectural fact is:

```text
Octavia is hierarchical:

LoadBalancer (VIP)
  └── Listener (protocol + frontend port)
        └── Pool (algorithm + persistence)
              ├── Member (address + backend port + weight)
              └── HealthMonitor

LoxiLB is flatter:

Service / load-balancer rule
  = VIP/external IP
  + protocol
  + frontend port
  + selection algorithm
  + endpoint list
  + service/NAT mode
  + endpoint probing configuration
```

Therefore the Provider Driver is not merely translating five independent Octavia resources into five independent LoxiLB resources. In the core L4 model, it must **synthesize and reconcile one or more LoxiLB service rules from the combined Octavia resource tree**.

---

## 2. Classification

| Classification | Meaning |
|---|---|
| **DIRECT** | The Octavia field/semantic has a close native LoxiLB equivalent. |
| **ADAPTER** | The semantic can be represented, but requires translation, composition, identity tracking, validation, or reconciliation. |
| **UNSUPPORTED** | The source material provides enough evidence that the requested Octavia semantic should not be exposed in the initial L4 provider. |
| **UNCLEAR / VERIFY** | The source material does not establish semantic equivalence strongly enough; lab/API validation is required before support is claimed. |

A resource can have one **primary resource-level classification** while individual fields have different classifications.

---

## 3. Summary mapping

| Octavia resource | Closest LoxiLB representation | Primary classification | Main reason |
|---|---|---|---|
| `LoadBalancer` | VIP / `externalIP` shared by one or more LoxiLB service rules | **ADAPTER** | LoxiLB does not evidence a 1:1 top-level object equivalent to the Octavia `LoadBalancer`; the VIP is native, but LB identity, placement, lifecycle and status are provider concepts. |
| `Listener` | Service frontend tuple: `externalIP + protocol + port` | **ADAPTER** | Listener fields map closely, but the LoxiLB frontend is part of a complete service rule rather than an independent Listener object. |
| `Pool` | Service selection algorithm + endpoint set | **ADAPTER** | No independent backend-group object is established in the examined LoxiLB core model; pool semantics are embedded in the service rule. |
| `Member` | LoxiLB endpoint: `endpointIP + targetPort [+ weight]` | **ADAPTER**, with direct field mapping | Address and port are close native mappings, but the endpoint is nested inside a service rule and Octavia UUID/lifecycle semantics require reconciliation. |
| `HealthMonitor` | LoxiLB endpoint probe configuration + endpoint health | **ADAPTER / PARTIAL** | Several probe types map, but retry, timeout, expected-code and alternate-monitor-address semantics are not fully 1:1. |

---

# 4. LoadBalancer mapping

## 4.1 Octavia semantic

`LoadBalancer` is the top-level logical service and owns the VIP context.

Important fields include:

```text
loadbalancer_id
project_id
vip_address
vip_network_id
vip_subnet_id
vip_port_id
provider
flavor
availability_zone
admin_state_up
```

An Octavia `LoadBalancer` does **not** inherently mean one VM or one appliance.

## 4.2 Closest LoxiLB representation

The directly mappable data is primarily:

```text
Octavia LoadBalancer.vip_address
        ↓
LoxiLB externalIP / VIP
```

However, a LoxiLB service rule also needs Listener, Pool and Member information. One Octavia LB with multiple listeners therefore conceptually becomes:

```text
Octavia LoadBalancer VIP = 10.10.0.100
    ├── Listener TCP:80  ──→ LoxiLB service rule 10.10.0.100/TCP/80
    └── Listener TCP:443 ──→ LoxiLB service rule 10.10.0.100/TCP/443
```

The VIP is shared; the service rules are distinct.

## 4.3 Field assessment

| Octavia field / concept | LoxiLB equivalent | Assessment | Notes |
|---|---|---|---|
| `vip_address` | `externalIP` / VIP | **DIRECT** | Strong conceptual equivalence. |
| `loadbalancer_id` | No proven native UUID equivalent | **ADAPTER** | Provider needs durable correlation/mapping. |
| `project_id` | No corresponding tenant identity established in core LoxiLB service model | **ADAPTER** | Provider-side ownership/isolation metadata. |
| `vip_network_id` | No direct LoxiLB service field established | **ADAPTER** | Neutron/provider-infrastructure concern. |
| `vip_subnet_id` | No direct LoxiLB service field established | **ADAPTER** | Neutron/provider-infrastructure concern. |
| `vip_port_id` | No direct LoxiLB service field established | **ADAPTER** | Depends on VIP ownership design. |
| `provider` | Provider selection is Octavia-side | **UNSUPPORTED as a LoxiLB field** | Not something to translate southbound. |
| `flavor` | No mapping established | **UNCLEAR / VERIFY** | Defer unless provider-specific flavor metadata is designed. |
| `availability_zone` | No direct mapping established | **UNCLEAR / VERIFY** | Could later map to node placement, but that is provider infrastructure. |
| `admin_state_up` | Exact service enable/disable primitive not established | **UNCLEAR / VERIFY** | Must not silently map to delete unless explicitly designed. |

## 4.4 Resource-level verdict

**Primary classification: ADAPTER.**

The VIP is direct, but the Octavia LoadBalancer object itself is a **logical ownership/lifecycle envelope** around one or more LoxiLB service rules.

The provider must decide separately:

- who owns the Neutron VIP port,
- which LoxiLB node(s) realize the LB,
- how multiple listeners share the VIP,
- how the LB UUID is correlated with backend rules,
- how aggregate operating status is calculated.

---

# 5. Listener mapping

## 5.1 Octavia semantic

A Listener identifies the frontend protocol and port on a LoadBalancer VIP.

Core fields include:

```text
listener_id
loadbalancer_id
protocol
protocol_port
default_pool_id
connection_limit
allowed_cidrs
TLS configuration
timeouts
admin_state_up
```

## 5.2 Closest LoxiLB representation

For the L4 subset:

```text
LoadBalancer.vip_address
+ Listener.protocol
+ Listener.protocol_port
        ↓
LoxiLB service frontend tuple
externalIP + protocol + port
```

Example:

```text
Octavia:
VIP      = 10.10.0.100
protocol = TCP
port     = 80

LoxiLB service:
externalIP = 10.10.0.100
protocol   = tcp
port       = 80
```

## 5.3 Field assessment

| Octavia field / concept | LoxiLB equivalent | Assessment | Notes |
|---|---|---|---|
| `protocol=TCP` | `protocol=tcp` | **DIRECT** | Recommended MVP protocol. |
| `protocol=UDP` | `protocol=udp` | **DIRECT**, release validation required | LoxiLB source architecture says UDP is supported; target Octavia release must also be confirmed. |
| `protocol=SCTP` | `protocol=sctp` | **DIRECT-ish / VERIFY** | LoxiLB documents SCTP; MVP can defer. |
| `protocol_port` | service frontend `port` | **DIRECT** | Strong mapping. |
| `listener_id` | No proven native independent listener ID | **ADAPTER** | Correlate to synthesized LoxiLB service rule. |
| `loadbalancer_id` | VIP / provider mapping context | **ADAPTER** | Needed to obtain the VIP and placement. |
| `default_pool_id` | Pool data folded into same LoxiLB service rule | **ADAPTER** | The rule must be rebuilt/reconciled when pool membership changes. |
| `connection_limit` | No equivalent established | **UNCLEAR / VERIFY** | Reject until proven. |
| `allowed_cidrs` | No equivalent established in examined service mapping | **UNCLEAR / VERIFY** | Do not claim support initially. |
| TLS termination | No generic standalone Octavia mapping established | **UNSUPPORTED in L4 MVP** | TCP pass-through is not TLS termination. |
| HTTP/L7 listener semantics | L7 documented mainly via Kubernetes Gateway/Ingress | **UNSUPPORTED in L4 MVP** | Do not equate TCP:80 with Octavia HTTP semantics. |
| listener timeouts | No exact mapping established | **UNCLEAR / VERIFY** | Defer. |
| `admin_state_up` | Exact enable/disable primitive not established | **UNCLEAR / VERIFY** | Requires explicit semantics. |

## 5.4 Resource-level verdict

**Primary classification: ADAPTER.**

The frontend tuple maps closely, but a Listener cannot be created independently in LoxiLB without the rest of the service rule. The translator/reconciler should therefore treat a Listener as one input to the desired LoxiLB service object.

---

# 6. Pool mapping

## 6.1 Octavia semantic

A Pool groups backend Members and defines distribution/session-persistence policy.

Relevant fields include:

```text
pool_id
protocol
lb_algorithm
members
healthmonitor
session_persistence
TLS backend configuration
admin_state_up
```

## 6.2 Closest LoxiLB representation

The examined LoxiLB service model embeds:

```text
selection algorithm
+
endpoint list
```

inside the same service rule as the frontend tuple.

Therefore:

```text
Octavia Pool
  ├── algorithm
  └── members
       ↓
LoxiLB service
  ├── sel
  └── endpoints[]
```

No independent LoxiLB "pool/backend-group" object was established by the source material.

## 6.3 Algorithm mapping

| Octavia semantic | LoxiLB | Assessment | MVP decision |
|---|---|---|---|
| `ROUND_ROBIN` | `rr` | **DIRECT** | **Support first.** |
| `LEAST_CONNECTIONS` | `lc` | **DIRECT** | Support after RR vertical slice. |
| `SOURCE_IP` | `persist` | **DIRECT-ish / VERIFY** | Support only after persistence behavior/timeouts are validated. |
| `SOURCE_IP_PORT` | closest is `hash` over full 5-tuple | **UNCLEAR / semantic mismatch** | Reject initially. |
| weighted distribution | `wrr` + endpoint weights | **UNCLEAR / VERIFY** | Validate how Octavia weights select/affect WRR and weight=0. |
| HTTP cookie persistence | No L4 equivalent | **UNSUPPORTED in L4 MVP** | Reject. |

## 6.4 Other Pool fields

| Octavia field / concept | Assessment | Notes |
|---|---|---|
| `pool_id` | **ADAPTER** | Durable identity needed because there is no proven independent LoxiLB pool UUID. |
| `protocol` | **ADAPTER** | Must be compatible with Listener/service protocol. |
| `members` | **ADAPTER** | Members become endpoint list entries. |
| `healthmonitor` | **ADAPTER / PARTIAL** | Probe configuration is folded into backend behavior. |
| `session_persistence` | **PARTIAL** | Source-IP persistence is plausible; cookie-based persistence is not. |
| backend TLS configuration | **UNSUPPORTED / UNCLEAR for MVP** | No generic Octavia backend-TLS mapping established. |
| `admin_state_up` | **UNCLEAR / VERIFY** | Exact backend-group disable semantics not established. |

## 6.5 Resource-level verdict

**Primary classification: ADAPTER.**

The Provider Driver must reconstruct the desired LoxiLB service rule whenever Pool algorithm, persistence, Members, or HealthMonitor changes.

For the first L4 MVP, the safest relationship is:

```text
one Listener
    ↓
one default Pool
    ↓
one LoxiLB service rule
```

Alternative pools selected by Octavia L7 policies are outside the initial scope.

---

# 7. Member mapping

## 7.1 Octavia semantic

A Member is one backend endpoint.

Core fields include:

```text
member_id
pool_id
address
protocol_port
subnet_id
weight
backup
monitor_address
monitor_port
admin_state_up
vnic_type
```

## 7.2 Closest LoxiLB representation

LoxiLB service definitions expose endpoint entries equivalent to:

```yaml
endpoints:
  - endpointIP: 10.0.1.11
    targetPort: 8080
    weight: 1
```

Thus the data mapping is:

```text
Member.address       -> endpointIP
Member.protocol_port -> targetPort
Member.weight        -> endpoint weight (verification required)
```

## 7.3 Field assessment

| Octavia field / concept | LoxiLB equivalent | Assessment | Notes |
|---|---|---|---|
| `address` | `endpointIP` | **DIRECT** | Strong mapping. |
| `protocol_port` | `targetPort` | **DIRECT** | Strong mapping. |
| `weight` | endpoint `weight` | **UNCLEAR / VERIFY** | LoxiLB has weights/WRR, but exact Octavia semantics, algorithm interaction and weight=0 behavior must be tested. |
| `member_id` | No proven endpoint UUID | **ADAPTER** | Correlate Octavia UUID to endpoint identity. |
| `pool_id` | Parent service-rule context | **ADAPTER** | Needed to find which service rule to reconcile. |
| `subnet_id` | No direct endpoint field established | **ADAPTER** | Connectivity/Neutron concern, not dataplane service identity. |
| `backup` | No equivalent established | **UNCLEAR / VERIFY** | Reject until proven. |
| `monitor_address` | Alternate probe-IP behavior not proven | **UNCLEAR / VERIFY** | Important health-monitor gap. |
| `monitor_port` | LoxiLB `probeport` | **DIRECT-ish** | Close mapping; verify precedence and defaults. |
| `admin_state_up` | No exact endpoint drain/disable behavior established | **UNCLEAR / VERIFY** | Do not equate to deletion without design evidence. |
| `vnic_type` | No service endpoint equivalent | **ADAPTER / provider infra** | Connectivity/capability validation concern. |

## 7.4 Resource-level verdict

**Primary classification: ADAPTER, with the strongest direct field mapping of the five resources.**

Member address/port are native endpoint concepts. The main adapter work is:

- stable identity,
- endpoint list reconciliation,
- algorithm/weight interaction,
- member health/status synchronization,
- connectivity validation.

For robustness, `member_batch_update()` is particularly suitable because LoxiLB naturally represents an endpoint **set** inside a service rule.

---

# 8. HealthMonitor mapping

## 8.1 Octavia semantic

A HealthMonitor defines how Members are tested and when they are considered healthy/unhealthy.

Common fields include:

```text
type
delay
timeout
max_retries
max_retries_down
url_path
expected_codes
monitor_port
```

Members can also expose alternate `monitor_address` and `monitor_port`.

## 8.2 LoxiLB probe surface established by the source

Documented probe types:

```text
ping
http
https
udp
tcp
sctp
none
```

Documented probe-related parameters include:

```text
request/path
expected/custom response string
probe port
period
retries
```

Active probing is disabled by default and must be explicitly enabled when LoxiLB is expected to perform health checking.

## 8.3 Type/field mapping

| Octavia HM type/field | LoxiLB | Assessment | MVP decision |
|---|---|---|---|
| TCP | `tcp` | **DIRECT-ish** | **Support first after lab validation.** |
| PING | `ping` | **DIRECT-ish** | Optional early support if target Octavia API/provider contract permits it. |
| HTTP | `http` | **ADAPTER** | Validate path, success criteria and timeout behavior before enabling. |
| HTTPS | `https` | **ADAPTER** | Same as HTTP plus TLS behavior validation. |
| UDP-CONNECT | `udp` | **UNCLEAR / VERIFY** | Exact success semantics must be tested. |
| SCTP | `sctp` | **DIRECT-ish / VERIFY** | Defer from first MVP. |
| TLS-HELLO | No exact documented primitive | **UNSUPPORTED / NOT EVIDENCED** | Reject initially. |
| `delay` | probe period | **DIRECT-ish** | Verify units, minimums and scheduling behavior. |
| `timeout` | No clean 1:1 public field established | **UNCLEAR / VERIFY** | Do not claim exact support yet. |
| `max_retries_down` | retries | **PARTIAL** | Verify fall/down threshold semantics. |
| `max_retries` | No distinct success/rise threshold established | **UNCLEAR / VERIFY** | Potential semantic gap. |
| `url_path` | request / `probereq` | **DIRECT-ish** | Verify request format. |
| `expected_codes` | custom response string, not clearly HTTP status-code range syntax | **UNCLEAR / semantic mismatch** | Reject complex code ranges until verified. |
| `monitor_port` | `probeport` | **DIRECT-ish** | Verify override/default rules. |
| Member `monitor_address` | No independent alternate probe address proven | **UNCLEAR / VERIFY** | Do not expose initially unless validated. |

## 8.4 Status mapping

LoxiLB exposes endpoint health, but Octavia owns status semantics.

Conceptually:

```text
LoxiLB endpoint health
        ↓
provider reconciler
        ↓
DriverLibrary.update_loadbalancer_status(...)
        ↓
Octavia Member / Pool / Listener / LB operating_status
```

A failed health check should not imply provisioning failure:

```text
Member provisioning_status = ACTIVE
Member operating_status    = ERROR/OFFLINE
```

if the requested configuration is correctly installed but the backend is unhealthy.

## 8.5 Resource-level verdict

**Primary classification: ADAPTER / PARTIAL.**

HealthMonitor support must be capability-driven. The driver should reject unsupported semantics with `UnsupportedOptionError` rather than silently converting one monitor type or threshold behavior into another.

---

# 9. Composite mapping: the actual object synthesized for LoxiLB

For the recommended L4 default-pool path:

```text
Octavia
─────────────────────────────────────────────
LoadBalancer.vip_address        10.10.0.100
Listener.protocol               TCP
Listener.protocol_port          80
Pool.lb_algorithm               ROUND_ROBIN
Member A                        10.0.1.11:8080
Member B                        10.0.1.12:8080
HealthMonitor                   TCP / delay=5 / ...

                    │
                    │ Provider translation
                    ▼

LoxiLB conceptual service rule
─────────────────────────────────────────────
externalIP                     10.10.0.100
protocol                       tcp
port                           80
sel                            rr
endpoints:
  - endpointIP                 10.0.1.11
    targetPort                 8080
  - endpointIP                 10.0.1.12
    targetPort                 8080
probe                          tcp
probe period / retry settings  translated subset
```

This synthesized rule is the central unit of desired-state reconciliation.

---

# 10. Lifecycle consequences of the flat LoxiLB model

Because several Octavia resources contribute to the same LoxiLB service rule, CRUD callbacks cannot be treated as isolated backend object CRUD.

Examples:

```text
listener_create
    → may create an incomplete desired service until a Pool exists

pool_update
    → may require rebuilding the service selection configuration

member_create
    → changes the endpoint set of an existing service rule

health_monitor_update
    → changes probing behavior associated with that service/endpoints
```

The source material proves LoxiLB create/get/delete API surfaces, but does not establish a first-class atomic update primitive for every Octavia field. Therefore the safe conceptual contract is:

```text
Octavia resource mutation
        ↓
recompute desired synthesized LoxiLB service
        ↓
read observed service
        ↓
create / replace / reconcile as supported
        ↓
verify realized state
        ↓
update Octavia provisioning_status
```

---

# 11. What is not a direct Octavia-resource mapping

The following important LoxiLB capabilities are **provider infrastructure**, not first-class Octavia `LoadBalancer` / `Listener` / `Pool` / `Member` / `HealthMonitor` objects:

```text
BGP
ECMP
LoxiLB node placement
service replication across nodes
active-active / active-backup topology
HA role management
connection-state synchronization
node health
configuration fan-out
cluster reconciliation
```

They belong below/around the Provider Driver:

```text
Octavia logical resources
        ↓
Provider Driver
        ↓
Provider cluster manager / reconciler
        ↓
one or more LoxiLB nodes
        ↓
BGP / ECMP / HA
```

Do not attempt to model BGP or a LoxiLB node as an Octavia Pool or Member.

---

# 12. Mapping contract for the first implementation phase

The safest first semantic contract is:

```text
LoadBalancer
  = one Octavia VIP and ownership boundary

Listener
  = one L4 frontend tuple on that VIP

Pool
  = one default backend set + supported algorithm

Member
  = one endpoint IP:port

HealthMonitor
  = one supported probe policy for the Pool

Composite result
  = one LoxiLB service rule per Listener/default-Pool path
```

Initially reject or defer:

```text
generic L7Policy / L7Rule routing
cookie persistence
TLS termination
TLS-HELLO HM
SOURCE_IP_PORT unless exact semantics are proven
unsupported health-monitor fields
unsupported listener timeout/CIDR behavior
silent semantic fallback
```

---

# 13. Final mapping verdict

The correct conceptual model is:

```text
Octavia resource tree
        ↓
translation + capability validation
        ↓
synthesized LoxiLB service desired state
        ↓
LoxiLB REST API
        ↓
realized service + endpoint health
        ↓
status reconciliation back to Octavia
```

Only a subset of **fields** map directly. None of the five Octavia resources should be assumed to have a complete independent 1:1 LoxiLB object equivalent.

That is precisely why the Provider Driver needs a translation and reconciliation layer rather than five thin REST wrappers.
