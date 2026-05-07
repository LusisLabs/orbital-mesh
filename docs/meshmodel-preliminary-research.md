# MeshModel Preliminary Research

MeshModel is the proposed memory-native model-kernel evolution of Mesh Brain.
This document records the preliminary research position for engineering work.
It does not claim that MeshModel exists as a runtime, serving backend, or
production-ready architecture.

## Research Objective

The first research objective is to determine whether Mesh can build a model
substrate that is more efficient and more persistent than a standard
long-context transformer for operational intelligence.

The testable claim is:

> MeshModel can combine efficient state evolution, model-level memory, sparse
> factual memory, and Mesh-governed promotion rules to answer source-grounded
> operational questions after the original context is removed.

The claim is not:

- "transformers are obsolete";
- "Mamba alone replaces attention";
- "model memory can replace Mesh memory";
- "external papers become production dependencies";
- "memory can influence action without Mesh policy and audit."

## Decision Frame

MeshModel should be planned as a hybrid memory system, not as a single
architecture bet.

| Research line | MeshModel role | Reason |
| --- | --- | --- |
| Mamba, Mamba-2, Mamba-3 | Efficient state-compression lane | SSMs target long-sequence cost and fixed/compact state behavior. |
| Titans, GradMem, Gdwm | Model-level memory lane | These papers directly target memory writing, test-time adaptation, and long-term state. |
| Memory Layers at Scale | Sparse factual-memory lane | Trainable KV memory is the cleanest factual-capacity reference. |
| Jamba, RecurrentGemma, RetNet, RWKV, Hyena, xLSTM | Hybrid and recurrent baselines | These prevent a false transformer-vs-SSM binary. |
| Existing Mesh memory | Governance baseline | Observations, claims, contradictions, citations, freshness, and promotion remain authoritative. |

The preliminary conclusion is that the strongest path is a governed hybrid:

1. use SSM/recurrent state to compress long operational traces;
2. use attention or retrieval where exact local dependency and citation
   fidelity matter;
3. use model-level memory only when it beats deterministic baselines in
   context-removal tests;
4. use sparse memory only for factual capacity when freshness and tenant
   isolation are enforceable;
5. project any useful result back into Mesh-governed evidence packets.

## Literature Inputs

### Mamba and Mamba-2

Mamba identifies the core weakness of earlier subquadratic models as weak
content-based reasoning and addresses it with input-selective SSM parameters.
The paper claims linear scaling in sequence length and fast inference relative
to transformers for the tested settings: https://arxiv.org/abs/2312.00752.

Mamba-2 reframes the discussion by showing a structured state-space duality
between SSMs and attention variants, then introducing a faster Mamba-2 core
layer: https://arxiv.org/abs/2405.21060.

The official implementation is reference material only:
https://github.com/state-spaces/mamba. Its README indicates Linux, NVIDIA GPU,
PyTorch, and CUDA requirements for the normal path. That makes it useful for
GPU experiments but unsuitable as an immediate cross-platform Mesh dependency.

MeshModel implication: use Mamba-family work as the efficient state-compressor
line. Do not present it as proof that transformer replacement is solved.

### Mamba-3

Mamba-3 is a 2026 inference-first watch item:
https://arxiv.org/abs/2603.15569. It targets state tracking and hardware
efficiency with a more expressive recurrence, complex-valued state update, and
MIMO formulation.

MeshModel implication: track as a later SSM prototype candidate. Because it is
new and hardware-oriented, it should not become a dependency before local
reproduction.

### Titans

Titans introduces a neural long-term memory module that works beside attention:
https://arxiv.org/abs/2501.00663. The paper frames attention as short-term
memory and neural memory as longer-term historical memory. It reports benefits
on language modeling, commonsense reasoning, genomics, time-series, and large
needle-in-haystack contexts.

MeshModel implication: Titans is the primary design anchor for a neural memory
module. The unresolved engineering problem is governance: what gets written,
what gets overwritten, what is cited, what persists, and what is forbidden.

### GradMem and Gdwm

GradMem directly matches the context-removal problem:
https://openreview.net/forum?id=GidQ1tmQ2G and
https://huggingface.co/papers/2603.13875. It freezes model weights and writes
context into compact memory tokens through test-time gradient descent.

Gdwm adds an efficiency lens for test-time adaptation:
https://arxiv.org/abs/2601.12906. It treats write allocation as a
budget-constrained memory consolidation problem and introduces a controller for
where gradient steps are spent.

MeshModel implication: GradMem defines the strongest model-level memory
benchmark shape. Gdwm defines the write-budget problem MeshModel must solve
before any gradient-written memory lane is operator-useful.

### Memory Layers at Scale

Memory Layers at Scale uses trainable sparse key-value memory to add factual
capacity without increasing FLOPs in the same way dense layers do:
https://arxiv.org/abs/2412.09764.

MeshModel implication: this is the strongest source for a sparse factual-memory
lane. Mesh must add freshness, contradiction, tenant, and deletion rules before
this kind of memory can influence operational output.

### Hybrid and Recurrent Baselines

Jamba interleaves Transformer and Mamba layers and adds MoE:
https://openreview.net/forum?id=JFPaD7lpBD. It is evidence that hybrid
architectures remain a serious large-scale path.

RecurrentGemma uses Griffin, combining linear recurrences with local attention
and fixed-size state: https://arxiv.org/abs/2404.07839.

RetNet connects recurrence and attention through retention, with parallel,
recurrent, and chunkwise recurrent computation modes:
https://arxiv.org/abs/2307.08621.

Hyena uses long convolutions and gating as an attention-free alternative:
https://arxiv.org/abs/2302.10866.

xLSTM modernizes LSTM memory with exponential gating and scalar/matrix memory:
https://arxiv.org/abs/2405.04517.

RWKV remains relevant as an attention-free RNN-like baseline:
https://lfaidata.foundation/projects/rwkv/ and https://wiki.rwkv.com.

MeshModel implication: these are baselines and design constraints. A MeshModel
prototype must beat simple recurrent, local-attention, long-convolution, and
hybrid baselines before it earns a stronger claim.

## Mesh-Specific Research Dependencies

The research package must bind external literature to existing Mesh evidence
surfaces.

| Mesh plane | Existing anchor | Research dependency |
| --- | --- | --- |
| Data plane | `mesh_brain.data_plane` | Source classification, tenant filtering, redaction, training/eval eligibility. |
| Memory plane | `shared.mesh_runtime.memory_lifecycle` | Observation, claim, contradiction, freshness, and procedural promotion behavior. |
| Retrieval plane | `shared.mesh_runtime.memory_retrieval` | Lexical, graph, optional vector, and memory packet baselines. |
| Kernel plane | `mesh_brain.model_kernel_probe` | Deterministic evidence pattern and non-deployment run records. |
| Research registry | `mesh_brain.research_registry` | Non-serving source tracking and adoption guidance. |
| Control plane | `services.control_plane.RunCoordinator` | Future MeshModel probe should be a completed evidence run, not a serving rollout. |
| Runtime docs | `docs/post-training/runtime.md` | Public boundary for what is implemented versus proposed. |

## Preliminary Research Work Packages

### 1. Source Dossier

Build a stable source dossier with the paper title, source URL, code URL when
present, mechanism, memory form, benchmark claims, implementation status,
hardware requirements, license-review status, and Mesh adoption guidance.

Acceptance criteria:

- each claim points to a paper, official codebase, or clearly marked secondary
  source;
- no external repository is marked as a production dependency;
- every source has a Mesh role: compressor, memory writer, factual memory,
  baseline, or watch item.

### 2. Mesh Corpus Inventory

Inventory which first-party artifacts can seed the benchmark corpus:

- run sessions;
- run events;
- memory packets;
- observations, claims, relationships, and supersessions;
- decisions and evaluations;
- action and feedback records;
- operator notes;
- research sessions;
- Mesh Brain model-kernel, live-serving, backend-matrix, posttraining, quality,
  and rollback artifacts;
- production-readiness, go/no-go, Darkharness, and Perennial proof packets.

Acceptance criteria:

- every source type has a tenant/data-policy classification;
- every source type has training, evaluation, audit-only, or blocked status;
- citation refs and content hashes are required for benchmark rows.

### 3. Benchmark Contract

Define the first task suite before implementing kernels:

- context-removed QA;
- long operational recall;
- contradiction detection;
- procedural promotion;
- policy-bound reasoning;
- replay determinism;
- memory footprint;
- write/read latency.

Acceptance criteria:

- every task has source artifacts, baseline, metric, and pass gate;
- all tasks can run against deterministic baselines before model kernels exist;
- context-removal tests physically hide original context from the answer path.

### 4. Baseline Shortlist

Start with deterministic baselines:

- lexical overlap;
- graph expansion;
- existing Mesh memory packet;
- compact summary;
- optional vector retrieval if the deployment has embeddings configured.

Only after these pass should model kernels enter:

- SSM/recurrent compression;
- neural memory;
- gradient-written memory;
- sparse factual memory;
- long-context transformer reference.

Acceptance criteria:

- a model-level memory result is not considered useful unless it beats the
  deterministic baselines on at least one target task class.

## Open Research Questions

1. Which source artifacts produce enough supervised QA pairs without synthetic
   leakage?
2. What is the smallest memory state that preserves citation fidelity?
3. Does model-level memory add value beyond existing Mesh memory packets?
4. Can gradient-written memory be deterministic enough for audit?
5. Can sparse factual memory honor deletion, freshness, tenant, and
   contradiction rules?
6. Which failures must block promotion versus route to human review?
7. Which kernel has the best answer quality per byte of memory?
8. Which kernel has the best answer quality under p95 operator latency budgets?
9. Which paper claims fail when translated to Mesh operational evidence?
10. Which result would justify adding a control-plane `meshmodel-probe` route?

## Current Recommendation

Proceed in this order:

1. finish the research dossier and matrix;
2. define the benchmark plan and evidence packet;
3. implement deterministic baselines;
4. run context-removal tests on real Mesh artifacts;
5. add model-level memory only after baselines produce stable packets;
6. record any future MeshModel result as Mesh Brain governance evidence, never
   as production serving authority.
