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

## Verdict

The trial now demonstrates a bounded, evidence-carrying repo-patch action across
the Mesh/HSAI boundary. The orchestrator cannot import or construct the mutable
actuator. Goose and Hermes are review-only. A separate Unix-socket authority
service owns patch preparation, its internal single-use permit, target
promotion, durable lifecycle state, and recovery behavior.

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

The strongest result is a passing disposable Linux-container proof with three
kernel identities. Agent UID 1000 cannot write the target or connect to the
authority socket. Orchestrator UID 2000 cannot write the target but can submit a
signed request through authority group 4000. Authority UID 3000 alone owns the
mutable repository and observes the orchestrator peer UID before acting.

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
   disposable git worktree, applies the declared patch, runs only exact
   allowlisted argv vectors, pins executable digests, and emits a preflight
   receipt.
4. Mesh builds `mesh.hsai_admission_request.v2` from the decision, evaluation,
   and preflight receipt, then invokes the pinned Rust HSAI executable.
5. The beta's deterministic native adapter records a non-actuating review. Any
   proposed payload change is rejected. CLI-backed Goose and Hermes review
   contracts remain locally tested but are disabled in the beta because they
   are not OS-isolated from the orchestrator client key.
6. The orchestrator signs the execution request. The authority authenticates
   the client key and kernel peer credentials, recomputes preflight, reruns the
   pinned HSAI gate, and compares every substantive admission field.
7. The authority records a leased and dispatched lifecycle, issues and consumes
   its internal evidence-bound permit, atomically promotes the verified patch,
   verifies the result, and signs the terminal response.
8. A retry after a terminal permit reconciles and replays the binding-validated
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
  pinned Linux HSAI executable.

The materialized OS proof is
[`docs/evidence/repo-patch-authority-os-boundary-proof.json`](./evidence/repo-patch-authority-os-boundary-proof.json).
Every declared check is `true`.

The Docker-backed PostgreSQL restart, concurrency, fencing, and append-only
event rehearsal is recorded at
[`docs/evidence/repo-patch-authority-postgres-rehearsal.json`](./evidence/repo-patch-authority-postgres-rehearsal.json).

The five-action closed-beta campaign and the final credential-free ingress,
wrong-UID, replay, egress-blocking, restart, and cleanup checks are recorded at
[`docs/evidence/repo-patch-authority-beta-campaign.json`](./evidence/repo-patch-authority-beta-campaign.json).

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

## Claim Ceiling

This is local regression evidence plus a disposable Linux-container
kernel-UID enforcement proof. It supports the tested claim that the bounded
repo-patch path fails closed across API, signed protocol, durable lifecycle,
HSAI evidence binding, replay, concurrency, crash, and Linux identity boundaries.

It is not a production deployment, independent security audit, formal proof,
semantic-correctness proof, protection against compromised root or authority
processes, global software-agent identity, accepted HSAI evidence, benchmark
evidence, or certification. Production use still requires managed key custody,
managed verification-worker isolation for repository-controlled tests,
operator provisioning and rotation, managed-database backup/failover evidence,
monitoring, and an independent review.
