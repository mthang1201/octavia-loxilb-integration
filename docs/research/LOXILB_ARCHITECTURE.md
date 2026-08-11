# LoxiLB Architecture Research

**Research date:** 2026-08-11  
**Scope:** Official LoxiLB documentation, upstream LoxiLB source/API definition, and official OpenStack Octavia Provider Driver documentation.  
**Purpose:** Establish an evidence-based architecture baseline for integrating LoxiLB as an OpenStack Octavia provider backend.

---

## 1. Executive conclusion

LoxiLB is best understood as a **stateful L4 load-balancing and networking dataplane implemented primarily with TC eBPF**, managed by a Go control process, with integrated GoBGP support and a REST API. It can run independently of Kubernetes and is documented for Docker/containers and systemd-based standalone deployment. Its service model is fundamentally flatter than Octavia's object hierarchy: a LoxiLB load-balancer rule combines a **VIP/external IP + protocol/port + selection algorithm + endpoint list** into a service rule.

For this OpenStack project, the safest architectural classification is:

- **Core LoxiLB features:** eBPF dataplane, L4 VIP/service/endpoints, active health probes, multiple LB algorithms, REST configuration, GoBGP integration, BGP-based active-active ECMP, BGP/L2 active-backup mechanisms, and external active-backup connection synchronization.
- **Kubernetes-specific control/integration features:** `kube-loxilb` service discovery/CCM/operator behavior, Kubernetes Service automation, Ingress/Gateway API L7 control, automatic HA role election shown in the K8s guides, and Kubernetes service sharding/placement.
- **Octavia-mappable features:** L4 VIP/listener/pool/member and a useful subset of health-monitor/algorithm semantics can be mapped. BGP, ECMP, node placement, HA role management, connection synchronization, and cluster replication are **provider-infrastructure concerns**, not native Octavia resources. Generic Octavia `L7Policy`/`L7Rule` parity is **not evidenced by the examined core LoxiLB REST model** and should not be claimed for an MVP.

The most important caveat is that **LoxiLB connection synchronization is not a generic distributed configuration database**. Official HA documentation demonstrates long-lived connection synchronization in **external active-backup** deployments. A LoxiLB Octavia provider still needs its own desired-state reconciliation and configuration fan-out across nodes.

---

## 2. Evidence classification used in this document

| Label | Meaning |
|---|---|
| **CORE** | Implemented by the LoxiLB process/dataplane/API and usable without Kubernetes, based on official docs/source. |
| **K8S** | Automation or feature surface provided by `kube-loxilb`, Kubernetes Service/Ingress/Gateway API, or K8s-specific orchestration. |
| **OCTAVIA-DIRECT** | Semantics are close enough for a straightforward Provider Driver translation. |
| **OCTAVIA-ADAPTER** | Mappable only with translation, reconciliation, validation, or semantic restrictions. |
| **PROVIDER-INFRA** | Must be implemented below/around the Provider Driver as backend infrastructure orchestration; Octavia has no first-class equivalent object. |
| **NOT EVIDENCED** | No sufficiently clear official core API/source evidence was found to claim the feature in the required form. |

“Supported” in this report therefore does **not** mean “automatically usable by Octavia.”

---

## 3. High-level architecture

Official architecture documentation separates the system into a control process, eBPF dataplane, routing stack, CLI/API, and optional Kubernetes control components.

```text
                    Control / desired state

       loxicmd             REST clients          kube-loxilb [K8S]
          |                    |                       |
          +--------------------+-----------------------+
                               |
                               v
                    +---------------------+
                    |   loxilb Go process |
                    |---------------------|
                    | REST/API handlers   |
                    | service state       |
                    | endpoint state      |
                    | eBPF map management |
                    | HA state/sync hooks |
                    | GoBGP integration   |
                    +----+------------+---+
                         |            |
                   map/program        | route exchange
                   management         v
                         |        +---------+
                         |        |  GoBGP  |
                         |        +---------+
                         v
              +------------------------+
              |   Linux kernel eBPF    |
              |------------------------|
              | TC eBPF: main L4+ path |
              | XDP: selected L2 tasks |
              | conntrack/NAT state    |
              | pinned eBPF maps       |
              +------------------------+
                         |
                         v
                       traffic
```

### 3.1 What is Kubernetes-specific here?

`kube-loxilb` is a Kubernetes-side controller/operator. It watches Kubernetes objects/nodes/endpoints and programs one or more LoxiLB instances through their control API. It is **not required for standalone LoxiLB**.

For OpenStack, the Octavia Provider Driver plus an optional provider-side reconciler/cluster manager would assume the equivalent desired-state role.

---

## 4. eBPF dataplane

### 4.1 TC eBPF is the primary load-balancing datapath — CORE

Official eBPF internals documentation shows two built objects:

- `llb_ebpf_main.o` — TC eBPF path.
- `llb_xdp_main.o` — XDP path.

LoxiLB performs the **bulk of L4+ packet processing at TC eBPF**, because the skb context is more suitable for the checksum/offload and networking operations required by the load balancer. XDP is used for selected fast L2/special operations such as mirroring rather than being the main service load-balancing path.

Important entry points documented by LoxiLB include:

- `tc_packet_func` — main packet-processing path; established conntrack traffic can be transmitted here.
- `tc_packet_func_slow` — slow path for NAT lookup and stateful conntrack establishment.
- `xdp_packet_func` — XDP entry point.

LoxiLB also pins eBPF maps under `/opt/loxilb/dp/bpf/...`.

### 4.2 Control-plane / dataplane split

The Go `loxilb` process:

1. receives desired configuration,
2. maintains control-plane objects,
3. populates eBPF maps,
4. loads eBPF programs on interfaces,
5. integrates with GoBGP,
6. participates in HA synchronization.

This split is useful for Octavia because the Provider Driver does **not** need to manage eBPF maps directly. It should use the supported LoxiLB API and treat eBPF as an implementation detail of the backend.

### 4.3 Octavia implication

**Do not put eBPF-specific logic in Octavia translators.** A clean integration boundary is:

```text
Octavia model -> Provider mapping -> LoxiLB REST service model -> LoxiLB Go control plane -> eBPF
```

The driver should detect failures through API/state reconciliation, not by reading pinned BPF maps directly.

---

## 5. L4 versus L7

### 5.1 L4 — CORE and the recommended Octavia MVP

LoxiLB's standalone CLI/API model clearly exposes L4 load-balancer services. Official examples show TCP and SCTP rules, and documentation describes support for TCP/UDP/SCTP service load balancing and multiple NAT modes.

The core service primitive is well suited to Octavia's L4 subset:

```text
VIP/external IP
    + protocol
    + frontend port
    + selection algorithm
    + endpoint IP:port[:weight] list
    + service/NAT mode
```

Recommended first Octavia scope:

- VIP
- TCP/UDP listeners where supported by the target Octavia release/API
- pool
- members
- member weights with validated semantics
- health monitoring subset
- round-robin / least-connections / source-IP persistence
- HA and BGP/ECMP as provider infrastructure

### 5.2 L7 — REAL IN THE LOXILB ECOSYSTEM, BUT THE DOCUMENTED CONTROL SURFACE IS K8S-CENTRIC

Official LoxiLB documentation includes L4/L7 functionality through Kubernetes Gateway API and `loxilb-ingress`. The Gateway API guide explicitly assumes a Kubernetes cluster and uses:

- `kube-loxilb`,
- `loxilb-ingress`,
- `GatewayClass`,
- `Gateway`,
- `TCPRoute` / `UDPRoute` / `HTTPRoute`,
- Kubernetes TLS secrets for HTTPS ingress.

Therefore, the correct statement for this project is **not** “LoxiLB has no L7.” Instead:

> LoxiLB's ecosystem provides L7 HTTP/HTTPS routing, but the official operational path examined here is Kubernetes Ingress/Gateway-API based. No equivalent core standalone REST object model was established that maps cleanly to Octavia `L7Policy` and `L7Rule` semantics.

### 5.3 Octavia implication for L7

Treat these as separate questions:

- Can LoxiLB carry HTTP/HTTPS traffic at L4? **Yes, as TCP forwarding.**
- Does that implement Octavia HTTP semantics, TLS termination, header manipulation, path/host rules, or `L7Policy`/`L7Rule`? **No; TCP pass-through is not L7 feature parity.**
- Does LoxiLB ecosystem have L7 functionality? **Yes, documented through K8s ingress/gateway components.**
- Is generic standalone Octavia-L7 mapping proven? **No; NOT EVIDENCED in the examined core API.**

For the internship MVP, expose L7 options as unsupported unless a later phase proves a stable standalone API contract.

---

## 6. Service, VIP, and endpoint model

### 6.1 LoxiLB model — CORE

Official `loxicmd` examples and YAML define a load-balancer service using fields equivalent to:

```yaml
serviceArguments:
  externalIP: 1.2.3.1
  port: 80
  protocol: tcp
  sel: <selection>
endpoints:
  - endpointIP: 4.3.2.1
    weight: 1
    targetPort: 8080
  - endpointIP: 4.3.2.2
    weight: 1
    targetPort: 8080
```

This means the frontend tuple and backend endpoint set are represented together in a LoxiLB service/LB rule.

### 6.2 Octavia model is hierarchical

Octavia models roughly:

```text
LoadBalancer (VIP)
  +-- Listener (protocol + frontend port)
       +-- Pool (algorithm + persistence)
            +-- Member (address + backend port + weight)
            +-- HealthMonitor
```

This is not 1:1 with LoxiLB.

### 6.3 Required provider translation

For a basic default-pool listener, the Provider Driver can synthesize:

```text
Octavia LoadBalancer.vip_address       -> LoxiLB externalIP/VIP
Octavia Listener.protocol              -> LoxiLB service protocol
Octavia Listener.protocol_port         -> LoxiLB frontend port
Octavia Pool.lb_algorithm              -> LoxiLB selection mode
Octavia Member.address                 -> LoxiLB endpointIP
Octavia Member.protocol_port           -> LoxiLB targetPort
Octavia Member.weight                  -> LoxiLB endpoint weight (semantic validation required)
Octavia HealthMonitor                  -> endpoint probing configuration (partial mapping)
```

Multiple Octavia listeners on one VIP will normally become **multiple LoxiLB service rules sharing the VIP**.

### 6.4 Identity and reconciliation problem

LoxiLB's service identity is service-oriented; Octavia has UUIDs for each resource level. A production provider therefore needs a mapping/reconciliation layer that can answer:

- Which LoxiLB rule corresponds to this Octavia Listener/Pool?
- Which LoxiLB endpoint corresponds to this Octavia Member?
- Is the desired configuration present on every required LoxiLB node?
- What Octavia `provisioning_status` / `operating_status` should be reported?

Do not rely solely on local JSON mappings if durable recovery/reconciliation is required.

---

## 7. Health checking

### 7.1 LoxiLB active probes — CORE

LoxiLB supports active endpoint probing, but **active monitoring is disabled by default**. The documentation explains that Kubernetes may already supply endpoint health, so the user must explicitly enable monitoring when LoxiLB itself should probe endpoints.

Documented endpoint probe types:

- `ping`
- `http`
- `https`
- `udp`
- `tcp`
- `sctp`
- `none`

Documented probe parameters include:

- request/path for HTTP(S),
- expected/custom response string,
- probe port,
- period,
- retries.

The CLI can retrieve endpoint health using `loxicmd get ep`.

### 7.2 Mapping to Octavia health monitors

| Octavia HM type/field | LoxiLB | Mapping assessment |
|---|---|---|
| TCP | `tcp` probe | **OCTAVIA-DIRECT-ish** |
| HTTP | `http` probe | **OCTAVIA-ADAPTER** |
| HTTPS | `https` probe | **OCTAVIA-ADAPTER** |
| PING | `ping` | **OCTAVIA-DIRECT-ish** |
| SCTP | `sctp` | **OCTAVIA-DIRECT-ish** |
| UDP-CONNECT | `udp` probe | **PARTIAL**; validate exact success semantics |
| TLS-HELLO | no exact documented probe type | **NOT EVIDENCED / reject** |
| `delay` | probe period | Close mapping |
| `max_retries_down` | retries | Partial; verify rise/fall semantics |
| `max_retries` | no distinct documented “success threshold” equivalent | Partial |
| `timeout` | probe behavior has timeout logic, but the CLI surface is not a clean 1:1 Octavia field | Partial |
| `url_path` | `probereq` | Close mapping for HTTP(S) |
| `expected_codes` | documented custom response string, not clearly Octavia status-code range syntax | Partial |
| `monitor_port` | `probeport` | Close mapping |
| `monitor_address` | alternate probe IP semantics not proven as independent from endpoint identity | Needs validation |

### 7.3 Status synchronization

LoxiLB can expose endpoint health. The Provider Driver/reconciler must translate that observed state into Octavia operating status and call the supported Octavia driver status API. LoxiLB itself does not own Octavia UUID/status semantics.

---

## 8. Load-balancing algorithms

Official LoxiLB documentation lists five algorithms:

1. **Round Robin (`rr`)** — default.
2. **Weighted Round Robin (`wrr`)**.
3. **Persistence (`persist`)** — source-IP affinity.
4. **Flow hash (`hash`)** — incoming 5-tuple hash.
5. **Least Connections (`lc`)**.

### 8.1 Octavia mapping

| Octavia pool semantic | LoxiLB | Assessment |
|---|---|---|
| `ROUND_ROBIN` | `rr` | **DIRECT** |
| `LEAST_CONNECTIONS` | `lc` | **DIRECT** |
| `SOURCE_IP` | `persist` | **DIRECT/close**, validate persistence behavior/timeouts |
| `SOURCE_IP_PORT` | closest is `hash`, but LoxiLB hashes full 5-tuple | **PARTIAL, not semantically identical** |
| member `weight` | LoxiLB WRR/endpoint weights | **POSSIBLE**, but provider must define how Octavia weights activate LoxiLB `wrr` and test weight=0 semantics |
| HTTP cookie persistence | LoxiLB L4 source-IP persistence is not cookie persistence | **NOT MAPPABLE in L4 MVP** |

The provider should reject unsupported combinations with Octavia's documented unsupported-option mechanism rather than silently changing semantics.

---

## 9. REST API

### 9.1 Core REST interface — CORE

Official LoxiLB docs state that LoxiLB can be fully configured through REST APIs. The upstream `api/swagger.yml` defines a Swagger 2.0 API with:

- base path `/netlox/v1`,
- HTTP and HTTPS schemes,
- default service port `11111` for the insecure API in current source/options,
- a load-balancer create endpoint at `/config/loadbalancer`,
- a get-all endpoint `/config/loadbalancer/all` that includes LB/conntrack information,
- load-balancer delete forms by name or frontend tuple.

Current upstream source also contains API authentication/user-management code and TLS runtime options.

### 9.2 Security caveat

Official HTTPS documentation states that the API uses **plain HTTP by default** and TLS must be enabled/configured.

For OpenStack production use:

- require HTTPS,
- configure authentication/credentials,
- do not expose port 11111 on tenant networks,
- use a management network,
- define timeouts/retries/backoff,
- make operations idempotent or reconcile after ambiguous failures.

### 9.3 Update semantics

The examined source clearly proves create/get/delete surfaces. This report does **not** assume that every Octavia field has a first-class atomic `PUT/PATCH` operation. The provider should be written as a **desired-state reconciler**, able to replace/rebuild a LoxiLB service when an in-place update primitive is not available or not semantically safe.

---

## 10. BGP

### 10.1 Integrated GoBGP — CORE

LoxiLB integrates GoBGP as its routing stack. Standalone documentation shows GoBGP configuration and running LoxiLB with BGP enabled. The HA documentation shows LoxiLB advertising service/VIP routes according to HA mode.

### 10.2 What is core versus Kubernetes automation?

**CORE:**

- GoBGP integration.
- VIP/service route advertisement.
- BGP attributes used to represent active/backup preference.
- same-attribute advertisement for active-active ECMP.

**K8S:**

- `kube-loxilb` automatically generating/maintaining BGP peering settings from Kubernetes deployment arguments.
- choosing/electing HA roles in the documented K8s scenarios.

### 10.3 Octavia implication

BGP is not an Octavia Listener/Pool/Member resource. It belongs to **PROVIDER-INFRA**. The LoxiLB provider architecture needs a BGP manager/configuration policy or pre-provisioned fabric contract.

---

## 11. ECMP and active-active

### 11.1 Active-active with BGP ECMP — CORE mechanism, external network prerequisite

Official HA Scenario 3 documents L3 active-active:

- multiple LoxiLB instances advertise the same service/VIP,
- advertisements use the same attributes,
- an ECMP-capable upstream router/host installs multiple equal-cost next hops,
- on failure, BGP updates the ECMP set and traffic is sent to remaining active next hops.

This is the strongest official basis for **dataplane horizontal scale of a VIP**.

### 11.2 What it does not prove

The active-active ECMP section does **not** document connection-state synchronization between active nodes. Therefore it is unsafe to promise that an existing stateful flow that was using a failed node will continue seamlessly on another active node.

For the OpenStack design, explicitly measure:

- new-flow continuity,
- existing-flow reset rate,
- BGP convergence time,
- packet loss during node failure,
- effect of ECMP hashing,
- whether the chosen NAT mode can preserve sessions in the target topology.

### 11.3 Octavia mapping

Active-active is transparent backend topology from Octavia's perspective. The Provider Driver can expose a normal LB while the provider infrastructure replicates the service across N LoxiLB nodes and advertises the VIP from all of them.

```text
                       upstream router(s)
                         ECMP next hops
                      /       |       \
                     v        v        v
                 LoxiLB-1  LoxiLB-2  LoxiLB-3
                    \         |         /
                     \        |        /
                         backend VMs
```

The network fabric must support and be configured for ECMP; LoxiLB cannot create ECMP behavior in a router that does not support it.

---

## 12. Active-standby / active-backup

Official HA documentation shows:

- flat-L2 active-backup,
- L3 active-backup using BGP preference,
- active-backup with connection synchronization,
- active-backup with BFD-based fast failure detection.

### 12.1 K8s orchestration versus core mechanisms

The documented K8s topologies assign several responsibilities to `kube-loxilb`:

- health monitoring of LoxiLB instances,
- selecting a new active/master,
- assigning the service IP to that active instance,
- automating BGP peering in applicable scenarios.

Those responsibilities do **not** disappear in OpenStack. Without Kubernetes, the LoxiLB Octavia provider needs an equivalent cluster manager, external HA manager, or rigorously pre-provisioned HA scheme.

### 12.2 Recommended OpenStack interpretation

- **LoxiLB:** dataplane, route advertisement, endpoint health, connection sync mechanism.
- **Provider cluster manager:** node health, active role/placement, config replication, fencing, failover workflow.
- **Octavia Provider Driver:** converts Octavia intent into provider desired state and reports statuses.

---

## 13. Connection and state synchronization

### 13.1 What is explicitly documented — CORE but topology-limited

HA Scenario 4 states that active-backup connection synchronization is supported when LoxiLB runs **externally outside the Kubernetes cluster**, in default or full-NAT mode. LoxiLB is described as synchronizing long-lived connections to configured peer(s), with the `--cluster` option used to specify peers.

Current upstream runtime options describe the cluster list as a comma-separated list of cluster-node IP addresses.

### 13.2 What must not be inferred

Do not conflate three different states:

1. **Connection/conntrack state** — LoxiLB has documented synchronization for external active-backup.
2. **HA role state** — master/backup selection exists, but the documented K8s scenarios use `kube-loxilb` to orchestrate roles.
3. **Desired service configuration** — no generic distributed config database was established in the reviewed docs. A provider must still push/reconcile VIP/service/endpoint configuration across the correct nodes.

### 13.3 Active-active caveat

Official active-active ECMP documentation does not state that connection state is synchronized among all active nodes. Classify active-active stateful hitless failover as **NOT EVIDENCED** until tested or supported by more explicit upstream documentation/source.

### 13.4 DSR is not a general substitute

The HA guide notes that DSR can help preserve connections in some topology choices but lists limitations, including inability to ensure stateful filtering/connection tracking and lack of multihoming support for the described reason. Therefore, do not select DSR solely to avoid state synchronization without evaluating security and protocol requirements.

---

## 14. Horizontal scaling

Horizontal scaling needs to be split into three distinct problems.

### 14.1 Scaling traffic for the same VIP — CORE architecture

**BGP ECMP active-active** can add more LoxiLB forwarding nodes for a VIP. This is a real scale-out mechanism, but throughput scaling efficiency is not guaranteed by the architecture and must be benchmarked.

Potential bottlenecks include:

- NIC / virtual NIC limits,
- VM CPU scheduling,
- eBPF processing limits,
- upstream ECMP hash distribution,
- Neutron topology,
- backend capacity,
- conntrack/state requirements.

### 14.2 Sharding different services across nodes — K8S automation

Official **Kubernetes service sharding** is implemented by `kube-loxilb`. It creates HA shard instances and chooses a shard for Kubernetes `LoadBalancer` services. The guide explicitly notes that finding the selected shard currently requires inspecting instances (“no easy way out right now”).

This automation is **not a generic standalone LoxiLB cluster scheduler**.

### 14.3 Generic OpenStack scale-out — PROVIDER-INFRA

For Octavia, build one of these provider-side policies:

**A. Replicated active-active service**

```text
LB/VIP A -> node 1 + node 2 + node 3 -> BGP ECMP
```

**B. Sharded shared cluster**

```text
LB/VIP A -> nodes 1,2
LB/VIP B -> nodes 2,3
LB/VIP C -> nodes 3,4
```

**C. Hybrid**

- shard tenants/LBs to an HA group,
- replicate each LB inside its assigned group.

The provider needs placement metadata, capacity tracking, node health, and reconciliation. This is new integration work; do not attribute it to LoxiLB core merely because K8s service sharding exists.

---

## 15. VM, bare metal, and container deployment

### 15.1 Bare metal — SUPPORTED

Standalone docs explicitly discuss bare-metal networking and multi-interface setups.

### 15.2 Container — SUPPORTED, but privileged

The official Docker run command uses root, `--privileged`, and `SYS_ADMIN`. Multi-interface bare-metal/container deployments may use Docker `macvlan`, and host networking is also documented as an option.

For some sockmap/local-socket features, additional host PID/cgroup namespace access is documented.

Therefore “containerized” does **not** mean a locked-down unprivileged container.

### 15.3 VM — SUPPORTED as a normal Linux deployment target

LoxiLB does not require Kubernetes and has no special hardware requirement beyond documented OS/kernel requirements. A VM can host the standalone binary or privileged container as long as the guest satisfies the Linux/eBPF/networking requirements and has appropriate interfaces/connectivity.

For OpenStack, external provider VMs are a reasonable deployment model, but performance must be benchmarked with the selected vNIC type, MTU, offload, NUMA, and Neutron path.

### 15.4 System requirements

Official requirements currently state:

- Linux kernel **>= 5.15.x**,
- listed 64-bit Linux distributions including Ubuntu 20.04/22.04/24.04, Amazon Linux, Fedora 36, RockyOS, RHEL 9,
- Windows is listed as planned,
- no special hardware requirement; 2 vCPU / 2 GB is described as a starter footprint.

---

## 16. Current limitations and integration risks

The following are evidence-based limitations/gaps relevant to an Octavia provider.

### 16.1 Linux/kernel dependency

LoxiLB requires a sufficiently new Linux kernel (officially >= 5.15.x). Windows support is planned rather than current.

### 16.2 Privilege/network access

The documented container deployment is privileged and requires strong host/network capabilities. Security hardening must be treated as infrastructure work.

### 16.3 Active endpoint monitoring is opt-in

Without active monitoring enabled, LoxiLB can continue selecting an endpoint that is inactive. An Octavia Provider Driver must explicitly configure the intended monitoring policy.

### 16.4 Health monitor semantic gaps

Octavia exposes richer HM semantics than the documented LoxiLB CLI probe model, especially separate rise/fall counts, TLS-HELLO, HTTP status-code ranges, and alternate monitoring address semantics. The driver must reject or narrow unsupported combinations.

### 16.5 L7/Octavia feature-parity gap

The officially documented L7 routing path is tied to Kubernetes Gateway API/Ingress components. Generic standalone mapping for Octavia L7 policies/rules was not established in the reviewed core API.

### 16.6 API transport is HTTP by default

Production integration must explicitly enable TLS and authentication on the management plane.

### 16.7 ECMP depends on the underlay

Active-active requires an ECMP-capable upstream network device/host and correct BGP configuration.

### 16.8 Active-active connection continuity is not proven by the HA guide

The docs demonstrate BGP ECMP failover for traffic steering, but the connection-sync section is specifically active-backup/external. Existing-flow survival after an active-active node loss must be treated as a test requirement, not an assumed feature.

### 16.9 Configuration replication is not connection synchronization

An OpenStack provider still needs desired-state fan-out/reconciliation across a shared LoxiLB cluster.

### 16.10 Kubernetes service sharding is not standalone auto-scaling

The documented sharding scheduler is part of `kube-loxilb`. A generic OpenStack cluster-placement/autoscaling controller is new provider work.

### 16.11 Some current source flags are explicitly experimental

Current upstream runtime options label several functions experimental, including passive endpoint probing, RSS optimization, egress hooks, IPVS compatibility, fallback networking, local socket policy, sockmap-based L4 proxying, the built-in K8s watcher, cloud-CIDR behavior, and interface whitelist behavior. Do not base the OpenStack MVP on an experimental path without version-pinned validation.

### 16.12 Version pinning matters

Use a pinned LoxiLB release/image and record the commit/image digest used for testing. Do not benchmark `latest` and later treat the result as reproducible.

---

## 17. Recommended Octavia/LoxiLB architecture

A production-oriented design should keep Octavia, provider orchestration, and LoxiLB dataplane clearly separated.

```text
             OpenStack user / API / Horizon
                       |
                       v
                 +-----------+
                 | Octavia   |
                 | API       |
                 +-----+-----+
                       |
                       | provider=loxilb
                       v
            +------------------------+
            | LoxiLB Provider Driver |
            |------------------------|
            | Octavia object mapper  |
            | capability validation  |
            | async job submission   |
            +-----------+------------+
                        |
                        v
            +-------------------------+
            | Provider cluster manager|
            | / reconciler            |
            |-------------------------|
            | placement / sharding    |
            | config fan-out          |
            | node health             |
            | HA role/fencing         |
            | BGP policy              |
            | status aggregation      |
            +------+---------+--------+
                   |         |
              REST/TLS   REST/TLS ...
                   |         |
                 +-v---------v------------------+
                 | Shared LoxiLB node pool      |
                 |------------------------------|
                 | node 1  node 2  ...  node N  |
                 | eBPF    eBPF         eBPF    |
                 | GoBGP   GoBGP        GoBGP   |
                 +----------+-------------------+
                            |
                         BGP/ECMP
                            |
                     upstream fabric
                            |
                        tenant VIPs
                            |
                        backend VMs
```

### 17.1 Responsibilities

**Octavia:**

- API and lifecycle intent,
- stable resource model,
- provisioning/operating status consumers,
- provider selection.

**Provider Driver:**

- validation,
- model translation,
- asynchronous lifecycle hand-off,
- status callback integration.

**Provider cluster manager/reconciler:**

- shared-cluster desired state,
- placement,
- HA topology,
- service replication,
- BGP/fabric integration,
- retry/idempotency,
- status and drift reconciliation.

**LoxiLB nodes:**

- service/VIP/endpoints,
- eBPF dataplane,
- conntrack/NAT,
- endpoint health probing,
- route advertisement,
- supported connection sync.

### 17.2 Why this is preferable to putting everything in `driver.py`

Octavia callbacks should return acceptance quickly and backend work can fail/retry independently. Separating the cluster manager also makes it possible to test:

- LoxiLB without Octavia,
- placement without dataplane traffic,
- Octavia mapping without BGP,
- failure recovery independently of API request handling.

---

## 18. Proposed MVP support contract

### Support in MVP

- L4 service/VIP
- TCP and UDP where confirmed by target Octavia release
- Round Robin
- Least Connections
- Source-IP persistence
- Member weight only after WRR semantics are proven
- Member create/update/delete reconciliation
- TCP/PING and carefully validated HTTP/HTTPS health monitors
- API over TLS/authenticated management network
- shared external LoxiLB node pool
- active-active BGP/ECMP **or** active-backup as an explicit deployment profile
- status reconciliation

### Explicitly defer/reject initially

- generic Octavia L7Policy/L7Rule
- cookie persistence
- TLS-HELLO HM unless a direct LoxiLB primitive is proven
- SOURCE_IP_PORT if exact semantics cannot be preserved
- silent fallback from unsupported algorithm/HM to another behavior
- active-active “hitless existing-flow failover” claims before lab validation
- automated generic horizontal scaling claims before provider placement/reconciliation exists

---

## 19. Validation questions for the next lab phase

The following should be treated as **testable research questions**, not assumptions:

1. Does the selected LoxiLB release expose stable, idempotent REST behavior for create/read/update/delete of service rules?
2. How do duplicate creates and delete-not-found behave?
3. Can multiple VIPs/listeners/pools be hosted safely on one LoxiLB instance at the intended scale?
4. What exact REST fields correspond to RR, LC, persistence, hash, WRR, weights, modes, and monitoring?
5. What is the update behavior when only one member changes?
6. How quickly does endpoint health transition and what state is available over REST?
7. Which Octavia HM fields can be reproduced exactly?
8. What happens to existing TCP connections when one active-active ECMP node fails?
9. What is the failover behavior with active-backup connection sync?
10. Does BFD materially reduce convergence time in the target fabric?
11. What is the CPU/RAM/NIC scaling curve for 1, 2, 3, ... LoxiLB nodes?
12. What is the control-plane scaling curve for 100 / 1,000 / 10,000 service objects?
13. How should a provider-side mapping survive worker restarts and database loss?
14. Can all desired state be reconstructed from Octavia + live LoxiLB state?
15. Which LoxiLB runtime flags/features are stable in the chosen pinned release?

---

## 20. Official evidence sources

Only official/upstream sources were used for technical conclusions.

### LoxiLB documentation

- **[L1] Architecture in brief:** https://docs.loxilb.io/main/arch/
- **[L2] eBPF internals:** https://docs.loxilb.io/main/loxilbebpf/
- **[L3] loxicmd / service and endpoint examples:** https://docs.loxilb.io/main/cmd/
- **[L4] Load-balancer algorithms:** https://docs.loxilb.io/main/lb-algo/
- **[L5] High Availability:** https://docs.loxilb.io/main/ha-deploy/
- **[L6] Standalone mode:** https://docs.loxilb.io/main/standalone/
- **[L7] System requirements:** https://docs.loxilb.io/main/requirements/
- **[L8] REST API reference:** https://docs.loxilb.io/main/api/
- **[L9] HTTPS for API:** https://docs.loxilb.io/main/https/
- **[L10] Kubernetes Gateway API L4/L7:** https://docs.loxilb.io/main/gw-api/
- **[L11] Kubernetes service sharding:** https://docs.loxilb.io/main/service-sharding/

### LoxiLB upstream source

- **[S1] REST Swagger source:** https://github.com/loxilb-io/loxilb/blob/main/api/swagger.yml
- **[S2] Runtime options:** https://github.com/loxilb-io/loxilb/blob/main/options/options.go
- **[S3] Repository:** https://github.com/loxilb-io/loxilb

### OpenStack

- **[O1] Octavia Provider Driver Development Guide:** https://docs.openstack.org/octavia/latest/contributor/guides/providers.html
- **[O2] octavia-lib documentation:** https://docs.openstack.org/octavia-lib/latest/

---

## 21. Final architecture verdict

For an OpenStack integration, classify LoxiLB as a **high-performance L4-focused eBPF dataplane with useful native routing/HA primitives**, not as a drop-in replacement for every Octavia feature.

The engineering value of the Provider Driver is therefore larger than simple REST translation. It must provide the missing cloud-control functions around the dataplane:

- Octavia-to-LoxiLB model translation,
- capability validation,
- durable mapping,
- desired-state reconciliation,
- multi-node configuration replication,
- placement/sharding,
- HA role management where required,
- BGP/ECMP integration,
- health/status aggregation,
- safe retries/idempotency.

That separation also gives a defensible research story: **measure which LoxiLB capabilities are real, identify which behaviors are Kubernetes automation rather than LoxiLB core, then implement only the OpenStack-specific control plane needed to expose proven capabilities through Octavia.**
