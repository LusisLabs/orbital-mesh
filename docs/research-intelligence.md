# Research Intelligence

The control plane reads autoresearch sessions from `MESH_RESEARCH_DIRECTORY` (default `.mesh-runtime-state/research`) and derives a compact intelligence layer for each session.

## Behavior

- `GET /api/research-sessions` includes a `research_intelligence` summary per session.
- `GET /api/research-sessions/:session_id` includes the full session-level `research_intelligence` object.
- `GET /api/research-corpus` aggregates classifications, recurring flags, grounded anchors, drift sessions, and next actions across the corpus.
- `final_report_markdown` is sanitized before API and UI display: `<think>...</think>` blocks are removed and counted as `reasoning_block_redacted`.

## Classifications

- `repo_grounded`: enough repo-specific anchors are present and off-domain drift is low.
- `mixed`: repo anchors are present, but off-domain drift also appears.
- `off_domain`: the session is dominated by concepts outside this repository, such as wireless networking or cabling ROI.
- `needs_review`: insufficient repo anchors or research markdown to classify confidently.

## Anchors

Grounded research is expected to discuss repo-relevant constructs:

- `FirstSlicePipeline`, `run_events`, `event_chain`, and stage counts.
- Evaluation and execution separation, including `evaluation_passed`, `evaluation_recommendation`, and `execution_status`.
- Operator steering, approval gates, overrides, and pauses.
- Vault and Merkle auditability.
- Feature-flag and Kubernetes signal contracts.
- Native, Promptfoo, and Goose mode separation.

## Drift Flags

- `off_domain_drift`: the report uses terms that map to unrelated network-mesh positioning.
- `unsupported_superlative_risk`: the report uses public-claim language such as "#1", "fastest", or "industry-leading".
- `evidence_scope_limit`: the report acknowledges limits such as small sample size or missing comparative evidence.
- `reasoning_block_redacted`: hidden reasoning markup was removed before display.
- `no_research_markdown`: no markdown was available under `synthesis/`, `results/`, or `notes/`.
