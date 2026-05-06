"""Configuration for native Mesh evaluation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.evaluation.evaluation_stack import EVALUATION_INTEGRATION_IDS, normalize_integration_lanes


@dataclass(frozen=True)
class MeshEvalConfig:
    """Declares how trajectory evaluation and LatentMAS token budgets align."""

    package: str = "native_mesh_eval"
    version: str = "mesh_eval_v1"
    context_token_budget: int = 2048
    tokenizer_json: str | None = None
    sentencepiece_model: str | None = None
    latentmas_crate: str = "latent-mesh/LatentMAS"
    latentmas_command: str | None = None
    latentmas_timeout_seconds: float = 5.0
    integration_lanes: tuple[str, ...] = EVALUATION_INTEGRATION_IDS

    @classmethod
    def from_env(cls) -> "MeshEvalConfig":
        budget = os.environ.get("MESH_EVAL_CONTEXT_TOKEN_BUDGET")
        return cls(
            context_token_budget=int(budget) if budget else 2048,
            tokenizer_json=os.environ.get("MESH_EVAL_TOKENIZER_JSON"),
            sentencepiece_model=os.environ.get("MESH_EVAL_SENTENCEPIECE_MODEL"),
            latentmas_crate=os.environ.get("MESH_EVAL_LATENTMAS_CRATE", "latent-mesh/LatentMAS"),
            latentmas_command=os.environ.get("MESH_EVAL_LATENTMAS_COMMAND"),
            latentmas_timeout_seconds=float(os.environ.get("MESH_EVAL_LATENTMAS_TIMEOUT_SECONDS", "5")),
            integration_lanes=normalize_integration_lanes(os.environ.get("MESH_EVAL_INTEGRATION_LANES")),
        ).validate()

    def validate(self) -> "MeshEvalConfig":
        if self.tokenizer_json and self.sentencepiece_model:
            raise ValueError("configure either MESH_EVAL_TOKENIZER_JSON or MESH_EVAL_SENTENCEPIECE_MODEL, not both")
        if self.context_token_budget < 0:
            raise ValueError("MESH_EVAL_CONTEXT_TOKEN_BUDGET must be non-negative")
        if self.latentmas_timeout_seconds <= 0:
            raise ValueError("MESH_EVAL_LATENTMAS_TIMEOUT_SECONDS must be positive")
        return self

    @property
    def tokenizer_backend(self) -> str:
        if self.tokenizer_json:
            return "huggingface_tokenizers"
        if self.sentencepiece_model:
            return "sentencepiece"
        return "heuristic"

    def latentmas_args(self) -> list[str]:
        args = ["--context-token-budget", str(self.context_token_budget)]
        if self.tokenizer_json:
            args.extend(["--tokenizer-json", self.tokenizer_json])
        if self.sentencepiece_model:
            args.extend(["--sentencepiece-model", self.sentencepiece_model])
        return args

    def to_artifact(self) -> dict[str, Any]:
        return {
            "package": self.package,
            "version": self.version,
            "trajectory_source": "services.evaluation.mesh_eval",
            "latent_mesh": {
                "crate": self.latentmas_crate,
                "command": self.latentmas_command,
                "timeout_seconds": self.latentmas_timeout_seconds,
                "context_token_budget": self.context_token_budget,
                "tokenizer_backend": self.tokenizer_backend,
                "tokenizer_json": _display_path(self.tokenizer_json),
                "sentencepiece_model": _display_path(self.sentencepiece_model),
                "rust_args": self.latentmas_args(),
            },
            "promptfoo_role": "legacy_compatibility_only",
            "evaluation_stack": {
                "default_lanes": list(EVALUATION_INTEGRATION_IDS),
                "enabled_lanes": list(self.integration_lanes),
            },
        }


def _display_path(path: str | None) -> str | None:
    if not path:
        return None
    return str(Path(path))
