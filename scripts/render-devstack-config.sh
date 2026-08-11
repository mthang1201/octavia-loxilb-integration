#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/lab-common.sh
source "${SCRIPT_DIR}/lib/lab-common.sh"

load_lab_env
for key in HOST_IP PUBLIC_INTERFACE MGMT_ALLOWED_CIDR OPENSTACK_RELEASE DEVSTACK_REF OCTAVIA_REF OVN_OCTAVIA_PROVIDER_REF LAB_ADMIN_PASSWORD LAB_DATABASE_PASSWORD LAB_RABBIT_PASSWORD LAB_SERVICE_PASSWORD LAB_SERVICE_TOKEN LAB_OCTAVIA_HEALTH_KEY; do
    require_value "${key}"
done

TEMPLATE="${LAB_REPOSITORY_ROOT}/deployment/devstack/local.conf.tpl"
DESTINATION="${1:-${LAB_REPOSITORY_ROOT}/lab/generated/local.conf}"
require_command python3
export TEMPLATE DESTINATION

python3 - <<'PY'
import os
import re
import shlex
from pathlib import Path

template = Path(os.environ["TEMPLATE"]).read_text()
keys = set(re.findall(r"{{([A-Z0-9_]+)}}", template))
for key in sorted(keys):
    value = os.environ.get(key, "")
    if not value:
        raise SystemExit(f"Missing template value: {key}")
    if "\n" in value or "\r" in value:
        raise SystemExit(f"Newline is not allowed in {key}")
    template = template.replace("{{" + key + "}}", shlex.quote(value))
if "{{" in template or "}}" in template:
    raise SystemExit("Unresolved template marker")
destination = Path(os.environ["DESTINATION"])
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(template)
PY

chmod 600 "${DESTINATION}"
info "Rendered ${DESTINATION} with mode 0600"
