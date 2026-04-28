from __future__ import annotations

import logging
from typing import Any

from shared.mesh_runtime import RuntimeConfig

from .service import ActuatorResult


_LOG = logging.getLogger("mesh.actuators.load_balancer")


class LoadBalancerAdapter:
    """Mock-by-default load-balancer drain/restore adapter.

    Production providers can be wired behind this interface. Until then,
    configured mock mode gives the orchestrator a stable safety workflow:
    drain -> restart -> postflight -> restore.
    """

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig()

    def drain_target(self, parameters: dict[str, Any]) -> ActuatorResult:
        target_id = parameters.get("lb_target_id")
        if not target_id:
            return _failure("missing_lb_target", "lb_target_id is required for load-balancer drain")
        _LOG.info("lb: drain target=%s provider=%s", target_id, self.config.load_balancer_provider)
        return {
            "status": "succeeded",
            "external_refs": {
                "lb_provider": self.config.load_balancer_provider,
                "lb_target_id": target_id,
                "lb_pool": parameters.get("lb_pool"),
                "lb_state": "drained",
                "mock": self.config.load_balancer_provider == "mock",
            },
        }

    def target_status(self, parameters: dict[str, Any]) -> ActuatorResult:
        target_id = parameters.get("lb_target_id")
        if not target_id:
            return _failure("missing_lb_target", "lb_target_id is required for load-balancer status")
        return {
            "status": "succeeded",
            "external_refs": {
                "lb_provider": self.config.load_balancer_provider,
                "lb_target_id": target_id,
                "lb_state": "drained",
                "active_connections": 0,
            },
        }

    def restore_target(self, parameters: dict[str, Any]) -> ActuatorResult:
        target_id = parameters.get("lb_target_id")
        if not target_id:
            return _failure("missing_lb_target", "lb_target_id is required for load-balancer restore")
        _LOG.info("lb: restore target=%s provider=%s", target_id, self.config.load_balancer_provider)
        return {
            "status": "succeeded",
            "external_refs": {
                "lb_provider": self.config.load_balancer_provider,
                "lb_target_id": target_id,
                "lb_pool": parameters.get("lb_pool"),
                "lb_state": "active",
                "mock": self.config.load_balancer_provider == "mock",
            },
        }


def _failure(reason: str, detail: str) -> ActuatorResult:
    return {"status": "failed", "failure": {"reason": reason, "detail": detail}, "external_refs": {}}
