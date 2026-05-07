# MeshModel Architecture

MeshModel is the proposed memory-native model-kernel evolution of Mesh Brain.
It is not a production runtime today. It is a research and benchmark lane for
proving whether Mesh can build a governed model substrate that learns useful
operational memory across runs without depending on unbounded context growth.

## Positioning

Mesh Brain is the control plane and model lifecycle system:

- data refinery;
- posttraining and adapter proof;
- model catalog and promotion gates;
- serving and backend smoke;
- quality and red-team gates;
- audit, rollback, and production artifact records.

MeshModel is a model-kernel research plane inside that boundary:

- memory-native reasoning kernel;
- recurrent and SSM state compression;
- model-level write/read memory;
- sparse factual memory;
- context-removal evaluation;
- governance-bound memory promotion.

The working thesis is:

> MeshModel is a governed, memory-native reasoning model that uses efficient
> state evolution, model-level memory, sparse factual memory, and auditable
> memory lifecycle controls to produce reusable intelligence across Mesh runs.

Do not claim MeshModel is a transformer replacement or a breakthrough until
benchmarks prove it against strong baselines.

## Non-Goals

- Do not vendor external research repositories directly into the production
  runtime.
- Do not let model memory bypass policy, evidence, evaluation, approval,
  rollback, or audit gates.
- Do not promote a memory kernel from paper claims alone.
- Do not treat long-context recall as operational intelligence unless the
  answer includes correct citations and survives context removal.
- Do not replace the existing Mesh memory store with an opaque model state.
- Do not conflate proposal-only agent lanes with production actuation authority.

## Core Design

MeshModel should be assembled as a set of benchmarkable lanes. Each lane must
read the same source artifacts, emit the same answer contract, and record the
same provenance so comparisons are meaningful.

| Lane | Purpose | Memory form | Expected value | Promotion risk |
| --- | --- | --- | --- | --- |
| Transformer baseline | Reference quality and attention behavior | KV cache and prompt context | Strong local dependency modeling | Expensive long context; session-bound memory |
| SSM compressor | Cheap long-sequence state update | Selective or structured recurrent state | Lower inference memory and latency | State may lose exact facts or citations |
| Recurrent/local-attention hybrid | Fixed-state inference with local precision | Recurrent state plus local attention | Lower KV pressure while retaining recent precision | Long-range recall can degrade |
| Neural long-term memory | Model-level persistent memory module | Learned neural memory | Better historical context use | Write policy and overwrite behavior must be controlled |
| Gradient-written memory | Loss-driven context compression | Optimized prefix or memory tokens | Strong context-removal candidate | Test-time compute and privacy handling |
| Sparse factual memory | Cheap factual capacity | Trainable key-value memory table | High factual recall per FLOP | Staleness, update policy, and tenant isolation |
| Mesh memory baseline | Audited operational substrate | Observations, claims, relationships, packets | Citation, confidence, contradiction handling | Retrieval quality depends on source coverage |

## Memory Model

MeshModel must distinguish five kinds of memory.

| Memory kind | Description | MeshModel use |
| --- | --- | --- |
| Working memory | Run-scoped state for current task execution | Short-horizon scratch context and local state |
| Episodic memory | Immutable source-grounded observations | Run events, operator notes, artifacts, postmortems |
| Semantic memory | Verified claims derived from observations | Stable statements with confidence and citations |
| Procedural memory | Promoted reusable guidance | Runbook-like behavior and recurring operational lessons |
| Model-level memory | Compact learned or optimized state inside the model path | Context-removal answer state, recurrent state, sparse memory |

Model-level memory never becomes authoritative by itself. It must project back
into Mesh memory records or produce cited answers against Mesh memory records
before it can influence operational decisions.

## Write Path

A MeshModel write path must be explicit and auditable.

1. Ingest source records from Mesh run sessions, run events, memory packets,
   decisions, evaluations, operator notes, research sessions, postmortems, and
   rollback drills.
2. Classify each source as trainable, evaluation-only, audit-only, or blocked.
3. Redact secret-like content and enforce tenant boundary before any model input.
4. Build a compact memory candidate using one or more kernels:
   - deterministic summary;
   - recurrent state scan;
   - SSM state scan;
   - sparse KV insert;
   - neural memory update;
   - gradient-written memory tokens.
5. Score the memory candidate on reconstruction, recall, citation fidelity,
   contradiction handling, and policy compliance.
6. Store the memory candidate as an experiment artifact, not as production
   authority.
7. Promote only verified observations and claims through the Mesh memory
   lifecycle.

## Read Path

Every read must produce an answer packet, not just free text.

Required fields:

- `question`;
- `memory_kernel`;
- `answer`;
- `supporting_observation_ids`;
- `supporting_claim_ids`;
- `citation_refs`;
- `contradictions`;
- `confidence`;
- `freshness`;
- `policy_scope`;
- `tenant_scope`;
- `context_removed`;
- `source_artifact_refs`;
- `latency_ms`;
- `memory_bytes`;
- `replay_hash`.

The `context_removed` flag is critical. It proves whether the answer came from
the compact memory state or from the original context.

## Benchmark Tasks

MeshModel must start with operational benchmarks, not generic chat preference.

| Task | Question answered | Source artifacts | Primary metric |
| --- | --- | --- | --- |
| Context-removed QA | Can the model answer after the original context is removed? | Run events, notes, docs, memory packets | Accuracy with correct citations |
| Long operational recall | Can it recall facts across many runs? | Run sessions and artifacts | Exact recall and freshness |
| Contradiction detection | Can it identify newer evidence that supersedes old claims? | Claims, supersessions, evaluations | Contradiction F1 |
| Procedural promotion | Can it identify repeated successful behavior? | Feedback, evaluations, actions | Promotion precision |
| Policy-bound reasoning | Does it avoid unsafe unsupported action claims? | Decisions, policies, evaluations | Unsafe-claim rate |
| Replay determinism | Does same input produce same packet? | Fixed source bundle | Replay hash stability |
| Memory efficiency | Does it reduce context/KV footprint? | Same benchmark corpus | Bytes per useful fact |
| Write/read latency | Is memory useful under operator latency constraints? | Same benchmark corpus | p50/p95 write and read latency |

## Baselines

MeshModel must beat simple baselines before it is worth deeper integration.

| Baseline | Why it matters |
| --- | --- |
| Lexical search | Lowest-cost source-grounded baseline |
| Graph expansion | Current Mesh relationship-aware memory path |
| Vector retrieval | Standard RAG comparison when embeddings are configured |
| Compact summary | Cheap long-context compression baseline |
| Long-context transformer | Strong quality baseline with high memory cost |
| Existing Mesh memory packet | Current governed operational substrate |

## Promotion Gates

An experimental MeshModel kernel can move forward only when it satisfies all
gates below against a fixed corpus.

- Accuracy beats lexical, graph, compact-summary, and long-context transformer
  baselines for at least one target class of task.
- Citation correctness is high enough for operator review. An uncited correct
  answer is not enough.
- Contradiction handling catches stale or superseded claims.
- Replay determinism is stable for deterministic kernels or bounded for
  stochastic kernels with fixed seed and fixed backend.
- Tenant and data-classification boundaries are preserved.
- Memory write/read costs are measured and reported.
- Unsafe unsupported action claims are blocked or routed to human review.
- The output can be recorded as Mesh Brain governance evidence.

## End-to-End Build Phases

### Phase 0: Documentation and Research Matrix

Deliverables:

- this architecture document;
- `docs/meshmodel-preliminary-research.md`;
- research matrix for source papers, code, risks, and Mesh fit;
- `docs/meshmodel-benchmark-plan.md` with exact tasks, source artifacts, and
  pass gates.

Exit gate:

- no runtime code claims MeshModel support until the research matrix and
  benchmark contract exist.

### Phase 1: Deterministic Benchmark Harness

Deliverables:

- `mesh_brain/meshmodel/` package;
- source bundle builder from existing Mesh state;
- deterministic lexical, graph, and summary baselines;
- context-removal QA task format;
- JSON result schema.

Exit gate:

- same source bundle produces stable result packets and replay hashes.

### Phase 2: Recurrent and SSM Prototype

Deliverables:

- fixed-state recurrent scan baseline;
- SSM-style state compressor baseline;
- memory footprint and latency reports;
- recall and citation comparison against deterministic baselines.

Exit gate:

- state compression gives measurable memory savings without destroying
  citation fidelity on target tasks.

### Phase 3: Model-Level Memory Prototype

Deliverables:

- neural-memory or memory-token write prototype;
- context-removal read path;
- reconstruction and QA scoring;
- privacy and tenant-boundary checks.

Exit gate:

- model-level memory answers from compact state and cites source records without
  original context access.

### Phase 4: Sparse Factual Memory Prototype

Deliverables:

- sparse KV factual-memory experiment;
- factual recall benchmark;
- stale-memory and supersession tests;
- tenant partitioning proof.

Exit gate:

- factual memory improves recall without bypassing freshness and supersession
  controls.

### Phase 5: Control-Plane Evidence Lane

Deliverables:

- `POST /api/mesh-brain/meshmodel-probe`;
- Mesh run artifacts for benchmark results;
- non-deployment record;
- release-readiness blocker until explicit promotion gates pass.

Exit gate:

- MeshModel probe evidence appears in run artifacts, vault, Merkle/proof chain,
  and readiness/go-no-go surfaces as research evidence only.

## Integration Boundaries

MeshModel should depend on existing Mesh Brain and Mesh Runtime primitives:

- `mesh_brain.data_plane` for source normalization and tenant filtering;
- `mesh_brain.model_kernel_probe` as the pattern for deterministic kernel proof;
- `mesh_brain.research_registry` for non-serving research influences;
- `shared.mesh_runtime.memory_retrieval` for current lexical/graph/vector
  baseline retrieval;
- `shared.mesh_runtime.memory_lifecycle` for crystallization, promotion,
  freshness, and supersession;
- `services.control_plane.RunCoordinator` for evidence-producing Mesh runs;
- `docs/post-training/runtime.md` for current Mesh Brain runtime posture.

External research code can be used only as reference or optional isolated
experiments until license, dependency, reproducibility, hardware, and security
reviews are complete.

## Research Inputs

Primary research inputs are tracked in `docs/meshmodel-research-matrix.md`.
The high-value families are:

- Mamba and Mamba-2 for selective and structured SSM state evolution;
- Mamba-3 as an active 2026 watch item for inference-first SSM improvements;
- Titans for neural long-term memory beside attention;
- GradMem for gradient-written compact memory tokens;
- Jamba for large-scale Transformer-Mamba-MoE hybrid evidence;
- RecurrentGemma and Griffin for recurrence plus local attention;
- RWKV, RetNet, xLSTM, Hyena, and StripedHyena for attention-alternative
  baselines;
- Memory Layers at Scale for trainable sparse factual memory;
- long-context benchmarks such as LongBench, RULER, BABILong, ZeroSCROLLS,
  NeedleBench, and InfiniteBench for external task coverage.

## Success Definition

MeshModel becomes a credible Mesh Brain evolution only when the system can show:

- compact memory can answer source-grounded questions after context removal;
- recurring operational evidence is promoted into procedural memory without
  losing provenance;
- stale or contradicted memory is detected and demoted;
- memory write/read costs are lower than unbounded context replay for target
  workflows;
- memory never bypasses Mesh policy, evaluation, approval, or audit;
- every claim can be replayed from exact source artifacts.

The breakthrough claim is earned only if these properties hold at useful scale.
