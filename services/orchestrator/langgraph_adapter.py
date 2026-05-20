from __future__ import annotations

from typing import Any

from shared.mesh_runtime.agent_workers import build_agent_attempt
from shared.mesh_runtime.config import RuntimeConfig
from shared.mesh_runtime.control_plane_models import AgentAttempt, AgentTask
from shared.mesh_runtime.zaxy_langgraph import langgraph_workflow_record


class LangGraphAdapter:
    """Proposal-only LangGraph workflow boundary.

    LangGraph checkpointing is useful for long-running agent reasoning, but
    Mesh keeps policy, approval, tests, audit, promotion, and actuation.
    """

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig.from_env()

    def build_lane_attempt(
        self,
        *,
        agent: str,
        task: AgentTask,
        trigger: Any,
        decision: Any,
        evaluation: Any,
    ) -> AgentAttempt:
        checkpoint_id = f"lg_{task.task_id}_{agent}"
        output = {
            "workflow_name": "mesh_proposal_lane",
            "graph_version": "mesh.langgraph_proposal_workflow.v1",
            "thread_id": checkpoint_id,
            "checkpoint_ref": checkpoint_id,
            "checkpoint_ready": bool(self.config.langgraph_checkpointer_url),
            "authority": {
                "mesh_control_plane_authoritative": True,
                "langgraph_workflow_authoritative": False,
                "production_actuation_allowed": False,
            },
        }
        if not self.config.langgraph_checkpointer_url:
            return self._failed_attempt(
                agent=agent,
                task=task,
                summary="LangGraph proposal checkpointing is enabled but no checkpointer is configured.",
                risk_flags=["langgraph_checkpointer_unavailable"],
                output=output,
            )
        try:
            import langgraph  # noqa: F401
        except ImportError:
            return self._failed_attempt(
                agent=agent,
                task=task,
                summary="LangGraph package is not installed or not on PYTHONPATH.",
                risk_flags=["langgraph_dependency_missing"],
                output=output,
            )

        output["workflow_record"] = langgraph_workflow_record(
            self.config,
            task_id=task.task_id,
            run_id=task.run_id,
            agent=agent,
            checkpoint_id=checkpoint_id,
        )
        return build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent=agent,
            adapter="langgraph",
            status="completed",
            summary=f"{agent} LangGraph workflow checkpoint recorded as bounded proposal metadata.",
            risk_flags=[],
            recommended_action="human_review",
            output=output,
            observations_proposed=[
                {
                    "agent": agent,
                    "service": getattr(trigger, "service", None),
                    "content": "LangGraph workflow produced advisory proposal state only.",
                    "authority": "proposal_only",
                }
            ],
            citations=[
                {
                    "source_type": "langgraph_checkpoint",
                    "checkpoint_ref": checkpoint_id,
                    "mesh_run_id": task.run_id,
                }
            ],
        )

    def _failed_attempt(
        self,
        *,
        agent: str,
        task: AgentTask,
        summary: str,
        risk_flags: list[str],
        output: dict[str, Any],
    ) -> AgentAttempt:
        return build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent=agent,
            adapter="langgraph",
            status="failed",
            summary=summary,
            risk_flags=risk_flags,
            recommended_action="human_review",
            output=output,
        )
