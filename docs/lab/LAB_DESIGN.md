# Lab Design

## 1. Goal

Design the **smallest practical lab** that can validate the following sequence without prematurely building a production-scale environment:

1. OpenStack + Neutron networking works.
2. Octavia Amphora works as the reference baseline.
3. OVN can be used as a second Octavia provider **if the lab is deployed with ML2/OVN from the beginning**.
4. LoxiLB works independently as an L4 load balancer.
5. A LoxiLB Octavia Provider Driver can be installed and exercised end-to-end.
6. The same lab can later be extended to BGP/ECMP and multi-node LoxiLB without redesigning everything.

This is a **functional integration lab**, not the final performance benchmark environment. CPU overcommit, nested virtualization, virtual NICs, and a single compute host are acceptable for correctness testing but must not be used to make production performance claims.

---

## 2. Design decisions

### 2.1 OpenStack deployment model

Use **one OpenStack all-in-one node** for the first lab:

- Keystone
- Glance
- Nova API/Scheduler/Conductor/Compute
- Placement
- Neutron server
- OVN Northbound/Southbound DB
- OVN Northd
- OVN Controller
- Octavia API
- Octavia Worker
- Octavia Health Manager
- Octavia Housekeeping
- MariaDB
- RabbitMQ

For the smallest R&D setup, DevStack is the simplest choice. If the Viettel IDC target environment is Kolla-Ansible, reproduce the validated design in Kolla later; do not make the first functional lab unnecessarily large.

**Important:** deploy Neutron with **ML2/OVN from day one**. This makes the OVN Octavia provider feasible later while Amphora remains usable as a parallel provider.

### 2.2 First LoxiLB topology

Start with **one LoxiLB VM in one-arm mode** on the same tenant subnet as the client and backend VMs.

Why:

- one LoxiLB VM;
- one data NIC;
- one tenant subnet;
- no BGP router yet;
- no separate frontend/backend routing design yet;
- easy manual validation before the Provider Driver is involved.

This is intentionally a **functional MVP topology**, not the final performance or HA topology.

### 2.3 Initial Provider Driver scope

The first end-to-end target should be:

- LoadBalancer
- TCP Listener
- Pool
- two Members
- TCP HealthMonitor
- create/update/delete
- provisioning status
- operating status
- Neutron VIP plumbing

UDP should be validated immediately after TCP. L7/TLS should not be required for the first successful lab.

### 2.4 OVN is optional, not a blocker

OVN Provider validation is useful as a second OpenStack-native L4 baseline, but it must **not block LoxiLB Provider Driver development**.

Use OVN only for features it actually supports. In the current OpenStack feature matrix, OVN is primarily an L4 provider and does not have Amphora feature parity. For example, TCP/UDP are supported, while HTTP/HTTPS listener features are not; SOURCE_IP_PORT is the relevant OVN pool algorithm, and TCP/UDP-CONNECT health monitoring is supported.

---

## 3. Initial topology

```text
                            LAB HOST / PARENT VM

              +-----------------------------------------+
              |          os-aio (OpenStack AIO)         |
              |                                         |
              | Keystone / Nova / Glance / Neutron      |
              | OVN / Octavia / DB / MQ                 |
              | nova-compute                            |
              +-------------------+---------------------+
                                  |
                                  | Neutron / OVN virtual networking
                                  |
                +-----------------+------------------+
                |                                    |
          public/provider                       lb-net
          172.24.4.0/24                       10.20.0.0/24
                |                                    |
                |                          +---------+---------+
                |                          |         |         |
                |                          |         |         |
                |                     LoxiLB-1    client-1  backend-1
                |                     10.20.0.10  10.20.0.30 10.20.0.21
                |                          |                   |
                |                          |                backend-2
                |                          |                10.20.0.22
                |                          |
                |                     VIP pool
                |                     10.20.0.100-119
                |
                +---- Floating IP / management access to LoxiLB API


Octavia Amphora baseline:

client-1 -> Octavia VIP -> Amphora VM -> backend-1/backend-2

OVN baseline:

client-1 -> Octavia VIP -> OVN logical LB -> backend-1/backend-2

LoxiLB standalone / provider:

client-1 -> VIP 10.20.0.100 -> LoxiLB-1 -> backend-1/backend-2
```

Octavia also requires its own Amphora management connectivity. Keep it separate from the tenant data network:

```text
octavia-mgmt: 172.31.0.0/24

os-aio health-manager/controller
          |
          +-------------------- Amphora management interface
```

---

## 4. Node and VM roles

| Node/VM | Role | Initial requirement | Notes |
|---|---|---:|---|
| `os-aio` | OpenStack controller + compute + OVN + Octavia | Required | The only infrastructure node in the smallest lab. |
| `loxilb-1` | LoxiLB dataplane + API | Required | Fixed appliance for standalone and Provider Driver testing. |
| `client-1` | Traffic generator / functional client | Required | curl, iperf3, wrk/hey later. |
| `backend-1` | Backend server | Required | nginx or small HTTP/TCP echo service. |
| `backend-2` | Backend server | Required | Needed to prove load distribution and health behavior. |
| Amphora VM | Octavia Amphora reference LB | Dynamically created | Spawned by Octavia through Nova. |
| OVN LB | Distributed OVN dataplane | Optional | No dedicated LB VM is required. |
| `loxilb-2` | Second LoxiLB node | Later | Added for HA/BGP/ECMP phase. |
| `frr-router` | BGP peer / ECMP router | Later | Added only when multi-node LoxiLB is tested. |

---

## 5. Network and subnet plan

### 5.1 Infrastructure/host network

| Purpose | Network | Example IP |
|---|---|---|
| Lab host / parent management | existing lab LAN | environment-specific |
| `os-aio` management | existing lab LAN | e.g. `192.168.50.10` |

Do not hard-code the parent LAN into OpenStack configuration until the actual Viettel IDC lab network is known.

### 5.2 OpenStack public/provider network

| Item | Value |
|---|---|
| Network | `public` |
| Type | flat/provider network through `br-ex` |
| CIDR | `172.24.4.0/24` |
| Gateway | `172.24.4.1` |
| Floating IP pool | `172.24.4.100-172.24.4.199` |

Use this for:

- floating IP access to test VMs;
- access to the LoxiLB management API if needed;
- general lab debugging.

### 5.3 Tenant load-balancer network

| Item | Value |
|---|---|
| Network | `lb-net` |
| CIDR | `10.20.0.0/24` |
| Gateway | `10.20.0.1` |
| `loxilb-1` data IP | `10.20.0.10` |
| `backend-1` | `10.20.0.21` |
| `backend-2` | `10.20.0.22` |
| `client-1` | `10.20.0.30` |
| Reserved test VIP range | `10.20.0.100-10.20.0.119` |

The first manual LoxiLB service can use:

```text
VIP:      10.20.0.100:80/TCP
Backend:  10.20.0.21:80
Backend:  10.20.0.22:80
```

### 5.4 Octavia management network

| Item | Value |
|---|---|
| Network | `octavia-mgmt` |
| CIDR | `172.31.0.0/24` |
| Purpose | controller/health-manager to Amphora management traffic |

Keep this network operator-owned and separate from tenant workloads.

### 5.5 Neutron VIP handling for LoxiLB

This is a **critical validation point**, not something to hide with broad port-security exceptions.

For the standalone LoxiLB smoke test, it is acceptable to temporarily use a manually configured VIP and a controlled port-security workaround.

For Provider Driver validation, the target behavior is:

1. Octavia/driver reserves the VIP in Neutron.
2. The LoxiLB data port is explicitly permitted to send/receive the VIP using the correct Neutron mechanism, normally a `/32` allowed-address-pair or a provider-created VIP-port workflow.
3. The driver removes that networking state when the LB is deleted.
4. Port security is **not disabled globally**.

The exact VIP-port ownership model should be finalized during Provider Driver implementation because Octavia allows providers to implement `create_vip_port()` themselves.

---

## 6. CPU, RAM and disk sizing

### 6.1 Smallest host that is still practical

| Resource | Functional minimum | Comfortable R&D target |
|---|---:|---:|
| CPU | 16 vCPU | 24 vCPU |
| RAM | 32 GB | 48 GB |
| Disk | 160 GB SSD | 200-250 GB SSD |
| NIC | 1 usable NIC | 1-2 NICs |
| Virtualization | KVM required | KVM required |

**If `os-aio` itself runs inside another VM, nested virtualization must expose VT-x/AMD-V and `/dev/kvm`.** Without hardware-assisted nested virtualization, Nova/Amphora can sometimes be forced through software emulation, but the lab becomes slow and unsuitable even for realistic functional timing.

### 6.2 Guest sizing

| VM | vCPU | RAM | Disk | Notes |
|---|---:|---:|---:|---|
| `loxilb-1` | 2 | 2 GB | 10 GB | Raise to 4 vCPU/4 GB for stress tests. |
| `client-1` | 2 | 2 GB | 10 GB | Functional traffic only. |
| `backend-1` | 1 | 1 GB | 5 GB | nginx/echo server. |
| `backend-2` | 1 | 1 GB | 5 GB | nginx/echo server. |
| Amphora, SINGLE | 1-2 | 1-2 GB | ~5 GB | Use a deliberately small lab flavor. |
| Amphora, ACTIVE_STANDBY | 2 x above | 2 x above | 2 x above | Test after SINGLE works. |
| `loxilb-2` | 2 | 2 GB | 10 GB | Later HA phase. |
| `frr-router` | 1 | 1 GB | 5 GB | Later BGP phase. |

The 32 GB host budget is for correctness testing. Do not infer throughput or CPU-efficiency conclusions from this oversubscribed AIO environment.

---

## 7. Software baseline

Use one consistent OpenStack release across:

- DevStack/OpenStack;
- Octavia;
- `octavia-lib`;
- `python-octaviaclient`;
- `ovn-octavia-provider`;
- Provider Driver development environment.

Do not mix arbitrary master branches with a packaged Provider Driver environment unless compatibility is being tested intentionally.

Minimum OpenStack services for this lab:

```text
Keystone
Glance
Nova
Placement
Neutron ML2/OVN
Octavia
MariaDB
RabbitMQ
```

Not required for the initial L4 lab:

```text
Cinder
Swift
Heat
Horizon
Barbican (unless TLS/secret features are later tested)
```

---

## 8. Deployment order

### Stage 0 — Host prerequisite check

1. Install a supported Linux host for the chosen OpenStack release.
2. Verify KVM:
   - virtualization extensions visible;
   - `/dev/kvm` present;
   - nested virtualization available if this is itself a VM.
3. Confirm at least 32 GB RAM and ~160 GB free SSD.
4. Confirm the host can expose a provider/public bridge.
5. Snapshot the VM/host before installing OpenStack if the platform supports snapshots.

**Exit criterion:** the host can run nested Nova guests using KVM.

### Stage 1 — OpenStack all-in-one with ML2/OVN

Deploy:

- Keystone
- Glance
- Nova
- Placement
- Neutron ML2/OVN
- Octavia services

Create `public` provider networking and verify:

- test VM boots;
- DHCP works;
- security groups work;
- floating IP works;
- VM-to-VM connectivity works;
- OVN NB/SB state is healthy.

**Exit criterion:** ordinary Nova + Neutron networking is stable before Octavia troubleshooting begins.

### Stage 2 — Amphora baseline

1. Build/import an Amphora image.
2. Create a small Amphora flavor.
3. Create Octavia management network/security group/certificates.
4. Enable the Amphora provider.
5. Start with `SINGLE` topology.
6. Create:
   - LB
   - TCP listener
   - pool
   - two members
   - TCP health monitor
7. Verify traffic and statuses.
8. Only then optionally validate `ACTIVE_STANDBY`.

**Exit criterion:** Amphora provides a known-good Octavia reference path using the same backend VMs.

### Stage 3 — OVN provider baseline (optional but recommended)

Because Neutron already uses ML2/OVN:

1. Install/enable `ovn-octavia-provider` matching the OpenStack release.
2. Ensure Octavia lists both `amphora` and `ovn` providers.
3. Create a minimal OVN LB using only OVN-supported features:
   - TCP listener;
   - TCP pool;
   - SOURCE_IP_PORT algorithm;
   - two members;
   - TCP health monitor.
4. Validate create/update/delete.

**Exit criterion:** OVN gives a second L4 control-plane/dataplane baseline. If this fails for packaging/version reasons, record it and continue; it is not a blocker for LoxiLB.

### Stage 4 — Workload VMs

Create:

- `backend-1` (`10.20.0.21`)
- `backend-2` (`10.20.0.22`)
- `client-1` (`10.20.0.30`)

Backends should return different identifiers, for example:

```text
backend-1 -> "backend-1"
backend-2 -> "backend-2"
```

This makes balancing behavior visible with repeated requests.

**Exit criterion:** the client can reach each backend directly before inserting any load balancer.

### Stage 5 — LoxiLB standalone

Create `loxilb-1`:

```text
Data IP: 10.20.0.10
Management: floating IP or controlled management access
```

Validate LoxiLB without Octavia:

1. API/CLI access.
2. Create `10.20.0.100:80/TCP`.
3. Add both backends.
4. Send repeated connections from `client-1`.
5. Verify distribution.
6. Stop `backend-1` and verify health/fail behavior.
7. Update a member.
8. Delete service and confirm cleanup.
9. Repeat for UDP if supported by the selected test server/client.

**Exit criterion:** LoxiLB behavior and API semantics are known independently of Provider Driver code.

This stage is important because the upstream `octavia-loxilb-driver` audit found enough architectural/test issues that it should be treated as reusable reference material rather than assumed working infrastructure.

### Stage 6 — Provider Driver installation

Install the new/adapted Provider Driver into the Octavia API environment and register:

```text
provider = loxilb
```

Use a fixed endpoint for `loxilb-1` first. Do not introduce node placement, HA orchestration, BGP or scale-out yet.

**Exit criterion:** `openstack loadbalancer provider list` exposes `loxilb` and Octavia can invoke the driver.

### Stage 7 — End-to-end LoxiLB Provider validation

Create the same logical service used by Amphora:

```text
LoadBalancer
  -> TCP Listener :80
      -> Pool
          -> 10.20.0.21:80
          -> 10.20.0.22:80
          -> TCP HealthMonitor
```

Validate:

```text
OpenStack CLI/API
    -> Octavia
        -> LoxiLB Provider Driver
            -> LoxiLB API
                -> LoxiLB dataplane
                    -> backend VMs
```

Only after this succeeds should HA and BGP be added.

---

## 9. Validation checklist

### 9.1 Host / virtualization

- [ ] KVM is available.
- [ ] Nested KVM works if `os-aio` is itself a VM.
- [ ] CPU/RAM/disk meet the functional minimum.
- [ ] Provider/public bridge connectivity works.

### 9.2 OpenStack / Neutron / OVN

- [ ] Keystone authentication works.
- [ ] Glance image upload works.
- [ ] Nova VM create/delete works.
- [ ] Neutron network/subnet/port CRUD works.
- [ ] Security groups work.
- [ ] Floating IP works.
- [ ] VM-to-VM connectivity works.
- [ ] ML2/OVN NB/SB databases are healthy.
- [ ] Rebooting a test VM does not break basic networking.

### 9.3 Amphora baseline

- [ ] `amphora` appears in Octavia provider list.
- [ ] Amphora image is selected correctly.
- [ ] Amphora management connectivity works.
- [ ] LoadBalancer reaches `ACTIVE` provisioning status.
- [ ] Listener reaches `ACTIVE`.
- [ ] Pool reaches `ACTIVE`.
- [ ] Members are created successfully.
- [ ] TCP health monitor reports expected member state.
- [ ] Repeated client connections reach both backends.
- [ ] Failed backend is removed from service.
- [ ] Recovered backend returns to service.
- [ ] Update works.
- [ ] Delete removes Octavia and Neutron artifacts.

### 9.4 OVN provider

- [ ] `ovn` appears in provider list.
- [ ] TCP LB can be created.
- [ ] SOURCE_IP_PORT pool works.
- [ ] Members are reachable.
- [ ] TCP health monitor works.
- [ ] Update/delete works.
- [ ] No Amphora VM is created for the OVN LB.
- [ ] Unsupported Amphora-only features are not used to judge OVN correctness.

### 9.5 LoxiLB standalone

- [ ] LoxiLB starts cleanly.
- [ ] REST/API or CLI control endpoint is reachable.
- [ ] VIP can be created.
- [ ] Two backend endpoints can be attached.
- [ ] TCP traffic is balanced.
- [ ] UDP traffic is validated separately.
- [ ] Backend liveness detection works.
- [ ] Member add/update/delete works.
- [ ] Service delete removes dataplane state.
- [ ] Restart behavior is documented.
- [ ] Any persistence/reconciliation behavior is documented rather than assumed.

### 9.6 LoxiLB Provider Driver MVP

- [ ] `loxilb` is registered as an Octavia provider.
- [ ] `LoadBalancer` create works.
- [ ] `Listener` create/update/delete works.
- [ ] `Pool` create/update/delete works.
- [ ] `Member` create/update/delete works.
- [ ] `HealthMonitor` create/update/delete works.
- [ ] TCP end-to-end traffic works.
- [ ] UDP is validated after TCP.
- [ ] `provisioning_status` transitions correctly.
- [ ] `operating_status` reflects backend/service state.
- [ ] Unsupported features fail explicitly instead of being silently ignored.
- [ ] Repeating/retrying an operation does not create duplicate LoxiLB rules.
- [ ] Deleting an LB removes LoxiLB state.
- [ ] Deleting an LB removes Neutron VIP/AAP state.
- [ ] Driver restart does not corrupt existing service state.
- [ ] LoxiLB restart behavior is captured.
- [ ] Octavia and LoxiLB state can be compared for reconciliation testing.

### 9.7 Failure tests before BGP

- [ ] Kill `backend-1` during traffic.
- [ ] Restart `backend-1`.
- [ ] Restart LoxiLB process/container.
- [ ] Restart Provider Driver/Octavia worker process.
- [ ] Temporarily block Provider Driver -> LoxiLB API access.
- [ ] Verify Octavia reports `ERROR` rather than false `ACTIVE` when provisioning genuinely fails.
- [ ] Restore connectivity and test recovery/reconciliation behavior.

---

## 10. BGP/ECMP extension — later phase

Do **not** add this to the first successful lab. Extend only after single-node Provider Driver CRUD is stable.

Add:

| VM | IP example | Purpose |
|---|---|---|
| `loxilb-2` | `10.40.0.11` | second active LoxiLB node |
| `frr-router` | `10.40.0.1` | BGP peer and ECMP next-hop selection |
| `client-1` second/reworked NIC | `10.10.0.30` | traffic enters through router instead of same L2 domain |

Suggested future networks:

```text
client-net     10.10.0.0/24
backend-net    10.30.0.0/24
bgp-transit    10.40.0.0/24
VIP prefix     10.99.0.0/24  (advertise individual VIPs as /32)
```

Future topology:

```text
client-1
10.10.0.30
    |
    v
+-----------+
| FRR Router|
| BGP + ECMP|
+-----+-----+
      |
      | bgp-transit 10.40.0.0/24
      |
   +--+------------------+
   |                     |
   v                     v
LoxiLB-1              LoxiLB-2
10.40.0.10            10.40.0.11
   |                     |
   +----------+----------+
              |
          backend-net
              |
       +------+------+
       |             |
   backend-1     backend-2
```

Both LoxiLB nodes advertise the same VIP route, for example:

```text
10.99.0.100/32
```

The FRR router should then show multiple equal-cost next hops.

### BGP/ECMP validation checklist

- [ ] Both BGP sessions become Established.
- [ ] Both LoxiLB nodes advertise the same VIP /32.
- [ ] FRR installs multiple equal-cost next hops.
- [ ] New flows reach both LoxiLB nodes.
- [ ] Killing one LoxiLB withdraws/removes its route.
- [ ] Traffic continues through the remaining node.
- [ ] Convergence time is measured.
- [ ] Packet loss is measured.
- [ ] Existing-connection behavior is measured separately from new-connection behavior.
- [ ] State/connection synchronization is validated with evidence rather than inferred from routing convergence.
- [ ] Add a third LoxiLB node only after two-node behavior is understood.

---

## 11. What this lab deliberately does not validate

The smallest lab is **not sufficient** to make claims about:

- production throughput;
- CPS/RPS ceilings;
- p99 latency under high load;
- NUMA effects;
- NIC queue scaling;
- SR-IOV/DPDK behavior;
- multi-compute failure domains;
- real ToR BGP behavior;
- production ECMP hashing;
- cloud-scale control-plane limits;
- 100/1,000+ load balancers;
- multi-tenant isolation at production scale.

Those belong in the later benchmark/scale-out lab.

---

## 12. Minimum-success definition

The initial lab is considered successful when all of the following are true:

```text
1. The same backend-1/backend-2 workload works behind Amphora.
2. OVN works as a second L4 provider if the selected OpenStack release/package set supports it cleanly.
3. LoxiLB standalone provides the same simple TCP service.
4. provider=loxilb creates the service through Octavia without manual LoxiLB configuration.
5. Member health is reflected back into Octavia operating status.
6. Delete cleans both LoxiLB and Neutron state.
7. No BGP/ECMP is required to achieve items 1-6.
```

At that point the project has a clean functional baseline and can move to:

```text
single-node correctness
        -> failure/reconciliation
        -> two-node HA
        -> BGP/ECMP
        -> horizontal scale
        -> benchmark
```

---

## 13. Recommended lab bill of materials

### Initial functional lab

```text
1 x OpenStack AIO host
1 x LoxiLB VM
1 x traffic-generator VM
2 x backend VMs
1 x Amphora VM created on demand
0 x dedicated OVN LB VM
```

Recommended parent capacity:

```text
24 vCPU
48 GB RAM
200-250 GB SSD
```

Absolute functional floor:

```text
16 vCPU
32 GB RAM
160 GB SSD
```

### Later HA/BGP extension

Add only:

```text
1 x LoxiLB VM
1 x FRR router VM
```

No new OpenStack controller/compute node is required for the first BGP/ECMP proof-of-concept.

---

## 14. References used for this design

Verified against current project documentation on 2026-08-11:

- OpenStack Octavia — Available Provider Drivers.
- OpenStack Octavia — Provider Driver Development Guide.
- OpenStack Octavia — Provider Feature Matrix.
- OVN Octavia Provider 2026.1 — OVN as a Provider Driver for Octavia.
- Kolla-Ansible latest — Octavia / Amphora / OVN provider configuration.
- OpenStack Neutron / neutron-lib — allowed address pairs behavior.
- OpenStack Octavia — allowed-address-pairs network driver source documentation.
- LoxiLB official GitHub project documentation — L4/eBPF, one-arm/FullNAT/DSR, health checking and HA capabilities.
- Existing `octavia-loxilb-driver==1.0.3` upstream audit/context supplied for this internship project; treated as reference/reuse material, not as a proven production architecture.

