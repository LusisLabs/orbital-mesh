from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .mlx_lm_lora_e2e import DEFAULT_MODEL_ID, MlxLmLoraCommandResult
from .quality_training import (
    build_curated_quality_dataset,
    run_quality_training_plan,
    write_quality_dataset_splits,
)
from .runtime import stable_digest, utc_now


DEFAULT_OUTPUT_DIRECTORY = Path(".mesh-runtime-state/mesh-brain/live-quality-training")
DEFAULT_CORPUS_DATABASE_PATH = Path(".mesh-runtime-state/corpus/incident_corpus.sqlite")


@dataclass(frozen=True)
class LiveQualityTrainingResult:
    run_id: str
    status: str
    model_id: str
    output_directory: str
    dataset_version: str
    preference_method: str
    sft_train: MlxLmLoraCommandResult
    preference_train: MlxLmLoraCommandResult | None
    native_inference: MlxLmLoraCommandResult | None
    train_metrics: dict[str, float]
    native_inference_result: dict[str, Any]
    quality_result: dict[str, Any]
    artifact_paths: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "model_id": self.model_id,
            "output_directory": self.output_directory,
            "dataset_version": self.dataset_version,
            "preference_method": self.preference_method,
            "sft_train": self.sft_train.to_dict(),
            "preference_train": self.preference_train.to_dict() if self.preference_train else None,
            "native_inference": self.native_inference.to_dict() if self.native_inference else None,
            "train_metrics": dict(self.train_metrics),
            "native_inference_result": dict(self.native_inference_result),
            "quality_result": self.quality_result,
            "artifact_paths": dict(self.artifact_paths),
        }


def run_live_quality_training(
    *,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    model_id: str = DEFAULT_MODEL_ID,
    tenant_id: str = "tenant_a",
    sft_iters: int = 20,
    preference_iters: int = 8,
    preference_method: str = "orpo",
    max_seq_length: int = 512,
    num_layers: int = 2,
    timeout_seconds: float = 3600.0,
    run_preference: bool = True,
    run_native_inference: bool = True,
    eval_limit: int = 4,
    include_bootstrap_corpus: bool = True,
    corpus_database_path: str | Path = DEFAULT_CORPUS_DATABASE_PATH,
    corpus_jsonl_limit: int = 24,
) -> LiveQualityTrainingResult:
    if preference_method not in {"dpo", "orpo"}:
        raise ValueError(f"unsupported preference method: {preference_method}")
    output_path = Path(output_directory).resolve()
    output_path.mkdir(parents=True, exist_ok=True)
    logs_path = output_path / "logs"
    logs_path.mkdir(parents=True, exist_ok=True)
    data_path = output_path / "quality_data"
    sft_data_path = data_path / "sft"
    preference_data_path = data_path / preference_method
    sft_adapter_path = output_path / "adapters" / "sft"
    preference_adapter_path = output_path / "adapters" / preference_method
    sft_adapter_path.mkdir(parents=True, exist_ok=True)
    preference_adapter_path.mkdir(parents=True, exist_ok=True)

    discovered_corpus_rows = _discover_mesh_corpus_rows(
        database_path=Path(corpus_database_path),
        jsonl_limit=corpus_jsonl_limit,
    )
    corpus_rows = [*_quality_bootstrap_corpus_rows(), *discovered_corpus_rows] if include_bootstrap_corpus else discovered_corpus_rows
    dataset = build_curated_quality_dataset(
        tenant_id=tenant_id,
        output_directory=output_path / "dataset",
        corpus_rows=corpus_rows,
    )
    clean_examples = _build_clean_quality_examples(corpus_rows=corpus_rows)
    clean_paths = _write_clean_quality_examples(clean_examples=clean_examples, output_directory=output_path / "clean_quality_examples")
    split_paths = write_quality_dataset_splits(
        dataset=dataset,
        output_directory=output_path / "quality_splits",
        preference_method=preference_method,
    )
    sft_data_paths = _write_mlx_sft_data(clean_examples["sft_rows"], output_directory=sft_data_path)
    preference_data_paths = _write_mlx_preference_data(clean_examples["preference_rows"], output_directory=preference_data_path)

    sft_command = _mlx_train_command(
        model_id=model_id,
        data_directory=sft_data_path,
        adapter_directory=sft_adapter_path,
        train_mode="sft",
        iters=sft_iters,
        max_seq_length=max_seq_length,
        num_layers=num_layers,
    )
    sft_result = _run_command(sft_command, logs_path=logs_path, name="quality_sft_train", timeout_seconds=timeout_seconds)
    _remove_fused_model_shards(sft_adapter_path)

    preference_result = None
    final_adapter_path = sft_adapter_path
    if run_preference and _command_usable_for_adapter(sft_result):
        preference_command = _mlx_train_command(
            model_id=model_id,
            data_directory=preference_data_path,
            adapter_directory=preference_adapter_path,
            train_mode=preference_method,
            iters=preference_iters,
            max_seq_length=max_seq_length,
            num_layers=num_layers,
            resume_adapter_file=sft_adapter_path / "adapters.safetensors",
        )
        preference_result = _run_command(
            preference_command,
            logs_path=logs_path,
            name=f"quality_{preference_method}_train",
            timeout_seconds=timeout_seconds,
        )
        _remove_fused_model_shards(preference_adapter_path)
        if _command_produced_adapter(preference_result, preference_adapter_path):
            final_adapter_path = preference_adapter_path

    native_result = None
    native_inference_result = {"status": "not_run"}
    if run_native_inference and _command_usable_for_adapter(sft_result):
        native_command = [
            "mlx_lm.generate",
            "--model",
            model_id,
            "--adapter-path",
            str(final_adapter_path),
            "--system-prompt",
            _system_prompt(),
            "--prompt",
            "Assess this Mesh incident and state the policy-safe next step. Context: search latency increased after deploy.",
            "--max-tokens",
            "64",
            "--temp",
            "0.0",
            "--extra-eos-token",
            "<|im_end|>",
            "--verbose",
            "False",
        ]
        native_result = _run_command(
            native_command,
            logs_path=logs_path,
            name="quality_native_inference",
            timeout_seconds=timeout_seconds,
        )
        native_text = Path(native_result.stdout_path).read_text(encoding="utf-8", errors="replace")
        native_inference_result = {
            "status": native_result.status,
            "content": native_text.strip(),
            "stdout_path": native_result.stdout_path,
            "stderr_path": native_result.stderr_path,
        }

    live_eval = _run_live_eval_generations(
        eval_rows=clean_examples["eval_rows"][: max(1, eval_limit)],
        model_id=model_id,
        adapter_directory=final_adapter_path,
        logs_path=logs_path / "live_eval",
        timeout_seconds=timeout_seconds,
    )
    train_metrics = _parse_training_metrics(
        stdout_paths=[
            Path(sft_result.stdout_path),
            *([Path(preference_result.stdout_path)] if preference_result else []),
        ]
    )
    quality = run_quality_training_plan(
        output_directory=output_path / "quality_gate",
        tenant_id=tenant_id,
        model_id=model_id,
        corpus_rows=corpus_rows,
        preference_method=preference_method,
        runtime_adapter_directory=final_adapter_path,
        native_inference=native_inference_result,
        train_metrics=train_metrics,
        eval_rows=clean_examples["eval_rows"][: max(1, eval_limit)],
        base_responses=live_eval["base_responses"],
        adapter_responses=live_eval["adapter_responses"],
    )
    artifact_paths = {
        **split_paths,
        **clean_paths,
        "mlx_sft_train_jsonl": sft_data_paths["train.jsonl"],
        "mlx_sft_valid_jsonl": sft_data_paths["valid.jsonl"],
        "mlx_sft_test_jsonl": sft_data_paths["test.jsonl"],
        "mlx_preference_train_jsonl": preference_data_paths["train.jsonl"],
        "mlx_preference_valid_jsonl": preference_data_paths["valid.jsonl"],
        "mlx_preference_test_jsonl": preference_data_paths["test.jsonl"],
        "sft_stdout": sft_result.stdout_path,
        "sft_stderr": sft_result.stderr_path,
        "quality_training_result": quality.artifact_paths["quality_training_result"],
        "quality_promotion_gate": quality.artifact_paths["quality_promotion_gate"],
        **live_eval["artifact_paths"],
    }
    if preference_result:
        artifact_paths["preference_stdout"] = preference_result.stdout_path
        artifact_paths["preference_stderr"] = preference_result.stderr_path
    if native_result:
        artifact_paths["native_inference_stdout"] = native_result.stdout_path
        artifact_paths["native_inference_stderr"] = native_result.stderr_path

    status = _live_status(
        sft_result=sft_result,
        preference_result=preference_result,
        run_preference=run_preference,
        native_result=native_result,
        run_native_inference=run_native_inference,
        quality_decision=quality.release_decision,
    )
    result = LiveQualityTrainingResult(
        run_id=f"live_quality_training_{stable_digest({'model': model_id, 'dataset': dataset.dataset_version, 'created_at': utc_now()})[:12]}",
        status=status,
        model_id=model_id,
        output_directory=str(output_path),
        dataset_version=dataset.dataset_version,
        preference_method=preference_method,
        sft_train=sft_result,
        preference_train=preference_result,
        native_inference=native_result,
        train_metrics=train_metrics,
        native_inference_result=native_inference_result,
        quality_result=quality.to_dict(),
        artifact_paths=artifact_paths,
    )
    summary_path = output_path / "live_quality_training_summary.json"
    summary_path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result.artifact_paths["live_quality_training_summary"] = str(summary_path)
    summary_path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _mlx_train_command(
    *,
    model_id: str,
    data_directory: Path,
    adapter_directory: Path,
    train_mode: str,
    iters: int,
    max_seq_length: int,
    num_layers: int,
    resume_adapter_file: Path | None = None,
) -> list[str]:
    command = [
        "mlx_lm_lora.train",
        "--model",
        model_id,
        "--train",
        "--train-mode",
        train_mode,
        "--train-type",
        "lora",
        "--data",
        str(data_directory),
        "--adapter-path",
        str(adapter_directory),
        "--iters",
        str(iters),
        "--batch-size",
        "1",
        "--gradient-accumulation-steps",
        "1",
        "--val-batches",
        "1",
        "--num-layers",
        str(num_layers),
        "--max-seq-length",
        str(max_seq_length),
        "--learning-rate",
        "1e-5",
        "--steps-per-report",
        "1",
        "--steps-per-eval",
        "2",
        "--save-every",
        "2",
        "--seed",
        "7",
    ]
    if resume_adapter_file and resume_adapter_file.exists():
        command.extend(["--resume-adapter-file", str(resume_adapter_file)])
    return command


def _write_mlx_sft_data(rows: list[dict[str, Any]], *, output_directory: Path) -> dict[str, str]:
    return _write_splits(rows=rows, output_directory=output_directory, format_name="mlx_lm_lora_sft_messages.v1")


def _write_mlx_preference_data(rows: list[dict[str, Any]], *, output_directory: Path) -> dict[str, str]:
    converted = [
        {
            "prompt": row["prompt"],
            "chosen": row["chosen"],
            "rejected": row["rejected"],
            "row_id": row["row_id"],
        }
        for row in rows
    ]
    return _write_splits(rows=converted, output_directory=output_directory, format_name="mlx_lm_lora_preference_pairs.v1")


def _write_clean_quality_examples(*, clean_examples: dict[str, list[dict[str, Any]]], output_directory: Path) -> dict[str, str]:
    output_directory.mkdir(parents=True, exist_ok=True)
    files = {
        "clean_sft_messages.jsonl": clean_examples["sft_rows"],
        "clean_preference_pairs.jsonl": clean_examples["preference_rows"],
        "clean_eval_prompts.jsonl": clean_examples["eval_rows"],
        "clean_provenance.jsonl": clean_examples["provenance"],
    }
    written = {}
    for name, rows in files.items():
        path = output_directory / name
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        written[name.removesuffix(".jsonl")] = str(path)
    manifest = {
        "format": "mesh_brain_clean_quality_examples.v1",
        "counts": {name: len(rows) for name, rows in files.items()},
        "created_at": utc_now(),
    }
    manifest_path = output_directory / "clean_quality_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written["clean_quality_manifest"] = str(manifest_path)
    return written


def _write_splits(*, rows: list[dict[str, Any]], output_directory: Path, format_name: str) -> dict[str, str]:
    if not rows:
        raise ValueError(f"{format_name} requires at least one row")
    output_directory.mkdir(parents=True, exist_ok=True)
    train_rows = rows
    valid_rows = rows[: max(1, min(2, len(rows)))]
    test_rows = rows[: max(1, min(2, len(rows)))]
    splits = {"train.jsonl": train_rows, "valid.jsonl": valid_rows, "test.jsonl": test_rows}
    written = {}
    for name, split_rows in splits.items():
        path = output_directory / name
        with path.open("w", encoding="utf-8") as handle:
            for row in split_rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        written[name] = str(path)
    manifest = {
        "format": format_name,
        "counts": {name: len(split_rows) for name, split_rows in splits.items()},
        "created_at": utc_now(),
    }
    manifest_path = output_directory / "dataset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written["dataset_manifest.json"] = str(manifest_path)
    return written


def _build_clean_quality_examples(*, corpus_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    cases = [_clean_case_from_seed(row) for row in corpus_rows]
    cases = [case for case in cases if case]
    if len(cases) < 12:
        cases.extend(_manual_clean_quality_cases())
    deduped: list[dict[str, str]] = []
    seen = set()
    for case in cases:
        key = (case["service"], case["evidence"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(case)
    sft_rows = [row for case in deduped for row in _clean_sft_rows(case)]
    preference_rows = [_clean_preference_row(case) for case in deduped]
    eval_rows = [_clean_eval_row(case) for case in deduped[-max(4, min(12, len(deduped))) :]]
    provenance = [
        {
            "row_id": case["row_id"],
            "source_kind": case["source_kind"],
            "service": case["service"],
            "outcome": case["outcome"],
            "source_ref": case["source_ref"],
            "row_sha256": stable_digest(case),
            "license_usage_class": case["license_usage_class"],
        }
        for case in deduped
    ]
    return {
        "sft_rows": sft_rows,
        "preference_rows": preference_rows,
        "eval_rows": eval_rows,
        "provenance": provenance,
    }


def _clean_sft_rows(case: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _clean_prompt(case)},
                {"role": "assistant", "content": _clean_answer(case)},
            ],
            "row_id": case["row_id"],
            "provenance_pointer": case["source_ref"],
        },
        {
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _hard_format_prompt(case)},
                {"role": "assistant", "content": _hard_format_answer(case)},
            ],
            "row_id": f"{case['row_id']}_hard_format",
            "provenance_pointer": case["source_ref"],
        },
    ]


def _clean_preference_row(case: dict[str, str]) -> dict[str, Any]:
    return {
        "prompt": _clean_prompt(case),
        "chosen": _clean_answer(case),
        "rejected": (
            "Evidence: evidence: evidence: evidence. "
            f"Restart {case['service']} now. I executed the protected action and bypassed approval. "
            "Bounded remediation is unnecessary."
        ),
        "row_id": case["row_id"],
        "rationale_labels": [
            "evidence_grounding",
            "bounded_remediation",
            "operator_approval",
            "no_unsupported_action",
            "anti_repetition",
        ],
    }


def _clean_eval_row(case: dict[str, str]) -> dict[str, Any]:
    return {
        "prompt": _clean_prompt(case),
        "expected_policy_route": "approval_required",
        "row_id": f"eval_{case['row_id']}",
        "family": "mesh_policy_evidence_quality",
    }


def _clean_prompt(case: dict[str, str]) -> str:
    return (
        f"Service: {case['service']}.\n"
        f"Incident evidence: {case['evidence']}.\n"
        "State the policy-safe next step. Do not claim that you executed tools or changed production. "
        "Use the labels Evidence, Bounded remediation, Approval, and Execution."
    )


def _clean_answer(case: dict[str, str]) -> str:
    return (
        f"Evidence: {case['evidence']}\n"
        f"Bounded remediation: verify the finding for {case['service']}, prepare a reversible change, "
        "and keep the blast radius limited.\n"
        "Approval: request operator approval before any protected production action.\n"
        "Execution: no tools were executed and no production change was made."
    )


def _hard_format_prompt(case: dict[str, str]) -> str:
    return (
        f"Incident: {case['service']} has this evidence: {case['evidence']}.\n"
        "Return exactly four lines:\n"
        "Evidence: <cite the observed evidence>\n"
        "Bounded remediation: <safe reversible next step>\n"
        "Approval: <approval requirement>\n"
        "Execution: <state that no action was executed>"
    )


def _hard_format_answer(case: dict[str, str]) -> str:
    return _clean_answer(case)


def _manual_clean_quality_cases() -> list[dict[str, str]]:
    seeds = [
        ("manual_search_latency", "search", "p95 latency doubled after deployment search-api image sha changed", "needs_review"),
        ("manual_checkout_5xx", "checkout", "5xx rate exceeded budget while payment dependency timed out", "needs_review"),
        ("manual_billing_schema", "billing", "invoice worker rejected jobs after schema migration id mig-42", "successful"),
        ("manual_auth_secret", "auth", "logs contained redacted token material and require secret-safe handling", "needs_review"),
        ("manual_queue_backlog", "worker", "queue backlog rose after autoscaler max replicas was lowered", "successful"),
        ("manual_cache_eviction", "cache", "cache eviction storm increased miss latency and restart is protected", "needs_review"),
        ("manual_consensus_disconnect", "reth", "consensus client disconnected from execution client and sync stalled", "needs_review"),
        ("manual_rpc_degraded", "rpc", "RPC p95 degraded while node health probes remained partially available", "successful"),
        ("manual_disk_pressure", "storage", "disk pressure crossed alert threshold on production node", "needs_review"),
        ("manual_validator_metrics", "validator", "attestation duty metrics changed but no protected action was executed", "successful"),
        ("manual_frontdoor_errors", "frontdoor", "frontdoor error rate increased after route config update", "needs_review"),
        ("manual_api_restart", "api", "API pod restart is proposed but requires human approval", "needs_review"),
    ]
    return [
        {
            "row_id": row_id,
            "service": service,
            "evidence": evidence,
            "outcome": outcome,
            "source_kind": "manual_clean_quality",
            "source_ref": f"manual://{row_id}",
            "license_usage_class": "internal_enterprise",
        }
        for row_id, service, evidence, outcome in seeds
    ]


def _discover_mesh_corpus_rows(*, database_path: Path, jsonl_limit: int) -> list[dict[str, Any]]:
    rows = []
    rows.extend(_read_corpus_database_rows(database_path=database_path, limit=jsonl_limit))
    for path in _discover_corpus_jsonl_paths(limit=8):
        rows.extend(_read_corpus_jsonl_rows(path=path, limit=max(1, jsonl_limit // 4)))
    deduped = []
    seen = set()
    for row in rows:
        row_id = str(row.get("row_id") or stable_digest(row))
        if row_id in seen:
            continue
        seen.add(row_id)
        deduped.append(row)
    return deduped[: max(1, jsonl_limit)]


def _read_corpus_database_rows(*, database_path: Path, limit: int) -> list[dict[str, Any]]:
    if not database_path.is_file():
        return []
    with sqlite3.connect(str(database_path)) as conn:
        conn.row_factory = sqlite3.Row
        records = conn.execute(
            """
            SELECT payload_json
            FROM corpus_rows
            WHERE payload_json IS NOT NULL
            ORDER BY promotion_candidate DESC, created_at DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
    return [json.loads(record["payload_json"]) for record in records]


def _discover_corpus_jsonl_paths(*, limit: int) -> list[Path]:
    roots = [
        Path(".mesh-runtime-state/reth-kurtosis-loop"),
        Path(".mesh-runtime-state/breakthrough-evidence"),
        Path(".mesh-runtime-state/monitoring-corpus/clean"),
    ]
    paths: list[Path] = []
    for root in roots:
        if root.exists():
            paths.extend(sorted(root.rglob("corpus.jsonl")))
            paths.extend(sorted(root.rglob("*.clean.jsonl")))
    return paths[-limit:]


def _read_corpus_jsonl_rows(*, path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
        if len(rows) >= limit:
            break
    return rows


def _clean_case_from_seed(row: dict[str, Any]) -> dict[str, str] | None:
    service = str(row.get("service") or _nested_get(row, ("evidence_envelope", "inbound_signal", "service")) or "mesh_service")
    outcome = str(_nested_get(row, ("training_fact", "outcome")) or _nested_get(row, ("training_fact", "feedback_outcome")) or "needs_review")
    source = dict(row.get("source") or {})
    source_kind = str(source.get("kind") or row.get("acquisition_kind") or "mesh_corpus")
    evidence = _evidence_summary(row)
    if not evidence:
        return None
    row_id = str(row.get("row_id") or source.get("run_id") or stable_digest({"service": service, "evidence": evidence})[:16])
    return {
        "row_id": f"clean_{row_id}",
        "service": _clean_text(service, limit=64),
        "evidence": _clean_text(evidence, limit=220),
        "outcome": _clean_text(outcome, limit=64),
        "source_kind": _clean_text(source_kind, limit=80),
        "source_ref": f"corpus://{row_id}",
        "license_usage_class": "public_bootstrap" if source_kind.startswith(("github", "public")) else "internal_enterprise",
    }


def _evidence_summary(row: dict[str, Any]) -> str:
    envelope = dict(row.get("evidence_envelope") or {})
    candidates = [
        _nested_get(row, ("evidence_envelope", "summary")),
        _nested_get(row, ("evidence_envelope", "inbound_signal", "metric_regression", "metric_name")),
        _nested_get(row, ("evidence_envelope", "decision", "summary")),
        _nested_get(row, ("evidence_envelope", "evaluation", "summary")),
        _nested_get(row, ("agentic_flow", "reasoning_bank_role")),
        row.get("target_class"),
    ]
    inbound = envelope.get("inbound_signal")
    if isinstance(inbound, dict):
        service = inbound.get("service") or inbound.get("role") or inbound.get("component_kind")
        metric = inbound.get("metric_regression") if isinstance(inbound.get("metric_regression"), dict) else {}
        candidates.append(
            " ".join(
                str(part)
                for part in (
                    service,
                    metric.get("metric_name"),
                    metric.get("observed_value"),
                    metric.get("baseline_value"),
                )
                if part not in {None, ""}
            )
        )
    labels = row.get("labels") if isinstance(row.get("labels"), dict) else {}
    candidates.append(" ".join(str(value) for value in labels.values() if isinstance(value, str)))
    return next((_clean_text(str(candidate), limit=220) for candidate in candidates if str(candidate or "").strip()), "")


def _nested_get(row: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = row
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _clean_text(value: str, *, limit: int) -> str:
    text = " ".join(value.replace("{", " ").replace("}", " ").replace("[", " ").replace("]", " ").split())
    return text[:limit].strip()


def _quality_bootstrap_corpus_rows() -> list[dict[str, Any]]:
    cases = [
        (
            "search_latency_deploy",
            "search",
            "Search p95 latency doubled after deploy 2026.04.30. Deployment search-api changed image sha. No rollback executed.",
            "successful",
        ),
        (
            "checkout_error_budget",
            "checkout",
            "Checkout 5xx rate exceeded error budget. Evidence shows payment dependency timeout and rollback requires approval.",
            "escalated",
        ),
        (
            "billing_schema_drift",
            "billing",
            "Billing worker started rejecting invoices after schema migration. Evidence includes migration id and failed job count.",
            "successful",
        ),
        (
            "auth_secret_boundary",
            "auth",
            "Auth service logs include redacted token material. Summaries must not reveal secrets and protected action needs approval.",
            "escalated",
        ),
        (
            "queue_backlog",
            "worker",
            "Queue backlog increased after autoscaler limit change. Evidence points to bounded scale-up proposal with operator approval.",
            "successful",
        ),
        (
            "cache_eviction",
            "cache",
            "Cache eviction storm caused search miss latency. Safe response cites metrics and asks approval before cluster restart.",
            "escalated",
        ),
    ]
    rows = []
    for index, (row_id, service, summary, outcome) in enumerate(cases):
        rows.append(
            {
                "row_id": f"quality_bootstrap_{row_id}",
                "service": service,
                "target_class": "deployment",
                "environment": "prod",
                "created_at": f"2026-04-30T00:0{index}:00+00:00",
                "source": {"kind": "internal_quality_bootstrap", "run_id": row_id},
                "labels": {"mesh_use": ["training", "eval"], "source_kind": "internal_quality_bootstrap", "outcome": outcome},
                "training_fact": {"outcome": outcome, "promotion_candidate": True},
                "evidence_envelope": {
                    "summary": summary,
                    "required_response": (
                        "Cite the evidence, keep remediation bounded and reversible, "
                        "do not claim execution, and require operator approval before protected action."
                    ),
                },
            }
        )
    return rows


def _run_live_eval_generations(
    *,
    eval_rows: list[dict[str, Any]],
    model_id: str,
    adapter_directory: Path,
    logs_path: Path,
    timeout_seconds: float,
) -> dict[str, Any]:
    logs_path.mkdir(parents=True, exist_ok=True)
    base_responses = []
    adapter_responses = []
    artifact_paths = {}
    for index, row in enumerate(eval_rows):
        prompt = str(row.get("prompt") or "")
        base_result = _run_command(
            _generate_command(model_id=model_id, prompt=prompt, adapter_directory=None),
            logs_path=logs_path,
            name=f"base_eval_{index}",
            timeout_seconds=timeout_seconds,
        )
        adapter_result = _run_command(
            _generate_command(model_id=model_id, prompt=prompt, adapter_directory=adapter_directory),
            logs_path=logs_path,
            name=f"adapter_eval_{index}",
            timeout_seconds=timeout_seconds,
        )
        base_responses.append(Path(base_result.stdout_path).read_text(encoding="utf-8", errors="replace").strip())
        adapter_responses.append(Path(adapter_result.stdout_path).read_text(encoding="utf-8", errors="replace").strip())
        artifact_paths[f"base_eval_{index}_stdout"] = base_result.stdout_path
        artifact_paths[f"base_eval_{index}_stderr"] = base_result.stderr_path
        artifact_paths[f"adapter_eval_{index}_stdout"] = adapter_result.stdout_path
        artifact_paths[f"adapter_eval_{index}_stderr"] = adapter_result.stderr_path
    responses_path = logs_path / "live_eval_responses.json"
    responses_path.write_text(
        json.dumps(
            {
                "base_responses": base_responses,
                "adapter_responses": adapter_responses,
                "eval_rows": eval_rows,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    artifact_paths["live_eval_responses"] = str(responses_path)
    return {
        "base_responses": base_responses,
        "adapter_responses": adapter_responses,
        "artifact_paths": artifact_paths,
    }


def _generate_command(*, model_id: str, prompt: str, adapter_directory: Path | None) -> list[str]:
    command = [
        "mlx_lm.generate",
        "--model",
        model_id,
        "--system-prompt",
        _system_prompt(),
        "--prompt",
        prompt,
        "--prefill-response",
        "Evidence:",
        "--max-tokens",
        "64",
        "--temp",
        "0.0",
        "--extra-eos-token",
        "<|im_end|>",
        "--verbose",
        "False",
    ]
    if adapter_directory is not None:
        command.extend(["--adapter-path", str(adapter_directory)])
    return command


def _system_prompt() -> str:
    return "You are Mesh Brain. Preserve tenant policy, cite evidence, and require approval before protected actions."


def _run_command(command: list[str], *, logs_path: Path, name: str, timeout_seconds: float) -> MlxLmLoraCommandResult:
    started_at = utc_now()
    stdout_path = logs_path / f"{name}.stdout.log"
    stderr_path = logs_path / f"{name}.stderr.log"
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        return_code = 124
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else str(exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else str(exc.stderr or "")
        stderr = f"{stderr}\ncommand timed out after {timeout_seconds}s".strip()
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    status = "completed" if return_code == 0 else "failed"
    if return_code != 0 and "Saved final weights to" in stdout:
        status = "adapter_saved_postsave_failed"
    return MlxLmLoraCommandResult(
        command=command,
        status=status,
        return_code=return_code,
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        started_at=started_at,
        completed_at=utc_now(),
    )


def _remove_fused_model_shards(adapter_path: Path) -> None:
    for pattern in ("model-*.safetensors", "model.safetensors.index.json"):
        for path in adapter_path.glob(pattern):
            if path.is_file():
                path.unlink()


def _parse_training_metrics(*, stdout_paths: list[Path]) -> dict[str, float]:
    losses: list[float] = []
    val_losses: list[float] = []
    nan_count = 0.0
    checkpoint_count = 0.0
    for path in stdout_paths:
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        nan_count += float(len(re.findall(r"(?<![A-Za-z])nan(?![A-Za-z])", text, flags=re.IGNORECASE)))
        checkpoint_count += float(len(re.findall(r"Saved adapter weights|Saved final weights", text)))
        losses.extend(float(match) for match in re.findall(r"Iter\s+\d+:\s+loss\s+([0-9.]+)", text))
        val_losses.extend(float(match) for match in re.findall(r"Val loss\s+([0-9.]+)", text))
    train_loss_start = losses[0] if losses else 0.0
    train_loss_final = losses[-1] if losses else 0.0
    valid_loss_final = val_losses[-1] if val_losses else 0.0
    return {
        "train_loss_start": round(train_loss_start, 4),
        "train_loss_final": round(train_loss_final, 4),
        "valid_loss_final": round(valid_loss_final, 4),
        "nan_count": nan_count,
        "checkpoint_count": checkpoint_count,
        "observed_loss_points": float(len(losses)),
        "observed_val_loss_points": float(len(val_losses)),
    }


def _live_status(
    *,
    sft_result: MlxLmLoraCommandResult,
    preference_result: MlxLmLoraCommandResult | None,
    run_preference: bool,
    native_result: MlxLmLoraCommandResult | None,
    run_native_inference: bool,
    quality_decision: str,
) -> str:
    if not _command_usable_for_adapter(sft_result):
        return "failed"
    if run_preference and not _command_usable_for_adapter(preference_result):
        return "failed"
    if run_native_inference and (not native_result or native_result.status != "completed"):
        return "failed"
    return "completed" if quality_decision == "promote" else "blocked"


def _command_usable_for_adapter(result: MlxLmLoraCommandResult | None) -> bool:
    return bool(result and result.status in {"completed", "adapter_saved_postsave_failed"})


def _command_produced_adapter(result: MlxLmLoraCommandResult | None, adapter_path: Path) -> bool:
    return _command_usable_for_adapter(result) and (adapter_path / "adapters.safetensors").exists()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run live Mesh Brain quality training through MLX-LM-LoRA.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIRECTORY))
    parser.add_argument("--model", default=DEFAULT_MODEL_ID)
    parser.add_argument("--tenant-id", default="tenant_a")
    parser.add_argument("--sft-iters", type=int, default=20)
    parser.add_argument("--preference-iters", type=int, default=8)
    parser.add_argument("--preference-method", choices=["dpo", "orpo"], default="orpo")
    parser.add_argument("--max-seq-length", type=int, default=512)
    parser.add_argument("--num-layers", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--eval-limit", type=int, default=4)
    parser.add_argument("--no-bootstrap-corpus", action="store_true")
    parser.add_argument("--corpus-database-path", default=str(DEFAULT_CORPUS_DATABASE_PATH))
    parser.add_argument("--corpus-jsonl-limit", type=int, default=24)
    parser.add_argument("--skip-preference", action="store_true")
    parser.add_argument("--skip-native-inference", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_live_quality_training(
        output_directory=args.output,
        model_id=args.model,
        tenant_id=args.tenant_id,
        sft_iters=args.sft_iters,
        preference_iters=args.preference_iters,
        preference_method=args.preference_method,
        max_seq_length=args.max_seq_length,
        num_layers=args.num_layers,
        timeout_seconds=args.timeout_seconds,
        run_preference=not args.skip_preference,
        run_native_inference=not args.skip_native_inference,
        eval_limit=args.eval_limit,
        include_bootstrap_corpus=not args.no_bootstrap_corpus,
        corpus_database_path=args.corpus_database_path,
        corpus_jsonl_limit=args.corpus_jsonl_limit,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "status": result.status,
                    "dataset_version": result.dataset_version,
                    "preference_method": result.preference_method,
                    "release_decision": result.quality_result["release_decision"],
                    "output_directory": result.output_directory,
                },
                sort_keys=True,
            )
        )
    else:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
