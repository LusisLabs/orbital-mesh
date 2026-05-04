from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ResearchInfluence:
    name: str
    url: str
    organization: str
    category: str
    planes: tuple[str, ...]
    capabilities: tuple[str, ...]
    adoption_guidance: str
    mvp_relevance: str
    risks: tuple[str, ...] = ()

    def supports_plane(self, plane: str) -> bool:
        return plane in self.planes

    def supports_capability(self, capability: str) -> bool:
        normalized = capability.lower()
        return any(normalized in item.lower() for item in self.capabilities)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


RESEARCH_INFLUENCES: tuple[ResearchInfluence, ...] = (
    ResearchInfluence(
        name="NVIDIA/NeMo-RL",
        url="https://github.com/NVIDIA/NeMo-RL",
        organization="NVIDIA",
        category="posttraining_rl",
        planes=("posttraining", "training_jobs", "eval_jobs", "agent_runtime"),
        capabilities=(
            "RLHF-style posttraining",
            "PPO and GRPO training patterns",
            "distributed rollout collection",
            "reward model integration",
            "policy evaluation loop",
            "agent RL sandbox inspiration",
        ),
        adoption_guidance=(
            "Use as the north-star shape for bounded agent RL orchestration after SFT and preference tuning pass. "
            "Keep Mesh policy gates outside the trainer."
        ),
        mvp_relevance="defer",
        risks=("reward hacking", "distributed training complexity", "policy bypass if trainer owns approvals"),
    ),
    ResearchInfluence(
        name="NVIDIA/Megatron-LM",
        url="https://github.com/NVIDIA/Megatron-LM",
        organization="NVIDIA",
        category="distributed_training",
        planes=("posttraining", "training_jobs", "model_management"),
        capabilities=(
            "tensor parallelism",
            "pipeline parallelism",
            "sequence parallelism",
            "large-scale checkpointing",
            "distributed optimizer patterns",
        ),
        adoption_guidance="Use only when adapter jobs outgrow single-node trainer assumptions.",
        mvp_relevance="not_mvp",
        risks=("operational complexity", "checkpoint portability", "cluster scheduling overhead"),
    ),
    ResearchInfluence(
        name="stanford-futuredata/megablocks",
        url="https://github.com/stanford-futuredata/megablocks",
        organization="Stanford FutureData",
        category="moe_kernels",
        planes=("serving", "training_jobs", "model_management"),
        capabilities=(
            "block-sparse MoE training",
            "dropless expert routing",
            "efficient expert parallelism",
            "sparse matrix multiplication",
        ),
        adoption_guidance="Use as design influence for future MoE adapter or expert-routing work, not for Qwen 27B MVP.",
        mvp_relevance="not_mvp",
        risks=("MoE-specific complexity", "expert imbalance", "kernel portability"),
    ),
    ResearchInfluence(
        name="google-research/google-research",
        url="https://github.com/google-research/google-research",
        organization="Google Research",
        category="research_corpus",
        planes=("eval_jobs", "serving", "posttraining"),
        capabilities=(
            "systems research references",
            "model evaluation patterns",
            "optimization experiments",
            "long-context and retrieval research",
        ),
        adoption_guidance="Treat as research reference material; promote only concrete, reproducible methods into Mesh Brain jobs.",
        mvp_relevance="reference_only",
        risks=("mixed maturity", "paper-code drift", "not productized"),
    ),
    ResearchInfluence(
        name="google-deepmind/open_spiel",
        url="https://github.com/google-deepmind/open_spiel",
        organization="Google DeepMind",
        category="rl_environments",
        planes=("agent_runtime", "eval_jobs", "training_jobs"),
        capabilities=(
            "multi-agent environment patterns",
            "policy evaluation",
            "bounded game-like RL tasks",
            "rollout and reward instrumentation",
        ),
        adoption_guidance="Use as conceptual input for sandboxed agent RL environments with observable rewards.",
        mvp_relevance="defer",
        risks=("environment mismatch", "reward proxy mismatch"),
    ),
    ResearchInfluence(
        name="google-deepmind/acme",
        url="https://github.com/google-deepmind/acme",
        organization="Google DeepMind",
        category="rl_framework",
        planes=("training_jobs", "agent_runtime"),
        capabilities=(
            "agent-environment loop structure",
            "replay buffers",
            "distributed RL components",
            "actor learner separation",
        ),
        adoption_guidance="Use as architecture reference if Mesh Brain adds a full RL learner; keep audit and approval in Mesh runtime.",
        mvp_relevance="defer",
        risks=("framework overhead", "integration complexity"),
    ),
    ResearchInfluence(
        name="openai/evals",
        url="https://github.com/openai/evals",
        organization="OpenAI",
        category="eval_harness",
        planes=("eval_jobs", "agent_runtime"),
        capabilities=(
            "eval registry pattern",
            "model-graded evals",
            "completion function abstraction",
            "regression suite organization",
        ),
        adoption_guidance="Use as influence for eval registry shape; Mesh Brain keeps release gates deterministic and policy-aware.",
        mvp_relevance="reference_only",
        risks=("model-graded eval drift", "non-Mesh policy semantics"),
    ),
    ResearchInfluence(
        name="EleutherAI/lm-evaluation-harness",
        url="https://github.com/EleutherAI/lm-evaluation-harness",
        organization="EleutherAI",
        category="eval_harness",
        planes=("eval_jobs", "model_management"),
        capabilities=(
            "benchmark harness",
            "task registry",
            "few-shot evaluation",
            "model comparison",
        ),
        adoption_guidance="Use for external benchmark compatibility, not as the release gate source of truth.",
        mvp_relevance="reference_only",
        risks=("benchmarks may not reflect CROPS workflows", "policy coverage gaps"),
    ),
)


def list_research_influences(
    *,
    plane: str | None = None,
    category: str | None = None,
    mvp_relevance: str | None = None,
) -> list[ResearchInfluence]:
    influences = list(RESEARCH_INFLUENCES)
    if plane is not None:
        influences = [influence for influence in influences if influence.supports_plane(plane)]
    if category is not None:
        influences = [influence for influence in influences if influence.category == category]
    if mvp_relevance is not None:
        influences = [influence for influence in influences if influence.mvp_relevance == mvp_relevance]
    return influences


def get_research_influence(name: str) -> ResearchInfluence:
    for influence in RESEARCH_INFLUENCES:
        if influence.name == name:
            return influence
    raise KeyError(name)


def research_capability_report(*, plane: str, required_capabilities: list[str]) -> dict[str, Any]:
    influences = list_research_influences(plane=plane)
    coverage: dict[str, list[str]] = {}
    for capability in required_capabilities:
        coverage[capability] = [influence.name for influence in influences if influence.supports_capability(capability)]
    missing = [capability for capability, names in coverage.items() if not names]
    return {
        "plane": plane,
        "influence_count": len(influences),
        "coverage": coverage,
        "missing_capabilities": missing,
        "influences": [influence.to_dict() for influence in influences],
    }


def research_adoption_plan(*, plane: str) -> list[dict[str, Any]]:
    relevance_rank = {"mvp": 0, "reference_only": 1, "defer": 2, "not_mvp": 3}
    influences = sorted(
        list_research_influences(plane=plane),
        key=lambda item: (relevance_rank.get(item.mvp_relevance, 99), item.name),
    )
    return [
        {
            "name": influence.name,
            "category": influence.category,
            "mvp_relevance": influence.mvp_relevance,
            "adoption_guidance": influence.adoption_guidance,
            "risks": list(influence.risks),
        }
        for influence in influences
    ]
