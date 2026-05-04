from __future__ import annotations

import difflib
import importlib
import json
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any

try:
    from langchain.chat_models import init_chat_model
except ImportError:  # pragma: no cover - optional dependency for deepagents fabric
    def init_chat_model(*args: Any, **kwargs: Any) -> Any:
        raise ImportError("langchain is not installed")

try:
    from langchain_core.messages import HumanMessage
except ImportError:  # pragma: no cover - optional dependency for deepagents fabric
    class HumanMessage:  # type: ignore[override]
        def __init__(self, *, content: str):
            self.content = content

from shared.mesh_runtime import Decision, EvaluationResult, RuntimeConfig, Trigger
from shared.mesh_runtime.agent_workers import build_agent_attempt
from shared.mesh_runtime.control_plane_models import AgentAttempt, AgentTask


_LANE_SYSTEM_PROMPTS: dict[str, str] = {
    "goose": (
        "You are the Goose operational coordination lane for Mesh Intelligence. "
        "Coordinate investigation using subagents; never propose direct Kubernetes or production changes."
    ),
    "hermes": (
        "You are the Hermes root-cause lane. Prioritize evidence-backed hypotheses; delegate analysis to subagents."
    ),
    "codex": (
        "You are the Codex patch-proposal lane. Propose minimal, testable edits only inside the sandbox workspace; "
        "never touch the real repository or production."
    ),
    "claudecode": (
        "You are the Claude Code review lane. Focus on blast radius, rollback, and test gaps."
    ),
    "openclaw": (
        "You are the OpenClaw staging-validation lane. Validate scope against the provided kubernetes_scope only; "
        "never execute kubectl or cluster commands."
    ),
    "evo": (
        "You are the Evo benchmark-advisory lane. Advise on bounded discovery/benchmark readiness; "
        "never run evo optimize/init/new/run or git worktrees from this task."
    ),
}


def _mesh_subagent_specs(*, include_rollback: bool) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = [
        {
            "name": "root-cause-analyst",
            "description": "Investigates symptoms, logs, and hypotheses for the incident context.",
            "system_prompt": (
                "Analyze the Mesh task context and produce concise root-cause findings. "
                "Use read-only reasoning; cite only facts present in the context JSON."
            ),
        },
        {
            "name": "patch-proposer",
            "description": "Drafts code or config patches inside the sandbox workspace when allowed paths exist.",
            "system_prompt": (
                "If files exist in the workspace, read them and propose concrete edits using filesystem tools. "
                "Stay within workspace paths that mirror allowed_paths from the task context."
            ),
        },
        {
            "name": "reviewer",
            "description": "Reviews proposals for safety, rollback, and missing tests.",
            "system_prompt": "Review for production safety, rollback clarity, and test coverage gaps.",
        },
        {
            "name": "staging-validator",
            "description": "Checks staging/Kubernetes scope consistency without executing cluster commands.",
            "system_prompt": (
                "Validate that kubernetes_scope fields are coherent for a staging check. "
                "Do not invoke kubectl or any live cluster tooling."
            ),
        },
        {
            "name": "rollback-planner",
            "description": "Outlines rollback steps consistent with Mesh policy (no live actuation).",
            "system_prompt": (
                "Propose rollback steps as narrative checks only. Mesh owns Kubernetes actuation; do not run commands."
            ),
        },
        {
            "name": "evo-benchmark-advisor",
            "description": "Advises on Evo discovery/benchmark gates for code-remediation tasks.",
            "system_prompt": (
                "Advise whether Evo-style benchmarking is appropriate given allowed_paths and test_commands. "
                "Never instruct running evo CLI optimization commands."
            ),
        },
    ]
    if not include_rollback:
        specs = [s for s in specs if s["name"] != "rollback-planner"]
    return specs


def _normalize_rel(path: str) -> str:
    return str(Path(path).as_posix()).lstrip("./")


def _repo_root(trigger: Trigger, decision: Decision) -> Path | None:
    related = trigger.related_context if isinstance(trigger.related_context, dict) else {}
    parameters = decision.execution_plan.get("parameters", {}) if isinstance(decision.execution_plan, dict) else {}
    raw = parameters.get("repo_path") or related.get("repo_path") or ""
    if not raw:
        return None
    root = Path(str(raw)).expanduser().resolve()
    return root if root.is_dir() else None


def _copy_allowed_workspace(
    *,
    repo_root: Path | None,
    allowed_paths: list[str],
    workspace: Path,
) -> dict[str, str]:
    """Copy allowed files into workspace; return relative path -> original text snapshot."""
    snapshot: dict[str, str] = {}
    workspace.mkdir(parents=True, exist_ok=True)
    if repo_root is None or not allowed_paths:
        return snapshot
    repo_root = repo_root.resolve()
    for raw in allowed_paths:
        rel = _normalize_rel(raw)
        if not rel or rel.startswith(".."):
            continue
        src = (repo_root / rel).resolve()
        try:
            src.relative_to(repo_root)
        except ValueError:
            continue
        if not src.is_file():
            continue
        dest = (workspace / rel).resolve()
        try:
            dest.relative_to(workspace.resolve())
        except ValueError:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        snapshot[rel] = src.read_text(encoding="utf-8", errors="replace")
    return snapshot


def _diff_against_snapshot(snapshot: dict[str, str], workspace: Path) -> tuple[str, list[str]]:
    changed: list[str] = []
    chunks: list[str] = []
    for rel, before in sorted(snapshot.items()):
        after_path = workspace / rel
        after = (
            after_path.read_text(encoding="utf-8", errors="replace")
            if after_path.is_file()
            else ""
        )
        if after != before:
            changed.append(rel)
            diff_lines = difflib.unified_diff(
                before.splitlines(),
                after.splitlines(),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                lineterm="",
            )
            chunks.append("\n".join(diff_lines))
    return "\n\n".join(chunks).strip(), changed


def _disallowed_workspace_files(task: AgentTask, workspace: Path) -> list[str]:
    """Flag files in the workspace that are outside the task allowlist (patch-style gates)."""
    if not task.allowed_paths:
        return []
    allowed = {_normalize_rel(p) for p in task.allowed_paths}
    bad: list[str] = []
    root = workspace.resolve()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if _normalize_rel(rel) not in allowed:
            bad.append(rel)
    return bad


def _bounded_task_context(
    *,
    task: AgentTask,
    trigger: Trigger,
    decision: Decision,
    evaluation: EvaluationResult,
    max_chars: int,
) -> dict[str, Any]:
    return {
        "run_id": task.run_id,
        "task_id": task.task_id,
        "task_kind": task.kind,
        "allowed_paths": task.allowed_paths,
        "test_commands": task.test_commands,
        "kubernetes_scope": task.kubernetes_scope,
        "memory_scope": task.memory_scope,
        "memory_packet": _compact_jsonish(task.memory_packet, max_chars=max_chars),
        "memory_write_policy": task.memory_write_policy,
        "open_questions": task.open_questions,
        "trigger": {
            "trigger_type": trigger.trigger_type,
            "related_context": _compact_jsonish(trigger.related_context, max_chars=max_chars),
        },
        "decision": {
            "summary": decision.summary,
            "decision_type": decision.decision_type,
            "execution_plan": _compact_jsonish(decision.execution_plan, max_chars=max_chars),
        },
        "evaluation": {
            "passed": evaluation.passed,
            "final_recommendation": evaluation.final_recommendation,
            "blocking_reasons": evaluation.blocking_reasons,
        },
    }


def _compact_jsonish(value: Any, *, max_chars: int) -> Any:
    if max_chars <= 0:
        return value
    raw = json.dumps(value, default=str, sort_keys=True)
    if len(raw) <= max_chars:
        return value
    return {
        "truncated": True,
        "original_chars": len(raw),
        "excerpt": raw[:max_chars],
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    cursor = 0
    while True:
        start = text.find("{", cursor)
        if start < 0:
            return None
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        if isinstance(parsed, dict):
                            return parsed
                    except json.JSONDecodeError:
                        pass
                    cursor = start + 1
                    break
        else:
            return None


def _final_ai_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        cls_name = message.__class__.__name__
        if cls_name == "AIMessage" or getattr(message, "type", None) == "ai":
            content = getattr(message, "content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(str(block.get("text", "")))
                    elif isinstance(block, str):
                        parts.append(block)
                return "".join(parts)
    return ""


def _model_env_warnings(model: str) -> list[str]:
    warnings: list[str] = []
    lower = model.lower()
    if lower.startswith("openai:") and not _openai_api_key_for_model(model):
        warnings.append("OPENAI_API_KEY is not set")
    if lower.startswith("anthropic:") and not (os.getenv("ANTHROPIC_API_KEY") or "").strip():
        warnings.append("ANTHROPIC_API_KEY is not set")
    return warnings


def _openai_api_key_for_model(model: str) -> str:
    openai_api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if openai_api_key:
        return openai_api_key
    if "minimax" in model.lower():
        return (os.getenv("MINIMAX_API_KEY") or "").strip()
    return ""


def _import_deepagents() -> tuple[Any, Any]:
    try:
        from deepagents.backends.filesystem import FilesystemBackend
        from deepagents.graph import create_deep_agent
    except ModuleNotFoundError:
        _ensure_vendored_deepagents_path()
        importlib.invalidate_caches()
        from deepagents.backends.filesystem import FilesystemBackend
        from deepagents.graph import create_deep_agent
    return FilesystemBackend, create_deep_agent


def _ensure_vendored_deepagents_path() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    sdk_path = repo_root / "deepagents" / "libs" / "deepagents"
    if sdk_path.exists() and str(sdk_path) not in sys.path:
        sys.path.insert(0, str(sdk_path))


def _uses_minimax_openai_compatible_route(model: str) -> bool:
    lower_model = model.lower()
    if "minimax" in lower_model:
        return True
    for env_name in ("OPENAI_BASE_URL", "OPENAI_HOST"):
        raw = (os.getenv(env_name) or "").strip().lower()
        if "minimax.io" in raw:
            return True
    return False


def _resolve_deepagents_model(model: str, *, max_output_tokens: int | None = None) -> Any:
    if model.lower().startswith("anthropic:"):
        kwargs: dict[str, Any] = {}
        if max_output_tokens is not None:
            kwargs["max_tokens"] = max_output_tokens
        return init_chat_model(model, **kwargs)
    if model.lower().startswith("openai:") and _uses_minimax_openai_compatible_route(model):
        kwargs: dict[str, Any] = {"use_responses_api": False}
        openai_base_url = (os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_HOST") or "").strip()
        if openai_base_url:
            kwargs["base_url"] = openai_base_url
        openai_api_key = _openai_api_key_for_model(model)
        if openai_api_key:
            kwargs["api_key"] = openai_api_key
        return init_chat_model(model, **kwargs)
    return model


class DeepAgentsAdapter:
    """Single integration boundary for Deep Agents worker lanes (sandboxed, proposal-only)."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def _cap_text(self, value: str) -> str:
        cap = max(0, int(self.config.mesh_deepagents_max_artifact_chars))
        if cap == 0 or len(value) <= cap:
            return value
        return value[:cap] + "\n[truncated]"

    def build_lane_attempt(
        self,
        *,
        agent: str,
        task: AgentTask,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ) -> AgentAttempt:
        risk_flags: list[str] = []
        if not evaluation.passed:
            risk_flags.append("evaluation_failed")

        try:
            FilesystemBackend, create_deep_agent = _import_deepagents()
        except ImportError as exc:
            return build_agent_attempt(
                task_id=task.task_id,
                run_id=task.run_id,
                agent=agent,
                adapter="deepagents",
                status="failed",
                summary=self._cap_text(f"Deep Agents dependency unavailable: {exc}"),
                risk_flags=[*risk_flags, "deepagents_dependency_missing"],
                recommended_action="human_review",
                output={"error": self._cap_text(str(exc))},
            )

        workspace = (
            Path(self.config.mesh_deepagents_workspace_root).expanduser().resolve()
            / task.run_id
            / task.task_id
            / agent
        )
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True, exist_ok=True)

        repo = _repo_root(trigger, decision)
        snapshot = _copy_allowed_workspace(repo_root=repo, allowed_paths=task.allowed_paths, workspace=workspace)

        ctx = _bounded_task_context(
            task=task,
            trigger=trigger,
            decision=decision,
            evaluation=evaluation,
            max_chars=int(self.config.mesh_deepagents_max_artifact_chars),
        )
        env_warnings = _model_env_warnings(self.config.mesh_deepagents_model)
        if env_warnings:
            risk_flags.append("deepagents_model_credentials_missing")

        lane_prompt = _LANE_SYSTEM_PROMPTS.get(
            agent,
            "You are a Mesh worker lane producing bounded proposals only.",
        )
        include_rollback = task.kind == "rollback_plan"
        subagents = _mesh_subagent_specs(include_rollback=include_rollback)
        instructions = (
            "\n\nYou may delegate via the task tool to these subagents. "
            "Mesh forbids production Kubernetes access, mutating the real git checkout on main, "
            "and any Mesh actuation — proposals only.\n"
            "Shared memory is read-mostly. You may propose observations, claims, procedures, citations, "
            "and contradiction flags, but you may not mutate shared semantic or procedural memory directly.\n"
            "After analysis, respond with a single JSON object (no markdown fences) containing:\n"
            '{ "summary": string, "recommended_action": string, "risk_flags": string[], '
            '"changed_files": string[], "test_results": [ { "name": string, "passed": boolean, "detail": string } ], '
            '"observations_proposed": object[], "claims_proposed": object[], "procedures_proposed": object[], '
            '"citations": object[], "contradictions_detected": object[], "memory_actions_requested": string[] }\n'
            "Use changed_files only for sandbox paths you touched; use test_results only if you have concrete check outcomes."
        )

        backend = FilesystemBackend(root_dir=str(workspace), virtual_mode=True)
        try:
            graph = create_deep_agent(
                model=_resolve_deepagents_model(
                    self.config.mesh_deepagents_model,
                    max_output_tokens=int(self.config.mesh_deepagents_max_output_tokens),
                ),
                backend=backend,
                subagents=subagents,
                system_prompt=lane_prompt + instructions,
            )
        except Exception as exc:  # noqa: BLE001 — surface model/config errors as lane failures
            return build_agent_attempt(
                task_id=task.task_id,
                run_id=task.run_id,
                agent=agent,
                adapter="deepagents",
                status="failed",
                summary=self._cap_text(f"Deep Agents graph build failed: {exc}"),
                risk_flags=[*risk_flags, "deepagents_model_error"],
                recommended_action="human_review",
                output={
                    "error": self._cap_text(str(exc)),
                    "workspace_path": str(workspace),
                },
            )

        user_message = (
            "MESH_TASK_CONTEXT (read-only; Mesh owns policy and actuation):\n"
            f"{json.dumps(ctx, default=str)}\n"
            f"Sandbox workspace root (virtual paths are under this root): {workspace}\n"
        )

        def _invoke() -> dict[str, Any]:
            return graph.invoke({"messages": [HumanMessage(content=user_message)]})

        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(_invoke)
        try:
            result = future.result(timeout=float(self.config.mesh_deepagents_timeout_seconds))
        except FuturesTimeout:
            future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
            return build_agent_attempt(
                task_id=task.task_id,
                run_id=task.run_id,
                agent=agent,
                adapter="deepagents",
                status="failed",
                summary=self._cap_text(
                    f"Deep Agents invoke timed out after {self.config.mesh_deepagents_timeout_seconds}s",
                ),
                risk_flags=[*risk_flags, "deepagents_timeout"],
                recommended_action="human_review",
                output={
                    "workspace_path": str(workspace),
                    "context_chars": len(json.dumps(ctx, default=str)),
                },
            )
        except Exception as exc:  # noqa: BLE001
            pool.shutdown(wait=False, cancel_futures=True)
            return build_agent_attempt(
                task_id=task.task_id,
                run_id=task.run_id,
                agent=agent,
                adapter="deepagents",
                status="failed",
                summary=self._cap_text(f"Deep Agents invoke failed: {exc}"),
                risk_flags=[*risk_flags, "deepagents_invoke_failed"],
                recommended_action="human_review",
                output={
                    "error": self._cap_text(str(exc)),
                    "workspace_path": str(workspace),
                },
            )
        finally:
            if future.done() and not future.cancelled():
                pool.shutdown(wait=True)

        messages = result.get("messages", [])
        final_text = _final_ai_text(messages)
        parsed = _extract_json_object(final_text)
        if parsed is None and final_text.strip():
            risk_flags.append("deepagents_output_unparseable")

        diff_text, diff_changed = _diff_against_snapshot(snapshot, workspace)
        disallowed = _disallowed_workspace_files(task, workspace)
        if disallowed:
            risk_flags.append("deepagents_sandbox_path_violation")

        changed_files: list[str] = []
        test_results: list[dict[str, Any]] = []
        observations_proposed: list[dict[str, Any]] = []
        claims_proposed: list[dict[str, Any]] = []
        procedures_proposed: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = list(task.memory_packet.get("citations", []))
        contradictions_detected: list[dict[str, Any]] = list(task.memory_packet.get("contradictions", []))
        memory_actions_requested: list[str] = ["review"]
        summary = self._cap_text(final_text or "Deep Agents lane completed without parseable summary.")
        recommended_action = "human_review"

        if isinstance(parsed, dict):
            summary = self._cap_text(str(parsed.get("summary") or summary))
            recommended_action = str(parsed.get("recommended_action") or recommended_action)
            parsed_flags = parsed.get("risk_flags")
            if isinstance(parsed_flags, list):
                risk_flags.extend(str(x) for x in parsed_flags)
            cf = parsed.get("changed_files")
            if isinstance(cf, list):
                changed_files = [str(x) for x in cf]
            tr = parsed.get("test_results")
            if isinstance(tr, list):
                test_results = [x for x in tr if isinstance(x, dict)]
            if isinstance(parsed.get("observations_proposed"), list):
                observations_proposed = [x for x in parsed["observations_proposed"] if isinstance(x, dict)]
            if isinstance(parsed.get("claims_proposed"), list):
                claims_proposed = [x for x in parsed["claims_proposed"] if isinstance(x, dict)]
            if isinstance(parsed.get("procedures_proposed"), list):
                procedures_proposed = [x for x in parsed["procedures_proposed"] if isinstance(x, dict)]
            if isinstance(parsed.get("citations"), list):
                citations = [x for x in parsed["citations"] if isinstance(x, dict)]
            if isinstance(parsed.get("contradictions_detected"), list):
                contradictions_detected = [x for x in parsed["contradictions_detected"] if isinstance(x, dict)]
            if isinstance(parsed.get("memory_actions_requested"), list):
                memory_actions_requested = [str(x) for x in parsed["memory_actions_requested"]]

        if diff_changed:
            for path in diff_changed:
                if path not in changed_files:
                    changed_files.append(path)

        allowed_norm = {_normalize_rel(p) for p in task.allowed_paths}
        for path in list(changed_files):
            if allowed_norm and _normalize_rel(path) not in allowed_norm:
                risk_flags.append("deepagents_changed_file_not_allowlisted")
        for path in diff_changed:
            if allowed_norm and _normalize_rel(path) not in allowed_norm:
                risk_flags.append("deepagents_changed_file_not_allowlisted")

        output: dict[str, Any] = {
            "diff": self._cap_text(diff_text),
            "deepagents_final_message": self._cap_text(final_text),
            "workspace_path": str(workspace),
        }
        if env_warnings:
            output["model_env_warnings"] = env_warnings

        return build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent=agent,
            adapter="deepagents",
            status="completed",
            summary=summary,
            changed_files=changed_files,
            test_results=test_results,
            risk_flags=sorted(set(risk_flags)),
            recommended_action=recommended_action,
            output=output,
            observations_proposed=observations_proposed
            or [{"kind": "agent_observation", "service": trigger.service, "author": agent, "content": summary}],
            claims_proposed=claims_proposed,
            procedures_proposed=procedures_proposed,
            citations=citations,
            contradictions_detected=contradictions_detected,
            memory_actions_requested=memory_actions_requested,
        )
