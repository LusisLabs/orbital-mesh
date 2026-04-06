from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class RuntimeConfig:
    environment: str = "local"
    evaluation_mode: str = "mock"
    orchestration_mode: str = "mock"

    @classmethod
    def from_env(cls) -> "RuntimeConfig":
        return cls(
            environment=os.getenv("MESH_ENVIRONMENT", "local"),
            evaluation_mode=os.getenv("MESH_EVALUATION_MODE", "mock"),
            orchestration_mode=os.getenv("MESH_ORCHESTRATION_MODE", "mock"),
        )
