from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
from pathlib import Path
from typing import Any

from .config import RuntimeConfig
from .control_plane_models import GoalRecord, MerkleSnapshot, RunEvent, RunSession
from .integrations import resolve_integrations_config
from .merkle import branch_hash, build_merkle_proof

POSTPROCESSABLE_STAGES = {"feedback_ready", "completed", "failed", "cancelled"}


class VaultAiPostprocessor:
    def __init__(self, vault_root: str | Path, runtime_config: RuntimeConfig):
        self.vault_root = Path(vault_root)
        self.runtime_config = runtime_config
        self.meta_dir = Path(runtime_config.state_directory) / "postprocess"
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self._active_runs: set[str] = set()
        self._lock = threading.Lock()

    def write_run_postprocess(
        self,
        session: RunSession,
        events: list[RunEvent],
        merkle: MerkleSnapshot,
        goal: GoalRecord | None,
    ) -> None:
        if not self.runtime_config.vault_ai_postprocess_enabled:
            return
        if session.stage not in POSTPROCESSABLE_STAGES:
            return
        if not events:
            return

        proof_event = self._proof_event(events)
        proof = build_merkle_proof(session.run_id, events, proof_event.event_id) if proof_event else None

        insight_markdown = self._fallback_insight_markdown(session, goal, proof_event)
        visualization_markdown = self._fallback_visualization_markdown(session, merkle, proof_event, proof)
        self._write_markdown(self.vault_root / "Insights" / f"{session.run_id}.md", insight_markdown)
        self._write_markdown(self.vault_root / "Visualizations" / f"{session.run_id}.md", visualization_markdown)

        if self._is_current(session, merkle):
            return
        if not self._mark_active(session.run_id):
            return
        threading.Thread(
            target=self._generate_and_write,
            args=(session, list(events), merkle, goal, proof_event, proof, insight_markdown, visualization_markdown),
            daemon=True,
        ).start()

    def _generate_and_write(
        self,
        session: RunSession,
        events: list[RunEvent],
        merkle: MerkleSnapshot,
        goal: GoalRecord | None,
        proof_event: RunEvent | None,
        proof: Any,
        insight_markdown: str,
        visualization_markdown: str,
    ) -> None:
        try:
            ai_payload = self._generate_ai_markdown(session, goal, events, merkle, proof_event, proof)
            if ai_payload is not None:
                insight_markdown = ai_payload.get("run_insight_markdown", "").strip() or insight_markdown
                visualization_markdown = (
                    ai_payload.get("merkle_visualization_markdown", "").strip() or visualization_markdown
                )
                self._write_markdown(self.vault_root / "Insights" / f"{session.run_id}.md", insight_markdown)
                self._write_markdown(self.vault_root / "Visualizations" / f"{session.run_id}.md", visualization_markdown)
            self._write_meta(session, merkle, proof_event)
        finally:
            self._clear_active(session.run_id)

    def _mark_active(self, run_id: str) -> bool:
        with self._lock:
            if run_id in self._active_runs:
                return False
            self._active_runs.add(run_id)
            return True

    def _clear_active(self, run_id: str) -> None:
        with self._lock:
            self._active_runs.discard(run_id)

    def _generate_ai_markdown(
        self,
        session: RunSession,
        goal: GoalRecord | None,
        events: list[RunEvent],
        merkle: MerkleSnapshot,
        proof_event: RunEvent | None,
        proof: Any,
    ) -> dict[str, str] | None:
        command = self._goose_postprocess_command()
        if not command:
            return None

        prompt_payload = {
            "goal": goal.to_dict() if goal else None,
            "run": {
                "run_id": session.run_id,
                "scenario_key": session.scenario_key,
                "stage": session.stage,
                "status": session.status,
                "steering_mode": session.steering_mode,
                "evaluation_mode": session.evaluation_mode,
                "orchestration_mode": session.orchestration_mode,
                "operator_notes": session.operator_notes,
            },
            "decision": session.artifacts.get("decision"),
            "evaluation": session.artifacts.get("evaluation"),
            "execution": session.artifacts.get("execution"),
            "feedback": session.artifacts.get("feedback"),
            "merkle": merkle.to_dict(),
            "proof_event": proof_event.to_dict() if proof_event else None,
            "proof": proof.to_dict() if proof is not None else None,
            "recent_events": [event.to_dict() for event in events[-8:]],
        }
        system_prompt = (
            "Reply with only compact JSON matching this shape: "
            '{"run_insight_markdown": string, "merkle_visualization_markdown": string}. '
            "Write polished markdown suitable for operator documentation. "
            "Be precise, concise, and operationally useful. Do not include markdown fences."
        )
        user_prompt = (
            "Generate two markdown documents for this run.\n\n"
            "1. `run_insight_markdown`: explain what happened, why it mattered, operator-relevant risks, "
            "and recommended next checks.\n"
            "2. `merkle_visualization_markdown`: explain the proof target event, verification path, "
            "and how the proof links the event to the root. Include a Mermaid diagram.\n\n"
            f"Run payload:\n{json.dumps(prompt_payload, indent=2, sort_keys=True)}"
        )
        payload = self._run_goose_with_fallback(command, user_prompt, system_prompt)
        if payload is None:
            return None
        text = self._assistant_text(payload)
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        run_markdown = parsed.get("run_insight_markdown")
        merkle_markdown = parsed.get("merkle_visualization_markdown")
        if not isinstance(run_markdown, str) or not isinstance(merkle_markdown, str):
            return None
        return {
            "run_insight_markdown": run_markdown,
            "merkle_visualization_markdown": merkle_markdown,
        }

    def _goose_postprocess_command(self) -> list[str] | None:
        resolved = resolve_integrations_config(self.runtime_config)
        if not resolved.goose_command:
            return None
        tokens = shlex.split(resolved.goose_command)
        goose_bin = self._flag_value(tokens, "--goose-bin")
        if goose_bin is None:
            return None
        provider = self._flag_value(tokens, "--provider") or self._env_provider()
        model = self._flag_value(tokens, "--model") or self._env_model()
        fallback_provider = self._flag_value(tokens, "--fallback-provider") or os.getenv("GOOSE_FALLBACK_PROVIDER")
        fallback_model = self._flag_value(tokens, "--fallback-model") or os.getenv("GOOSE_FALLBACK_MODEL")
        return self._profiled_goose_commands(goose_bin, provider, model, fallback_provider, fallback_model)

    def _run_goose_with_fallback(
        self,
        commands: list[list[str]],
        user_prompt: str,
        system_prompt: str,
    ) -> dict[str, Any] | None:
        for command in commands:
            try:
                completed = subprocess.run(
                    command + ["run", "--text", user_prompt, "--system", system_prompt, "--no-session", "--quiet", "--output-format", "json"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=90,
                    env=self._command_env(self._flag_value(command, "--provider")),
                )
            except (OSError, subprocess.TimeoutExpired):
                continue
            if completed.returncode != 0:
                continue
            try:
                return json.loads(completed.stdout)
            except json.JSONDecodeError:
                continue
        return None

    def _profiled_goose_commands(
        self,
        goose_bin: str,
        provider: str | None,
        model: str | None,
        fallback_provider: str | None,
        fallback_model: str | None,
    ) -> list[list[str]]:
        commands = [self._single_goose_command(goose_bin, provider, model)]
        if (fallback_provider or fallback_model) and (fallback_provider, fallback_model) != (provider, model):
            commands.append(self._single_goose_command(goose_bin, fallback_provider, fallback_model))
        return commands

    def _single_goose_command(self, goose_bin: str, provider: str | None, model: str | None) -> list[str]:
        command = [goose_bin]
        if provider or model:
            command.append("--no-profile")
        if provider:
            command.extend(["--provider", provider])
        if model:
            command.extend(["--model", model])
        return command

    def _env_provider(self) -> str | None:
        provider = os.getenv("GOOSE_PROVIDER")
        if provider:
            return provider
        hermes_provider = os.getenv("HERMES_INFERENCE_PROVIDER")
        if hermes_provider and hermes_provider.lower() != "auto":
            return hermes_provider
        if hermes_provider and hermes_provider.lower() == "auto" and os.getenv("OPENAI_BASE_URL"):
            return "openai"
        if os.getenv("OPENAI_BASE_URL"):
            return "openai"
        return None

    def _env_model(self) -> str | None:
        return os.getenv("GOOSE_MODEL") or os.getenv("HERMES_MODEL") or os.getenv("LLM_MODEL")

    def _proof_event(self, events: list[RunEvent]) -> RunEvent | None:
        preferred_types = ("execution_recorded", "feedback_recorded", "evaluation_ready", "decision_ready")
        for event_type in preferred_types:
            for event in reversed(events):
                if event.event_type == event_type:
                    return event
        return events[-1] if events else None

    def _fallback_insight_markdown(
        self,
        session: RunSession,
        goal: GoalRecord | None,
        proof_event: RunEvent | None,
    ) -> str:
        evaluation = session.artifacts.get("evaluation") or {}
        execution = session.artifacts.get("execution") or {}
        feedback = session.artifacts.get("feedback") or {}
        blocking_reasons = evaluation.get("blocking_reasons") or []
        lines = [
            f"# AI Run Insight {session.run_id}",
            "",
            f"- Goal: {goal.title if goal else 'none'}",
            f"- Scenario: `{session.scenario_key or 'manual'}`",
            f"- Final Stage: `{session.stage}`",
            f"- Evaluation Recommendation: `{evaluation.get('final_recommendation', 'unknown')}`",
            f"- Execution Status: `{execution.get('status', 'not recorded')}`",
            f"- Feedback Outcome: `{feedback.get('outcome', 'not recorded')}`",
            f"- Proof Focus Event: `{proof_event.event_id if proof_event else 'none'}`",
            "",
            "## Operator Summary",
            "",
        ]
        if blocking_reasons:
            lines.extend([f"- Blocking reason: {reason}" for reason in blocking_reasons])
        else:
            lines.append("- No blocking evaluation reasons were recorded.")
        lines.extend(
            [
                "",
                "## Recommended Next Checks",
                "",
                "- Verify the recorded execution and feedback artifacts for the bounded action outcome.",
                "- Review the Merkle visualization to confirm the selected event chains to the stored root.",
                "- Re-run or override only if the current evaluation recommendation no longer matches operator intent.",
            ]
        )
        return "\n".join(lines)

    def _fallback_visualization_markdown(
        self,
        session: RunSession,
        merkle: MerkleSnapshot,
        proof_event: RunEvent | None,
        proof: Any,
    ) -> str:
        diagram = self._merkle_mermaid(proof)
        lines = [
            f"# Merkle Visualization {session.run_id}",
            "",
            f"- Root Hash: `{merkle.root_hash}`",
            f"- Leaf Count: `{merkle.leaf_count}`",
            f"- Proof Event: `{proof_event.event_id if proof_event else 'none'}`",
            "",
            "## Inclusion Path",
            "",
        ]
        if proof is not None and getattr(proof, "proof", None):
            lines.extend(
                [
                    f"- Step {index + 1}: combine `{step.position}` sibling `{step.hash}`"
                    for index, step in enumerate(proof.proof)
                ]
            )
        else:
            lines.append("- No proof chain available.")
        lines.extend(
            [
                "",
                "## Diagram",
                "",
                "```mermaid",
                diagram,
                "```",
            ]
        )
        return "\n".join(lines)

    def _merkle_mermaid(self, proof: Any) -> str:
        if proof is None:
            return "flowchart TD\n  root[No proof available]"
        cursor = proof.leaf_hash
        lines = ["flowchart TD", f'  leaf["Leaf<br/>{cursor[:16]}"]']
        previous = "leaf"
        for index, step in enumerate(proof.proof):
            sibling_id = f"s{index}"
            node_id = f"n{index}"
            lines.append(f'  {sibling_id}["{step.position.title()} Sibling<br/>{step.hash[:16]}"]')
            combined = branch_hash(step.hash, cursor) if step.position == "left" else branch_hash(cursor, step.hash)
            lines.append(f'  {node_id}["Level {index + 1}<br/>{combined[:16]}"]')
            if step.position == "left":
                lines.append(f"  {sibling_id} --> {node_id}")
                lines.append(f"  {previous} --> {node_id}")
            else:
                lines.append(f"  {previous} --> {node_id}")
                lines.append(f"  {sibling_id} --> {node_id}")
            previous = node_id
            cursor = combined
        lines.append(f'  root["Root<br/>{proof.root_hash[:16]}"]')
        lines.append(f"  {previous} --> root")
        return "\n".join(lines)

    def _write_markdown(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n")

    def _is_current(self, session: RunSession, merkle: MerkleSnapshot) -> bool:
        meta_path = self.meta_dir / f"{session.run_id}.json"
        if not meta_path.exists():
            return False
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            return False
        return meta.get("root_hash") == merkle.root_hash and meta.get("stage") == session.stage

    def _write_meta(self, session: RunSession, merkle: MerkleSnapshot, proof_event: RunEvent | None) -> None:
        meta_path = self.meta_dir / f"{session.run_id}.json"
        meta_path.write_text(
            json.dumps(
                {
                    "run_id": session.run_id,
                    "root_hash": merkle.root_hash,
                    "stage": session.stage,
                    "proof_event_id": proof_event.event_id if proof_event else None,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    def _flag_value(self, tokens: list[str], flag: str) -> str | None:
        try:
            index = tokens.index(flag)
        except ValueError:
            return None
        if index + 1 >= len(tokens):
            return None
        return tokens[index + 1]

    def _command_env(self, provider: str | None) -> dict[str, str]:
        env = os.environ.copy()
        if provider == "openai" and env.get("OPENAI_BASE_URL") and not env.get("OPENAI_HOST"):
            env["OPENAI_HOST"] = env["OPENAI_BASE_URL"]
        if provider == "anthropic" and env.get("ANTHROPIC_BASE_URL") and not env.get("ANTHROPIC_HOST"):
            env["ANTHROPIC_HOST"] = env["ANTHROPIC_BASE_URL"]
        return env

    def _assistant_text(self, payload: dict[str, Any]) -> str:
        messages = payload.get("messages", [])
        for message in reversed(messages):
            if message.get("role") != "assistant":
                continue
            parts = message.get("content", [])
            text = "".join(part.get("text", "") for part in parts if part.get("type") == "text").strip()
            if text:
                return text
        return ""
