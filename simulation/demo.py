"""Side-by-side demo runner — writes three labeled streams for tmux.

# What this is

A drivable demo that injects a curated sequence of faults into a
synthetic Reth node, runs the real Mesh pipeline against each one,
and writes three live files:

* ``/tmp/mesh-demo/node.txt``  — current node state (overwritten per fault)
* ``/tmp/mesh-demo/chaos.log`` — append-only chaos-injection log
* ``/tmp/mesh-demo/mesh.log``  — append-only Mesh decision + observer log

Pair with ``simulation/demo.sh`` which sets up a tmux session with one
pane per file, so a screen recording captures all three streams
side-by-side.

# Why a curated sequence

The full catalog (26 faults) is great for evals but bad for narration.
The default story below is **six faults** chosen to walk a viewer
through the safety properties in order:

1. ``all_clear``                       — show the baseline.
2. ``peer_zero_rpc_up``                — first interesting fault; observer approves a restart.
3. ``cascade_peer_zero_engine_down``   — same surface symptom, but engine API is down too;
                                          hypothesis ranking flips to consensus_disconnect →
                                          escalate. The "naive automation would have restarted"
                                          moment.
4. ``disk_pressure_critical_99``       — observer ``reject_unsafe`` with cited reasoning.
5. ``authrpc_publicly_exposed``        — fast-path skips probes, escalates immediately.
6. ``all_clear``                       — return to baseline.

You can override with ``--faults`` if you want a different arc.

# Auto-enables the observer when ANTHROPIC_API_KEY is set

So the common case (Claude in the loop) is one ``export`` away. Set
``MESH_OBSERVER_ENABLED=false`` to force deterministic-only.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from services.runtime import MeshRuntimeEngine
from shared.mesh_runtime import RuntimeConfig

from simulation import baseline, fault_catalog
from simulation.fault_catalog import CATALOG, Fault


_DEMO_DIR = Path("/tmp/mesh-demo")
_NODE_FILE = _DEMO_DIR / "node.txt"
_CHAOS_LOG = _DEMO_DIR / "chaos.log"
_MESH_LOG = _DEMO_DIR / "mesh.log"

# Add env for observer toggle/trace
_OBSERVER_ENABLED = os.environ.get("MESH_OBSERVER_ENABLED", "").lower() in ("1", "true", "yes")
_ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")


# Default story arc. See module docstring for why.
_STORY: tuple[str, ...] = (
    "all_clear",
    "peer_zero_rpc_up",
    "cascade_peer_zero_engine_down",
    "disk_pressure_critical_99",
    "authrpc_publicly_exposed",
    "all_clear",
)


def _stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _truthy(s: str) -> bool:
    return s.lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------
# Pane renderers
# ---------------------------------------------------------------------


def _render_node_state(state: dict) -> str:
    e = state["execution"]
    c = state["consensus"]
    s = state["storage"]
    r = state["rpc"]
    n = state["node"]
    rate_pct = (r["error_rate"] or 0) * 100
    return "\n".join([
        "",
        f"  NODE   {n['name']}    [{n['network']} / {n['role']}]",
        "  -------------------------------------------------------",
        f"  client       {n['client_version']}",
        f"  peer_count   {e['peer_count']}    (min {e['min_peer_count']})",
        f"  syncing      {e['syncing']}     block_lag {e['block_lag']}",
        f"  disk_used    {s['disk_used_pct']}%",
        f"  engine_api   {'reachable' if c['engine_api_reachable'] else 'UNREACHABLE'}",
        f"  forkchoice   {'recent' if c['forkchoice_updates_recent'] else 'STALE'}",
        f"  jwt          configured={c['jwt_configured']}  mode={c['jwt_secret_mode']}",
        f"  rpc          {r['latency_ms']}ms latency, {rate_pct:.1f}% errors",
        f"  rpc public   {r['publicly_exposed']}",
        f"  authrpc pub  {r['authrpc_publicly_exposed']}",
        "",
        f"  updated      {_stamp()}",
        "",
    ])


def _append_chaos(fault: Fault) -> None:
    severity = (
        "(escalate-only)" if fault.expected_outcomes == ("escalate",)
        else "(no-action expected)" if fault.expected_outcomes == ("no_action",)
        else "(restartable / ambiguous)"
    )
    with _CHAOS_LOG.open("a") as f:
        f.write(f"[{_stamp()}]  INJECT  {fault.fault_id}\n")
        f.write(f"            {fault.description}\n")
        f.write(f"            expected: {severity}\n\n")


def _wrap_quote(text: str, indent: int = 15, width: int = 70) -> str:
    """Wrap a single-line LLM reason into ``width``-column blocks with
    a leading indent and surrounding quotes. Demo logs are read at
    presentation pace, so wrapping matters more than density."""
    pad = " " * indent
    body = text.strip().replace("\n", " ")
    if not body:
        return f"{pad}\"\""
    out: list[str] = []
    line = pad + '"'
    first = True
    for word in body.split():
        candidate = (line + " " + word) if not first and line.strip() else line + word
        if len(candidate) > width:
            out.append(line)
            line = pad + " " + word
            first = False
            continue
        if first:
            line = pad + '"' + word
            first = False
        else:
            line = candidate
    line = line + '"'
    out.append(line)
    return "\n".join(out)


def _format_decision(fault: Fault, outcome: dict) -> str:
    sep = "─" * 70
    out: list[str] = [sep, f"[{_stamp()}]  FAULT  {fault.fault_id}"]
    out.append(f"            {fault.description}")
    out.append("")

    trigger = outcome.get("trigger") or {}
    if not trigger:
        out.append("  trigger      (none — signal did not satisfy thresholds)")
        out.append("  FINAL        no_action")
        out.append(sep)
        out.append("")
        return "\n".join(out) + "\n"

    rc = trigger.get("related_context") or {}
    sigs = rc.get("error_signatures", [])
    out.append(f"  trigger      {trigger.get('trigger_type', '?')}")
    out.append(f"  signatures   {sigs}")

    decision = outcome.get("decision") or {}
    reasoning = (decision.get("reasoning") or {}) if isinstance(decision, dict) else {}
    pack_artifact = (
        (reasoning.get("evidence_pack") or {}).get("evidence_pack_artifact") or {}
    )
    fast_paths = pack_artifact.get("fast_path_signatures") or []

    evidence_summary = (
        f"source={pack_artifact.get('source','inline_signal')}, "
        f"sufficient={pack_artifact.get('sufficient', True)}"
    )
    if fast_paths:
        evidence_summary += f", fast_path={fast_paths}"
    out.append(f"  evidence     {evidence_summary}")

    ranked = reasoning.get("ranked_hypotheses") or []
    if ranked:
        top = ranked[0]
        post = top.get("posterior_confidence") or 0.0
        out.append(
            f"  hypothesis   top: {top.get('candidate_cause', '?')}  "
            f"(posterior {float(post):.2f})"
        )
        for evid in (top.get("supporting_evidence") or [])[:3]:
            out.append(f"               supports: {evid}")
        for evid in (top.get("disconfirming_evidence") or [])[:1]:
            out.append(f"               disconfirms: {evid}")
        if len(ranked) >= 2:
            n2 = ranked[1]
            n2_post = n2.get("posterior_confidence") or 0.0
            out.append(
                f"               #2: {n2.get('candidate_cause', '?')}  "
                f"(posterior {float(n2_post):.2f})"
            )
    else:
        out.append("  hypothesis   (none ranked)")

    if isinstance(decision, dict):
        out.append(
            f"  engine       {decision.get('decision_type', '?')}  "
            f"(autonomy {decision.get('autonomy_tier', '?')}, "
            f"conf {float(decision.get('confidence') or 0):.2f})"
        )

    obs = reasoning.get("observer_verdict") or {}
    if isinstance(obs, dict) and obs.get("verdict") and not obs.get("error"):
        latency_ms = obs.get("latency_ms") or 0
        out.append(
            f"  observer     {obs.get('verdict')}  "
            f"({obs.get('model', '?')}, conf {float(obs.get('confidence') or 0):.2f}, "
            f"latency {(latency_ms or 0) / 1000:.1f}s)"
        )
        reason = (obs.get("reason") or "").strip()
        if reason:
            out.append(_wrap_quote(reason))
        for c in (obs.get("concerns") or [])[:2]:
            out.append(f"               concern: {c[:120]}")
    elif isinstance(obs, dict) and obs.get("error"):
        out.append(
            f"  observer     ERROR: {obs.get('error')[:80]}  (deterministic decision stands)"
        )
    else:
        out.append("  observer     (disabled)")

    out.append("")
    final = decision.get("decision_type", "?") if isinstance(decision, dict) else "?"
    out.append(f"  FINAL        {final}")
    out.append(sep)
    out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------


def _setup_demo_dir() -> None:
    _DEMO_DIR.mkdir(parents=True, exist_ok=True)
    _NODE_FILE.write_text("\n  (initializing... wait one tick.)\n\n")
    _CHAOS_LOG.write_text(
        f"[{_stamp()}]  chaos agent online; queueing fault sequence\n\n"
    )
    _MESH_LOG.write_text(
        f"[{_stamp()}]  mesh demo runner online; engine constructed\n"
        f"               waiting for first injection...\n\n"
    )


def _auto_configure_observer() -> bool:
    """If ANTHROPIC_API_KEY is set and observer not explicitly disabled,
    flip MESH_OBSERVER_* env so the engine wires the observer in.
    Returns True if the observer ends up active.
    """
    if os.environ.get("MESH_OBSERVER_ENABLED", "").lower() in ("0", "false", "no"):
        return False
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        api_key = "".join(api_key.split())
        os.environ.setdefault("MESH_OBSERVER_ENABLED", "true")
        os.environ.setdefault("MESH_OBSERVER_PROVIDER", "anthropic")
        os.environ.setdefault("MESH_OBSERVER_BASE_URL", "https://api.anthropic.com")
        os.environ.setdefault(
            "MESH_OBSERVER_MODEL", "claude-opus-4-6"
        )
        os.environ.setdefault("MESH_OBSERVER_API_KEY", api_key)
        os.environ.setdefault("MESH_OBSERVER_TIMEOUT_SECONDS", "30")
    if os.environ.get("MESH_OBSERVER_API_KEY"):
        os.environ["MESH_OBSERVER_API_KEY"] = "".join(
            os.environ["MESH_OBSERVER_API_KEY"].split()
        )
    return _observer_ready_from_env()


def _observer_ready_from_env() -> bool:
    return (
        _truthy(os.environ.get("MESH_OBSERVER_ENABLED", "false"))
        and bool(os.environ.get("MESH_OBSERVER_BASE_URL"))
        and bool(os.environ.get("MESH_OBSERVER_API_KEY"))
        and bool(os.environ.get("MESH_OBSERVER_MODEL"))
    )


def _observer_status_line() -> str:
    enabled = _truthy(os.environ.get("MESH_OBSERVER_ENABLED", "false"))
    provider = os.environ.get("MESH_OBSERVER_PROVIDER", "openai")
    model = os.environ.get("MESH_OBSERVER_MODEL", "")
    base_url = os.environ.get("MESH_OBSERVER_BASE_URL", "")
    has_key = bool(os.environ.get("MESH_OBSERVER_API_KEY"))
    missing = [
        name
        for name, present in (
            ("enabled", enabled),
            ("base_url", bool(base_url)),
            ("api_key", has_key),
            ("model", bool(model)),
        )
        if not present
    ]
    state = "on" if not missing else "off"
    suffix = "" if not missing else f"; missing={','.join(missing)}"
    return (
        f"[{_stamp()}]  observer {state}; provider={provider}; "
        f"model={model or '<unset>'}; base_url={base_url or '<unset>'}; "
        f"api_key={'set' if has_key else 'missing'}{suffix}\n"
    )


def _resolve_faults(fault_ids: list[str]) -> list[Fault]:
    out: list[Fault] = []
    for fid in fault_ids:
        try:
            out.append(next(f for f in CATALOG if f.fault_id == fid))
        except StopIteration:
            print(f"[demo] unknown fault id: {fid!r}", file=sys.stderr)
    return out


def run(faults: list[Fault], hold_seconds: float, engine: MeshRuntimeEngine) -> None:
    for idx, fault in enumerate(faults, start=1):
        print(
            f"[demo] {idx:02d}/{len(faults):02d}  {fault.fault_id}",
            file=sys.stderr,
        )
        # 1. Mutate the world. The state file the operator sees is the
        # *post-injection* snapshot; the chaos log entry says what just
        # happened.
        state = fault_catalog.apply_fault(fault, baseline.healthy_state())
        baseline.stamp_signal(state)
        _NODE_FILE.write_text(_render_node_state(state))
        _append_chaos(fault)

        # 2. Run the real Mesh pipeline. ``run_sync`` does ingest →
        # trigger → evidence → scenario → decision → evaluation →
        # orchestrator → feedback in process, exactly the way the HTTP
        # path does. We only render the parts the viewer cares about.
        outcome = engine.run_sync(state, scenario_name=f"demo_{fault.fault_id}")

        # 3. Mesh log entry. This is what gets read out loud during
        # narration.
        with _MESH_LOG.open("a") as f:
            f.write(_format_decision(fault, outcome))

        # 4. Hold so the viewer can read all three panes before the
        # next event.
        time.sleep(hold_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simulation.demo")
    parser.add_argument(
        "--faults",
        default=",".join(_STORY),
        help=(
            "comma-separated fault ids in injection order; "
            "default is the curated story arc"
        ),
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=18.0,
        help="seconds to hold each fault state on screen (default 18)",
    )
    parser.add_argument(
        "--no-clear",
        action="store_true",
        help="don't reset the demo dir; append to existing logs",
    )
    args = parser.parse_args(list(argv or sys.argv[1:]))

    observer_active = _auto_configure_observer()
    if not args.no_clear:
        _setup_demo_dir()
    with _MESH_LOG.open("a") as f:
        f.write(_observer_status_line())
        f.write("\n")

    fault_ids = [f.strip() for f in args.faults.split(",") if f.strip()]
    faults = _resolve_faults(fault_ids)
    if not faults:
        print("[demo] no valid faults to run; exiting", file=sys.stderr)
        return 1

    print(
        f"[demo] writing to {_DEMO_DIR}; observer={'on' if observer_active else 'off'}",
        file=sys.stderr,
    )
    print(
        f"[demo] running {len(faults)} faults with {args.hold}s hold each",
        file=sys.stderr,
    )

    engine = MeshRuntimeEngine(config=RuntimeConfig.from_env())
    run(faults, args.hold, engine)

    # Final marker so the viewer knows the run is done.
    with _MESH_LOG.open("a") as f:
        f.write(f"[{_stamp()}]  demo complete; ran {len(faults)} faults\n\n")
    print("[demo] complete", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
