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

`GET /api/pilot/go-no-go` blocks with `release_provenance_complete` until `MESH_RELEASE_PROVENANCE_PATH` points to a readable `mesh.release_provenance.v1` packet with `status: "complete"`, an empty `missing` list, passing embedded release checks, and CI attestation metadata that confirms `sha_matches_git_commit`.

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

The command writes `MESH_RELEASE_PROVENANCE_PATH`, `MESH_BUILD_COMMIT`, and `MESH_BUILD_IMAGE_DIGEST` only after the packet is complete and the optional local image ref matches the packet digest. After deployment, run the same verifier with `--health-url https://<mesh-host>/api/health` to confirm the live control plane reports the bound commit and image digest before capturing `/api/pilot/go-no-go`.

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
  --connector-certification-registry config/connector-certification.registry.json \
  --base-image-digest "python:3.12-slim-bookworm=sha256:<digest>" \
  --base-image-digest "python:3.11-slim-bookworm=sha256:<digest>" \
  --base-image-digest "rust:1.92-slim-bookworm=sha256:<digest>" \
  --base-image-digest "node:22-bookworm-slim=sha256:<digest>" \
  --base-image-digest "debian:12-slim=sha256:<digest>"
```

`--allow-dirty` exists only for local rehearsals and tests. Do not use it for a signed pilot packet.

`--migration-rehearsal` must point at a `mesh.migration_rehearsal.v1` packet verified by `scripts/verify_migration_rehearsal.py`. The proof must match the release packet's latest migration version and combined migration hash, include pre-migration snapshot and post-migration validation refs, and prove rollback was rehearsed. Use `scripts/generate_migration_rehearsal.py` after a real Postgres rehearsal to compute the repo migration version/hash and package the operator-supplied snapshot, rollback, validation, review, and timing evidence.

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

The script runs Syft for a CycloneDX SBOM, runs Grype as the real release-image scanner for vulnerability findings, normalizes both artifacts, binds them to `MESH_IMAGE_DIGEST`, and fails on unaccepted high or critical findings. It must run after image metadata collection so the SBOM and vulnerability scan match the same image digest used by the CI attestation. `scripts/generate_release_assurance_rehearsal_inputs.py` remains only a local contract fixture; release provenance marks those rehearsal artifacts incomplete with `real_release_image_sbom` and `real_release_image_vulnerability_scan`.

Collect release image metadata before generating the CI attestation:

```bash
python3 scripts/collect_release_image_metadata.py \
  --image-tag orbital-mesh:ci \
  --output dist/release-image-metadata.json \
  --github-env "$GITHUB_ENV" \
  --base-image-args dist/base-image-digest.args
```

The collector writes `MESH_IMAGE_DIGEST` and base-image digest args for the attestation generator. It prefers pushed repo digests when present and falls back to the local Docker image id for unpushed CI builds; signed pilot releases should still use the published image digest.

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

The CI attestation artifact must use `mesh.ci_attestation.v1`, include a matching `attestation_sha256`, identify `provider: "github-actions"`, include non-empty `workflow`, `job`, `run_id`, and `sha` metadata, bind `sha` to the release packet's git commit, and show passed `python-test`, `web`, and `docker-build` checks. Release provenance ignores attested image digest, build command, and base-image digest fields unless the attestation is valid for the same commit.

## Policy Lifecycle Hashes

`config/policy-lifecycle.manifest.json` records owner, lifecycle state, risk tier, effective window, review expiry, and rollback reference for every JSON policy in `policies/`.

`GET /api/policy/lifecycle` returns `mesh.policy_lifecycle.v1` with every policy file hash, the combined policy hash, manifest hash, coverage checks, and an HMAC signature when `MESH_POLICY_SIGNING_KEY` is supplied. Staging and pilot readiness include `policy_lifecycle_signed`; a missing signing key or manifest/policy mismatch blocks readiness.

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
  --artifacts-json .mesh-runtime-state/artifacts.json \
  --proof-manifest dist/mesh-brain-artifact-upload-proof.json \
  --require-upload-proof \
  --json
```

This verifier checks that every Mesh Brain production artifact record uses a durable object-storage URI, keeps immutable production metadata, and has matching upload proof for hash and byte count.
