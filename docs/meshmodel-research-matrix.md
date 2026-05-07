# MeshModel Research Matrix

This matrix converts the current architecture literature into MeshModel
adoption criteria. It is a research dependency map, not a dependency lockfile.
No listed project is a production dependency until it passes license,
reproducibility, security, hardware, and benchmark review.

## Reading Rules

- Prefer primary papers, official code, and official model cards.
- Treat blog posts and unofficial implementations as context only.
- Separate benchmark claims from Mesh evidence. A paper result is not a Mesh
  runtime result.
- Record both the capability and the failure mode.
- Track whether a method is useful as a baseline, prototype, compressor, memory
  writer, or future production candidate.

## Architecture Matrix

| Family | Source | Mechanism | Memory form | Maturity | Implementation status | Hardware/dependency notes | MeshModel use | Blocking risk |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Mamba | https://arxiv.org/abs/2312.00752 | Selective SSM | Recurrent state | Paper plus official code | Official PyTorch/CUDA repo exists | Linux, NVIDIA GPU, PyTorch, CUDA path in official README | SSM compressor baseline | Exact recall and citations may degrade |
| Mamba-2 / SSD | https://arxiv.org/abs/2405.21060 | Structured state-space duality | Structured recurrent state | ICML 2024 paper plus official code | Implemented in `state-spaces/mamba` | Same CUDA-heavy reference path | Core SSM reference | Paper links transformers and SSMs, so replacement framing is too simple |
| Mamba-3 | https://arxiv.org/abs/2603.15569 | Inference-first SSM refinements | Complex/MIMO recurrent state | 2026 paper and code path in official repo | Source install path noted in official README | Requires source install and GPU verification | Watch item for later SSM prototype | Too new for dependency without local reproduction |
| Titans | https://arxiv.org/abs/2501.00663 | Attention plus neural long-term memory | Neural memory module | Paper | Unofficial implementations only in current source set | Needs independent implementation review | Model-level memory design anchor | Persistence and overwrite policy need Mesh governance |
| GradMem | https://openreview.net/forum?id=GidQ1tmQ2G | Test-time gradient memory writing | Prefix/memory tokens | Paper plus secondary summary | GitHub link appears on HF paper page | Test-time optimization cost must be measured | Context-removal benchmark target | Compute, privacy, determinism |
| Gdwm | https://arxiv.org/abs/2601.12906 | Gated differentiable working memory | Transient adapted parameters | 2026 paper | No dependency selected | Budget controller is concept-level first | Write-budget control for GradMem-like memory | Utility estimator and gradient variance |
| Jamba | https://openreview.net/forum?id=JFPaD7lpBD | Transformer-Mamba-MoE hybrid | Attention KV plus SSM state plus MoE | ICLR 2025 poster | Public model weights are claimed by source | Large model footprint | Hybrid architecture evidence | Too heavy for immediate local baseline |
| RecurrentGemma | https://arxiv.org/abs/2404.07839 | Griffin recurrence plus local attention | Fixed-size recurrent state | Paper plus public model family | Official architecture note exists | Model availability and license must be checked before use | Fixed-state inference baseline | Long-range exact recall can degrade |
| RWKV | https://lfaidata.foundation/projects/rwkv/ | Attention-free RNN-like model | Recurrent state | Project and docs | Version-specific implementation review needed | Ecosystem differs from Mesh Brain stack | Attention-free baseline | Benchmark comparability and version drift |
| RetNet | https://arxiv.org/abs/2307.08621 | Retention mechanism | Retention state | Paper | Minimal/unofficial code exists | No production dependency selected | O(1) inference baseline | Claims need Mesh-local benchmark |
| Hyena | https://arxiv.org/abs/2302.10866 | Long convolution plus gating | Implicit convolution/filter state | Paper and related codebases | StripedHyena code exists separately | Separate stack and model format | Attention-free long-context baseline | Citation fidelity and exact recall |
| xLSTM | https://arxiv.org/abs/2405.04517 | Modern LSTM with exponential gating | Scalar/matrix memory | Paper and OpenReview | No dependency selected | Implementation review required | Recurrent memory baseline | May not beat transformer or SSM baselines |
| Memory Layers at Scale | https://arxiv.org/abs/2412.09764 | Sparse trainable KV memory | Trainable key-value table | Paper and OpenReview | No dependency selected | Needs training/runtime integration design | Sparse factual-memory reference | Staleness, tenant separation, deletion policy |

## Adoption Classification

| Class | Sources | Mesh action |
| --- | --- | --- |
| Immediate documentation inputs | Mamba, Mamba-2, Titans, GradMem, Gdwm, Memory Layers at Scale | Keep in docs and research registry only. |
| Deterministic benchmark influences | RetNet, RecurrentGemma, RWKV, xLSTM, Hyena | Use to shape simple recurrent/state baselines before importing code. |
| Later optional experiments | `state-spaces/mamba`, Titans unofficial PyTorch, minimal RetNet, StripedHyena | Use only in isolated experiments after license and hardware review. |
| Not production dependencies | All current sources | No runtime dependency until benchmark, license, security, and reproducibility gates pass. |

## Source Review Register

| Source | License/check status | Benchmark claim to verify | Mesh adoption guidance |
| --- | --- | --- | --- |
| Mamba | Paper citation allowed; official code license and CUDA build must be reviewed before use. | Linear sequence scaling, fast inference, and million-length behavior. | Implement deterministic SSM-like compression first; use official code only in isolated GPU experiment. |
| Mamba-2 / SSD | Paper citation allowed; official code path requires same dependency review as Mamba. | SSD layer speedup and competitive language-modeling behavior. | Treat as theory and SSM kernel reference, not proof of transformer replacement. |
| Mamba-3 | Paper citation allowed; source install and GPU path require fresh review. | State-tracking and performance-efficiency claims at 1.5B scale. | Watch item; no dependency until reproduced locally. |
| Titans | Paper citation allowed; unofficial code requires full review. | Long-term neural memory improves long-context and needle tasks. | Use to design memory write/read contract and overwrite policy. |
| GradMem | Paper citation allowed; code link from HF page requires review. | Test-time gradient writes outperform forward-only memory in context-removal tasks. | Use as primary context-removal benchmark shape. |
| Gdwm | Paper citation allowed. | Comparable or better long-context results with fewer gradient steps. | Use as write-budget and utility-controller reference. |
| Jamba | Paper/model references allowed; model license and hardware footprint require review before use. | Hybrid Transformer-Mamba-MoE throughput and long-context capability. | Use as hybrid evidence; too heavy for default local baseline. |
| RecurrentGemma | Paper and official explanation allowed; model license must be checked before execution. | Fixed-size recurrent state reduces memory use while keeping comparable quality. | Use to define recurrent/local-attention baseline requirements. |
| RWKV | Project/docs can be cited; implementation version and license require review. | Attention-free recurrent inference quality and efficiency. | Use as attention-free baseline class, not immediate dependency. |
| RetNet | Paper citation allowed; minimal code is unofficial and review-only. | Parallel training, recurrent O(1) inference, and chunkwise long-sequence mode. | Use to define retention/recurrent baseline behavior. |
| Hyena | Paper citation allowed; StripedHyena code requires review. | Long-convolution/gating speed and long-sequence recall. | Use as long-convolution baseline class. |
| xLSTM | Paper/OpenReview citation allowed; implementation dependency not selected. | Scalar/matrix memory and scaling behavior versus transformers/SSMs. | Use as modern recurrent memory baseline. |
| Memory Layers at Scale | Paper/OpenReview citation allowed. | Sparse KV memory improves factual tasks without dense-compute growth. | Use as sparse factual-memory reference; require freshness and tenant controls. |

## Benchmark Dependencies

External benchmarks are useful only when mapped to Mesh tasks.

| Benchmark family | What it tests | MeshModel mapping | Risk |
| --- | --- | --- | --- |
| Needle-in-haystack | Exact retrieval from long context | Operational fact recall across long run history | Can over-reward string matching |
| LongBench | Long-context QA and summarization | Cross-run recall and long evidence review | Generic tasks may not cover governance |
| RULER | Synthetic long-context diagnostic tasks | Controlled recall, aggregation, and tracking tests | Synthetic success may not transfer |
| BABILong | Long-context reasoning over facts | Context-removal and multi-hop memory QA | Limited operational realism |
| ZeroSCROLLS | Long-sequence summarization/QA | Research session and incident digesting | Summary quality can hide citation errors |
| InfiniteBench | Very long-context stress | Extreme run-history compression | Hardware and runtime cost can dominate |
| Internal Mesh corpus | Runs, events, memory packets, evaluations | Actual target workload | Must enforce tenant and data policy |

## Mesh Corpus Inputs

MeshModel should build its private corpus from existing first-party artifacts:

- run sessions;
- run events;
- trigger records;
- decision artifacts;
- evaluation artifacts;
- action records;
- feedback records;
- memory packets;
- observations, claims, relationships, and supersessions;
- operator notes;
- vault documents;
- research sessions under the configured research directory;
- Mesh Brain model-kernel, live-serving, posttraining, backend-matrix, and
  rollback-drill artifacts;
- production-readiness and go/no-go packets;
- Darkharness and Perennial proof packets where present.

Each source row needs:

- source type;
- source id;
- tenant scope;
- service scope;
- timestamp;
- data classification;
- retention class;
- training eligibility;
- evaluation eligibility;
- redaction status;
- citation pointer;
- content hash.

## Evidence Contract

Every MeshModel experiment should emit a result packet shaped like this:

```json
{
  "version": "mesh.meshmodel_probe.v1",
  "run_id": "run_example",
  "kernel": "ssm_summary_baseline",
  "benchmark_task": "context_removed_qa",
  "context_removed": true,
  "source_bundle_hash": "sha256:...",
  "answer": "bounded answer text",
  "supporting_observation_ids": [],
  "supporting_claim_ids": [],
  "citation_refs": [],
  "contradictions": [],
  "metrics": {
    "answer_correct": true,
    "citation_correct": true,
    "contradiction_detected": false,
    "memory_bytes": 0,
    "write_latency_ms": 0.0,
    "read_latency_ms": 0.0,
    "replay_deterministic": true
  },
  "policy": {
    "tenant_scope_verified": true,
    "data_classification_verified": true,
    "unsafe_action_claim": false
  }
}
```

## Kernel Evaluation Criteria

| Criterion | Pass condition |
| --- | --- |
| Accuracy | Beats deterministic baselines on target task class |
| Citation fidelity | Supports answer with exact source refs |
| Context removal | Answers without original context available |
| Contradiction handling | Finds stale or superseded claims |
| Freshness | Penalizes stale memory unless explicitly requested |
| Tenant isolation | Does not mix records across tenant boundaries |
| Data handling | Honors audit-only and no-training records |
| Replay | Produces stable packet under fixed inputs |
| Cost | Reports write/read latency and memory footprint |
| Governance | Cannot trigger action authority directly |

## Dependency Policy

Research inputs fall into four classes.

| Class | Meaning | Examples | Allowed use |
| --- | --- | --- | --- |
| Citation | Paper or documentation only | Mamba-2 paper, Titans paper, xLSTM paper | Architecture notes and benchmark design |
| Reference code | External code studied but not imported | state-spaces/mamba, stripedhyena | Isolated local experiment after review |
| Optional experiment | Dependency installed in a disposable environment | unofficial Titans PyTorch, minimal RetNet | Prototype only; no production runtime |
| Candidate substrate | Code that may become a real dependency | None yet | Requires license, security, tests, reproducibility |

No current source is a candidate production substrate.

## Research Questions

The first MeshModel research pass must answer:

1. Which kernel best compresses Mesh run evidence while preserving citations?
2. Which kernel best answers after context removal?
3. Which memory path handles contradictions and supersession best?
4. Does model-level memory beat Mesh memory packets, or only complement them?
5. Can gradient-written memory be made reproducible and affordable?
6. Can sparse factual memory remain tenant-safe and freshness-aware?
7. Which approach gives the best accuracy per byte of memory?
8. Which approach gives the best answer quality under operator latency budgets?
9. Which results are explainable enough for audit?
10. Which kernels fail safely when memory is stale, missing, or contradictory?

## Initial Implementation Backlog

| Step | Output | Notes |
| --- | --- | --- |
| Source bundle builder | `meshmodel_source_bundle.json` | Existing Mesh artifacts only |
| Baseline runner | lexical, graph, summary, long-context reference | Deterministic first |
| Benchmark schema | JSON task/result packets | Include replay hash |
| Context-removal task set | QA pairs from Mesh artifacts | Hide source context at answer time |
| Contradiction task set | stale/new claim pairs | Use supersession records where present |
| Memory-cost report | bytes, latency, context tokens | Compare all kernels |
| Research registry entries | source-to-plane mapping | Keep claims non-serving |
| Control-plane probe | later `meshmodel-probe` route | Evidence only, non-deployment |

## Current Conclusion

The literature supports a serious MeshModel lane, but it does not yet justify
claiming transformer replacement. The strongest direction is hybrid:

- SSM/recurrent state for efficient long-horizon compression;
- short attention or retrieval for local precision;
- model-level memory for compact context-removal answers;
- sparse memory for factual capacity;
- Mesh governance for provenance, contradiction handling, policy, approval, and
  audit.

That combination is the defensible MeshModel hypothesis.
