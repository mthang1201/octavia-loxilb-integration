#!/usr/bin/env bash

set -euo pipefail

LAB_SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LAB_REPOSITORY_ROOT="$(CDPATH= cd -- "${LAB_SCRIPT_DIR}/.." && pwd)"
LAB_ENV_FILE="${LAB_ENV_FILE:-${LAB_REPOSITORY_ROOT}/lab/lab.env}"

die() {
    echo "ERROR: $*" >&2
    exit 1
}

info() {
    echo "INFO: $*"
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

load_lab_env() {
    [[ -f "${LAB_ENV_FILE}" ]] || die "Missing ${LAB_ENV_FILE}; run scripts/generate-lab-env.sh first"
    set -a
    # shellcheck disable=SC1090
    source "${LAB_ENV_FILE}"
    set +a
}

require_value() {
    local name="$1"
    [[ -n "${!name:-}" ]] || die "${name} is required in ${LAB_ENV_FILE}"
}

osc() {
    if [[ -n "${LAB_OS_CLOUD:-}" ]]; then
        openstack --os-cloud "${LAB_OS_CLOUD}" "$@"
    else
        openstack "$@"
    fi
}

single_id() {
    local output
    output="$(osc "$@" -f value -c ID)"
    [[ "$(printf '%s\n' "${output}" | sed '/^[[:space:]]*$/d' | wc -l | tr -d ' ')" == "1" ]] || return 1
    printf '%s\n' "${output}"
}

sha256_file() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        die "sha256sum or shasum is required"
    fi
}
