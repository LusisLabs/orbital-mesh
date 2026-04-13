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
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.config import RuntimeConfig  # noqa: E402

ARCHIVE_DIRNAME = "_archive"
PRIOR_EXCERPT_CHARS = 14_000


def _truthy(raw: str | None, default: bool) -> bool:
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


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


def _run_showcase_session_dir(
    *,
    evaluation_mode: str,
    orchestration_mode: str,
    embed_minimax_prompt: bool,
) -> Path:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "scripts" / "mesh_showcase_research.py"),
        "--evaluation-mode",
        evaluation_mode,
        "--orchestration-mode",
        orchestration_mode,
    ]
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
        description="Overnight Mesh autoresearch: Promptfoo+Goose showcase, optional evolving MiniMax, "
        "optional live K8s HTTP run, double archive of each research session."
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
    args = parser.parse_args()

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
        f"double_archive={args.double_archive} archive_vault_twice={args.archive_vault_twice}",
        flush=True,
    )

    while time.time() < end_ts:
        cycle += 1
        print(f"\n=== cycle {cycle} {datetime.now(timezone.utc).isoformat()} ===", flush=True)
        session_dir: Path | None = None
        try:
            session_dir = _run_showcase_session_dir(
                evaluation_mode=args.evaluation_mode,
                orchestration_mode=args.orchestration_mode,
                embed_minimax_prompt=args.minimax,
            )
            print(f"showcase session: {session_dir}", flush=True)

            if args.minimax:
                prior = None
                if args.evolve_prior:
                    prior = _latest_prior_final_report(research_root, exclude=session_dir)
                if prior:
                    print("merging prior synthesis into manifest question", flush=True)
                    _merge_prior_into_manifest_question(session_dir, prior)
                _run_minimax(session_dir)

            if args.http_runs:
                if not os.environ.get("E2E_RUN_TERMINAL_WAIT_SECONDS"):
                    os.environ.setdefault("E2E_RUN_TERMINAL_WAIT_SECONDS", "3600")
                os.environ.setdefault("BASE_URL", "http://127.0.0.1:8787")
                os.environ.setdefault("GOAL_ID", "goal_default")
                os.environ.setdefault("EVALUATION_MODE", args.evaluation_mode)
                os.environ.setdefault("ORCHESTRATION_MODE", args.orchestration_mode)
                os.environ.setdefault("STEERING_MODE", os.environ.get("STEERING_MODE", "interruptible_auto"))
                print("running scripts/e2e_run_mesh.sh …", flush=True)
                _run_http_mesh_sh()

            if args.double_archive and session_dir is not None:
                extra: dict[str, Any] = {
                    "evaluation_mode": args.evaluation_mode,
                    "orchestration_mode": args.orchestration_mode,
                    "minimax": args.minimax,
                    "http_runs": args.http_runs,
                    "evolve_prior": args.evolve_prior,
                }
                a, b = _double_archive_session(session_dir, archive_root, cycle=cycle, extra_meta=extra)
                print(f"archived session x2:\n  {a}\n  {b}", flush=True)

            if args.archive_vault_twice:
                vault = Path(cfg.vault_path).resolve()
                va = _double_archive_path_tree(vault, archive_root, cycle=cycle, label=f"vault_{vault.name}")
                if va:
                    print(f"archived vault x2:\n  {va[0]}\n  {va[1]}", flush=True)

        except Exception as exc:
            print(f"warning: cycle {cycle} error: {exc!r}", file=sys.stderr, flush=True)

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
