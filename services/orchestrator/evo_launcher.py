from __future__ import annotations

import json
import re
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from shared.mesh_runtime import RuntimeConfig


_DASHBOARD_URL_RE = re.compile(r"Dashboard live:\s*(http://127\.0\.0\.1:\d+)")
_MAX_OUTPUT_CHARS = 20_000


class EvoLaunchService:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def run_launch(
        self,
        *,
        run_id: str,
        repo_path: str,
        target_path: str,
        benchmark_command: str | None,
        metric: str,
        instrumentation_mode: str,
        gate_command: str | None,
        note: str | None = None,
    ) -> dict[str, Any]:
        launch_id = f"evo_{run_id}_{uuid4().hex[:8]}"
        repo = Path(repo_path).resolve()
        workspace_detected = (repo / ".evo" / "meta.json").is_file()
        record: dict[str, Any] = {
            "launch_id": launch_id,
            "action": "status" if workspace_detected else "discover_bootstrap",
            "status": "running",
            "requested_at": _timestamp(),
            "started_at": _timestamp(),
            "completed_at": None,
            "repo_path": str(repo),
            "target_path": target_path,
            "metric": metric,
            "instrumentation_mode": instrumentation_mode,
            "benchmark_command": benchmark_command,
            "gate_command": gate_command,
            "workspace_detected": workspace_detected,
            "dashboard_url": None,
            "steps": [],
            "error": None,
        }
        try:
            if workspace_detected:
                status_step = self._run_command(repo, ["status"])
                record["steps"].append(status_step)
                if status_step["returncode"] != 0:
                    raise RuntimeError(status_step["stderr"] or status_step["stdout"] or "evo status failed")
            else:
                if not benchmark_command:
                    raise ValueError("benchmark_command is required when the repo does not already contain an Evo workspace")
                self._ensure_clean_git(repo)
                init_args = [
                    "init",
                    "--target",
                    target_path,
                    "--benchmark",
                    benchmark_command,
                    "--metric",
                    metric,
                    "--instrumentation-mode",
                    instrumentation_mode,
                ]
                if gate_command:
                    init_args.extend(["--gate", gate_command])
                init_step = self._run_command(repo, init_args)
                record["steps"].append(init_step)
                record["dashboard_url"] = _dashboard_url(init_step["stdout"]) or _dashboard_url(init_step["stderr"])
                if init_step["returncode"] != 0:
                    raise RuntimeError(init_step["stderr"] or init_step["stdout"] or "evo init failed")

                launch_note = note or "mesh: bounded discover bootstrap"
                new_step = self._run_command(repo, ["new", "--parent", "root", "-m", launch_note])
                record["steps"].append(new_step)
                if new_step["returncode"] != 0:
                    raise RuntimeError(new_step["stderr"] or new_step["stdout"] or "evo new failed")
                exp_id = _parse_new_experiment_id(new_step["stdout"])
                record["experiment_id"] = exp_id

                run_step = self._run_command(repo, ["run", exp_id])
                record["steps"].append(run_step)
                if run_step["returncode"] != 0:
                    raise RuntimeError(run_step["stderr"] or run_step["stdout"] or "evo run failed")

            record["status"] = "completed"
        except Exception as exc:  # noqa: BLE001
            record["status"] = "failed"
            record["error"] = str(exc)
        record["completed_at"] = _timestamp()
        return record

    def _run_command(self, repo: Path, args: list[str]) -> dict[str, Any]:
        base = shlex.split(self.config.evo_command or "")
        if not base:
            raise RuntimeError("MESH_EVO_COMMAND is not configured")
        started = time.time()
        try:
            completed = subprocess.run(
                base + args,
                cwd=repo,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.config.evo_command_timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(str(exc)) from exc
        return {
            "argv": base + args,
            "returncode": completed.returncode,
            "stdout": _cap(completed.stdout),
            "stderr": _cap(completed.stderr),
            "duration_seconds": round(time.time() - started, 3),
        }

    def _ensure_clean_git(self, repo: Path) -> None:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "git status failed")
        if completed.stdout.strip():
            raise RuntimeError("repo has uncommitted changes; Evo bootstrap requires a clean git worktree")


def _parse_new_experiment_id(stdout: str) -> str:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise RuntimeError("evo new did not return JSON") from exc
    exp_id = payload.get("id")
    if not isinstance(exp_id, str) or not exp_id:
        raise RuntimeError("evo new did not return an experiment id")
    return exp_id


def _dashboard_url(text: str) -> str | None:
    match = _DASHBOARD_URL_RE.search(text or "")
    if not match:
        return None
    return match.group(1)


def _cap(value: str) -> str:
    if len(value) <= _MAX_OUTPUT_CHARS:
        return value
    return value[:_MAX_OUTPUT_CHARS] + "\n[truncated]\n"


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
