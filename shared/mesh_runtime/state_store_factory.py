from __future__ import annotations

from .config import RuntimeConfig
from .control_plane_state import FileStateStore
from .mesh_state_store import MeshStateStore
from .postgres_state import PostgresStateStore


def build_mesh_state_store(config: RuntimeConfig) -> MeshStateStore:
    if config.state_backend == "postgres":
        return PostgresStateStore(config)
    return FileStateStore(config)
