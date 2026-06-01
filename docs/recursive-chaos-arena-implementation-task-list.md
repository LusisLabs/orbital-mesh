# Recursive Chaos Arena implementation task list

This tracks implementation slices for `mesh.recursive_chaos.*.v1`. It is not target-environment readiness proof and does not claim production autonomy.

- [x] Slice 1 `recursive-chaos.profile-registry.v1`: 16 domain arena profiles, schema, verifier, CLI, tests, and `verify:contracts` wiring.
- [x] Slice 2 `recursive-chaos.packet-contracts.v1`: experiment manifest, cycle packet, ghost recovery packet, learning packet, and evidence bundle schemas, dataclasses, validators, and builder helpers.
- [x] Slice 3 `recursive-chaos.catalog-session.v1`: plan-only catalog runner that selects existing chaos portfolio experiments, writes sealed packet bundles, and blocks production/Hetzner mutation unless execution is explicitly allowed by safety class.
- [x] Slice 4 `recursive-chaos.compose-integration.v1`: compose-native chaos sessions now emit recursive chaos manifests and packet bundles beside existing events and summaries.
- [x] Slice 5 `recursive-chaos.public-utility-docs.v1`: README and compose-stack docs describe the verifier, runner, packet outputs, safety behavior, and environment controls.
- [x] Slice 6 `recursive-chaos.control-plane-run.v1`: `/api/recursive-chaos/profiles` exposes the 16-profile registry and verification packet; `/api/recursive-chaos/sessions` requires operator identity, creates a Mesh run, records a contract-valid `no_action` decision, registers emitted packet files as run artifacts, and stores the MeshBrain/MeshModel advisory packet as sealed-source, recommend-only, and training-blocked.
- [x] Slice 7 `recursive-chaos.operator-panel.v1`: the active `meshapp/frontend` control-plane view can read the arena profile matrix and launch a one-cycle packet run through the authenticated control-plane API.
- [x] Final validation ladder after implementation: `git diff --check`, `pnpm run verify:contracts`, `pnpm run test:focused`, `pnpm run lint`, `git status --short --branch`.

Validated locally on 2026-06-01:

- `git diff --check`
- `pnpm run verify:contracts`
- `pnpm run lint:fast`
- `PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uv run --with-editable . python -m unittest tests.test_recursive_chaos_contracts tests.test_recursive_chaos_profiles tests.test_recursive_chaos_arena_session tests.test_recursive_chaos_control_plane tests.test_compose_chaos_session`
- `pnpm --dir meshapp/frontend run typecheck`
- `pnpm --dir meshapp/frontend run test`
- `pnpm run test:focused`
- `COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack pnpm@10.24.0 run lint`

Next unfinished slice: none.
