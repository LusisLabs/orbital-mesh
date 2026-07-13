# Evidence-Carrying Agent Actions: Repo-Patch Authority Trial

Date: 2026-07-13

State slices:

- `mesh.repo_patch_authority_orchestration.v1`
- `mesh.repo_patch_authority_service.v1`
- `mesh.repo_patch_authority_store_lifecycle.v1`
- `mesh.repo_patch_disposable_worktree.v1`
- `mesh.repo_patch_execution_permit.v1`
- `mesh.repo_patch_execution_permit_auth.v1`
- `mesh.hsai_admission_request.v2`
- `mesh.repo_patch_authority_os_identity_boundary.v1`
- `mesh.repo_patch_authority_postgres_rehearsal.v1`
- `mesh.repo_patch_authority_lifecycle_reconciliation.v1`
- `mesh.repo_patch_path_containment.v1`
- `mesh.repo_patch_beta_runtime_hardening.v1`
- `mesh.repo_patch_beta_loopback_ingress.v1`
- `mesh.repo_patch_verifier_protocol.v1`
- `mesh.repo_patch_verifier_worker.v1`
- `mesh.repo_patch_verifier_receipt.v2`
- `mesh.repo_patch_verifier_workspace_handoff.v1`

## Verdict

The trial now demonstrates a bounded, evidence-carrying repo-patch action across
the Mesh/HSAI boundary. The orchestrator cannot import or construct the mutable
actuator. Goose and Hermes are review-only. A separate Unix-socket authority
service owns patch preparation, its internal single-use permit, target
promotion, durable lifecycle state, and recovery behavior.

Repository verification is now outside that authority boundary. The authority
creates a manifest-bound worktree in a dedicated handoff volume and calls a
peer-UID-pinned verifier sidecar. The sidecar has no authority keys, state,
target mount, HSAI binary, authority socket, database URL, network, or Docker
socket. Its trusted root supervisor copies the bounded regular-file tree to
tmpfs, drops each command to capability-free UID 6000, streams output under a hard limit, kills
timeout descendants, and returns a request-bound terminal receipt. The authority
still independently verifies the canonical changed path and postimage before
HSAI admission or promotion.

The closed-beta overlay permits only the deterministic native review adapter.
Goose, Hermes, and Evo subprocess commands are empty in the merged beta
configuration because a same-UID subprocess would share the orchestrator's
mount namespace and could read its client signing key. CLI-backed reviewers are
not eligible for this beta until they run in a separate worker identity with no
key or authority-socket access.

The Mesh container is restricted to an internal control network. Host access
is restored only through a credential-free UID 65534 proxy published on
`127.0.0.1`. The proxy has no mounts or secrets and a fixed `mesh:8787`
upstream; it rejects absolute-form, chunked, and oversized requests. This is
network and credential separation, not client authentication.

The strongest authority-path result is a passing disposable Linux-container
proof with five observed process identities. Agent UID 1000 cannot write the
target or connect to the authority socket. Orchestrator UID 2000 cannot write
the target but can submit a signed request through authority group 4000.
Authority UID 3000 alone owns the mutable repository and observes the
orchestrator peer UID before acting. A root verifier supervisor in a separate
minimal image copies the bounded handoff into tmpfs and signs every terminal v2
receipt with a verifier-only Ed25519 key, while the admitted command runs as
keyless, capability-free UID 6000. A one-shot initializer stages that key into a
Linux-owned volume so Docker Desktop host-file sharing cannot expose the direct
bind mount to the command UID.

HSAI remains admission-only. Mesh and the authority independently invoke the
same caller-pinned Phase 747 Rust Evidence V2 executable. HSAI evaluates an
exact candidate bound to disposable-worktree preflight evidence and explicitly
does not grant execution authority. Only the authority service can issue and
consume the internal execution permit.

## Execution Protocol

1. Mesh policy admits the bounded `repo_patch_service/investigate_and_patch`
   decision and rejects any non-authority-eligible HSAI adapter.
2. The orchestrator sends a signed preflight request over a Unix socket.
3. The authority requires a stage-zero Git regular blob, opens every path
   component descriptor-relatively without following symlinks, creates a
   disposable git worktree, applies the declared patch, and authorizes only exact
   argv vectors with pinned executable and command digests.
4. The authority sends the candidate, worktree manifest, commands, immutable
   verifier image digest, and sandbox-profile digest to the separate verifier.
   The verifier rechecks those identities, executes as UID 6000, rejects output,
   timeout, nonzero exit, workspace mutation, restart, or replay drift, and
   returns a signed terminal v2 receipt. The authority pins its public key,
   retains the verified execute-time receipt in Mesh execution references,
   independently rechecks the canonical worktree, and emits the unchanged
   HSAI-compatible preflight receipt.
5. Mesh builds `mesh.hsai_admission_request.v2` from the decision, evaluation,
   and preflight receipt, then invokes the pinned Rust HSAI executable.
6. The beta's deterministic native adapter records a non-actuating review. Any
   proposed payload change is rejected. CLI-backed Goose and Hermes review
   contracts remain locally tested but are disabled in the beta because they
   are not OS-isolated from the orchestrator client key.
7. The orchestrator signs the execution request. The authority authenticates
   the client key and kernel peer credentials, recomputes preflight, reruns the
   pinned HSAI gate, and compares every substantive admission field.
8. The authority records a leased and dispatched lifecycle, issues and consumes
   its internal evidence-bound permit, atomically promotes the verified patch,
   verifies the result, and signs the terminal response.
9. A retry after a terminal permit reconciles and replays the binding-validated
   committed or aborted result. A recovered dispatched action with no terminal
   permit result becomes `unknown_after_dispatch`; it is never blindly promoted
   or retried.

The permit binds the HSAI request, decision, candidate, evidence, Mesh action,
run, policy, idempotency key, canonical actuation parameters, target preimage,
preflight receipt, accepted claims, enforced nonclaims, issuer, executor
audience, signing key, nonce, expiry, and authority-ledger tip.

## Verification Evidence

The targeted regression suites produced more than 200 passing tests. They include:

- 1,024 authenticated protocol-negative cases with zero mutation;
- 500 deterministic permit, context, and payload tamper cases blocked;
- 12 direct raw-parameter actuator bypass shapes blocked;
- one mutation across 16 concurrent consumers, with terminal replay for the
  remaining consumers;
- 256 distinct benign authorized actions accepted;
- stale preimage, preflight drift, malformed frame, wrong peer, wrong key,
  replay, corrupt ledger, missing authority, and unlisted-command failures;
- pre-dispatch lease reclamation with a fresh fencing token;
- post-dispatch crash recovery to an explicit unknown outcome without
  repromotion;
- post-dispatch restart reconciliation to exact committed and aborted terminal
  permit outcomes;
- absolute and relative parent-symlink escape rejection plus a deterministic
  parent-component swap race with zero external mutation;
- real Rust CLI allow and protected-path denial cases;
- merged beta-compose isolation contracts for non-root identity, socket group,
  read-only mounts, disabled local model CLIs, internal-only Mesh networking,
  credential-free loopback ingress, bounded resources, durable state, and the
  pinned Linux HSAI executable;
- isolated-verifier contract tests for request tamper, wrong peer, executable
  drift, symlink handoff, nonzero exit, workspace mutation, streaming output
  limit, timeout, terminal replay, restart terminalization, and preservation of
  an already durable terminal receipt when a stale running marker survives;
- a minimal-verifier-image Docker Linux-VM adversarial proof showing UID 6000
  command execution, signer-key denial to that UID, verified Ed25519 receipt,
  absent authority assets, `network=none`, read-only input/root, effective
  PID/memory limits, timeout/output rejection, and cleanup of a session-escaped
  descendant.

The materialized OS proof is
[`docs/evidence/repo-patch-authority-os-boundary-proof.json`](./evidence/repo-patch-authority-os-boundary-proof.json).
Every declared check is `true`, including execution of the admitted command as
verifier runner UID 6000 before the real HSAI gate and exact target promotion.

The isolated-verifier Docker proof is
[`docs/evidence/repo-patch-isolated-verifier-os-proof.json`](./evidence/repo-patch-isolated-verifier-os-proof.json).
Every declared check is `true`. The hostile commands are submitted directly to
the verifier protocol to test the worker boundary; the closed-beta authority
allowlist remains fixed to `python3 -c pass`.

The Docker-backed PostgreSQL restart, concurrency, fencing, and append-only
event rehearsal is recorded at
[`docs/evidence/repo-patch-authority-postgres-rehearsal.json`](./evidence/repo-patch-authority-postgres-rehearsal.json).

The five-action closed-beta campaign and the final credential-free ingress,
wrong-UID, replay, egress-blocking, restart, and cleanup checks are recorded at
[`docs/evidence/repo-patch-authority-beta-campaign.json`](./evidence/repo-patch-authority-beta-campaign.json).

Role-level release evidence uses the additive
`mesh.repo_patch_service_image_bundle.v1` contract. Generate it with
`scripts/generate_repo_patch_service_image_bundle.py` and verify it with
`scripts/verify_repo_patch_service_image_bundle.py`. It requires exact
commit-bound records for `mesh_control_plane`, `repo_patch_authority`, and
`repo_patch_verifier`: immutable image digests, Dockerfile hashes, CycloneDX
SBOMs, zero-unaccepted-blocker normalized scans, GitHub Actions attestations,
and the verifier sandbox/signer public-key policy. It does not replace
`mesh.release_provenance.v1`; it closes the role-level evidence gap introduced
by splitting privileged services into independent images.

## NIST Relationship

The design is directionally aligned with NIST's February 2026
[software-agent identity and authorization concept](https://www.nist.gov/news-events/news/2026/02/new-concept-paper-identity-and-authority-software-agents)
and the associated
[NCCoE project](https://www.nccoe.nist.gov/projects/software-and-ai-agent-identity-and-authorization):
each actor has a distinct identity,
requests are authenticated before access, authorization is policy-bound, and
activity produces attributable audit evidence. The NIST publication is a draft
concept paper and an active project input, not a normative certification target.
This trial therefore makes no NIST-compliance claim.

## Three-Role Release Boundary

State slice: `mesh.repo_patch_service_image_bundle.v1`.

The exact-commit release workflow builds the control-plane, authority, and
verifier images separately. It scans all three before registry authentication,
requires zero unaccepted high or critical findings, publishes only commit-bound
GHCR tags, resolves immutable registry digests, rescans the published subjects,
creates GitHub OIDC provenance attestations, then generates and independently
verifies the three-role bundle. Verifier sandbox and public-key policy enter
through repository variables; neither the private receipt-signing key nor an
HSAI evidence-signing key enters the build or publication job.

This boundary is implemented and statically tested, but current role scans fail
closed before publication. It is not live registry evidence until one clean
committed SHA completes the workflow and the generated bundle verifies against
the externally resolved digests and pinned verifier policy.

## Claim Ceiling

This is local regression evidence plus disposable Docker Linux-VM kernel-UID
and mount/network regression proofs. It supports the tested claim that the
bounded repo-patch path fails closed across API, signed protocol, durable
lifecycle, HSAI evidence binding, replay, concurrency, crash, authority identity,
and the signed-supervisor/keyless-command verifier boundary.

It is not a production deployment, independent security audit, formal proof,
semantic-correctness proof, production-host isolation proof, protection against
compromised root, verifier supervisor, authority, host, or container runtime,
arbitrary repository compatibility, global software-agent identity, accepted
HSAI evidence, benchmark evidence, or certification. Production use still
requires managed key custody, per-job PID/mount/cgroup isolation or a microVM,
immutable verifier image admission, current-head role-level image bundles,
operator provisioning
and rotation, managed-database backup/failover evidence, monitoring, and an
independent review.
