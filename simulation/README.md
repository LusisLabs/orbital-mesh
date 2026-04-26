# Mesh fault-injection simulation

Drive a synthetic Reth node through Mesh's full pipeline (ingest →
trigger → evidence → decision → observer) and produce a markdown
report scored against expected outcomes.

The simulation is shaped around **AI reasoning quality**, not
deterministic-policy verification. The unit tests already cover the
deterministic floor; this harness exists to answer:

- Does the LLM observer cite specific evidence (`execution.peer_count=0`)
  in its reason field, or does it reason from vibes?
- Does it promote to `escalate` / `reject_unsafe` /
  `request_more_evidence` when the fault demands it?
- Does it stay calm on transient faults that should be left alone?
- How does latency hold up across a long burst of faults?

## Running

```bash
# Default: full catalog with the Anthropic Claude observer.
export ANTHROPIC_API_KEY=sk-ant-...
python -m simulation

# Default model is claude-sonnet-4-6; switch to Haiku for faster + cheaper:
MESH_OBSERVER_MODEL=claude-haiku-4-5-20251001 python -m simulation

# Cron mode: pick faults at random for 10 minutes.
python -m simulation --mode cron --duration 600 --interval 15

# Deterministic only — observer not called.
python -m simulation --no-observer

# OpenAI / vLLM / Ollama / Together: any /v1/chat/completions endpoint.
OPENAI_API_KEY=... python -m simulation \
  --observer-provider openai \
  --observer-base-url https://api.openai.com \
  --observer-model gpt-4o-mini

# Bound to first N faults for debugging.
python -m simulation --limit 5
```

Reports land in `.mesh-runtime-state/simulation/sim_<mode>_<UTC>.md`
and are also printed to stdout.

## What's in the catalog

26 fault scenarios across:

| category | examples |
|---|---|
| peer | zero peers / RPC up, peers below floor, transient dip |
| sync | clean stall, stall+disk, stall+consensus disconnect, catching up |
| disk | 92% pressure, 99% critical, 85% warning |
| rpc | error rate spike, publicly exposed overload, unreachable, high latency |
| consensus | engine API down, forkchoice stale, JWT missing, JWT world-readable |
| exposure | authrpc exposed, RPC publicly exposed without overload |
| release | snapshot restoring (must not be touched) |
| cascade | peer-zero+EAPI-down, sync+disk+JWT |
| policy | restart frequency exceeded |
| noise | log warnings without real failure, pristine baseline |

Each scenario carries an `expected_outcomes` set (e.g.
`("escalate",)` for hard-unsafe faults; `("escalate", "no_action")`
for ambiguous ones). The driver scores both the deterministic
decision and the LLM observer's verdict against this set.

## Observer-quality scoring

For each run where the observer ran successfully:

- **Promoted?** — did the verdict force escalation
  (`escalate`, `reject_unsafe`, `request_more_evidence`)?
- **Cited evidence?** — did the reason field include at least one
  path-shaped reference into the pack
  (`execution.peer_count`, `rpc.error_rate`, `consensus.engine_api_reachable`)?
  This is a heuristic for groundedness, not perfect, but useful.
- **Promoted when expected?** — for faults whose only acceptable
  outcome is `escalate`, did the observer promote? This is precision-
  on-promotion.

## Rate limits

Anthropic's per-minute quotas (10 RPM on free / low tiers) are tighter
than a tight loop wants. Sweep mode defaults to a 7s gap between
faults when the observer is on. Override with `--inter-delay`. The
client also retries once on 429/5xx with `Retry-After` honored.

## Determinism

Cron mode picks faults via a seeded RNG (default `42`). Sweep mode
runs the catalog in source order. Observer responses themselves are
not deterministic — that's the point of the simulation: see whether
the LLM's variance keeps it inside the safety envelope.
