#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/lab-common.sh
source "${SCRIPT_DIR}/lib/lab-common.sh"

load_lab_env
for key in PUBLIC_NETWORK_NAME LB_NETWORK_NAME LB_SUBNET_NAME LB_CIDR LB_GATEWAY LOXILB_FIXED_IP BACKEND1_FIXED_IP BACKEND2_FIXED_IP CLIENT_FIXED_IP LOXILB_VIP LAB_IMAGE_NAME LAB_IMAGE_FILE LAB_IMAGE_SHA256 LAB_SSH_KEY_NAME LAB_SSH_PUBLIC_KEY_FILE LOXILB_IMAGE MGMT_ALLOWED_CIDR; do
    require_value "${key}"
done
require_command openstack
require_command python3

osc token issue >/dev/null
info "OpenStack authentication succeeded"

[[ -f "${LAB_IMAGE_FILE}" ]] || die "Image file not found: ${LAB_IMAGE_FILE}"
[[ -f "${LAB_SSH_PUBLIC_KEY_FILE}" ]] || die "SSH public key not found: ${LAB_SSH_PUBLIC_KEY_FILE}"
actual_image_sha="$(sha256_file "${LAB_IMAGE_FILE}")"
[[ "${actual_image_sha}" == "${LAB_IMAGE_SHA256}" ]] || die "Image checksum mismatch: expected ${LAB_IMAGE_SHA256}, got ${actual_image_sha}"

if ! osc image show "${LAB_IMAGE_NAME}" >/dev/null 2>&1; then
    osc image create "${LAB_IMAGE_NAME}" \
        --disk-format qcow2 \
        --container-format bare \
        --property baseline=true \
        --property "lab_image_sha256=${actual_image_sha}" \
        --file "${LAB_IMAGE_FILE}" >/dev/null
    info "Created image ${LAB_IMAGE_NAME}"
else
    stored_image_sha="$(osc image show "${LAB_IMAGE_NAME}" -f json | python3 -c 'import json,re,sys; d=json.load(sys.stdin); p=d.get("properties", {}); value=d.get("lab_image_sha256", ""); value=p.get("lab_image_sha256", value) if isinstance(p, dict) else value; match=re.search(r"(?:^|[, ]+)lab_image_sha256=[\x27\x22]?([0-9a-fA-F]{64})", p) if isinstance(p, str) else None; print(match.group(1) if match else value)')"
    [[ "${stored_image_sha}" == "${actual_image_sha}" ]] || die "Existing image ${LAB_IMAGE_NAME} is not the recorded artifact (${stored_image_sha:-no checksum property})"
    info "Image ${LAB_IMAGE_NAME} already exists with the expected checksum"
fi

if ! osc keypair show "${LAB_SSH_KEY_NAME}" >/dev/null 2>&1; then
    osc keypair create --public-key "${LAB_SSH_PUBLIC_KEY_FILE}" "${LAB_SSH_KEY_NAME}" >/dev/null
    info "Created keypair ${LAB_SSH_KEY_NAME}"
fi

ensure_flavor() {
    local name="$1" ram="$2" vcpus="$3" disk="$4"
    if ! osc flavor show "${name}" >/dev/null 2>&1; then
        osc flavor create --ram "${ram}" --vcpus "${vcpus}" --disk "${disk}" --public "${name}" >/dev/null
        info "Created flavor ${name}"
    else
        osc flavor show "${name}" -f json | python3 -c 'import json,sys; d=json.load(sys.stdin); expected={"ram":int(sys.argv[1]),"vcpus":int(sys.argv[2]),"disk":int(sys.argv[3])}; actual={k:int(d[k]) for k in expected}; raise SystemExit(0 if actual == expected else f"flavor drift: {actual} != {expected}")' "${ram}" "${vcpus}" "${disk}" || die "Existing flavor ${name} differs from the baseline"
    fi
}
ensure_flavor lab.small 1024 1 8
ensure_flavor lab.medium 2048 2 10

if ! osc network show "${PUBLIC_NETWORK_NAME}" >/dev/null 2>&1; then
    die "DevStack public network ${PUBLIC_NETWORK_NAME} is missing"
fi
public_external="$(osc network show "${PUBLIC_NETWORK_NAME}" -f value -c router:external)"
[[ "${public_external,,}" == "true" ]] || die "${PUBLIC_NETWORK_NAME} is not an external network"

if ! osc network show "${LB_NETWORK_NAME}" >/dev/null 2>&1; then
    osc network create --internal --enable-port-security "${LB_NETWORK_NAME}" >/dev/null
    info "Created network ${LB_NETWORK_NAME}"
fi
port_security="$(osc network show "${LB_NETWORK_NAME}" -f value -c port_security_enabled)"
[[ "${port_security,,}" == "true" ]] || die "Port security must remain enabled on ${LB_NETWORK_NAME}"

if ! osc subnet show "${LB_SUBNET_NAME}" >/dev/null 2>&1; then
    osc subnet create "${LB_SUBNET_NAME}" \
        --network "${LB_NETWORK_NAME}" \
        --subnet-range "${LB_CIDR}" \
        --gateway "${LB_GATEWAY}" \
        --dns-nameserver 1.1.1.1 \
        --allocation-pool start=10.20.0.10,end=10.20.0.99 \
        --allocation-pool start=10.20.0.120,end=10.20.0.254 >/dev/null
    info "Created subnet ${LB_SUBNET_NAME}; 10.20.0.100-119 stays out of automatic allocation"
else
    osc subnet show "${LB_SUBNET_NAME}" -f json | python3 -c 'import json,sys; d=json.load(sys.stdin); expected=(sys.argv[1],sys.argv[2]); actual=(d.get("cidr"),d.get("gateway_ip")); raise SystemExit(0 if actual == expected else f"subnet drift: {actual} != {expected}")' "${LB_CIDR}" "${LB_GATEWAY}" || die "Existing subnet ${LB_SUBNET_NAME} differs from the baseline"
fi

if ! osc router show lab-router >/dev/null 2>&1; then
    osc router create lab-router >/dev/null
fi
gateway_network="$(osc router show lab-router -f json | python3 -c 'import json,sys; print((json.load(sys.stdin).get("external_gateway_info") or {}).get("network_id", ""))')"
public_network_id="$(osc network show "${PUBLIC_NETWORK_NAME}" -f value -c id)"
if [[ "${gateway_network}" != "${public_network_id}" ]]; then
    osc router set --external-gateway "${PUBLIC_NETWORK_NAME}" lab-router
fi
if ! osc router show lab-router -f json | python3 -c 'import json,sys; target=sys.argv[1]; ports=json.load(sys.stdin).get("interfaces_info", []); raise SystemExit(0 if any(p.get("subnet_id")==target for p in ports) else 1)' "$(osc subnet show "${LB_SUBNET_NAME}" -f value -c id)"; then
    osc router add subnet lab-router "${LB_SUBNET_NAME}"
fi

if ! osc security group show lab-workload >/dev/null 2>&1; then
    osc security group create --description "Baseline workload traffic" lab-workload >/dev/null
fi

ensure_rule() {
    local protocol="$1" port="$2" remote="$3"
    local args=(security group rule create --ingress --protocol "${protocol}" --remote-ip "${remote}")
    [[ -n "${port}" ]] && args+=(--dst-port "${port}")
    args+=(lab-workload)
    local error_file
    error_file="$(mktemp "${TMPDIR:-/tmp}/lab-sg-rule.XXXXXX")"
    if ! osc "${args[@]}" >/dev/null 2>"${error_file}"; then
        if grep -Eqi 'already exists|conflict|duplicate' "${error_file}"; then
            info "Security-group rule already exists: ${protocol} ${port:-all} from ${remote}"
        else
            sed 's/^/openstack: /' "${error_file}" >&2
            rm -f -- "${error_file}"
            die "Could not create security-group rule"
        fi
    fi
    rm -f -- "${error_file}"
}
ensure_rule icmp "" "${LB_CIDR}"
ensure_rule tcp 80 "${LB_CIDR}"
ensure_rule tcp 22 "${MGMT_ALLOWED_CIDR}"

ensure_port() {
    local name="$1" address="$2"
    local fixed_ips
    if ! osc port show "${name}" >/dev/null 2>&1; then
        osc port create "${name}" \
            --network "${LB_NETWORK_NAME}" \
            --fixed-ip "subnet=${LB_SUBNET_NAME},ip-address=${address}" \
            --security-group lab-workload >/dev/null
        info "Created port ${name} (${address})"
    else
        fixed_ips="$(osc port show "${name}" -f value -c fixed_ips)"
        [[ "${fixed_ips}" == *"${address}"* ]] || die "Existing port ${name} does not have ${address}"
    fi
}
ensure_port backend-1-port "${BACKEND1_FIXED_IP}"
ensure_port backend-2-port "${BACKEND2_FIXED_IP}"
ensure_port client-1-port "${CLIENT_FIXED_IP}"
ensure_port loxilb-1-port "${LOXILB_FIXED_IP}"
osc port set --allowed-address "ip-address=${LOXILB_VIP}/32" loxilb-1-port

render_user_data() {
    local template="$1" output="$2" instance_name="${3:-}"
    TEMPLATE_FILE="${template}" OUTPUT_FILE="${output}" INSTANCE_NAME="${instance_name}" LOXILB_IMAGE_VALUE="${LOXILB_IMAGE}" python3 - <<'PY'
import os
from pathlib import Path

text = Path(os.environ["TEMPLATE_FILE"]).read_text()
text = text.replace("{{INSTANCE_NAME}}", os.environ["INSTANCE_NAME"])
text = text.replace("{{LOXILB_IMAGE}}", os.environ["LOXILB_IMAGE_VALUE"])
if "{{" in text or "}}" in text:
    raise SystemExit("Unresolved cloud-init template marker")
Path(os.environ["OUTPUT_FILE"]).write_text(text)
PY
}

temporary_directory="$(mktemp -d "${TMPDIR:-/tmp}/baseline-cloud-init.XXXXXX")"
trap 'rm -rf -- "${temporary_directory}"' EXIT
render_user_data "${LAB_REPOSITORY_ROOT}/deployment/cloud-init/backend.yaml.tpl" "${temporary_directory}/backend-1.yaml" backend-1
render_user_data "${LAB_REPOSITORY_ROOT}/deployment/cloud-init/backend.yaml.tpl" "${temporary_directory}/backend-2.yaml" backend-2
render_user_data "${LAB_REPOSITORY_ROOT}/deployment/cloud-init/loxilb.yaml.tpl" "${temporary_directory}/loxilb-1.yaml"

ensure_server() {
    local name="$1" port="$2" flavor="$3" user_data="$4"
    if ! osc server show "${name}" >/dev/null 2>&1; then
        osc server create "${name}" \
            --image "${LAB_IMAGE_NAME}" \
            --flavor "${flavor}" \
            --key-name "${LAB_SSH_KEY_NAME}" \
            --nic "port-id=$(osc port show "${port}" -f value -c id)" \
            --user-data "${user_data}" \
            --property baseline=true \
            --wait >/dev/null
        info "Created server ${name}"
    else
        status="$(osc server show "${name}" -f value -c status)"
        [[ "${status}" != "ERROR" ]] || die "Existing server ${name} is in ERROR; inspect it before replacing"
    fi
}
ensure_server backend-1 backend-1-port lab.small "${temporary_directory}/backend-1.yaml"
ensure_server backend-2 backend-2-port lab.small "${temporary_directory}/backend-2.yaml"
ensure_server client-1 client-1-port lab.small "${LAB_REPOSITORY_ROOT}/deployment/cloud-init/client.yaml"
ensure_server loxilb-1 loxilb-1-port lab.medium "${temporary_directory}/loxilb-1.yaml"

ensure_floating_ip() {
    local port_name="$1"
    local port_id address
    port_id="$(osc port show "${port_name}" -f value -c id)"
    address="$(osc floating ip list --port "${port_id}" -f value -c 'Floating IP Address' | head -n 1)"
    if [[ -z "${address}" ]]; then
        address="$(osc floating ip create --port "${port_id}" "${PUBLIC_NETWORK_NAME}" -f value -c floating_ip_address)"
    fi
    printf '%s\n' "${address}"
}

client_fip="$(ensure_floating_ip client-1-port)"
loxilb_fip="$(ensure_floating_ip loxilb-1-port)"
info "client-1 floating IP: ${client_fip}"
info "loxilb-1 floating IP: ${loxilb_fip}"
info "Bootstrap complete. Wait for cloud-init, then run scripts/configure-loxilb.sh"
