# Mesh Brain Runtime Slice

`mesh_brain/` implements the first Mesh Brain control surface from the PRD:

- data refinery rows for SFT, preference, RL trajectory, eval, and red-team outputs;
- deterministic training manifests with signed lineage references;
- model artifact registration with signed manifest requirements;
- training job launchers for SFT, LoRA/QLoRA, DPO/IPO/KTO, agent RL, quantization, and QAT;
- eval-gated canary and promotion decisions;
- rollback metadata for promoted artifacts;
- hardware-aware serving-route selection;
- runtime tool-policy enforcement, approval routing, audit events, and trace-to-dataset export;
- Mesh-compatible observability records for model, adapter, engine, tenant, task type, token, cache, eval, and policy-route labels;
- a deterministic model-kernel probe for micro-transformer math, fixed-point drift, and tiny batch-1 runtime guidance;
- a private AI CROPS MVP orchestration that proves the PRD acceptance path end to end.

This slice does not start vLLM, SGLang, Dynamo, MLX, or llama.cpp. It produces the registry state and routing decisions that later service adapters can consume.

`shared.mesh_runtime.mesh_brain` remains a compatibility import path. New code should import from `mesh_brain`.

## End-to-End Reference Flow

`run_e2e_reference_flow()` exercises the MVP control loop:

1. Convert source records into the five required dataset outputs.
2. Build a LoRA training manifest with dataset and code lineage.
3. Register a tenant adapter with a signed manifest reference.
4. Run the release gate and promote only after the canary metric passes.
5. Select a hardware-aware serving route for a high-risk CROPS task.
6. Route a protected tool call through policy and approval checks.
7. Export the runtime trace as an RL trajectory dataset row.

`run_private_crops_mvp_e2e()` exercises the fuller PRD MVP:

1. Build at least 50 golden CROPS eval cases from runbook and incident records.
2. Register one Qwen 27B-class base model and one previous production tenant adapter.
3. Launch one QLoRA adapter job.
4. Run candidate-vs-production eval jobs on the NVIDIA/SGLang target tier.
5. Canary the adapter only after eval pass.
6. Plan an OpenAI-compatible SGLang serving request.
7. Run one Mesh-OS supervised worker-lane task through schema validation, policy, approval, and audit.
8. Export the runtime trace as an RL trajectory dataset row.
9. Roll back the canary alias to the prior production adapter.
10. Emit Mesh-compatible observability JSON and Prometheus text for the request path.

Run the persisted local artifact generator with:

```bash
python3 -m mesh_brain.run_mvp_e2e --output .mesh-runtime-state/mesh-brain/mvp-e2e
```

It writes:

- `run_summary.json`;
- `mvp_workflow.json`;
- `mvp_acceptance_report.json`;
- `trace_dataset_row.json`;
- `data/dataset_manifest.json`;
- `data/sft.jsonl`;
- `data/eval_cases.jsonl`;
- `training/training_job.json`;
- `training/deployment_manifest.json`;
- `eval/eval_job.json`;
- `serving/serving_plan.json`;
- `observability/mesh_brain_metrics.prom`;
- `catalog/model_catalog_snapshot.json`.

## Control-Plane Lane

`RunCoordinator.run_mesh_brain_mvp()` records the deterministic MVP as a first-class Mesh run instead of a package-only command. The HTTP hook is:

```http
POST /api/mesh-brain/mvp-runs
```

The run session stores these normalized artifact keys:

- `mesh_brain_dataset_manifest`;
- `mesh_brain_training_job`;
- `mesh_brain_eval_job`;
- `mesh_brain_serving_plan`;
- `mesh_brain_runtime_trace`;
- `mesh_brain_observability_metrics`;
- `mesh_brain_catalog_snapshot`.

The session also stores `mesh_brain_run_record`, which includes run id, tenant id, stage/status, artifact refs, audit events, policy events, summary metrics, and final release decision. A blocked eval marks the deployment record as blocked and non-deployed. `/metrics` appends the latest Mesh Brain Prometheus samples from recorded Mesh Brain runs.

Live model-call smoke can be recorded as a Mesh run with:

```http
POST /api/mesh-brain/live-serving-smoke
```

The live serving run stores:

- `mesh_brain_live_serving_execution`;
- `mesh_brain_live_smoke_gate`;
- `mesh_brain_live_response_eval`;
- `mesh_brain_live_judge_eval`;
- `mesh_brain_live_release_gate`;
- `mesh_brain_live_serving_summary`;
- `mesh_brain_live_serving_record`.

That record preserves the served model id, backend, hardware tier, request id, completion id, token usage, finish reason, latency, gate decision, response-eval decision, judge-eval decision, release-gate decision, deployment eligibility, reasons, and content preview. The infrastructure gate, semantic response eval, and rubric-bound judge eval all emit `pass`, `manual_review`, or `block`; the release gate combines them with the deterministic release decision and emits `block`, `manual_review`, `canary`, or `promote`.

Backend matrix smoke can be recorded as a Mesh run with:

```http
POST /api/mesh-brain/backend-matrix
```

The matrix run stores:

- `mesh_brain_backend_matrix_results`;
- `mesh_brain_backend_matrix_summary`;
- `mesh_brain_backend_matrix_record`.

Each target uses the same OpenAI-compatible live smoke path, including infrastructure gate, response eval, judge eval, and release gate. The aggregate status is `block` if any target blocks, `manual_review` if any target requires review, and `pass` only when every enabled target is promotable or canary-eligible.

Posttraining proof can be recorded as a Mesh run with:

```http
POST /api/mesh-brain/posttraining-proof
```

The posttraining proof run stores:

- `mesh_brain_posttraining_dataset_manifest`;
- `mesh_brain_posttraining_training_job`;
- `mesh_brain_posttraining_backend_result`;
- `mesh_brain_posttraining_registered_artifact`;
- `mesh_brain_posttraining_adapter_export`;
- `mesh_brain_posttraining_eval_job`;
- `mesh_brain_posttraining_serving_smoke`;
- `mesh_brain_posttraining_deployment_record`;
- `mesh_brain_posttraining_proof_record`.

`mesh_brain.posttraining_proof` adds `MeshBrainTrainingBackend`, `DeterministicTrainingBackend`, and `LocalSubprocessTrainingBackend`. The default proof executes a real local subprocess command, `python -m mesh_brain.local_lora_sft`, against the Mesh Brain data-plane manifest. That manifest now includes the deterministic reference row plus incident-corpus rows from `corpus_database_path` and current control-plane runtime sessions/events when invoked through `POST /api/mesh-brain/posttraining-proof`. The command writes adapter/config files and backend metrics, then Mesh Brain registers the produced adapter, records an Apple Silicon `mlx_lm_lora` adapter export manifest, runs the eval job gate, and smoke-serves the resulting artifact through the model-client boundary. Failed training commands block before artifact registration, adapter export, eval, or serving.

`mesh_brain.hardware_profiles` records backend-specific adapter export manifests. The Apple Silicon target uses `mlx_lm_lora`: training command metadata points at `mlx_lm_lora.train --train-mode sft --train-type lora`, generation command metadata points at `mlx_lm.generate --adapter-path`, and the compatibility record marks `supports_runtime_adapter_load` as false because adapter selection is a process or generation-command boundary for this path.

`mesh_brain.adapter_runtime` verifies adapter file presence, registered hashes, and base-model compatibility before serving. The posttraining proof smoke now loads the trained adapter through that runtime, records adapter readiness, and only reports `smoke_served` after adapter verification, load/readiness, and inference all pass. The OpenAI-compatible adapter runtime supports a fake llama.cpp/MLX-style server contract with `/health`, `/v1/models`, `/v1/adapters/load`, and `/v1/chat/completions`; live MLX/llama.cpp smoke should use that boundary when the backend exposes adapter loading.

Live adapter capability can be recorded through:

```http
POST /api/mesh-brain/live-adapter-runtime-probe
```

The probe checks `/v1/models`, runs a base-model `/v1/chat/completions` request, evaluates the response, and probes `/v1/adapters/load`. If adapter loading is unsupported, the run can only report `base_model_pass`; it never counts as trained-adapter serving. It reports `adapter_pass` only when adapter loading succeeds and the loaded adapter appears in `/v1/models`.

The real Apple Silicon MLX LoRA lane can be recorded through:

```http
POST /api/mesh-brain/mlx-lm-lora-e2e
```

This lane wraps `mesh_brain.mlx_lm_lora_e2e`. It prepares MLX-LM-LoRA `messages` JSONL splits from the Mesh Brain data plane, runs `mlx_lm_lora.train` against `mlx-community/NVIDIA-Nemotron-3-Nano-4B-BF16`, records native `mlx_lm.generate` inference, writes an `mlx_lm_lora` adapter export manifest, and stores backend compatibility for `mlx_lm_lora.train`, `mlx_lm.generate`, and `mlx_lm.server`. Native MLX is the source-of-truth serving path for this model family. Promotion requires native train/generate/server checks plus Mesh response eval; LM Studio can be recorded only as optional compatibility metadata and is not promotion-blocking.

## Data Plane

`mesh_brain.data_plane` implements the first organized PRD plane. `MeshBrainDataRefinery` accepts source records, rejects records for other tenants, removes duplicates, redacts secret-like material, chunks content, extracts tool-call schemas, labels outcomes, and writes the five required JSONL outputs plus `dataset_manifest.json`. `build_context_training_data_plane()` is the posttraining ingestion path for mixed context: reference records, incident-corpus rows, runtime run sessions, and runtime run events. Public corpus rows are included for context and eval coverage, but remain audit-only unless their catalog metadata explicitly allows training use.

`build_data_plane_e2e()` is the deterministic reference path for this plane. It proves:

- one duplicate source record is skipped;
- one cross-tenant source record is rejected;
- redacted rows never retain the raw secret value;
- tool calls are converted into strict JSON schemas;
- every output row carries tenant, source, timestamp, redaction status, license/usage class, and provenance pointer.

## Posttraining Plane

`mesh_brain.posttraining` turns a `DatasetBundle` into a signed deployable artifact plan. `TrainingJobSpec` validates the training method, tenant isolation, trainable row availability, and shared-adapter approval requirements before any artifact is emitted.

`build_posttraining_e2e()` proves:

- LoRA training produces a signed manifest reference;
- trainable lineage excludes audit-only rows;
- cross-tenant rows block training;
- shared adapters require customer and legal approval evidence;
- artifact, lineage graph, rollback manifest, and model card files are written together;
- every model card marks eval as required before deployment.

## Training Jobs

`mesh_brain.training_jobs` exposes the functional training surface from the PRD. It launches SFT, LoRA/QLoRA, DPO/IPO/KTO, agent RL rollout, quantization, and QAT jobs while reusing the posttraining plane for signed manifests, lineage, rollback, and model-card generation.

`build_training_jobs_e2e()` proves:

- each job records dataset version, code version, base artifact, hyperparameters, hardware tier, metrics, and output artifacts;
- preference jobs require preference-pair rows;
- agent RL jobs require RL trajectory rows;
- quantization and QAT emit quantized checkpoint deployment outputs;
- every job writes `training_job.json`, `model_card.json`, `deployment_manifest.json`, and `metrics.json`;
- deployment manifests require a release gate before serving.

## Quality Training

`mesh_brain.quality_training` is the promotion-grade training gate above the deterministic proof runs. It builds curated runtime/corpus datasets from reference records, incident-corpus rows, control-plane run sessions, and runtime events. It writes SFT, preference, eval, red-team, and provenance rows so the training set is auditable before any adapter can be promoted.

The quality plan records:

- a measurable SFT stage with row count, iteration count, train/validation loss trend, NaN checks, and adapter checkpoint gate;
- a DPO or ORPO preference stage with preference-pair count, iteration count, margin metric, and NaN checks;
- concrete runtime evidence that adapter files were created and native inference completed;
- a deterministic or injected LLM-as-judge comparison between base and adapter responses on Mesh policy/evidence tasks;
- side-by-side policy-boundary, evidence-grounding, approval-gating, and unsupported-action-claim rubric scores;
- a red-team regression gate that blocks unsafe adapter behavior;
- a promotion gate that only promotes when SFT passed, runtime adapter evidence passed, preference training passed, the adapter beats base on aggregate and rubric-specific checks, and no red-team regression is found.

`run_quality_training_plan()` writes `quality_dataset.json`, `quality_sft_stage.json`, `quality_preference_stage.json`, `quality_runtime_evidence.json`, `quality_eval_comparison.json`, `quality_promotion_gate.json`, and `quality_training_result.json`. It also writes JSONL split artifacts for `quality_sft_messages`, `quality_preference_pairs`, `quality_eval_prompts`, `quality_red_team_prompts`, and `quality_provenance`, plus a pinned `quality_split_manifest`. This is the quality-control contract for longer MLX or GPU training runs; it does not claim that a long live DPO/ORPO run has already been executed.

Run the live Apple Silicon quality-training path with:

```bash
PYTHONPATH=. python3 -m mesh_brain.live_quality_training \
  --output .mesh-runtime-state/mesh-brain/live-quality-training-nemotron \
  --model mlx-community/NVIDIA-Nemotron-3-Nano-4B-BF16 \
  --sft-iters 20 \
  --preference-iters 8 \
  --preference-method orpo \
  --json
```

The live runner writes MLX SFT and preference datasets, executes `mlx_lm_lora.train` for SFT and ORPO/DPO, runs native `mlx_lm.generate`, runs held-out prompts against base and adapter, and feeds the real responses into the quality gate. If MLX saves adapter weights but fails while writing fused full-model shards, Mesh Brain treats the adapter as usable only when the adapter file exists and native inference succeeds; the post-save failure remains visible in the command record.

The live runner also combines local Mesh corpus sources before training:

- `.mesh-runtime-state/corpus/incident_corpus.sqlite`;
- recent `corpus.jsonl` rows under `.mesh-runtime-state/reth-kurtosis-loop`;
- breakthrough evidence corpus rows;
- cleaned public monitoring-corpus rows.

Those rows are not fed to MLX as raw JSON. Mesh Brain synthesizes clean instruction examples from the source evidence, writes `clean_sft_messages.jsonl`, `clean_preference_pairs.jsonl`, `clean_eval_prompts.jsonl`, and `clean_provenance.jsonl`, and trains/evaluates on those clean examples while retaining source provenance.

## Inference Catalog

`mesh_brain.inference_catalog` encodes the backend matrix from `sota_llm_inference_repos_by_hardware (1).html`. It records hardware support, model families, techniques, category, and default/secondary roles for vLLM, SGLang, Dynamo, TensorRT-LLM, NVIDIA Model Optimizer, FlashInfer, llm-d, llama.cpp, MLX, vllm-mlx, GPTQModel, inference research lists, optillm, and flash-llm.

Use `backend_capability_report()` to prove whether a hardware tier can satisfy required techniques such as prefix caching, speculative decoding, disaggregated prefill/decode, constrained decoding, KV offload, quantization, or CUDA/Metal-specific paths.

## Research Registry

`mesh_brain.research_registry` records non-serving research influences separately from the inference backend catalog. It maps research sources to Mesh Brain planes, capabilities, adoption guidance, MVP relevance, and risks so research references do not become implicit product commitments.

The registry currently covers:

- NVIDIA NeMo RL for bounded agent RL orchestration;
- NVIDIA Megatron-LM for future distributed training scale;
- MegaBlocks for MoE and block-sparse expert-routing influence;
- Google Research as a broad research reference corpus;
- Google DeepMind OpenSpiel and Acme for RL environment and agent-loop structure;
- Nydhal/microgpt.apl for explicit micro-transformer math and gradient-check discipline;
- AlexCheema/talos-vs-macbook for tiny batch-1 runtime-overhead and fixed-point drift guidance;
- OpenAI evals and EleutherAI lm-evaluation-harness for eval registry and benchmark-harness influence.

`research_capability_report()` proves which sources cover required capabilities for a plane. `research_adoption_plan()` keeps open-ended RL and MoE work deferred from the MVP unless a later phase explicitly promotes that work.

## Eval Plane

`mesh_brain.eval_plane` evaluates a candidate artifact against dataset-derived eval and red-team cases, aggregates release metrics, checks required backend capabilities, and emits an `EvalSuiteResult` plus release gate. Backend capability gaps are treated as deployment blockers because the PRD requires hardware-aware serving economics, not only model quality.

`build_eval_plane_e2e()` proves:

- eval cases are derived from `eval_cases.jsonl` and `red_team_cases.jsonl` rows;
- the selected default backend comes from the inference catalog;
- missing required backend techniques block deployment;
- passing task, policy, schema, latency, cost, and backend checks produces a promotable release gate.

## Eval Jobs

`mesh_brain.eval_jobs` is the job-level PRD surface above the eval plane. It runs eval suites for any candidate artifact across one or more hardware tiers, compares the candidate against the current production artifact, runs sandbox tool-use checks, runs policy and red-team checks, and aggregates latency/cost outcomes into a single release decision.

`build_eval_jobs_e2e()` proves:

- candidate and production artifacts are compared before release;
- sandbox tool-use evals are required for CROPS/tool workflows;
- policy and red-team cases are reported separately;
- latency and cost are reported for each hardware tier;
- missing backend capabilities block release;
- insufficient improvement over production routes to `manual_review`;
- final job decisions are one of `block`, `canary`, `promote`, or `manual_review`.

## Serving Plane

`mesh_brain.serving` plans OpenAI-compatible chat requests against healthy serving pools, tenant quotas, artifact state, canary weight, and backend capability requirements. It does not start the underlying engine; it produces deterministic serving plans and request traces that can later wrap SGLang, vLLM, Dynamo, TensorRT-LLM, llama.cpp, MLX, or vllm-mlx.

`mesh_brain.model_client` adds the model-call boundary for that plan:

- `MeshBrainModelClient` defines the chat-completion interface;
- `DeterministicMeshBrainModelClient` returns stable local completions for tests and replay;
- `OpenAICompatibleMeshBrainModelClient` posts `/v1/chat/completions` requests to an OpenAI-compatible backend and normalizes the response;
- `MeshBrainServingFabric.execute_chat_completion()` plans the route, calls the injected client, and returns a `ServingExecution` trace.

Run a live OpenAI-compatible smoke against a local MLX endpoint with:

```bash
PYTHONPATH=. python3 -m mesh_brain.run_live_serving_smoke \
  --base-url http://127.0.0.1:1234 \
  --model nvidia/nemotron-3-nano-4b \
  --hardware-tier apple_silicon \
  --tenant-id tenant_a \
  --output .mesh-runtime-state/mesh-brain/live-serving-smoke \
  --json
```

The smoke writes `live_serving_execution.json`, `live_smoke_gate.json`, `live_response_eval.json`, `live_judge_eval.json`, `live_release_gate.json`, and `live_serving_summary.json`.

`mesh_brain.live_judge` adds a judge boundary for local smoke runs. The CROPS rubric scores evidence grounding, bounded reversible remediation, operator approval, unsupported execution claims, and concision. It also runs an order-swap consistency check so criterion order cannot change the release decision.

`mesh_brain.judge_client` defines `MeshBrainJudgeClient`, `DeterministicMeshBrainJudgeClient`, and `OpenAICompatibleMeshBrainJudgeClient`. Live smoke can use `--judge-base-url` and `--judge-model` to call a model-backed judge through `/v1/chat/completions`; Mesh Brain still applies the local rubric guardrail so a permissive model judge cannot override unsupported execution claims.

`mesh_brain.backend_matrix` runs the same live smoke across multiple OpenAI-compatible targets and writes `backend_matrix_results.json` plus `backend_matrix_summary.json`. The aggregate status is `block` if any backend blocks, `manual_review` if any backend needs review, and `pass` only when every enabled backend is promotable or canary-eligible.

`mesh_brain.live_feedback` turns blocked or manual-review live runs into data-plane feedback. It emits the existing five dataset row families from the failed/manual run context, including SFT, preference, RL trajectory, eval, and red-team rows. Promoted or canary-eligible runs are recorded as skipped feedback and do not create training rows.

## Model Kernel Probe

`mesh_brain.model_kernel_probe` integrates bounded lessons from `Nydhal/microgpt.apl` and `AlexCheema/talos-vs-macbook` without vendoring either project or adding runtime dependencies. The probe is intentionally tiny and deterministic. It is a Mesh Brain gate, not a production throughput benchmark.

The correctness probe checks:

- full-sequence causal attention versus token-by-token KV-style forward parity;
- explicit matrix gradients against finite-difference gradients;
- one Adam step reduces the fixed reference loss;
- Q4.12 fixed-point weight quantization stays below the configured logit-drift threshold.

The runtime probe executes only a pure-Python local reference and records guidance targets for Apple Silicon native CPU, MLX GPU, and Q4.12 fixed-point paths. Those guidance rows are profile-only until a real backend smoke or load artifact measures the target environment.

Run it directly:

```bash
PYTHONPATH=. python3 -m mesh_brain.run_model_kernel_probe \
  --output .mesh-runtime-state/mesh-brain/model-kernel-probe \
  --benchmark-iterations 2000 \
  --json
```

It writes `model_kernel_correctness.json`, `model_kernel_runtime_benchmark.json`, `model_kernel_gate.json`, and `model_kernel_probe_summary.json`. `run_quality_training_plan()` now runs this probe by default and includes `quality_model_kernel_probe.json`; promotion is blocked if the model-kernel gate fails.

`mesh_brain.readiness_gaps` writes an explicit readiness report for the remaining non-MVP work. It marks live smoke ready, but full posttraining execution and MoE training/serving not ready until longer quality-training jobs and sparse-expert proofs exist.

`build_serving_fabric_e2e()` proves:

- high-risk requests route through verification mode and constrained decoding;
- streaming and structured-output flags are preserved;
- serving execution crosses the model-client boundary;
- tenant adapters are selected by tenant and task;
- tenant quotas block excess requests;
- adapter hot-swap and rollback update routing state;
- engine metrics include health, backend, cache metrics, and prefill/decode split metadata.

## Multi-Hardware Profiles

`mesh_brain.hardware_profiles` implements the Phase 4 multi-hardware serving surface without starting real engines. It builds smoke profiles from the inference catalog, records supported and unsupported features per tier, and emits quantization export manifests tied to an eval baseline.

`run_multi_hardware_smoke()` proves:

- NVIDIA datacenter, Apple Silicon, and CPU/edge tiers can produce smoke profiles;
- each tier declares its default backend and required features;
- unsupported features are explicit blockers;
- quantization export manifests track target hardware, export format, source artifact, output artifact, quality baseline eval report, and expected quality delta;
- reports can be written as `multi_hardware_smoke.json`, `hardware_profiles.json`, and `quantization_exports.json`.

## Agent Runtime Plane

`mesh_brain.agent_runtime` implements the Mesh-OS control loop. The model can propose a tool call or memory write, but the runtime owns schema validation, permission checks, policy decisions, approval routing, audit events, replay, eval-signal collection, and feedback collection.

`build_agent_runtime_e2e()` proves:

- protected high-risk actions route to approval before execution;
- invalid tool-call schemas block execution;
- role permission failures block execution;
- every tool execution has prior schema and policy audit events;
- memory writes are proposed, reviewed, and versioned;
- replayed traces can be exported as RL trajectory rows for eval and posttraining.

## Observability Adapter

`mesh_brain.observability` does not replace Mesh's existing OTEL ingest, metric-action rules, Phoenix trace helpers, or agent SLO export. It is a thin adapter that converts Mesh Brain serving, eval, and runtime outputs into Mesh-compatible records and Prometheus text.

`build_mesh_brain_observation()` proves the PRD observability labels are present:

- model;
- adapter;
- engine;
- tenant;
- task type;
- token count;
- cache hit rate;
- eval outcome;
- policy route.

## Model and Adapter Management

`mesh_brain.model_management` manages base models, tenant adapters, task adapters, quantized variants, lineage, aliases, and deployment state transitions. It keeps canary, promote, rollback, and retire behavior deterministic so serving can resolve an artifact route without owning model governance.

`build_model_management_e2e()` proves:

- base model, tenant adapter, and quantized checkpoint registration;
- release-gated promotion into a tenant/task alias;
- route resolution by tenant, task, hardware tier, risk, and structured-output need;
- artifact lineage lookup;
- catalog snapshot export;
- rollback target preservation across canary-to-production promotion.

## Artifact Registry

Deployable artifacts must include `signed_manifest_ref`. This applies to base models, adapters, quantized checkpoints, and draft models. The registry stores artifacts under:

```text
<state_directory>/mesh_brain/registry.json
```

Use `MeshBrainRegistry.register_artifact()` to add an artifact and `MeshBrainRegistry.promote_artifact()` to move a candidate into `canary` or `production`.

Promotion requires a `ReleaseGateResult` for the same artifact. A blocked gate result raises `ValueError` and does not mutate registry state.

## Release Gate

`evaluate_release_gate()` maps eval metrics to one of:

- `block`: critical policy regression, unsafe autonomous action-rate regression, schema-validity regression, task success below threshold, latency over budget, or cost over budget.
- `canary`: offline gates pass, but canary has not passed yet.
- `promote`: offline gates pass and `canary_passed=true`, or the policy does not require canary pass.

The gate is intentionally conservative. It treats policy and unsafe-action regressions as blockers even when task success improves.

## Rollback

When a new production artifact replaces an existing alias, the promoted artifact records `rollback_artifact_id`. `MeshBrainRegistry.rollback(alias)` retires the current artifact and restores the rollback target to production.

## Serving Route

`select_serving_route()` maps request context to the PRD hardware strategy:

| Hardware tier | Default engine | Secondary engine |
| --- | --- | --- |
| `nvidia_datacenter` | `sglang` | `vllm` |
| `nvidia_large_cluster` | `dynamo` | `llm-d` |
| `nvidia_consumer` | `vllm` | `sglang` |
| `amd_rocm` | `vllm` | `sglang` |
| `apple_silicon` | `mlx` | `vllm-mlx` |
| `cpu_edge` | `llama.cpp` | none |

High-risk requests use verification mode and constrained decoding. Long-context requests enable chunked prefill and KV-aware routing. CPU/edge routes disable continuous batching.
