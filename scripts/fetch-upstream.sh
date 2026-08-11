#!/usr/bin/env bash
set -euo pipefail

PACKAGE="octavia-loxilb-driver"
VERSION="1.0.3"
ARCHIVE_NAME="octavia_loxilb_driver-${VERSION}.tar.gz"
SOURCE_DIR_NAME="octavia_loxilb_driver-${VERSION}"
EXPECTED_SHA256="5d1c55752dadcc489c0780aeb83ebe117ab571eb8e5d8c2cf7c603241e445c5d"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
ORIGINAL_DIR="${REPOSITORY_ROOT}/upstream/octavia-loxilb-driver/original"
ARCHIVE_PATH="${ORIGINAL_DIR}/${ARCHIVE_NAME}"
SOURCE_PATH="${ORIGINAL_DIR}/${SOURCE_DIR_NAME}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

hash_file() {
    "${PYTHON_BIN}" - "$1" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys

path = Path(sys.argv[1])
print(sha256(path.read_bytes()).hexdigest())
PY
}

verify_archive() {
    local actual_sha256
    actual_sha256="$(hash_file "$1")"
    if [[ "${actual_sha256}" != "${EXPECTED_SHA256}" ]]; then
        echo "Checksum mismatch for $1" >&2
        echo "Expected: ${EXPECTED_SHA256}" >&2
        echo "Actual:   ${actual_sha256}" >&2
        exit 1
    fi
}

validate_archive_members() {
    "${PYTHON_BIN}" - "$1" "${SOURCE_DIR_NAME}" <<'PY'
from pathlib import PurePosixPath
import sys
import tarfile

archive, expected_root = sys.argv[1:]
with tarfile.open(archive, "r:gz") as source:
    for member in source.getmembers():
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts:
            raise SystemExit(f"Unsafe archive member: {member.name}")
        if not path.parts or path.parts[0] != expected_root:
            raise SystemExit(f"Unexpected archive root: {member.name}")
        if member.issym() or member.islnk():
            target = PurePosixPath(member.linkname)
            if target.is_absolute() or ".." in target.parts:
                raise SystemExit(f"Unsafe archive link: {member.name}")
PY
}

compare_trees() {
    "${PYTHON_BIN}" - "$1" "$2" <<'PY'
from hashlib import sha256
from pathlib import Path
import os
import sys


def manifest(root):
    root = Path(root)
    entries = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries[relative] = ("symlink", os.readlink(path))
        elif path.is_dir():
            entries[relative] = ("directory",)
        elif path.is_file():
            entries[relative] = ("file", sha256(path.read_bytes()).hexdigest())
        else:
            entries[relative] = ("other",)
    return entries


expected = manifest(sys.argv[1])
actual = manifest(sys.argv[2])
if expected != actual:
    for name in sorted(set(expected) | set(actual)):
        if expected.get(name) != actual.get(name):
            print(f"Tree mismatch: {name}", file=sys.stderr)
    raise SystemExit(1)
PY
}

mkdir -p "${ORIGINAL_DIR}"

if [[ ! -f "${ARCHIVE_PATH}" ]]; then
    DOWNLOAD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/octavia-loxilb-download.XXXXXX")"
    trap 'rm -rf -- "${DOWNLOAD_DIR}"' EXIT
    "${PYTHON_BIN}" -m pip download \
        --no-deps \
        --no-binary=:all: \
        --dest "${DOWNLOAD_DIR}" \
        "${PACKAGE}==${VERSION}"
    verify_archive "${DOWNLOAD_DIR}/${ARCHIVE_NAME}"
    cp -- "${DOWNLOAD_DIR}/${ARCHIVE_NAME}" "${ARCHIVE_PATH}"
fi

verify_archive "${ARCHIVE_PATH}"
validate_archive_members "${ARCHIVE_PATH}"

COMPARE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/octavia-loxilb-extract.XXXXXX")"
trap 'rm -rf -- "${COMPARE_DIR}" "${DOWNLOAD_DIR:-}"' EXIT
LC_ALL=C tar -xzf "${ARCHIVE_PATH}" -C "${COMPARE_DIR}"

if [[ -d "${SOURCE_PATH}" ]]; then
    if ! compare_trees "${COMPARE_DIR}/${SOURCE_DIR_NAME}" "${SOURCE_PATH}"; then
        echo "Existing source differs from the verified archive: ${SOURCE_PATH}" >&2
        echo "Refusing to overwrite immutable audit input." >&2
        exit 1
    fi
else
    LC_ALL=C tar -xzf "${ARCHIVE_PATH}" -C "${ORIGINAL_DIR}"
fi

chmod -R a-w "${ARCHIVE_PATH}" "${SOURCE_PATH}"
echo "Verified ${PACKAGE}==${VERSION}"
echo "SHA-256: ${EXPECTED_SHA256}"
echo "Source: ${SOURCE_PATH}"
