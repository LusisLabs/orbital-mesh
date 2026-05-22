from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, is_dataclass
from typing import Any, Protocol

from shared.mesh_runtime.agent_workers import build_agent_attempt, build_agent_attempt_thread
from shared.mesh_runtime.config import RuntimeConfig
from shared.mesh_runtime.control_plane_models import AgentAttempt, AgentAttemptThreadEvent, AgentTask


class CentaurClient(Protocol):
    def run_sandbox(self, request: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        ...


class HttpCentaurClient:
    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config

    def run_sandbox(self, request: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        if not self.config.centaur_endpoint:
            raise CentaurAdapterError("MESH_CENTAUR_ENDPOINT is not configured")
        api_key = os.getenv(self.config.centaur_api_key_env_name, "")
        if not api_key:
            raise CentaurAdapterError(f"{self.config.centaur_api_key_env_name} is not configured")

        thread_key = str(request["thread_key"])
        execute_id = f"mesh-{request['run_id']}-{request['task_id']}-{request['agent']}"
        execute_result = self._post_json(
            "/agent/execute",
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            payload={
                "thread_key": thread_key,
                "execute_id": execute_id,
                "harness": request.get("harness"),
                "message": _prompt_from_request(request),
                "delivery": {"channel": "mesh", "platform": "mesh", "recipient_user_id": "mesh-control-plane"},
                "metadata": {
                    "mesh_run_id": request.get("run_id"),
                    "mesh_task_id": request.get("task_id"),
                    "mesh_agent": request.get("agent"),
                    "mesh_authority": request.get("authority", {}),
                    "state_slice": request.get("state_slice"),
                },
            },
        )
        execution_id = str(execute_result.get("execution_id") or execute_result.get("execute_id") or execute_id)
        final = self._poll_execution(execution_id, api_key=api_key, timeout_seconds=timeout_seconds)
        release = self._release_thread(thread_key, api_key=api_key, timeout_seconds=timeout_seconds)
        return _normalize_centaur_execution_result(execute_result=execute_result, final=final, release=release)

    def _post_json(
        self,
        path: str,
        *,
        api_key: str,
        timeout_seconds: float,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._request_json(path, api_key=api_key, timeout_seconds=timeout_seconds, method="POST", payload=payload)

    def _get_json(self, path: str, *, api_key: str, timeout_seconds: float) -> dict[str, Any]:
        return self._request_json(path, api_key=api_key, timeout_seconds=timeout_seconds, method="GET", payload=None)

    def _request_json(
        self,
        path: str,
        *,
        api_key: str,
        timeout_seconds: float,
        method: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        url = self.config.centaur_endpoint.rstrip("/") + path
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-Mesh-Authority": "proposal-only",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                body = response.read()
        except urllib.error.URLError as exc:
            raise CentaurAdapterError(str(exc)) from exc
        result = json.loads(body.decode("utf-8"))
        if not isinstance(result, dict):
            raise CentaurAdapterError(f"Centaur {path} response must be a JSON object")
        return result

    def _poll_execution(self, execution_id: str, *, api_key: str, timeout_seconds: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_seconds
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            last = self._get_json(f"/agent/executions/{execution_id}", api_key=api_key, timeout_seconds=timeout_seconds)
            if str(last.get("status") or "") in {"completed", "failed_permanent", "cancelled"}:
                return last
            time.sleep(0.5)
        raise CentaurAdapterError(f"Centaur execution {execution_id} did not finish within {timeout_seconds}s")

    def _release_thread(self, thread_key: str, *, api_key: str, timeout_seconds: float) -> dict[str, Any]:
        try:
            return self._post_json(
                f"/agent/threads/{urllib.parse.quote(thread_key, safe='')}/release",
                api_key=api_key,
                timeout_seconds=timeout_seconds,
                payload={"cancel_inflight": False},
            )
        except CentaurAdapterError:
            return {"released": False, "release_error": "release_failed_closed"}


class CentaurAdapterError(RuntimeError):
    pass


class CentaurAdapter:
    """Proposal-only Centaur-style sandbox boundary.

    Provenance: adapted from Centaur source-input patterns recorded in
    docs/centaur-source-input.md. This adapter mirrors lifecycle semantics but
    returns only Mesh AgentAttempt records; Mesh remains authoritative.
    """

    def __init__(self, config: RuntimeConfig | None = None, client: CentaurClient | None = None) -> None:
        self.config = config or RuntimeConfig.from_env()
        self.client = client or HttpCentaurClient(self.config)

    def build_lane_attempt(
        self,
        *,
        agent: str,
        task: AgentTask,
        trigger: Any,
        decision: Any,
        evaluation: Any,
    ) -> AgentAttempt:
        harness = self._harness(agent)
        request = self._sandbox_request(
            agent=agent,
            task=task,
            trigger=trigger,
            decision=decision,
            evaluation=evaluation,
            harness=harness,
        )
        if harness not in set(self.config.centaur_allowed_harnesses):
            return self._failed_attempt(
                agent=agent,
                task=task,
                summary=f"Centaur harness {harness!r} is not allowed for this Mesh runtime.",
                risk_flags=["centaur_harness_not_allowed"],
                request=request,
                events=[],
            )
        try:
            result = self.client.run_sandbox(
                request,
                timeout_seconds=float(self.config.centaur_timeout_seconds),
            )
        except Exception as exc:  # noqa: BLE001 - proposal lanes fail closed into AgentAttempt
            return self._failed_attempt(
                agent=agent,
                task=task,
                summary=f"Centaur sandbox proposal failed closed: {exc}",
                risk_flags=["centaur_sandbox_unavailable"],
                request=request,
                events=[],
            )

        status = str(result.get("status") or "failed")
        if status not in {"completed", "failed", "cancelled"}:
            status = "failed"
        risk_flags = [str(flag) for flag in result.get("risk_flags", []) if str(flag)]
        if status != "completed" and "centaur_proposal_incomplete" not in risk_flags:
            risk_flags.append("centaur_proposal_incomplete")
        attempt = build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent=agent,
            adapter="centaur",
            status=status,
            summary=str(result.get("summary") or "Centaur sandbox returned proposal metadata."),
            changed_files=_list_of_dict_strings(result.get("changed_files")),
            test_results=_list_of_dicts(result.get("test_results")),
            risk_flags=risk_flags,
            recommended_action=str(result.get("recommended_action") or "human_review"),
            output={
                "sandbox_request": request,
                "execution_events": _list_of_dicts(result.get("events")),
                "tool_calls": _list_of_dicts(result.get("tool_calls")),
                "centaur_output": _safe_result_output(result.get("output")),
                "authority": _mesh_authority_record(),
            },
            observations_proposed=_list_of_dicts(result.get("observations_proposed")),
            claims_proposed=_list_of_dicts(result.get("claims_proposed")),
            procedures_proposed=_list_of_dicts(result.get("procedures_proposed")),
            citations=_list_of_dicts(result.get("citations")),
            contradictions_detected=_list_of_dicts(result.get("contradictions_detected")),
            memory_actions_requested=[str(item) for item in result.get("memory_actions_requested", []) if str(item)],
        )
        self._attach_thread(attempt, task=task, harness=harness, events=_list_of_dicts(result.get("events")), request=request)
        return attempt

    def _failed_attempt(
        self,
        *,
        agent: str,
        task: AgentTask,
        summary: str,
        risk_flags: list[str],
        request: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> AgentAttempt:
        attempt = build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent=agent,
            adapter="centaur",
            status="failed",
            summary=summary,
            risk_flags=risk_flags,
            recommended_action="human_review",
            output={
                "sandbox_request": request,
                "execution_events": events,
                "tool_calls": [],
                "authority": _mesh_authority_record(),
            },
        )
        self._attach_thread(
            attempt,
            task=task,
            harness=str(request.get("harness") or self.config.centaur_default_harness),
            events=events,
            request=request,
        )
        return attempt

    def _attach_thread(
        self,
        attempt: AgentAttempt,
        *,
        task: AgentTask,
        harness: str,
        events: list[dict[str, Any]],
        request: dict[str, Any],
    ) -> None:
        thread_events = [
            AgentAttemptThreadEvent(
                event_id=str(event.get("event_id") or f"centaur_event_{idx}"),
                thread_id=f"thread_{task.task_id}_{attempt.agent}_{attempt.adapter}",
                sequence=idx,
                event_type=str(event.get("event_type") or event.get("type") or "centaur_event"),
                recorded_at=str(event.get("recorded_at") or attempt.completed_at),
                payload=event,
                summary=event.get("summary") if isinstance(event.get("summary"), dict) else None,
                status=str(event.get("status")) if event.get("status") is not None else None,
            )
            for idx, event in enumerate(events, start=1)
        ]
        output = dict(attempt.output)
        thread = build_agent_attempt_thread(
            attempt_id=attempt.attempt_id,
            task_id=task.task_id,
            run_id=task.run_id,
            agent=attempt.agent,
            adapter=attempt.adapter,
            status=attempt.status,
            started_at=attempt.started_at,
            completed_at=attempt.completed_at,
            sandbox_ref=None,
            harness=harness,
            events=thread_events,
            request=request,
            tool_calls=_list_of_dicts(output.get("tool_calls")),
            output=_safe_result_output(output.get("centaur_output")),
            risk_flags=list(attempt.risk_flags),
            test_results=list(attempt.test_results),
            release_status=_release_status_from_output(output),
        )
        output["thread"] = thread.to_dict()
        attempt.output = output

    def _sandbox_request(
        self,
        *,
        agent: str,
        task: AgentTask,
        trigger: Any,
        decision: Any,
        evaluation: Any,
        harness: str,
    ) -> dict[str, Any]:
        return {
            "state_slice": "mesh.agent_sandbox_runtime.v1",
            "mode": "proposal_only",
            "thread_key": f"mesh:{task.run_id}:{task.task_id}:{agent}",
            "run_id": task.run_id,
            "task_id": task.task_id,
            "agent": agent,
            "harness": harness,
            "prompt_format": "anthropic_content" if harness == "claude-code" else "text",
            "allowed_paths": list(task.allowed_paths),
            "test_commands": list(task.test_commands),
            "kubernetes_scope": dict(task.kubernetes_scope),
            "context": {
                "trigger": _to_dict(trigger),
                "decision": _to_dict(decision),
                "evaluation": _to_dict(evaluation),
            },
            "authority": _mesh_authority_record(),
            "credential_policy": {
                "api_key_env_name": self.config.centaur_api_key_env_name,
                "raw_secret_in_sandbox": False,
                "sandbox_receives_placeholder_only": True,
            },
        }

    def _harness(self, agent: str) -> str:
        mapping = {
            "codex": "codex",
            "claudecode": "claude-code",
        }
        return mapping.get(agent, self.config.centaur_default_harness)


def _to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict"):
        try:
            result = value.to_dict()
            return result if isinstance(result, dict) else {}
        except Exception:  # noqa: BLE001 - prompt context should not make proposal collection fatal
            if is_dataclass(value):
                return asdict(value)
            return {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _prompt_from_request(request: dict[str, Any]) -> str:
    return (
        "MESH CENTAUR PROPOSAL REQUEST\n"
        "Mesh is authoritative for policy, approval, actuation, final run state, Merkle proof, and promotion.\n"
        "Return a bounded investigation proposal only.\n\n"
        f"{json.dumps(request, sort_keys=True, default=str)}"
    )


def _normalize_centaur_execution_result(
    *,
    execute_result: dict[str, Any],
    final: dict[str, Any],
    release: dict[str, Any] | None = None,
) -> dict[str, Any]:
    centaur_status = str(final.get("status") or execute_result.get("status") or "failed")
    status = "completed" if centaur_status == "completed" else ("cancelled" if centaur_status == "cancelled" else "failed")
    terminal_reason = str(final.get("terminal_reason") or "")
    result_text = str(final.get("result_text") or "")
    error_text = str(final.get("error_text") or "")
    summary = result_text.strip() or error_text.strip() or terminal_reason or "Centaur execution reached terminal state."
    events = [
        {
            "event_id": "centaur_execute_enqueued",
            "event_type": "centaur_execute_enqueued",
            "status": str(execute_result.get("status") or "accepted"),
            "payload": execute_result,
        },
        {
            "event_id": "centaur_execution_terminal",
            "event_type": "centaur_execution_terminal",
            "status": centaur_status,
            "payload": final,
            "summary": {"terminal_reason": terminal_reason},
        },
        {
            "event_id": "centaur_thread_released",
            "event_type": "centaur_thread_released",
            "status": "released" if (release or {}).get("released") else "not_released",
            "payload": dict(release or {}),
            "summary": {"released": bool((release or {}).get("released"))},
        },
    ]
    risk_flags: list[str] = []
    if status != "completed":
        risk_flags.append("centaur_execution_failed")
    return {
        "status": status,
        "summary": summary[:2000],
        "recommended_action": "human_review",
        "risk_flags": risk_flags,
        "events": events,
        "output": {
            "execution_id": final.get("execution_id") or execute_result.get("execution_id"),
            "thread_key": final.get("thread_key") or execute_result.get("thread_key"),
            "assignment_generation": final.get("assignment_generation") or execute_result.get("assignment_generation"),
            "terminal_reason": terminal_reason,
            "result_text": result_text,
            "error_text": error_text,
            "agent_thread_id": final.get("agent_thread_id"),
            "centaur_status": centaur_status,
            "release": dict(release or {}),
        },
        "citations": [
            {
                "source_type": "centaur_execution",
                "execution_id": final.get("execution_id") or execute_result.get("execution_id"),
            }
        ],
    }


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _list_of_dict_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _safe_result_output(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _release_status_from_output(output: dict[str, Any]) -> dict[str, Any]:
    centaur_output = output.get("centaur_output")
    if not isinstance(centaur_output, dict):
        return {}
    release = centaur_output.get("release")
    return dict(release) if isinstance(release, dict) else {}


def _mesh_authority_record() -> dict[str, Any]:
    return {
        "mesh_control_plane_authoritative": True,
        "centaur_control_plane_authoritative": False,
        "policy_approval_actuation_allowed": False,
        "final_run_state_owned_by_mesh": True,
    }
