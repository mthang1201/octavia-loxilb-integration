# Upstream source record

## Artifact

| Field | Value |
|---|---|
| Package | `octavia-loxilb-driver` |
| Version | `1.0.3` |
| Distribution | Python source distribution (`.tar.gz`) |
| PyPI | <https://pypi.org/project/octavia-loxilb-driver/1.0.3/> |
| Project repository declared by package | <https://github.com/NLX-SeokHwanKong/octavia-loxilb-driver> |
| SHA-256 | `5d1c55752dadcc489c0780aeb83ebe117ab571eb8e5d8c2cf7c603241e445c5d` |

On 2026-08-11, `pip download --no-deps --no-binary=:all:
octavia-loxilb-driver==1.0.3` produced an archive byte-identical to the archive
already present in this workspace: both were 481,903 bytes and had the SHA-256
above.

## Preservation policy

The archive and extracted source live under `original/`. That directory is
ignored by Git and treated as immutable audit input. The upstream artifact is
never edited or sanitized, including its sample configuration. Run
`scripts/fetch-upstream.sh` to retrieve, verify, and extract it reproducibly.
The script refuses to overwrite an extracted tree that differs from the
verified archive and removes write permission after verification.

The upstream sample configuration contains values that appear potentially
sensitive. This audit does not establish whether they are live. They are not
reproduced in tracked files. If their owners determine that any remain valid,
they should rotate or revoke them through the relevant systems.

## Audit metadata

| Field | Value |
|---|---|
| Audit date | 2026-08-11 |
| Host | macOS Darwin 24.3.0, arm64 |
| Test interpreter | CPython 3.12.13 |
| Default host interpreter | CPython 3.14.6 (outside upstream's declared 3.8–3.11 classifiers) |
| Audit scope | Phase A static review, packaging checks, unit-test reproduction, and claim verification |
| Real OpenStack/LoxiLB environment | Not available; functional/E2E/HA/performance claims remain unverified |

Evidence labels used throughout the audit are `verified`, `partial`,
`unsupported`, `claimed but unverified`, `not implemented`, and `unknown`.
“Verified” means directly demonstrated by inspected source or an executed test;
it does not imply successful operation against a real LoxiLB deployment unless
that evidence is explicitly cited.

## Audit index

- [`audit/ARCHITECTURE.md`](audit/ARCHITECTURE.md)
- [`audit/CODE_WALKTHROUGH.md`](audit/CODE_WALKTHROUGH.md)
- [`audit/FEATURE_MATRIX.md`](audit/FEATURE_MATRIX.md)
- [`audit/REUSE_MATRIX.md`](audit/REUSE_MATRIX.md)
- [`audit/ISSUES.md`](audit/ISSUES.md)
- [`audit/SECURITY_REVIEW.md`](audit/SECURITY_REVIEW.md)
- [`audit/evidence/README.md`](audit/evidence/README.md)

The upstream distribution declares Apache License 2.0. That observation does
not choose a license for the Viettel IDC repository itself.

