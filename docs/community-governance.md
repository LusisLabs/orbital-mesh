# Community Governance

`orbital-mesh` can accept community contributions without weakening the commercial and production-safety boundary.

## Contribution Boundary

Community-safe areas:

- fixtures under `fixtures/`;
- documentation under `docs/`;
- deterministic tests under `tests/`;
- read-only investigation tools;
- adapters that default to disabled, mock, or proposal-only certification;
- UI improvements that do not create new mutation paths.

Maintainer-reviewed areas:

- `services/control_plane.py`;
- `control_plane_server.py`;
- `shared/mesh_runtime/contracts.py`;
- `shared/mesh_runtime/schemas/`;
- `services/actuators/`;
- Kubernetes live execution logic;
- operator authorization and audit code;
- state-store migrations.

Rejected by default:

- production credential handling in proposal lanes;
- autonomous actuation without approval, allowlists, rollback metadata, and policy/evaluation pass;
- claims that an unfinished adapter is production-ready;
- broad rewrites of vendored or upstream paths;
- public marketing claims not backed by observed benchmark evidence.

## Governance Model

Roles:

- maintainers own merge, release, schema, and security decisions;
- reviewers can approve scoped code and docs changes;
- contributors can submit issues, fixtures, tests, docs, and proposal adapters;
- security reporters use private disclosure for vulnerabilities.

Release gates:

- `npm --prefix web run lint`;
- `PYTHONPATH=. uvx --with-editable . --with deepagents --with pytest pytest`;
- `RUFF_CACHE_DIR=/tmp/ruff-cache uvx ruff check .`;
- strict mypy command from `AGENTS.md`;
- `scripts/verify_release_cut_list.py --json`;
- live compose and production smokes only when the target environment is available.

## Community Versus Commercial Boundary

Community/local proof includes:

- local fixture runs;
- read-only evidence graph inspection;
- policy simulation;
- mock, read-only, and proposal-only connectors;
- local compose proof with non-production credentials.

Commercial production platform includes:

- authenticated operator identity;
- enterprise auth integration;
- signed release packets;
- private deployment support;
- regulated audit exports;
- production connector certification;
- design-partner support and incident-response operating agreements.

The boundary is capability-based, not arbitrary. Production authority requires operational accountability, security review, audit evidence, and support ownership.

## Issue And PR Shape

Issues should include:

- observed behavior;
- expected behavior;
- environment;
- relevant command output;
- whether live execution, Postgres, OTel, or proposal lanes were enabled.

Pull requests should include:

- scope summary;
- changed authority boundary, if any;
- tests run;
- docs updated when public behavior changes;
- known gaps.

Do not submit production secrets, kubeconfigs, tokens, private incident exports, or customer data.
