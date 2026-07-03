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

The bridge adds three schema-backed contracts under
`shared/mesh_runtime/schemas/`:

- `mesh.hsai_admission_request.v1`
- `mesh.hsai_admission_decision.v1`
- `mesh.combined_proof_packet.v1`

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

`OrchestratorService` calls the bridge before any selected repo-patch execution.
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

Allowed repo-patch decisions carry `_mesh_hsai_admission_context` in execution
parameters before they are handed to native adapters, CLI executors, or Goose /
Hermes bridge subprocesses. Those execution paths revalidate that context before
calling the raw `RepoPatchAdapter`. This binds the execution attempt to the
current `mesh_run_id`, `mesh_action_id`, policy id, action proposal digest,
request digest, decision digest, candidate digest, and allowed HSAI decision.
Repo-patch execution also uses the existing execution-attempt replay guard so a
terminal outcome for the same idempotency key is reused instead of dispatching a
second patch attempt.

The raw `services.actuators.repo_patch.RepoPatchAdapter` remains a low-level
actuator helper. Production orchestrator entry points for repo patching must go
through the HSAI execution-context guard.

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

Mesh also ships a narrow subprocess-compatible command:

```bash
MESH_HSAI_ADMISSION_COMMAND="python scripts/hsai_admission_adapter.py"
```

That command reads a `mesh.hsai_admission_request.v1` object from stdin,
validates it, optionally reads the formal-backend bundle environment variable
below, and writes a `mesh.hsai_admission_decision.v1` object to stdout. It is a
bridge adapter command, not a deep repository merge or HSAI crate import.

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
