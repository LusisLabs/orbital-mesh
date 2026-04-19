from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.config import RuntimeConfig
from shared.mesh_runtime.integrations import resolve_integrations_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap a Goose autoresearch session workspace.")
    parser.add_argument("--slug", required=True, help="Short human-readable session name")
    parser.add_argument("--question", required=True, help="Primary research question")
    parser.add_argument("--owner", default="cursor", help="Session owner label")
    parser.add_argument("--output-root", help="Optional output root; defaults to .mesh-runtime-state/research")
    parser.add_argument("--dry-run", action="store_true", help="Print the resolved scaffold without writing files")
    args = parser.parse_args()

    runtime_config = RuntimeConfig.from_env()
    output_root = (
        Path(args.output_root)
        if args.output_root
        else Path(runtime_config.state_directory) / "research"
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = _slugify(args.slug)
    session_dir = output_root / f"{timestamp}-{slug}"
    goose_profile = _resolved_goose_profile(runtime_config)

    manifest = {
        "session_id": session_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "owner": args.owner,
        "question": args.question,
        "status": "bootstrapped",
        "topology": {
            "lead": "lead",
            "workers": [
                {"id": "worker-01", "role": "baseline"},
                {"id": "worker-02", "role": "skeptic"},
                {"id": "worker-03", "role": "deep-dive"},
                {"id": "worker-04", "role": "editor"},
            ],
        },
        "rubric": ["correctness", "evidence_quality", "novelty", "actionability", "repo_reality"],
        "paths": {
            "session_dir": str(session_dir),
            "prompts_dir": str(session_dir / "prompts"),
            "results_dir": str(session_dir / "results"),
            "notes_dir": str(session_dir / "notes"),
            "synthesis_dir": str(session_dir / "synthesis"),
        },
        "goose": goose_profile,
    }

    files = {
        "README.md": _readme_content(manifest),
        "manifest.json": json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        "prompts/lead.md": _lead_prompt(args.question),
        "prompts/worker-template.md": _worker_template(args.question),
        "prompts/synthesis-template.md": _synthesis_template(),
        "results/scorecard.md": _scorecard_template(),
        "notes/operator-notes.md": "# Operator Notes\n\n- Session created.\n",
        "synthesis/final-report.md": "# Final Report\n\n## Executive Summary\n\nPending.\n",
    }

    if args.dry_run:
        print(json.dumps({"session_dir": str(session_dir), "manifest": manifest, "files": sorted(files)}, indent=2))
        return

    for relative_path, content in files.items():
        destination = session_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)

    print(session_dir)


def _resolved_goose_profile(runtime_config: RuntimeConfig) -> dict[str, Any]:
    resolved = resolve_integrations_config(runtime_config)
    command = resolved.goose_command
    if not command:
        return {
            "resolved_command": None,
            "goose_bin": None,
            "provider": None,
            "model": None,
            "fallback_provider": None,
            "fallback_model": None,
            "ready_hint": "Goose command is not configured. Run python3 setup_integrations.py first.",
        }

    tokens = shlex.split(command)
    goose_bin = _flag_value(tokens, "--goose-bin")
    provider = _flag_value(tokens, "--provider")
    model = _flag_value(tokens, "--model")
    fallback_provider = _flag_value(tokens, "--fallback-provider")
    fallback_model = _flag_value(tokens, "--fallback-model")
    direct_command = [goose_bin] if goose_bin else tokens[:1]
    if provider or model:
        direct_command.append("--no-profile")
    if provider:
        direct_command.extend(["--provider", provider])
    if model:
        direct_command.extend(["--model", model])

    return {
        "resolved_command": command,
        "goose_bin": goose_bin,
        "provider": provider,
        "model": model,
        "fallback_provider": fallback_provider,
        "fallback_model": fallback_model,
        "direct_command": shlex.join(direct_command) if direct_command else None,
    }


def _flag_value(tokens: list[str], flag: str) -> str | None:
    try:
        index = tokens.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(tokens):
        return None
    return tokens[index + 1]


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "research-session"


def _readme_content(manifest: dict[str, Any]) -> str:
    question = manifest["question"]
    direct_command = manifest["goose"].get("direct_command") or "unavailable"
    return (
        f"# {manifest['session_id']}\n\n"
        f"- Question: {question}\n"
        f"- Owner: `{manifest['owner']}`\n"
        f"- Direct Goose Command: `{direct_command}`\n\n"
        "## Workflow\n\n"
        "1. Refine the brief in `prompts/lead.md`.\n"
        "2. Run the first worker wave and save each output into `results/`.\n"
        "3. Fill in `results/scorecard.md`.\n"
        "4. Run another wave only for unresolved gaps.\n"
        "5. Publish the converged answer in `synthesis/final-report.md`.\n"
    )


def _lead_prompt(question: str) -> str:
    return f"""# Lead Brief

## Research Question
{question}

## Why This Matters
[fill in operator or product context]

## Scope
- Include:
- Exclude:

## Success Rubric
- Correctness
- Evidence quality
- Novelty
- Actionability
- Repo reality

## Worker Plan
- worker-01 baseline:
- worker-02 skeptic:
- worker-03 deep-dive:
- worker-04 editor:
"""


def _worker_template(question: str) -> str:
    return f"""You are `worker-[id]` in a clustered Goose autoresearch session.

Role: [baseline | skeptic | deep-dive | editor]
Goal: [specific sub-question]

Session question:
{question}

Required behavior:
- Stay focused on this worker role.
- Prefer concrete evidence over broad claims.
- Surface uncertainty explicitly.
- End with a compact verdict and next checks.

Return using this structure:
## Summary
## Key Evidence
## Risks / Uncertainty
## Recommendation
## Follow-up Questions
"""


def _synthesis_template() -> str:
    return """You are the lead synthesizer for a clustered Goose autoresearch session.

Your job:
- compare worker outputs
- resolve direct contradictions when evidence is sufficient
- preserve disagreement when evidence is insufficient
- recommend the clearest next action

Return using this structure:
# Final Report

## Executive Summary
## Strongest Findings
## Conflicts And Unknowns
## Recommended Next Action
## Appendix: Winning Evidence
"""


def _scorecard_template() -> str:
    return """# Scorecard

| Worker | Correctness | Evidence | Novelty | Actionability | Repo Reality | Notes |
|---|---:|---:|---:|---:|---:|---|
| worker-01 |  |  |  |  |  |  |
| worker-02 |  |  |  |  |  |  |
| worker-03 |  |  |  |  |  |  |
| worker-04 |  |  |  |  |  |  |

## Convergence
- Consensus:
- Disagreements:
- Missing evidence:
- Decision on next wave:
"""


if __name__ == "__main__":
    main()
