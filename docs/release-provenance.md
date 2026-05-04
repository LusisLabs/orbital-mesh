# Release Provenance Packet

`scripts/generate_release_provenance.py` creates the supply-chain record required before a production pilot can claim release readiness.

The packet schema is `mesh.release_provenance.v1`. It records:

- git commit, branch, dirty state, and dirty file list;
- Mesh image tag and digest;
- Docker base images and required `sha256:` digests;
- dependency lockfile hashes;
- Docker and compose build-input hashes;
- policy file hashes and combined policy hash;
- Postgres migration version and migration hashes;
- SBOM path and hash;
- vulnerability scan path and hash;
- build command and builder identity;
- readiness profile and environment.

## Local Generation

Run:

```bash
scripts/generate_release_provenance.py --json
```

Local output usually has `status: incomplete` because developer worktrees are dirty and CI-only artifacts such as image digests, SBOMs, vulnerability scans, and pinned base-image digests are not present.

Write the packet to a file:

```bash
scripts/generate_release_provenance.py --output dist/release-provenance.json
```

## Pilot Completeness Gate

For a pilot release, run with `--require-complete`. The command exits non-zero unless every required field is present:

```bash
scripts/generate_release_provenance.py \
  --require-complete \
  --image-tag "$MESH_STACK_IMAGE" \
  --image-digest "$MESH_IMAGE_DIGEST" \
  --sbom "$MESH_SBOM_PATH" \
  --vulnerability-scan "$MESH_VULNERABILITY_SCAN_PATH" \
  --build-command "$MESH_BUILD_COMMAND" \
  --builder-identity "$MESH_BUILDER_IDENTITY" \
  --base-image-digest "python:3.12-slim-bookworm=sha256:<digest>" \
  --base-image-digest "python:3.11-slim-bookworm=sha256:<digest>" \
  --base-image-digest "rust:1.92-slim-bookworm=sha256:<digest>" \
  --base-image-digest "node:22-bookworm-slim=sha256:<digest>" \
  --base-image-digest "debian:12-slim=sha256:<digest>"
```

`--allow-dirty` exists only for local rehearsals and tests. Do not use it for a signed pilot packet.

## Interpretation

- `status: complete` means the packet is structurally ready for a pilot release review.
- `status: incomplete` means one or more release gates are absent. Missing gates appear under `missing`.
- `packet_sha256` is the hash of the packet payload before the hash field is attached. Use it as the audit pointer in a release record.

The packet does not replace the pilot go/no-go API. The go/no-go packet proves runtime evidence. The release provenance packet proves build and supply-chain evidence. Both must pass before a signed pilot record is valid.
