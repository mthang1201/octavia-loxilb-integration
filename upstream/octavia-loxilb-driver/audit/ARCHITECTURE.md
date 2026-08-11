# Upstream architecture audit

## Scope and evidence rule

This document describes `octavia-loxilb-driver==1.0.3` as shipped in the
verified source distribution. A source-visible path is **verified** only as an
implementation fact; no OpenStack-to-LoxiLB functional behavior was verified
against a live environment in Phase A.

## Control flow

```text
Octavia API
  -> octavia.api.drivers entry point
  -> LoxiLBProviderDriver
       -> load-balancer create/delete: synchronous local TaskFlow
       |    -> OpenStack SDK -> per-load-balancer LoxiLB VM
       |    -> locate Octavia VIP port -> attach base port/AAP
       |    -> RPC cast for a second controller-worker operation
       |
       -> most other lifecycle methods: asynchronous oslo.messaging cast
            -> LoxiLBControllerWorker
            -> Octavia DB lookup
            -> TaskFlow flow/tasks
            -> resource subdriver / LoxiLBAPIClient
            -> Octavia repository status updates
```

This is a mixed orchestration model. `loadbalancer_create()` executes a local
TaskFlow synchronously and then sends `create_load_balancer` over RPC
(`driver/provider_driver.py:252-291`). Load-balancer delete repeats the same
pattern (`driver/provider_driver.py:328-347`). Listener, pool, member, and
health-monitor operations are primarily RPC casts; listener creation has a
direct subdriver fallback (`driver/provider_driver.py:411-468`). The upstream
design therefore has more than one owner for orchestration and state.

## Per-load-balancer appliance provisioning

The create flow is a linear TaskFlow containing compute create, VIP lookup,
and VIP plug tasks
(`controller/worker/flows/loxilb_load_balancer_flows.py:26-54`). Compute create
names one server `loxilb-<load-balancer-id>` and selects a management or VIP
network (`controller/worker/tasks/loxilb_compute_tasks.py:37-94`). No topology
branch creates a second instance.

The networking task looks up Octavia's existing VIP port and uses an
Amphora-inspired allowed-address-pair (AAP) operation on a base port
(`controller/worker/tasks/loxilb_network_tasks.py:37-129`). Delete deallocates
the VIP port and deletes servers matching the per-LB name. This is an
appliance-per-Octavia-LB architecture, not a shared LoxiLB infrastructure
cluster.

## LoxiLB API endpoint discovery

`LoxiLBAPIClient` accepts configured endpoints and, when management networking
is enabled, creates an OpenStack SDK connection. For an operation carrying an
LB ID it looks up the matching `loxilb-<id>` VM management address and builds a
dynamic HTTP(S) endpoint (`api/loxilb_client.py:20-85,251-284`). If discovery
does not produce an endpoint, it falls back to the configured endpoint pool.

The requests session implements connection pooling and urllib3 retries for
selected methods, while `_make_request()` is separately wrapped in a Tenacity
retry (`api/loxilb_client.py:118-151,248-354`). This provides endpoint failover
mechanics but creates overlapping retry semantics.

## Resource mapping

`ResourceMapper` translates Octavia objects into a LoxiLB service model and
back. The primary service identity is effectively VIP, listener port, and
protocol. It also keeps Octavia-to-LoxiLB identifiers and metadata in an
in-memory dictionary persisted as local JSON. The default is
`/var/lib/octavia/loxilb_id_mappings.json`
(`resource_mapping/mapper.py:28-50`).

The mapper covers listener, pool, member, health-monitor, and statistics-shaped
dictionaries, but several mappings use defaults instead of rejecting unknown
inputs. HTTP-family protocols map to TCP, unknown protocols map to TCP, and an
unknown algorithm maps to round-robin
(`resource_mapping/mapper.py:94-115,368-386`). The local JSON model has no
distributed locking, durable database transaction, or controller ownership
model suitable for multiple workers or shared-cluster placement.

## Status and reconciliation

The controller worker reads Octavia DB objects, runs TaskFlow, and uses the
database tasks in `controller/worker/tasks/database_tasks.py` to update or mark
objects deleted. The direct `update_loadbalancer_status()` callback is a no-op
(`driver/provider_driver.py:165-196`). Consequently, the RPC/worker path must
be available for authoritative status updates.

Reconciliation is incomplete. Member existence is assumed true and orphan
detection is an empty loop with TODO markers
(`common/state_reconciler.py:245-312`). Health-monitor operating status is
always returned as `ONLINE` regardless of endpoint state
(`driver/healthmonitor_driver.py:600-610`). These gaps prevent the source from
supporting a reliable desired-versus-actual state claim.

## Architectural conclusion

Useful interface, client, translation, AAP, and TaskFlow patterns exist, but
the orchestration boundary is inconsistent and the state model is tied to a
single local process and per-LB VM. The preferred Viettel IDC hypothesis is a
shared LoxiLB infrastructure cluster with explicit placement, durable state,
BGP/ECMP advertisement, and reconciliation. It remains an unapproved
hypothesis until standalone capability and failure testing establishes the
target LoxiLB version's API and dataplane semantics.
