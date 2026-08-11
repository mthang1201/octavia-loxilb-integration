# Upstream code walkthrough

All paths below are relative to the extracted upstream package root under
`original/`.

## Packaging and entry points

- `pyproject.toml:62-71` exports the provider as
  `driver.provider_driver:LoxiLBProviderDriver` and the provider agent as
  `controller.worker:LoxiLBControllerWorker`, plus four console scripts.
- `driver/provider_driver.py:100` contains the Provider Driver class. The
  provider entry point loads in the Phase A environment.
- `controller/worker/__init__.py` is empty. The provider-agent entry point
  therefore fails to load the exported class. The class actually exists at
  `controller/controller_worker.py:40`.
- `common/config.py` registers the `[loxilb]` and service-auth groups.
  `pyproject.toml`, root `requirements.txt`, and the nested setup/requirements
  files declare inconsistent dependency sets.

## Provider entry and dispatch

`LoxiLBProviderDriver.__init__()` registers configuration, creates the API
client, mapper, RPC client, and five resource subdrivers
(`driver/provider_driver.py:103-163`). Its intended startup connectivity test
is accidentally indented inside the no-op `update_loadbalancer_status()`
method (`driver/provider_driver.py:176-207`) and is not part of initialization.

Important call chains:

```text
loadbalancer_create
  -> flow_utils.get_create_loxilb_load_balancer_flow
  -> LoxiLBLoadBalancerFlows.get_create_load_balancer_flow
  -> LoxiLBComputeCreate
  -> LoxiLBAllocateVIP
  -> LoxiLBPlugVIPPort
  -> RPC create_load_balancer
```

```text
listener/pool/member/health-monitor CRUD
  -> provider RPC cast
  -> LoxiLBControllerWorker.<operation>
  -> Octavia DB repository lookup
  -> resource TaskFlow
  -> LoxiLB task/subdriver
  -> LoxiLBAPIClient
  -> database status task
```

The first chain mixes a synchronous OpenStack provisioning flow with a later
asynchronous RPC operation. The second chain relies on the controller worker
being deployed and registered correctly, which conflicts with the broken
provider-agent entry point.

## Worker, flows, and tasks

- `controller/controller_worker.py` implements lifecycle endpoints and uses
  Octavia repositories to obtain complete objects. It contains two definitions
  of `update_health_monitor` at lines 947 and 1240.
- `controller/worker/flows/` composes TaskFlow graphs for load balancers,
  listeners, pools, members, health monitors, L7 objects, and cascade delete.
- `controller/worker/tasks/loxilb_compute_tasks.py` creates/deletes per-LB
  Nova servers.
- `controller/worker/tasks/loxilb_network_tasks.py` locates the VIP port and
  applies/removes Neutron AAP wiring.
- `controller/worker/tasks/loxilb_tasks.py` invokes resource subdrivers. It
  defines `DeleteAllListenersInLoxiLB` twice (lines 654 and 998).
- `controller/worker/tasks/database_tasks.py` writes provisioning/deletion
  results to Octavia DB repositories.
- `controller/queue/` is an additional consumer/endpoints implementation.
  Its L7 endpoints explicitly raise `NotImplementedError`
  (`controller/queue/endpoints.py:340-450`).

## API client

`api/loxilb_client.py` provides configured endpoint parsing, optional dynamic
per-LB discovery, authentication, TLS settings, retry/failover, LB service
CRUD, endpoint/probe operations, and metrics-shaped reads.

The code has duplicate `get_status()` and `health_check()` definitions. Its
`list_loadbalancers()` consumes the response key `lbServices`
(`api/loxilb_client.py:458-477`), while its unit fixtures provide `lbAttr`;
three API-client tests fail on this schema drift. Debug mode logs full request
data and response text (`api/loxilb_client.py:294-305`).

## Translators and local state

`resource_mapping/mapper.py` is both translator and persistence coordinator:

- LB/listener/pool/member/health-monitor conversion;
- protocol, algorithm, persistence, monitor, TLS-reference, and statistics
  fields;
- identifier/metadata storage in a local JSON file;
- reverse conversion from LoxiLB response dictionaries.

The mapper's breadth is reusable as a source of test cases, but its local
state and silent fallbacks are not suitable as target behavior.

## Resource subdrivers

- `driver/loadbalancer_driver.py`: direct LB service CRUD and reads. It has L7
  pass-through/no-op methods, but no `failover()` or `get_stats()` even though
  the provider invokes both.
- `driver/listener_driver.py`: listener service create/update/delete and
  mapping recovery. Some updates require delete/recreate. TLS container
  references are passed as identifiers; no secret retrieval or certificate
  installation path is present.
- `driver/pool_driver.py`: pool metadata and recreation of the containing
  listener service.
- `driver/member_driver.py`: member metadata, endpoint operations, and service
  recreation paths; health-monitor cleanup calls methods absent from the HM
  driver.
- `driver/healthmonitor_driver.py`: validation, endpoint-probe shaping, and
  metadata. Several tested helpers have schema/signature drift, and operating
  status is hard-coded to `ONLINE`.

## Reconciliation and status

`common/state_reconciler.py` attempts consistency checks and cascade cleanup.
It cannot prove member existence and does not implement orphan discovery.
`common/utils.py` contains the JSON mapping helpers and shared validation/status
utilities. There is no durable cross-worker reconciliation loop demonstrated
by tests.

## Tests

- `octavia_loxilb_driver/tests/unit/`: seven modules, 117 collected tests after
  Octavia is added manually. The failures concentrate in client response
  parsing, health-monitor behavior, ID mapping, member/pool service recreation,
  and missing member/HM coordination methods.
- `octavia_loxilb_driver/tests/functional/`: four LoxiLB integration tests.
  They collect but were not executed because no LoxiLB target was available.
- `tests/integration/test_load_balancer_combinations.py`: one method on
  `LoadBalancerIntegrationTest`; the configured `Test*` class rule does not
  collect that class. Plain `pytest` therefore finds zero tests.

See `evidence/test-summary.md` for the exact executed baseline.
