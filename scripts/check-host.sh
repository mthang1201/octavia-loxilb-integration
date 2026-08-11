#!/usr/bin/env bash
set -u

STRICT=0
[[ "${1:-}" == "--strict" ]] && STRICT=1
failures=0

pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; failures=$((failures + 1)); }
warn() { printf 'WARN  %s\n' "$*"; }

if [[ "$(uname -s)" != "Linux" ]]; then
    fail "AIO host must be Linux (found $(uname -s))"
else
    pass "Linux host"
fi

cpu_count="$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 0)"
if (( cpu_count >= 16 )); then pass "CPU count ${cpu_count} >= 16"; else fail "CPU count ${cpu_count} < 16"; fi

mem_kib="$(awk '/MemTotal:/ {print $2}' /proc/meminfo 2>/dev/null || echo 0)"
if (( mem_kib >= 32 * 1024 * 1024 )); then pass "RAM >= 32 GiB"; else fail "RAM < 32 GiB"; fi

free_kib="$(df -Pk "${DEVSTACK_DEST:-/opt}" 2>/dev/null | awk 'NR==2 {print $4}' || echo 0)"
if (( free_kib >= 160 * 1024 * 1024 )); then pass "Free disk >= 160 GiB"; else fail "Free disk below 160 GiB at ${DEVSTACK_DEST:-/opt}"; fi

if [[ -c /dev/kvm && -r /dev/kvm && -w /dev/kvm ]]; then
    pass "/dev/kvm is usable"
else
    fail "/dev/kvm is not usable"
fi

if grep -Eq '(vmx|svm)' /proc/cpuinfo 2>/dev/null; then
    pass "CPU virtualization extension visible"
else
    fail "vmx/svm virtualization extension not visible"
fi

nested=""
for parameter in /sys/module/kvm_intel/parameters/nested /sys/module/kvm_amd/parameters/nested; do
    [[ -r "${parameter}" ]] && nested="$(tr '[:upper:]' '[:lower:]' < "${parameter}")"
done
if [[ "${nested}" == "y" || "${nested}" == "1" ]]; then
    pass "Nested virtualization enabled"
elif [[ -n "${nested}" ]]; then
    warn "Nested virtualization is disabled; this matters when os-aio is itself a VM"
else
    warn "Nested virtualization state could not be read"
fi

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${LAB_ENV_FILE:-${REPOSITORY_ROOT}/lab/lab.env}"
if [[ -f "${ENV_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    set +a
    if [[ -n "${PUBLIC_INTERFACE:-}" ]] && ip link show dev "${PUBLIC_INTERFACE}" >/dev/null 2>&1; then
        pass "Provider interface exists: ${PUBLIC_INTERFACE}"
    elif [[ -n "${PUBLIC_INTERFACE:-}" ]]; then
        fail "Provider interface does not exist: ${PUBLIC_INTERFACE}"
    else
        fail "PUBLIC_INTERFACE is not configured"
    fi
    if [[ -n "${HOST_IP:-}" ]] && ip -4 address show | grep -Fq "${HOST_IP}/"; then
        pass "HOST_IP is assigned locally: ${HOST_IP}"
    elif [[ -n "${HOST_IP:-}" ]]; then
        fail "HOST_IP is not assigned locally: ${HOST_IP}"
    else
        fail "HOST_IP is not configured"
    fi
else
    warn "${ENV_FILE} not found; interface/address checks skipped"
fi

if (( failures > 0 )); then
    printf 'SUMMARY: %d prerequisite failure(s)\n' "${failures}"
    (( STRICT == 1 )) && exit 1
fi
exit 0
