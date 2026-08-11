# Baseline lab runbook

This directory turns [`docs/lab/LAB_DESIGN.md`](../docs/lab/LAB_DESIGN.md) into a reproducible functional baseline. It deploys OpenStack AIO with ML2/OVN and Octavia, creates the tenant workloads, and configures one standalone LoxiLB service. It does **not** install, register, or implement a LoxiLB Octavia Provider Driver.

## Pinned baseline and local inputs

- OpenStack/DevStack: `stable/2025.2`; the DevStack, Octavia, and OVN provider entry commits are pinned in `lab.env.example`.
- Amphora topology: `SINGLE`.
- LoxiLB: `ghcr.io/loxilb-io/loxilb:v0.9.8` by default. An immutable digest may replace this tag.
- Guest OS: operator-supplied qcow2 plus a mandatory SHA-256; no mutable download URL is hidden in a script.
- Credentials: generated only in ignored `lab/lab.env`, mode `0600`. No credential is committed.

The exact source commits actually installed can be recorded after deployment with:

```bash
for repository in devstack octavia ovn-octavia-provider neutron nova; do
  test -d "/opt/stack/${repository}/.git" && \
    git -C "/opt/stack/${repository}" rev-parse HEAD
done
sudo docker exec loxilb loxicmd version || true
```

## 0. Prepare the AIO host

Use a disposable Ubuntu 24.04 AIO host. The target minimum is 16 vCPU, 32 GiB RAM, 160 GiB free SSD, usable `/dev/kvm`, and a dedicated provider NIC. If the AIO is a VM, expose nested virtualization.

```bash
scripts/check-host.sh --strict
```

Create the conventional unprivileged DevStack account if it does not exist, then make the repository accessible to it. Do not run `stack.sh` as root.

```bash
sudo useradd --create-home --home-dir /opt/stack --shell /bin/bash stack
sudo chmod 0755 /opt/stack
sudo install -d -o stack -g stack /opt/stack/logs
```

`PUBLIC_INTERFACE` must be the dedicated provider interface, not the only management interface. Losing the management connection is a realistic consequence of selecting the wrong NIC.

## 1. Create local configuration

```bash
scripts/generate-lab-env.sh
chmod 0600 lab/lab.env
${EDITOR:-vi} lab/lab.env
```

Fill these environment-specific values:

- `HOST_IP`, `PUBLIC_INTERFACE`, and `MGMT_ALLOWED_CIDR`;
- `LAB_IMAGE_FILE` and the output of `sha256sum <image.qcow2>`;
- public/private SSH key paths.

To inspect the generated DevStack configuration without changing the host:

```bash
scripts/render-devstack-config.sh
sed -n '1,240p' lab/generated/local.conf
```

The rendered file contains secrets and is ignored. Never paste it into an issue or commit it.

## 2. Deploy OpenStack AIO

Run as the `stack` user from a checkout of this repository:

```bash
scripts/deploy-devstack.sh
# Review /opt/stack/devstack/local.conf.
scripts/deploy-devstack.sh --run
```

The committed template enables Keystone, Glance, Placement, Nova, Neutron ML2/OVN, Octavia Amphora services, and the optional OVN provider. It disables Cinder, Swift, Horizon, Heat, and Tempest for this functional lab. The Octavia plugin creates its conventional `lb-mgmt-net`/`lb-mgmt-subnet` resources using `172.31.0.0/24`; this is the `octavia-mgmt` network described in the design, with upstream DevStack naming.

Load an admin or demo credential context without checking it into Git. Examples are DevStack's local `openrc` or an ignored `clouds.yaml`:

```bash
source /opt/stack/devstack/openrc admin admin
# Or set LAB_OS_CLOUD in lab/lab.env and keep lab/clouds.yaml mode 0600.
openstack token issue
```

## 3. Create networks and workload VMs

```bash
scripts/bootstrap-openstack.sh
```

The script is safe to rerun and creates:

- `lb-net`/`lb-subnet` and `lab-router`;
- fixed ports for `loxilb-1`, `client-1`, and both backends;
- a `/32` allowed-address-pair for `10.20.0.100` only on `loxilb-1-port`;
- backend HTTP services returning distinct names;
- floating IPs for the client and LoxiLB management paths.

The automatic subnet allocation pools skip `10.20.0.100-119`. Port security remains enabled globally and per network.

## 4. Create the native Octavia baselines

Create Amphora first and do not continue until it is functional:

```bash
scripts/create-octavia-baseline.sh amphora
```

The optional OVN provider uses `SOURCE_IP_PORT`, matching its L4 feature set:

```bash
scripts/create-octavia-baseline.sh ovn
```

Both commands create a TCP listener on port 80, a pool, two members, and a TCP health monitor. They reuse existing named resources on rerun.

## 5. Configure standalone LoxiLB

Cloud-init installs the pinned container on `loxilb-1`. After it completes:

```bash
scripts/configure-loxilb.sh
```

That command configures and persists only this rule:

```text
10.20.0.100:80/TCP, one-arm, monitored
  -> 10.20.0.21:80
  -> 10.20.0.22:80
```

It uses SSH and `docker exec`; the LoxiLB API is not exposed to the public network. The equivalent container declaration is recorded in `deployment/loxilb/compose.yaml`.

## 6. Validate and retain evidence

Repository-only validation can run on any machine:

```bash
scripts/validate-baseline.sh --static
```

Run the live checks on the AIO host with OpenStack credentials loaded and `lab/lab.env` populated:

```bash
scripts/validate-baseline.sh --live | tee "lab/logs/validation-$(date -u +%Y%m%dT%H%M%SZ).log"
```

Live validation checks authentication/endpoints, providers, networks, server state, the VIP allowed-address-pair, direct backend traffic, traffic through any created Amphora/OVN baseline, standalone LoxiLB traffic, and OVN NB/SB responsiveness where the local CLIs exist. A missing optional baseline is reported as `SKIP`, not a false pass.

## Deliberate exclusions

- no LoxiLB Provider Driver package, entry point, Octavia registration, or worker configuration;
- no global port-security disablement;
- no BGP, ECMP, HA pair, performance claim, or benchmark;
- no embedded OpenStack, SSH, registry, or LoxiLB credential.

## Upstream references

- [DevStack with Octavia](https://docs.openstack.org/devstack/2025.2/guides/devstack-with-octavia.html)
- [OVN Octavia provider sample configuration](https://opendev.org/openstack/ovn-octavia-provider/src/branch/stable/2025.2/devstack/local.conf.sample)
- [LoxiLB standalone mode](https://docs.loxilb.io/main/standalone/)
- [`loxicmd` load-balancer and endpoint commands](https://docs.loxilb.io/main/cmd/)
