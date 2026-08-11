# Normalized Phase A evidence

This directory contains concise, tracked summaries of commands and results.
It intentionally excludes potentially sensitive values, machine-specific
absolute paths, raw virtual environments, caches, and full tool output.

Evidence documents:

- [`environment.md`](environment.md): audit date and tool versions.
- [`source-verification.md`](source-verification.md): checksum, PyPI comparison,
  tree verification, and immutability check.
- [`test-summary.md`](test-summary.md): installation, collection, unit, and
  entry-point results.
- [`quality-summary.md`](quality-summary.md): compile, dependency, Black, and
  Flake8 results.

Command notation uses `${SRC}` for the verified extracted source root and
`${VENV}` for the ignored Python 3.12 audit environment. Exit codes and counts
are observations from 2026-08-11. Functional, E2E, HA, scale, BGP/ECMP, and
benchmark results are explicitly not present because those tests were not run.
