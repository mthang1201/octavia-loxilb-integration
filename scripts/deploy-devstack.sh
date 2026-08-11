#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/lab-common.sh
source "${SCRIPT_DIR}/lib/lab-common.sh"

RUN_STACK=0
[[ "${1:-}" == "--run" ]] && RUN_STACK=1
load_lab_env
for key in DEVSTACK_REPOSITORY DEVSTACK_REF; do require_value "${key}"; done
require_command git

if [[ "${EUID}" == "0" ]]; then
    die "Run as the unprivileged stack user, not root"
fi

DEST="${DEVSTACK_DEST:-/opt/stack/devstack}"
if [[ ! -d "${DEST}/.git" ]]; then
    mkdir -p "$(dirname -- "${DEST}")"
    git clone "${DEVSTACK_REPOSITORY}" "${DEST}"
fi

git -C "${DEST}" fetch --tags origin "${DEVSTACK_REF}"
git -C "${DEST}" checkout --detach "${DEVSTACK_REF}"
"${SCRIPT_DIR}/render-devstack-config.sh" "${DEST}/local.conf"
info "DevStack checkout: $(git -C "${DEST}" rev-parse HEAD)"

if (( RUN_STACK == 1 )); then
    "${SCRIPT_DIR}/check-host.sh" --strict
    info "Running stack.sh; this is a long, network-dependent operation"
    "${DEST}/stack.sh"
else
    info "Configuration prepared. Re-run with --run after reviewing ${DEST}/local.conf"
fi
