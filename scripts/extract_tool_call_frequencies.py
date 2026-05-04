#!/usr/bin/env python3
"""Tally Bash + MCP tool calls across recent Claude Code transcripts.

Used to refresh the project's permission allowlist (see
``/fewer-permission-prompts``). Reading the most-recent N JSONL session
transcripts under ``~/.claude/projects/`` gives an empirical picture of
which read-only commands you actually run, so you can prune permission
prompts that block common workflows.

The script intentionally does NOT decide what is read-only — that
classification belongs in the skill (and in Claude Code's built-in
``COMMAND_ALLOWLIST``). It just produces frequency counts, leaving the
human to pick patterns and merge them into ``.claude/settings.json``.

Usage::

    python3 -m scripts.extract_tool_call_frequencies                # default: top 80 bash, 40 MCP
    python3 -m scripts.extract_tool_call_frequencies --sessions 100 # widen the scan
    python3 -m scripts.extract_tool_call_frequencies --json         # machine-readable output

Output is JSON to stdout: ``{"bash": [(key, count), ...], "mcp": [...]}``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


# Commands whose first arg names a sub-command worth keeping in the
# tally key (so ``git status`` and ``git push`` count separately). Other
# commands collapse to just the head token.
_MULTI_ARG_COMMANDS: frozenset[str] = frozenset({
    "git", "gh", "docker", "kubectl", "helm", "npm", "yarn", "pnpm", "bun",
    "uv", "uvx", "cargo", "go", "make", "just", "claude", "brew", "rustup",
    "rg", "fd", "fdfind", "terraform", "aws", "gcloud", "psql", "mysql",
    "redis-cli", "tsc", "pyright", "ruff", "mypy", "pytest", "jest",
    "vitest", "kustomize", "cast", "forge", "anvil",
})

# Wrappers that prefix the real command and should be peeled off before
# tallying so ``sudo apt install`` keys as ``apt install``.
_WRAPPERS: frozenset[str] = frozenset({"sudo", "timeout", "time", "nohup", "exec", "command"})

_ENV_PREFIX_RE = re.compile(r"^([A-Z_][A-Z0-9_]*=\S+\s+)+")


def _canonical_bash_key(command: str) -> str | None:
    """Return ``"head"`` or ``"head subcmd"`` from a shell command line.

    Strips env-var prefixes (``DEBUG=1 git status``), unwraps ``sudo``,
    splits on the first ``|``/``&&``/``||``/``;`` so we tally the lead
    command in compound pipelines, and normalizes path-prefixed binaries
    (``/usr/bin/python3`` → ``python3``).
    """

    if not command:
        return None
    text = command.strip()
    if not text:
        return None
    for separator in ("&&", "||", "|", ";"):
        if separator in text:
            text = text.split(separator, 1)[0].strip()
    text = _ENV_PREFIX_RE.sub("", text)
    parts = text.split()
    while parts and parts[0] in _WRAPPERS:
        parts.pop(0)
    if not parts:
        return None
    head = parts[0].strip("()`")
    if "/" in head and not head.startswith("./"):
        head = head.rsplit("/", 1)[-1]
    if head in _MULTI_ARG_COMMANDS and len(parts) >= 2 and not parts[1].startswith("-"):
        return f"{head} {parts[1]}"
    return head


def _extract_calls(transcript: Path) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    try:
        handle = transcript.open(encoding="utf-8")
    except OSError:
        return calls
    with handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (obj.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for entry in content:
                if not isinstance(entry, dict) or entry.get("type") != "tool_use":
                    continue
                name = entry.get("name") or ""
                inp = entry.get("input") or {}
                if name == "Bash":
                    key = _canonical_bash_key(inp.get("command", ""))
                    if key:
                        calls.append(("bash", key))
                elif isinstance(name, str) and name.startswith("mcp__"):
                    calls.append(("mcp", name))
    return calls


def _recent_transcripts(projects_root: Path, limit: int) -> list[Path]:
    if not projects_root.exists():
        return []
    transcripts = list(projects_root.rglob("*.jsonl"))
    transcripts.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return transcripts[:limit]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--projects-root",
        default=str(Path.home() / ".claude" / "projects"),
        help="Root directory containing per-project transcript folders.",
    )
    parser.add_argument(
        "--sessions",
        type=int,
        default=50,
        help="Scan the N most-recently-modified .jsonl transcripts. Default: 50.",
    )
    parser.add_argument(
        "--bash-top",
        type=int,
        default=80,
        help="Number of Bash tally rows to emit. Default: 80.",
    )
    parser.add_argument(
        "--mcp-top",
        type=int,
        default=40,
        help="Number of MCP tally rows to emit. Default: 40.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON (default). Reserved for future text mode.",
    )
    args = parser.parse_args(argv)

    transcripts = _recent_transcripts(Path(args.projects_root), args.sessions)
    bash_counter: Counter[str] = Counter()
    mcp_counter: Counter[str] = Counter()
    for transcript in transcripts:
        for kind, key in _extract_calls(transcript):
            if kind == "bash":
                bash_counter[key] += 1
            else:
                mcp_counter[key] += 1

    output = {
        "scanned_transcript_count": len(transcripts),
        "bash": bash_counter.most_common(args.bash_top),
        "mcp": mcp_counter.most_common(args.mcp_top),
    }
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
