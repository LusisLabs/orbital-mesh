from __future__ import annotations

import json
import logging
import sys
import threading
import time
from dataclasses import replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

from shared.mesh_runtime import RuntimeConfig


_LOG = logging.getLogger("mesh.latentmas")
_REPO_ROOT = Path(__file__).resolve().parents[2]
_LATENTMAS_ROOT = _REPO_ROOT / "latent-mesh" / "LatentMAS"


class MeshLatentMasRuntime:
    def __init__(self, config: RuntimeConfig):
        self.config = config
        self._lock = threading.Lock()
        self._model = None
        self._model_name: str | None = None
        self._model_backend: str | None = None
        self._loaded_at: float | None = None

    def health(self) -> dict[str, Any]:
        return {
            "ready": _LATENTMAS_ROOT.is_dir(),
            "model_loaded": self._model is not None,
            "model_name": self._model_name or self.config.latentmas_model_name,
            "backend": self._model_backend or ("vllm" if self.config.latentmas_use_vllm else "transformers"),
            "latentmas_root": str(_LATENTMAS_ROOT),
            "use_vllm": self.config.latentmas_use_vllm,
        }

    def infer(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            started = time.monotonic()
            options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
            runtime_config = self._config_from_options(options)
            model = self._ensure_model(runtime_config)
            question = _build_mesh_question(payload)
            raw_prediction, traces = _run_latentmas_inference(model, runtime_config, question)
            parsed, parse_error = _parse_advisory_json(raw_prediction)
            risk_flags = _string_list(parsed.get("risk_flags")) if parsed else []
            if parse_error:
                risk_flags.append("latentmas_output_unparseable")
            elapsed = round(time.monotonic() - started, 4)
            raw_summary = parsed.get("summary") or (raw_prediction.splitlines()[0] if raw_prediction.splitlines() else None)
            summary = str(raw_summary or "LatentMAS inference completed.")
            return {
                "status": "completed",
                "summary": summary[:1000],
                "recommended_action": str(parsed.get("recommended_action") or "human_review"),
                "risk_flags": risk_flags,
                "confidence": parsed.get("confidence"),
                "raw_prediction": raw_prediction,
                "agent_traces": traces,
                "metrics": {
                    "model_name": runtime_config.latentmas_model_name,
                    "elapsed_time_sec": elapsed,
                    "latent_steps": runtime_config.latentmas_latent_steps,
                    "prompt_mode": runtime_config.latentmas_prompt_mode,
                    "backend": self._model_backend or "transformers",
                    "model_loaded_at": self._loaded_at,
                    "parse_error": parse_error,
                },
            }

    def _config_from_options(self, options: dict[str, Any]) -> RuntimeConfig:
        return replace(
            self.config,
            latentmas_model_name=str(options.get("model_name") or self.config.latentmas_model_name),
            latentmas_device=str(options.get("device") or self.config.latentmas_device),
            latentmas_prompt_mode=str(options.get("prompt_mode") or self.config.latentmas_prompt_mode),
            latentmas_latent_steps=int(options.get("latent_steps") or self.config.latentmas_latent_steps),
            latentmas_max_new_tokens=int(options.get("max_new_tokens") or self.config.latentmas_max_new_tokens),
            latentmas_use_vllm=bool(options.get("use_vllm", self.config.latentmas_use_vllm)),
        )

    def _ensure_model(self, config: RuntimeConfig):
        requested_backend = "vllm" if config.latentmas_use_vllm else "transformers"
        if (
            self._model is not None
            and self._model_name == config.latentmas_model_name
            and (
                self._model_backend == requested_backend
                or (requested_backend == "vllm" and self._model_backend == "transformers")
            )
        ):
            return self._model
        if not _LATENTMAS_ROOT.is_dir():
            raise RuntimeError(f"LatentMAS root not found: {_LATENTMAS_ROOT}")
        if str(_LATENTMAS_ROOT) not in sys.path:
            sys.path.insert(0, str(_LATENTMAS_ROOT))
        from models import ModelWrapper
        from utils import auto_device, set_seed

        device = auto_device(config.latentmas_device)
        args = SimpleNamespace(
            model_name=config.latentmas_model_name,
            method="latent_mas",
            max_new_tokens=config.latentmas_max_new_tokens,
            latent_space_realign=False,
            use_vllm=config.latentmas_use_vllm,
            enable_prefix_caching=config.latentmas_use_vllm,
            use_second_HF_model=config.latentmas_use_vllm,
            device=str(device),
            device2=str(device),
            tensor_parallel_size=1,
            gpu_memory_utilization=0.9,
        )
        set_seed(42)
        self._model = ModelWrapper(config.latentmas_model_name, device, use_vllm=config.latentmas_use_vllm, args=args)
        self._model_name = config.latentmas_model_name
        self._model_backend = "vllm" if getattr(self._model, "use_vllm", False) else "transformers"
        self._loaded_at = time.time()
        return self._model


class LatentMasServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], config: RuntimeConfig):
        super().__init__(server_address, LatentMasRequestHandler)
        self.config = config
        self.runtime = MeshLatentMasRuntime(config)


class LatentMasRequestHandler(BaseHTTPRequestHandler):
    server: LatentMasServer

    def log_message(self, fmt: str, *args: object) -> None:
        _LOG.info("%s - %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] == "/health":
            self._send_json(self.server.runtime.health())
            return
        self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/infer":
            self._send_json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            result = self.server.runtime.infer(payload)
        except Exception as exc:
            _LOG.exception("LatentMAS inference failed")
            self._send_json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self._send_json(result)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _run_latentmas_inference(model: Any, config: RuntimeConfig, question: str) -> tuple[str, list[dict[str, Any]]]:
    if getattr(model, "use_vllm", False):
        return _run_latentmas_inference_vllm(model, config, question)

    past_key_values = None
    traces: list[dict[str, Any]] = []
    final_text = ""
    roles = ("planner", "critic", "refiner", "judger")
    for role in roles:
        messages = _build_role_messages(role, question, config.latentmas_prompt_mode)
        prompt, input_ids, attention_mask, tokens = model.prepare_chat_input(messages, add_generation_prompt=True)
        if role != "judger":
            past_key_values = model.generate_latent_batch(
                input_ids,
                attention_mask=attention_mask,
                latent_steps=config.latentmas_latent_steps,
                past_key_values=past_key_values,
            )
            traces.append(
                {
                    "name": role.title(),
                    "role": role,
                    "input": prompt,
                    "input_tokens": tokens,
                    "latent_steps": config.latentmas_latent_steps,
                    "output": "",
                }
            )
            continue
        generations, _ = model.generate_text_batch(
            input_ids,
            attention_mask,
            max_new_tokens=config.latentmas_max_new_tokens,
            temperature=0.2,
            top_p=0.9,
            past_key_values=past_key_values if config.latentmas_latent_steps > 0 else None,
        )
        final_text = generations[0].strip() if generations else ""
        traces.append(
            {
                "name": "Judger",
                "role": role,
                "input": prompt,
                "input_tokens": tokens,
                "output": final_text,
            }
        )
    return final_text, traces


def _run_latentmas_inference_vllm(model: Any, config: RuntimeConfig, question: str) -> tuple[str, list[dict[str, Any]]]:
    import torch
    from vllm import SamplingParams

    past_key_values = None
    traces: list[dict[str, Any]] = []
    embedding_record = []
    final_text = ""
    roles = ("planner", "critic", "refiner", "judger")
    for role in roles:
        messages = _build_role_messages(role, question, config.latentmas_prompt_mode)
        prompt = model.render_chat(messages, add_generation_prompt=True)
        if role != "judger":
            encoded = model.tokenizer(
                prompt,
                return_tensors="pt",
                padding=True,
                add_special_tokens=False,
            )
            input_ids = encoded["input_ids"].to(model.HF_device)
            attention_mask = encoded["attention_mask"].to(model.HF_device)
            active_ids = input_ids[0][attention_mask[0].bool()].tolist()
            tokens = model.tokenizer.convert_ids_to_tokens(active_ids)
            past_key_values, previous_hidden_embedding = model.generate_latent_batch_hidden_state(
                input_ids,
                attention_mask=attention_mask,
                latent_steps=config.latentmas_latent_steps,
                past_key_values=past_key_values,
            )
            embedding_record.append(previous_hidden_embedding)
            traces.append(
                {
                    "name": role.title(),
                    "role": role,
                    "input": prompt,
                    "input_tokens": tokens,
                    "latent_steps": config.latentmas_latent_steps,
                    "output": "",
                }
            )
            continue

        encoded = model.tokenizer(
            prompt,
            return_tensors="pt",
            padding=True,
            add_special_tokens=False,
        )
        input_ids = encoded["input_ids"].to(model.HF_device)
        attention_mask = encoded["attention_mask"].to(model.HF_device)
        active_ids = input_ids[0][attention_mask[0].bool()].tolist()
        tokens = model.tokenizer.convert_ids_to_tokens(active_ids)
        current_embedding = model.embedding_layer(input_ids).to(model.device)
        if embedding_record:
            latent_embedding = torch.cat(embedding_record, dim=1).to(model.device)
            insert_idx = _latent_insert_index(model, prompt)
            left_embedding = current_embedding[:, :insert_idx, :]
            right_embedding = current_embedding[:, insert_idx:, :]
            prompt_embedding = torch.cat([left_embedding, latent_embedding, right_embedding], dim=1)
        else:
            prompt_embedding = current_embedding
        outputs = model.vllm_engine.generate(
            [{"prompt_embeds": prompt_embedding[0]}],
            SamplingParams(
                temperature=0.2,
                top_p=0.9,
                max_tokens=config.latentmas_max_new_tokens,
            ),
        )
        final_text = outputs[0].outputs[0].text.strip() if outputs else ""
        traces.append(
            {
                "name": "Judger",
                "role": role,
                "input": prompt,
                "input_tokens": tokens,
                "output": final_text,
            }
        )
    return final_text, traces


def _latent_insert_index(model: Any, prompt: str) -> int:
    marker = "<|im_start|>user\n"
    marker_index = prompt.find(marker)
    if marker_index < 0:
        return 0
    left = prompt[: marker_index + len(marker)]
    encoded = model.tokenizer(left, add_special_tokens=False)
    return len(encoded.get("input_ids", []))


def _build_role_messages(role: str, question: str, prompt_mode: str) -> list[dict[str, str]]:
    system = (
        "You are a bounded incident-response reasoning worker. "
        "You can only produce advisory analysis. Mesh Intelligence owns policy, tests, audit, and execution."
    )
    if role == "planner":
        content = (
            "Planner: build a concise remediation reasoning plan for this Mesh run. "
            "Do not execute actions or claim production state changed.\n\n"
            f"{question}"
        )
    elif role == "critic":
        content = (
            "Critic: review the latent planning context for missing risk, policy, rollback, testing, and scope issues. "
            "The prior plan is available only as latent memory.\n\n"
            f"{question}"
        )
    elif role == "refiner":
        content = (
            "Refiner: combine the latent plan and critique into the strongest advisory recommendation. "
            "Keep the recommendation bounded to Mesh-owned gates.\n\n"
            f"{question}"
        )
    else:
        content = (
            "Judger: return one JSON object only. Required keys: summary, recommended_action, risk_flags, confidence. "
            "recommended_action must be one of execute, human_review, root_cause_review, open_pr, review, stage_validation. "
            "risk_flags must be a list of strings. confidence must be a number from 0 to 1. "
            "Do not include markdown.\n\n"
            f"Prompt mode: {prompt_mode}\n\n{question}"
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


def _build_mesh_question(payload: dict[str, Any]) -> str:
    task = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    trigger = payload.get("trigger") if isinstance(payload.get("trigger"), dict) else {}
    decision = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    evaluation = payload.get("evaluation") if isinstance(payload.get("evaluation"), dict) else {}
    focus = {
        "run_id": payload.get("run_id"),
        "task": task,
        "trigger": {
            "trigger_type": trigger.get("trigger_type"),
            "environment": trigger.get("environment"),
            "service": trigger.get("service"),
            "endpoint": trigger.get("endpoint"),
            "metrics": trigger.get("metrics"),
            "related_context": trigger.get("related_context"),
        },
        "decision": {
            "decision_type": decision.get("decision_type"),
            "summary": decision.get("summary"),
            "autonomy_tier": decision.get("autonomy_tier"),
            "reasoning": decision.get("reasoning"),
            "risk": decision.get("risk"),
            "confidence": decision.get("confidence"),
            "execution_plan": decision.get("execution_plan"),
        },
        "evaluation": {
            "passed": evaluation.get("passed"),
            "final_recommendation": evaluation.get("final_recommendation"),
            "blocking_reasons": evaluation.get("blocking_reasons"),
            "stage_results": evaluation.get("stage_results"),
        },
    }
    return json.dumps(focus, indent=2, sort_keys=True)


def _parse_advisory_json(text: str) -> tuple[dict[str, Any], str | None]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, str(exc)
    if not isinstance(parsed, dict):
        return {}, "model output was not a JSON object"
    return parsed, None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def build_server(config: RuntimeConfig | None = None) -> LatentMasServer:
    resolved = config or RuntimeConfig.from_env()
    parsed = urlparse(resolved.latentmas_url or "http://127.0.0.1:8791")
    host = parsed.hostname or "127.0.0.1"
    if host == "127.0.0.1":
        host = "0.0.0.0"
    port = parsed.port or 8791
    return LatentMasServer((host, port), resolved)


def serve_forever(config: RuntimeConfig | None = None) -> LatentMasServer:
    server = build_server(config)
    _LOG.info("LatentMAS sidecar listening on %s:%s", *server.server_address)
    server.serve_forever()
    return server


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve_forever()
