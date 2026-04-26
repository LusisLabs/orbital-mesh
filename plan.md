# Mesh demo — runbook

A 3-minute side-by-side terminal demo. One tmux session with three
panes (node state, chaos injector, Mesh decisions), one Python
runner that drives the whole thing.

```
┌──────────────────────────────┬──────────────────────────────┐
│ NODE: reth-mainnet-sim-01    │ CHAOS AGENT                  │
│ peer_count: 12               │ [INJECT] peer_zero_rpc_up    │
│ disk_used:  60%              │          cascade_peer_zero…  │
│ engine_api: reachable        │          disk_pressure_99    │
│ jwt:        configured       │          authrpc_exposed     │
├──────────────────────────────┴──────────────────────────────┤
│ MESH                                                         │
│ trigger → evidence → hypothesis → decision → observer        │
│ FINAL: restart / escalate / reject_unsafe                    │
└──────────────────────────────────────────────────────────────┘
```

## 1. One-time setup (~30s)

```bash
# From repo root
chmod +x simulation/demo.sh

# Rotate the API key in the conversation transcript first.
# Then export the new one in this shell only:
export ANTHROPIC_API_KEY=sk-ant-...

# Optional: pick a model. Haiku 4.5 is fast and cheap; Sonnet 4.6 is
# more thorough. Defaults to Haiku.
export MESH_OBSERVER_MODEL=claude-haiku-4-5-20251001
```

If you don't set `ANTHROPIC_API_KEY`, the demo still runs — Mesh's
deterministic floor still ranks hypotheses and decides. The
`observer` line in each block reads `(disabled)`.

## 2. Launch the panes (terminal A)

```bash
./simulation/demo.sh
```

This opens a tmux session called `mesh-demo` with three panes
already tailing the right files. **Don't close this window.**

To detach without closing: `Ctrl-b d`. To reattach:
`tmux attach -t mesh-demo`. To tear down: `./simulation/demo.sh --kill`.

If you don't have tmux, see "no-tmux fallback" at the bottom.

## 3. Start your 30-second intro (camera on you)

You can talk over a static "tmux ready" view of the panes. Cover
these three things — they're the whole pitch:

- **"Most automation treats alerts as instructions. Mesh treats
  them as leads."** Naive automation restarts on peer-count-zero;
  sometimes that's wrong.
- **"Mesh runs five layers before acting."** Trigger → evidence
  pack → hypothesis ranking → deterministic decision → AI
  observer. Each can promote toward escalation. None can demote.
- **"I'm about to inject six faults. Watch the right pane for what
  the chaos agent is doing, the left pane for the node's state,
  and the bottom pane for what Mesh decides and why."**

## 4. Run the demo (terminal B)

```bash
python -m simulation.demo
```

That's it. The runner injects six faults in this order, holding
each on screen for 18 seconds. Total runtime: ~2 minutes.

| # | fault | what to narrate |
|---|---|---|
| 1 | `all_clear` | "We start healthy. 12 peers, disk at 60%, engine API reachable. Mesh sees no trigger." |
| 2 | `peer_zero_rpc_up` | "Peer count drops to zero, but RPC is fine and engine API is up. Hypothesis ranking picks **local_isolation** with posterior 0.88. Decision: approval-gated restart. Observer approves." |
| 3 | `cascade_peer_zero_engine_down` | "Same surface symptom — zero peers — but the engine API is also down. Hypothesis ranking flips: **consensus_disconnect** wins, posterior 0.65 vs local_isolation at 0.60. Decision: **escalate**, not restart. This is the case naive automation gets wrong." |
| 4 | `disk_pressure_critical_99` | "Disk at 99%. Deterministic engine says escalate. Watch the observer — Claude reads the same pack and says **reject_unsafe**, citing DB corruption risk on shutdown. The AI is doing real work, not rubber-stamping." |
| 5 | `authrpc_publicly_exposed` | "Auth-RPC is exposed to the internet. Source: **fast_path_skip** — Mesh doesn't even probe. The trigger alone is enough to escalate. Belt-and-suspenders: even if the policy file lost this signature, Mesh would still escalate." |
| 6 | `all_clear` | "Back to healthy. No trigger fires. The pipeline is silent — that's the point." |

Each fault block in the bottom pane shows the same template:

```
[hh:mm:ss]  FAULT  <id>
            <description>

  trigger      reth_node_degraded
  signatures   [...]
  evidence     source=..., sufficient=True
  hypothesis   top: <cause> (posterior X.XX)
               supports: <predicate>: <evidence path>
               #2: <cause> (posterior X.XX)
  engine       <decision_type> (autonomy ..., conf X.XX)
  observer     <verdict> (model, conf X.XX, latency Xs)
               "<reason quoting evidence by path>"

  FINAL        <decision_type>
```

The `supports` lines are the predicate-level falsification record.
The observer's `reason` is the LLM's verbatim output. **Read at
least one of these aloud during the cascade or disk-pressure
fault** — that's the moment the AI feels real to a viewer.

## 5. Outro (back on camera, ~30s)

- "Six faults, five layers each, full audit trail. The whole demo
  is one Python module — `simulation/demo.py` — driving the same
  pipeline that runs against real signals."
- "26 fault scenarios shipped, observer works with any
  OpenAI-compatible API or Anthropic native, deterministic floor
  works without any AI at all."
- Optional CTA: link the repo / PR / your own follow-up form.

## Customizing the run

```bash
# Different fault sequence
python -m simulation.demo --faults sync_with_disk_pressure,jwt_secret_missing,rpc_publicly_exposed_overload

# Faster (less hold time per fault — good for a 90s cut)
python -m simulation.demo --hold 8

# Append to existing logs (chain multiple runs without resetting panes)
python -m simulation.demo --no-clear
```

## No-tmux fallback

Open three terminal tabs. In each:

```bash
# Tab 1 — node state
watch -n 0.5 cat /tmp/mesh-demo/node.txt

# Tab 2 — chaos log
tail -F /tmp/mesh-demo/chaos.log

# Tab 3 — mesh decisions
tail -F /tmp/mesh-demo/mesh.log
```

Then in a fourth tab:

```bash
python -m simulation.demo
```

Arrange the windows side by side in your screen recorder.

## If something goes wrong

| symptom | fix |
|---|---|
| `tmux: command not found` | `brew install tmux` (macOS), `apt install tmux` (Debian/Ubuntu). Or use the no-tmux fallback above. |
| Observer says `(disabled)` for every fault | `ANTHROPIC_API_KEY` is not set in the shell that runs `python -m simulation.demo`. The tmux panes inherit env from `demo.sh`'s shell, but the runner runs in your other shell — set it there. |
| Observer errors on every call | Rate limit. Check console.anthropic.com for tier; default sweep mode paces 7s/fault but the demo runs back-to-back at the `--hold` rate. Bump `--hold` to 25 or 30, or use `MESH_OBSERVER_MODEL=claude-haiku-4-5-20251001` for higher RPM. |
| `mesh.log` shows hypotheses with `top: unknown` | Expected for disk / consensus / JWT / exposure faults today — the hypothesis engine's templates for those signatures are pending; the deterministic policy + observer carry the load there. Mention this in voice-over if it's distracting. |
| Cascade case still ranks `local_isolation` first | Pull latest — fixed in the post-review commit. `git log --oneline | head -3` should show the "Fix four review issues" commit. |

## Recording settings

- 1920×1080, 60fps minimum.
- tmux pane font: 14–16pt, monospace, dark background.
- Mic close, room treated. Voice-over fits to the visible action,
  so don't pre-record narration; talk live during the runner.
- One take is fine. Each fault's pane updates are tiny — if you
  fumble a sentence, restart the runner with `--no-clear` and pick
  up where you left off.

## What the recording captures, scene-by-scene

- 0:00–0:30  Talking head intro (no recording of the panes yet,
             or pan slowly across the empty panes while you speak).
- 0:30       Run `python -m simulation.demo`. Cut to tmux full-screen.
- 0:30–2:30  The six faults play. Narrate per the table above.
- 2:30–3:00  Outro back on camera.

3 minutes. Done.
