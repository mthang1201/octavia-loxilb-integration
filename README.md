# Viettel IDC OpenStack–LoxiLB R&D

This repository is in **Phase A: upstream audit**. No replacement Provider
Driver, target architecture, deployment, benchmark, or production claim has
been implemented.

The audited reference is `octavia-loxilb-driver==1.0.3`. Its immutable source
is kept locally outside Git; provenance and checksum are recorded in
[`SOURCE.md`](upstream/octavia-loxilb-driver/SOURCE.md). To reproduce the source
setup:

```bash
scripts/fetch-upstream.sh
```

The audit distinguishes source-verified behavior from partial implementations,
unsupported features, upstream claims without evidence, unimplemented paths,
and unknowns. Start with the
[`feature matrix`](upstream/octavia-loxilb-driver/audit/FEATURE_MATRIX.md) and
[`reuse matrix`](upstream/octavia-loxilb-driver/audit/REUSE_MATRIX.md).

## Security notice

The untouched upstream source contains sample configuration with values that
appear potentially sensitive. This repository does not establish that they are
live and does not reproduce them in tracked content. The original remains
ignored and immutable. If the responsible operators confirm that any values
are still valid, they should rotate or revoke them.

## Evidence policy

“Verified” means supported by inspected source or a recorded command. It does
not mean a feature was validated against real OpenStack or LoxiLB unless that
environment and evidence are named. Functional, E2E, HA, scale-out, BGP/ECMP,
and benchmark work was not executed in Phase A.

## Next gate

Before Provider Driver development, validate the target LoxiLB version
standalone and write an architecture decision comparing the upstream per-LB VM
model with a shared LoxiLB infrastructure cluster. The shared-cluster model is
the preferred Viettel IDC research hypothesis, not an approved architecture.

