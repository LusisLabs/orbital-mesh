from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .runtime import DatasetRow, stable_digest, utc_now
from .serving import ServingPlan


@dataclass
class ToolDefinition:
    name: str
    schema: dict[str, Any]
    allowed_roles: set[str]
    protected: bool = False
    risk_level: str = "low"


@dataclass
class RuntimeUser:
    user_id: str
    tenant_id: str
    roles: set[str]


@dataclass
class ModelProposal:
    content: str
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = field(default_factory=dict)
    memory_write: dict[str, Any] | None = None


@dataclass
class ApprovalDecision:
    required: bool
    approved: bool
    approver: str | None = None
    reason: str | None = None


@dataclass
class RuntimeEvent:
    event_type: str
    run_id: str
    recorded_at: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MemoryRecord:
    memory_id: str
    tenant_id: str
    version: int
    proposed_by: str
    reviewed_by: str | None
    state: str
    payload: dict[str, Any]
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentRuntimeResult:
    run_id: str
    status: str
    final_output: str
    events: list[RuntimeEvent]
    memory_records: list[MemoryRecord]
    eval_signals: dict[str, Any]
    feedback: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "final_output": self.final_output,
            "events": [event.to_dict() for event in self.events],
            "memory_records": [record.to_dict() for record in self.memory_records],
            "eval_signals": dict(self.eval_signals),
            "feedback": dict(self.feedback),
        }


class MeshOSAgentRuntime:
    def __init__(self, *, tool_registry: list[ToolDefinition], approval_allowlist: set[str] | None = None):
        self._tools = {tool.name: tool for tool in tool_registry}
        self._approval_allowlist = set(approval_allowlist or set())
        self._memory_versions: dict[str, int] = {}

    def run(
        self,
        *,
        run_id: str,
        serving_plan: ServingPlan,
        user: RuntimeUser,
        proposal: ModelProposal,
        approval: ApprovalDecision | None = None,
    ) -> AgentRuntimeResult:
        events: list[RuntimeEvent] = []
        memory_records: list[MemoryRecord] = []
        self._record(events, "model_call", run_id, {"serving_plan": serving_plan.to_dict(), "proposal": asdict(proposal)})
        self._record(events, "adapter_selected", run_id, {"adapter_artifact_ids": list(serving_plan.adapter_artifact_ids)})

        tool_result: dict[str, Any] | None = None
        status = "completed"
        final_output = proposal.content

        if proposal.tool_name:
            tool = self._tools.get(proposal.tool_name)
            schema_result = self._validate_tool_schema(tool=tool, arguments=proposal.tool_arguments)
            self._record(events, "tool_schema_validated", run_id, schema_result)
            policy_result = self._evaluate_policy(tool=tool, user=user, schema_valid=schema_result["valid"])
            self._record(events, "policy_decision", run_id, policy_result)

            if not schema_result["valid"]:
                status = "blocked_invalid_schema"
                final_output = "Tool call blocked: invalid schema."
            elif not policy_result["allowed"]:
                status = "blocked_by_policy"
                final_output = "Tool call blocked: policy denied execution."
            elif policy_result["approval_required"]:
                approval_result = self._apply_approval(tool_name=proposal.tool_name, approval=approval)
                self._record(events, "approval_decision", run_id, approval_result)
                if not approval_result["approved"]:
                    status = "approval_required"
                    final_output = "Operator approval required before tool execution."
                else:
                    tool_result = self._execute_tool(proposal.tool_name, proposal.tool_arguments)
                    self._record(events, "tool_call", run_id, tool_result)
            else:
                tool_result = self._execute_tool(proposal.tool_name, proposal.tool_arguments)
                self._record(events, "tool_call", run_id, tool_result)

        if proposal.memory_write is not None:
            memory = self._propose_memory(
                tenant_id=user.tenant_id,
                run_id=run_id,
                proposed_by=user.user_id,
                payload=proposal.memory_write,
                approval=approval,
            )
            memory_records.append(memory)
            self._record(events, "memory_write_proposed", run_id, memory.to_dict())

        eval_signals = self._collect_eval_signals(events=events, status=status)
        feedback = self._collect_feedback(status=status, tool_result=tool_result)
        self._record(events, "eval_signals_collected", run_id, eval_signals)
        self._record(events, "runtime_feedback_collected", run_id, feedback)
        self._record(events, "final_output", run_id, {"status": status, "content": final_output})

        return AgentRuntimeResult(
            run_id=run_id,
            status=status,
            final_output=final_output,
            events=events,
            memory_records=memory_records,
            eval_signals=eval_signals,
            feedback=feedback,
        )

    def replay(self, result: AgentRuntimeResult) -> dict[str, Any]:
        event_types = [event.event_type for event in result.events]
        return {
            "run_id": result.run_id,
            "event_count": len(result.events),
            "event_types": event_types,
            "tool_executed": "tool_call" in event_types,
            "policy_recorded_before_tool": _precedes(event_types, "policy_decision", "tool_call"),
            "final_status": result.status,
        }

    def export_replay_dataset_row(self, *, tenant_id: str, result: AgentRuntimeResult, provenance_pointer: str) -> DatasetRow:
        trace = result.to_dict()
        return DatasetRow(
            row_id=f"mb_runtime_trace_{stable_digest({'tenant_id': tenant_id, 'trace': trace})[:16]}",
            tenant_id=tenant_id,
            source="agent_runtime_trace",
            timestamp=utc_now(),
            redaction_status="clean",
            license_usage_class="internal_enterprise",
            provenance_pointer=provenance_pointer,
            row_type="rl_trajectory",
            payload={
                "state": {"run_id": result.run_id, "events": [event.event_type for event in result.events]},
                "action": result.status,
                "observation": trace,
                "reward": 1.0 if result.status == "completed" else 0.0,
                "terminal_outcome": result.status,
            },
        )

    def _validate_tool_schema(self, *, tool: ToolDefinition | None, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool is None:
            return {"valid": False, "reason": "unknown_tool"}
        required = set(tool.schema.get("required", []))
        properties = set((tool.schema.get("properties") or {}).keys())
        argument_keys = set(arguments.keys())
        missing = sorted(required - argument_keys)
        extra = sorted(argument_keys - properties) if tool.schema.get("additionalProperties") is False else []
        return {
            "valid": not missing and not extra,
            "tool": tool.name,
            "missing": missing,
            "extra": extra,
        }

    def _evaluate_policy(self, *, tool: ToolDefinition | None, user: RuntimeUser, schema_valid: bool) -> dict[str, Any]:
        if tool is None or not schema_valid:
            return {"allowed": False, "approval_required": False, "reason": "schema_or_tool_invalid"}
        role_allowed = bool(user.roles & tool.allowed_roles)
        approval_required = (tool.protected or tool.risk_level in {"high", "critical"}) and tool.name not in self._approval_allowlist
        return {
            "allowed": role_allowed,
            "approval_required": approval_required,
            "tool": tool.name,
            "risk_level": tool.risk_level,
            "user_id": user.user_id,
            "tenant_id": user.tenant_id,
            "roles": sorted(user.roles),
        }

    def _apply_approval(self, *, tool_name: str, approval: ApprovalDecision | None) -> dict[str, Any]:
        if approval is None:
            return {"tool": tool_name, "required": True, "approved": False, "reason": "approval_missing"}
        return {"tool": tool_name, **asdict(approval)}

    def _execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool": tool_name,
            "arguments": dict(arguments),
            "status": "executed",
            "observation": {"summary": f"{tool_name} completed in sandbox"},
        }

    def _propose_memory(
        self,
        *,
        tenant_id: str,
        run_id: str,
        proposed_by: str,
        payload: dict[str, Any],
        approval: ApprovalDecision | None,
    ) -> MemoryRecord:
        key = f"{tenant_id}:{stable_digest(payload)[:12]}"
        version = self._memory_versions.get(key, 0) + 1
        self._memory_versions[key] = version
        reviewed = approval.approved if approval is not None else False
        return MemoryRecord(
            memory_id=f"mb_memory_{stable_digest({'tenant': tenant_id, 'payload': payload})[:16]}",
            tenant_id=tenant_id,
            version=version,
            proposed_by=proposed_by,
            reviewed_by=approval.approver if approval and approval.approved else None,
            state="reviewed" if reviewed else "proposed",
            payload=dict(payload),
            created_at=utc_now(),
        )

    def _collect_eval_signals(self, *, events: list[RuntimeEvent], status: str) -> dict[str, Any]:
        event_types = [event.event_type for event in events]
        return {
            "status": status,
            "schema_validated": "tool_schema_validated" in event_types,
            "policy_evaluated": "policy_decision" in event_types,
            "tool_executed": "tool_call" in event_types,
            "approval_route_correct": status != "completed" or "policy_decision" in event_types or "tool_schema_validated" not in event_types,
            "trace_replayable": all(event.run_id and event.recorded_at for event in events),
        }

    def _collect_feedback(self, *, status: str, tool_result: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "outcome": "successful" if status == "completed" else status,
            "tool_status": tool_result.get("status") if tool_result else None,
            "collected_at": utc_now(),
        }

    def _record(self, events: list[RuntimeEvent], event_type: str, run_id: str, payload: dict[str, Any]) -> None:
        events.append(RuntimeEvent(event_type=event_type, run_id=run_id, recorded_at=utc_now(), payload=payload))


def build_agent_runtime_e2e(*, serving_plan: ServingPlan) -> tuple[MeshOSAgentRuntime, AgentRuntimeResult]:
    runtime = MeshOSAgentRuntime(
        tool_registry=[
            ToolDefinition(
                name="kubernetes.restart_deployment",
                schema={
                    "type": "object",
                    "properties": {"deployment": {"type": "string"}, "namespace": {"type": "string"}},
                    "required": ["deployment", "namespace"],
                    "additionalProperties": False,
                },
                allowed_roles={"sre"},
                protected=True,
                risk_level="high",
            )
        ]
    )
    result = runtime.run(
        run_id="mb_agent_runtime_reference",
        serving_plan=serving_plan,
        user=RuntimeUser(user_id="operator_1", tenant_id=serving_plan.route.tenant_id, roles={"sre"}),
        proposal=ModelProposal(
            content="Restart requires approval because it is protected.",
            tool_name="kubernetes.restart_deployment",
            tool_arguments={"deployment": "search", "namespace": "prod"},
            memory_write={"lesson": "Restart deployment requires approval for tenant production workloads."},
        ),
        approval=ApprovalDecision(required=True, approved=False, reason="operator_not_present"),
    )
    return runtime, result


def _precedes(event_types: list[str], before: str, after: str) -> bool:
    if after not in event_types:
        return before in event_types
    if before not in event_types:
        return False
    return event_types.index(before) < event_types.index(after)
