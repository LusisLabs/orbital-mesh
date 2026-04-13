#!/usr/bin/env python3
"""Overnight Mesh autoresearch: evolving MiniMax briefs + double session archive.

Environment (optional, same names as overnight_autoresearch_loop.sh):
  OVERNIGHT_DURATION_SECONDS, OVERNIGHT_INTERVAL_SECONDS
  OVERNIGHT_EVALUATION_MODE, OVERNIGHT_ORCHESTRATION_MODE
  OVERNIGHT_MINIMAX (1 to run MiniMax after each showcase)
  OVERNIGHT_HTTP_RUNS, BASE_URL, E2E_RUN_TERMINAL_WAIT_SECONDS, STEERING_MODE, GOAL_ID, …
  OVERNIGHT_EVOLVE_PRIOR (default 1) — prepend last cycle's synthesis/final-report.md
  OVERNIGHT_DOUBLE_ARCHIVE (default 1) — two full copytrees under research/_archive/
  OVERNIGHT_ARCHIVE_VAULT_TWICE (default 0) — also duplicate MESH_VAULT_PATH twice per cycle
  OVERNIGHT_OLLAMA_FALLBACK (default 1) — if MiniMax cannot run or fails, synthesize via Ollama chat API;
    if live HTTP e2e fails, write a short Ollama remediation note under notes/
  OVERNIGHT_OLLAMA_MODEL (default gemma4:31b-it-q4_K_M) — must exist in `ollama list` (pull first if needed)
  OLLAMA_HOST (default http://127.0.0.1:11434)
  OVERNIGHT_OLLAMA_TRY_SERVE (default 0) — if 1, attempt `ollama serve` in the background when the API is down
  OVERNIGHT_OLLAMA_CHAT_TIMEOUT_SECONDS (default 900)
  OVERNIGHT_HOLISTIC_MATRIX (default 1) — sweep native/promptfoo × native/goose across all pipeline fixtures per cycle
  OVERNIGHT_HTTP_FULL_MATRIX (default 0) — when HTTP holistic: each cycle hits live K8s + both scenario_keys × all
    mode pairs (12 POSTs). When 0, one rotated payload × four mode pairs (4 POSTs/cycle).
  OVERNIGHT_HTTP_PER_RUN_TIMEOUT_SECONDS (default 300) — terminal wait per control-plane run in holistic HTTP mode
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.config import RuntimeConfig  # noqa: E402

from scripts.mesh_showcase_research import holistic_eval_orchestration_pairs  # noqa: E402

ARCHIVE_DIRNAME = "_archive"
PRIOR_EXCERPT_CHARS = 14_000


def _truthy(raw: str | None, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _falsy(raw: str | None, default: bool) -> bool:
    """Like _truthy but treats explicit 0/false/off as False when raw is set."""
    if raw is None or raw == "":
        return default
    s = raw.strip().lower()
    if s in ("0", "false", "no", "off"):
        return False
    return s in ("1", "true", "yes", "on")


def _load_repo_dotenv() -> None:
    path = REPO_ROOT / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        val = rest.strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1].replace('\\"', '"')
        elif val.startswith("'") and val.endswith("'"):
            val = val[1:-1]
        if key and key not in os.environ:
            os.environ[key] = val


def _minimax_env_configured() -> bool:
    if os.environ.get("OPENAI_API_KEY"):
        return True
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return False


def _ollama_host() -> str:
    return (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")


def _ollama_chat_timeout_seconds() -> int:
    raw = os.environ.get("OVERNIGHT_OLLAMA_CHAT_TIMEOUT_SECONDS", "900")
    try:
        return max(60, int(str(raw).strip()))
    except ValueError:
        return 900


def _maybe_spawn_ollama_serve(host: str) -> None:
    if not _truthy(os.environ.get("OVERNIGHT_OLLAMA_TRY_SERVE"), False):
        return
    if shutil.which("ollama") is None:
        print("warning: OVERNIGHT_OLLAMA_TRY_SERVE set but `ollama` not on PATH", flush=True)
        return
    if _ollama_api_reachable(host):
        return
    print("starting `ollama serve` in background (OVERNIGHT_OLLAMA_TRY_SERVE=1) …", flush=True)
    subprocess.Popen(
        ["ollama", "serve"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(15):
        time.sleep(1)
        if _ollama_api_reachable(host):
            print("ollama API became reachable.", flush=True)
            return
    print("warning: ollama API still unreachable after background serve wait", flush=True)


def _ollama_api_reachable(host: str) -> bool:
    try:
        url = f"{host.rstrip('/')}/api/tags"
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ollama_pull_model(model: str) -> None:
    ollama_bin = shutil.which("ollama")
    if ollama_bin is None:
        raise RuntimeError("`ollama` CLI not found on PATH (install Ollama or add to PATH)")
    proc = subprocess.run(
        [ollama_bin, "pull", model],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=7200,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "ollama pull failed")


def _ollama_chat(host: str, model: str, *, system: str, user: str) -> str:
    url = f"{host.rstrip('/')}/api/chat"
    payload = json.dumps(
        {
            "model": model,
            "messages": (
                [{"role": "system", "content": system}, {"role": "user", "content": user}]
                if system
                else [{"role": "user", "content": user}]
            ),
            "stream": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=float(_ollama_chat_timeout_seconds())) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ollama HTTP {exc.code}: {body[:800]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ollama unreachable at {host}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("ollama returned non-object JSON")
    if data.get("error"):
        raise RuntimeError(str(data["error"]))
    msg = data.get("message") or {}
    content = (msg.get("content") if isinstance(msg, dict) else None) or ""
    if not str(content).strip():
        raise RuntimeError("ollama returned empty message content")
    return str(content)


def _run_ollama_fallback_synthesis(session_dir: Path, *, reason: str) -> None:
    _load_repo_dotenv()
    host = _ollama_host()
    model = os.environ.get("OVERNIGHT_OLLAMA_MODEL", "gemma4:31b-it-q4_K_M").strip() or "gemma4:31b-it-q4_K_M"
    _maybe_spawn_ollama_serve(host)

    manifest_path = session_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    question = str(manifest.get("question", "")).strip()
    if len(question) > 28_000:
        question = question[:28_000] + "\n\n[…question truncated for Ollama context…]\n"

    system = (
        "You are a principal engineer writing Mesh Intelligence research. "
        "Output polished markdown only. Be precise; no fake benchmarks or '#1' claims."
    )
    user = textwrap.dedent(
        f"""
        Context: overnight autoresearch fallback via local Ollama ({reason}).

        Use the session brief below (empirical digest + any carry-forward context) to produce
        a single **Final Report** comparable to a multi-wave research deliverable:

        # Executive summary
        # Key findings (numbered)
        # Risks and unknowns
        # Concrete next actions for the mesh-intelligence codebase and operators

        ## Session brief (manifest question)

        {question}
        """
    ).strip()

    try:
        text = _ollama_chat(host, model, system=system, user=user)
    except RuntimeError as first:
        err = str(first).lower()
        if "not found" in err or "file does not exist" in err or "pull" in err:
            print(f"ollama: pulling model {model} …", flush=True)
            _ollama_pull_model(model)
            text = _ollama_chat(host, model, system=system, user=user)
        else:
            raise

    synth = session_dir / "synthesis"
    synth.mkdir(parents=True, exist_ok=True)
    header = (
        f"# Final report — Ollama fallback ({model})\n\n"
        f"_Reason: {reason} · {datetime.now(timezone.utc).isoformat()}_\n\n"
    )
    (synth / "final-report.md").write_text(header + text.strip() + "\n", encoding="utf-8")

    manifest["overnight_synthesis_route"] = "ollama_fallback"
    manifest["overnight_ollama_model"] = model
    manifest["overnight_ollama_reason"] = reason
    manifest["status"] = "overnight_ollama_synthesis_complete"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"ollama fallback synthesis wrote {synth / 'final-report.md'}", flush=True)


def _run_ollama_http_failure_note(session_dir: Path, *, error: str) -> None:
    _load_repo_dotenv()
    host = _ollama_host()
    model = os.environ.get("OVERNIGHT_OLLAMA_MODEL", "gemma4:31b-it-q4_K_M").strip() or "gemma4:31b-it-q4_K_M"
    _maybe_spawn_ollama_serve(host)
    notes = session_dir / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    system = "You write short operator runbooks for local Kubernetes + Mesh control plane issues."
    user = (
        "The mesh overnight loop failed to complete scripts/e2e_run_mesh.sh (live POST /api/runs + kubectl). "
        f"Error summary:\n```\n{error[:4000]}\n```\n\n"
        "Write markdown (max ~400 words) with: likely causes, checks (kubectl context, cluster up, "
        "MESH_KUBERNETES_* env, BASE_URL), and safe recovery steps. No filler."
    )
    try:
        body = _ollama_chat(host, model, system=system, user=user)
    except RuntimeError as first:
        err = str(first).lower()
        if "not found" in err or "file does not exist" in err or "pull" in err:
            _ollama_pull_model(model)
            body = _ollama_chat(host, model, system=system, user=user)
        else:
            raise
    path = notes / "kubernetes_http_run_fallback.md"
    path.write_text(
        f"# Kubernetes HTTP e2e — Ollama fallback note\n\n"
        f"_Model `{model}` · {datetime.now(timezone.utc).isoformat()}_\n\n"
        + body.strip()
        + "\n",
        encoding="utf-8",
    )
    print(f"ollama wrote HTTP failure note: {path}", flush=True)


def _research_root(cfg: RuntimeConfig) -> Path:
    return Path(cfg.state_directory).resolve() / "research"


def _archive_root(cfg: RuntimeConfig) -> Path:
    return _research_root(cfg) / ARCHIVE_DIRNAME


def _iter_session_dirs(research_root: Path) -> list[Path]:
    if not research_root.is_dir():
        return []
    out: list[Path] = []
    for p in research_root.iterdir():
        if not p.is_dir():
            continue
        if p.name == ARCHIVE_DIRNAME or p.name.startswith("."):
            continue
        out.append(p)
    return out


def _latest_prior_final_report(research_root: Path, exclude: Path | None) -> str | None:
    """Return text of the newest synthesis/final-report.md among sessions (excluding `exclude`)."""
    candidates: list[tuple[float, Path]] = []
    for p in _iter_session_dirs(research_root):
        if exclude is not None and p.resolve() == exclude.resolve():
            continue
        fr = p / "synthesis" / "final-report.md"
        if not fr.is_file():
            continue
        try:
            candidates.append((fr.stat().st_mtime, fr))
        except OSError:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    text = candidates[0][1].read_text(encoding="utf-8")
    if len(text) > PRIOR_EXCERPT_CHARS:
        return text[: PRIOR_EXCERPT_CHARS - 40] + "\n\n[…truncated prior synthesis…]\n"
    return text


def _merge_prior_into_manifest_question(session_dir: Path, prior: str) -> None:
    manifest_path = session_dir / "manifest.json"
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    original = str(manifest.get("question", ""))
    merged = (
        "## Carried forward from the previous overnight synthesis\n\n"
        f"{prior.strip()}\n\n"
        "---\n\n"
        "## Current cycle — empirical grounding + instructions\n\n"
        f"{original}"
    )
    manifest["question"] = merged
    manifest["overnight_prior_context"] = True
    manifest["overnight_prior_context_truncated_chars"] = min(len(prior), PRIOR_EXCERPT_CHARS)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _double_archive_session(
    session_dir: Path,
    archive_root: Path,
    *,
    cycle: int,
    extra_meta: dict[str, Any],
) -> tuple[Path, Path]:
    archive_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{ts}_overnight_cycle{cycle:04d}_{session_dir.name}"
    dest_a = archive_root / f"{base}_archive_a"
    dest_b = archive_root / f"{base}_archive_b"
    if dest_a.exists() or dest_b.exists():
        raise FileExistsError(f"archive destination already exists: {dest_a} or {dest_b}")
    shutil.copytree(session_dir, dest_a, symlinks=True)
    shutil.copytree(session_dir, dest_b, symlinks=True)
    meta = {
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "cycle": cycle,
        "source_session": str(session_dir),
        "archive_a": str(dest_a),
        "archive_b": str(dest_b),
        **extra_meta,
    }
    (archive_root / f"{base}_ARCHIVE_MANIFEST.json").write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return dest_a, dest_b


def _double_archive_path_tree(src: Path, archive_root: Path, *, cycle: int, label: str) -> tuple[Path, Path] | None:
    if not src.is_dir():
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{ts}_overnight_cycle{cycle:04d}_{label}"
    dest_a = archive_root / f"{base}_archive_a"
    dest_b = archive_root / f"{base}_archive_b"
    if dest_a.exists() or dest_b.exists():
        raise FileExistsError(f"vault archive collision: {dest_a}")
    shutil.copytree(src, dest_a, symlinks=True)
    shutil.copytree(src, dest_b, symlinks=True)
    return dest_a, dest_b


def _http_get_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post_json(url: str, payload: dict[str, Any], *, timeout: int = 60) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:800]}") from exc


def _http_wait_control_plane_health(base_url: str, *, deadline_s: float = 60) -> None:
    base_url = base_url.rstrip("/")
    health = f"{base_url}/api/health"
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        try:
            req = urllib.request.Request(health, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"control plane not healthy: {health}")


def _http_wait_run_terminal(base_url: str, run_id: str, *, deadline_s: float) -> dict[str, Any]:
    terminal = {"completed", "failed", "cancelled", "no_trigger"}
    base_url = base_url.rstrip("/")
    deadline = time.time() + max(5.0, deadline_s)
    while time.time() < deadline:
        run = _http_get_json(f"{base_url}/api/runs/{run_id}", timeout=30)
        if run.get("stage") in terminal:
            return run
        time.sleep(1)
    raise TimeoutError(f"run {run_id} did not reach a terminal stage within {deadline_s}s")


def _http_holistic_payloads_for_cycle(*, full_matrix: bool, cycle_index: int) -> list[tuple[str, str | None]]:
    triple: list[tuple[str, str | None]] = [
        ("live", None),
        ("scenario", "search_latency_regression"),
        ("scenario", "kubernetes_crashloop_patch"),
    ]
    if full_matrix:
        return triple
    return [triple[(cycle_index - 1) % len(triple)]]


def _http_build_run_payload(
    *,
    goal_id: str,
    evaluation_mode: str,
    orchestration_mode: str,
    steering_mode: str,
    kind: str,
    scenario_key: str | None,
    live: dict[str, str],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "goal_id": goal_id,
        "evaluation_mode": evaluation_mode,
        "orchestration_mode": orchestration_mode,
        "steering_mode": steering_mode,
    }
    if kind == "live":
        body["live_signal"] = {
            "source": "kubernetes",
            "deployment_name": live["deployment_name"],
            "namespace": live["namespace"],
            "kube_context": live["kube_context"],
            "environment": live["environment"],
        }
    elif kind == "scenario":
        if not scenario_key:
            raise ValueError("scenario_key required for scenario payload")
        body["scenario_key"] = scenario_key
    else:
        raise ValueError(f"unknown payload kind {kind!r}")
    return body


def _run_http_holistic_suite(
    session_dir: Path,
    *,
    cycle_index: int,
    full_matrix: bool,
    per_run_deadline_s: float,
) -> list[dict[str, Any]]:
    base_url = os.environ.get("BASE_URL", "http://127.0.0.1:8787").rstrip("/")
    goal_id = os.environ.get("GOAL_ID", "goal_default")
    steering = os.environ.get("STEERING_MODE", "interruptible_auto")
    live = {
        "deployment_name": os.environ.get("DEPLOYMENT_NAME", "semantic-search"),
        "namespace": os.environ.get("NAMESPACE", "search"),
        "kube_context": os.environ.get("KUBE_CONTEXT", "k3d-mesh-e2e"),
        "environment": os.environ.get("ENVIRONMENT", "local"),
    }
    _http_wait_control_plane_health(base_url)
    kinds = _http_holistic_payloads_for_cycle(full_matrix=full_matrix, cycle_index=cycle_index)
    pairs = holistic_eval_orchestration_pairs()
    records: list[dict[str, Any]] = []
    for evaluation_mode, orchestration_mode in pairs:
        for kind, scenario_key in kinds:
            label = f"{evaluation_mode}+{orchestration_mode}:{kind}" + (
                f":{scenario_key}" if scenario_key else ""
            )
            body = _http_build_run_payload(
                goal_id=goal_id,
                evaluation_mode=evaluation_mode,
                orchestration_mode=orchestration_mode,
                steering_mode=steering,
                kind=kind,
                scenario_key=scenario_key,
                live=live,
            )
            run_id: str | None = None
            last_err: BaseException | None = None
            for _attempt in range(5):
                try:
                    out = _http_post_json(f"{base_url}/api/runs", body, timeout=60)
                    run_id = str(out["run_id"])
                    break
                except Exception as exc:
                    last_err = exc
                    time.sleep(1)
            if not run_id:
                records.append({"label": label, "error": f"post_failed:{last_err!s}"[:500]})
                continue
            try:
                final = _http_wait_run_terminal(base_url, run_id, deadline_s=per_run_deadline_s)
            except TimeoutError as te:
                records.append({"label": label, "run_id": run_id, "error": str(te)})
                continue
            arts = final.get("artifacts") or {}
            records.append(
                {
                    "label": label,
                    "run_id": run_id,
                    "stage": final.get("stage"),
                    "scenario_key": final.get("scenario_key"),
                    "decision_type": (arts.get("decision") or {}).get("decision_type"),
                    "execution_status": (arts.get("execution") or {}).get("status"),
                    "evaluation_recommendation": (arts.get("evaluation") or {}).get("final_recommendation"),
                }
            )
    data_dir = session_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "http_holistic_runs.json").write_text(
        json.dumps(records, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {data_dir / 'http_holistic_runs.json'} ({len(records)} control-plane runs)", flush=True)
    return records


def _run_showcase_session_dir(
    *,
    evaluation_mode: str,
    orchestration_mode: str,
    embed_minimax_prompt: bool,
    holistic_matrix: bool,
) -> Path:
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "mesh_showcase_research.py")]
    if holistic_matrix:
        cmd.append("--holistic-matrix")
    else:
        cmd.extend(["--evaluation-mode", evaluation_mode, "--orchestration-mode", orchestration_mode])
    if embed_minimax_prompt:
        cmd.append("--embed-minimax-prompt")
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "mesh_showcase_research failed")
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not lines:
        raise RuntimeError("mesh_showcase_research produced no stdout")
    session_dir = Path(lines[0]).resolve()
    if not session_dir.is_dir():
        raise RuntimeError(f"invalid session path from showcase: {session_dir}")
    return session_dir


def _run_minimax(session_dir: Path) -> None:
    runner = REPO_ROOT / ".cursor/skills/goose-autoresearch/scripts/run_minimax_research.py"
    if not runner.is_file():
        raise FileNotFoundError(runner)
    proc = subprocess.run(
        [sys.executable, str(runner), "--session-dir", str(session_dir)],
        cwd=str(REPO_ROOT),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"run_minimax_research exited {proc.returncode}")


def _run_http_mesh_sh() -> None:
    proc = subprocess.run(["bash", str(REPO_ROOT / "scripts" / "e2e_run_mesh.sh")], cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        raise RuntimeError(f"e2e_run_mesh.sh exited {proc.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Overnight Mesh autoresearch: holistic pipeline+HTTP sweeps (eval/orch matrix), optional MiniMax, "
        "Ollama fallback, double archive."
    )
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=int(os.environ.get("OVERNIGHT_DURATION_SECONDS", str(8 * 3600))),
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.environ.get("OVERNIGHT_INTERVAL_SECONDS", "900")),
    )
    parser.add_argument(
        "--evaluation-mode",
        default=os.environ.get("OVERNIGHT_EVALUATION_MODE", "promptfoo"),
    )
    parser.add_argument(
        "--orchestration-mode",
        default=os.environ.get("OVERNIGHT_ORCHESTRATION_MODE", "goose"),
    )
    parser.add_argument(
        "--minimax",
        action=argparse.BooleanOptionalAction,
        default=_truthy(os.environ.get("OVERNIGHT_MINIMAX"), False),
    )
    parser.add_argument(
        "--http-runs",
        action=argparse.BooleanOptionalAction,
        default=_truthy(os.environ.get("OVERNIGHT_HTTP_RUNS"), False),
    )
    parser.add_argument(
        "--evolve-prior",
        action=argparse.BooleanOptionalAction,
        default=_truthy(os.environ.get("OVERNIGHT_EVOLVE_PRIOR"), True),
    )
    parser.add_argument(
        "--double-archive",
        action=argparse.BooleanOptionalAction,
        default=_truthy(os.environ.get("OVERNIGHT_DOUBLE_ARCHIVE"), True),
    )
    parser.add_argument(
        "--archive-vault-twice",
        action=argparse.BooleanOptionalAction,
        default=_truthy(os.environ.get("OVERNIGHT_ARCHIVE_VAULT_TWICE"), False),
    )
    parser.add_argument(
        "--ollama-fallback",
        action=argparse.BooleanOptionalAction,
        default=_falsy(os.environ.get("OVERNIGHT_OLLAMA_FALLBACK"), True),
        help="When MiniMax cannot run or fails, synthesize final-report.md via Ollama; on HTTP e2e failure, "
        "write notes/kubernetes_http_run_fallback.md. Set OVERNIGHT_OLLAMA_FALLBACK=0 to disable.",
    )
    parser.add_argument(
        "--holistic-matrix",
        action=argparse.BooleanOptionalAction,
        default=_falsy(os.environ.get("OVERNIGHT_HOLISTIC_MATRIX"), True),
        help="Run mesh_showcase_research --holistic-matrix (4×3 pipeline sweep). Set OVERNIGHT_HOLISTIC_MATRIX=0 to use single eval/orch.",
    )
    parser.add_argument(
        "--http-full-matrix",
        action=argparse.BooleanOptionalAction,
        default=_truthy(os.environ.get("OVERNIGHT_HTTP_FULL_MATRIX"), False),
        help="Holistic HTTP: POST live + both scenario fixtures × all eval/orch pairs each cycle (12 runs). "
        "Default rotates one payload kind per cycle × four pairs (4 runs).",
    )
    args = parser.parse_args()

    _load_repo_dotenv()

    cfg = RuntimeConfig.from_env()
    research_root = _research_root(cfg)
    archive_root = _archive_root(cfg)
    end_ts = time.time() + max(60, args.duration_seconds)
    cycle = 0

    print(f"overnight_mesh_autoresearch: repo={REPO_ROOT}", flush=True)
    print(
        f"research_root={research_root} | until={datetime.fromtimestamp(end_ts, tz=timezone.utc).isoformat()} | "
        f"interval={args.interval_seconds}s | eval={args.evaluation_mode} orch={args.orchestration_mode} | "
        f"minimax={args.minimax} http={args.http_runs} evolve_prior={args.evolve_prior} "
        f"double_archive={args.double_archive} archive_vault_twice={args.archive_vault_twice} "
        f"ollama_fallback={args.ollama_fallback} holistic_matrix={args.holistic_matrix} "
        f"http_full_matrix={args.http_full_matrix}",
        flush=True,
    )

    while time.time() < end_ts:
        cycle += 1
        print(f"\n=== cycle {cycle} {datetime.now(timezone.utc).isoformat()} ===", flush=True)
        session_dir: Path | None = None
        cycle_meta: dict[str, Any] = {}
        try:
            session_dir = _run_showcase_session_dir(
                evaluation_mode=args.evaluation_mode,
                orchestration_mode=args.orchestration_mode,
                embed_minimax_prompt=args.minimax,
                holistic_matrix=args.holistic_matrix,
            )
            print(f"showcase session: {session_dir}", flush=True)
            cycle_meta["synthesis"] = "none"
            cycle_meta["http"] = "skipped"

            if args.minimax:
                prior = None
                if args.evolve_prior:
                    prior = _latest_prior_final_report(research_root, exclude=session_dir)
                if prior:
                    print("merging prior synthesis into manifest question", flush=True)
                    _merge_prior_into_manifest_question(session_dir, prior)

                ran_minimax = False
                if _minimax_env_configured():
                    try:
                        _run_minimax(session_dir)
                        ran_minimax = True
                        cycle_meta["synthesis"] = "minimax"
                    except Exception as mm_exc:
                        print(f"warning: MiniMax run failed: {mm_exc!r}", file=sys.stderr, flush=True)
                        cycle_meta["minimax_error"] = str(mm_exc)[:800]
                else:
                    print(
                        "MiniMax API keys not configured (OPENAI_API_KEY / ANTHROPIC_*); skipping MiniMax.",
                        flush=True,
                    )
                    cycle_meta["synthesis"] = "minimax_skipped_no_keys"

                if not ran_minimax and args.ollama_fallback:
                    try:
                        reason = "minimax_failed" if _minimax_env_configured() else "minimax_not_configured"
                        _run_ollama_fallback_synthesis(session_dir, reason=reason)
                        cycle_meta["synthesis"] = "ollama_fallback"
                    except Exception as ol_exc:
                        print(f"warning: Ollama synthesis fallback failed: {ol_exc!r}", file=sys.stderr, flush=True)
                        cycle_meta["ollama_error"] = str(ol_exc)[:800]
                elif not ran_minimax:
                    print("warning: no MiniMax and Ollama fallback disabled; no synthesis for this cycle.", flush=True)

            if args.http_runs:
                os.environ.setdefault("BASE_URL", "http://127.0.0.1:8787")
                os.environ.setdefault("GOAL_ID", "goal_default")
                os.environ.setdefault("STEERING_MODE", os.environ.get("STEERING_MODE", "interruptible_auto"))
                try:
                    if args.holistic_matrix:
                        per_run = float(os.environ.get("OVERNIGHT_HTTP_PER_RUN_TIMEOUT_SECONDS", "300"))
                        records = _run_http_holistic_suite(
                            session_dir,
                            cycle_index=cycle,
                            full_matrix=bool(args.http_full_matrix),
                            per_run_deadline_s=per_run,
                        )
                        errs = sum(1 for r in records if r.get("error"))
                        cycle_meta["http"] = f"holistic_{len(records)}_runs_{errs}_errors"
                    else:
                        if not os.environ.get("E2E_RUN_TERMINAL_WAIT_SECONDS"):
                            os.environ.setdefault("E2E_RUN_TERMINAL_WAIT_SECONDS", "3600")
                        os.environ.setdefault("EVALUATION_MODE", args.evaluation_mode)
                        os.environ.setdefault("ORCHESTRATION_MODE", args.orchestration_mode)
                        print("running scripts/e2e_run_mesh.sh …", flush=True)
                        _run_http_mesh_sh()
                        cycle_meta["http"] = "ok"
                except Exception as http_exc:
                    cycle_meta["http"] = f"error:{http_exc!s}"[:500]
                    print(f"warning: HTTP e2e run failed: {http_exc!r}", file=sys.stderr, flush=True)
                    if args.ollama_fallback:
                        try:
                            _run_ollama_http_failure_note(session_dir, error=str(http_exc))
                            cycle_meta["http_ollama_note"] = True
                        except Exception as note_exc:
                            print(
                                f"warning: Ollama HTTP failure note failed: {note_exc!r}",
                                file=sys.stderr,
                                flush=True,
                            )

        except Exception as exc:
            print(f"warning: cycle {cycle} error: {exc!r}", file=sys.stderr, flush=True)
        finally:
            if args.double_archive and session_dir is not None and session_dir.is_dir():
                extra: dict[str, Any] = {
                    "evaluation_mode": args.evaluation_mode,
                    "orchestration_mode": args.orchestration_mode,
                    "minimax": args.minimax,
                    "http_runs": args.http_runs,
                    "evolve_prior": args.evolve_prior,
                    "holistic_matrix": args.holistic_matrix,
                    "http_full_matrix": args.http_full_matrix,
                    **cycle_meta,
                }
                try:
                    a, b = _double_archive_session(session_dir, archive_root, cycle=cycle, extra_meta=extra)
                    print(f"archived session x2:\n  {a}\n  {b}", flush=True)
                except Exception as arch_exc:
                    print(
                        f"warning: double-archive failed for {session_dir}: {arch_exc!r}",
                        file=sys.stderr,
                        flush=True,
                    )
            if args.archive_vault_twice:
                vault = Path(cfg.vault_path).resolve()
                try:
                    va = _double_archive_path_tree(vault, archive_root, cycle=cycle, label=f"vault_{vault.name}")
                    if va:
                        print(f"archived vault x2:\n  {va[0]}\n  {va[1]}", flush=True)
                except Exception as vault_exc:
                    print(f"warning: vault double-archive failed: {vault_exc!r}", file=sys.stderr, flush=True)

        if time.time() >= end_ts:
            break
        remaining = end_ts - time.time()
        sleep_s = min(args.interval_seconds, max(0, int(remaining)))
        if sleep_s > 0:
            print(f"sleeping {sleep_s}s …", flush=True)
            time.sleep(sleep_s)

    print(f"overnight_mesh_autoresearch finished after {cycle} cycle(s).", flush=True)


if __name__ == "__main__":
    main()
