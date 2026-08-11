# Baseline Lab Validation

## Result

**Static implementation validation: PASS.** The baseline deployment/configuration artifacts are present, render deterministically from local inputs, contain no committed credential, and do not enable or implement a LoxiLB Octavia Provider Driver.

**Live AIO/E2E validation: NOT RUN.** The implementation session ran on `Darwin 24.3.0 arm64`, not on the target Ubuntu/KVM AIO host. The machine had no OpenStack CLI or authenticated cloud and its Docker daemon was unavailable. OpenStack, OVN, Amphora VM, workload VM, and LoxiLB dataplane results must therefore not be inferred from the static result.

Validation time: `2026-08-11T07:51:31Z`.

## Implemented scope

| Area | Artifact | Purpose |
|---|---|---|
| DevStack | `deployment/devstack/local.conf.tpl` | AIO, ML2/OVN from first deployment, Amphora `SINGLE`, optional OVN provider |
| Guest initialization | `deployment/cloud-init/` | Distinct HTTP backends, traffic client, pinned LoxiLB container |
| LoxiLB runtime | `deployment/loxilb/compose.yaml` | Recorded equivalent standalone container configuration |
| Local input | `lab/lab.env.example` | Version pins, address plan, artifact hashes, blank credential fields |
| Runbook | `lab/README.md` | Ordered commands, configuration boundaries, evidence procedure |
| Automation | `scripts/generate-lab-env.sh` | Generates random local DevStack secrets with mode `0600` |
| Automation | `scripts/render-devstack-config.sh` | Renders a private `local.conf`, rejects missing/newline values |
| Automation | `scripts/check-host.sh` | CPU/RAM/disk/KVM/nesting/provider-interface prerequisites |
| Automation | `scripts/deploy-devstack.sh` | Checks out the pinned DevStack commit and optionally runs `stack.sh` |
| Automation | `scripts/bootstrap-openstack.sh` | Image checksum guard, tenant network, fixed ports, VMs, FIPs, VIP AAP |
| Automation | `scripts/create-octavia-baseline.sh` | Idempotent Amphora or OVN TCP baseline resources |
| Automation | `scripts/configure-loxilb.sh` | Exact standalone one-arm TCP rule via SSH/`loxicmd` |
| Validation | `scripts/validate-baseline.sh` | Static and separately gated live checks with `PASS/FAIL/SKIP` |

The pinned source baseline recorded in `lab/lab.env.example` is:

```text
OpenStack release:        stable/2025.2
DevStack:                 92e864aa017f61e911a8ce3976e828fa5b750ded
Octavia:                  ddaa9172fb68e66f13ea0f8f0a26bcbd9b0479cb
OVN Octavia provider:     1c17bfe45fff4277165f9e580eb3f2f64c048a83
LoxiLB image default:     ghcr.io/loxilb-io/loxilb:v0.9.8
```

## Checks executed

### Static validator

Command:

```bash
scripts/validate-baseline.sh --static
```

Result: exit `0`.

```text
PASS  All shell scripts pass bash -n
PASS  Required baseline artifacts are present
PASS  Address plan, template variables and credential policy are valid
PASS  No LoxiLB Octavia Provider Driver is enabled
SKIP  shellcheck is not installed
SKIP  Docker daemon unavailable; Compose validation not run
SUMMARY: 4 passed, 0 failed, 2 skipped
```

The credential-policy check verifies that tracked credential fields are empty, rendered credential assignments remain template references, the LoxiLB image does not use `:latest`, all fixed addresses are unique/in-subnet, and the standalone VIP remains inside `10.20.0.100-119`.

### Secret/config render smoke test

A temporary environment was generated using `scripts/generate-lab-env.sh`, populated with documentation-only host values, and rendered using `scripts/render-devstack-config.sh`.

Verified:

- generated environment mode: `0600`;
- rendered `local.conf` mode: `0600`;
- no unresolved `{{...}}` marker;
- rendered release: `stable/2025.2`;
- rendered Octavia and OVN-provider commit references match the pins above;
- generated credential values were not printed;
- the temporary fixture containing generated credentials was deleted after the test.

Result: exit `0`.

### YAML syntax

Command used Ruby/Psych to parse the YAML after replacing the two documented template markers:

```bash
ruby -ryaml -e 'ARGV.each { |f| text=File.read(f).gsub("{{INSTANCE_NAME}}", "backend-1").gsub("{{LOXILB_IMAGE}}", "ghcr.io/loxilb-io/loxilb:v0.9.8"); YAML.parse(text) or abort("empty YAML: #{f}"); puts "YAML OK: #{f}" }' \
  deployment/cloud-init/backend.yaml.tpl \
  deployment/cloud-init/client.yaml \
  deployment/cloud-init/loxilb.yaml.tpl \
  deployment/loxilb/compose.yaml
```

Result: all four files parsed, exit `0`.

### Repository hygiene

The baseline artifacts were checked for trailing whitespace, and `git diff --check` completed successfully. Generated `lab/lab.env`, `lab/generated/`, state, logs, and local `clouds.yaml` are ignored.

## Security/configuration assertions

- No credential is hard-coded in a tracked file; DevStack secrets are independently generated with `openssl rand`.
- Guest image creation requires a caller-supplied SHA-256 and records it as a Glance property. A same-name image without the expected property is rejected.
- Existing flavors, subnet, fixed ports, and image are checked for material drift instead of silently reused.
- Port security is explicitly required on `lb-net`.
- Only `10.20.0.100/32` is added as an allowed-address-pair on `loxilb-1-port`; port security is not disabled globally.
- The LoxiLB API is not opened through the workload security group. Standalone configuration is performed through SSH and `docker exec`.
- The standalone configurator replaces only the exact baseline VIP/port and persists that rule.
- No Provider Driver package, Octavia entry point, provider registration, or worker configuration was added.

## Live validation gate

On the Ubuntu AIO host, after deployment and credential loading, run:

```bash
scripts/check-host.sh --strict
scripts/validate-baseline.sh --live | tee "lab/logs/validation-$(date -u +%Y%m%dT%H%M%SZ).log"
```

The live validator must produce evidence for:

1. Keystone and service endpoints;
2. Amphora registration and optional OVN registration;
3. public/tenant networks and all four workload VMs;
4. the precise VIP allowed-address-pair;
5. direct reachability to both distinct backends;
6. repeated traffic reaching both backends through standalone LoxiLB;
7. `ACTIVE` state and traffic through each native Octavia baseline that was created;
8. OVN NB/SB command responsiveness when the CLIs run locally.

Until that command succeeds on the target lab, the checklist items that depend on KVM, OpenStack services, OVN databases, Amphorae, Neutron traffic, or LoxiLB dataplane remain **unvalidated**.
