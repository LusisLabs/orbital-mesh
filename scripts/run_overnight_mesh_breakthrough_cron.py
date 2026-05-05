#!/usr/bin/env python3
"""Eight-hour Mesh end-to-end breakthrough runner.

This script is intentionally orchestration-only. It composes existing, tested
Mesh lanes and leaves each lane's artifacts in its native output directory.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / ".mesh-runtime-state" / "overnight-breakthrough"
DEFAULT_COMPOSE_FILE = REPO_ROOT / "docker-compose.stack.yml"
DEFAULT_BASE_URL = "http://127.0.0.1:8787"
DEFAULT_COMPOSE_BASE_URL = "http://mesh:8787"


@dataclass
class LaneResult:
    name: str
    status: str
    started_at: str
    finished_at: str
    elapsed_seconds: float
    command: list[str] = field(default_factory=list)
    log_path: str | None = None
    returncode: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_root = Path(args.output_root).resolve()
    run_dir = output_root / _stamp()
    logs_dir = run_dir / "logs"
    run_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    deadline = time.monotonic() + max(300, int(args.duration_seconds))
    env = _base_env(run_dir=run_dir, base_url=args.base_url)

    manifest: dict[str, Any] = {
        "run_id": run_dir.name,
        "started_at": _now(),
        "deadline_seconds": int(args.duration_seconds),
        "base_url": args.base_url,
        "compose_file": str(Path(args.compose_file).resolve()),
        "output_directory": str(run_dir),
        "lanes": [],
        "capability_map": _capability_map(),
    }
    _write_json(run_dir / "manifest.running.json", manifest)

    lane_results: list[LaneResult] = []
    background: list[tuple[str, subprocess.Popen[bytes], Path, float, list[str]]] = []

    if args.start_stack:
        lane_results.append(
            _run_command(
                "compose_stack_up",
                [
                    "docker",
                    "compose",
                    "-f",
                    str(Path(args.compose_file).resolve()),
                    "up",
                    "--build",
                    "-d",
                    "mesh",
                    "mesh-agent-operator",
                    "mesh-smoke",
                    "latentmas",
                ],
                logs_dir=logs_dir,
                env=env,
                timeout_seconds=min(1800, _remaining(deadline)),
                allow_failure=False,
            )
        )

    lane_results.append(_probe_mesh_health(args.base_url, logs_dir=logs_dir))

    if args.run_mesh_smoke:
        lane_results.append(
            _run_command(
                "compose_smoke",
                [
                    "docker",
                    "compose",
                    "-f",
                    str(Path(args.compose_file).resolve()),
                    "run",
                    "--rm",
                    "mesh-smoke",
                ],
                logs_dir=logs_dir,
                env=env,
                timeout_seconds=min(1800, _remaining(deadline)),
                allow_failure=True,
            )
        )

    if args.run_mesh_brain:
        lane_results.append(_mesh_brain_extracted_lane(logs_dir=logs_dir))

    if args.run_compose_chaos:
        chaos_duration = max(300, int(_remaining(deadline)) - 900)
        chaos_env = {
            **env,
            "MESH_STACK_CHAOS_DURATION_SECONDS": str(chaos_duration),
            "MESH_STACK_CHAOS_STOP_ON_BREAKTHROUGH": "1",
            "MESH_STACK_CHAOS_COVERAGE_FIRST": "1",
            "MESH_STACK_CHAOS_REQUIRE_FULL_AXIS_COVERAGE": "1",
            "MESH_STACK_CHAOS_REQUIRE_SUBSTRATE_COVERAGE": "1",
            "MESH_STACK_CHAOS_REQUIRE_MULTI_FAULT_BREADTH": "1",
            "MESH_STACK_CHAOS_MIN_SLEEP_SECONDS": os.environ.get("MESH_STACK_CHAOS_MIN_SLEEP_SECONDS", "10"),
            "MESH_STACK_CHAOS_MAX_SLEEP_SECONDS": os.environ.get("MESH_STACK_CHAOS_MAX_SLEEP_SECONDS", "35"),
            "MESH_STACK_CHAOS_HOLD_SECONDS": os.environ.get("MESH_STACK_CHAOS_HOLD_SECONDS", "12"),
            "MESH_STACK_BASE_URL": DEFAULT_COMPOSE_BASE_URL,
        }
        background.append(
            _start_background(
                "compose_chaos_breakthrough",
                [
                    "docker",
                    "compose",
                    "-f",
                    str(Path(args.compose_file).resolve()),
                    "run",
                    "--rm",
                    "--no-deps",
                    "mesh-chaos",
                ],
                logs_dir=logs_dir,
                env=chaos_env,
            )
        )

    if args.run_autoresearch:
        autoresearch_duration = max(300, int(_remaining(deadline)) - 300)
        autoresearch_env = {
            **env,
            "BASE_URL": args.base_url,
            "OVERNIGHT_DURATION_SECONDS": str(autoresearch_duration),
            "OVERNIGHT_INTERVAL_SECONDS": str(args.autoresearch_interval_seconds),
            "OVERNIGHT_MINIMAX": "1" if args.minimax else "0",
            "OVERNIGHT_HTTP_RUNS": "1",
            "OVERNIGHT_HTTP_FULL_MATRIX": "1" if args.http_full_matrix else "0",
            "OVERNIGHT_HOLISTIC_MATRIX": "1",
            "OVERNIGHT_DOUBLE_ARCHIVE": "1",
            "OVERNIGHT_OLLAMA_FALLBACK": "1",
            "OVERNIGHT_EVALUATION_MODE": "promptfoo",
            "OVERNIGHT_ORCHESTRATION_MODE": "goose",
        }
        background.append(
            _start_background(
                "autoresearch_matrix_synthesis",
                [
                    sys.executable,
                    "scripts/overnight_mesh_autoresearch.py",
                    "--duration-seconds",
                    str(autoresearch_duration),
                    "--interval-seconds",
                    str(args.autoresearch_interval_seconds),
                    "--http-runs",
                    "--holistic-matrix",
                ]
                + (["--http-full-matrix"] if args.http_full_matrix else [])
                + (["--minimax"] if args.minimax else ["--no-minimax"]),
                logs_dir=logs_dir,
                env=autoresearch_env,
            )
        )

    if args.run_node_probes and _remaining(deadline) > 60:
        lane_results.append(
            _run_command(
                "production_node_breakthrough",
                [sys.executable, "scripts/production_node_breakthrough_session.py"],
                logs_dir=logs_dir,
                env={
                    **env,
                    "MESH_NODE_BREAKTHROUGH_OUTPUT_DIR": str(run_dir / "node-breakthrough"),
                },
                timeout_seconds=min(1800, _remaining(deadline)),
                allow_failure=True,
            )
        )

    if args.run_simulation_benchmarks and _remaining(deadline) > 90:
        lane_results.append(
            _run_command(
                "simulation_benchmarks",
                [
                    sys.executable,
                    "scripts/run_nightly_benchmarks.py",
                    "--iterations",
                    str(args.benchmark_iterations),
                    "--workers",
                    str(args.benchmark_workers),
                    "--root",
                    str(run_dir / "simulation-stress"),
                    "--allow-regression",
                ],
                logs_dir=logs_dir,
                env=env,
                timeout_seconds=min(2400, _remaining(deadline)),
                allow_failure=True,
            )
        )

    lane_results.extend(_wait_background(background, deadline=deadline))

    if args.generate_proof and _remaining(deadline) > 60:
        lane_results.append(
            _run_command(
                "breakthrough_proof_replay",
                ["scripts/run_breakthrough_proof.sh", "--replay-only"],
                logs_dir=logs_dir,
                env={
                    **env,
                    "MESH_BREAKTHROUGH_OUTPUT_DIR": str(run_dir / "proofs"),
                },
                timeout_seconds=min(1800, _remaining(deadline)),
                allow_failure=True,
            )
        )

    if args.run_halo and _remaining(deadline) > 60:
        lane_results.append(
            _run_command(
                "halo_outer_loop",
                [
                    "docker",
                    "compose",
                    "-f",
                    str(Path(args.compose_file).resolve()),
                    "--profile",
                    "halo",
                    "run",
                    "--rm",
                    "mesh-halo-optimizer",
                ],
                logs_dir=logs_dir,
                env=env,
                timeout_seconds=min(2400, _remaining(deadline)),
                allow_failure=True,
            )
        )

    manifest["finished_at"] = _now()
    manifest["lanes"] = [result.__dict__ for result in lane_results]
    manifest["artifact_index"] = _artifact_index(run_dir)
    manifest["status"] = _overall_status(lane_results)
    _write_json(run_dir / "manifest.json", manifest)
    _write_markdown(run_dir / "report.md", manifest)
    running = run_dir / "manifest.running.json"
    if running.exists():
        running.unlink()
    print(json.dumps({"status": manifest["status"], "run_dir": str(run_dir)}, sort_keys=True))
    return 0 if manifest["status"] in {"completed", "completed_with_findings"} else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the eight-hour Mesh e2e breakthrough cron workload.")
    parser.add_argument("--duration-seconds", type=int, default=int(os.environ.get("MESH_OVERNIGHT_DURATION_SECONDS", 8 * 3600)))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--compose-file", default=str(DEFAULT_COMPOSE_FILE))
    parser.add_argument("--base-url", default=os.environ.get("MESH_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--start-stack", action=argparse.BooleanOptionalAction, default=_truthy("MESH_OVERNIGHT_START_STACK", True))
    parser.add_argument("--run-mesh-smoke", action=argparse.BooleanOptionalAction, default=_truthy("MESH_OVERNIGHT_RUN_SMOKE", True))
    parser.add_argument("--run-compose-chaos", action=argparse.BooleanOptionalAction, default=_truthy("MESH_OVERNIGHT_RUN_COMPOSE_CHAOS", True))
    parser.add_argument("--run-autoresearch", action=argparse.BooleanOptionalAction, default=_truthy("MESH_OVERNIGHT_RUN_AUTORESEARCH", True))
    parser.add_argument(
        "--run-mesh-brain",
        action=argparse.BooleanOptionalAction,
        default=_truthy("MESH_OVERNIGHT_RUN_MESH_BRAIN", False),
        help="Deprecated compatibility flag. Mesh Brain lanes live in the extracted post-training repo.",
    )
    parser.add_argument("--run-node-probes", action=argparse.BooleanOptionalAction, default=_truthy("MESH_OVERNIGHT_RUN_NODE_PROBES", True))
    parser.add_argument("--run-simulation-benchmarks", action=argparse.BooleanOptionalAction, default=_truthy("MESH_OVERNIGHT_RUN_SIM_BENCH", True))
    parser.add_argument("--generate-proof", action=argparse.BooleanOptionalAction, default=_truthy("MESH_OVERNIGHT_GENERATE_PROOF", True))
    parser.add_argument("--run-halo", action=argparse.BooleanOptionalAction, default=_truthy("MESH_OVERNIGHT_RUN_HALO", True))
    parser.add_argument("--minimax", action=argparse.BooleanOptionalAction, default=_truthy("OVERNIGHT_MINIMAX", False))
    parser.add_argument("--http-full-matrix", action=argparse.BooleanOptionalAction, default=_truthy("OVERNIGHT_HTTP_FULL_MATRIX", True))
    parser.add_argument("--autoresearch-interval-seconds", type=int, default=int(os.environ.get("OVERNIGHT_INTERVAL_SECONDS", "1800")))
    parser.add_argument("--benchmark-iterations", type=int, default=int(os.environ.get("MESH_OVERNIGHT_BENCHMARK_ITERATIONS", "48")))
    parser.add_argument("--benchmark-workers", type=int, default=int(os.environ.get("MESH_OVERNIGHT_BENCHMARK_WORKERS", "8")))
    return parser


def _base_env(*, run_dir: Path, base_url: str) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(REPO_ROOT))
    env.setdefault("BASE_URL", base_url)
    env.setdefault("MESH_OVERNIGHT_RUN_DIR", str(run_dir))
    return env


def _mesh_brain_extracted_lane(*, logs_dir: Path) -> LaneResult:
    started = time.monotonic()
    started_at = _now()
    log_path = logs_dir / "mesh_brain_extracted.json"
    details = {
        "status": "skipped",
        "reason": "Mesh Brain control-plane and local package lanes were extracted from this repo.",
        "external_repo": "https://github.com/hyperstrategy/post-training",
    }
    _write_json(log_path, details)
    return LaneResult(
        name="mesh_brain_extracted",
        status="completed",
        started_at=started_at,
        finished_at=_now(),
        elapsed_seconds=round(time.monotonic() - started, 3),
        log_path=str(log_path),
        details=details,
    )


def _run_command(
    name: str,
    command: list[str],
    *,
    logs_dir: Path,
    env: dict[str, str],
    timeout_seconds: float,
    allow_failure: bool,
) -> LaneResult:
    started = time.monotonic()
    started_at = _now()
    log_path = logs_dir / f"{name}.log"
    with log_path.open("wb") as log:
        try:
            proc = subprocess.run(
                command,
                cwd=REPO_ROOT,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=max(1, int(timeout_seconds)),
                check=False,
            )
            status = "completed" if proc.returncode == 0 else "failed"
            if allow_failure and proc.returncode != 0:
                status = "completed_with_findings"
            return LaneResult(
                name=name,
                status=status,
                started_at=started_at,
                finished_at=_now(),
                elapsed_seconds=round(time.monotonic() - started, 3),
                command=command,
                log_path=str(log_path),
                returncode=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            return LaneResult(
                name=name,
                status="timed_out",
                started_at=started_at,
                finished_at=_now(),
                elapsed_seconds=round(time.monotonic() - started, 3),
                command=command,
                log_path=str(log_path),
            )


def _start_background(
    name: str,
    command: list[str],
    *,
    logs_dir: Path,
    env: dict[str, str],
) -> tuple[str, subprocess.Popen[bytes], Path, float, list[str]]:
    log_path = logs_dir / f"{name}.log"
    log = log_path.open("wb")
    proc = subprocess.Popen(command, cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    log.close()
    return name, proc, log_path, time.monotonic(), command


def _wait_background(
    processes: list[tuple[str, subprocess.Popen[bytes], Path, float, list[str]]],
    *,
    deadline: float,
) -> list[LaneResult]:
    results: list[LaneResult] = []
    remaining = processes[:]
    while remaining and time.monotonic() < deadline:
        next_remaining: list[tuple[str, subprocess.Popen[bytes], Path, float, list[str]]] = []
        for name, proc, log_path, started, command in remaining:
            code = proc.poll()
            if code is None:
                next_remaining.append((name, proc, log_path, started, command))
                continue
            results.append(
                LaneResult(
                    name=name,
                    status="completed" if code == 0 else "completed_with_findings",
                    started_at=_from_monotonic(started),
                    finished_at=_now(),
                    elapsed_seconds=round(time.monotonic() - started, 3),
                    command=command,
                    log_path=str(log_path),
                    returncode=code,
                )
            )
        remaining = next_remaining
        if remaining:
            time.sleep(5)
    for name, proc, log_path, started, command in remaining:
        proc.terminate()
        try:
            code = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = proc.wait(timeout=30)
        results.append(
            LaneResult(
                name=name,
                status="timed_out" if code != 0 else "completed",
                started_at=_from_monotonic(started),
                finished_at=_now(),
                elapsed_seconds=round(time.monotonic() - started, 3),
                command=command,
                log_path=str(log_path),
                returncode=code,
            )
        )
    return results


def _probe_mesh_health(base_url: str, *, logs_dir: Path) -> LaneResult:
    started = time.monotonic()
    started_at = _now()
    log_path = logs_dir / "mesh_health.json"
    result: dict[str, Any] = {"base_url": base_url}
    for endpoint in ("/api/health", "/api/readiness"):
        url = f"{base_url.rstrip('/')}{endpoint}"
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                result[endpoint] = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - health probe should report any connection/readiness failure.
            result[endpoint] = {"error": repr(exc)}
    _write_json(log_path, result)
    healthy = "/api/health" in result and not result["/api/health"].get("error")
    return LaneResult(
        name="mesh_health_readiness",
        status="completed" if healthy else "failed",
        started_at=started_at,
        finished_at=_now(),
        elapsed_seconds=round(time.monotonic() - started, 3),
        log_path=str(log_path),
        details={"healthy": healthy},
    )


def _artifact_index(run_dir: Path) -> dict[str, list[str]]:
    roots = {
        "overnight_run": run_dir,
        "compose_chaos": REPO_ROOT / ".mesh-runtime-state" / "compose-chaos",
        "research": REPO_ROOT / ".mesh-runtime-state" / "research",
        "proofs": run_dir / "proofs",
    }
    index: dict[str, list[str]] = {}
    for key, root in roots.items():
        if not root.exists():
            index[key] = []
            continue
        files = sorted(
            (path for path in root.rglob("*") if path.is_file()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        index[key] = [str(path) for path in files[:30]]
    return index


def _capability_map() -> dict[str, list[str]]:
    return {
        "compose_chaos_breakthrough": [
            "live Kubernetes actuation",
            "container/vm/baremetal substrate coverage",
            "multi-fault coverage",
            "post-injection Mesh run recovery",
        ],
        "autoresearch_matrix_synthesis": [
            "native/promptfoo evaluation matrix",
            "native/goose orchestration matrix",
            "HTTP control-plane runs",
            "prior synthesis evolution",
        ],
        "production_node_breakthrough": [
            "Reth/systemd probes",
            "OTel node pressure",
            "Docker Compose/bare-metal/VM signals",
            "negative controls and multi-fault classification",
        ],
        "simulation_benchmarks": [
            "stress matrix trend",
            "pass-rate and latency regression evidence",
            "reconciliation disagreement tracking",
        ],
        "halo_outer_loop": [
            "Mesh run trace export",
            "HALO harness failure-mode optimizer",
            "bounded harness patch-task recording",
        ],
    }


def _overall_status(results: list[LaneResult]) -> str:
    hard_failures = [result for result in results if result.status in {"failed", "timed_out"} and result.name in {"compose_stack_up"}]
    if hard_failures:
        return "failed"
    if any(result.status in {"failed", "timed_out", "completed_with_findings"} for result in results):
        return "completed_with_findings"
    return "completed"


def _write_markdown(path: Path, manifest: dict[str, Any]) -> None:
    lanes = manifest.get("lanes") or []
    lines = [
        "# Overnight Mesh Breakthrough Report",
        "",
        f"- Status: {manifest.get('status')}",
        f"- Started: {manifest.get('started_at')}",
        f"- Finished: {manifest.get('finished_at')}",
        f"- Output: `{manifest.get('output_directory')}`",
        "",
        "## Lanes",
        "",
        "| Lane | Status | Seconds | Log |",
        "| --- | --- | ---: | --- |",
    ]
    for lane in lanes:
        lines.append(
            f"| {lane.get('name')} | {lane.get('status')} | {lane.get('elapsed_seconds')} | `{lane.get('log_path') or ''}` |"
        )
    lines.extend(["", "## Artifact Index", ""])
    for key, files in (manifest.get("artifact_index") or {}).items():
        lines.append(f"### {key}")
        if files:
            lines.extend(f"- `{item}`" for item in files[:10])
        else:
            lines.append("- none")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _remaining(deadline: float) -> float:
    return max(1.0, deadline - time.monotonic())


def _truthy(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _from_monotonic(started: float) -> str:
    wall_started = time.time() - (time.monotonic() - started)
    return datetime.fromtimestamp(wall_started, tz=timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
