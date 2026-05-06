from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import RuntimeConfig
from .control_plane_models import GoalRecord, MerkleSnapshot, RunEvent, RunSession
from .postprocessing import VaultAiPostprocessor


VAULT_DIRECTORIES = (
    "Goals",
    "Runs",
    "Decisions",
    "Evaluations",
    "Executions",
    "Feedback",
    "Agents",
    "Merkle",
    "Notes",
    "Insights",
    "Visualizations",
    "MemoryObservations",
    "MemoryClaims",
    "MemoryProcedures",
    "MemoryRetrievals",
)


class VaultManager:
    def __init__(self, root_path: str | Path, runtime_config: RuntimeConfig | None = None):
        self.root_path = Path(root_path)
        self.root_path.mkdir(parents=True, exist_ok=True)
        for directory in VAULT_DIRECTORIES:
            (self.root_path / directory).mkdir(parents=True, exist_ok=True)
        self.postprocessor = VaultAiPostprocessor(self.root_path, runtime_config) if runtime_config else None

    def write_goal(self, goal: GoalRecord) -> str:
        relative_path = self._goal_note_path(goal.goal_id)
        lines = [
            f"# {goal.title}",
            "",
            f"- Goal ID: `{goal.goal_id}`",
            f"- Status: `{goal.status}`",
            f"- Tags: {', '.join(goal.tags) if goal.tags else 'none'}",
            f"- Updated: `{goal.updated_at}`",
            "",
            "## Objective",
            "",
            goal.objective,
            "",
            "## Success Criteria",
            "",
        ]
        if goal.success_criteria:
            lines.extend([f"- {criterion}" for criterion in goal.success_criteria])
        else:
            lines.append("- none recorded")
        self._write_markdown(relative_path, lines)
        return relative_path

    def write_run_bundle(
        self,
        session: RunSession,
        events: list[RunEvent],
        merkle: MerkleSnapshot,
        goal: GoalRecord | None,
    ) -> None:
        goal_link = self._wikilink(self._goal_note_path(goal.goal_id), goal.title) if goal else "none"
        run_lines = [
            f"# Run {session.run_id}",
            "",
            f"- Goal: {goal_link}",
            f"- Scenario: `{session.scenario_key or 'manual'}`",
            f"- Stage: `{session.stage}`",
            f"- Status: `{session.status}`",
            f"- Steering Mode: `{session.steering_mode}`",
            f"- Evaluation Mode: `{session.evaluation_mode}`",
            f"- Orchestration Mode: `{session.orchestration_mode}`",
            f"- Latest Merkle Root: `{merkle.root_hash}`",
            "",
            "## Linked Notes",
            "",
            f"- Decision: {self._artifact_link('Decisions', session.run_id)}",
            f"- Evaluation: {self._artifact_link('Evaluations', session.run_id)}",
            f"- Execution: {self._artifact_link('Executions', session.run_id)}",
            f"- Feedback: {self._artifact_link('Feedback', session.run_id)}",
            f"- Agents: {self._artifact_link('Agents', session.run_id)}",
            f"- Merkle: {self._artifact_link('Merkle', session.run_id)}",
            f"- Notes: {self._artifact_link('Notes', session.run_id)}",
            f"- Insights: {self._artifact_link('Insights', session.run_id)}",
            f"- Visualizations: {self._artifact_link('Visualizations', session.run_id)}",
            "",
            "## Timeline",
            "",
        ]
        for event in events:
            run_lines.append(
                f"- `{event.sequence:02d}` `{event.stage}` `{event.event_type}` at `{event.recorded_at}`"
            )
        self._write_markdown(self._run_note_path(session.run_id), run_lines)

        self._write_markdown(
            self._artifact_path("Decisions", session.run_id),
            self._artifact_document("Decision", session.artifacts.get("decision")),
        )
        self._write_markdown(
            self._artifact_path("Evaluations", session.run_id),
            self._artifact_document("Evaluation", session.artifacts.get("evaluation")),
        )
        self._write_markdown(
            self._artifact_path("Executions", session.run_id),
            self._artifact_document("Execution", session.artifacts.get("execution")),
        )
        self._write_markdown(
            self._artifact_path("Feedback", session.run_id),
            self._artifact_document("Feedback", session.artifacts.get("feedback")),
        )
        self._write_markdown(
            self._artifact_path("Agents", session.run_id),
            self._artifact_document("Agent Mesh", {"tasks": session.artifacts.get("agent_tasks", [])}),
        )
        self._write_markdown(
            self._artifact_path("Merkle", session.run_id),
            [
                f"# Merkle {session.run_id}",
                "",
                f"- Root: `{merkle.root_hash}`",
                f"- Leaves: `{merkle.leaf_count}`",
                "",
                "## Event IDs",
                "",
                *[f"- `{event_id}`" for event_id in merkle.event_ids],
            ],
        )
        notes_lines = [
            f"# Notes {session.run_id}",
            "",
            "## Operator Notes",
            "",
        ]
        if session.operator_notes:
            notes_lines.extend([f"- {note}" for note in session.operator_notes])
        else:
            notes_lines.append("- none recorded")
        self._write_markdown(self._artifact_path("Notes", session.run_id), notes_lines)
        if self.postprocessor is not None:
            self.postprocessor.write_run_postprocess(session, events, merkle, goal)

    def tree(self) -> list[dict[str, Any]]:
        def build(path: Path) -> list[dict[str, Any]]:
            nodes: list[dict[str, Any]] = []
            for child in sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
                relative_path = child.relative_to(self.root_path).as_posix()
                if child.is_dir():
                    nodes.append(
                        {
                            "name": child.name,
                            "path": relative_path,
                            "kind": "directory",
                            "children": build(child),
                        }
                    )
                else:
                    nodes.append({"name": child.name, "path": relative_path, "kind": "file"})
            return nodes

        return build(self.root_path)

    def read_document(self, relative_path: str) -> dict[str, str]:
        root = self.root_path.resolve()
        candidate = (root / relative_path).resolve()
        if not str(candidate).startswith(str(root)):
            raise FileNotFoundError(relative_path)
        return {
            "path": candidate.relative_to(root).as_posix(),
            "content": candidate.read_text(),
        }

    def _write_markdown(self, relative_path: str, lines: list[str]) -> None:
        destination = self.root_path / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("\n".join(lines).rstrip() + "\n")

    def write_memory_observation(self, observation: dict[str, Any]) -> str:
        relative_path = f"MemoryObservations/{observation['observation_id']}.md"
        lines = [
            f"# Observation {observation['observation_id']}",
            "",
            f"- Kind: `{observation.get('kind')}`",
            f"- Service: `{observation.get('service') or 'none'}`",
            f"- Run: `{observation.get('run_id') or 'none'}`",
            f"- Source Type: `{observation.get('source_type')}`",
            f"- Author: `{observation.get('author')}`",
            f"- Created: `{observation.get('created_at')}`",
            "",
            "## Content",
            "",
            str(observation.get("content") or ""),
            "",
            "## Source Refs",
            "",
            "```json",
            json.dumps(observation.get("source_refs", []), indent=2, sort_keys=True),
            "```",
        ]
        self._write_markdown(relative_path, lines)
        return relative_path

    def write_memory_claim(self, claim: dict[str, Any]) -> str:
        directory = "MemoryProcedures" if claim.get("tier") == "procedural" else "MemoryClaims"
        relative_path = f"{directory}/{claim['claim_id']}.md"
        lines = [
            f"# Claim {claim['claim_id']}",
            "",
            f"- Tier: `{claim.get('tier')}`",
            f"- State: `{claim.get('state')}`",
            f"- Confidence: `{claim.get('confidence')}`",
            f"- Freshness: `{claim.get('freshness')}`",
            f"- Superseded By: `{claim.get('superseded_by') or 'none'}`",
            f"- Updated: `{claim.get('updated_at')}`",
            "",
            "## Statement",
            "",
            str(claim.get("statement") or ""),
            "",
            "## Support",
            "",
            f"- Supporting observations: {', '.join(claim.get('supporting_observation_ids', [])) or 'none'}",
            f"- Contradicting claims: {', '.join(claim.get('contradicting_claim_ids', [])) or 'none'}",
            "",
            "## Confidence Factors",
            "",
            "```json",
            json.dumps(claim.get("confidence_factors", {}), indent=2, sort_keys=True),
            "```",
        ]
        self._write_markdown(relative_path, lines)
        return relative_path

    def write_memory_retrieval(self, retrieval: dict[str, Any]) -> str:
        relative_path = f"MemoryRetrievals/{retrieval['retrieval_id']}.md"
        lines = [
            f"# Retrieval {retrieval['retrieval_id']}",
            "",
            f"- Query: `{retrieval.get('query')}`",
            f"- Channels: {', '.join(retrieval.get('channels', [])) or 'none'}",
            f"- Created: `{retrieval.get('created_at')}`",
            "",
            "## Scope",
            "",
            "```json",
            json.dumps(retrieval.get("scope", {}), indent=2, sort_keys=True),
            "```",
            "",
            "## IDs",
            "",
            f"- Candidate IDs: {', '.join(retrieval.get('candidate_ids', [])) or 'none'}",
            f"- Verified IDs: {', '.join(retrieval.get('verified_ids', [])) or 'none'}",
            f"- Discarded IDs: {', '.join(retrieval.get('discarded_ids', [])) or 'none'}",
        ]
        self._write_markdown(relative_path, lines)
        return relative_path

    def _artifact_document(self, title: str, payload: dict[str, Any] | None) -> list[str]:
        lines = [f"# {title}", ""]
        if payload is None:
            lines.append("No artifact recorded.")
            return lines
        lines.extend(
            [
                "```json",
                json.dumps(payload, indent=2, sort_keys=True),
                "```",
            ]
        )
        return lines

    def _goal_note_path(self, goal_id: str) -> str:
        return f"Goals/{goal_id}.md"

    def _run_note_path(self, run_id: str) -> str:
        return f"Runs/{run_id}.md"

    def _artifact_path(self, directory: str, run_id: str) -> str:
        return f"{directory}/{run_id}.md"

    def _artifact_link(self, directory: str, run_id: str) -> str:
        return self._wikilink(self._artifact_path(directory, run_id), f"{directory.lower()} note")

    def _wikilink(self, relative_path: str, label: str) -> str:
        return f"[[{relative_path[:-3]}|{label}]]"
