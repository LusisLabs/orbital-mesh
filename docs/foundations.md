# Foundations

This repository implements a bounded remediation control plane. The work is easier to review and extend when the non-negotiables are explicit.

## Non-Negotiables

- Bounded action vocabulary. No arbitrary shell automation as a default execution path.
- Evaluation before execution. Policy and quality gates are first-class stages.
- Operator steering by default. Approval gates exist for a reason.
- Audit-grade run memory. Runs emit typed events and artifacts with replay-friendly stage chains.
- Explicit rollback semantics. Live Kubernetes actions are allowlisted and off by default.

## System Shape

The core loop is:

1. Ingest (normalize) signal
2. Trigger detection (actionable or no-trigger terminal)
3. Decision (bounded action type + parameters)
4. Evaluation (policy + quality gates)
5. Operator gate (approve/cancel/override/pause/notes)
6. Execution (bounded actuator path)
7. Feedback (post-action outcome and guardrails)
8. Persistence (events, vault mirror, Merkle roots/proofs)

## Evidence Standard

External-facing claims should map to one of:

- fixture-backed runs (deterministic, local)
- the production-like local runbook path
- recorded operator sessions with saved artifacts

## Public Messaging Rules

- Prefer "policy-guided", "bounded", "operator-steerable", and "evaluation-gated".
- Avoid "self-healing" and unsupported superlatives.
- Treat "live Kubernetes execution" as an explicitly enabled, allowlisted demo/validation path.

## Pointers

- Architecture: `architecture.md`
- HTTP API reference: `docs/api-reference.md`
- Extending Mesh (plug-ins): `docs/extending-mesh.md`
- Integrations and readiness: `docs/integrations.md`
- Investigation harness: `docs/investigation-harness.md`
- Production-like local E2E: `docs/production-live-runbook.md`
- UI workspace model: `docs/ui-auto-canvas-workspace.md`
- Mesh webapp (Remix BFF): `apps/mesh-webapp/` (migration surface, not yet production-authoritative)
