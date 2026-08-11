# Source verification

## Commands

```bash
python -m pip download --no-deps --no-binary=:all: \
  --dest <ignored-download-directory> octavia-loxilb-driver==1.0.3
scripts/fetch-upstream.sh
```

The verification script hashes the archive, extracts it to a fresh temporary
directory, compares directory/file/symlink manifests and per-file SHA-256
values, refuses a mismatch, and finally removes write permission.

## Results

| Check | Result |
|---|---|
| Workspace archive size | 481,903 bytes |
| Fresh PyPI archive size | 481,903 bytes |
| Workspace SHA-256 | `5d1c55752dadcc489c0780aeb83ebe117ab571eb8e5d8c2cf7c603241e445c5d` |
| Fresh PyPI SHA-256 | `5d1c55752dadcc489c0780aeb83ebe117ab571eb8e5d8c2cf7c603241e445c5d` |
| Byte comparison | identical |
| Extracted regular files | 144 |
| Extracted tree vs fresh extraction | identical |
| Archive/source permissions after verification | read-only |
| Git policy | `original/` ignored; no original content staged or tracked |

Potentially sensitive-looking upstream sample values were not copied into this
evidence. Their validity was not tested.
