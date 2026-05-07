# Security Audit Readiness

This repository treats OpenSSF alignment as an executable control set, not a badge claim.

## OpenSSF Control Map

| Area | Repository control |
| --- | --- |
| Security policy | `SECURITY.md` defines supported versions, private reporting, sensitive artifact handling, baseline controls, and audit cadence. |
| Scorecard | `.github/workflows/security.yml` runs OpenSSF Scorecard on public repositories, and on private repositories only when `OPENSSF_SCORECARD_ON_PRIVATE=true` is set. |
| Dependency update tool | `.github/dependabot.yml` covers GitHub Actions, npm, pip, root Cargo, and LatentMAS Cargo dependencies. |
| Dependency review | Pull requests run GitHub dependency review and fail on high or critical severity dependency changes when the repository is public or `GHAS_DEPENDENCY_REVIEW_ON_PRIVATE=true` confirms private-repository support. |
| Known vulnerabilities | The security workflow scans lockfiles with a pinned OSV scanner image, uploads `osv-lockfile-scan.json`, runs `npm audit --audit-level=high`, and uploads `npm-audit.json` for release-candidate evidence. |
| Token permissions | GitHub workflows use `contents: read` by default, with scoped write permissions only for SARIF upload jobs. |
| Pinned workflow dependencies | First-party workflows pin external GitHub Actions to full commit SHAs. |
| Code review ownership | `.github/CODEOWNERS` names owners for critical runtime, schema, policy, docs, and workflow paths. |
| Secret handling | `.gitignore`, `SECURITY.md`, production docs, run-export redaction, and the scheduled Gitleaks CLI secret scan cover committed and exported secret material. |
| Release provenance | `scripts/generate_release_provenance.py` records commit, image digest, base-image digests, lockfile hashes, policy hashes, migrations, SBOM, vulnerability scan, build command, and builder identity. |
| Runtime evidence | `docs/production-hardening-records.md` points auditors to identity gates, policy simulation, kill switch, run exports, Merkle proof, retention, and go/no-go evidence. |
| Procurement security package | `config/procurement-security.package.json` and `scripts/verify_procurement_security_package.py` bind SSO, audit export, retention, data boundaries, deployment modes, security answers, support escalation, and known limitations into one reviewed artifact set. |

OpenSSF Best Practices Badge self-certification is a maintainer attestation step. The executable evidence for that attestation comes from this document, `SECURITY.md`, the security workflow, release provenance, and production hardening records.

## Regular Audit Cadence

Pull request:

- CI lint, tests, web build, web tests, and Docker health smoke;
- audit readiness verifier;
- dependency review;
- secret scan;
- lockfile vulnerability scan;
- npm audit.

Weekly:

- scheduled security workflow;
- OpenSSF Scorecard where repository visibility and GitHub security features permit it;
- CodeQL where repository visibility and GitHub security features permit it;
- dependency-review, OSV lockfile scan, and npm audit release-candidate outputs;
- Dependabot update proposals.

Release candidate:

- production cut-list verifier;
- audit readiness verifier;
- authenticated ingress rehearsal;
- production smoke;
- Postgres restart proof when Postgres backs state;
- Mesh Brain artifact upload proof when Mesh Brain artifacts ship;
- complete release provenance packet.

Quarterly:

- review CODEOWNERS coverage for critical paths;
- review role boundaries for launcher, viewer, approver, and admin;
- sample run exports for redaction and retention metadata;
- rehearse kill-switch and rollback evidence;
- refresh OpenSSF Best Practices Badge answers against current repo evidence.

## E2E Audit Commands

```bash
scripts/verify_security_audit_readiness.py --json
scripts/verify_procurement_security_package.py --json
scripts/verify_release_cut_list.py --json
scripts/verify_authenticated_ingress.py --json
scripts/prod_smoke.sh
scripts/verify_postgres_restart_proof.py --json
scripts/generate_release_provenance.py --require-complete --json
scripts/verify_mesh_brain_artifact_registry.py --require-upload-proof --json
npm --prefix web run lint
```

`scripts/generate_release_provenance.py --require-complete` requires CI or release-job inputs for image digest, base-image digests, SBOM, vulnerability scan, build command, and builder identity. Local developer runs are expected to be incomplete unless those inputs are provided.

## Audit Evidence Package

Auditors should receive:

- GitHub workflow run URLs for CI and security audit;
- dependency-review, secret-scan, OSV, npm audit, CodeQL, and Scorecard outputs when available;
- release provenance JSON and packet hash;
- SBOM and vulnerability scan artifacts referenced by release provenance;
- authenticated ingress rehearsal output;
- production smoke output;
- go/no-go API output;
- run export archive for a representative approved action and a denied action;
- Mesh Brain artifact upload proof when model artifacts are in scope.

Audit packages must not include raw secrets, kubeconfigs, bearer tokens, database URLs with credentials, private keys, or unredacted production traces.

The LatentMAS lockfile carries a scoped OSV exception in `latent-mesh/LatentMAS/osv-scanner.toml` for `RUSTSEC-2024-0436`. The advisory is informational/unmaintained, comes from transitive `tokenizers` dependency `paste`, and expires on 2026-08-06 for review. Release-image Grype exceptions are separate and must live in `config/release-vulnerability-exceptions.json` with owner, expiry, decision, reason, and compensating controls.

## Procurement Security Package

`config/procurement-security.package.json` is the maintained manifest for enterprise procurement and security review. It uses `mesh.procurement_security_package.v1` and must verify with:

```bash
scripts/verify_procurement_security_package.py --json
```

The manifest covers SSO identity, audit export, retention controls, data boundaries, deployment modes, security answers, support escalation, and known limitations. Passing verification means the repository artifact set is complete and secret-free. It does not replace target-environment evidence for deployed SSO, external audit sink receipts, signed release provenance, or customer-specific support terms.
