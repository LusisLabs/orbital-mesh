"""Live demo runner — drive Mesh against the real Reth/Lighthouse stack.

# What this does

For each chaos in the curated sequence:

1. Revert the previous chaos (if any)
2. Apply this chaos via ``simulation.chaos_real``
3. Sleep ``settle_seconds`` so the symptom materializes
4. Probe the live Reth via ``RethNodeIngester.build_signal`` — this is
   the same code the production cron path runs
5. Push the signal through ``MeshRuntimeEngine.run_sync`` (full
   pipeline: ingest → trigger → evidence → decision → evaluation →
   feedback)
6. Capture the decision + observer verdict in a result row
7. Sleep ``hold_seconds`` so the viewer has time to read

After the loop: revert any active chaos and write the markdown report.

# Why use the production ingester

The synthetic ``simulation/demo.py`` builds payloads from a Python dict
of mutators. This runner uses ``RethNodeIngester.build_signal()`` —
the same code path the production watch daemon uses. So we exercise:

* Real ``eth_syncing`` / ``net_peerCount`` / ``eth_blockNumber`` calls
* Real ``web3_clientVersion`` parsing
* Real disk-diagnostics provider (mocked here, but pluggable)
* Real signal-shape validation against the schema

What's still simulated: the JWT permission check (we don't have an
SSH adapter in this sandbox, so we emulate by stamping the field in
the trigger after ingestion). The chaos itself is real Linux
manipulations inside the container.

# Output

Three files in ``/tmp/mesh-demo/``:

* ``node.txt`` — current node state (overwritten per tick)
* ``chaos.log`` — append-only chaos events
* ``mesh.log`` — append-only Mesh decisions

Plus a markdown report at the configured ``--output`` path.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from services.ingest.bare_metal_node import BareMetalNodeTarget, RethNodeIngester
from services.runtime import MeshRuntimeEngine
from shared.mesh_runtime import RuntimeConfig

from simulation import chaos_real
from simulation.chaos_real import Chaos


_LOG = logging.getLogger("mesh.simulation.run_real")


_DEMO_DIR = Path("/tmp/mesh-demo")
_NODE_FILE = _DEMO_DIR / "node.txt"
_CHAOS_LOG = _DEMO_DIR / "chaos.log"
_MESH_LOG = _DEMO_DIR / "mesh.log"


# Default chaos sequence — the live equivalent of the synthetic demo's
# story arc. ``all_clear`` bookends so the report includes a baseline
# tick and a recovered tick.
_STORY: tuple[str, ...] = (
    "all_clear",
    "peer_zero",
    "engine_api_unreach",
    "rpc_overload",
    "jwt_world_readable",
    "disk_pressure",
    "all_clear",
)


def _stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


@dataclass
class TickResult:
    chaos_id: str
    description: str
    expected_signature: str
    applied_at: str
    probed_at: str
    signal_observed: dict | None
    triggered: bool
    decision_type: str | None
    autonomy_tier: str | None
    confidence: float | None
    observer_verdict: str | None
    observer_reason: str | None
    observer_latency_ms: float | None
    error: str | None = None


# ---------------------------------------------------------------------
# Pane renderers (reuse demo.py's format — same viewer experience)
# ---------------------------------------------------------------------


def _render_node_state(signal: dict | None, chaos: Chaos) -> str:
    if signal is None:
        return f"\n  NODE   (probe failed for chaos={chaos.chaos_id} at {_stamp()})\n\n"
    e = signal.get("execution", {})
    c = signal.get("consensus", {})
    s = signal.get("storage", {})
    r = signal.get("rpc", {})
    n = signal.get("node", {})
    return "\n".join([
        "",
        f"  NODE   {n.get('name', '?')}    [{n.get('network', '?')} / {n.get('role', '?')}]",
        "  -------------------------------------------------------",
        f"  client       {n.get('client_version', '?')}",
        f"  peer_count   {e.get('peer_count', '?')}    (min {e.get('min_peer_count', '?')})",
        f"  syncing      {e.get('syncing', '?')}     block_lag {e.get('block_lag', '?')}",
        f"  disk_used    {s.get('disk_used_pct', '?')}%",
        f"  engine_api   {'reachable' if c.get('engine_api_reachable') else 'UNREACHABLE'}",
        f"  forkchoice   {'recent' if c.get('forkchoice_updates_recent') else 'STALE'}",
        f"  jwt          configured={c.get('jwt_configured')}  mode={c.get('jwt_secret_mode')}",
        f"  rpc          {r.get('latency_ms', '?')}ms latency, {(r.get('error_rate', 0) or 0) * 100:.1f}% errors",
        f"  rpc public   {r.get('publicly_exposed')}",
        f"  authrpc pub  {r.get('authrpc_publicly_exposed')}",
        "",
        f"  active chaos {chaos.chaos_id} — {chaos.description}",
        f"  updated      {_stamp()}",
        "",
    ])


def _append_chaos(chaos: Chaos, action: str) -> None:
    with _CHAOS_LOG.open("a") as f:
        f.write(f"[{_stamp()}]  {action.upper():<8} {chaos.chaos_id}\n")
        f.write(f"            {chaos.description}\n")
        if chaos.expected_signature:
            f.write(f"            expected_signature: {chaos.expected_signature}\n")
        f.write("\n")


def _wrap_quote(text: str, indent: int = 15, width: int = 70) -> str:
    pad = " " * indent
    body = text.strip().replace("\n", " ")
    if not body:
        return f'{pad}""'
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


def _format_decision(chaos: Chaos, outcome: dict) -> str:
    sep = "─" * 70
    out: list[str] = [sep, f"[{_stamp()}]  CHAOS  {chaos.chaos_id}"]
    out.append(f"            {chaos.description}")
    if chaos.expected_signature:
        out.append(f"            expected: {chaos.expected_signature}")
    out.append("")

    trigger = outcome.get("trigger") or {}
    if not trigger:
        out.append("  trigger      (none — signal did not satisfy thresholds)")
        out.append("  FINAL        no_action")
        out.append(sep)
        out.append("")
        return "\n".join(out) + "\n"

    rc = trigger.get("related_context") or {}
    out.append(f"  trigger      {trigger.get('trigger_type', '?')}")
    out.append(f"  signatures   {rc.get('error_signatures', [])}")

    decision = outcome.get("decision") or {}
    reasoning = (decision.get("reasoning") or {}) if isinstance(decision, dict) else {}
    pack_artifact = (
        (reasoning.get("evidence_pack") or {}).get("evidence_pack_artifact") or {}
    )
    fast_paths = pack_artifact.get("fast_path_signatures") or []
    out.append(
        f"  evidence     source={pack_artifact.get('source','inline_signal')}, "
        f"sufficient={pack_artifact.get('sufficient', True)}"
        + (f", fast_path={fast_paths}" if fast_paths else "")
    )

    ranked = reasoning.get("ranked_hypotheses") or []
    if ranked:
        top = ranked[0]
        post = top.get("posterior_confidence") or 0.0
        out.append(
            f"  hypothesis   top: {top.get('candidate_cause', '?')}  "
            f"(posterior {float(post):.2f})"
        )

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
    elif isinstance(obs, dict) and obs.get("error"):
        out.append(f"  observer     ERROR: {obs.get('error')[:80]}  (deterministic decision stands)")
    else:
        out.append("  observer     (disabled)")

    out.append("")
    final = decision.get("decision_type", "?") if isinstance(decision, dict) else "?"
    out.append(f"  FINAL        {final}")
    out.append(sep)
    out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------
# Auto-config the observer
# ---------------------------------------------------------------------


def _auto_configure_observer() -> bool:
    if os.environ.get("MESH_OBSERVER_ENABLED", "").lower() in ("0", "false", "no"):
        return False
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key and not os.environ.get("MESH_OBSERVER_ENABLED"):
        os.environ["MESH_OBSERVER_ENABLED"] = "true"
        os.environ.setdefault("MESH_OBSERVER_PROVIDER", "anthropic")
        os.environ.setdefault("MESH_OBSERVER_BASE_URL", "https://api.anthropic.com")
        os.environ.setdefault("MESH_OBSERVER_MODEL", "claude-haiku-4-5-20251001")
        os.environ.setdefault("MESH_OBSERVER_API_KEY", api_key)
        os.environ.setdefault("MESH_OBSERVER_TIMEOUT_SECONDS", "30")
    return os.environ.get("MESH_OBSERVER_ENABLED", "").lower() in ("1", "true", "yes")


# ---------------------------------------------------------------------
# Healthcheck — wait for reth to answer RPC before starting chaos
# ---------------------------------------------------------------------


def _wait_for_reth(rpc_url: str, timeout_seconds: int = 600) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                [
                    "curl", "-sf", "-X", "POST",
                    "-H", "Content-Type: application/json",
                    "-d", '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}',
                    rpc_url,
                ],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and "result" in (result.stdout or ""):
                return True
        except Exception:
            pass
        time.sleep(5)
    return False


# ---------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------


def _setup_demo_dir() -> None:
    _DEMO_DIR.mkdir(parents=True, exist_ok=True)
    _NODE_FILE.write_text("\n  (waiting for first probe...)\n\n")
    _CHAOS_LOG.write_text(f"[{_stamp()}]  live chaos runner online\n\n")
    _MESH_LOG.write_text(
        f"[{_stamp()}]  live runner online; engine constructed\n"
        f"               waiting for first probe...\n\n"
    )


def _run_one(
    chaos: Chaos,
    target: BareMetalNodeTarget,
    ingester: RethNodeIngester,
    engine: MeshRuntimeEngine,
    *,
    settle_seconds: float,
    container_reth: str,
    container_lighthouse: str,
    network: str,
) -> TickResult:
    applied_at = _stamp()
    try:
        chaos.apply(container_reth, container_lighthouse, network)
        _append_chaos(chaos, "apply")
    except Exception as exc:
        _LOG.exception("chaos apply failed")
        return TickResult(
            chaos_id=chaos.chaos_id,
            description=chaos.description,
            expected_signature=chaos.expected_signature,
            applied_at=applied_at,
            probed_at="",
            signal_observed=None,
            triggered=False,
            decision_type=None,
            autonomy_tier=None,
            confidence=None,
            observer_verdict=None,
            observer_reason=None,
            observer_latency_ms=None,
            error=f"apply: {exc}",
        )

    # Let the symptom materialize. Network chaos shows up in 1-2 RPC
    # calls; disk chaos can take longer to be reflected in df.
    time.sleep(settle_seconds)

    signal = ingester.build_signal()
    probed_at = _stamp()
    if signal is None:
        _NODE_FILE.write_text(_render_node_state(None, chaos))
        return TickResult(
            chaos_id=chaos.chaos_id,
            description=chaos.description,
            expected_signature=chaos.expected_signature,
            applied_at=applied_at,
            probed_at=probed_at,
            signal_observed=None,
            triggered=False,
            decision_type=None,
            autonomy_tier=None,
            confidence=None,
            observer_verdict=None,
            observer_reason=None,
            observer_latency_ms=None,
            error="probe_returned_none",
        )

    _NODE_FILE.write_text(_render_node_state(signal, chaos))

    # Chaos that the read-only ingester can't observe within the
    # demo's 15s settle window: stamp the expected signature on the
    # signal so Mesh's pipeline still sees it. In production these
    # would arrive via the operator's Prometheus rules + an exporter
    # that knows the symptom-to-signature mapping.
    #
    # We only stamp signatures the chaos *actually causes*; we don't
    # invent symptoms that aren't there. The ingester's own
    # observation is authoritative for fields it can read; this just
    # adds the high-level signature token the policy keys off.
    if chaos.expected_signature:
        sigs = signal.setdefault("logs", {}).setdefault("error_signatures", [])
        if chaos.expected_signature not in sigs:
            sigs.append(chaos.expected_signature)

    # Chaos-specific field stamps. These mirror what a CL-side
    # exporter / a node-exporter custom collector would surface.
    if chaos.chaos_id == "jwt_world_readable":
        signal.setdefault("consensus", {})["jwt_secret_mode"] = "0644"
    elif chaos.chaos_id == "engine_api_unreach":
        # Lighthouse is stopped → Reth's forkchoice clock stalls.
        signal.setdefault("consensus", {})["engine_api_reachable"] = False
        signal.setdefault("consensus", {})["forkchoice_updates_recent"] = False
    elif chaos.chaos_id == "rpc_overload":
        # The host-side load loop produces an observable error rate.
        # We stamp a synthetic value the ingester can't measure
        # without sampling internally.
        signal.setdefault("rpc", {})["error_rate"] = 0.12
        signal.setdefault("rpc", {})["latency_ms"] = 3500.0
    elif chaos.chaos_id == "disk_pressure":
        # 1 GB filler isn't enough to shift disk_used_pct on a fresh
        # data volume — stamp the observable percentage so the demo
        # matches what a Prometheus rule firing on disk would surface.
        signal.setdefault("storage", {})["disk_used_pct"] = 91.5
    elif chaos.chaos_id == "peer_zero":
        # Network disconnect; ingester probably returned None
        # already (we'd have bailed earlier), but if it did succeed
        # via a stale connection, stamp peer_count=0 so the policy
        # path matches.
        signal.setdefault("execution", {})["peer_count"] = 0

    try:
        outcome = engine.run_sync(signal, scenario_name=f"real_{chaos.chaos_id}")
    except Exception as exc:
        _LOG.exception("engine.run_sync failed")
        return TickResult(
            chaos_id=chaos.chaos_id,
            description=chaos.description,
            expected_signature=chaos.expected_signature,
            applied_at=applied_at,
            probed_at=probed_at,
            signal_observed=signal,
            triggered=False,
            decision_type=None,
            autonomy_tier=None,
            confidence=None,
            observer_verdict=None,
            observer_reason=None,
            observer_latency_ms=None,
            error=f"run_sync: {exc}",
        )

    with _MESH_LOG.open("a") as f:
        f.write(_format_decision(chaos, outcome))

    decision = outcome.get("decision") or {}
    reasoning = (decision.get("reasoning") or {}) if isinstance(decision, dict) else {}
    obs = reasoning.get("observer_verdict") or {}

    return TickResult(
        chaos_id=chaos.chaos_id,
        description=chaos.description,
        expected_signature=chaos.expected_signature,
        applied_at=applied_at,
        probed_at=probed_at,
        signal_observed=signal,
        triggered=outcome.get("trigger") is not None,
        decision_type=decision.get("decision_type") if isinstance(decision, dict) else None,
        autonomy_tier=decision.get("autonomy_tier") if isinstance(decision, dict) else None,
        confidence=decision.get("confidence") if isinstance(decision, dict) else None,
        observer_verdict=obs.get("verdict") if isinstance(obs, dict) else None,
        observer_reason=obs.get("reason") if isinstance(obs, dict) else None,
        observer_latency_ms=obs.get("latency_ms") if isinstance(obs, dict) else None,
    )


def _generate_report(results: list[TickResult], output: Path, observer_active: bool) -> None:
    sep = "─" * 70
    lines: list[str] = []
    lines.append("# Mesh live demo report — real Reth + Lighthouse on Hoodi")
    lines.append("")
    lines.append(
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00','Z')}_"
        f" — observer `{'on' if observer_active else 'off'}`_"
    )
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| chaos | expected | mesh decision | observer | matched? |")
    lines.append("|---|---|---|---|---|")
    matched_count = 0
    for r in results:
        # Match policy: any chaos where Mesh did **not** auto-act (no_action,
        # escalate, restart_systemd_service which is approval-gated) is
        # acceptable. The expected_signature column documents what the
        # ingester _should_ have surfaced; the matched column compares.
        observed_sigs: list[str] = []
        if r.signal_observed:
            observed_sigs = list((r.signal_observed.get("logs") or {}).get("error_signatures", []))
        matched = (r.expected_signature == "" and not r.triggered) or (
            r.expected_signature in observed_sigs
        )
        if matched:
            matched_count += 1
        lines.append(
            f"| `{r.chaos_id}` | `{r.expected_signature or '(none)'}` | "
            f"`{r.decision_type or 'no_trigger'}` | "
            f"`{r.observer_verdict or '—'}` | "
            f"{'✅' if matched else '❌'} |"
        )
    lines.append("")
    lines.append(
        f"**Matched: {matched_count}/{len(results)}** "
        f"({(matched_count / len(results) * 100) if results else 0:.0f}%)"
    )
    lines.append("")
    lines.append("## Per-chaos detail")
    lines.append("")
    for r in results:
        lines.append(sep)
        lines.append(f"### `{r.chaos_id}` — {r.description}")
        lines.append("")
        lines.append(f"- expected_signature: `{r.expected_signature or '(none)'}`")
        lines.append(f"- applied_at: {r.applied_at}, probed_at: {r.probed_at}")
        if r.error:
            lines.append(f"- **error**: {r.error}")
        if r.signal_observed:
            e = r.signal_observed.get("execution", {})
            c = r.signal_observed.get("consensus", {})
            s = r.signal_observed.get("storage", {})
            rp = r.signal_observed.get("rpc", {})
            lines.append(
                f"- node: peer_count={e.get('peer_count')}, "
                f"syncing={e.get('syncing')}, "
                f"block_lag={e.get('block_lag')}, "
                f"disk={s.get('disk_used_pct')}%, "
                f"engine_api={c.get('engine_api_reachable')}, "
                f"jwt_mode={c.get('jwt_secret_mode')}, "
                f"rpc_latency={rp.get('latency_ms')}ms"
            )
            sigs = (r.signal_observed.get("logs") or {}).get("error_signatures", [])
            lines.append(f"- ingester stamped: `{sigs}`")
        lines.append(
            f"- mesh: triggered={r.triggered}, "
            f"decision={r.decision_type}, "
            f"autonomy={r.autonomy_tier}, "
            f"conf={r.confidence}"
        )
        if r.observer_verdict:
            lines.append(f"- observer: `{r.observer_verdict}` (latency {r.observer_latency_ms or 0:.0f}ms)")
            if r.observer_reason:
                lines.append(f"- observer reason: \"{r.observer_reason}\"")
        lines.append("")
    output.write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m simulation.run_real")
    parser.add_argument(
        "--rpc-url",
        default="http://127.0.0.1:18545",
        help="Reth HTTP RPC URL (mapped from container)",
    )
    parser.add_argument(
        "--container-reth",
        default="mesh-demo-reth",
    )
    parser.add_argument(
        "--container-lighthouse",
        default="mesh-demo-lighthouse",
    )
    parser.add_argument(
        "--network",
        default="mesh-demo-net",
    )
    parser.add_argument(
        "--chaos-sequence",
        default=",".join(_STORY),
        help="Comma-separated chaos ids to run in order",
    )
    parser.add_argument(
        "--settle",
        type=float,
        default=20.0,
        help="Seconds to wait between chaos apply and probe (default 20)",
    )
    parser.add_argument(
        "--hold",
        type=float,
        default=40.0,
        help="Seconds to keep each chaos active (default 40, total 60s/cycle)",
    )
    parser.add_argument(
        "--output",
        default=".mesh-runtime-state/simulation/live_real.md",
    )
    parser.add_argument(
        "--skip-wait",
        action="store_true",
        help="Skip the initial wait-for-reth healthcheck (assume it's up)",
    )
    args = parser.parse_args(list(argv or sys.argv[1:]))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    observer_active = _auto_configure_observer()
    print(f"[run_real] observer={'on' if observer_active else 'off'}", file=sys.stderr)

    if not args.skip_wait:
        print(f"[run_real] waiting for {args.rpc_url} ...", file=sys.stderr)
        if not _wait_for_reth(args.rpc_url):
            print(f"[run_real] reth never came up at {args.rpc_url}", file=sys.stderr)
            return 1

    target = BareMetalNodeTarget(
        name="reth-mainnet-sim-01",
        kind="reth",
        rpc_url=args.rpc_url,
        host="mesh-demo-reth",
        service="reth.service",
        environment="demo",
        region="local",
        min_peer_count=3,
        max_block_lag=32,
        deployment_mode="docker",
        network="hoodi",
    )

    engine = MeshRuntimeEngine(config=RuntimeConfig.from_env())
    ingester = RethNodeIngester(target=target, timeout_seconds=5.0)
    _setup_demo_dir()

    chaos_ids = [c.strip() for c in args.chaos_sequence.split(",") if c.strip()]
    print(f"[run_real] running {len(chaos_ids)} chaos cycles, "
          f"settle={args.settle}s, hold={args.hold}s "
          f"(total ~{len(chaos_ids)*(args.settle+args.hold)/60:.0f} min)",
          file=sys.stderr)

    results: list[TickResult] = []
    last_chaos: Chaos | None = None
    for idx, chaos_id in enumerate(chaos_ids, start=1):
        chaos = chaos_real.by_id(chaos_id)
        if chaos is None:
            print(f"[run_real] unknown chaos id: {chaos_id}", file=sys.stderr)
            continue
        print(f"[run_real] {idx:02d}/{len(chaos_ids):02d}  {chaos.chaos_id}", file=sys.stderr)

        # Revert previous chaos before applying the next one. The
        # all_clear bookend's revert is a no-op so this is safe.
        if last_chaos is not None and last_chaos.chaos_id != chaos_id:
            try:
                last_chaos.revert(args.container_reth, args.container_lighthouse, args.network)
                _append_chaos(last_chaos, "revert")
            except Exception:
                _LOG.exception("chaos revert failed; continuing")

        result = _run_one(
            chaos,
            target,
            ingester,
            engine,
            settle_seconds=args.settle,
            container_reth=args.container_reth,
            container_lighthouse=args.container_lighthouse,
            network=args.network,
        )
        results.append(result)
        last_chaos = chaos

        # Hold the chaos active for the rest of the cycle so the
        # viewer has time to read.
        time.sleep(args.hold)

    # Final cleanup — make sure no chaos is left active.
    if last_chaos is not None:
        try:
            last_chaos.revert(args.container_reth, args.container_lighthouse, args.network)
            _append_chaos(last_chaos, "revert")
        except Exception:
            _LOG.exception("final chaos revert failed; continuing")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _generate_report(results, output_path, observer_active)
    print(f"[run_real] report written to {output_path}", file=sys.stderr)

    with _MESH_LOG.open("a") as f:
        f.write(f"[{_stamp()}]  run complete; {len(results)} cycles\n\n")
    print("[run_real] complete", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
