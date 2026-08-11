#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/lab-common.sh
source "${SCRIPT_DIR}/lib/lab-common.sh"

provider="${1:-amphora}"
[[ "${provider}" == "amphora" || "${provider}" == "ovn" ]] || die "Usage: $0 [amphora|ovn]"
load_lab_env
for key in LB_SUBNET_NAME BACKEND1_FIXED_IP BACKEND2_FIXED_IP; do require_value "${key}"; done
require_command openstack
osc token issue >/dev/null

if ! osc loadbalancer provider list -f value -c name | grep -Fxq "${provider}"; then
    die "Octavia provider is not registered: ${provider}"
fi

prefix="baseline-${provider}"
lb_name="${prefix}-lb"
listener_name="${prefix}-tcp-80"
pool_name="${prefix}-pool"
hm_name="${prefix}-tcp-hm"
algorithm=ROUND_ROBIN
[[ "${provider}" == "ovn" ]] && algorithm=SOURCE_IP_PORT

lb_id="$(osc loadbalancer list --name "${lb_name}" -f value -c id | head -n 1)"
if [[ -z "${lb_id}" ]]; then
    lb_id="$(osc loadbalancer create --wait --name "${lb_name}" --provider "${provider}" --vip-subnet-id "${LB_SUBNET_NAME}" -f value -c id)"
    info "Created ${provider} load balancer ${lb_id}"
fi

actual_provider="$(osc loadbalancer show "${lb_id}" -f value -c provider)"
[[ "${actual_provider}" == "${provider}" ]] || die "Existing ${lb_name} uses provider ${actual_provider}, not ${provider}"
wait_for_lb() {
    local status attempt
    for attempt in $(seq 1 60); do
        status="$(osc loadbalancer show "${lb_id}" -f value -c provisioning_status)"
        [[ "${status}" == "ACTIVE" ]] && return 0
        [[ "${status}" == "ERROR" ]] && die "${lb_name} entered ERROR"
        sleep 5
    done
    die "Timed out waiting for ${lb_name} to become ACTIVE"
}
wait_for_lb

listener_id="$(osc loadbalancer listener list --name "${listener_name}" -f value -c id | head -n 1)"
if [[ -z "${listener_id}" ]]; then
    listener_id="$(osc loadbalancer listener create --wait --name "${listener_name}" --protocol TCP --protocol-port 80 "${lb_id}" -f value -c id)"
fi

pool_id="$(osc loadbalancer pool list --name "${pool_name}" -f value -c id | head -n 1)"
if [[ -z "${pool_id}" ]]; then
    pool_id="$(osc loadbalancer pool create --wait --name "${pool_name}" --listener "${listener_id}" --protocol TCP --lb-algorithm "${algorithm}" -f value -c id)"
fi

ensure_member() {
    local name="$1" address="$2"
    local member_id
    member_id="$(osc loadbalancer member list "${pool_id}" -f value -c id -c name | awk -v wanted="${name}" '$2 == wanted {print $1; exit}')"
    if [[ -z "${member_id}" ]]; then
        osc loadbalancer member create --wait --name "${name}" --subnet-id "${LB_SUBNET_NAME}" --address "${address}" --protocol-port 80 "${pool_id}" >/dev/null
    fi
}
ensure_member backend-1 "${BACKEND1_FIXED_IP}"
ensure_member backend-2 "${BACKEND2_FIXED_IP}"

hm_id="$(osc loadbalancer healthmonitor list --name "${hm_name}" -f value -c id | head -n 1)"
if [[ -z "${hm_id}" ]]; then
    osc loadbalancer healthmonitor create --wait --name "${hm_name}" --delay 5 --timeout 3 --max-retries 3 --type TCP "${pool_id}" >/dev/null
fi

vip="$(osc loadbalancer show "${lb_id}" -f value -c vip_address)"
info "${provider} baseline ready: ${vip}:80 (${lb_name})"
