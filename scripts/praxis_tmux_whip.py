#!/usr/bin/env python3
"""Create tmux-backed Praxis milestone runs.

The launcher creates a durable run directory with:
- manifest.json
- automator-prompt.md
- milestone.md copied from the canonical milestone template
- run.sh for tmux

The automator updates milestone.md after each concrete action. The helper also
has a small `mark` subcommand so agents can update a burndown row and append a
work-log entry without hand-editing the Markdown table.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = REPO_ROOT / "docs/plans/praxis-agent-tool-mesh-overnight-plan.html"
DEFAULT_MILESTONE = REPO_ROOT / "docs/plans/praxis-agent-tool-mesh-overnight-milestone.md"
DEFAULT_RUN_ROOT = REPO_ROOT / ".mesh-runtime-state/praxis-tmux-whip"
STATE_SLICE = "praxis-tmux-whip-milestone-automation"
VALID_STATUSES = {"pending", "in_progress", "blocked", "done", "deferred"}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def require_file(path: Path, label: str) -> None:
    if not path.exists() or not path.is_file():
        raise SystemExit(f"{label} not found: {path}")


def reject_tail_command(command: str | None) -> None:
    if not command:
        return
    try:
        words = shlex.split(command)
    except ValueError as exc:
        raise SystemExit(f"invalid command quoting: {exc}") from exc
    if any(word == "tail" or word.endswith("/tail") for word in words):
        raise SystemExit("refusing command: repo policy says do not run tail")


def render_prompt(*, run_dir: Path, html_path: Path, milestone_path: Path) -> str:
    return f"""# Praxis tmux whip automator prompt

State slice: `{STATE_SLICE}`

You are operating inside a durable tmux run. Your source of truth is:

- HTML plan: `{html_path}`
- Active milestone: `{milestone_path}`
- Run directory: `{run_dir}`

## Non-negotiable rules

- Read the HTML plan and active milestone before editing code.
- Plan first, act after. Keep a short task list in the active milestone.
- Measure twice, cut once policy.
- Every mutation must name the state slice it touches.
- Use `pnpm`, not `npm`.
- Do not run `tail`.
- Do not use no-mistakes.
- Keep the codebase clean: no tmp files, no dead code, no dead files, no unnecessary folders.
- Preserve unrelated dirty worktree changes.
- Do not stage, commit, push, or open PRs unless explicitly instructed by the human.
- Akto evidence is advisory/security evidence. It cannot grant production authority.
- ACP is a supervised session surface. It cannot grant runtime authority.
- Mesh owns policy, connector certification, approval, audit, bounded execution, and revocation.

## Update rule

After every concrete action, update `{milestone_path}`:

1. mark the active P item with `scripts/praxis_tmux_whip.py mark`;
2. append a Work Log entry naming command/action, result, validation, and next step;
3. record blockers immediately instead of hiding them.

Example:

```bash
python3 scripts/praxis_tmux_whip.py mark --milestone "{milestone_path}" --item P1 --status in_progress --note "Started schema contract pass for praxis.contracts.v1"
```

## Repeated error rule

When the same error appears twice:

1. Stop editing.
2. Record the exact command and error in Work Log.
3. Research 3-5 plausible fixes.
4. Choose the smallest fix consistent with Mesh authority boundaries.
5. Implement one fix and re-run the narrowest trustworthy validation.

## Initial target order

P0 -> P1 -> P2 -> P3 -> P4 -> P5 -> P8.

Do not work on managed hosting, marketplace, or pilot runtime until the proof packet path exists.
"""


def render_runner(run_dir: Path, prompt_path: Path, html_path: Path, milestone_path: Path) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail

cd {shlex.quote(str(REPO_ROOT))}
export PRAXIS_WHIP_RUN_DIR={shlex.quote(str(run_dir))}
export PRAXIS_WHIP_PROMPT={shlex.quote(str(prompt_path))}
export PRAXIS_WHIP_HTML={shlex.quote(str(html_path))}
export PRAXIS_WHIP_MILESTONE={shlex.quote(str(milestone_path))}

printf '%s\\n' 'Praxis tmux whip ready.'
printf '%s\\n' "Run dir: $PRAXIS_WHIP_RUN_DIR"
printf '%s\\n' "Prompt: $PRAXIS_WHIP_PROMPT"
printf '%s\\n' "HTML: $PRAXIS_WHIP_HTML"
printf '%s\\n' "Milestone: $PRAXIS_WHIP_MILESTONE"
printf '%s\\n' ''
printf '%s\\n' 'If PRAXIS_WHIP_COMMAND is set, executing it now. Otherwise opening an interactive shell.'

if [[ -n "${{PRAXIS_WHIP_COMMAND:-}}" ]]; then
  exec bash -lc "$PRAXIS_WHIP_COMMAND"
fi

exec "${{SHELL:-/bin/zsh}}" -l
"""


def build_run(args: argparse.Namespace, *, write: bool) -> dict[str, object]:
    html_path = Path(args.html).expanduser().resolve()
    canonical_milestone = Path(args.milestone).expanduser().resolve()
    run_root = Path(args.run_root).expanduser().resolve()
    session = args.session or f"praxis-whip-{utc_stamp()}"
    run_dir = run_root / session
    active_milestone = run_dir / "milestone.md"
    prompt_path = run_dir / "automator-prompt.md"
    runner_path = run_dir / "run.sh"
    manifest_path = run_dir / "manifest.json"

    require_file(html_path, "HTML plan")
    require_file(canonical_milestone, "Markdown milestone")
    command = args.command if args.command is not None else os.environ.get("PRAXIS_WHIP_COMMAND")
    reject_tail_command(command)

    manifest: dict[str, object] = {
        "schema_version": "praxis.tmux_whip_run.v1",
        "state_slice": STATE_SLICE,
        "status": "initialized",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session": session,
        "repo_root": str(REPO_ROOT),
        "run_dir": str(run_dir),
        "html_plan": str(html_path),
        "canonical_milestone": str(canonical_milestone),
        "active_milestone": str(active_milestone),
        "prompt": str(prompt_path),
        "runner": str(runner_path),
        "command": command or None,
        "heavy_gate": "pnpm run lint",
        "fast_gates": [
            "pnpm run lint:fast",
            "pnpm run verify:contracts",
            "pnpm run test:focused",
            "pnpm run verify:full",
        ],
        "rules": [
            "plan first, act after",
            "measure twice, cut once",
            "pnpm not npm",
            "do not run tail",
            "update active milestone after every concrete action",
            "Mesh owns policy/certification/approval/audit/actuation/revocation",
        ],
    }

    if write:
        run_dir.mkdir(parents=True, exist_ok=False)
        shutil.copyfile(canonical_milestone, active_milestone)
        prompt_path.write_text(
            render_prompt(run_dir=run_dir, html_path=html_path, milestone_path=active_milestone),
            encoding="utf-8",
        )
        runner_path.write_text(
            render_runner(run_dir, prompt_path, html_path, active_milestone),
            encoding="utf-8",
        )
        runner_path.chmod(0o755)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return manifest


def cmd_init(args: argparse.Namespace) -> int:
    manifest = build_run(args, write=not args.dry_run)
    if args.dry_run:
        manifest["status"] = "dry_run"
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def cmd_launch(args: argparse.Namespace) -> int:
    manifest = build_run(args, write=not args.dry_run)
    if args.dry_run:
        manifest["status"] = "dry_run"
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0

    session = str(manifest["session"])
    runner = str(manifest["runner"])
    if shutil.which("tmux") is None:
        raise SystemExit("tmux not found")

    env = os.environ.copy()
    command = manifest.get("command")
    tmux_cmd = ["tmux", "new-session", "-d", "-s", session]
    if isinstance(command, str) and command:
        env["PRAXIS_WHIP_COMMAND"] = command
        tmux_cmd.extend(["-e", f"PRAXIS_WHIP_COMMAND={command}"])
    tmux_cmd.append(runner)
    subprocess.run(tmux_cmd, check=True, env=env)
    manifest["status"] = "launched"
    manifest["tmux_attach"] = f"tmux attach -t {session}"
    Path(str(manifest["run_dir"]), "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def cmd_mark(args: argparse.Namespace) -> int:
    milestone = Path(args.milestone).expanduser().resolve()
    require_file(milestone, "milestone")
    if args.status not in VALID_STATUSES:
        raise SystemExit(f"invalid status {args.status!r}; expected one of {sorted(VALID_STATUSES)}")

    lines = milestone.read_text(encoding="utf-8").splitlines()
    item = args.item.upper()
    changed = False
    output: list[str] = []
    for line in lines:
        if line.startswith(f"| {item} |"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 6:
                raise SystemExit(f"cannot update malformed row for {item}")
            cells[1] = args.status
            line = "| " + " | ".join(cells) + " |"
            changed = True
        output.append(line)

    if not changed:
        raise SystemExit(f"burndown item not found: {item}")

    timestamp = datetime.now(timezone.utc).isoformat()
    note = args.note.strip()
    entry = f"- {timestamp} `{item}` -> `{args.status}`: {note}"
    marker = "<!-- worklog -->"
    try:
        marker_index = output.index(marker)
    except ValueError:
        output.extend(["", "## Work Log", "", marker, ""])
        marker_index = output.index(marker)
    output.insert(marker_index + 1, entry)

    milestone.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    print(json.dumps({"status": "updated", "milestone": str(milestone), "item": item, "new_status": args.status}))
    return 0


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--html", default=str(DEFAULT_HTML), help="HTML plan path")
    parser.add_argument("--milestone", default=str(DEFAULT_MILESTONE), help="Markdown milestone template path")
    parser.add_argument("--run-root", default=str(DEFAULT_RUN_ROOT), help="Run root directory")
    parser.add_argument("--session", default=None, help="tmux session and run directory name")
    parser.add_argument("--command", default=None, help="Optional automator command executed inside tmux")
    parser.add_argument("--dry-run", action="store_true", help="Print manifest without writing files or launching tmux")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    init_parser = subparsers.add_parser("init", help="Create a run directory without launching tmux")
    add_common_args(init_parser)
    init_parser.set_defaults(func=cmd_init)

    launch_parser = subparsers.add_parser("launch", help="Create a run directory and launch tmux")
    add_common_args(launch_parser)
    launch_parser.set_defaults(func=cmd_launch)

    mark_parser = subparsers.add_parser("mark", help="Update one burndown row and append a work-log entry")
    mark_parser.add_argument("--milestone", required=True, help="Active run-local milestone.md path")
    mark_parser.add_argument("--item", required=True, help="Burndown id, for example P1")
    mark_parser.add_argument("--status", required=True, help=f"New status: {', '.join(sorted(VALID_STATUSES))}")
    mark_parser.add_argument("--note", required=True, help="Work-log note")
    mark_parser.set_defaults(func=cmd_mark)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
