# Phase A security review

## Scope and handling rule

This is a source review, not credential validation or penetration testing. The
unmodified upstream sample configuration contains values that appear
potentially sensitive. Phase A does **not** establish that any value is a live
credential or reachable endpoint. No such value is reproduced in tracked
files, and the original artifact was not edited or sanitized.

The complete artifact remains ignored and read-only under `original/`. If the
responsible owners determine that any referenced value is still valid, they
should rotate or revoke it in the relevant identity/network system and review
access logs. If it is not live, no rotation claim is implied.

## Findings

| Severity | Finding | Evidence | Recommendation |
|---|---|---|---|
| High | Potentially sensitive sample values are published in the upstream sdist | Untouched sample configuration in ignored `original/` | Keep excluded from Git; notify the upstream owner privately if appropriate; rotate/revoke conditionally if confirmed valid. |
| High | LoxiLB API default is unauthenticated plaintext HTTP | `common/config.py:20-27,69-96` defaults to a local HTTP endpoint and `loxilb_auth_type=none` | Production configuration must require HTTPS, server verification, and an appropriate auth mode; isolate management networking. |
| High | Debug API logging emits full request bodies and response text | `api/loxilb_client.py:294-305` | Never enable in production without structured redaction; suppress tokens, credentials, certificates, cookies, and sensitive payload fields. |
| High | TLS termination secret lifecycle is absent | Mapper/listener code passes container reference identifiers; no Barbican retrieval, secure delivery, or deletion path | Reject TLS termination until secret access, memory/file handling, rotation, revocation, and audit controls are designed and tested. |
| Medium | Local JSON state is a security and integrity boundary | `resource_mapping/mapper.py:28-50` defaults below `/var/lib/octavia` | Replace with durable access-controlled storage; use atomic writes, validation, locking, least privilege, backup, and tamper detection. |
| Medium | Retry and error logging may expose response content | `api/loxilb_client.py:251-354` includes response bodies in exceptions | Redact before logs/status messages; cap body size; separate operator diagnostics from user-facing errors. |
| Medium | OpenStack authentication options are duplicated/inconsistent | `[loxilb]` auth fields coexist with `service_auth`; sample options diverge from registrations | Use Keystone session loaders and secret-aware config sources; document file ownership/mode and avoid duplicate precedence. |
| Medium | Potentially destructive network/compute operations have ambiguous ownership | Load-balancer delete deallocates a VIP port and deletes name-matched servers | Define ownership tags and exact resource IDs; require idempotent read-before-delete and reconcile tombstones. |
| Medium | Unknown choices are silently weakened or changed | Mapper defaults unsupported protocol/algorithm/persistence | Fail closed with explicit unsupported-option errors; do not translate security-sensitive intent silently. |
| Low | Logs include infrastructure identifiers and addresses | Dynamic endpoint and network tasks log endpoint/port/server details | Use structured log levels and retention/access controls; identifiers are not secrets but may be operationally sensitive. |

## Positive controls present

- `oslo.config` marks LoxiLB/OpenStack password and token options as secret.
- TLS client certificate/key and CA verification options exist, with certificate
  verification defaulting to true when TLS auth is selected.
- The requests client uses bounded timeouts, and configuration validates URL
  schemes.

These controls are useful patterns, not proof of a secure deployment. The
plaintext/no-auth defaults, logging behavior, incomplete secret lifecycle, and
unvalidated environment prevent a production security conclusion.

## Phase A conclusion

No credential-like value was tested or characterized as confirmed live. No
original file was changed. Production use should remain blocked until secure
defaults, redaction, durable state, API authentication/TLS, and secret
lifecycle tests are part of the target design.
