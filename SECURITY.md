# Security Policy

## Supported Versions

`orbital-mesh` is pre-1.0. Security fixes are accepted on `main` and `master`. Release tags are supported only when a maintainer explicitly marks them as active in the release record.

## Reporting Vulnerabilities

Report suspected vulnerabilities through GitHub private vulnerability reporting or a private maintainer channel. Do not file public issues for exploitable behavior, secret exposure, auth bypass, unsafe actuation, supply-chain compromise, or audit-log tampering.

Include:

- affected commit, tag, image digest, or deployment record;
- reproduction steps against a local or disposable environment;
- expected and observed behavior;
- logs or artifacts with secrets redacted;
- whether the issue affects read-only inspection, run creation, steering, approval, actuation, exports, model-serving, or release provenance.

Do not send raw kubeconfigs, API keys, bearer tokens, database URLs with credentials, private keys, production traces containing customer data, or unredacted run exports.

## Security Design Baseline

Production operation must keep:

- authenticated ingress in front of the HTTP API;
- proxy-stamped operator identity headers stripped from untrusted clients before Mesh sees them;
- `MESH_OPERATOR_IDENTITY_REQUIRED=1`;
- `MESH_FORCE_APPROVAL_GATE=1`;
- bounded Kubernetes contexts and namespaces when live execution is enabled;
- security headers enabled;
- Postgres or another durable state backend for pilot and production profiles;
- run-export retention reviewed and enforced;
- Mesh Brain production artifacts backed by durable object storage and hash-checked upload proof;
- release provenance packets complete before pilot promotion.

## Audit Cadence

Every pull request must pass CI and security audit readiness checks. The scheduled security workflow runs weekly and records secret scanning, dependency review, CodeQL when supported, and OpenSSF Scorecard when supported by repository visibility or GitHub Advanced Security. External dependency vulnerability scans, including OSV lockfile scanning and `npm audit`, run automatically for public repositories and require explicit `EXTERNAL_DEPENDENCY_AUDIT_ON_PRIVATE=true` approval for private repositories.

Release candidates must also include:

- `scripts/verify_release_cut_list.py --json`;
- `scripts/verify_security_audit_readiness.py --json`;
- authenticated ingress rehearsal evidence;
- production smoke evidence;
- Postgres restart-proof evidence when Postgres is the state backend;
- Mesh Brain artifact registry proof when model artifacts are part of the release;
- complete release provenance with SBOM path, vulnerability scan path, image digest, base-image digests, dependency lock hashes, policy hashes, migration hashes, build command, and builder identity.

## Disclosure And Remediation

Maintainers triage reports by authority impact first: unauthenticated mutation, auth bypass, live-actuation bypass, secret disclosure, audit-log tampering, release-provenance forgery, model-serving policy bypass, and denial of service against approval or kill-switch paths. Fixes must preserve audit evidence and must not make unsafe runtime modes easier to enable.
