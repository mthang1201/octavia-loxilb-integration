# LoxiLB L4/L7/ECMP/BGP/eBPF Research

**Research date:** 2026-08-12  
**Scope:** LoxiLB support for L4 load balancing, L7 load balancing, ECMP, BGP, and eBPF, with emphasis on applicability to an OpenStack Octavia Provider Driver.  
**Evidence policy:** Primarily official LoxiLB documentation and upstream `loxilb-io` source repositories. OpenStack upstream documentation is used only to evaluate Octavia relevance.

---

## 1. Executive summary

LoxiLB has strong, directly evidenced support for **standalone Layer-4 load balancing** built around a Go control plane and an **eBPF data plane**. Standalone operation is explicitly documented, load-balancer rules can be created with `loxicmd`, and the upstream Swagger definition exposes a REST API described as being for **bare-metal scenarios**. LoxiLB supports stateful L4/NAT processing, multiple NAT modes, endpoint health checking, and several endpoint-selection algorithms. This is the clearest technical foundation for an OpenStack Octavia Provider Driver.

**BGP is also a real standalone/core capability**, but LoxiLB integrates the separate GoBGP project rather than implementing an independent BGP stack entirely inside its eBPF dataplane. The standalone guide documents direct GoBGP configuration, and the HA guide uses BGP for service-VIP advertisement.

**ECMP is supported as an HA/deployment architecture**, particularly for active-active LoxiLB nodes advertising the same service VIP over BGP. It is important not to confuse this with LoxiLB's backend-selection algorithms such as round-robin. ECMP happens in the surrounding routed network: routers/hosts must actually install and use equal-cost routes. The official worked example is Kubernetes-oriented, although the HA guide says similar configurations can be used for external deployments.

**L7 support exists, but its scope must be stated carefully.** Current official documentation lists policy-driven HTTP proxying for HTTP/1.0, HTTP/1.1 and HTTP/2.0; release notes also record transparent L7 proxy, HTTPS termination, HTTP/2 parsing and protocol-aware telco work such as NGAP parsing. However, the clearest operational HTTP L7 documentation is tied to Kubernetes Ingress/Gateway API and `loxilb-ingress`. More importantly for Octavia, the upstream standalone Swagger surface does **not expose Octavia-equivalent `L7Policy` and `L7Rule` resources**. Therefore this research does **not** treat LoxiLB as proven to provide generic standalone Octavia L7 feature parity.

The eBPF implementation is a **proven core dataplane**, not a Kubernetes-only feature. Official internals documentation shows TC eBPF handling most L4+ processing, XDP being used for selected fast L2/special operations, pinned BPF maps for state, and stateful conntrack/NAT handling. LoxiLB currently documents a Linux kernel requirement of at least 5.15.

A major HA caveat is also clear from the official documentation: **active-active BGP ECMP and connection-state synchronization are documented as separate scenarios**. Connection synchronization is explicitly documented for an **external active-backup deployment** in default/full-NAT mode, with synchronization of long-lived connections. No official evidence found in this review establishes connection-state synchronization among all active-active ECMP nodes. The design must not claim that property unless a later source or lab proves it.

### Overall assessment for an Octavia Provider Driver

| Capability | Research classification | Octavia relevance |
|---|---|---|
| L4 load balancing | **Proven core/standalone** | **High** — suitable MVP dataplane/control target |
| L7 load balancing | **Implemented, but standalone Octavia parity not evidenced** | **Low for MVP / requires separate validation and mapping** |
| BGP | **Proven core integration; GoBGP dependency** | **High for optional VIP advertisement / HA**, but primarily provider infrastructure |
| ECMP | **Proven HA architecture; surrounding network dependency** | **Medium-High for scale-out/active-active architecture**, not an Octavia resource itself |
| eBPF | **Proven core dataplane** | **Foundational** — the reason LoxiLB can serve as the actual LB dataplane |

---

## 2. Evidence classification used in this report

The terms below are used deliberately:

### 2.1 Proven core feature

A capability is classified as **proven core** when official LoxiLB documentation and/or upstream source explicitly shows it operating as part of LoxiLB itself and it is not dependent on Kubernetes as the only control plane.

Examples in this report:

- standalone L4 LB rules;
- eBPF dataplane;
- standalone REST/CLI control;
- GoBGP integration.

### 2.2 Kubernetes-only integration feature

This means the integration mechanism itself depends on Kubernetes objects/controllers, even when the underlying LoxiLB dataplane is reusable elsewhere.

Examples:

- `kube-loxilb` watching Kubernetes `Service` objects;
- Kubernetes Ingress integration;
- Kubernetes Gateway API resources;
- BGP peer/policy CRDs.

This classification does **not** mean the underlying packet-processing capability necessarily works only in Kubernetes.

### 2.3 Provider-infrastructure concern

These are capabilities needed to deploy LoxiLB successfully in OpenStack, but they should not automatically be modeled as Octavia user-facing objects.

Examples:

- BGP peering to the fabric;
- ECMP route installation;
- VIP reachability;
- placement of multiple LoxiLB nodes;
- virtual-NIC/eBPF compatibility;
- failure detection and route withdrawal.

### 2.4 Unsupported or not evidenced

This report uses **not evidenced** rather than “unsupported” when official material does not establish the exact behavior being asked for.

Important examples:

- generic standalone Octavia-compatible `L7Policy`/`L7Rule` API semantics;
- active-active ECMP connection-state synchronization;
- seamless preservation of every existing flow after an active-active node failure.

Absence of a documented API is negative evidence, not mathematical proof that no internal implementation exists.

---

## 3. Architecture relevant to these capabilities

The most useful conceptual model for OpenStack is:

```text
                    OpenStack control plane
                           |
                    Octavia API / API v2
                           |
               hypothetical LoxiLB Provider Driver
                           |
           +---------------+----------------+
           |                                |
    LoxiLB REST API                   Provider infrastructure
    /netlox/v1                         orchestration
           |                                |
     LoxiLB Go control plane                 +--> VIP/network setup
           |                                  +--> LoxiLB node placement
           |                                  +--> BGP peer/fabric setup
           |                                  +--> HA/ECMP topology
           |
     +-----+-------------------+
     |                         |
 eBPF maps/programs         GoBGP integration
     |                         |
 TC eBPF / selected XDP     VIP advertisements
     |                         |
 packets -> NAT/CT/LB       routers / ECMP fabric
     |
 backend members
```

A separate Kubernetes-oriented control path exists:

```text
Kubernetes Service / Ingress / Gateway API
                 |
       kube-loxilb / loxilb-ingress
                 |
             LoxiLB
                 |
           eBPF dataplane
```

This distinction matters for Octavia. `kube-loxilb` is a Kubernetes operator/controller. It should not be mistaken for the LoxiLB dataplane itself or treated as a required component of an OpenStack integration.

Official architecture documentation describes the main LoxiLB process as a Go framework that receives configuration, populates eBPF maps, loads eBPF programs on interfaces, and interacts with GoBGP. It describes the eBPF component as the dataplane responsible for packet processing. [S2][S5]

The upstream Swagger specification identifies the REST interface as **“Loxilb REST API for Baremetal Scenarios”**, listens by default on port `11111`, and uses `/netlox/v1` as its base path. It exposes create/get/delete operations for load-balancer services and inspection of conntrack state. [S10]

That standalone API is particularly relevant to a Provider Driver because an Octavia driver needs a control API independent of Kubernetes.

---

# 4. Layer-4 load balancing

## 4.1 Status

**Classification: PROVEN CORE / STANDALONE FEATURE**

This is the strongest and clearest LoxiLB capability for an Octavia integration.

The current official introduction states that LoxiLB acts as an **L4 load balancer and service proxy by default**. It lists stateful L4/NAT load balancing and protocols including TCP, UDP and SCTP, along with additional protocol handling such as QUIC, FTP and TFTP. [S1]

The standalone guide explicitly creates a TCP load-balancer rule with `loxicmd`, demonstrating that Kubernetes is not required for basic L4 service creation. [S3]

The upstream Swagger API also provides a standalone `/config/loadbalancer` resource and describes the API as intended for bare-metal scenarios. [S10]

## 4.2 How it works

At a high level:

1. a service/VIP and protocol/port are configured;
2. one or more backend endpoints are associated with the service;
3. LoxiLB's Go control plane programs eBPF maps;
4. incoming traffic reaches the LoxiLB dataplane;
5. LoxiLB performs service lookup, endpoint selection, NAT/forwarding and conntrack as required by the chosen mode;
6. established traffic can follow the fast dataplane state already maintained in eBPF maps.

Official eBPF internals document a slow path responsible for NAT lookup and stateful conntrack establishment, after which established connections can be forwarded from the main TC eBPF processing path. [S5]

## 4.3 L4 endpoint-selection algorithms

Official documentation lists:

- **Round-robin (`rr`)** — default; endpoint selected in round-robin order for each new connection.
- **Weighted round-robin (`wrr`)** — endpoint weights control distribution.
- **Persistence (`persist`)** — source IP maps consistently to an endpoint.
- **Flow hash (`hash`)** — 5-tuple hash using source/destination IP, source/destination port and IP protocol.
- **Least connections (`lc`)** — chooses the endpoint with the fewest active connections.

[S6]

These algorithms map conceptually to Octavia pool load-balancing algorithms, but exact one-to-one compatibility should be verified against the Octavia version and the LoxiLB API representation used by the Provider Driver.

## 4.4 NAT/deployment modes

Official LoxiLB documentation describes multiple L4/NAT deployment modes, including variants of:

- default/DNAT-style behavior;
- one-arm;
- full NAT;
- DSR.

The current introduction explicitly lists One-ARM, FullNAT and DSR under the L4/NAT feature set. [S1][S7]

These modes are important because they change:

- source-address preservation;
- return-path requirements;
- whether LoxiLB must see return traffic;
- statefulness;
- topology requirements.

They should be considered provider/flavor/deployment choices rather than blindly exposed as core Octavia semantics.

## 4.5 Core feature or Kubernetes-specific?

**Core.**

Kubernetes can automate service discovery and configuration using `kube-loxilb`, but LoxiLB itself can be deployed externally or in standalone mode. The official Kubernetes architecture page explicitly describes `kube-loxilb` as the Kubernetes control-plane/operator component while LoxiLB performs the actual service connectivity and load balancing. [S8]

Therefore:

> Kubernetes `ServiceType=LoadBalancer` support is an integration mode; L4 load balancing itself is not Kubernetes-specific.

## 4.6 Limitations and external dependencies

Important practical constraints include:

- Linux is required for the current eBPF dataplane; current docs require **Linux kernel >= 5.15.x**. [S11]
- LoxiLB must attach eBPF programs to relevant interfaces; interface selection/blacklisting matters. [S5]
- NAT mode determines return-path and topology requirements.
- Health-monitor semantics must be checked against Octavia's richer health-monitor model.
- Source-IP persistence is not equivalent to every Octavia session-persistence option.
- Algorithm names may match conceptually without having identical edge-case semantics.
- API authentication, TLS/OAuth setup, multi-tenancy boundaries, idempotency and reconciliation behavior need provider-side design and validation.

## 4.7 Relevance to OpenStack Octavia

**High. This is the recommended MVP target.**

A plausible conceptual mapping is:

| Octavia object | LoxiLB concept |
|---|---|
| LoadBalancer | VIP / logical grouping plus provider-managed LoxiLB placement |
| Listener | VIP + protocol + frontend port LB rule |
| Pool | endpoint set + selection algorithm |
| Member | backend endpoint IP/port/weight |
| HealthMonitor | LoxiLB endpoint probe configuration |

The mapping is not perfectly 1:1. In particular, LoxiLB appears to model much of the service in a load-balancer rule, while Octavia separates listener, pool, member and health-monitor resources. The Provider Driver therefore needs an adapter/resource-mapping layer.

The upstream REST API is a promising control surface because it directly exposes load-balancer creation and retrieval outside Kubernetes. [S10]

## 4.8 What still requires lab verification

At minimum:

1. TCP and UDP service creation through REST rather than only CLI.
2. Add/remove/update member behavior.
3. Weighted member updates.
4. Round-robin, least-connections, hash and persistence behavior.
5. Failure detection and endpoint exclusion.
6. Health-monitor type compatibility with Octavia.
7. IPv4 and IPv6 behavior.
8. One-arm/full-NAT/default/DSR return paths.
9. Existing-flow behavior when members are disabled or deleted.
10. Statistics suitable for Octavia listener statistics.
11. REST authentication/TLS behavior under automation.
12. Idempotent create/update/delete and recovery after driver restart.
13. Behavior when LoxiLB itself restarts while OpenStack resources remain.
14. Multi-tenant isolation strategy.

---

# 5. Layer-7 load balancing

## 5.1 Status

**Classification: IMPLEMENTED CAPABILITY, BUT GENERIC STANDALONE OCTAVIA L7 PARITY IS NOT PROVEN**

This is deliberately more conservative than simply saying “LoxiLB supports L7.”

Current official documentation contains several positive pieces of evidence:

- the current introduction says LoxiLB supports **policy-driven HTTP proxying for HTTP/1.0, HTTP/1.1 and HTTP/2.0**; [S1]
- the release roadmap/history records **L7 transparent proxy** and **HTTPS termination** in the 0.9.5 milestone; [S12]
- it records an **HTTP/2 parser** and NGAP parser work in the 0.9.6 milestone; [S12]
- current documentation says Kubernetes L7 load balancing is provided through the Ingress implementation enhanced by eBPF `sockmap`; [S1]
- an official Gateway API guide covers HTTP routing in a Kubernetes environment. [S9]

Therefore L7 implementation work clearly exists.

However, that does **not** establish that LoxiLB exposes all of the standalone resource semantics required by Octavia.

## 5.2 Why L7 must not be overclaimed

Octavia's L7 API is explicit and structured. Its Provider Driver interface includes:

- `L7Policy`;
- `L7Rule`;
- actions such as redirect-to-pool, redirect-to-URL and reject;
- rule types such as cookie, file type, header, host name and path;
- comparison modes such as contains, ends-with, equal-to, regex and starts-with.

[S14]

In contrast, in the upstream LoxiLB Swagger file reviewed here:

- the standalone REST API clearly exposes generic load-balancer service operations;
- a text search of that Swagger file did **not** find an explicit `L7` resource;
- no Octavia-equivalent `L7Policy` / `L7Rule` object model was found in that public standalone Swagger surface.

[S10]

This is significant for an Octavia Provider Driver. Having an HTTP parser or transparent proxy does not automatically mean that Octavia's L7 policy/rule CRUD model can be represented faithfully.

## 5.3 How documented L7 works

There appear to be at least two distinct L7 areas and they should not be conflated.

### A. HTTP/Ingress/Gateway-oriented L7

The current introduction explicitly frames Kubernetes L7 support through its Ingress implementation, with eBPF `sockmap` acceleration/helpers. [S1]

The official Gateway API material shows Kubernetes `HTTPRoute`-style routing as part of a Kubernetes control path. [S9]

This path involves Kubernetes resources/controllers and is therefore a **Kubernetes integration feature**, even though parts of the proxy implementation may be reusable internally.

### B. Protocol-aware/transparent L7 or telco parsing

Release material identifies transparent proxy, HTTP/2 parsing and NGAP parsing as functional features rather than merely Kubernetes features. [S12]

The current introduction also discusses protocol-aware telco use cases such as NGAP. [S1]

This is evidence of L7/protocol-aware processing inside the broader LoxiLB project, but it still does not prove general Octavia HTTP L7 feature equivalence.

## 5.4 Core feature or Kubernetes-specific?

The correct answer is **mixed**:

- **L7 implementation is not purely Kubernetes-only.** Official release notes describe transparent proxy, HTTPS termination and parsers as functional features.
- **The best-documented HTTP routing integration is Kubernetes-specific**, especially Ingress/Gateway API and `loxilb-ingress`.
- **Standalone Octavia-style L7 CRUD semantics are not evidenced by the reviewed Swagger API.**

That distinction should be preserved in any thesis/report.

## 5.5 Limitations and external dependencies

Open questions and constraints include:

- No reviewed official evidence demonstrates full Octavia `L7Policy`/`L7Rule` parity.
- HTTP/HTTPS routing documentation is much stronger in Kubernetes workflows than standalone workflows.
- TLS certificate lifecycle/mapping to OpenStack Barbican is not established by these LoxiLB sources.
- Octavia listener protocols and termination models may not map directly to LoxiLB's proxy modes.
- It is not established that every Octavia L7 rule type and action is supported.
- The relationship between the core LoxiLB proxy functions and the separate `loxilb-ingress` project needs source-level validation if L7 is pursued.
- `sockmap`-related functionality can require host PID/cgroup namespace access in standalone container deployment; the standalone guide explicitly calls out extra container arguments for local socket policy/eBPF sockmap features. [S3]

## 5.6 Relevance to OpenStack Octavia

**Not recommended for the first Provider Driver MVP.**

For an MVP, the safer capability declaration is:

> L4 only; L7 policies/rules return unsupported/not-implemented until a precise mapping and standalone control path are proven.

Octavia's Provider Driver interface explicitly permits a provider to raise `NotImplementedError` for unsupported operations and `UnsupportedOptionError` for unsupported options. [S14]

L7 could become a later phase if research proves one of the following:

1. native LoxiLB standalone APIs can represent Octavia's L7 model;
2. a stable LoxiLB proxy API exists outside the currently reviewed Swagger;
3. a deliberate adapter to a separate L7 controller is architecturally acceptable.

## 5.7 What still requires lab/source verification

Before claiming Octavia L7 support:

1. Identify the exact upstream source modules implementing HTTP L7 proxying.
2. Identify the public control API for creating/removing L7 policies outside Kubernetes.
3. Verify host/path/header/cookie routing behavior.
4. Verify redirect/reject actions.
5. Verify TLS termination and certificate lifecycle.
6. Verify HTTP/1.1 and HTTP/2 traffic behavior.
7. Determine whether `loxilb-ingress` is mandatory for ordinary HTTP L7 routing.
8. Determine whether L7 state/config can be recovered and reconciled after restart.
9. Compare every intended Octavia L7 action/rule type against actual LoxiLB behavior.
10. Only after that advertise L7 capability from the Provider Driver.

---

# 6. BGP

## 6.1 Status

**Classification: PROVEN CORE/STANDALONE INTEGRATION, WITH EXTERNAL GoBGP DEPENDENCY**

LoxiLB uses GoBGP as its routing stack. The official architecture documentation explicitly says GoBGP is a separate project that LoxiLB has adopted and integrated. [S2]

The standalone guide contains a concrete non-Kubernetes workflow:

1. create `gobgp.conf`;
2. configure local AS, router ID and neighbor;
3. start LoxiLB with BGP enabled;
4. verify the neighbor with the `gobgp` CLI.

It also states that GoBGP is packaged in the LoxiLB Docker image, while a systemd/package deployment requires GoBGP to be installed separately. [S3]

This is direct evidence that BGP is not limited to Kubernetes.

## 6.2 How it works in LoxiLB

Conceptually:

```text
LoxiLB service/VIP state
        |
LoxiLB Go control plane
        |
     GoBGP
        |
 BGP peers / fabric
        |
 route to service VIP
```

LoxiLB can advertise service IPs through the integrated GoBGP process. In HA designs, route attributes and availability determine which LoxiLB node(s) receive external traffic. [S4]

## 6.3 Core feature or Kubernetes-specific?

**Core integration:** GoBGP-backed routing itself.

**Kubernetes-specific automation includes:**

- `kube-loxilb --setBGP`;
- `--extBGPPeers`;
- automatic BGP peering between LoxiLB pods;
- BGP peer/policy CRDs.

[S8][S12]

An OpenStack implementation should generally use the underlying LoxiLB/GoBGP capability or provider-side configuration rather than depend on Kubernetes CRDs.

## 6.4 Limitations and external dependencies

- GoBGP is a separate upstream project, although packaged/integrated by LoxiLB.
- BGP requires reachable peers and correct routing policy in the infrastructure.
- Route filtering, AS design, multipath policy, BFD and operational safeguards belong partly to the network fabric.
- Kubernetes CRD automation should not be assumed available in OpenStack.
- Provider security policy must decide who may modify BGP peers/routes.
- BGP convergence and failure timing depend on peer configuration and the external network, not only LoxiLB.

## 6.5 Relevance to OpenStack Octavia

**High for deployment architecture, but not a normal Octavia resource.**

BGP can solve an important question:

> How does a client/network learn that a given Octavia VIP is reachable through one or more LoxiLB nodes?

Possible provider architectures could use BGP to advertise VIPs from LoxiLB appliances/nodes toward a routed OpenStack/provider network.

However, the Provider Driver must not treat “BGP” as if it were a Listener or Pool. It belongs mainly in:

- provider flavor/configuration;
- infrastructure automation;
- LoxiLB node lifecycle;
- VIP advertisement;
- HA/scale-out routing.

## 6.6 What still requires lab verification

1. Standalone eBGP from LoxiLB VM to a lab router.
2. VIP advertisement on service create.
3. VIP withdrawal on service delete.
4. VIP withdrawal when LoxiLB is unhealthy.
5. IPv4/IPv6 behavior.
6. Route-policy/attribute behavior.
7. BFD integration if used.
8. Reconciliation after GoBGP/LoxiLB restart.
9. OpenStack security-group/firewall rules for BGP.
10. Whether provider networking allows the required peering and route propagation.

---

# 7. ECMP

## 7.1 Status

**Classification: PROVEN HA/DEPLOYMENT ARCHITECTURE; PROVIDER-INFRASTRUCTURE DEPENDENCY**

Official HA documentation contains an explicit scenario named:

> **L3 network (active-active with BGP ECMP)**

It says the service IPs are advertised with the same attributes/priority/MED and that network devices/hosts must be capable of supporting ECMP. [S4]

The same guide says that on failure, BGP on the client/network updates the ECMP route and begins sending traffic to the remaining active ECMP endpoints. [S4]

## 7.2 What ECMP means here

ECMP in this architecture is **not** LoxiLB choosing among backend members.

There are two different load-distribution layers:

```text
Layer A: network ECMP
client/router
   |-- equal-cost path --> LoxiLB node A
   `-- equal-cost path --> LoxiLB node B

Layer B: LoxiLB endpoint selection
LoxiLB node
   |-- rr/hash/lc/etc --> backend 1
   `-- rr/hash/lc/etc --> backend 2
```

ECMP distributes traffic across LoxiLB instances or routes.

LoxiLB's RR/hash/LC/etc. algorithms distribute service traffic to backend endpoints.

Treating these as the same feature would produce an incorrect architecture.

## 7.3 Core or Kubernetes-specific?

The official **worked example is Kubernetes-oriented** and uses `kube-loxilb` to automate peering and service configuration. [S4]

However:

- BGP itself is supported in standalone mode; [S3]
- the HA guide explicitly says similar configuration should suffice for external deployments; [S4]
- ECMP ultimately depends on equal route advertisements and network multipath support.

Therefore the correct classification is:

> **ECMP is an LoxiLB-supported deployment/HA design whose official example is Kubernetes-oriented, but the underlying mechanism is not inherently Kubernetes-only. A standalone/OpenStack implementation still requires lab proof.**

## 7.4 External dependencies

The official guide is explicit that network devices/hosts must support ECMP. [S4]

In an OpenStack deployment, additional provider concerns include:

- whether the upstream router supports multipath;
- whether multiple equal-cost routes to the same VIP are accepted;
- route hashing behavior;
- symmetry requirements for stateful NAT;
- how routes are withdrawn when a node fails;
- how traffic behaves while the BGP control plane converges.

## 7.5 Relevance to OpenStack Octavia

**High for a later scale-out/HA phase.**

ECMP could support a design in which multiple LoxiLB instances are simultaneously active and advertise the same VIP.

This is attractive for:

- horizontal scale;
- avoiding a single active dataplane node;
- spreading new flows across appliances.

But it should be implemented as a **provider deployment strategy**, not as an Octavia pool algorithm.

## 7.6 Critical connection-state caveat

The official HA guide documents active-active BGP ECMP as **Scenario 3**.

It separately documents **Scenario 4 — ACTIVE-BACKUP with Connection Sync** and states that connection-sync mode is supported when LoxiLB runs externally outside Kubernetes in default or full-NAT mode. It says LoxiLB synchronizes long-lived connections to configured peers. [S4]

This review found **no official evidence that the active-active ECMP scenario performs full connection-state synchronization among active nodes**.

Therefore the following must **not** be claimed:

- “active-active ECMP provides synchronized conntrack on every LoxiLB node”;
- “an existing TCP connection always survives failure of any active-active LoxiLB node”;
- “ECMP failover is hitless for all flows.”

Those properties require explicit upstream evidence or lab measurements.

## 7.7 What still requires lab verification

1. Two standalone LoxiLB nodes advertising the same VIP.
2. Equal-cost routes actually installed by the chosen router.
3. New-flow distribution across both nodes.
4. Node-failure route withdrawal.
5. Existing TCP connection behavior after one active node fails.
6. Return-path symmetry in one-arm/full-NAT modes.
7. Interaction with health monitoring.
8. BGP convergence time.
9. Recovery/rejoin behavior.
10. Whether any state synchronization exists in the chosen active-active mode.
11. Scale from 2 to N LoxiLB nodes.
12. Effect of router hash policy on distribution.

---

# 8. eBPF

## 8.1 Status

**Classification: PROVEN CORE DATAPLANE**

eBPF is not merely an acceleration option around a conventional userspace proxy; it is central to LoxiLB's dataplane architecture.

Official architecture documentation says:

- the Go control plane populates eBPF maps and loads eBPF programs on interfaces;
- the eBPF component implements the dataplane.

[S2]

The official eBPF internals guide provides implementation-level detail. [S5]

## 8.2 How it works

The documentation describes two built objects:

- `llb_ebpf_main.o`;
- `llb_xdp_main.o`.

It explains that:

- most L4+ processing occurs at the **TC eBPF** layer;
- XDP is used for selected operations where its very early packet-processing hook is advantageous;
- the main TC function handles most packet processing;
- a slower path performs NAT lookup and stateful conntrack establishment;
- established connections can then be processed through the main fast path;
- LoxiLB uses pinned BPF maps for networking state.

[S5]

This is direct architectural evidence that load balancing/NAT/conntrack are tied closely to eBPF state.

## 8.3 TC versus XDP

A common oversimplification would be to describe LoxiLB as “an XDP load balancer.”

The official internals documentation instead says the bulk of L4+ processing is done in TC eBPF. XDP is used for selected quick/special operations such as some L2 functionality. [S5]

A more accurate statement is:

> LoxiLB is an eBPF dataplane using TC eBPF as the principal L4+ processing hook, with XDP used selectively.

## 8.4 Core feature or Kubernetes-specific?

**Core.**

The standalone deployment uses the same LoxiLB dataplane. Kubernetes merely supplies an optional control/integration layer.

## 8.5 Requirements and limitations

Current official requirements state:

- 64-bit supported Linux distributions;
- **Linux kernel >= 5.15.x**;
- Windows is listed as planned;
- 2 vCPU / 2 GB is described as sufficient for a starter deployment.

[S11]

The eBPF internals also show that the Go agent loads programs onto relevant interfaces by default. [S5]

This has direct consequences for OpenStack VM deployment:

- virtual NIC behavior matters;
- kernel capabilities matter;
- offload behavior can matter;
- interface discovery/blacklisting matters;
- container privilege/capabilities matter.

The LoxiLB roadmap/history explicitly mentions improved virtio support as a past enhancement, which is a reason to test the exact OpenStack virtio environment instead of assuming parity with bare metal. [S12]

## 8.6 Relevance to OpenStack Octavia

eBPF is the **dataplane foundation**, not an Octavia API feature.

Octavia does not need to expose “eBPF” to users. Rather:

- the Provider Driver configures logical LB resources;
- LoxiLB translates those into eBPF map/program state;
- the Provider Driver reports resulting status/statistics back to Octavia.

This separation is desirable because Octavia stays vendor-neutral while LoxiLB provides the high-performance implementation.

## 8.7 What still requires lab verification in OpenStack

1. LoxiLB in a VM using the actual OpenStack virtio NIC model.
2. TC eBPF attachment to the expected interfaces.
3. MTU behavior.
4. checksum/GSO/GRO/TSO interactions.
5. VLAN/provider-network behavior if relevant.
6. SR-IOV behavior if that is a deployment target.
7. eBPF program loading after VM reboot.
8. coexistence with host/container networking.
9. packet path under one-arm/full-NAT/DSR.
10. CPU/memory scaling under expected throughput/CPS/RPS.
11. kernel compatibility of the production OpenStack image.

---

# 9. Capability comparison matrix

| Capability | Direct official evidence | Core standalone? | Kubernetes-specific part | External/provider dependency | Octavia assessment |
|---|---|---:|---|---|---|
| Stateful L4 LB | Current docs, standalone CLI, REST API, eBPF internals | **Yes** | `kube-loxilb` automates K8s Services | VIP/network reachability | **Strong MVP candidate** |
| TCP/UDP/SCTP L4 | Current official feature list | **Yes** | Service annotations/discovery | Network/backend reachability | **High relevance** |
| RR / WRR / persistence / hash / LC | Official algorithm guide | **Yes** | Annotation-based selection in K8s | None fundamental | **Map to Pool algorithm with validation** |
| Endpoint health checking | Current docs + HA/K8s docs | **Yes / underlying feature** | K8s annotations automate probes | Endpoint connectivity | **Map to HealthMonitor, semantics need validation** |
| HTTP L7 proxy | Current feature list + release history | **Implemented** | Strongest documented routing path is Ingress/Gateway | proxy/TLS configuration | **Do not claim Octavia parity yet** |
| Kubernetes Ingress | Official docs | No — integration itself is K8s | **Yes** | Kubernetes + ingress components | **Not directly reusable as Octavia API** |
| Kubernetes Gateway API | Official guide | No — integration itself is K8s | **Yes** | Gateway API CRDs/controllers | **Conceptual evidence only for L7** |
| Octavia-style L7Policy/L7Rule | No equivalent found in reviewed standalone Swagger | **Not evidenced** | N/A | would require adapter/new API | **Unsupported for MVP** |
| GoBGP integration | Architecture + standalone guide | **Yes** | K8s flags/CRDs automate it | GoBGP + BGP peers | **Useful provider infrastructure** |
| Active-active BGP ECMP | Official HA scenario | Mechanism can be external; worked example K8s | kube-loxilb automates example | **ECMP-capable router/host required** | **Promising scale-out mode** |
| Active-active connection sync | No official evidence found | **Not evidenced** | — | — | **Must not claim** |
| Active-backup connection sync | Official HA scenario | **Yes, explicitly external in documented mode** | kube-loxilb participates in example orchestration | peer connectivity/BGP as used | **Potential HA mode; lab required** |
| eBPF dataplane | Architecture + eBPF internals/source | **Yes** | None fundamental | Linux kernel / interfaces | **Foundational dataplane** |
| TC eBPF L4+ processing | Official internals | **Yes** | None | Linux networking/eBPF | **Foundational** |
| XDP | Official internals | **Yes, selective use** | None | driver/kernel capabilities | **Do not describe as sole LB hook** |

---

# 10. OpenStack Octavia relevance

## 10.1 What Octavia expects from a Provider Driver

OpenStack's official Provider Driver guide defines stable interfaces for provider implementations and requires providers to handle or explicitly reject resource operations.

Key resource types include:

- LoadBalancer;
- Listener;
- Pool;
- Member;
- HealthMonitor;
- L7Policy;
- L7Rule.

Providers also need to report:

- provisioning status;
- operating status;
- listener statistics.

[S14]

This means successful packet forwarding alone is not sufficient. A production Provider Driver also needs a control-state model.

## 10.2 Recommended initial support boundary

Based on the reviewed evidence, a defensible MVP is:

### Support first

- LoadBalancer lifecycle;
- L4 Listener;
- Pool;
- Member;
- basic HealthMonitor;
- TCP;
- UDP;
- a small validated set of algorithms, likely RR first;
- one simple deployment mode, likely a topology that is easiest to reproduce in the lab;
- status callbacks;
- basic statistics if the LoxiLB API exposes sufficiently reliable counters.

### Defer

- L7Policy;
- L7Rule;
- TLS termination;
- advanced persistence;
- BGP ECMP active-active;
- connection synchronization;
- BFD;
- DSR;
- SCTP multihoming;
- advanced LoxiLB-specific telco features.

BGP/ECMP should be a later provider-infrastructure phase after a single-node L4 path works reliably.

## 10.3 Why BGP/ECMP are not direct Octavia resource mappings

Octavia describes what load-balancing service a tenant wants.

BGP and ECMP describe how the provider makes that service reachable and resilient.

A useful separation is:

```text
Tenant-visible Octavia model
LB -> Listener -> Pool -> Members -> HealthMonitor
                 |
                 v
Provider implementation
LoxiLB rules + LoxiLB nodes + VIP plumbing + optional BGP/ECMP
```

This permits multiple provider deployment modes without changing the basic Octavia API.

## 10.4 Status and reconciliation challenge

The LoxiLB Swagger API supports querying LB services and conntrack state, which is promising for reconciliation. [S10]

But the Provider Driver still needs to answer:

- What constitutes `ACTIVE` versus `ERROR`?
- What constitutes `ONLINE`, `OFFLINE`, `DEGRADED`?
- How are backend health changes translated to member/pool operating status?
- How are asynchronous failures reported?
- How are stale LoxiLB rules detected?
- How is configuration reconstructed after a driver restart?
- How are per-listener Octavia statistics derived from LoxiLB counters?

These are Provider Driver concerns, not eBPF dataplane concerns.

---

# 11. Important limitations and non-claims

The following statements are intentionally **not** made by this report.

## 11.1 No claim of full Octavia L7 support

LoxiLB has L7 functionality, but the reviewed evidence does not establish a generic standalone API equivalent to Octavia's L7 policy/rule model.

## 11.2 No claim of active-active connection synchronization

The official HA guide separates:

- active-active BGP ECMP;
- active-backup connection synchronization.

This report does not merge those scenarios.

## 11.3 No claim that ECMP is a LoxiLB pool algorithm

ECMP is a routing/fabric distribution mechanism. Backend algorithms such as RR/hash/LC are separate.

## 11.4 No claim that Kubernetes is required for L4 or BGP

Standalone L4 and standalone GoBGP configuration are both officially documented.

## 11.5 No claim that all virtualized NIC environments behave like bare metal

The actual OpenStack virtio/kernel/offload environment needs lab testing.

## 11.6 No claim of semantic parity based only on matching names

For example, “least connections” or “persistence” may exist in both systems while still differing in details that matter to an Octavia API contract.

---

# 12. Lab-verification plan derived from unresolved evidence

This is not an implementation plan; it is a research-validation checklist.

## Phase A — prove standalone L4 control

- Deploy one LoxiLB node/VM.
- Create and delete services using REST.
- Validate TCP and UDP.
- Validate two backend members.
- Validate RR.
- Capture LoxiLB service state and conntrack.
- Restart LoxiLB and test persistence/reconciliation.

**Exit criterion:** L4 service lifecycle is reproducible without Kubernetes.

## Phase B — prove Octavia-semantic primitives

- member add/remove/update;
- member weight;
- endpoint failure;
- health-monitor behavior;
- operating-state transitions;
- counters/statistics.

**Exit criterion:** enough behavior is known to map LB/Listener/Pool/Member/HealthMonitor.

## Phase C — prove OpenStack dataplane compatibility

- virtio NIC;
- eBPF attachment;
- MTU/offload behavior;
- actual tenant/provider network path;
- VIP reachability.

**Exit criterion:** LoxiLB works reliably as a VM/appliance in the target OpenStack environment.

## Phase D — prove BGP

- external GoBGP peer;
- advertise/withdraw VIP;
- failure convergence.

**Exit criterion:** provider network can reliably route VIPs through LoxiLB.

## Phase E — prove active-active ECMP

- two LoxiLB nodes;
- equal-cost advertisements;
- new-flow distribution;
- node failure;
- existing-flow observation.

**Exit criterion:** actual HA behavior is measured, including whether existing sessions survive or reset.

## Phase F — investigate L7 separately

- locate authoritative standalone L7 control surface;
- map exact Octavia L7 policies/rules;
- test HTTP routing and TLS;
- explicitly mark unsupported fields.

**Exit criterion:** only advertise L7 if the mapping is demonstrably correct.

---

# 13. Unresolved questions

## 13.1 L4 / API

1. What is the exact current REST schema for endpoint weights, algorithms, probe options and NAT modes in the release selected for the project?
2. Does the REST API provide atomic update semantics, or must a Provider Driver recreate LB rules?
3. Which LoxiLB counters best map to Octavia listener statistics?
4. What are the API's concurrency, authentication and multi-user guarantees?
5. What reconciliation mechanism is safest after Provider Driver or LoxiLB restart?

## 13.2 L7

6. What upstream module is the authoritative implementation of policy-driven HTTP proxying?
7. Is there a stable, supported standalone REST API for HTTP host/path/header/cookie policies?
8. Can LoxiLB represent Octavia `REDIRECT_TO_POOL`, `REDIRECT_TO_URL`, `REDIRECT_PREFIX` and `REJECT` semantics?
9. Can it represent Octavia `COOKIE`, `FILE_TYPE`, `HEADER`, `HOST_NAME` and `PATH` rules with required compare operations?
10. Is `loxilb-ingress` required for ordinary HTTP L7 routing?
11. How would Barbican-managed TLS certificates be delivered and rotated?
12. Is L7 configuration/state exposed in the same standalone API used for L4?

## 13.3 BGP / ECMP / HA

13. What BGP topology best matches the target OpenStack network?
14. Will the provider router accept multiple equal-cost VIP routes?
15. What exact BGP attributes are used for active-active versus active-backup?
16. What failure detector should trigger withdrawal: LoxiLB process health, node health, BFD, or another mechanism?
17. Are existing active-active connections lost when their ingress LoxiLB node fails?
18. Is there any supported state-sync mode that can be combined with active-active ECMP? **No such combination is claimed by this report.**
19. How does ECMP behave with one-arm versus full-NAT return paths?
20. How does scale-out from two to more LoxiLB nodes affect flow distribution?

## 13.4 eBPF / OpenStack

21. Does the target OpenStack guest kernel satisfy LoxiLB's required eBPF features?
22. Does the exact virtio configuration need offload adjustments?
23. Are there conflicts with other TC/eBPF programs in the guest?
24. What interface blacklist/attachment policy is required?
25. Is SR-IOV part of the target deployment, and if so, how does it affect the dataplane?
26. What are realistic throughput/CPS/RPS/latency limits for the actual VM flavor?

---

# 14. Research conclusions

### L4

**Proven and appropriate for an Octavia MVP.**  
There is strong official evidence for standalone L4 service configuration, eBPF stateful dataplane processing, multiple endpoint algorithms and a standalone REST API.

### L7

**Real capability exists, but Octavia parity is not established.**  
LoxiLB documentation shows HTTP L7 proxy work, HTTPS termination, protocol parsers and Kubernetes Ingress/Gateway integration. That is insufficient evidence for claiming the complete Octavia L7 policy/rule API. Treat L7 as deferred until a precise standalone mapping is proven.

### BGP

**Proven standalone/core integration through GoBGP.**  
Useful for VIP advertisement and HA, but depends on external routing infrastructure and should mostly live below the tenant-facing Octavia model.

### ECMP

**Proven as an officially documented active-active HA architecture.**  
It depends on ECMP-capable network devices/hosts and is separate from backend load-balancing algorithms. A standalone/OpenStack design is plausible but must be validated.

### eBPF

**Proven core dataplane.**  
TC eBPF carries most L4+ processing, with selective XDP use. Linux/kernel/interface compatibility is therefore a first-class deployment requirement.

### HA state synchronization

**Only make the narrow claim supported by the official guide:** connection synchronization is documented in an **external active-backup** scenario for default/full-NAT mode and long-lived connections.  
**Do not claim active-active ECMP connection synchronization without further evidence.**

---

# 15. Official sources

## Primary LoxiLB documentation and upstream source

**[S1] LoxiLB official current documentation — Introduction / features**  
https://docs.loxilb.io/main/  
Evidence used: L4 default role, current feature list, L7 statement, eBPF/GoBGP components, Kubernetes integrations.

**[S2] LoxiLB official architecture overview**  
https://docs.loxilb.io/main/arch/  
Evidence used: Go control plane, eBPF map programming/loading, eBPF dataplane, GoBGP integration.

**[S3] LoxiLB official standalone deployment guide**  
https://docs.loxilb.io/main/standalone/  
Evidence used: standalone `loxicmd` LB rule, standalone GoBGP setup, GoBGP packaging/manual dependency, sockmap-related container requirements.

**[S4] LoxiLB official HA deployment guide**  
https://docs.loxilb.io/main/ha-deploy/  
Evidence used: active-active BGP ECMP, network ECMP dependency, route failover, separate active-backup connection-sync scenario.

**[S5] LoxiLB official eBPF internals**  
https://docs.loxilb.io/loxilbebpf/  
Evidence used: TC/XDP object files, TC as main L4+ path, eBPF loading, conntrack/NAT path and pinned maps.

**[S6] LoxiLB official load-balancer algorithms**  
https://docs.loxilb.io/lb-algo/  
Evidence used: RR, WRR, persistence, flow hash and least-connections behavior.

**[S7] LoxiLB official NAT mode documentation**  
https://docs.loxilb.io/nat/  
Evidence used: NAT/one-arm/full-NAT/DSR deployment semantics.

**[S8] LoxiLB official kube-loxilb architecture/configuration**  
https://docs.loxilb.io/main/kube-loxilb/  
Evidence used: separation of Kubernetes operator from LoxiLB dataplane, BGP automation flags, Kubernetes-specific integration.

**[S9] LoxiLB official Kubernetes Gateway API L4/L7 guide**  
https://docs.loxilb.io/v0.9.7/gw-api/  
Evidence used: Kubernetes Gateway API/HTTPRoute-oriented L7 path.  
Note: this is a versioned official guide and should not by itself be treated as proof of current generic standalone L7 semantics.

**[S10] Upstream LoxiLB Swagger REST API**  
https://github.com/loxilb-io/loxilb/blob/main/api/swagger.yml  
Evidence used: API described for bare-metal scenarios, `/netlox/v1`, load-balancer create/get/delete, conntrack inspection. No explicit `L7` resource was found by text search in the reviewed file.

**[S11] LoxiLB official system requirements**  
https://docs.loxilb.io/main/requirements/  
Evidence used: supported Linux environments and Linux kernel >= 5.15.x.

**[S12] LoxiLB official release/development roadmap**  
https://docs.loxilb.io/roadmap/  
Evidence used: historical milestones for L7 transparent proxy, HTTPS termination, HTTP/2 parser, ECMP support, virtio improvements and Kubernetes BGP/Gateway integrations.

**[S13] Upstream LoxiLB repository**  
https://github.com/loxilb-io/loxilb  
Evidence used: upstream implementation/repository context and current README.

### Additional upstream LoxiLB repositories

**LoxiLB eBPF source repository/submodule**  
https://github.com/loxilb-io/loxilb-ebpf

**loxilb-ingress upstream repository**  
https://github.com/loxilb-io/loxilb-ingress

**kube-loxilb upstream repository**  
https://github.com/loxilb-io/kube-loxilb

## OpenStack sources used only for Octavia relevance

**[S14] OpenStack Octavia Provider Driver Development Guide**  
https://docs.openstack.org/octavia/latest/contributor/guides/providers.html  
Evidence used: provider resource interfaces, unsupported-operation behavior, L7Policy/L7Rule model, status/statistics callbacks.

**[S15] OpenStack Octavia API v2 reference**  
https://docs.openstack.org/api-ref/load-balancer/v2/  
Evidence used: current Octavia API resource/protocol/health-monitor context.

---

## Final research position

For the proposed OpenStack integration, the evidence supports treating LoxiLB primarily as a **standalone eBPF-based L4 dataplane controlled through its API**, with **GoBGP/BGP and ECMP as optional provider-level HA/scale-out mechanisms**.

The research does **not** support advertising full Octavia L7 capability in an MVP, and it does **not** support claiming active-active connection-state synchronization.

No code was implemented as part of this research.
