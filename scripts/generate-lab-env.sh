#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
SOURCE_FILE="${REPOSITORY_ROOT}/lab/lab.env.example"
DESTINATION_FILE="${LAB_ENV_FILE:-${REPOSITORY_ROOT}/lab/lab.env}"

command -v openssl >/dev/null 2>&1 || { echo "openssl is required" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 1; }

if [[ -e "${DESTINATION_FILE}" ]]; then
    echo "Refusing to overwrite ${DESTINATION_FILE}" >&2
    exit 1
fi

ADMIN_SECRET="$(openssl rand -hex 24)"
DATABASE_SECRET="$(openssl rand -hex 24)"
RABBIT_SECRET="$(openssl rand -hex 24)"
SERVICE_SECRET="$(openssl rand -hex 24)"
TOKEN_SECRET="$(openssl rand -hex 24)"
HEALTH_SECRET="$(openssl rand -hex 32)"
export SOURCE_FILE DESTINATION_FILE ADMIN_SECRET DATABASE_SECRET RABBIT_SECRET SERVICE_SECRET TOKEN_SECRET HEALTH_SECRET

python3 - <<'PY'
import os
from pathlib import Path

source = Path(os.environ["SOURCE_FILE"])
destination = Path(os.environ["DESTINATION_FILE"])
replacements = {
    "LAB_ADMIN_PASSWORD": os.environ["ADMIN_SECRET"],
    "LAB_DATABASE_PASSWORD": os.environ["DATABASE_SECRET"],
    "LAB_RABBIT_PASSWORD": os.environ["RABBIT_SECRET"],
    "LAB_SERVICE_PASSWORD": os.environ["SERVICE_SECRET"],
    "LAB_SERVICE_TOKEN": os.environ["TOKEN_SECRET"],
    "LAB_OCTAVIA_HEALTH_KEY": os.environ["HEALTH_SECRET"],
}
lines = []
for line in source.read_text().splitlines():
    key = line.split("=", 1)[0]
    if key in replacements:
        line = f"{key}={replacements[key]}"
    lines.append(line)
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text("\n".join(lines) + "\n")
PY

chmod 600 "${DESTINATION_FILE}"
echo "Created ${DESTINATION_FILE} with mode 0600"
echo "Fill HOST_IP, PUBLIC_INTERFACE, MGMT_ALLOWED_CIDR, image and SSH key settings before rendering."
