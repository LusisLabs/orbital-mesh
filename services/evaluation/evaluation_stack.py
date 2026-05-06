"""Provider map for the native Mesh evaluation stack."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class EvaluationAccountConfig:
    credential_env: tuple[str, ...] = ()
    endpoint_env: tuple[str, ...] = ()
    project_env: tuple[str, ...] = ()
    account_env: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationIntegration:
    integration_id: str
    display_name: str
    best_for: str
    native_role: str
    native_artifacts: tuple[str, ...]
    optional_external_config: tuple[str, ...] = ()
    account_config: EvaluationAccountConfig = EvaluationAccountConfig()


EVALUATION_INTEGRATIONS: tuple[EvaluationIntegration, ...] = (
    EvaluationIntegration(
        integration_id="promptfoo",
        display_name="Promptfoo",
        best_for="prompt assertions, regression fixtures, and legacy prompt-eval compatibility",
        native_role="contract assertion lane",
        native_artifacts=("contract_checks", "trajectory_quality", "task_trace.mesh_eval.promptfoo_role"),
        optional_external_config=("MESH_PROMPTFOO_COMMAND",),
        account_config=EvaluationAccountConfig(
            credential_env=("MESH_EVAL_PROMPTFOO_API_KEY", "PROMPTFOO_API_KEY"),
            endpoint_env=("MESH_EVAL_PROMPTFOO_ENDPOINT", "PROMPTFOO_REMOTE_API_BASE_URL"),
            project_env=("MESH_EVAL_PROMPTFOO_PROJECT",),
            account_env=("MESH_EVAL_PROMPTFOO_ACCOUNT",),
        ),
    ),
    EvaluationIntegration(
        integration_id="langsmith",
        display_name="LangSmith",
        best_for="LangChain tracing, prompt versioning, and structured evals",
        native_role="trace and experiment projection lane",
        native_artifacts=("task_trace", "run_events", "sre_judgment"),
        account_config=EvaluationAccountConfig(
            credential_env=("MESH_EVAL_LANGSMITH_API_KEY", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"),
            endpoint_env=("MESH_EVAL_LANGSMITH_ENDPOINT", "LANGSMITH_ENDPOINT"),
            project_env=("MESH_EVAL_LANGSMITH_PROJECT", "LANGSMITH_PROJECT", "LANGCHAIN_PROJECT"),
            account_env=("MESH_EVAL_LANGSMITH_ACCOUNT",),
        ),
    ),
    EvaluationIntegration(
        integration_id="deepeval",
        display_name="DeepEval / Confident AI",
        best_for="pytest-style evaluation, custom metrics, and CI-friendly tests",
        native_role="code-defined metric lane",
        native_artifacts=("contract_checks", "trajectory_quality", "behavioral_scores"),
        optional_external_config=("PYTEST_ADDOPTS",),
        account_config=EvaluationAccountConfig(
            credential_env=("MESH_EVAL_DEEPEVAL_API_KEY", "DEEPEVAL_API_KEY", "CONFIDENT_API_KEY", "CONFIDENT_AI_API_KEY"),
            endpoint_env=("MESH_EVAL_DEEPEVAL_ENDPOINT", "CONFIDENT_API_BASE_URL"),
            project_env=("MESH_EVAL_DEEPEVAL_PROJECT", "CONFIDENT_PROJECT"),
            account_env=("MESH_EVAL_DEEPEVAL_ACCOUNT",),
        ),
    ),
    EvaluationIntegration(
        integration_id="ragas",
        display_name="RAGAS",
        best_for="RAG retrieval quality, answer faithfulness, and context precision checks",
        native_role="retrieval quality lane",
        native_artifacts=("task_trace.context.evidence_pack", "task_trace.context.reasoning_bank_packet", "evidence_sufficiency"),
        account_config=EvaluationAccountConfig(
            credential_env=("MESH_EVAL_RAGAS_API_KEY", "RAGAS_API_KEY"),
            endpoint_env=("MESH_EVAL_RAGAS_ENDPOINT", "RAGAS_ENDPOINT"),
            project_env=("MESH_EVAL_RAGAS_PROJECT",),
            account_env=("MESH_EVAL_RAGAS_ACCOUNT",),
        ),
    ),
    EvaluationIntegration(
        integration_id="trulens",
        display_name="TruLens",
        best_for="feedback-function evaluation and RAG relevance checks",
        native_role="feedback-function lane",
        native_artifacts=("evidence_sufficiency", "verifier", "task_trace.context"),
        account_config=EvaluationAccountConfig(
            credential_env=("MESH_EVAL_TRULENS_API_KEY", "TRULENS_API_KEY"),
            endpoint_env=("MESH_EVAL_TRULENS_ENDPOINT", "TRULENS_ENDPOINT"),
            project_env=("MESH_EVAL_TRULENS_PROJECT",),
            account_env=("MESH_EVAL_TRULENS_ACCOUNT",),
        ),
    ),
    EvaluationIntegration(
        integration_id="braintrust",
        display_name="Braintrust",
        best_for="production monitoring, shared experiments, and evaluation governance",
        native_role="governance export lane",
        native_artifacts=("evaluation_id", "decision_id", "stage_results", "blocker_analysis"),
        account_config=EvaluationAccountConfig(
            credential_env=("MESH_EVAL_BRAINTRUST_API_KEY", "BRAINTRUST_API_KEY"),
            endpoint_env=("MESH_EVAL_BRAINTRUST_ENDPOINT", "BRAINTRUST_API_URL"),
            project_env=("MESH_EVAL_BRAINTRUST_PROJECT", "BRAINTRUST_PROJECT"),
            account_env=("MESH_EVAL_BRAINTRUST_ACCOUNT", "BRAINTRUST_ORG_NAME"),
        ),
    ),
    EvaluationIntegration(
        integration_id="opik",
        display_name="Opik",
        best_for="open-source tracing, prompt versioning, and CI-friendly tests",
        native_role="open trace export lane",
        native_artifacts=("task_trace", "phoenix_spans", "trajectory_quality"),
        account_config=EvaluationAccountConfig(
            credential_env=("MESH_EVAL_OPIK_API_KEY", "OPIK_API_KEY"),
            endpoint_env=("MESH_EVAL_OPIK_ENDPOINT", "OPIK_URL"),
            project_env=("MESH_EVAL_OPIK_PROJECT", "OPIK_PROJECT_NAME"),
            account_env=("MESH_EVAL_OPIK_ACCOUNT", "OPIK_WORKSPACE"),
        ),
    ),
    EvaluationIntegration(
        integration_id="weave",
        display_name="Weave",
        best_for="Weights & Biases eval dashboards, versioning, and experiment comparison",
        native_role="dashboard export lane",
        native_artifacts=("trajectory_quality", "behavioral_scores", "verifier"),
        account_config=EvaluationAccountConfig(
            credential_env=("MESH_EVAL_WEAVE_API_KEY", "WEAVE_API_KEY", "WANDB_API_KEY"),
            endpoint_env=("MESH_EVAL_WEAVE_ENDPOINT", "WANDB_BASE_URL"),
            project_env=("MESH_EVAL_WEAVE_PROJECT", "WANDB_PROJECT"),
            account_env=("MESH_EVAL_WEAVE_ACCOUNT", "WANDB_ENTITY"),
        ),
    ),
    EvaluationIntegration(
        integration_id="maxim_ai",
        display_name="Maxim AI",
        best_for="prompt building, simulation, and continuous eval workflows",
        native_role="simulation and prompt-workflow lane",
        native_artifacts=("task_trace.context.scenario_analysis", "trajectory_quality", "verifier"),
        account_config=EvaluationAccountConfig(
            credential_env=("MESH_EVAL_MAXIM_AI_API_KEY", "MAXIM_API_KEY", "MAXIM_AI_API_KEY"),
            endpoint_env=("MESH_EVAL_MAXIM_AI_ENDPOINT", "MAXIM_API_BASE_URL"),
            project_env=("MESH_EVAL_MAXIM_AI_PROJECT", "MAXIM_PROJECT"),
            account_env=("MESH_EVAL_MAXIM_AI_ACCOUNT",),
        ),
    ),
    EvaluationIntegration(
        integration_id="zenml",
        display_name="ZenML",
        best_for="reusable evaluation pipelines with lineage and governance",
        native_role="pipeline lineage lane",
        native_artifacts=("task_trace", "stage_results", "mesh_eval"),
        account_config=EvaluationAccountConfig(
            credential_env=("MESH_EVAL_ZENML_API_KEY", "ZENML_STORE_API_KEY"),
            endpoint_env=("MESH_EVAL_ZENML_ENDPOINT", "ZENML_STORE_URL"),
            project_env=("MESH_EVAL_ZENML_PROJECT",),
            account_env=("MESH_EVAL_ZENML_ACCOUNT",),
        ),
    ),
    EvaluationIntegration(
        integration_id="arize_phoenix",
        display_name="Arize Phoenix",
        best_for="local-first debugging, hallucination checks, and RAG analysis",
        native_role="span and RAG-debug lane",
        native_artifacts=("phoenix_spans", "task_trace.context.evidence_pack", "verifier"),
        account_config=EvaluationAccountConfig(
            credential_env=("MESH_EVAL_ARIZE_PHOENIX_API_KEY", "PHOENIX_API_KEY", "ARIZE_API_KEY"),
            endpoint_env=("MESH_EVAL_ARIZE_PHOENIX_ENDPOINT", "PHOENIX_COLLECTOR_ENDPOINT", "PHOENIX_ENDPOINT"),
            project_env=("MESH_EVAL_ARIZE_PHOENIX_PROJECT", "PHOENIX_PROJECT_NAME", "ARIZE_SPACE_KEY"),
            account_env=("MESH_EVAL_ARIZE_PHOENIX_ACCOUNT", "ARIZE_ORG_KEY"),
        ),
    ),
)

EVALUATION_INTEGRATION_IDS: tuple[str, ...] = tuple(item.integration_id for item in EVALUATION_INTEGRATIONS)
_INTEGRATION_BY_ID = {item.integration_id: item for item in EVALUATION_INTEGRATIONS}
_LANE_ALIASES = {
    "arize": "arize_phoenix",
    "phoenix": "arize_phoenix",
    "arize_phoenix": "arize_phoenix",
    "confident": "deepeval",
    "confident_ai": "deepeval",
    "deep_eval": "deepeval",
    "maxim": "maxim_ai",
    "maxim_ai": "maxim_ai",
}


def normalize_integration_lanes(raw: str | None) -> tuple[str, ...]:
    value = (raw or "all").strip().lower()
    if value in {"", "all", "*"}:
        return EVALUATION_INTEGRATION_IDS
    lanes = []
    for item in value.split(","):
        lane = _normalize_lane_id(item)
        if lane:
            lanes.append(lane)
    return tuple(dict.fromkeys(lane for lane in lanes if lane in _INTEGRATION_BY_ID))


def _normalize_lane_id(raw: str) -> str:
    lane = raw.strip().lower().replace("-", "_").replace(" ", "_").replace("/", "_")
    return _LANE_ALIASES.get(lane, lane)


def build_evaluation_stack(
    *,
    requested_lanes: tuple[str, ...],
    trace: dict[str, Any],
    stage_results: dict[str, Any],
    phoenix_spans: list[dict[str, Any]] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    lanes = requested_lanes or EVALUATION_INTEGRATION_IDS
    env = os.environ if environ is None else environ
    integrations = []
    for integration_id in lanes:
        integration = _INTEGRATION_BY_ID.get(integration_id)
        if integration is None:
            continue
        integrations.append(
            {
                **asdict(integration),
                "authority": "advisory",
                "status": _integration_status(integration, trace, stage_results, phoenix_spans),
                "account_connection": _account_connection(integration, env),
            }
        )
    return {
        "version": "mesh_evaluation_stack_v1",
        "authority": "mesh_native",
        "native_gates": (
            "schema_validation",
            "policy_validation",
            "contract_checks",
            "trajectory_quality",
            "verifier",
            "evidence_sufficiency",
            "remediation_safety",
        ),
        "external_authority": "disabled",
        "integrations": integrations,
    }


def _account_connection(integration: EvaluationIntegration, env: Mapping[str, str]) -> dict[str, Any]:
    config = integration.account_config
    credential_var = _first_configured(config.credential_env, env)
    endpoint_var = _first_configured(config.endpoint_env, env)
    project_var = _first_configured(config.project_env, env)
    account_var = _first_configured(config.account_env, env)
    command_var = _first_configured(integration.optional_external_config, env)
    configured_vars = tuple(
        item for item in (credential_var, endpoint_var, project_var, account_var, command_var) if item
    )
    return {
        "status": "connected" if configured_vars else "not_configured",
        "credential_configured": credential_var is not None,
        "endpoint_configured": endpoint_var is not None,
        "project_configured": project_var is not None,
        "account_configured": account_var is not None,
        "command_configured": command_var is not None,
        "configured_env": configured_vars,
        "account_ref": _safe_ref(account_var, env) or _safe_ref(project_var, env),
        "outbound_export_enabled": _export_enabled(integration.integration_id, env),
        "notes": (
            ["credentials are redacted; Mesh records configuration state only"]
            if configured_vars
            else ["set Mesh-owned account variables or existing vendor variables to connect this lane"]
        ),
    }


def _first_configured(names: tuple[str, ...], env: Mapping[str, str]) -> str | None:
    for name in names:
        if env.get(name, "").strip():
            return name
    return None


def _safe_ref(name: str | None, env: Mapping[str, str]) -> str | None:
    if name is None:
        return None
    value = env.get(name, "").strip()
    if not value:
        return None
    return value if len(value) <= 80 else f"{value[:77]}..."


def _export_enabled(integration_id: str, env: Mapping[str, str]) -> bool:
    lane_name = f"MESH_EVAL_{integration_id.upper()}_EXPORT_ENABLED"
    return _truthy(env.get(lane_name)) or _truthy(env.get("MESH_EVAL_EXPORT_ENABLED"))


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _integration_status(
    integration: EvaluationIntegration,
    trace: dict[str, Any],
    stage_results: dict[str, Any],
    phoenix_spans: list[dict[str, Any]] | None,
) -> str:
    if integration.integration_id == "arize_phoenix" and phoenix_spans:
        return "native_artifacts_ready"
    if integration.integration_id in {"ragas", "trulens", "arize_phoenix"} and _has_rag_context(trace):
        return "native_artifacts_ready"
    if integration.integration_id == "maxim_ai" and _has_scenario_context(trace):
        return "native_artifacts_ready"
    if integration.integration_id in {"promptfoo", "deepeval", "weave"} and stage_results.get("trajectory_quality"):
        return "native_artifacts_ready"
    if integration.integration_id in {"langsmith", "opik", "zenml"} and trace:
        return "native_artifacts_ready"
    if integration.integration_id == "braintrust" and stage_results.get("blocker_analysis"):
        return "native_artifacts_ready"
    return "declared"


def _has_rag_context(trace: dict[str, Any]) -> bool:
    context = trace.get("context") if isinstance(trace.get("context"), dict) else {}
    return bool(context.get("evidence_pack") or context.get("reasoning_bank_packet"))


def _has_scenario_context(trace: dict[str, Any]) -> bool:
    context = trace.get("context") if isinstance(trace.get("context"), dict) else {}
    return bool(context.get("scenario_analysis"))
