#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/lab-common.sh
source "${SCRIPT_DIR}/lib/lab-common.sh"

load_lab_env
for key in LOXILB_VIP BACKEND1_FIXED_IP BACKEND2_FIXED_IP LAB_SSH_PRIVATE_KEY_FILE LAB_SSH_USER; do require_value "${key}"; done
require_command openstack
require_command ssh
[[ -f "${LAB_SSH_PRIVATE_KEY_FILE}" ]] || die "SSH private key not found: ${LAB_SSH_PRIVATE_KEY_FILE}"

port_id="$(osc port show loxilb-1-port -f value -c id)"
loxilb_fip="$(osc floating ip list --port "${port_id}" -f value -c 'Floating IP Address' | head -n 1)"
[[ -n "${loxilb_fip}" ]] || die "loxilb-1 has no floating IP"

ssh_options=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -i "${LAB_SSH_PRIVATE_KEY_FILE}")
remote="${LAB_SSH_USER}@${loxilb_fip}"

info "Waiting for LoxiLB container on ${remote}"
for attempt in $(seq 1 30); do
    if ssh "${ssh_options[@]}" "${remote}" 'sudo docker exec loxilb loxicmd get lb >/dev/null 2>&1'; then
        break
    fi
    (( attempt < 30 )) || die "LoxiLB did not become ready"
    sleep 5
done

# Replace only the exact baseline VIP/port.  This makes reruns deterministic
# without touching any unrelated LoxiLB rule.
ssh "${ssh_options[@]}" "${remote}" \
    "sudo docker exec loxilb loxicmd delete lb '${LOXILB_VIP}' --tcp=80 >/dev/null 2>&1 || true; sudo docker exec loxilb loxicmd create lb '${LOXILB_VIP}' --tcp=80:80 --endpoints='${BACKEND1_FIXED_IP}:1,${BACKEND2_FIXED_IP}:1' --mode=onearm --monitor; sudo docker exec loxilb loxicmd save --lb"

info "Configured standalone LoxiLB service ${LOXILB_VIP}:80"
ssh "${ssh_options[@]}" "${remote}" 'sudo docker exec loxilb loxicmd get lb -o wide'
