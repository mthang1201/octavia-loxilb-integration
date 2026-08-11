# Static and dependency quality summary

## Commands (normalized)

```bash
PYTHONPYCACHEPREFIX=<ignored-directory> ${VENV}/bin/python -m compileall -q ${SRC}
${VENV}/bin/python -m pip check
${VENV}/bin/black --check ${SRC}
(cd ${SRC} && ${VENV}/bin/flake8 .)
(cd ${SRC} && ${VENV}/bin/flake8 --ignore=F811 .)
```

These commands were read-only with respect to the immutable upstream tree.

## Results

| Check | Result |
|---|---|
| `compileall` | exit 0 |
| `pip check` after supplemental Octavia install | exit 0, no broken installed requirements |
| Black check | exit 1; 49 files would be reformatted, 24 unchanged |
| Flake8 7.3.0, unconfigured | exit 1; 3,704 findings |
| Flake8 excluding only `F811` | exit 1; 3,700 findings |

The four-count difference is fully accounted for by four duplicate-definition
`F811` findings: two methods in the API client, one controller-worker method,
and one task class. The approved baseline's normalized 3,700 count excluded
that category; the current tool's ordinary output is recorded as 3,704 so the
evidence remains reproducible and does not conceal defects.

`pip check` describes the final audit environment after Octavia was manually
added. It does not negate the earlier collection failure demonstrating that
the sdist's declared dependencies are incomplete.
