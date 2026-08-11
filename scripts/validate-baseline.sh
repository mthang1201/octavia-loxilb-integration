#!/usr/bin/env bash
set -u
set -o pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
mode="${1:---static}"
case "${mode}" in
    --static|--live|--all) ;;
    *) echo "Usage: $0 [--static|--live|--all]" >&2; exit 2 ;;
esac

passes=0
failures=0
skips=0
pass() { printf 'PASS  %s\n' "$*"; passes=$((passes + 1)); }
fail() { printf 'FAIL  %s\n' "$*"; failures=$((failures + 1)); }
skip() { printf 'SKIP  %s\n' "$*"; skips=$((skips + 1)); }

run_static() {
    local script syntax_failed=0
    while IFS= read -r script; do
        if bash -n "${script}"; then
            :
        else
            syntax_failed=1
        fi
        [[ -x "${script}" ]] || fail "Script is not executable: ${script#"${REPOSITORY_ROOT}/"}"
    done < <(find "${REPOSITORY_ROOT}/scripts" -type f -name '*.sh' -print | sort)
    if (( syntax_failed == 0 )); then pass "All shell scripts pass bash -n"; else fail "Shell syntax validation"; fi

    local required=(
        deployment/devstack/local.conf.tpl
        deployment/cloud-init/backend.yaml.tpl
        deployment/cloud-init/client.yaml
        deployment/cloud-init/loxilb.yaml.tpl
        deployment/loxilb/compose.yaml
        docs/lab/BASELINE_VALIDATION.md
        lab/lab.env.example
        lab/README.md
        scripts/check-host.sh
        scripts/bootstrap-openstack.sh
        scripts/create-octavia-baseline.sh
        scripts/configure-loxilb.sh
    )
    local missing=0 path
    for path in "${required[@]}"; do
        if [[ ! -f "${REPOSITORY_ROOT}/${path}" ]]; then
            fail "Missing required artifact: ${path}"
            missing=1
        fi
    done
    (( missing == 0 )) && pass "Required baseline artifacts are present"

    if python3 - "${REPOSITORY_ROOT}" <<'PY'
import ipaddress
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
env = {}
for raw in (root / "lab/lab.env.example").read_text().splitlines():
    if raw and not raw.startswith("#") and "=" in raw:
        key, value = raw.split("=", 1)
        env[key] = value.strip("'\"")

network = ipaddress.ip_network(env["LB_CIDR"])
addresses = [
    env["LB_GATEWAY"], env["LOXILB_FIXED_IP"], env["BACKEND1_FIXED_IP"],
    env["BACKEND2_FIXED_IP"], env["CLIENT_FIXED_IP"], env["LOXILB_VIP"],
]
if any(ipaddress.ip_address(address) not in network for address in addresses):
    raise SystemExit("LB address outside LB_CIDR")
if len(addresses) != len(set(addresses)):
    raise SystemExit("Duplicate LB address")
if not ipaddress.ip_address("10.20.0.100") <= ipaddress.ip_address(env["LOXILB_VIP"]) <= ipaddress.ip_address("10.20.0.119"):
    raise SystemExit("Standalone VIP outside reserved range")

template = (root / "deployment/devstack/local.conf.tpl").read_text()
template_keys = set(re.findall(r"{{([A-Z0-9_]+)}}", template))
missing = template_keys - set(env)
if missing:
    raise SystemExit(f"Template keys missing from env example: {sorted(missing)}")

secret_keys = {
    "LAB_ADMIN_PASSWORD", "LAB_DATABASE_PASSWORD", "LAB_RABBIT_PASSWORD",
    "LAB_SERVICE_PASSWORD", "LAB_SERVICE_TOKEN", "LAB_OCTAVIA_HEALTH_KEY",
}
for key in secret_keys:
    if env.get(key):
        raise SystemExit(f"Credential populated in tracked env example: {key}")
if env["LOXILB_IMAGE"].endswith(":latest"):
    raise SystemExit("LoxiLB image uses mutable latest tag")
for line in template.splitlines():
    if re.match(r"^(ADMIN_PASSWORD|DATABASE_PASSWORD|RABBIT_PASSWORD|SERVICE_PASSWORD|SERVICE_TOKEN|OCTAVIA_HEALTH_KEY)=", line):
        if "{{" not in line:
            raise SystemExit(f"Credential literal in local.conf template: {line}")
PY
    then
        pass "Address plan, template variables and credential policy are valid"
    else
        fail "Address/template/credential static validation"
    fi

    if grep -R -E '(enable_plugin|provider[[:space:]]*=)[^#]*(loxilb|octavia-loxilb)' \
        "${REPOSITORY_ROOT}/deployment" "${REPOSITORY_ROOT}/lab" >/dev/null 2>&1; then
        fail "A LoxiLB Octavia Provider Driver appears to be enabled"
    else
        pass "No LoxiLB Octavia Provider Driver is enabled"
    fi

    if command -v shellcheck >/dev/null 2>&1; then
        if shellcheck -x "${REPOSITORY_ROOT}"/scripts/*.sh "${REPOSITORY_ROOT}"/scripts/lib/*.sh; then
            pass "shellcheck"
        else
            fail "shellcheck"
        fi
    else
        skip "shellcheck is not installed"
    fi

    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
        if LOXILB_IMAGE=ghcr.io/loxilb-io/loxilb:v0.9.8 docker compose -f "${REPOSITORY_ROOT}/deployment/loxilb/compose.yaml" config --quiet; then
            pass "LoxiLB Compose configuration"
        else
            fail "LoxiLB Compose configuration"
        fi
    else
        skip "Docker daemon unavailable; Compose validation not run"
    fi
}

run_live() {
    local env_file="${LAB_ENV_FILE:-${REPOSITORY_ROOT}/lab/lab.env}"
    if [[ ! -f "${env_file}" ]]; then
        fail "Live validation requires ${env_file}"
        return
    fi
    set -a
    # shellcheck disable=SC1090
    source "${env_file}"
    set +a

    if ! command -v openstack >/dev/null 2>&1; then
        fail "openstack CLI not installed"
        return
    fi
    os_cmd=(openstack)
    [[ -n "${LAB_OS_CLOUD:-}" ]] && os_cmd+=(--os-cloud "${LAB_OS_CLOUD}")
    os() { "${os_cmd[@]}" "$@"; }

    if os token issue >/dev/null 2>&1; then pass "Keystone authentication"; else fail "Keystone authentication"; return; fi
    for service in compute image network load-balancer; do
        if os endpoint list --service "${service}" -f value -c ID | grep -q .; then
            pass "Service endpoint: ${service}"
        else
            fail "Missing service endpoint: ${service}"
        fi
    done

    for provider in amphora ovn; do
        if os loadbalancer provider list -f value -c name | grep -Fxq "${provider}"; then
            pass "Octavia provider registered: ${provider}"
        elif [[ "${provider}" == "ovn" ]]; then
            skip "Optional OVN provider not registered"
        else
            fail "Amphora provider not registered"
        fi
    done

    for network in "${PUBLIC_NETWORK_NAME:-public}" "${LB_NETWORK_NAME:-lb-net}"; do
        if os network show "${network}" >/dev/null 2>&1; then pass "Network exists: ${network}"; else fail "Network missing: ${network}"; fi
    done

    for server in backend-1 backend-2 client-1 loxilb-1; do
        status="$(os server show "${server}" -f value -c status 2>/dev/null || true)"
        if [[ "${status}" == "ACTIVE" ]]; then pass "Server ACTIVE: ${server}"; else fail "Server not ACTIVE: ${server} (${status:-missing})"; fi
    done

    aap="$(os port show loxilb-1-port -f value -c allowed_address_pairs 2>/dev/null || true)"
    if [[ "${aap}" == *"${LOXILB_VIP}"* ]]; then
        pass "LoxiLB port has VIP /32 allowed-address-pair"
    else
        fail "LoxiLB VIP allowed-address-pair"
    fi

    if [[ -z "${LAB_SSH_PRIVATE_KEY_FILE:-}" || ! -f "${LAB_SSH_PRIVATE_KEY_FILE}" ]]; then
        skip "SSH key unavailable; guest traffic validation skipped"
        return
    fi
    client_port_id="$(os port show client-1-port -f value -c id 2>/dev/null || true)"
    client_fip="$(os floating ip list --port "${client_port_id}" -f value -c 'Floating IP Address' | head -n 1)"
    if [[ -z "${client_fip}" ]]; then
        fail "client-1 floating IP"
        return
    fi
    ssh_opts=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -i "${LAB_SSH_PRIVATE_KEY_FILE}")
    remote="${LAB_SSH_USER:-ubuntu}@${client_fip}"
    if ssh "${ssh_opts[@]}" "${remote}" 'cloud-init status --wait >/dev/null' 2>/dev/null; then pass "client-1 cloud-init complete"; else fail "client-1 SSH/cloud-init"; return; fi

    for pair in "backend-1:${BACKEND1_FIXED_IP}" "backend-2:${BACKEND2_FIXED_IP}"; do
        name="${pair%%:*}"; address="${pair#*:}"
        response="$(ssh "${ssh_opts[@]}" "${remote}" "curl -fsS --connect-timeout 5 http://${address}/" 2>/dev/null || true)"
        if [[ "${response}" == *"${name}"* ]]; then pass "Direct backend reachability: ${name}"; else fail "Direct backend reachability: ${name}"; fi
    done

    validate_vip() {
        local label="$1" vip="$2" responses
        responses="$(ssh "${ssh_opts[@]}" "${remote}" "for i in \$(seq 1 16); do curl -fsS --connect-timeout 5 http://${vip}/ || exit; done" 2>/dev/null || true)"
        if grep -q 'backend-1' <<<"${responses}" && grep -q 'backend-2' <<<"${responses}"; then
            pass "Traffic through ${label} reaches both backends"
        else
            fail "Traffic through ${label} did not prove both backends"
        fi
    }
    validate_vip "standalone LoxiLB ${LOXILB_VIP}" "${LOXILB_VIP}"

    for provider in amphora ovn; do
        lb_name="baseline-${provider}-lb"
        vip="$(os loadbalancer show "${lb_name}" -f value -c vip_address 2>/dev/null || true)"
        provisioning="$(os loadbalancer show "${lb_name}" -f value -c provisioning_status 2>/dev/null || true)"
        if [[ -z "${vip}" ]]; then
            skip "${provider} baseline resource has not been created"
        elif [[ "${provisioning}" != "ACTIVE" ]]; then
            fail "${provider} load balancer provisioning status: ${provisioning}"
        else
            pass "${provider} load balancer ACTIVE"
            validate_vip "${provider} VIP ${vip}" "${vip}"
        fi
    done

    if command -v ovn-nbctl >/dev/null 2>&1 && command -v ovn-sbctl >/dev/null 2>&1; then
        if sudo ovn-nbctl --timeout=5 show >/dev/null && sudo ovn-sbctl --timeout=5 show >/dev/null; then
            pass "OVN NB/SB databases respond"
        else
            fail "OVN NB/SB database health"
        fi
    else
        skip "ovn-nbctl/ovn-sbctl unavailable on validation host"
    fi
}

[[ "${mode}" == "--static" || "${mode}" == "--all" ]] && run_static
[[ "${mode}" == "--live" || "${mode}" == "--all" ]] && run_live
printf 'SUMMARY: %d passed, %d failed, %d skipped\n' "${passes}" "${failures}" "${skips}"
(( failures == 0 ))
