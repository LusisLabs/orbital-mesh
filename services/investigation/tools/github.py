"""GitHub read-only domain pack for the investigation harness.

Four tools, all read-only, all backed by ``gh api`` (the GitHub CLI's
authenticated REST passthrough):

* ``github_recent_commits`` — last N commits on a branch.
* ``github_file_contents`` — read a file at a ref.
* ``github_search_code`` — search code in a repo.
* ``github_pr_diff`` — diff of a specific PR.

Why ``gh`` and not the GitHub Python SDK:

* ``gh`` is already used in this repo (see ``services/actuators/
  argocd.py`` and the docs). Adding ``PyGithub`` as a hard dep
  duplicates auth handling.
* ``gh auth status`` is the universal contract for "do I have
  GitHub access right now"; subprocessing ``gh api`` inherits that
  auth without us touching tokens.
* The same shape used by the AWS pack (single tool that proxies a
  read-only verb) doesn't fit GitHub well — the four resources we
  care about have very different post-processing needs (diffs are
  text, contents are base64, search is JSON). Per-tool wrappers are
  honest here.

Read-only enforcement:

* The critic blocks anything not classified ``read_only``.
* Each tool builds an explicit ``gh api -X GET ...`` argv. There is
  no "exec arbitrary gh command" surface; user args feed only into
  resource paths and query params.
* The ``-X GET`` is explicit so the critic can't be tricked by
  an upstream argv mutation.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

from ..harness import (
    RawToolOutput,
    ToolDefinition,
    ToolRegistry,
)


DOMAIN = "github"
MAX_OUTPUT_BYTES = 96 * 1024


def _build_definitions() -> list[ToolDefinition]:
    repo_args = {"repo": {"type": "str", "required": True}}
    schemas = {
        "github_recent_commits": {
            **repo_args,
            "branch": {"type": "str", "required": False, "nullable": True},
            "limit": {"type": "int", "required": False},
        },
        "github_file_contents": {
            **repo_args,
            "path": {"type": "str", "required": True},
            "ref": {"type": "str", "required": False, "nullable": True},
        },
        "github_search_code": {
            **repo_args,
            "query": {"type": "str", "required": True},
            "limit": {"type": "int", "required": False},
        },
        "github_pr_diff": {
            **repo_args,
            "pr_number": {"type": "int", "required": True},
        },
    }
    descriptions = {
        "github_recent_commits": "List recent commits on a branch (defaults to repo's default branch).",
        "github_file_contents": "Read a file at a given ref (defaults to the default branch).",
        "github_search_code": "Search code within a repo via the GitHub code search API.",
        "github_pr_diff": "Read the unified diff for a pull request by number.",
    }
    return [
        ToolDefinition(
            name=name,
            domain=DOMAIN,
            description=description,
            args_schema=dict(schemas[name]),
            mutation_class="read_only",
            timeout_seconds=15.0,
            budget_cost=1.5,
            citations_kind="github_api",
        )
        for name, description in descriptions.items()
    ]


TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(_build_definitions())


_NO_GH_PATH_PROVIDED = object()


def register(
    registry: ToolRegistry,
    *,
    gh_path: str | None = _NO_GH_PATH_PROVIDED,  # type: ignore[assignment]
) -> None:
    """Register the four GitHub read tools."""
    if gh_path is _NO_GH_PATH_PROVIDED:
        resolved = shutil.which("gh")
    else:
        resolved = gh_path or None
    for definition in TOOL_DEFINITIONS:
        registry.register(definition, _make_github_invoker(definition.name, resolved))


def _make_github_invoker(tool_name: str, gh_path: str | None):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        if not gh_path:
            return _failure(tool_name, "gh CLI binary not found in PATH")
        argv, accept_text = _build_argv(tool_name, args)
        if argv is None:
            return _failure(tool_name, "could not build gh argv (missing required args)")
        try:
            result = subprocess.run(
                [gh_path, *argv],
                capture_output=True,
                text=True,
                timeout=15.0,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _failure(tool_name, "gh timed out after 15s")
        except OSError as exc:
            return _failure(tool_name, f"gh exec error: {exc}")
        stdout = (result.stdout or "")[:MAX_OUTPUT_BYTES]
        stderr = (result.stderr or "")[:1024]
        if result.returncode != 0:
            return _failure(tool_name, stderr.strip() or f"gh exited {result.returncode}", argv=argv)
        parsed: Any = None
        if not accept_text:
            try:
                parsed = json.loads(stdout) if stdout.strip() else None
            except json.JSONDecodeError:
                parsed = None
        output: dict[str, Any] = {"argv": list(argv)}
        if accept_text:
            output["text"] = stdout
        else:
            output["json"] = parsed
            output["raw"] = stdout if parsed is None else None
        return RawToolOutput(
            output=output,
            output_summary=f"gh {' '.join(argv)} -> {stdout[:400]}",
            citations=[{"source_type": "github_api", "source_ref": " ".join(argv)}],
            valid=bool(stdout),
            redaction_status="clean",
            status="completed",
        )

    return invoke


def _build_argv(tool_name: str, args: dict[str, Any]) -> tuple[list[str] | None, bool]:
    """Return (argv_after_gh, accept_text_output).

    ``accept_text_output`` is True when the GitHub API returns plain
    text rather than JSON (PR diffs use ``Accept: application/vnd.github.diff``).
    """
    repo = str(args.get("repo") or "").strip()
    if not repo or "/" not in repo:
        return None, False

    if tool_name == "github_recent_commits":
        limit = int(args.get("limit") or 20)
        branch = args.get("branch")
        path = f"repos/{repo}/commits"
        params = [f"per_page={max(1, min(limit, 100))}"]
        if branch:
            params.append(f"sha={branch}")
        return ["api", "-X", "GET", f"{path}?{'&'.join(params)}"], False

    if tool_name == "github_file_contents":
        path = str(args.get("path") or "").lstrip("/")
        if not path:
            return None, False
        ref = args.get("ref")
        api_path = f"repos/{repo}/contents/{path}"
        if ref:
            api_path = f"{api_path}?ref={ref}"
        return ["api", "-X", "GET", api_path], False

    if tool_name == "github_search_code":
        query = str(args.get("query") or "").strip()
        if not query:
            return None, False
        limit = int(args.get("limit") or 20)
        # Encode "+repo:foo/bar" into the q parameter
        import urllib.parse

        q = urllib.parse.quote(f"{query} repo:{repo}", safe="")
        return ["api", "-X", "GET", f"search/code?q={q}&per_page={max(1, min(limit, 100))}"], False

    if tool_name == "github_pr_diff":
        pr_number = int(args.get("pr_number") or 0)
        if pr_number <= 0:
            return None, False
        return [
            "api",
            "-X",
            "GET",
            "-H",
            "Accept: application/vnd.github.diff",
            f"repos/{repo}/pulls/{pr_number}",
        ], True

    return None, False


def _failure(tool_name: str, message: str, *, argv: list[str] | None = None) -> RawToolOutput:
    return RawToolOutput(
        output={"argv": argv or [], "error": message},
        output_summary=f"{tool_name} failed: {message[:400]}",
        citations=[{"source_type": "github_api", "source_ref": tool_name}],
        valid=False,
        redaction_status="clean",
        status="failed",
        error=message,
    )


def maybe_register_at_root(registry: ToolRegistry) -> bool:
    """Register GitHub tools iff ``gh`` is on PATH and authenticated."""
    if shutil.which("gh") is None:
        return False
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    if result.returncode != 0:
        # Not authenticated. Don't fail engine startup; just skip.
        return False
    register(registry)
    return True
