# post-training

Model lifecycle plane extracted from Mesh: data refinery → training jobs → eval → serving.

This repo holds the `mesh_brain` Python package and its tests. It was split out of the Mesh monorepo with full git history (via `git subtree split`).

## Layout

```
mesh_brain/        # the package
tests/             # unit + integration tests (23 files)
docs/
  prd.md           # product requirements
  prd.pdf
  runtime.md       # runtime architecture
```

## What's in the package

The package covers the full post-training lifecycle:

- **Data refinery** (`data_plane.py`) — tenant filter → dedupe → redact → chunk → label, producing five row types: `sft`, `preference_pair`, `rl_trajectory`, `eval_case`, `red_team_case`.
- **Training jobs** (`training_jobs.py`) — declares method registry: `sft`, `lora`, `qlora`, `dpo`, `ipo`, `kto`, `agent_rl`, `quantization`, `qat`. Default hyperparams baked in.
- **Trainers** — `mlx_lm_lora_e2e.py` (real, shells out to `mlx_lm.lora`, defaults to `mlx-community/NVIDIA-Nemotron-3-Nano-4B-BF16`); `local_lora_sft.py` (stub, writes a JSON blob to a `.safetensors` file).
- **Eval** (`eval_jobs.py`, `eval_plane.py`, `judge_client.py`, `live_judge.py`).
- **Serving** (`serving.py`, `model_management.py`, `inference_catalog.py`, `adapter_runtime.py`).
- **Observability** (`observability.py`, `posttraining.py`, `posttraining_proof.py`).
- **MVP / E2E orchestration** (`mvp.py`, `run_mvp_e2e.py`, `run_live_serving_smoke.py`, `quality_training.py`, `live_quality_training.py`).

## What actually runs

Honest take: only the **MLX LoRA** path executes a real fine-tune. The rest of the algorithms in `JOB_METHODS` (DPO, IPO, KTO, QLoRA, agent_rl, QAT, quantization) are method stubs — the registry, hyperparams, and plumbing are wired up, but the trainer side is not implemented yet.

## Tests

```
pip install -e ".[dev]"
pytest
```

23 of the original 28 mesh-side test files were portable. Five were left behind in the Mesh repo because they import from `services.*` or `shared.mesh_runtime.*`:

- `test_mesh_brain.py` (tests a different module: `shared.mesh_runtime.mesh_brain`)
- `test_mesh_brain_control_plane.py`
- `test_mesh_brain_data_plane.py`
- `test_mesh_brain_live_quality_training.py`
- `test_mesh_brain_posttraining_proof.py`

Those tests cover the integration boundary, not the package itself, so they remain in Mesh.

## Dependencies

Runtime: stdlib only.

For the MLX LoRA path you'll need `mlx_lm` installed in the active Python environment — the package shells out to `python -m mlx_lm.lora`.

## Provenance

Extracted from `hydrogenbond007/mesh@mesh-brain` via `git subtree split --prefix=mesh_brain`.
