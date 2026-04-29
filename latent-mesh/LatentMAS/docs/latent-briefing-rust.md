# Latent Briefing Rust Core

This repository now includes a Rust crate that hardens the experiment layer around LatentMAS and adds a typed implementation boundary for Latent Briefing.

## Scope

The Rust core owns:

- Agent role definitions and default multi-agent topology.
- Local JSON and JSONL example loading.
- Prompt construction for sequential and hierarchical modes.
- Answer extraction and lightweight correctness checks.
- Task-guided compaction planning with shared token selection and MAD thresholding.
- A CLI bridge that can delegate model execution to the existing Python backend.
- Token-budgeted context windows to reduce repeated prior-agent context.

The Python backend still owns Hugging Face and vLLM model execution. That boundary is intentional: direct KV-cache mutation, CUDA tensor solves, and vLLM prompt embedding insertion depend on Python-first model APIs in the current repository.

## Latent Briefing Planner

`plan_task_guided_compaction` accepts per-head relevance scores over trajectory positions, optional head weights, and a MAD threshold.

The planner:

1. Validates that all heads have the same number of positions.
2. Uses uniform head weights when optimized head weights are unavailable.
3. Aggregates head scores into a single score per token position.
4. Computes `median + threshold * MAD`.
5. Retains all positions whose score is strictly greater than the cutoff.

This matches the research direction:

- Task-guided query vectors provide the relevance scores.
- Shared token selection enables batched downstream KV operations.
- MAD thresholding avoids hard-coding a top-k cache size.

## CLI

Rust dry run:

```bash
cargo run -- --method latent-briefing --task gsm8k --context-token-budget 2048
```

Use an exact tokenizer when evaluating context budgets:

```bash
cargo run -- --method latent-briefing --task gsm8k --context-token-budget 2048 --tokenizer-json /path/to/tokenizer.json
cargo run -- --method latent-briefing --task gsm8k --context-token-budget 2048 --sentencepiece-model /path/to/tokenizer.model
```

Run through the existing Python backend:

```bash
cargo run -- --python-backend --method latent-mas --model-name Qwen/Qwen3-14B --task gsm8k -- --max_samples 1
```

The arguments after `--` are passed directly to `run.py`.

## Context Token Budgeting

TextMAS previously exposed `--text_mas_context_length`, but prompt construction sliced characters directly and `-1` dropped the final character. The runtime now applies tokenizer-aware context trimming before prompt construction.

The Rust boundary is `latentmas::tokenizer::MeshTokenizer`. It supports:

- Hugging Face `tokenizer.json` files through the Rust `tokenizers` crate.
- SentencePiece `.model` files through the Rust `sentencepiece` binding.
- The legacy four-characters-per-token estimate as an explicit fallback when no tokenizer model is configured.

Budget trimming uses binary search over UTF-8 character boundaries and re-tokenizes candidates with the configured backend. That keeps retained text valid while enforcing model-specific token counts for both head and tail retention.

Mesh packages this boundary through `services.evaluation.mesh_eval`. Native
trajectory artifacts include a `mesh_eval` section that records the LatentMAS
crate path, context token budget, tokenizer backend, and Rust CLI arguments used
to reproduce the same token-budget policy.

Use:

```bash
python run.py --method text_mas --model_name Qwen/Qwen3-14B --task gsm8k --text_mas_context_tokens 2048
```

Set `--text_mas_context_tokens -1` to disable token trimming. The legacy `--text_mas_context_length` remains available as a character cap after token trimming.

The Rust CLI forwards `--context-token-budget` to the Python backend as `--text_mas_context_tokens`.

## Public API

Important public modules:

- `latentmas::agents`
- `latentmas::briefing`
- `latentmas::context`
- `latentmas::data`
- `latentmas::eval`
- `latentmas::prompts`
- `latentmas::run`
- `latentmas::tokenizer`

Behavior-changing utilities should be documented here when extended.
