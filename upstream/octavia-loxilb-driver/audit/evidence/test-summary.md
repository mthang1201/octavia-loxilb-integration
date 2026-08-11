# Test and packaging summary

## Commands (normalized)

```bash
python3.12 -m venv ${VENV}
${VENV}/bin/python -m pip install '${SRC}.tar.gz[dev]'

# Declared dependencies only
PYTHONDONTWRITEBYTECODE=1 ${VENV}/bin/python -m pytest \
  -p no:cacheprovider --collect-only ${SRC}/octavia_loxilb_driver/tests/unit

${VENV}/bin/python -m pip install octavia==18.0.0

# Upstream default, then explicit suites
(cd ${SRC} && PYTHONDONTWRITEBYTECODE=1 ${VENV}/bin/python -m pytest \
  -q -p no:cacheprovider)
PYTHONDONTWRITEBYTECODE=1 ${VENV}/bin/python -m pytest \
  -q -p no:cacheprovider --collect-only ${SRC}/octavia_loxilb_driver/tests/unit
PYTHONDONTWRITEBYTECODE=1 ${VENV}/bin/python -m pytest \
  -q -p no:cacheprovider ${SRC}/octavia_loxilb_driver/tests/unit
PYTHONDONTWRITEBYTECODE=1 ${VENV}/bin/python -m pytest \
  -q -p no:cacheprovider --collect-only ${SRC}/octavia_loxilb_driver/tests/functional
```

Tests were launched from an ignored working directory where necessary, with
bytecode and pytest cache writes disabled, so the source tree remained
unchanged.

## Results

| Check | Exit/result | Interpretation |
|---|---|---|
| Isolated sdist plus declared `dev` dependencies | install succeeded | The wheel/package can be built and installed on Python 3.12. |
| Unit collection with only declared dependencies | exit 2; 85 collected before two collection errors | Imports fail with `ModuleNotFoundError: octavia`; `octavia` is used but undeclared. |
| Plain upstream `pytest` | exit 5; zero tests | `testpaths=["tests"]` reaches a class named `LoadBalancerIntegrationTest`, which does not match configured `Test*`. |
| Explicit unit collection after Octavia 18.0.0 | 117 tests | Seven unit modules: 15 + 29 + 13 + 19 + 7 + 17 + 17. |
| Explicit unit execution | exit 1; 82 passed, 35 failed | Failures are real baseline defects/drift, not hidden or weakened. |
| Explicit functional collection | four tests | `NOT EXECUTED`: no reachable LoxiLB environment was available. |
| Provider entry point | load succeeded | Resolved `LoxiLBProviderDriver`. |
| Provider-agent entry point | load failed | Exported `controller.worker:LoxiLBControllerWorker` class is absent. |

The 35 failures comprise three API response-schema failures; seventeen
health-monitor failures; one load-balancer mapping failure; seven member
failures; five member/health-monitor coordination failures; and two pool
failures.

The upstream README claim of 121/121 passing and 100% coverage is not
reproduced. The source contains 122 syntactic test functions: 117 collected
unit tests, four collected functional tests, and one non-collectable root
integration method.
