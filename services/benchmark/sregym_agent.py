from __future__ import annotations

import argparse
import asyncio
import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from services.investigation import InvestigationService
from services.scenario_analysis import ScenarioAnalysisService
from shared.mesh_runtime import Trigger


class SreGymClient(Protocol):
    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        ...


@dataclass
class ToolRecorder:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self,
        *,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any],
        valid: bool = True,
        relevance: float = 1.0,
    ) -> None:
        self.calls.append(
            {
                "tool_name": tool_name,
                "args": args,
                "status": "completed" if valid else "invalid",
                "valid": valid,
                "relevance": relevance,
                "result_summary": _summary(result),
                "citation_ids": [f"sregym:{tool_name}:{len(self.calls) + 1}"],
            }
        )


@dataclass(frozen=True)
class SreGymEndpointConfig:
    """SREGym MCP SSE endpoint map.

    SREGym exposes diagnostic MCP tools through its benchmark MCP server,
    port-forwarded on ``MCP_SERVER_PORT``. The conductor API on ``API_PORT``
    exposes the stage-aware submit MCP at ``/submit_mcp/sse``.
    """

    kubectl_url: str
    prometheus_url: str
    loki_url: str
    jaeger_url: str
    submit_url: str

    @classmethod
    def from_server_url(
        cls,
        server_url: str,
        *,
        submit_path: str = "/submit_mcp/sse",
        mcp_server_url: str | None = None,
    ) -> "SreGymEndpointConfig":
        base = server_url.rstrip("/")
        mcp_base = (
            mcp_server_url.rstrip("/")
            if mcp_server_url
            else f"http://{os.getenv('API_HOSTNAME', 'localhost')}:{os.getenv('MCP_SERVER_PORT', '9954')}"
        )
        return cls(
            kubectl_url=f"{mcp_base}/kubectl/sse",
            prometheus_url=f"{mcp_base}/prometheus/sse",
            loki_url=f"{mcp_base}/loki/sse",
            jaeger_url=f"{mcp_base}/jaeger/sse",
            submit_url=f"{base}{submit_path}",
        )


class SseMcpSreGymClient:
    """SREGym MCP client using the benchmark server's SSE transports."""

    def __init__(
        self,
        server_url: str,
        *,
        session_id: str | None = None,
        submit_path: str = "/submit_mcp/sse",
        mcp_server_url: str | None = None,
    ) -> None:
        self.endpoints = SreGymEndpointConfig.from_server_url(
            server_url,
            submit_path=submit_path,
            mcp_server_url=mcp_server_url,
        )
        self.session_id = session_id or str(uuid.uuid4())

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        tool_name, endpoint, tool_args = self._normalize_tool(name, dict(arguments or {}))
        return asyncio.run(self._call_mcp_tool(endpoint, tool_name, tool_args))

    def _normalize_tool(self, name: str, arguments: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
        if name == "exec_read_only_kubectl_cmd":
            command = _kubectl_command(arguments)
            _assert_read_only_kubectl(command)
            return "exec_kubectl_cmd_safely", self.endpoints.kubectl_url, {"cmd": command}
        if name == "exec_kubectl_cmd_safely":
            command = _kubectl_command(arguments)
            return name, self.endpoints.kubectl_url, {"cmd": command}
        if name in {"rollback_command", "get_previous_rollbackable_cmd"}:
            return name, self.endpoints.kubectl_url, arguments
        if name in {"get_metrics", "get_alerts"}:
            return name, self.endpoints.prometheus_url, arguments
        if name == "get_logs":
            return name, self.endpoints.loki_url, arguments
        if name in {"get_services", "get_operations", "get_traces", "get_dependency_graph"}:
            return name, self.endpoints.jaeger_url, arguments
        if name == "submit":
            answer = arguments.get("ans") or arguments.get("answer")
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("SREGym submit requires a non-empty ans string")
            return name, self.endpoints.submit_url, {"ans": answer}
        raise ValueError(f"unknown SREGym tool: {name}")

    async def _call_mcp_tool(self, endpoint: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Live SREGym execution requires the `mcp` Python package. "
                "Run from the SREGym environment or install its client dependencies."
            ) from exc

        try:
            stream_context = sse_client(url=endpoint, headers={"sregym_ssid": self.session_id})
        except TypeError:
            stream_context = sse_client(url=endpoint)

        async with (
            stream_context as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)
        return _mcp_result_to_dict(result)


def run_mesh_sregym_agent(
    *,
    client: SreGymClient,
    trigger: Trigger | None = None,
    target: str = "local-kind",
    allow_mitigation: bool = True,
) -> dict[str, Any]:
    if target != "local-kind":
        raise ValueError("SREGym mitigation is only allowed for the local-kind benchmark target")

    recorder = ToolRecorder()
    if trigger is None:
        trigger = bootstrap_trigger_from_sregym(client, recorder)
    observations = _collect_observations(client, trigger, recorder)
    investigation = InvestigationService().investigate(
        trigger=trigger,
        evidence_pack={
            "source": "sregym_mcp",
            "sufficient": True,
            "probe_results": recorder.calls,
            "missing_fields": [],
        },
        service_context={"sregym_observations": observations},
    )
    scenario_analysis, _ = ScenarioAnalysisService().analyze(
        trigger,
        investigation_report=investigation.to_dict(),
    )
    diagnosis = _diagnosis_text(trigger, investigation.to_dict(), scenario_analysis.to_dict())
    _required_call_and_record(client, recorder, "submit", {"ans": diagnosis})

    mitigation = None
    if allow_mitigation:
        mitigation = _mitigation_command(trigger)
        if mitigation is not None:
            _call_and_record(client, recorder, "exec_kubectl_cmd_safely", mitigation)
            _required_call_and_record(client, recorder, "submit", {"ans": "done"})

    return {
        "diagnosis": diagnosis,
        "mitigation": mitigation,
        "investigation_report": investigation.to_dict(),
        "scenario_analysis": scenario_analysis.to_dict(),
        "tool_trajectory": recorder.calls,
    }


def bootstrap_trigger_from_sregym(client: SreGymClient, recorder: ToolRecorder | None = None) -> Trigger:
    recorder = recorder or ToolRecorder()
    services = _call_and_record(client, recorder, "get_services", {})
    pods = _call_and_record(
        client,
        recorder,
        "exec_read_only_kubectl_cmd",
        {"command": "kubectl get pods -A -o wide"},
    )
    deployment = _call_and_record(
        client,
        recorder,
        "exec_read_only_kubectl_cmd",
        {"command": "kubectl get deployments -A"},
    )
    service = _infer_service_from_observation(pods) or _infer_service_from_observation(services) or "unknown-service"
    return Trigger(
        trigger_id=f"sregym:{uuid.uuid4()}",
        trigger_type="kubernetes_deployment_unhealthy",
        triggered_at="1970-01-01T00:00:00Z",
        environment="sregym-local-kind",
        service=service,
        endpoint=f"deployment/{service}",
        flag_key="",
        current_rollout_pct=0,
        comparison_window={"baseline": "PT30M", "observed": "PT5M"},
        segment={"benchmark": "sregym"},
        metrics={
            "restart_count_total": 0,
            "baseline_p95_latency_ms": 0,
            "observed_p95_latency_ms": 0,
            "baseline_error_rate": 0.0,
            "observed_error_rate": 0.0,
            "sample_size": 1,
        },
        related_context={
            "sregym_services": services,
            "sregym_pods": pods,
            "sregym_deployments": deployment,
            "audit_logging_available": True,
        },
    )


def _collect_observations(client: SreGymClient, trigger: Trigger, recorder: ToolRecorder) -> dict[str, Any]:
    observations = {}
    observations["services"] = _call_and_record(client, recorder, "get_services", {})
    observations["metrics"] = _call_and_record(
        client,
        recorder,
        "get_metrics",
        {"query": f'up{{service="{trigger.service}"}}'},
    )
    observations["kubectl"] = _call_and_record(
        client,
        recorder,
        "exec_read_only_kubectl_cmd",
        {"command": f"kubectl describe deployment {trigger.service} -A"},
    )
    return observations


def _call_and_record(
    client: SreGymClient,
    recorder: ToolRecorder,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    try:
        result = client.call_tool(tool_name, args)
        recorder.record(tool_name=tool_name, args=args, result=result, valid=True)
        return result
    except Exception as exc:
        result = {"error": str(exc)}
        recorder.record(tool_name=tool_name, args=args, result=result, valid=False, relevance=0.0)
        return result


def _required_call_and_record(
    client: SreGymClient,
    recorder: ToolRecorder,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    result = _call_and_record(client, recorder, tool_name, args)
    status = str(result.get("status") or "").lower()
    if result.get("error") or status in {"error", "n/a"}:
        raise RuntimeError(f"required SREGym tool call failed: {tool_name}: {_summary(result)}")
    return result


def _diagnosis_text(trigger: Trigger, investigation_report: dict[str, Any], scenario_analysis: dict[str, Any]) -> str:
    findings = investigation_report.get("findings") if isinstance(investigation_report.get("findings"), list) else []
    first = findings[0].get("summary") if findings and isinstance(findings[0], dict) else "no dominant finding"
    return (
        f"Root cause for {trigger.service}/{trigger.endpoint}: {first}. "
        f"Suggested decision: {scenario_analysis.get('suggested_decision_type', 'escalate')}."
    )


def _mitigation_command(trigger: Trigger) -> dict[str, Any] | None:
    if trigger.trigger_type == "kubernetes_deployment_unhealthy":
        return {"cmd": f"kubectl rollout restart deployment {trigger.service} -A"}
    return None


def _summary(result: dict[str, Any]) -> str:
    return json.dumps(result, sort_keys=True)[:500]


def _kubectl_command(arguments: dict[str, Any]) -> str:
    command = arguments.get("cmd") or arguments.get("command") or arguments.get("query")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("kubectl tool requires cmd or command")
    command = command.strip()
    if not command.startswith("kubectl "):
        command = f"kubectl {command}"
    return command


def _assert_read_only_kubectl(command: str) -> None:
    read_only_prefixes = (
        "kubectl api-resources",
        "kubectl api-version",
        "kubectl auth can-i",
        "kubectl cluster-info",
        "kubectl config current-context",
        "kubectl config get",
        "kubectl config view",
        "kubectl describe",
        "kubectl diff",
        "kubectl events",
        "kubectl explain",
        "kubectl get",
        "kubectl logs",
        "kubectl options",
        "kubectl top",
        "kubectl version",
    )
    if command.startswith("kubectl logs -f") or not command.startswith(read_only_prefixes):
        raise ValueError(f"non-read-only kubectl command refused: {command}")


def _infer_service_from_observation(observation: dict[str, Any]) -> str | None:
    text = _summary(observation).lower()
    unhealthy_markers = ("crashloopbackoff", "imagepullbackoff", "errimagepull", "pending", "0/1")
    if not any(marker in text for marker in unhealthy_markers):
        return None
    for token in text.replace("\\n", " ").replace("/", " ").split():
        clean = token.strip(" ,.'\"[]{}():")
        if clean and any(marker in clean for marker in ("service", "frontend", "cart", "checkout", "product")):
            return clean.split("-")[0] if "-" in clean else clean
    return None


def _mcp_result_to_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    content = getattr(result, "content", None)
    if isinstance(content, list):
        parts = []
        for part in content:
            text = getattr(part, "text", None)
            if text is not None:
                parts.append(str(text))
        return {"result": "\n".join(parts)}
    if isinstance(result, list):
        parts = []
        for part in result:
            text = getattr(part, "text", None)
            parts.append(str(text if text is not None else part))
        return {"result": "\n".join(parts)}
    return {"result": str(result)}


def build_agent_registry_entry(
    *,
    server_url: str = "http://localhost:8000",
    workdir: str | None = None,
    target: str = "local-kind",
    agent_name: str = "mesh",
) -> dict[str, Any]:
    command = (
        "python -m services.benchmark.sregym_agent "
        f"--server-url {server_url} --target {target}"
    )
    return {
        "name": agent_name,
        "kickoff_command": command,
        "kickoff_workdir": workdir or str(Path.cwd()),
        "kickoff_env": None,
        "install_script": None,
        "agent_version": None,
        "container_isolation": False,
    }


def render_agent_yaml(entry: dict[str, Any]) -> str:
    lines = ["agents:"]
    lines.append(f"  - name: {entry['name']}")
    for key in ("kickoff_command", "kickoff_workdir", "kickoff_env", "install_script", "agent_version"):
        value = entry.get(key)
        rendered = "null" if value is None else str(value)
        lines.append(f"    {key}: {rendered}")
    lines.append(f"    container_isolation: {str(bool(entry.get('container_isolation'))).lower()}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Mesh as a SREGym custom agent.")
    parser.add_argument("--server", "--server-url", dest="server_url", default="http://localhost:8000")
    parser.add_argument("--submit-path", default="/submit_mcp/sse")
    parser.add_argument("--mcp-server-url", default=None)
    parser.add_argument("--trigger-json", default=None)
    parser.add_argument("--target", default="local-kind")
    parser.add_argument("--no-mitigation", action="store_true")
    parser.add_argument("--print-agent-yaml", action="store_true")
    parser.add_argument("--agent-name", default="mesh")
    parser.add_argument("--workdir", default=None)
    args = parser.parse_args()
    if args.print_agent_yaml:
        print(
            render_agent_yaml(
                build_agent_registry_entry(
                    server_url=args.server_url,
                    workdir=args.workdir,
                    target=args.target,
                    agent_name=args.agent_name,
                )
            ),
            end="",
        )
        return
    trigger = Trigger(**json.loads(args.trigger_json)) if args.trigger_json else None
    result = run_mesh_sregym_agent(
        client=SseMcpSreGymClient(
            args.server_url,
            submit_path=args.submit_path,
            mcp_server_url=args.mcp_server_url,
        ),
        trigger=trigger,
        target=args.target,
        allow_mitigation=not args.no_mitigation,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
