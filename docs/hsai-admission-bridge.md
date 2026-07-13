# Lusis Mesh / HSAI Admission Bridge

State slice: `mesh.hsai_admission_bridge.v1`.

## Boundary

This is a narrow bridge, not a repository merge. Lusis Mesh remains the
product/control-plane shell. HSAI remains the evidence/admission engine.
The HSAI repository context is
`/Users/shaanp/Documents/GitHub/composed-zk-benchmark-os`.

The first bridged action path is `repo_patch_service` with action
`investigate_and_patch`. Kubernetes rollback and feature-flag execution are
outside this initial patch.

This bridge does not claim production-ready certifying-agent control. It gates
one repo-patch execution path locally and emits audit metadata. Production
certifying-agent control still requires a real target action path enforced
end-to-end in its target environment.

## Contracts

The bridge and local execution-authority layer add schema-backed contracts under
`shared/mesh_runtime/schemas/`:

- `mesh.hsai_admission_request.v1`
- `mesh.hsai_admission_request.v2`
- `mesh.hsai_admission_decision.v1`
- `mesh.combined_proof_packet.v1`
- `mesh.repo_patch_authority_request.v1`
- `mesh.repo_patch_authority_response.v1`
- `mesh.repo_patch_execution_permit.v1`

Canonical bridge fixtures live under `fixtures/hsai_bridge/`:

- `golden_allow_request.json`
- `golden_allow_decision.json`
- `golden_deny_request.json`
- `golden_deny_decision.json`
- `formal_backend_notrun_bundle/gateway-formal-backend-run/*`

The allow fixture preserves accepted claims and explicit nonclaims. The denial
fixture preserves the HSAI reason code `missing_explicit_nonclaims`. These
fixtures are the shared request / decision contract; Mesh and HSAI should not
independently invent compatible-looking payloads.

The formal-backend bundle fixture is a committed conformance bundle for the
current HSAI `phase-276-hsai-gateway-formal-backend-run-inert-artifact-metadata`
contract. Mesh verifies the declared file set, SHA-256 sidecars, schema
versions, `NotRun` statuses, redaction report, and required nonclaims before it
can be bound into admission metadata.

Mesh builds the admission request from the repo-patch decision, evaluation
record, policy id, actor context, proposal digest, candidate digest, evidence
packet digest, attestation refs, requested claims, and explicit nonclaims.

The HSAI-compatible adapter must return a decision with matching request,
Mesh run id, Mesh action id, action kind, candidate, policy, nonclaim, and
decision digests. Malformed responses, unavailable adapters, digest drift,
run/action replay, policy mismatch, and missing nonclaims fail closed.

All bridge digests use canonical JSON with sorted keys and compact separators.
Schema versions fail closed for requests, HSAI decisions, combined proof packets,
and the execution context attached to an allowed repo-patch decision.

## Execution Rule

`OrchestratorService` performs an early fail-closed eligibility check, then asks
the authority service for non-mutating preflight evidence. It invokes the HSAI
bridge with a `mesh.hsai_admission_request.v2` candidate bound to that evidence.
Execution proceeds only when:

- HSAI decision is `allow`;
- Mesh evaluation passed;
- Mesh final recommendation is `execute`;
- the decision is bound to the current Mesh run id;
- the decision is bound to the current Mesh action id;
- the decision is bound to the expected candidate digest;
- the decision is bound to the expected policy id;
- required nonclaims are preserved;
- request, decision, proof packet, and execution-context schema versions are
  supported.

If either side blocks, the repo patch is not executed and the execution record
contains a `combined_proof_packet` in `external_refs`. Successful execution also
contains the packet with executor receipt digest and action result metadata.
Existing run export packages include execution `external_refs`, so the combined
packet is exportable through the current run export path.

Goose and Hermes are protocol-level review-only for this action: their result
cannot carry a permit or modify final parameters, and their adapters cannot
construct or import `RepoPatchAdapter`. This does not isolate a same-UID CLI
subprocess from the orchestrator client's mounted signing key. The closed-beta
overlay therefore disables Goose, Hermes, and Evo subprocess commands and uses
only the deterministic native review adapter. CLI-backed review is not beta
eligible until it runs under a separate OS identity with no key or authority
socket access.

The out-of-process authority independently authenticates the client signature
and kernel peer credentials, recomputes disposable-worktree preflight, invokes
an identity-pinned authority-eligible HSAI adapter, compares the substantive
gate result, and only then creates its internal single-consumption
`mesh.repo_patch_execution_permit.v1`. Shell-form verification is rejected;
tests execute exact allowlisted argv vectors with executable-digest binding and
without `/bin/sh`.

`services.actuators.repo_patch.RepoPatchAdapter` remains self-enforcing, but the
authority service is the only runtime module permitted to import or construct
it. Its permit, ledger, backup, and target-promotion details stay inside the
authority process. A terminal execution outcome is replayed for the same
idempotency key. A dispatched lifecycle first reconciles a binding-validated
committed or aborted permit result; only a dispatched request without a durable
terminal permit outcome is recorded as unknown and not automatically repeated.

The authority keeps the verified detached worktree open through authorization
and atomically promotes those exact verified bytes; it does not ask the actuator
to apply a second patch. Its append-only CAS lifecycle is issue, lease, dispatch,
and terminal. An expired pre-dispatch lease can be reclaimed with a fresh fence.
A crash after dispatch reconciles an exact terminal permit result when one
exists. Otherwise it becomes `unknown/recovery-required` and cannot silently
promote again.

## Proof Packet Invariants

Combined proof packets preserve enforced nonclaims and must not promote those
nonclaims into accepted claims. Blocked packets cannot include an executor
receipt. Executed and failed packets must include one. The exported packet
contains run id, action id, policy id, HSAI request / decision / candidate
digests, nonclaims, HSAI status, Mesh policy status, and action execution
metadata. Export metadata asserts the state slice, canonical digest algorithm,
schema versions, replay protection, and inclusion in execution `external_refs`.

## Adapter

Default local mode uses a deterministic HSAI-compatible metadata adapter. A real
subprocess bridge can be configured with:

```bash
MESH_HSAI_ADMISSION_COMMAND="<command reading request JSON from stdin>"
MESH_HSAI_ADMISSION_TIMEOUT_SECONDS=30
```

The subprocess must return `mesh.hsai_admission_decision.v1` JSON on stdout.
The local metadata adapter and the shipped `scripts/hsai_admission_adapter.py`
subprocess are not authority-eligible and cannot produce a mutable repo-patch
permit. Ordinary subprocess adapters are permanently non-authoritative. The
only subprocess authority mode is the pinned Rust evidence-v2 CLI identity:

```bash
MESH_HSAI_ADMISSION_COMMAND="/absolute/path/hsai-cli --current-policy-id mesh_policy://repo-patch/current"
MESH_HSAI_ADMISSION_AUTHORITY_MODE="rust_evidence_v2"
MESH_HSAI_ADMISSION_EXECUTABLE_SHA256="sha256:<64 lowercase hex>"
MESH_HSAI_ADMISSION_TIMEOUT_SECONDS=30
```

Authority mode requires the exact CLI argument shape shown above, an absolute
regular executable that is not a symlink, execute permission, and a
caller-configured SHA-256 pin. Mesh hashes the executable at construction and
again before every admission call. The stable adapter identity binds the
evidence-v2 identity version, executable digest, and current policy id. Missing,
partial, unknown-mode, relative-path, symlink, permission, or digest-drift
configuration fails closed before launching the CLI.

Mutable permit issuance additionally requires:

```bash
MESH_REPO_PATCH_PERMIT_SIGNING_KEY_PATH="/run/secrets/repo-patch-permit.key"
MESH_REPO_PATCH_PERMIT_SIGNING_KEY_ID="repo-patch-permit-hmac"
MESH_REPO_PATCH_PERMIT_ISSUER="mesh.orchestrator"
MESH_REPO_PATCH_PERMIT_EXECUTOR_AUDIENCE="mesh.repo_patch_actuator"
```

`MESH_REPO_PATCH_PERMIT_SIGNING_KEY` is the inline alternative to the secret
file path. Do not reuse `MESH_POLICY_SIGNING_KEY` for permit authority.

Mesh also ships a narrow subprocess-compatible command:

```bash
MESH_HSAI_ADMISSION_COMMAND="python scripts/hsai_admission_adapter.py"
```

That command reads a `mesh.hsai_admission_request.v1` object from stdin,
validates it, optionally reads the formal-backend bundle environment variable
below, and writes a `mesh.hsai_admission_decision.v1` object to stdout. It is a
bridge adapter command, not a deep repository merge or HSAI crate import.

## Out-of-Process Repo-Patch Authority

State slice `mesh.repo_patch_authority_orchestration.v1` confines repo-patch
actuation to the Unix-socket authority service. Goose and Hermes adapters are
review-only for this action. The orchestrator requires their exact
review-only, unchanged-parameters, no-authority, and no-credentials assertions
before contacting the authority. It never issues a permit or imports the raw
repo-patch actuator.

The client requires all of the following configuration; absent, partial,
relative, symlinked, unreadable, or permission-invalid key configuration fails
the repo-patch action closed:

```bash
MESH_REPO_PATCH_AUTHORITY_SOCKET_PATH=/run/mesh/repo-patch-authority.sock
MESH_REPO_PATCH_AUTHORITY_CLIENT_PRIVATE_KEY_PATH=/run/mesh/orchestrator-client.pem
MESH_REPO_PATCH_AUTHORITY_CLIENT_KEY_ID=mesh-orchestrator-client
MESH_REPO_PATCH_AUTHORITY_PUBLIC_KEY_PATH=/run/mesh/repo-patch-authority-public.pem
MESH_REPO_PATCH_AUTHORITY_KEY_ID=mesh-repo-patch-authority
```

After Mesh policy approval and the authority-eligible-adapter check,
orchestration performs a signed, non-mutating disposable-worktree preflight.
The receipt feeds the HSAI v2 request. Only a matching HSAI allow decision and
unchanged review result may feed the signed execution request. The authority
reruns both preflight and the pinned HSAI gate before promotion. Once execution is marked dispatched, a
transport error, malformed response, or lost response becomes
`outcome_unknown_after_dispatch`; Mesh does not retry or fall back to local
actuation. The verified authority signature, service receipt, and execution
result are retained in execution references and covered by the combined proof
packet receipt digest. Missing authority configuration is resolved lazily, so
non-repo actions remain unchanged.

### Closed-beta deployment overlay

`docker-compose.repo-patch-beta.yml` runs Mesh as UID/GID 2000 with only the
authority socket group, runs the authority as UID 3000, keeps Mesh on an
internal network, publishes loopback through a credential-free fixed-upstream
proxy, removes the writable host checkout and operator credential mounts,
disables local model CLI commands, applies read-only roots, drops capabilities,
sets no-new-privileges and resource bounds, gives only the authority target
write access, and mounts the same pinned Linux HSAI binary in both processes.
The beta fixes verification to the non-repository command `python3 -c pass`;
general repository-controlled verification remains outside the beta until it is
sandboxed in a separate no-secret worker. The production image retains Git for
detached worktrees. Operators must provide every declared key, identity, target,
state path, binary digest, and policy id. PostgreSQL migration 006 has a local
Docker restart/concurrency rehearsal, not managed multi-host availability proof.

This file is an overlay, not a standalone Compose project. Render or launch it
with the base service definition first:

```bash
docker compose -f docker-compose.yml -f docker-compose.repo-patch-beta.yml config
docker compose -f docker-compose.yml -f docker-compose.repo-patch-beta.yml up -d
```

### Linux OS-identity proof with the real Phase 747 CLI

Build the Phase 747 Rust binary for the same Linux container architecture. The
proof harness computes its SHA-256 pin inside the container and passes the pin
plus the exact `mesh_policy://repo-patch/os-boundary-proof` policy id to the
pinned adapter. No fake authority-eligible HSAI adapter participates.

```bash
docker build \
  -f docker/repo-patch-authority-proof.Dockerfile \
  -t orbital-mesh-authority-proof:local \
  .

docker volume create hsai-linux-target

docker run --rm \
  --mount type=bind,src=/absolute/path/to/composed-zk-benchmark-os,dst=/src,readonly \
  --mount type=volume,src=hsai-linux-target,dst=/target \
  -e CARGO_PROFILE_DEV_DEBUG=0 \
  rust:1.92-slim-bookworm \
  cargo build --locked --manifest-path /src/Cargo.toml --target-dir /target \
    -j 1 -p hsai-agent-admission --bin hsai-mesh-admission

docker run --rm --network none \
  --tmpfs /proof:rw,exec,mode=0755 \
  --mount type=volume,src=hsai-linux-target,dst=/hsai-target,readonly \
  -e MESH_OS_PROOF_HSAI_EXECUTABLE=/hsai-target/debug/hsai-mesh-admission \
  orbital-mesh-authority-proof:local
```

Success is a JSON proof with `status=pass`, three distinct observed UIDs,
denied agent and orchestrator direct writes, denied agent socket access, a real
pinned evidence-v2 allow decision, and target mutation only after the signed
orchestrator request. This remains disposable Linux-container evidence, not a
production deployment or semantic-correctness proof. The captured passing
result is `docs/evidence/repo-patch-authority-os-boundary-proof.json`.

## HSAI Formal Backend Metadata

The local adapter can also bind a Phase 278/279 HSAI
`gateway-formal-backend-run/*` bundle into `formal_evidence_metadata`:

```bash
MESH_HSAI_FORMAL_BACKEND_RUN_BUNDLE_PATH=/path/to/hsai/output-root
```

Mesh readback verifies the declared HSAI bundle files, `.sha256` sidecars,
schema versions, nonpromotion flags, redaction report, and required nonclaims.
Drift or escalation fails closed before repo-patch execution. The committed
fixture is also checked by `scripts/mesh.py verify-hsai-bridge-fixtures`.

This is metadata binding only. The current accepted bundle state is `NotRun`;
Mesh does not run Lean, SMT, COBALT, Rust-to-Lean, or any formal backend, and
does not treat the bundle as accepted HSAI evidence, Level2+ evidence,
production certification, executed formal proof, or authority to execute an
action. The combined proof packet includes the bounded metadata so audit/export
consumers can inspect the HSAI formal-backend context without upgrading its
claim boundary.

## Proof Packet Verification

Mesh exposes a narrow verifier command for exported combined proof packets:

```bash
python scripts/mesh.py verify-proof-packet \
  --packet /path/to/combined-proof-packet.json \
  --request /path/to/mesh.hsai_admission_request.v1.json \
  --decision /path/to/mesh.hsai_admission_decision.v1.json \
  --json
```

The verifier validates the HSAI request / decision binding, packet digests,
nonclaim preservation, export assertions, formal metadata nonclaim boundary, and
claim adequacy. It returns non-zero on failure. This command does not execute an
action, expand orchestration, mutate state, or promote metadata into accepted
evidence.

## Validation

Run the focused bridge tests:

```bash
PYTHONPATH=. UV_CACHE_DIR=/tmp/uv-cache UV_TOOL_DIR=/tmp/uv-tools uv run --with-editable . python -m unittest tests.test_hsai_admission_bridge
```

The deterministic evidence-carrying authority campaign is included in that
module. Its current local result and claim ceiling are recorded in
`docs/evidence-carrying-agent-actions-trial.md`.
