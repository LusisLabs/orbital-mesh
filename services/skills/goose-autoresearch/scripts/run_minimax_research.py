#!/usr/bin/env python3
"""
Multi-wave autoresearch using MiniMax (end-to-end, no Goose CLI).

Auth (first match wins for routing):
  - OPENAI_API_KEY (+ optional OPENAI_BASE_URL=https://api.minimax.io/v1) — OpenAI-compatible
  - Else ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN (+ ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic) — Anthropic-compatible fallback, same as Goose/Mesh .env

Loads repo `.env` when present (only sets variables not already in the environment).

Optional:
  export MINIMAX_MODEL=MiniMax-M2.7

Usage:
  python3 run_minimax_research.py --session-dir .mesh-runtime-state/research/<id>-<slug>
  python3 run_minimax_research.py --slug my-topic --question "Your research question?"

Writes wave artifacts under the session's results/ and synthesis/final-report.md.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Repo root: services/skills/goose-autoresearch/scripts/ -> parents[4]
REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from minimax_client import (  # noqa: E402
    chat_completion,
    minimax_model,
    minimax_route_label,
    research_chat_timeout_seconds,
)


def _load_repo_dotenv(repo_root: Path) -> None:
    """Lightweight .env load so `python3 run_minimax_research.py` picks up repo secrets without export."""
    path = repo_root / ".env"
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
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


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n\n[…truncated…]\n"


def _load_question(session_dir: Path) -> str:
    manifest_path = session_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        return str(manifest.get("question", "")).strip()
    raise SystemExit(f"No manifest.json in {session_dir}")


def _wave1_prompts(question: str) -> list[tuple[str, str, str]]:
    """worker_id, title, user content"""
    q = question.strip()
    shared = f"Primary research question:\n{q}\n"
    return [
        (
            "worker-01",
            "baseline",
            shared
            + textwrap.dedent(
                """
            You are worker-01 (baseline). Answer the question directly and thoroughly.
            Use clear sections: Summary, Landscape, Key Findings, Limits of this analysis.
            Prefer concrete comparisons and named categories over hype.
            """
            ).strip(),
        ),
        (
            "worker-02",
            "skeptic",
            shared
            + textwrap.dedent(
                """
            You are worker-02 (skeptic). Challenge optimistic assumptions.
            Sections: Weakest claims to avoid | Failure modes | What evidence would falsify conclusions | Safer public messaging.
            """
            ).strip(),
        ),
        (
            "worker-03",
            "deep-dive",
            shared
            + textwrap.dedent(
                """
            You are worker-03 (deep-dive). Focus on the hardest technical dimension: auditability,
            policy/evaluation gates, operator control, and execution safety in automated remediation systems.
            Sections: Rubric | Comparison axes | Where open-source vs SaaS typically differs.
            """
            ).strip(),
        ),
        (
            "worker-04",
            "editor",
            shared
            + textwrap.dedent(
                """
            You are worker-04 (editor). Do not add new facts; compare what a strong release narrative needs.
            Sections: Consensus outline | Conflicts to acknowledge | Glossary | Outline for an executive summary.
            """
            ).strip(),
        ),
    ]


def _run_worker(
    worker_id: str,
    title: str,
    user_content: str,
    system: str,
    *,
    timeout_seconds: float,
) -> tuple[str, str, str]:
    text = chat_completion(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        temperature=0.35,
        timeout_seconds=timeout_seconds,
    )
    return worker_id, title, text


def _wave3_timeout_seconds() -> float:
    base = research_chat_timeout_seconds()
    raw = os.getenv("MINIMAX_WAVE3_TIMEOUT_SECONDS")
    if raw is not None and str(raw).strip():
        return max(60.0, float(raw))
    return max(base, 900.0)


def _chat_completion_retry(
    messages: list[dict[str, str]],
    *,
    temperature: float,
    timeout_seconds: float,
    attempts: int = 3,
) -> str:
    last: Optional[RuntimeError] = None
    for attempt in range(attempts):
        try:
            return chat_completion(
                messages,
                temperature=temperature,
                timeout_seconds=timeout_seconds,
            )
        except RuntimeError as exc:
            last = exc
            if attempt >= attempts - 1 or "timed out" not in str(exc).lower():
                raise
            delay = min(8.0, 2.0**attempt)
            time.sleep(delay)
    assert last is not None
    raise last


def run_wave1(session_dir: Path, question: str) -> None:
    timeout = research_chat_timeout_seconds()
    system = (
        "You are a principal researcher for an infrastructure software product. "
        "Be precise, avoid unsubstantiated superlatives, and structure output in markdown."
    )
    results_dir = session_dir / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    prompts = _wave1_prompts(question)
    outputs: dict[str, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_run_worker, wid, title, body, system, timeout_seconds=timeout): wid
            for wid, title, body in prompts
        }
        for fut in as_completed(futures):
            wid, title, text = fut.result()
            outputs[wid] = (title, text)
            out_path = results_dir / f"wave1-{wid}-{title}-minimax.md"
            out_path.write_text(f"# {wid} ({title}) — MiniMax wave 1\n\n{text}\n")
    meta = {
        "wave": 1,
        "model": minimax_model(),
        "timeout_seconds": timeout,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "workers": list(outputs.keys()),
    }
    (results_dir / "wave1-minimax-meta.json").write_text(json.dumps(meta, indent=2) + "\n")


def run_wave2_lead(session_dir: Path, question: str) -> None:
    results_dir = session_dir / "results"
    parts = []
    for path in sorted(results_dir.glob("wave1-worker-*-minimax.md")):
        parts.append(f"## {path.name}\n\n{_truncate(path.read_text(), 14000)}")
    bundle = "\n\n".join(parts)
    system = (
        "You are the lead analyst for a multi-agent research session. "
        "You must produce an evidence-aware scorecard and gap analysis, not marketing copy."
    )
    user = textwrap.dedent(
        f"""
        Research question:
        {question}

        Below are four independent worker outputs from wave 1. Produce:

        1) **Scorecard** — table scoring each worker (1-5) on: Correctness, Evidence, Novelty, Actionability.
        2) **Consensus** — bullet list of agreements.
        3) **Conflicts** — disagreements or tensions; say how to resolve or what data is missing.
        4) **Gaps** — top 5 gaps for wave 3 to address in the final report.
        5) **Recommended framing** — 3 sentences safe for a public pre-release (no unverified benchmarks).

        Worker outputs:
        {bundle}
        """
    ).strip()
    text = chat_completion(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3,
        timeout_seconds=research_chat_timeout_seconds(),
    )
    (results_dir / "wave2-lead-scorecard-minimax.md").write_text(
        "# Wave 2 — Lead merge (MiniMax)\n\n" + text + "\n"
    )


def run_wave3_synthesis(session_dir: Path, question: str) -> None:
    results_dir = session_dir / "results"
    w2 = results_dir / "wave2-lead-scorecard-minimax.md"
    w2_text = w2.read_text() if w2.is_file() else ""
    w1_summary = "\n\n".join(
        _truncate(p.read_text(), 6000) for p in sorted(results_dir.glob("wave1-worker-*-minimax.md"))
    )
    system = (
        "You write the final research report for technical and executive readers. "
        "Tone: confident but honest; cite internal consistency, not fake third-party benchmarks."
    )
    user = textwrap.dedent(
        f"""
        Original question:
        {question}

        Wave 1 combined (possibly truncated):
        {w1_summary}

        Wave 2 lead analysis (scorecard + gaps):
        {_truncate(w2_text, 16000)}

        Write the **Final Report** with:
        # Executive summary
        # Key findings (numbered)
        # Competitive / ecosystem positioning (honest scope)
        # Risks and unknowns
        # Recommendations before public release
        # Appendix: evaluation rubric we can defend publicly

        Do not claim unsupported \"#1\" rankings; frame defensible differentiators.
        """
    ).strip()
    t3 = _wave3_timeout_seconds()
    text = _chat_completion_retry(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.25,
        timeout_seconds=t3,
    )
    synth_dir = session_dir / "synthesis"
    synth_dir.mkdir(parents=True, exist_ok=True)
    (synth_dir / "final-report.md").write_text(
        "# Final Report — MiniMax multi-wave research\n\n"
        f"_Generated {datetime.now(timezone.utc).isoformat()} · model `{minimax_model()}`_\n\n"
        + text
        + "\n"
    )


def _bootstrap_session(slug: str, question: str) -> Path:
    init = REPO_ROOT / "services/skills/goose-autoresearch/scripts/init_session.py"
    proc = subprocess.run(
        [sys.executable, str(init), "--slug", slug, "--question", question],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr or proc.stdout or "init_session failed")
    path = Path(proc.stdout.strip().splitlines()[-1].strip())
    if not path.is_dir():
        raise SystemExit(f"Unexpected init_session output: {proc.stdout!r}")
    return path


def main() -> None:
    _load_repo_dotenv(REPO_ROOT)
    parser = argparse.ArgumentParser(description="Multi-wave MiniMax autoresearch (OpenAI or Anthropic-compatible API).")
    parser.add_argument("--session-dir", type=Path, help="Existing session directory (see init_session.py)")
    parser.add_argument("--slug", help="With --question, bootstrap a new session first")
    parser.add_argument("--question", help="With --slug, bootstrap a new session first")
    args = parser.parse_args()

    if args.session_dir:
        session_dir = args.session_dir.resolve()
    elif args.slug and args.question:
        session_dir = _bootstrap_session(args.slug, args.question)
        print(session_dir, file=sys.stderr)
    else:
        parser.error("Provide --session-dir OR both --slug and --question")

    question = _load_question(session_dir)
    print(
        f"MiniMax route: {minimax_route_label()} · model: {minimax_model()} · "
        f"timeout: {research_chat_timeout_seconds()}s (wave3: {_wave3_timeout_seconds()}s)",
        file=sys.stderr,
    )
    print("Wave 1 (4 workers)…", file=sys.stderr)
    run_wave1(session_dir, question)
    print("Wave 2 (lead merge)…", file=sys.stderr)
    run_wave2_lead(session_dir, question)
    print("Wave 3 (final report)…", file=sys.stderr)
    run_wave3_synthesis(session_dir, question)

    manifest_path = session_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        manifest["status"] = "minimax_multiwave_complete"
        manifest["minimax_model"] = minimax_model()
        manifest["minimax_route"] = minimax_route_label()
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print(str(session_dir / "synthesis" / "final-report.md"))


if __name__ == "__main__":
    main()
