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

---

## Live demo (real Reth + Lighthouse in Docker)

For a credibility demo where the node is real, not synthesized:

```bash
# 1. Generate the JWT and bring up the stack (Reth + Lighthouse on Hoodi)
./simulation/bootstrap_demo.sh

# 2. Wait for Lighthouse to finish checkpoint sync (5-10 min on a fresh
#    machine; watch with: docker logs -f mesh-demo-lighthouse)

# 3. Run the live chaos cycle. Default sequence is 7 cycles × 60s ≈ 7 min.
uv run python -m simulation.run_real

# 4. Tear down
./simulation/bootstrap_demo.sh --kill
```

What's real:
- Reth and Lighthouse are real binaries in Docker on Hoodi testnet,
  with a real JWT-protected Engine API between them.
- ``simulation/run_real.py`` polls Reth via the production
  ``RethNodeIngester`` (same code path the watch daemon uses): real
  ``eth_syncing``, ``net_peerCount``, ``eth_blockNumber``,
  ``web3_clientVersion`` calls.
- Chaos primitives in ``simulation/chaos_real.py`` apply real
  Linux-level mutations:
  - ``peer_zero``: ``docker network disconnect`` — peer_count drops
  - ``engine_api_unreach``: ``docker stop`` on Lighthouse — forkchoice
    updates stop arriving
  - ``rpc_overload``: host-side curl loop hammering ``eth_getLogs``
  - ``jwt_world_readable``: ``chmod 0644`` on the JWT inside Reth
  - ``disk_pressure``: ``dd`` of a 1 GB filler in the datadir
  - ``all_clear``: no-op (baseline)
- Each chaos has a paired revert; the runner reverts the previous
  chaos before applying the next so symptoms don't compound.

What's still simulated:
- Validator-duty fields (``validator_attestation_pending``,
  ``validator_proposer_within_seconds``) — the demo doesn't load
  validator keys, so these stay null. Mesh's guards correctly treat
  null as "no opinion."
- The orchestrator's actuation step (``restart_systemd_service``)
  remains gated to the SSH-allowlist machinery — Mesh decides what
  to do, but the actual restart isn't executed against the demo
  container. To enable real actuation, set ``MESH_SSH_*`` env vars
  per the production runbook.

Output:
- Three log files in ``/tmp/mesh-demo/`` (``node.txt``, ``chaos.log``,
  ``mesh.log``) — same shape as the synthetic demo, viewable with
  ``./simulation/demo.sh`` panes or plain ``tail -F``.
- Markdown report at
  ``.mesh-runtime-state/simulation/live_real.md`` summarizing each
  chaos cycle: the live signal observed, Mesh's decision, observer
  verdict, and whether the observed signature matched the chaos's
  expected one.
