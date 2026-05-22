# Hardened Production Arena implementation task list

This is the visible task-list artifact for `hardened-arena.*.v1`. It tracks implementation slices only; it is not target-environment readiness proof and does not claim production readiness.

- [x] Preflight and operating-doc review completed.
- [x] Slice 1 `hardened-arena.profile-registry.v1`: profile registry config, schema, runtime verifier, CLI, tests, and `verify:contracts` wiring.
- [x] Slice 2 `hardened-arena.catalog-ingest.v1`: DHI catalog import, catalog data, schema, verifier, CLI, tests, and no deployment/production-ready claims.
- [x] Slice 3 `hardened-arena.packet-generator.v1`: review-only packet generation, verification, CLI smoke, tests, and ignored/generated output path.
- [x] Slice 4 `hardened-arena.intent-generator.v1`: review-only Helm/Kustomize/Compose/RBAC/NetworkPolicy/secret-reference/cleanup intent generation with no apply/install/secret values/kubeconfig material.
- [x] Slice 5 `hardened-arena.proof-runner.v1`: fail-closed target proof runner and verifier for health, readiness, identity, persistence, feedback, audit, rollback, run export, kill switch, cleanup, and release-packet binding. `target_validated` requires observed checks plus a valid referenced `mesh.hardened_arena.packet.v1` packet.
- [x] Slice 6 `hardened-arena.api-surface.v1`: bounded profiles/catalog/packet create/packet lookup routes, operator identity for stored packet creation, and no deployment/secret/apply route.
- [x] Slice 7 `hardened-arena.meshapp-ui.v1`: Meshapp Build Arena wizard, profile/use/compliance selection, component graph, authority boundaries, blockers, proof checklist, packet generation, and packet review/export copy without deployed-state language.
- [x] Slice 8 `hardened-arena.release-readiness.v1`: readiness exposes profile verifier state and release provenance can reference profile/packet/proof artifacts without upgrading production readiness absent target-specific proof.
- [x] Final validation ladder run after implementation: `git diff --check`, `pnpm run verify:contracts`, `pnpm run test:focused`, `pnpm run lint`, `git status --short --branch`.

Next unfinished slice: none.
