# MeshModel Benchmark Plan

This plan defines the first measurable benchmark contract for MeshModel. It is
intentionally independent of any new model-kernel implementation so deterministic
baselines can run first.

## Objective

MeshModel must prove that compact or learned memory can answer source-grounded
operational questions after original context is removed, while preserving Mesh
governance requirements.

The benchmark must answer four questions:

1. Does memory improve answer quality over existing Mesh retrieval?
2. Does compact memory reduce context, KV, or state footprint?
3. Does the answer include correct citations and contradiction handling?
4. Does memory remain inside tenant, data, policy, evaluation, and audit bounds?

## Source Bundle

The source bundle is the fixed input to every benchmark run. It should be
generated from existing Mesh artifacts and written as JSON for replay.

Required source categories:

- run sessions and run events;
- memory packets and retrieval records;
- observations, claims, relationships, and supersessions;
- trigger, decision, evaluation, action, and feedback artifacts;
- operator notes and vault documents;
- research session summaries and final reports;
- Mesh Brain model-kernel, live-serving, backend-matrix, posttraining, quality,
  adapter, and rollback records when present;
- production-readiness, go/no-go, Darkharness, and Perennial proof packets when
  present.

Every source row must carry:

- `source_type`;
- `source_id`;
- `tenant_scope`;
- `service_scope`;
- `created_at`;
- `data_classification`;
- `retention_class`;
- `training_eligibility`;
- `evaluation_eligibility`;
- `redaction_status`;
- `citation_refs`;
- `content_hash`;
- `artifact_refs`.

Rows without citation refs or content hashes can be included only as
audit-context rows and cannot satisfy answer correctness.

## Benchmark Tasks

| Task | Purpose | Required inputs | Pass gate |
| --- | --- | --- | --- |
| Context-removed QA | Prove compact memory can answer without original context. | Source bundle, hidden gold context, question set. | Correct answer with exact citation refs and no original-context access. |
| Long operational recall | Test recall across many runs. | Run sessions, events, artifacts, notes. | Recalls target fact and freshness state. |
| Contradiction detection | Test stale/superseded memory. | Claims, supersession records, newer evidence. | Flags contradiction and cites old and new evidence. |
| Procedural promotion | Test reusable memory promotion. | Repeated decisions, evaluations, feedback. | Promotes only repeated high-confidence behavior. |
| Policy-bound reasoning | Test safe memory use. | Policies, decisions, evaluations, action records. | Does not claim unsupported execution or bypass approval. |
| Replay determinism | Test audit reproducibility. | Fixed source bundle and fixed seed/config. | Stable replay hash and stable result packet. |
| Memory efficiency | Test state footprint. | Same source bundle across kernels. | Reports memory bytes and useful facts per byte. |
| Write/read latency | Test operator practicality. | Same source bundle across kernels. | Reports p50 and p95 write/read latency. |

## Baselines

Run these before model kernels.

| Baseline | Required behavior |
| --- | --- |
| Lexical | Token overlap over source-grounded records. |
| Graph | Relationship expansion from lexical seeds. |
| Existing memory packet | Current Mesh retrieval packet result. |
| Compact summary | Deterministic bounded summary with citations. |
| Optional vector | Embedding-backed retrieval only when configured. |
| Long-context transformer | Reference model path when a configured backend exists. |

Model-level memory must beat at least one deterministic baseline on a target
task class before it can move beyond research.

## Candidate Kernels

| Kernel | Entry criteria | Expected output |
| --- | --- | --- |
| SSM/recurrent compressor | Deterministic baselines are stable. | Compact state with recall/citation metrics. |
| Neural long-term memory | Source bundle has enough QA and contradiction cases. | Memory-conditioned answer packets. |
| Gradient-written memory | Context-removal task set exists. | Optimized memory-token artifacts plus answer packets. |
| Sparse factual memory | Factual recall set exists with freshness labels. | Sparse lookup result with tenant/freshness checks. |
| Hybrid attention + state | Local precision failures are measured. | Quality/cost comparison to transformer baseline. |

## Result Packet

Each benchmark run should emit one result packet per task and kernel.

```json
{
  "version": "mesh.meshmodel_benchmark_result.v1",
  "benchmark_id": "meshmodel_bench_example",
  "kernel": "lexical_baseline",
  "task": "context_removed_qa",
  "source_bundle_hash": "sha256:...",
  "context_removed": true,
  "answer": "answer text",
  "citation_refs": [],
  "supporting_observation_ids": [],
  "supporting_claim_ids": [],
  "contradictions": [],
  "metrics": {
    "answer_correct": false,
    "citation_correct": false,
    "contradiction_detected": false,
    "procedural_promotion_correct": false,
    "memory_bytes": 0,
    "write_latency_ms": 0.0,
    "read_latency_ms": 0.0,
    "replay_deterministic": true
  },
  "policy": {
    "tenant_scope_verified": true,
    "data_classification_verified": true,
    "approval_bypass_claim": false,
    "unsafe_action_claim": false
  }
}
```

The future control-plane probe can wrap these result packets, but this benchmark
plan does not add that route.

## Scoring

Minimum metrics:

- answer accuracy;
- citation correctness;
- contradiction F1;
- procedural promotion precision;
- unsafe-claim rate;
- replay determinism;
- memory bytes;
- useful facts per memory byte;
- write latency p50/p95;
- read latency p50/p95.

Blocking failures:

- answer cites no source when one is required;
- answer uses hidden original context in a context-removal task;
- cross-tenant memory leak;
- audit-only row used as trainable memory;
- stale claim used without freshness warning;
- unsupported execution or approval-bypass claim;
- non-deterministic result from deterministic baseline.

## Acceptance Criteria

Phase 1 is complete when:

- source bundle requirements are documented and implementable;
- all benchmark tasks have pass gates;
- deterministic baselines can be implemented without external model dependencies;
- model-kernel candidates have clear entry criteria;
- result packets are stable enough to become future Mesh Brain governance
  artifacts.

MeshModel remains research-only until at least one candidate kernel beats the
baseline suite on a real Mesh source bundle.
