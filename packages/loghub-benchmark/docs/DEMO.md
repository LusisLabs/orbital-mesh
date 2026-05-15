# LogBench Demo

This demo is ready for the small in-repo example. It proves the core benchmark
path works without downloading the full Loghub corpus:

1. build cases from a log file
2. export Harbor-style task directories
3. run the verifier against an answer
4. import a result report

The demo is intentionally tiny. It is a smoke test for the benchmark mechanics,
not a publishable benchmark score.

## What The Demo Uses

Input data:

```text
examples/tiny.log
```

That file is included in the repo. The full Loghub corpus is not included; for
real benchmark runs, download or mount Loghub separately and pass its local path
to `--input`.

## Install

From the repository root:

```bash
python -m pip install -e .
```

Or run without installing by setting `PYTHONPATH=src` in the commands below.

## Build Demo Cases

```bash
mkdir -p .benchmark/demo

PYTHONPATH=src python -m loghub_benchmark.cli build \
  --dataset Tiny \
  --input examples/tiny.log \
  --output .benchmark/demo/cases \
  --max-cases 1
```

Expected output:

```text
case_count=1
manifest=.benchmark/demo/cases/manifest.json
```

The generated case will usually be `silver`, because `examples/tiny.log` has no
separate label file. That is fine for a demo.

## Export Harbor Tasks

```bash
PYTHONPATH=src python -m loghub_benchmark.cli export-harbor \
  --cases .benchmark/demo/cases \
  --output .benchmark/demo/harbor \
  --split full \
  --track all
```

Expected output:

```text
task_count=1
dataset=.benchmark/demo/harbor
oracles=.benchmark/demo/harbor/private_oracles
```

The export creates:

```text
.benchmark/demo/harbor/
  manifest.json
  metadata.yaml
  tasks/<case_id>/
    instruction.md
    task.toml
    environment/Dockerfile
    environment/logs/tiny.log
    tests/test.sh
    tests/verifier.py
  private_oracles/<case_id>.oracle.json
```

The oracle is intentionally outside the task directory. Do not expose
`private_oracles/` to the agent.

## Run The Verifier Directly

This is a local smoke test that simulates what a Harbor agent would do by
writing `/app/answer.json`.

```bash
CASE_ID="$(basename "$(find .benchmark/demo/harbor/tasks -mindepth 1 -maxdepth 1 -type d | head -1)")"
TASK_DIR=".benchmark/demo/harbor/tasks/$CASE_ID"
ORACLE=".benchmark/demo/harbor/private_oracles/$CASE_ID.oracle.json"

LINE_ID="$(python - <<PY
import json
payload=json.load(open("$ORACLE"))
print(payload["oracle"]["anomaly_line_ids"][0])
PY
)"

mkdir -p .benchmark/demo/manual

cat > .benchmark/demo/manual/answer.json <<JSON
{
  "schema_version": "loghub-sre-answer-v1",
  "is_incident": true,
  "anomaly_line_ids": ["$LINE_ID"],
  "root_cause_type": "timeout",
  "affected_component": "demo-service",
  "evidence": [
    {
      "line_id": "$LINE_ID",
      "quote": "ERROR timeout talking to storage",
      "reason": "The line contains the incident signal."
    }
  ],
  "recommended_action": "escalate",
  "confidence": 0.9
}
JSON

LOGHUB_HARBOR_ORACLE_PATH="$ORACLE" \
LOGHUB_HARBOR_ANSWER_PATH=".benchmark/demo/manual/answer.json" \
LOGHUB_HARBOR_VERIFIER_DIR=".benchmark/demo/manual/verifier" \
python "$TASK_DIR/tests/verifier.py"
```

The verifier writes:

```text
.benchmark/demo/manual/verifier/reward.json
.benchmark/demo/manual/verifier/grading_details.json
.benchmark/demo/manual/verifier/evidence_audit.json
```

For a correct answer, `reward.json` should contain a high reward, often `1.0`.

## Import A Demo Result

Create a tiny Harbor-like result directory:

```bash
mkdir -p ".benchmark/demo/job/$CASE_ID/trial-1"
cp .benchmark/demo/manual/verifier/reward.json .benchmark/demo/job/reward.json

python - <<PY
import json
from pathlib import Path
case_id = "$CASE_ID"
reward = json.load(open(".benchmark/demo/manual/verifier/reward.json"))
out = {
    "task_id": case_id,
    "verifier_result": {
        "rewards": {"reward": reward["reward"]},
        "details": reward["details"]
    },
    "cost_usd": 0.0,
    "latency_ms": 100
}
path = Path(".benchmark/demo/job") / case_id / "trial-1" / "result.json"
path.write_text(json.dumps(out, indent=2))
PY

PYTHONPATH=src python -m loghub_benchmark.cli import-results \
  --job .benchmark/demo/job \
  --output .benchmark/demo/results
```

The importer writes:

```text
.benchmark/demo/results/summary.json
.benchmark/demo/results/report.md
.benchmark/demo/results/metadata.yaml
```

The report includes mean reward, Pass@3, Pass^3, invalid answer rate,
zero-evidence diagnosis rate, citation precision/recall, cost, and latency.

## Real Loghub Run

For real data, first download or clone Loghub separately:

```bash
git clone --filter=blob:none --sparse https://github.com/logpai/loghub.git data/loghub
git -C data/loghub sparse-checkout set BGL HDFS Apache
```

Then build:

```bash
PYTHONPATH=src python -m loghub_benchmark.cli build \
  --dataset BGL \
  --input data/loghub/BGL \
  --output .benchmark/bgl \
  --max-cases 100000
```

Use `gold/eval` for publishable claims:

```bash
PYTHONPATH=src python -m loghub_benchmark.cli export-harbor \
  --cases .benchmark/bgl \
  --output .benchmark/bgl-harbor-eval \
  --split eval \
  --track gold
```

Use `silver` or `full` only for engineering/regression runs.

## Cloud Audit Status

The benchmark has been smoke-tested on the cloud machine against the public
Loghub sample checkout:

```text
/opt/mesh-benchmarks/runs/logbench-full-audit-20260515T110406Z
```

That audit generated `6,407` tasks across `16` sample datasets, with `1,927`
gold cases, `4,480` silver cases, and `0` oracle leaks. It validated benchmark
generation, partitioning, task export, verifier behavior, and result import.

It was not a full Harbor agent run, because the generic `harbor` CLI was not
installed on that VM.
