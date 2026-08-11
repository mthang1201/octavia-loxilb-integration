# OpenStack Octavia Provider Architecture

## 0. Scope

This document describes the OpenStack Octavia architecture relevant to implementing an external Provider Driver, with particular focus on a future LoxiLB provider.

Primary references:

- OpenStack Octavia latest documentation.
- OpenStack Octavia API v2 reference.
- Upstream `openstack/octavia` source.
- Upstream `openstack/octavia-lib` source.
- Upstream `openstack/ovn-octavia-provider` source.

The important architectural principle is:

> Octavia owns the **load-balancing API and logical resource model**.  
> A Provider Driver owns the translation of that logical model into a particular load-balancing backend.

Octavia currently exposes provider drivers through a stable interface defined by `octavia-lib`.

---

# 1. Current Octavia Architecture

## 1.1 High-level architecture

```text
                   OpenStack User
                        │
                        │ REST / CLI / Horizon
                        ▼
                ┌─────────────────┐
                │   octavia-api   │
                │                 │
                │ Auth / RBAC     │
                │ Validation      │
                │ Quotas          │
                │ DB logical state│
                │ Provider select │
                └────────┬────────┘
                         │
                 provider=<name>
                         │
              ┌──────────┴───────────┐
              │                      │
              ▼                      ▼
       Amphora Provider       External Provider
              │                      │
              │                      │
        Oslo Messaging          Backend-specific
              │                 control mechanism
              ▼                      │
       octavia-worker                ▼
              │                  LoxiLB / OVN /
           TaskFlow              vendor appliance
              │
     ┌────────┼─────────┐
     ▼        ▼         ▼
   Nova    Neutron   Barbican
     │
     ▼
  Amphora VM
  HAProxy
```

The main Octavia control-plane processes documented by OpenStack are:

- `octavia-api`
- `octavia-worker`
- `octavia-health-manager`
- `octavia-housekeeping`
- `octavia-driver-agent`

The API receives load-balancing requests. The Controller Worker performs Amphora orchestration, the Health Manager monitors Amphora instances and performs failover, Housekeeping performs maintenance/cleanup, and the Driver Agent accepts status/statistics callbacks and can host optional provider agents.

Octavia uses several other OpenStack projects when operating the Amphora provider:

```text
Keystone   → authentication
Nova       → Amphora compute lifecycle
Neutron    → VIP and backend connectivity
Glance     → Amphora image
Barbican   → TLS secrets
Oslo       → messaging
TaskFlow   → workflow orchestration
```



### Important distinction for an external provider

The historical Octavia architecture diagrams often show:

```text
octavia-api
    ↓
octavia-worker
```

because this is the reference Amphora architecture.

The current Provider Driver path is more general:

```text
octavia-api
    ↓
Provider Driver
    ↓
provider-specific control plane
```

The current upstream API source loads the selected provider and directly invokes methods such as:

```text
loadbalancer_create()
loadbalancer_update()
loadbalancer_delete()
```

The Amphora implementation then sends work over Oslo messaging to the Octavia worker. An external provider is not required to use that mechanism.

---

# 2. Octavia Resource Model

The central logical hierarchy is:

```text
LoadBalancer
│
│  VIP
│
├── Listener :80/TCP
│     │
│     └── default Pool
│            │
│            ├── Member 10.0.1.11:8080
│            ├── Member 10.0.1.12:8080
│            └── Member 10.0.1.13:8080
│
└── Pool
      │
      └── HealthMonitor
```

The Octavia v2 API is fundamentally a logical model. Provisioning that model onto actual physical or virtual infrastructure may happen asynchronously.

---

## 2.1 LoadBalancer

A `LoadBalancer` is the top-level logical load-balancing service.

Important attributes include:

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

A load balancer has one primary VIP and may have additional VIPs.

The `provider` field determines which backend Provider Driver owns the LB for its lifetime.

Conceptually:

```text
LoadBalancer
    │
    └── VIP = 10.10.0.100
```

A LoadBalancer does **not** necessarily mean "one VM".

That interpretation is provider-specific:

```text
Amphora:
LoadBalancer → one or more Amphora VMs

OVN:
LoadBalancer → OVN logical configuration

LoxiLB:
LoadBalancer → TBD:
               per-LB appliance?
               shared cluster?
               node pool?
```

This distinction is fundamental for the LoxiLB architecture.

---

## 2.2 Listener

A `Listener` represents a frontend endpoint accepting client traffic.

Conceptually:

```text
VIP: 10.10.0.100
        │
        ▼
TCP :443
^^^^^^^^
Listener
```

Important attributes include:

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



A listener therefore answers:

> On which protocol and port does this load balancer accept traffic?

Examples:

```text
TCP :80
TCP :443
UDP :53
HTTP :80
TERMINATED_HTTPS :443
```

Whether a provider supports each protocol is provider-specific.

---

## 2.3 Pool

A `Pool` is a group of backend members plus the policy used to distribute traffic among those members.

Conceptually:

```text
Pool web-backends

algorithm = ROUND_ROBIN

├── server A
├── server B
└── server C
```

Typical pool properties include:

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

The Provider Driver must translate Octavia's requested algorithm/protocol into an equivalent supported by the backend.

Unsupported combinations must be explicitly rejected rather than silently approximated. The provider interface defines `UnsupportedOptionError` for this purpose.

---

## 2.4 Member

A `Member` is one backend endpoint in a pool.

Conceptually:

```text
Member
address       = 10.0.1.11
protocol_port = 8080
weight        = 10
```

Important attributes include:

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



Multiple Members form the backend set:

```text
Pool
├── 10.0.1.11:8080
├── 10.0.1.12:8080
└── 10.0.1.13:8080
```

---

## 2.5 HealthMonitor

A `HealthMonitor` specifies how Octavia's selected backend should determine whether members are healthy.

Example:

```text
type             = TCP
delay            = 5 s
timeout          = 3 s
max_retries      = 3
max_retries_down = 3
```

Supported Octavia monitor types include types such as TCP, HTTP, HTTPS, UDP-CONNECT, TLS-HELLO and others, although the actual subset depends on the provider.

Conceptually:

```text
Health Monitor
      │
      ├── probe Member A → healthy
      ├── probe Member B → unhealthy
      └── probe Member C → healthy
```

The load balancer backend should therefore stop selecting Member B.

### Important terminology

Do not confuse:

```text
HealthMonitor resource
```

with:

```text
Octavia Health Manager
```

They are different.

The first monitors **tenant pool members**.

The second is an Octavia daemon primarily responsible for monitoring **Amphora instances themselves**.

---

# 3. Where the Provider Driver Lives

The Provider Driver is part of the Octavia control path, immediately behind the Octavia API/provider-selection layer.

```text
User
 │
 ▼
Octavia REST API
 │
 │ provider="loxilb"
 ▼
Provider Driver Factory
 │
 ▼
LoxiLBProviderDriver
 │
 ▼
LoxiLB control plane
```

Provider drivers are loaded through `stevedore`.

Entry-point namespace:

```text
octavia.api.drivers
```

The name of the entry point becomes the provider name exposed to users.

Conceptually:

```text
amphora → AmphoraProviderDriver
ovn     → OvnProviderDriver
loxilb  → LoxiLBProviderDriver
```



The enabled providers are configured through:

```text
[api_settings]
enabled_provider_drivers
```

The current default provider is Amphora.

---

# 4. Generic LoadBalancer Lifecycle

The most important architectural fact is that Octavia separates:

```text
logical resource accepted
```

from:

```text
backend provisioning finished
```

Provider operations are therefore normally asynchronous from Octavia's point of view.

---

# 5. CREATE Lifecycle

## 5.1 Sequence flow

```text
User
 │
 │ POST /v2/lbaas/loadbalancers
 │ provider=loxilb
 ▼
octavia-api
 │
 ├─ authenticate / RBAC
 ├─ quota check
 ├─ API validation
 ├─ load provider driver
 │
 ├─ create logical DB record
 │    provisioning_status = PENDING_CREATE
 │    operating_status    = OFFLINE
 │
 ├─ determine VIP ownership
 │
 │   call:
 │   create_vip_port(...)
 │
 │       ┌─────────────────────────────────┐
 │       │ Provider implements it?         │
 │       ├─────────────────────────────────┤
 │       │ YES → Provider creates VIP port │
 │       │ NO  → Octavia creates via       │
 │       │       Neutron                   │
 │       └─────────────────────────────────┘
 │
 ├─ construct octavia-lib LoadBalancer
 │
 └─ call:
       loadbalancer_create(loadbalancer)
                │
                ▼
          LoxiLB Provider
                │
        accept / validate request
                │
                ▼
         provider backend
                │
       configure actual service
                │
        ┌───────┴────────┐
        │                │
      success          failure
        │                │
        ▼                ▼
      ACTIVE            ERROR
```

The current API source explicitly attempts `create_vip_port()` before invoking `loadbalancer_create()`. If the provider raises the provider `NotImplementedError`, Octavia creates the VIP port itself.

---

## 5.2 Status callback

Once actual backend provisioning finishes:

```text
Provider backend
      │
      ▼
Provider Driver / Provider Agent
      │
      │ DriverLibrary.update_loadbalancer_status(...)
      ▼
octavia-driver-agent
      │
      ▼
Octavia DB
```

Successful provisioning:

```text
PENDING_CREATE
      ↓
    ACTIVE
```

Failure:

```text
PENDING_CREATE
      ↓
     ERROR
```

Operating status should independently represent whether the resulting service is actually functioning.

---

# 6. UPDATE Lifecycle

Sequence:

```text
User
 │
 │ PUT resource
 ▼
octavia-api
 │
 ├─ validate resource is mutable
 ├─ lock logical resource
 ├─ provisioning_status = PENDING_UPDATE
 │
 ├─ obtain old resource representation
 ├─ obtain requested updated representation
 │
 └─ ProviderDriver.resource_update(
        old_resource,
        new_resource
    )
             │
             ▼
      Provider backend
             │
        apply changes
             │
      ┌──────┴───────┐
      ▼              ▼
   success          failure
      │              │
   ACTIVE           ERROR
```

For example:

```text
loadbalancer_update(old_loadbalancer, new_loadbalancer)

listener_update(old_listener, new_listener)

pool_update(old_pool, new_pool)

member_update(old_member, new_member)
```

Fields not included in an update are represented using octavia-lib's `Unset` model semantics.

---

# 7. DELETE Lifecycle

```text
User
 │
 │ DELETE LoadBalancer
 ▼
octavia-api
 │
 ├─ verify current provisioning status
 │
 ├─ reject if children exist
 │    unless cascade=True
 │
 ├─ provisioning_status
 │        = PENDING_DELETE
 │
 └─ loadbalancer_delete(
         loadbalancer,
         cascade
     )
            │
            ▼
       Provider backend
            │
       delete service
            │
       ┌────┴─────┐
       ▼          ▼
    success      failure
       │          │
    DELETED      ERROR
```

For cascade deletion, the provider is responsible for deleting the child resources as well.

---

# 8. provisioning_status vs operating_status

These represent two **orthogonal dimensions**.

## 8.1 provisioning_status

Answers:

> Did the control plane successfully apply the requested configuration?

Values include:

```text
PENDING_CREATE
PENDING_UPDATE
PENDING_DELETE
ACTIVE
ERROR
DELETED
```



Example:

```text
provisioning_status = ACTIVE
```

means:

```text
the last requested configuration was successfully provisioned
```

It does **not necessarily mean traffic is healthy**.

---

## 8.2 operating_status

Answers:

> What is the observed operational state of this resource?

Typical values include:

```text
ONLINE
OFFLINE
DEGRADED
ERROR
NO_MONITOR
DRAINING
```



---

## 8.3 Why both are required

Example:

```text
provisioning_status = ERROR
operating_status    = ONLINE
```

This is valid.

It can mean:

```text
The existing load balancer is still serving traffic,
but the latest requested configuration update failed.
```

OpenStack explicitly documents this distinction.

Another example:

```text
provisioning_status = ACTIVE
operating_status    = ERROR
```

means roughly:

```text
Configuration is synchronized successfully,
but the actual service/backend is not healthy.
```

---

## 8.4 PENDING status acts as a control-plane lock

A resource in a `PENDING_*` state is generally immutable.

```text
ACTIVE
   │
   │ user requests update
   ▼
PENDING_UPDATE
   │
   ├── successful → ACTIVE
   │
   └── failed     → ERROR
```

This prevents two control-plane mutations from racing against each other.

For a LoxiLB provider this is extremely important:

**Never mark the resource ACTIVE merely because the LoxiLB API accepted the HTTP request.**

`ACTIVE` should mean that the desired LoxiLB configuration has actually been successfully realized according to the provider's defined consistency model.

---

# 9. How the Amphora Provider Works

Amphora is Octavia's reference provider.

The basic architecture is:

```text
                     Octavia Control Plane

User
 │
 ▼
octavia-api
 │
 ▼
AmphoraProviderDriver
 │
 │ Oslo RPC cast
 ▼
octavia-worker
 │
 ▼
TaskFlow
 │
 ├── Nova
 ├── Neutron
 ├── Glance
 ├── Barbican
 │
 ▼
Amphora VM
 │
 ├── amphora-agent
 ├── HAProxy
 └── optional VRRP/HA components
```

The upstream Amphora Provider Driver's `loadbalancer_create()` converts the request into a payload and sends an asynchronous RPC `cast` to the controller worker.

The controller then uses TaskFlow to orchestrate the backend lifecycle. OpenStack's current controller documentation explicitly describes these workflows as TaskFlow flows.

---

## 9.1 Amphora dataplane

The reference Amphora is normally a VM image containing HAProxy.

```text
Client
 │
 ▼
VIP
 │
 ▼
Amphora VM
 │
 ▼
HAProxy
 │
 ├── Member A
 ├── Member B
 └── Member C
```

Octavia builds and stores the Amphora image in Glance and creates Amphora compute resources through Nova.

---

## 9.2 Amphora agent

The controller communicates with an agent inside the Amphora.

The reference interface is an HTTPS REST API protected using TLS and mutual certificate verification.

Operations include things such as:

```text
upload configuration
configure interfaces
configure VIP
reload HAProxy
start/stop services
```



---

## 9.3 Amphora health

Amphora instances send heartbeat/health information back toward the Octavia Health Manager.

The Health Manager detects Amphora failures and can initiate failover.

This represents infrastructure health:

```text
Is the load-balancing appliance alive?
```

which is separate from member HealthMonitor state:

```text
Is backend server 10.0.1.11 alive?
```

---

## 9.4 Amphora High Availability

An Active/Standby topology uses two Amphora instances with replicated load-balancing configuration and VRRP for VIP failover.

Conceptually:

```text
                  VIP
                   │
            VRRP active owner
                   │
       ┌───────────┴───────────┐
       │                       │
       ▼                       ▼
 Amphora A                  Amphora B
 ACTIVE                     STANDBY
 HAProxy                     HAProxy
```

This is fundamentally an **appliance-oriented architecture**.

---

# 10. How OVN Provider Differs from Amphora

OVN demonstrates why the Provider Driver abstraction matters.

## Amphora

```text
Octavia
   │
   ▼
Create dedicated compute resources
   │
   ▼
Amphora VM
   │
   ▼
HAProxy
```

## OVN

```text
Octavia
   │
   ▼
OVN Provider
   │
   ▼
OVN Northbound DB
   │
   ▼
ovn-northd
   │
   ▼
logical flows
   │
   ▼
ovn-controller
   │
   ▼
Open vSwitch datapath
```

The OVN provider writes load-balancer configuration to OVN's Northbound DB. `ovn-northd` turns this desired configuration into logical flows, and `ovn-controller` instances translate the flows into actual forwarding rules.

---

## 10.1 Architectural comparison

| Property | Amphora | OVN |
|---|---|---|
| Dedicated LB VM | Yes | No |
| Data plane | HAProxy | OVN/OVS flows |
| Per-LB appliance | Usually yes | No |
| Nova dependency for LB | Yes | No |
| LB management network | Yes | No Amphora mgmt network |
| L7 | Supported | Not supported |
| L4 | Supported | Supported |
| HA model | Amphora failover / VRRP | Distributed OVN dataplane |
| Explicit LB VM failover | Relevant | Not relevant |
| Provisioning speed | VM lifecycle involved | Configuration/flow update |
| Scaling model | Add/manage appliances | Distributed network dataplane |

The current OVN provider documentation explicitly highlights that no extra VM/container is required, and that OVN's load-balancing flows are distributed across nodes.

---

## 10.2 Current OVN limitations

The current official OVN provider documentation lists constraints including:

```text
TCP / UDP / SCTP only
no L7 load balancing
SOURCE_IP_PORT algorithm
TCP and UDP-CONNECT health monitoring
no Amphora-style failover
no Amphora-style flavor requirement
```



This is a useful model for LoxiLB development:

> A Provider Driver does not need feature parity with Amphora.

Instead:

```text
unsupported feature
       ↓
UnsupportedOptionError
or
NotImplementedError
```

must be returned correctly.

---

# 11. octavia-lib: Stable External Provider Interface

This is the most important dependency boundary for the LoxiLB Provider.

External drivers should restrict their Octavia interactions to:

```text
octavia_lib.api.drivers.data_models

octavia_lib.api.drivers.driver_lib

octavia_lib.api.drivers.exceptions

octavia_lib.api.drivers.provider_base

octavia_lib.common.constants
```

OpenStack explicitly states that other Octavia APIs are not considered stable/safe interfaces for provider drivers.

Therefore:

```text
GOOD

octavia_lib.*
```

versus:

```text
AVOID

octavia.db.*
octavia.controller.*
octavia.api.internal.*
octavia.common.data_models.*
```

for an external LoxiLB provider.

---

# 12. Important octavia-lib Interfaces

## 12.1 `provider_base.ProviderDriver`

Base contract implemented by a Provider Driver.

Important methods:

```text
create_vip_port()

loadbalancer_create()
loadbalancer_update()
loadbalancer_delete()
loadbalancer_failover()

listener_create()
listener_update()
listener_delete()

pool_create()
pool_update()
pool_delete()

member_create()
member_update()
member_delete()
member_batch_update()

health_monitor_create()
health_monitor_update()
health_monitor_delete()

l7policy_create()
l7policy_update()
l7policy_delete()

l7rule_create()
l7rule_update()
l7rule_delete()

get_supported_flavor_metadata()
validate_flavor()

get_supported_availability_zone_metadata()
validate_availability_zone()
```



---

## 12.2 `data_models`

Provider-facing representations of Octavia resources.

Important classes:

```text
LoadBalancer
Listener
Pool
Member
HealthMonitor
L7Policy
L7Rule
VIP

UnsetType / Unset
```



The Provider Driver should treat these as its northbound model.

Conceptually:

```text
Octavia API / DB models
        │
        ▼
octavia-lib data model
        │
        ▼
LoxiLB translator
        │
        ▼
LoxiLB API representation
```

---

## 12.3 `driver_lib.DriverLibrary`

This is the important south-to-north callback interface.

### Status callback

```text
update_loadbalancer_status(...)
```

Updates provisioning and operating status for a resource tree.

Supported resource categories include:

```text
loadbalancers
listeners
pools
members
healthmonitors
l7policies
l7rules
```



### Statistics callback

```text
update_listener_statistics(...)
```

Supports values including:

```text
active_connections
bytes_in
bytes_out
request_errors
total_connections
```



### Resource lookup

Current `DriverLibrary` also exposes resource retrieval methods including:

```text
get_loadbalancer()
get_listener()
get_pool()
get_member()
get_healthmonitor()
get_l7policy()
get_l7rule()
```



These can be especially valuable for reconciliation.

---

# 13. Exceptions

Important provider exceptions include:

```text
DriverError
NotImplementedError
UnsupportedOptionError
Conflict
```



Use them deliberately.

### `NotImplementedError`

Use when:

```text
This Provider Driver does not implement this API operation.
```

Example:

```text
L7 policy unsupported.
```

### `UnsupportedOptionError`

Use when:

```text
The operation exists,
but this particular configuration is unsupported.
```

Example:

```text
pool_create(
    protocol=TCP,
    lb_algorithm=LEAST_CONNECTIONS
)

LoxiLB provider supports TCP
but not LEAST_CONNECTIONS
```

Result:

```text
UnsupportedOptionError
```

rather than silently changing it to another algorithm.

---

# 14. Optional Provider Agent

An external provider may define a long-running provider agent.

Entry-point namespace:

```text
octavia.driver_agent.provider_agents
```

The agent runs under:

```text
octavia-driver-agent
```



Architecture:

```text
                   octavia-api
                       │
                       ▼
                 LoxiLB Driver
                       │
                       ▼
                     API
                       │
                       ▼
                  LoxiLB cluster


octavia-driver-agent
        │
        └── LoxiLB provider agent
                  │
                  ├── periodic reconciliation
                  ├── backend health/status polling
                  ├── events
                  └── statistics
```

Provider agents are explicitly **optional**.

For LoxiLB, however, some long-running reconciliation mechanism will probably be useful.

---

# 15. What Methods Must a LoxiLB Provider Implement?

There are two different answers.

## 15.1 Strict interface answer

`ProviderDriver` exposes the full provider interface.

A driver does **not** have to pretend that every feature is supported.

Unsupported operations are allowed to return:

```text
NotImplementedError
```



Therefore there is no useful rule saying:

> "Every provider must implement every method."

---

## 15.2 Practical LoxiLB MVP

For the target scope:

```text
LoadBalancer
Listener
Pool
Member
HealthMonitor

create
update
delete
```

the practical minimum CRUD surface is:

```text
LoadBalancer
────────────
loadbalancer_create
loadbalancer_update
loadbalancer_delete

Listener
────────
listener_create
listener_update
listener_delete

Pool
────
pool_create
pool_update
pool_delete

Member
──────
member_create
member_update
member_delete

HealthMonitor
─────────────
health_monitor_create
health_monitor_update
health_monitor_delete
```

That is **15 core CRUD callbacks**.

For a serious implementation, also support:

```text
member_batch_update
```

because Octavia exposes batch member synchronization and it maps naturally to reconciliation-oriented backends.

---

## 15.3 Methods that are not mandatory for the first LoxiLB MVP

### `create_vip_port`

Optional.

Two valid designs exist:

```text
A. LoxiLB Provider creates/manages Neutron VIP port

B. Octavia creates/manages Neutron VIP port
```

If LoxiLB does not implement `create_vip_port()`, Octavia can create the VIP port itself.

This architectural decision should be made explicitly before implementation.

---

### `loadbalancer_failover`

Potentially optional.

Failover is backend-specific.

For Amphora:

```text
replace failed Amphora
```

For another provider it might mean:

```text
active → standby transition
```



For a shared active-active LoxiLB cluster:

```text
loadbalancer_failover()
```

may have little or no meaningful per-LB operation.

That needs to be defined rather than copied from Amphora.

---

### L7 Policy / Rule methods

Can initially be unsupported:

```text
l7policy_create/update/delete
l7rule_create/update/delete
```

provided the driver rejects them correctly.

---

### Flavor interfaces

Can initially be unsupported unless you expose backend-specific configuration through Octavia flavors.

---

### Availability Zone interfaces

Can initially be unsupported unless the LoxiLB architecture maps Octavia AZ semantics onto LoxiLB node placement.

---

# 16. Generic Provider Sequence Flow

A useful mental model for the whole integration is:

```text
                    NORTHBOUND

OpenStack User
      │
      ▼
Octavia API
      │
      │ octavia-lib data models
      ▼
LoxiLB Provider Driver
      │
      │ translation
      ▼
LoxiLB desired state
      │
      ▼
LoxiLB API / controller
      │
      ▼
LoxiLB dataplane
      │
      ▼
Backend Members


                    SOUTHBOUND

LoxiLB dataplane
      │
      │ health / state / statistics
      ▼
Provider reconciliation
      │
      ▼
octavia-lib DriverLibrary
      │
      ▼
octavia-driver-agent
      │
      ▼
Octavia status model
      │
      ▼
OpenStack User
```

That is the architectural contract the LoxiLB provider needs to satisfy.

---

# 17. Important Design Questions Before Implementing LoxiLB

## 17.1 Do not start from the Provider Driver methods

First define:

```text
What does one Octavia LoadBalancer correspond to in LoxiLB?
```

Possible models:

```text
A. One Octavia LB
        ↓
   one LoxiLB VM

B. Many Octavia LBs
        ↓
   shared LoxiLB cluster

C. Many Octavia LBs
        ↓
   placement onto LoxiLB node pools
```

These are radically different architectures.

Your earlier upstream `octavia-loxilb-driver` audit is especially relevant here: the existing package should be treated as a selective reuse/reference source rather than automatically adopting its per-LB VM orchestration architecture.

---

## 17.2 Decide VIP ownership

Before implementation, answer:

```text
Who creates the Neutron VIP port?
```

Option A:

```text
Octavia
   │
   ▼
Neutron VIP port
```

Option B:

```text
LoxiLB Provider
   │
   ▼
Neutron VIP port
```

Do not let this emerge accidentally from implementation.

---

## 17.3 Define the resource mapping

You need deterministic mapping such as:

```text
Octavia LB UUID
        ↕
LoxiLB service / VIP

Octavia Listener UUID
        ↕
LoxiLB frontend

Octavia Pool UUID
        ↕
LoxiLB backend group

Octavia Member UUID
        ↕
LoxiLB endpoint

Octavia HealthMonitor UUID
        ↕
LoxiLB health-check configuration
```

The exact LoxiLB objects must be established from LoxiLB API evidence rather than assumptions.

---

## 17.4 Define source of truth

Decide explicitly:

```text
Octavia DB = desired state
LoxiLB     = realized state
```

This is usually the safest model.

Then reconciliation becomes:

```text
Desired state
     │
     │ compare
     ▼
Observed LoxiLB state
     │
     ├── equal → healthy
     │
     └── drift → reconcile
```

Avoid treating a local JSON mapping file as the authoritative state of the system.

---

## 17.5 Design idempotency before retries

Every operation should ideally tolerate:

```text
create called twice
update repeated
delete missing resource
provider process crashes after backend success
callback fails after backend success
network timeout with unknown outcome
```

Example:

```text
Octavia → create Member

LoxiLB successfully creates it

HTTP response is lost

Provider retries

→ must not create duplicate state
```

Provider operations and reconciliation should use Octavia UUIDs as stable correlation identifiers wherever possible.

---

## 17.6 Define status semantics before coding

Create a written mapping:

```text
LoxiLB state
      ↓
Octavia provisioning_status

LoxiLB service health
      ↓
Octavia operating_status
```

Example:

```text
API request accepted
        ≠ ACTIVE

LoxiLB desired configuration verified
        = ACTIVE
```

Similarly:

```text
member health check failed
        ↓
Member operating_status = ERROR

but

Member provisioning_status = ACTIVE
```

if the configuration itself is correctly installed.

---

## 17.7 Separate provisioning from operating health

This should produce two independent loops.

### Provisioning loop

```text
Octavia request
   ↓
desired configuration
   ↓
LoxiLB API
   ↓
configuration confirmed
   ↓
ACTIVE / ERROR
```

### Health loop

```text
LoxiLB dataplane
   ↓
member/service health
   ↓
provider status synchronization
   ↓
ONLINE / DEGRADED / ERROR
```

Do not collapse them into one `status` variable.

---

## 17.8 Determine the asynchronous architecture

A minimal driver could theoretically make direct calls:

```text
octavia-api
     │
     ▼
LoxiLB REST API
```

but long-running provisioning should not block API workers unnecessarily.

A more scalable design is likely:

```text
octavia-api
     │
     ▼
LoxiLB Provider
     │
     │ submit operation
     ▼
Provider worker/controller
     │
     ▼
LoxiLB cluster
```

plus:

```text
Provider agent
     │
     ├── reconciliation
     ├── status polling
     └── statistics
```

The exact mechanism does not have to copy Amphora's Oslo RPC + TaskFlow model.

---

## 17.9 Validate capabilities at the driver boundary

Create a capability matrix before coding:

| Feature | Octavia | LoxiLB | Provider decision |
|---|---:|---:|---|
| TCP | yes | verify | support/reject |
| UDP | yes | verify | support/reject |
| SCTP | yes | verify | support/reject |
| HTTP | yes | verify | support/reject |
| HTTPS | yes | verify | support/reject |
| TERMINATED_HTTPS | yes | verify | support/reject |
| ROUND_ROBIN | yes | verify | mapping |
| LEAST_CONNECTIONS | yes | verify | mapping |
| SOURCE_IP | yes | verify | mapping |
| Health Monitor TCP | yes | verify | mapping |
| HTTP Health Monitor | yes | verify | mapping |
| Session persistence | yes | verify | mapping |
| L7 Policy | yes | verify | phase 2? |
| TLS termination | yes | verify | phase 2? |

Never silently downgrade a request.

---

# 18. Recommended LoxiLB Provider Boundary

A clean architecture would be:

```text
┌─────────────────────────────────────────┐
│            Octavia boundary             │
│                                         │
│ octavia-lib ProviderDriver              │
│ octavia-lib data models                 │
│ octavia-lib DriverLibrary               │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│             Translation layer           │
│                                         │
│ LoadBalancer translator                 │
│ Listener translator                     │
│ Pool translator                         │
│ Member translator                       │
│ HealthMonitor translator                │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│              LoxiLB client              │
│                                         │
│ API transport                           │
│ authentication                          │
│ validation                              │
│ retry                                   │
│ idempotency                             │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│          LoxiLB infrastructure          │
│                                         │
│ node placement                          │
│ HA                                      │
│ BGP/ECMP                                │
│ dataplane                               │
└─────────────────────────────────────────┘
```

And separately:

```text
┌─────────────────────────────────────────┐
│           Reconciliation loop           │
│                                         │
│ Octavia desired state                   │
│             ↕                           │
│ LoxiLB observed state                   │
│             │                           │
│             ▼                           │
│ DriverLibrary status callback           │
└─────────────────────────────────────────┘
```

---

# 19. Most Important Interfaces for Phase B/C

Study these first, in approximately this order:

```text
1. octavia_lib.api.drivers.provider_base.ProviderDriver

2. octavia_lib.api.drivers.data_models

3. octavia_lib.api.drivers.driver_lib.DriverLibrary

4. octavia_lib.api.drivers.exceptions

5. octavia_lib.common.constants

6. octavia/api/v2/controllers/load_balancer.py

7. octavia/api/v2/controllers/listener.py

8. octavia/api/v2/controllers/pool.py
   + member / health-monitor controllers

9. octavia/api/drivers/amphora_driver/v2/driver.py

10. ovn-octavia-provider driver implementation
```

The first five are the **supported external Provider Driver contract**.

The remaining files should be treated as:

```text
reference implementations / architectural examples
```

rather than APIs that LoxiLB code should depend upon.

---

# 20. Final Mental Model

Do not think:

```text
Octavia
   ↓
Load Balancer
```

Think:

```text
                Desired state

User
 │
 ▼
Octavia API
 │
 ▼
Octavia logical model
 │
 ▼
Provider Driver
 │
 ▼
Backend-specific desired state


                Realized state

LoxiLB dataplane
 │
 ▼
Observed state
 │
 ▼
Provider reconciliation
 │
 ▼
Octavia status
```

Provider Driver is therefore not merely:

> "a Python wrapper around the LoxiLB REST API."

It is responsible for maintaining the semantic contract:

```text
Octavia logical state
        ↕
LoxiLB realized state
```

including:

```text
translation
validation
asynchronous lifecycle
idempotency
VIP/network ownership
resource identity
health synchronization
status synchronization
error semantics
reconciliation
HA semantics
```

That is the real engineering scope of the LoxiLB-Octavia integration.