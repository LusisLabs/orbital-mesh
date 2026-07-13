# Release Provenance Packet

`scripts/generate_release_provenance.py` creates the supply-chain record required before a production pilot can claim release readiness.

The packet schema is `mesh.release_provenance.v1`. It records:

- git commit, branch, dirty state, and dirty file list;
- Mesh image tag and digest;
- Docker base images and required `sha256:` digests;
- dependency lockfile hashes;
- Docker and compose build-input hashes;
- policy file hashes, combined policy hash, lifecycle manifest hash, and signed policy hash packet;
- connector certification registry status and matrix;
- Postgres migration version, migration hashes, and migration rehearsal proof status;
- SBOM path, hash, and normalized CycloneDX validity;
- vulnerability scan path, hash, scanner identity, and blocking finding count;
- CI attestation path, hash, and provider run metadata;
- build command and builder identity;
- readiness profile and environment.

## Local Generation

Run:

```bash
scripts/generate_release_provenance.py --json
```

Local output usually has `status: incomplete` because developer worktrees are dirty and CI-only artifacts such as image digests, SBOMs, vulnerability scans, CI attestations, and pinned base-image digests are not present.

Write the packet to a file:

```bash
scripts/generate_release_provenance.py --output dist/release-provenance.json
```

For pilot and expansion readiness, mount the completed packet where the running control plane can read it and set:

```bash
MESH_RELEASE_PROVENANCE_PATH=dist/release-provenance.json
```

`GET /api/pilot/go-no-go` blocks with `release_provenance_complete` until `MESH_RELEASE_PROVENANCE_PATH` points to a readable `mesh.release_provenance.v1` packet with `status: "complete"`, an empty `missing` list, passing embedded release checks, and CI attestation metadata that confirms both `sha_matches_git_commit` and `image_digest_match`.

For pilot and expansion profiles, the running control plane also binds the packet to the deployed runtime. `MESH_BUILD_COMMIT` must be the exact git commit in the packet, and `MESH_BUILD_IMAGE_DIGEST` must be the exact release image digest in the packet. Missing packet or runtime metadata, or mismatched runtime metadata, keeps `release_provenance_complete` blocked with `release_git_commit`, `release_image_digest`, `runtime_build_commit`, `runtime_build_commit_match`, `runtime_image_digest`, or `runtime_image_digest_match`.

Generate the runtime env file from the completed packet instead of copying values manually:

```bash
scripts/verify_release_runtime_binding.py \
  --release-provenance dist/release-provenance.json \
  --runtime-release-provenance-path /app/.mesh-runtime-state/release-provenance.json \
  --image-ref "$MESH_IMAGE" \
  --env-output dist/release-runtime.env \
  --json
```

The command writes `MESH_RELEASE_PROVENANCE_PATH`, `MESH_BUILD_COMMIT`, and `MESH_BUILD_IMAGE_DIGEST` only after the packet is complete and the env write has binding evidence. When `--image-ref` is supplied and the local image digest matches the packet, it also writes `MESH_IMAGE` and `MESH_STACK_IMAGE` so compose restarts the verified image. Supply `--image-ref` before deployment so the local image must match the packet digest, or `--health-url` after deployment so the live control plane must report the packet commit and image digest. `--allow-unverified-env-output` exists only for external deployment orchestrators that verify image identity elsewhere; do not use it as pilot-release evidence. After deployment, run the same verifier with `--health-url https://<mesh-host>/api/health` to confirm the live control plane reports the bound commit and image digest before capturing `/api/pilot/go-no-go`. For `lusislabs.com`, use the manual `Deploy Lusis Labs Preview` workflow with `deploy_mode=release-image` and the successful Release Image Handoff run ID. The source-preview deployment is useful for product inspection, but it is not release-image-bound evidence.

Run the final pilot-clearance audit only after deployment binding is in place:

```bash
scripts/verify_pilot_clearance.py \
  --base-url https://<mesh-host> \
  --timeout-seconds 30 \
  --expected-head "$(git rev-parse HEAD)" \
  --json
```

The audit emits `mesh.pilot_clearance_audit.v1` and fails unless health, pilot readiness, go/no-go evidence, complete release provenance, runtime commit/image-digest binding, and the live `/api/health.commit` to `--expected-head` binding all pass together. Omit `--expected-head` only for explicit historical release-bound audits that are not current-head pilot clearance.

To prove a live runtime is booted but intentionally blocked on missing pilot evidence, use the blocked-state mode:

```bash
scripts/verify_pilot_clearance.py \
  --base-url https://<mesh-host> \
  --timeout-seconds 30 \
  --expect-blocked \
  --json
```

This mode verifies `/api/health`, `/api/readiness`, and `/api/pilot/go-no-go` are reachable and explicitly blocked on the expected evidence/config gaps with no unexpected extra blocker names. It also fails if expected observed proofs such as denied-action evidence regress. Mesh Brain kernel, canary, and rollback proofs remain expected missing evidence until a live canary lane produces them. Its JSON output includes `prompt_to_artifact_checklist`, readiness blocker details, go/no-go missing-evidence details, and observed-proof details for the required state slices, env vars, evidence paths, remediation, and source endpoints. It is not a release-clearance signal.

## Full E2E Claim Gate

`pnpm run lint` proves the local contracts, focused tests, product browser E2E, release-cut list, and security-readiness gates. It does not prove that a production-ready frontend/backend claim is current-head and live-runtime bound. Use the E2E claim gate after downloading the artifact bundle that produced the bound runtime:

```bash
pnpm run verify:e2e-claim \
  --artifact-root dist/release-image-handoff-current \
  --health-url https://<mesh-host>/api/health \
  --pilot-base-url https://<mesh-host> \
  --live-proof-dir .mesh-runtime-state/live-proof-current \
  --expected-head "$(git rev-parse HEAD)" \
  --json
```

`--artifact-root` accepts either the CI release artifact download layout or the release-image handoff download layout. For live runtime checks, prefer the release-image handoff artifact because it is the signed bundle that produced the running image digest. The gate verifies the release artifact bundle, runtime release binding, pilot clearance, and production-autonomy proof aggregate as one state slice. It fails closed when any artifact path, live runtime binding, pilot endpoint, or `.mesh-runtime-state/live-proof-current/` proof packet is absent. Do not use production-ready or flawless E2E language for the current head until this gate passes with explicit artifact inputs.

## Local CI/CD Lane

The repo-owned local lane is `scripts/local_ci.py`. It avoids GitHub Actions spend and gives operators a repeatable local preflight, but it deliberately does not create GitHub-backed release authority.

Common commands:

```bash
pnpm run ci:fast
pnpm run ci:local
pnpm run ci:release
```

`pnpm run ci:fast` delegates to `lint:fast`. `pnpm run ci:local` runs the heavy root gate and `git diff --check`, then writes a `mesh.local_ci_manifest.v1` manifest under `dist/local-ci/<head>/manifest.json`. `pnpm run ci:release` adds the release rehearsal path: Docker image build, local runtime health smoke, release-image metadata, optional Postgres migration rehearsal when `MESH_MIGRATION_REHEARSAL_DATABASE_URL` is set, optional Syft/Grype release-image assurance when those binaries are installed, local CI attestation, and local release-provenance rehearsal.

The local manifest records:

- exact git head and branch;
- every command, status, duration, and log path;
- image tag and Docker/scanner availability;
- skipped optional evidence with reasons;
- explicit authority boundaries.

The local attestation is `provider=local`. That is intentional. Pilot and production release gates still require GitHub Actions-backed `mesh.ci_attestation.v1` evidence, complete release artifact bundles, runtime binding, pilot clearance, and live proof packets. Local CI is evidence for developer/operator readiness; it is not a shortcut around `scripts/verify_release_artifact_bundle.py` or `pnpm run verify:e2e-claim`.

Use `act` only as a compatibility check for the GitHub workflow YAML:

```bash
pnpm run ci:act
```

Use Skaffold only for a later Kubernetes deployment loop. It is not the source of truth for this repo's contracts, provenance, security, and proof gates.

## Pilot Completeness Gate

For a pilot release, run with `--require-complete`. The command exits non-zero unless every required field is present:

```bash
scripts/generate_release_provenance.py \
  --require-complete \
  --image-tag "$MESH_STACK_IMAGE" \
  --image-digest "$MESH_IMAGE_DIGEST" \
  --sbom "$MESH_SBOM_PATH" \
  --vulnerability-scan "$MESH_VULNERABILITY_SCAN_PATH" \
  --ci-attestation "$MESH_CI_ATTESTATION_PATH" \
  --migration-rehearsal "$MESH_MIGRATION_REHEARSAL_PATH" \
  --build-command "$MESH_BUILD_COMMAND" \
  --builder-identity "$MESH_BUILDER_IDENTITY" \
  --policy-signing-key "$MESH_POLICY_SIGNING_KEY" \
  --policy-signing-key-path "$MESH_POLICY_SIGNING_KEY_PATH" \
  --connector-certification-registry config/connector-certification.registry.json \
  --base-image-digest "python:3.12-slim-bookworm=sha256:<digest>" \
  --base-image-digest "python:3.11-slim-bookworm=sha256:<digest>" \
  --base-image-digest "rust:1.92-slim-bookworm=sha256:<digest>" \
  --base-image-digest "node:22-bookworm-slim=sha256:<digest>" \
  --base-image-digest "debian:12-slim=sha256:<digest>"
```

`--allow-dirty` exists only for local rehearsals and tests. Do not use it for a signed pilot packet.

`--migration-rehearsal` must point at a `mesh.migration_rehearsal.v1` packet verified by `scripts/verify_migration_rehearsal.py`. The proof must match the release packet's latest migration version and combined migration hash, include pre-migration snapshot and post-migration validation refs, and prove rollback was rehearsed.

Use `scripts/run_postgres_migration_rehearsal.py` against a disposable Postgres database when the operator can run the migration rehearsal directly:

```bash
MESH_MIGRATION_REHEARSAL_DATABASE_URL=postgresql://mesh:mesh@127.0.0.1:5432/mesh \
  python3 scripts/run_postgres_migration_rehearsal.py \
    --output dist/migration-rehearsal.json \
    --operator-id "$MESH_OPERATOR_ID" \
    --environment "$MESH_ENVIRONMENT" \
    --json
```

The runner refuses non-empty public schemas by default, applies every SQL file under `migrations/postgres` in one transaction, records pre- and post-migration schema hashes, rolls the transaction back, and verifies the generated proof. Use `--allow-destructive-statements` only after reviewing destructive migration SQL for the target release. Use `scripts/generate_migration_rehearsal.py` only when an external operator-controlled rehearsal already produced snapshot, rollback, validation, review, and timing evidence that must be packaged into the same proof schema.

When `MESH_MEMORY_GRAPH_BACKEND=helix` is used with the Postgres backend, migration `005_helix_projection_outbox.sql` must be included in the schema requirements. This migration creates the `helix_memory_projection_outbox` table required for the HelixDB projection outbox pattern.

The SBOM artifact must be JSON with `bomFormat: "CycloneDX"`. The vulnerability scan artifact must be normalized JSON with a `scanner` string and a `findings`, `vulnerabilities`, or `results` array. Any unaccepted `high` or `critical` severity finding keeps `vulnerability_scan_path` incomplete with `no_high_or_critical_findings`.

`config/release-vulnerability-exceptions.json` is the only in-repo release-image exception policy. It must use `mesh.release_vulnerability_exceptions.v1`; each accepted finding needs an owner, expiry, decision, reason, and compensating control. The normalizer annotates matching findings with `accepted_exception` metadata and still records the total `blocking_finding_count`. Expired, ownerless, or unmatched high/critical findings remain blocking.

Normalize raw CI scanner output before generating the release packet:

```bash
python3 scripts/normalize_release_assurance_artifacts.py \
  --sbom-input "$MESH_RAW_SBOM_PATH" \
  --scan-input "$MESH_RAW_VULNERABILITY_SCAN_PATH" \
  --scanner "$MESH_VULNERABILITY_SCANNER" \
  --image-digest "$MESH_IMAGE_DIGEST" \
  --output-dir dist/release-assurance \
  --require-scan \
  --fail-on-blocking \
  --exception-policy config/release-vulnerability-exceptions.json
```

Then set `MESH_SBOM_PATH=dist/release-assurance/sbom.cdx.json` and `MESH_VULNERABILITY_SCAN_PATH=dist/release-assurance/vulnerability-scan.json` for `scripts/generate_release_provenance.py`. The normalizer accepts CycloneDX SBOM JSON plus OSV, npm audit, Grype, or already-normalized scan JSON. Pilot provenance rejects SBOM and vulnerability scan artifacts unless their recorded image digest matches `MESH_IMAGE_DIGEST` with `release_image_digest_match`.

CI generates `release-assurance-artifacts` from the built release image with pinned and SHA-256-verified Syft and Grype packages:

```bash
python3 scripts/generate_release_image_assurance.py \
  --image-tag orbital-mesh:ci \
  --image-digest "$MESH_IMAGE_DIGEST" \
  --raw-output-dir dist/release-assurance-raw \
  --output-dir dist/release-assurance \
  --exception-policy config/release-vulnerability-exceptions.json
```

The script first retains complete raw Syft JSON, collects evidence from the
known Deno binary paths inside an isolated container, and passes both through
`scripts/normalize_syft_binary_identity.py`. That derivation applies only to the
exact Syft `1.44.0` identity defect in [issue 5057](https://github.com/anchore/syft/issues/5057): it requires the classifier artifact, paths, installed Python
packages, executed versions, binary SHA-256 values, sizes, and Python `RECORD`
entries to match the reviewed profile. It then removes exactly the synthetic
`deno@0.76.0` binary-classifier artifact and its relationships, preserves all
other Syft artifacts, and emits a hash-bound
`mesh.syft_binary_identity_correction.v1` proof. Any mismatch fails closed. The
raw Syft file remains an artifact; the evidence-derived Syft file is converted
to CycloneDX and scanned by Grype. This is a scanner-identity correction, not a
VEX statement or vulnerability exception.

The generator uses Grype as the real release-image scanner, normalizes the
resulting CycloneDX and Grype artifacts, binds them to `MESH_IMAGE_DIGEST`, and
fails on unaccepted high or critical findings.
It must run after image metadata collection so the SBOM, vulnerability scan,
and CI attestation match the same image digest.
`scripts/generate_release_assurance_rehearsal_inputs.py` remains only a local
contract fixture; release provenance marks those rehearsal artifacts incomplete
with `real_release_image_sbom` and `real_release_image_vulnerability_scan`.

## Repo-Patch Three-Role Image Release

State slice: `mesh.repo_patch_service_image_bundle.v1`.

`.github/workflows/repo-patch-service-image-release.yml` is the only automated
publication path for the repo-patch control-plane, authority, and verifier role
bundle. On `main` push or explicit dispatch it:

1. checks out `github.sha`, requires the exact clean source state, installs the
   frozen pnpm workspace, and runs the heavy root lint gate;
2. builds and locally scans every role before GHCR authentication, requiring
   zero unaccepted high or critical findings;
3. requires the verifier sandbox digest, key id, and public key from repository
   variables, without receiving any private signing key;
4. publishes commit-only tags, resolves registry manifest digests, pulls and
   rescans the immutable references, and rechecks zero unaccepted findings;
5. creates GitHub OIDC provenance attestations with a full-SHA-pinned action,
   generates exact-commit Mesh CI attestations, and generates the three-role
   service-image bundle; and
6. re-resolves every registry digest and verifies the bundle against the exact
   commit, role references, digests, and external verifier policy.

The job uploads bounded evidence even after a failure. It does not deploy a
runtime. A failed prepublication scan is evidence that the release was blocked,
not a releasable or attested image bundle.

`scripts/generate_release_provenance.py` requires the `mesh.ci_attestation.v1` image digest to match the release packet image digest. A packet that supplies a local or explicit image digest while reusing a CI attestation for a different image remains incomplete with `ci_attestation` missing.

## Downloaded CI Artifact Bundle

After the `CI` workflow completes, download the release artifacts and verify
them as one bundle before any deployment handoff:

```bash
gh run download <run-id> \
  --repo LusisLabs/orbital-mesh \
  --dir dist/ci-release-artifacts

scripts/verify_release_artifact_bundle.py \
  --artifact-root dist/ci-release-artifacts \
  --expected-head "$(git rev-parse HEAD)" \
  --json
```

The verifier checks the downloaded `ci-attestation`, `release-provenance-draft`,
`release-assurance-artifacts`, migration rehearsal, SBOM, vulnerability scan,
and release-image metadata as one state slice. It fails unless the release
packet is complete, every embedded check passes, the CI attestation is
GitHub-Actions backed, the attestation commit and image digest match the
release packet, and the downloaded SBOM, scan, migration rehearsal, and
attestation files match the hashes recorded in the release packet.

To produce deployment runtime env from the verified bundle, add either a local
image binding before deployment or a live health binding after deployment:

```bash
scripts/verify_release_artifact_bundle.py \
  --artifact-root dist/ci-release-artifacts \
  --expected-head "$(git rev-parse HEAD)" \
  --runtime-release-provenance-path /app/.mesh-runtime-state/release-provenance.json \
  --image-ref "$MESH_IMAGE" \
  --env-output dist/release-runtime.env \
  --json
```

or:

```bash
scripts/verify_release_artifact_bundle.py \
  --artifact-root dist/ci-release-artifacts \
  --expected-head "$(git rev-parse HEAD)" \
  --runtime-release-provenance-path /app/.mesh-runtime-state/release-provenance.json \
  --health-url https://<mesh-host>/api/health \
  --env-output dist/release-runtime.env \
  --json
```

`--allow-unverified-env-output` exists only for external deployment systems that
verify image identity outside this repository. Do not use it as pilot-release
evidence. The generated env is valid only together with the verified release
packet and image or health binding.

Collect release image metadata before generating the CI attestation:

```bash
python3 scripts/collect_release_image_metadata.py \
  --image-tag orbital-mesh:ci \
  --output dist/release-image-metadata.json \
  --github-env "$GITHUB_ENV" \
  --base-image-args dist/base-image-digest.args
```

The collector writes `MESH_IMAGE_DIGEST` and base-image digest args for the attestation generator. `scripts/generate_release_provenance.py` accepts `MESH_IMAGE_DIGEST`, `MESH_STACK_IMAGE_DIGEST`, or the runtime-binding alias `MESH_BUILD_IMAGE_DIGEST` when `--image-digest` is not supplied. It prefers pushed repo digests when present and falls back to the local Docker image id for unpushed CI builds; signed pilot releases should still use the published image digest.

## Release Image Handoff

The current CI workflow builds and attests the image, but it does not upload a runnable private image artifact. That is intentional: uploading the built image exports private repo contents into GitHub Actions artifact storage.

When GitHub-hosted runners fail before job steps start, use the manual `Self-hosted Release Assurance` workflow. It runs on the `self-hosted` `lusislabs-preview` runner, avoids marketplace action downloads by checking out with `git`, cleans the checkout before evidence generation, installs SHA-256-verified Node `v22.22.3`, enables `corepack pnpm`, installs workspace dependencies with the frozen lockfile, executes the root `pnpm run lint` gate, builds the release candidate image, performs the Postgres migration rehearsal, generates Syft/Grype release assurance artifacts, emits `mesh.ci_attestation.v1`, and preserves the evidence under `/var/tmp/orbital-mesh-release-assurance/<run>-<attempt>` on the runner with SHA256s in the job summary. This lane is still GitHub Actions evidence, but it is runner-provenance-specific; hosted CI remains the default broad compatibility signal when available.

Use `.github/workflows/release-image-handoff.yml` only after operator approval. The workflow is `workflow_dispatch` only, requires the exact `confirm_export=EXPORT_RELEASE_IMAGE` input, limits artifact retention to `1` through `7` days, runs Python, web reference, meshapp operator, release-cut, and security gates, builds the image, records release image metadata, rehearses Postgres migrations, generates SBOM and vulnerability scan artifacts, creates a CI attestation and release provenance draft, saves the runnable image with `docker save`, compresses it with `gzip -n`, and writes `scripts/generate_release_image_handoff.py` output as `mesh.release_image_handoff.v1`. Release provenance hashes the root `pnpm-lock.yaml` because the production image now serves the meshapp static export through the workspace lock discipline.

The uploaded artifact includes:

- `release-image-handoff/orbital-mesh-handoff-image.tar.gz`;
- `release-image-handoff/release-image-handoff.json`;
- `release-image-metadata.json`;
- `ci-attestation.json`;
- `migration-rehearsal.json`;
- `release-provenance-draft.json`;
- normalized and raw release assurance artifacts.

After downloading the handoff artifact, load and verify the image before deployment:

```bash
scripts/verify_release_image_handoff.py \
  --manifest release-image-handoff/release-image-handoff.json \
  --image-archive release-image-handoff/orbital-mesh-handoff-image.tar.gz \
  --artifact-root . \
  --require-artifacts \
  --json

docker load -i release-image-handoff/orbital-mesh-handoff-image.tar.gz

scripts/verify_release_image_handoff.py \
  --manifest release-image-handoff/release-image-handoff.json \
  --image-archive release-image-handoff/orbital-mesh-handoff-image.tar.gz \
  --artifact-root . \
  --require-artifacts \
  --runtime-release-provenance-path /app/.mesh-runtime-state/release-provenance.json \
  --image-ref "$HANDOFF_IMAGE_TAG" \
  --complete-release-provenance dist/release-provenance-complete.json \
  --env-output dist/release-runtime.env \
  --json
```

Generate the final `mesh.release_provenance.v1` packet from the handoff workflow's CI attestation, SBOM, vulnerability scan, release image digest, and the operator-controlled migration rehearsal proof before writing `dist/release-runtime.env`. The second handoff verification fails unless the loaded Docker image digest, final complete release packet commit, and final complete release packet image digest all match the handoff manifest. Then deploy the loaded image with the generated runtime env and rerun:

The generated runtime env includes `MESH_IMAGE` and `MESH_STACK_IMAGE` set to the verified `--image-ref`, plus `MESH_RELEASE_PROVENANCE_PATH`, `MESH_BUILD_COMMIT`, and `MESH_BUILD_IMAGE_DIGEST`. Use that env file as a unit with the loaded image; do not copy only the commit and digest variables into a default-image deployment.

```bash
scripts/verify_release_runtime_binding.py \
  --release-provenance dist/release-provenance-complete.json \
  --runtime-release-provenance-path /app/.mesh-runtime-state/release-provenance.json \
  --health-url https://<mesh-host>/api/health \
  --json
```

`scripts/verify_release_image_handoff.py` checks the handoff manifest hash, explicit operator confirmation marker, archive byte count and SHA-256, referenced JSON artifacts including the migration rehearsal proof, CI attestation commit and image digest, and release provenance commit and image digest. With `--require-artifacts`, `--image-ref`, `--complete-release-provenance`, and `--env-output`, it also verifies the downloaded artifact set, loaded image, and final complete release packet before writing runtime binding env. Do not treat the handoff manifest as pilot clearance. It is only proof that a runnable image artifact was exported under explicit operator confirmation.

Generate the CI attestation artifact inside the CI job that owns the release image:

```bash
python3 scripts/generate_ci_attestation.py \
  --output dist/ci-attestation.json \
  --require-github-actions \
  --check python-test \
  --check web \
  --check-status "docker-build=passed" \
  --image-tag "$MESH_STACK_IMAGE" \
  --image-digest "$MESH_IMAGE_DIGEST" \
  --base-image-digest "python:3.12-slim-bookworm=sha256:<digest>" \
  --base-image-digest "python:3.11-slim-bookworm=sha256:<digest>" \
  --base-image-digest "rust:1.92-slim-bookworm=sha256:<digest>" \
  --base-image-digest "node:22-bookworm-slim=sha256:<digest>" \
  --base-image-digest "debian:12-slim=sha256:<digest>" \
  --build-command "$MESH_BUILD_COMMAND"
```

Use `--check` only for checks that passed. Use `--check-status NAME=failed` when the release-image job reaches the attestation step but a required gate fails. The live CI workflow uploads that failed-status attestation for review, then fails the job; it is evidence of the run, not pilot-signing proof.

Pass `dist/ci-attestation.json` back into the release provenance command with `--ci-attestation "$MESH_CI_ATTESTATION_PATH"`. When the release command does not receive explicit `--image-digest`, `--build-command`, or `--base-image-digest` values, it uses the attested `image.digest`, `build.command`, and `build.base_images[]` fields from `mesh.ci_attestation.v1`.

The CI attestation artifact must use `mesh.ci_attestation.v1`, include a matching `attestation_sha256`, identify `provider: "github-actions"`, include non-empty `workflow`, `job`, `run_id`, and `sha` metadata, bind `sha` to the release packet's git commit, and show passed `python-test`, `web`, and `docker-build` checks. Release provenance validates that the attested image digest matches the release packet's image digest; a mismatch marks the packet incomplete with `image_digest_match` missing.

## Policy Lifecycle Hashes

`config/policy-lifecycle.manifest.json` records owner, lifecycle state, risk tier, effective window, review expiry, and rollback reference for every JSON policy in `policies/`.

`GET /api/policy/lifecycle` returns `mesh.policy_lifecycle.v1` with every policy file hash, the combined policy hash, manifest hash, coverage checks, and an HMAC signature when `MESH_POLICY_SIGNING_KEY` or `MESH_POLICY_SIGNING_KEY_PATH` is supplied. Staging and pilot readiness include `policy_lifecycle_signed`; a missing signing key or manifest/policy mismatch blocks readiness. `scripts/generate_release_provenance.py` follows the same precedence: raw `MESH_POLICY_SIGNING_KEY` first, then the key file path.

## Connector Certification Matrix

`config/connector-certification.registry.json` records the maximum certified state for each connector plus required tier, authority posture, credential policy, credential boundary, degraded behavior, allowed scopes, evidence refs, and blockers.

`GET /api/connectors/certification` returns `mesh.connector_certification.v1`. Release provenance embeds the same registry-backed matrix under `connectors.certification` and requires `connector_certification_registry` before a pilot packet can be complete.

`GET /api/deployment/compatibility` returns `mesh.deployment_compatibility.v1`. Release provenance embeds the same registry-backed matrix under `deployment.compatibility` and requires `deployment_compatibility_registry` before a pilot packet can be complete. The default registry keeps ECS/Fargate as the single next validated non-Kubernetes target, not as a validated claim.

## Interpretation

- `status: complete` means the packet is structurally ready for a pilot release review.
- `status: incomplete` means one or more release gates are absent. Missing gates appear under `missing`.
- `packet_sha256` is the hash of the packet payload before the hash field is attached. Use it as the audit pointer in a release record.

The packet does not replace the pilot go/no-go API. The go/no-go packet proves runtime evidence. The release provenance packet proves build and supply-chain evidence. Both must pass before a signed pilot record is valid.

Mesh Brain artifact durability is a separate rollout gate. After the model-kernel, live-serving smoke, quality-training, rollback, or backend artifacts are registered in Mesh, run:

```bash
scripts/verify_mesh_brain_artifact_registry.py \
  --artifacts-json "$MESH_BRAIN_ARTIFACT_REGISTRY_PATH" \
  --proof-manifest "$MESH_BRAIN_ARTIFACT_UPLOAD_PROOF_PATH" \
  --require-upload-proof \
  --json
```

This verifier checks that every Mesh Brain production artifact record uses a durable object-storage URI, keeps immutable production metadata, and has matching upload proof for hash and byte count. Pilot readiness and go/no-go require `MESH_BRAIN_ARTIFACT_REGISTRY_PATH` and `MESH_BRAIN_ARTIFACT_UPLOAD_PROOF_PATH` to point at the verified registry export and proof manifest.
