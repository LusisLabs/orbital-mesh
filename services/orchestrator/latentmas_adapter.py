from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from shared.mesh_runtime import Decision, EvaluationResult, RuntimeConfig, Trigger
from shared.mesh_runtime.agent_workers import build_agent_attempt
from shared.mesh_runtime.control_plane_models import AgentAttempt, AgentTask


class LatentMasAdapter:
    def __init__(self, config: RuntimeConfig):
        self.config = config

    def build_attempt(
        self,
        *,
        task: AgentTask,
        trigger: Trigger,
        decision: Decision,
        evaluation: EvaluationResult,
    ) -> AgentAttempt:
        if not self.config.latentmas_url:
            return self._failed_attempt(task, "enabled but MESH_LATENTMAS_URL is not configured")
        health_error = self._health_error()
        if health_error is not None:
            return self._failed_attempt(task, health_error)

        payload = {
            "run_id": task.run_id,
            "task": {
                "task_id": task.task_id,
                "kind": task.kind,
                "allowed_paths": task.allowed_paths,
                "test_commands": task.test_commands,
                "kubernetes_scope": task.kubernetes_scope,
            },
            "trigger": trigger.to_dict(),
            "decision": decision.to_dict(),
            "evaluation": evaluation.to_dict(),
            "options": {
                "model_name": self.config.latentmas_model_name,
                "device": self.config.latentmas_device,
                "prompt_mode": self.config.latentmas_prompt_mode,
                "latent_steps": self.config.latentmas_latent_steps,
                "max_new_tokens": self.config.latentmas_max_new_tokens,
                "use_vllm": self.config.latentmas_use_vllm,
            },
        }
        request = Request(
            f"{self.config.latentmas_url.rstrip('/')}/infer",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        raw = ""
        try:
            with urlopen(request, timeout=self.config.latentmas_timeout_seconds) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = self._http_error_detail(exc)
            return self._failed_attempt(task, f"LatentMAS sidecar error: {detail}")
        except (URLError, TimeoutError, OSError) as exc:
            return self._failed_attempt(task, f"LatentMAS sidecar unavailable: {exc}")

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            capped = self._cap_text(raw)
            return build_agent_attempt(
                task_id=task.task_id,
                run_id=task.run_id,
                agent="latentmas",
                adapter="latentmas_http",
                status="failed",
                summary=capped or "LatentMAS returned an unparseable response.",
                risk_flags=["latentmas_output_unparseable"],
                recommended_action="human_review",
                output={"raw_response": capped},
            )

        if not isinstance(result, dict):
            return build_agent_attempt(
                task_id=task.task_id,
                run_id=task.run_id,
                agent="latentmas",
                adapter="latentmas_http",
                status="failed",
                summary="LatentMAS returned a non-object response.",
                risk_flags=["latentmas_output_unparseable"],
                recommended_action="human_review",
                output={"raw_response": self._cap_value(result)},
            )

        risk_flags = _string_list(result.get("risk_flags"))
        status = str(result.get("status") or "completed")
        summary = self._cap_text(str(result.get("summary") or "LatentMAS inference completed."))
        output = {
            "confidence": result.get("confidence"),
            "raw_prediction": self._cap_value(result.get("raw_prediction")),
            "agent_traces": self._cap_value(result.get("agent_traces")),
            "metrics": self._cap_value(result.get("metrics")),
        }
        if result.get("error"):
            output["error"] = self._cap_value(result.get("error"))

        return build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent="latentmas",
            adapter="latentmas_http",
            status=status,
            summary=summary,
            risk_flags=risk_flags,
            recommended_action=str(result.get("recommended_action") or "human_review"),
            output={key: value for key, value in output.items() if value is not None},
        )

    def _failed_attempt(self, task: AgentTask, detail: str) -> AgentAttempt:
        return build_agent_attempt(
            task_id=task.task_id,
            run_id=task.run_id,
            agent="latentmas",
            adapter="latentmas_http",
            status="failed",
            summary=self._cap_text(detail),
            risk_flags=["latentmas_unavailable"],
            recommended_action="human_review",
            output={"error": self._cap_text(detail)},
        )

    def _health_error(self) -> str | None:
        request = Request(
            f"{self.config.latentmas_url.rstrip('/')}/health",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            with urlopen(request, timeout=min(self.config.latentmas_timeout_seconds, 5.0)) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            return f"LatentMAS sidecar healthcheck failed: {self._http_error_detail(exc)}"
        except (URLError, TimeoutError, OSError) as exc:
            return f"LatentMAS sidecar unavailable: {exc}"

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("ready", True):
            return None
        detail = str(payload.get("detail") or "sidecar reported not ready")
        return f"LatentMAS sidecar not ready: {detail}"

    def _http_error_detail(self, exc: HTTPError) -> str:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except OSError:
            body = ""
        if body:
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
            if isinstance(payload, dict) and payload.get("error"):
                return f"HTTP {exc.code}: {payload['error']}"
            return f"HTTP {exc.code}: {self._cap_text(body)}"
        return str(exc)

    def _cap_text(self, value: str) -> str:
        cap = max(0, int(self.config.latentmas_max_artifact_chars))
        if cap == 0 or len(value) <= cap:
            return value
        return value[:cap] + "\n[truncated]"

    def _cap_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._cap_text(value)
        if isinstance(value, list):
            return [self._cap_value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): self._cap_value(item) for key, item in value.items()}
        return value


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
