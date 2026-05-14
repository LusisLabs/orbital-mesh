# Loghub SRE Harbor Benchmark

Loghub SRE Harbor Benchmark turns local [Loghub](https://github.com/logpai/loghub)
datasets into Harbor-style offline SRE investigation tasks.

The benchmark is intentionally log-only. It evaluates whether an agent can:

- find incident/anomaly lines in large logs
- cite exact line IDs as evidence
- classify a bounded root-cause type
- recommend a safe SRE next step
- avoid hallucinated evidence and unsafe production mutations

## Tracks

- `gold`: label-backed cases only; use this for publishable claims.
- `silver`: heuristic regex anomaly cases; use this for regression and scale.
- `stress`: large-window cases for context, latency, and cost pressure.

## Install

```bash
python -m pip install -e .
```

The package uses only the Python standard library.

## Data

This repository does **not** include the full Loghub corpus. Loghub is a large
external dataset, so users download or mount it separately and point the
benchmark at the local files.

Good starting points:

- Loghub GitHub repository: `https://github.com/logpai/loghub`
- Loghub archive/mirror links referenced by the Loghub project

Expected local shape can be either a single log file:

```text
/data/loghub/Apache/Apache.log
```

or a dataset directory:

```text
/data/loghub/HDFS/
  HDFS.log
  anomaly_label.csv        # optional, when available
```

Label files are optional. If a CSV file whose name includes `label`,
`anomaly`, `groundtruth`, or `ground_truth` is present, positive rows are used
to create `gold` cases. Otherwise anomaly-looking lines become `silver` cases.

## Build Cases

```bash
loghub-benchmark build \
  --dataset HDFS \
  --input /path/to/loghub/HDFS \
  --output .benchmark/loghub-hdfs \
  --max-cases 1000
```

The build step writes deterministic case JSON under `cases/` plus a manifest.
If label/anomaly CSV files are present, matching positive rows become `gold`
cases. Unlabeled anomaly-looking lines become `silver` cases.

## Partitions

Each case receives a deterministic split from:

```text
sha256("<split-salt>:<case-id>") % 100
```

The default split map is:

- `smoke`: buckets `0-4`  (~5%)
- `dev`: buckets `5-24`  (~20%)
- `eval`: buckets `25-99` (~75%)
- `full`: not a stored split; export-time alias for all splits

The default salt is `mesh-loghub-harbor-v1`. Keep the salt fixed for published
benchmark releases so splits remain reproducible. Use `dev` for tuning and
`eval` for held-out reporting.

## Export Harbor Tasks

```bash
loghub-benchmark export-harbor \
  --cases .benchmark/loghub-hdfs \
  --output .benchmark/harbor-hdfs-eval \
  --split eval \
  --track gold
```

Generated tasks use:

- `instruction.md`
- `task.toml`
- `environment/Dockerfile`
- `environment/logs/*.log`
- `tests/test.sh`
- `tests/verifier.py`

Private oracle files are written separately under `private_oracles/`. Do not
mount or copy those into the agent-visible task environment.

The generated task directory intentionally does not contain the oracle answer.
During standalone verifier smoke tests, pass the oracle path with
`LOGHUB_HARBOR_ORACLE_PATH`. In a Harbor deployment, mount or inject the oracle
only for verifier execution.

## Import Harbor Results

```bash
loghub-benchmark import-results \
  --job /path/to/harbor/job \
  --output .benchmark/results
```

The importer writes `summary.json`, `report.md`, and `metadata.yaml`, including:

- mean reward
- Pass@3
- Pass^3
- invalid answer rate
- malformed answer rate
- zero-evidence diagnosis rate
- citation precision/recall
- cost and latency when present in Harbor results

## Answer Schema

Agents should write `/app/answer.json`:

```json
{
  "schema_version": "loghub-sre-answer-v1",
  "is_incident": true,
  "anomaly_line_ids": ["L000123"],
  "root_cause_type": "timeout",
  "affected_component": "worker-a",
  "evidence": [
    {
      "line_id": "L000123",
      "quote": "short evidence quote",
      "reason": "why this line matters"
    }
  ],
  "recommended_action": "escalate",
  "confidence": 0.87
}
```

Safe recommendation labels are `escalate`, `investigate`, `no_action`,
`open_incident`, and `page_owner`.

## Publication Boundary

Use `gold` for public claims. `silver` and `stress` are valuable engineering
tracks, but they are heuristic and should not be presented as leaderboard-grade
root-cause accuracy.

Recommended report language:

- Publishable: `gold/eval`, fixed commit, fixed split salt, fixed model/tool
  budget, repeated runs.
- Engineering-only: `silver`, `stress`, or ad hoc local corpora.
