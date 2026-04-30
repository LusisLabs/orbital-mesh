from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class InferenceBackend:
    name: str
    url: str
    hardware_tiers: tuple[str, ...]
    model_families: tuple[str, ...]
    techniques: tuple[str, ...]
    category: str
    default_for: tuple[str, ...] = ()
    secondary_for: tuple[str, ...] = ()

    def supports_hardware(self, hardware_tier: str) -> bool:
        return hardware_tier in self.hardware_tiers or self.hardware_tiers == ("multi",)

    def supports_technique(self, needle: str) -> bool:
        normalized = needle.lower()
        return any(normalized in technique.lower() for technique in self.techniques)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


INFERENCE_BACKENDS: tuple[InferenceBackend, ...] = (
    InferenceBackend(
        name="vllm-project/vllm",
        url="https://github.com/vllm-project/vllm",
        hardware_tiers=("nvidia_datacenter", "nvidia_consumer", "amd_rocm", "multi"),
        model_families=("all",),
        techniques=(
            "PagedAttention",
            "FlashAttention / FlashInfer",
            "Speculative decoding",
            "Continuous batching",
            "FP8 / INT4 / GPTQ / AWQ / NVFP4",
            "Prefix caching",
            "Chunked prefill",
            "Constrained decoding / structured outputs",
            "CUDA graph",
            "MoE kernels",
            "Tensor / pipeline parallelism",
        ),
        category="serving_engine",
        default_for=("nvidia_consumer", "amd_rocm"),
        secondary_for=("nvidia_datacenter",),
    ),
    InferenceBackend(
        name="sgl-project/sglang",
        url="https://github.com/sgl-project/sglang",
        hardware_tiers=("nvidia_datacenter", "nvidia_consumer", "amd_rocm", "multi"),
        model_families=("all",),
        techniques=(
            "RadixAttention prefix reuse",
            "FlashInfer kernels",
            "MXFP8 MoE",
            "Piecewise CUDA graph",
            "Prefill/decode disaggregation",
            "Speculative decoding",
            "Constrained decoding / structured outputs",
            "Structured agentic workload optimization",
            "Elastic expert parallelism",
        ),
        category="serving_engine",
        default_for=("nvidia_datacenter",),
        secondary_for=("nvidia_consumer", "amd_rocm"),
    ),
    InferenceBackend(
        name="ai-dynamo/dynamo",
        url="https://github.com/ai-dynamo/dynamo",
        hardware_tiers=("nvidia_datacenter", "multi"),
        model_families=("DeepSeek", "Llama", "Qwen", "MoE"),
        techniques=(
            "Disaggregated prefill/decode",
            "KV-aware routing",
            "SLA-based GPU autoscaler",
            "NIXL low-latency transfer",
            "Multi-tier KV offload",
            "Wide expert parallelism",
            "Multi-node orchestration",
        ),
        category="orchestration",
        default_for=("nvidia_large_cluster",),
    ),
    InferenceBackend(
        name="NVIDIA/TensorRT-LLM",
        url="https://github.com/NVIDIA/TensorRT-LLM",
        hardware_tiers=("nvidia_datacenter", "nvidia_consumer"),
        model_families=("all",),
        techniques=(
            "FP8 / NVFP4 / INT8 / INT4",
            "FlashMLA",
            "Wide expert parallelism",
            "In-flight batching",
            "CUDA graph",
            "Speculative decoding",
            "Constrained decoding / structured outputs",
            "KV cache reuse",
            "AutoDeploy PyTorch backend",
        ),
        category="serving_engine",
    ),
    InferenceBackend(
        name="NVIDIA/Model-Optimizer",
        url="https://github.com/NVIDIA/Model-Optimizer",
        hardware_tiers=("nvidia_datacenter", "nvidia_consumer"),
        model_families=("Llama", "DeepSeek", "Nemotron", "diffusion"),
        techniques=(
            "NVFP4 / FP8 PTQ",
            "Quantization-aware training",
            "Medusa speculative decoding",
            "Pruning and distillation",
            "EoRA LoRA-based recovery",
            "Export to SGLang / vLLM / TRT-LLM",
        ),
        category="quantization",
    ),
    InferenceBackend(
        name="flashinfer-ai/flashinfer",
        url="https://github.com/flashinfer-ai/flashinfer",
        hardware_tiers=("nvidia_datacenter", "nvidia_consumer"),
        model_families=("all",),
        techniques=(
            "Block-sparse KV cache",
            "JIT kernel compilation",
            "Load-balanced scheduling",
            "CUDA graph compatible",
            "GQA / MLA / MQA kernels",
            "MXFP8 GEMM",
        ),
        category="kernel_library",
    ),
    InferenceBackend(
        name="llm-d/llm-d",
        url="https://github.com/llm-d/llm-d",
        hardware_tiers=("nvidia_datacenter", "multi"),
        model_families=("DeepSeek", "Llama", "MoE"),
        techniques=(
            "Disaggregated serving",
            "KV connector interfaces",
            "Wide expert parallelism",
            "CPU memory tiering for KV",
            "Kubernetes Inference Gateway",
            "Prefix cache offload",
        ),
        category="orchestration",
        secondary_for=("nvidia_large_cluster",),
    ),
    InferenceBackend(
        name="ggml-org/llama.cpp",
        url="https://github.com/ggml-org/llama.cpp",
        hardware_tiers=("nvidia_consumer", "amd_rocm", "apple_silicon", "cpu_edge", "multi"),
        model_families=("all",),
        techniques=(
            "GGUF 2-8 bit quantization",
            "Metal GPU offload",
            "ROCm / Vulkan / SYCL",
            "GGML tensor ops",
            "Flash attention",
            "Speculative decoding",
            "CPU SIMD",
            "Grammar sampling / constrained decoding",
        ),
        category="runtime",
        default_for=("cpu_edge",),
    ),
    InferenceBackend(
        name="ml-explore/mlx",
        url="https://github.com/ml-explore/mlx",
        hardware_tiers=("apple_silicon",),
        model_families=("all",),
        techniques=(
            "Unified memory zero-copy",
            "Lazy evaluation and op fusion",
            "Metal GPU kernels",
            "4-bit / 8-bit quantization",
            "Rotating KV cache",
            "Prompt caching",
        ),
        category="runtime",
        default_for=("apple_silicon",),
    ),
    InferenceBackend(
        name="waybarrios/vllm-mlx",
        url="https://github.com/waybarrios/vllm-mlx",
        hardware_tiers=("apple_silicon",),
        model_families=("Llama", "Qwen", "LLaVA", "Gemma"),
        techniques=(
            "Continuous batching on Metal",
            "PagedAttention unified memory",
            "Prefix caching",
            "SSD-tiered KV cache",
            "KV cache quantization",
            "Vision embedding reuse",
            "OpenAI-compatible API",
        ),
        category="serving_engine",
        secondary_for=("apple_silicon",),
    ),
    InferenceBackend(
        name="modelcloud/GPTQModel",
        url="https://github.com/modelcloud/gptqmodel",
        hardware_tiers=("nvidia_datacenter", "nvidia_consumer", "amd_rocm", "cpu_edge", "multi"),
        model_families=("all",),
        techniques=(
            "GPTQ / AWQ / QQQ / FP8",
            "GGUF / EXL3 / ParoQuant",
            "JIT CUDA kernel compilation",
            "Marlin / Machete kernels",
            "vLLM and SGLang export",
            "MoE quantization lazy loading",
        ),
        category="quantization",
    ),
    InferenceBackend(
        name="chenhongyu2048/LLM-inference-optimization-paper",
        url="https://github.com/chenhongyu2048/LLM-inference-optimization-paper",
        hardware_tiers=("multi",),
        model_families=("all",),
        techniques=(
            "KV cache compression / offload",
            "Progressive sparse attention",
            "HCache",
            "CPU memory tiering",
            "KV budget allocation",
            "GPU bottleneck analysis",
        ),
        category="research_list",
    ),
    InferenceBackend(
        name="sihyeong/Awesome-LLM-Inference-Engine",
        url="https://github.com/sihyeong/Awesome-LLM-Inference-Engine",
        hardware_tiers=("nvidia_datacenter", "nvidia_consumer", "amd_rocm", "apple_silicon", "cpu_edge", "multi"),
        model_families=("all",),
        techniques=("Engine survey", "Latency", "Throughput", "Scalability", "Ease of use", "Agent workload analysis"),
        category="survey",
    ),
    InferenceBackend(
        name="xlite-dev/Awesome-LLM-Inference",
        url="https://github.com/xlite-dev/Awesome-LLM-Inference",
        hardware_tiers=("multi",),
        model_families=("all",),
        techniques=(
            "FlashAttention variants",
            "PagedAttention",
            "INT8 / INT4",
            "Tensor / sequence parallelism",
            "MHA to MLA conversion",
            "Ring attention",
        ),
        category="research_list",
    ),
    InferenceBackend(
        name="codelion/optillm",
        url="https://github.com/codelion/optillm",
        hardware_tiers=("multi",),
        model_families=("all",),
        techniques=(
            "Mixture-of-agents",
            "Test-time compute scaling",
            "Entropy decoding",
            "Multi-provider load balancing",
            "Two-pass verification",
            "OpenAI-compatible proxy",
        ),
        category="inference_time_scaling",
    ),
    InferenceBackend(
        name="AlibabaResearch/flash-llm",
        url="https://github.com/AlibabaResearch/flash-llm",
        hardware_tiers=("nvidia_datacenter", "nvidia_consumer"),
        model_families=("OPT", "GPT", "Llama"),
        techniques=(
            "Unstructured sparsity on tensor cores",
            "Load-as-Sparse / Compute-as-Dense SpMM",
            "Sparse GEMM",
            "Pruned model inference",
        ),
        category="kernel_library",
    ),
)


def list_backends(*, hardware_tier: str | None = None, category: str | None = None) -> list[InferenceBackend]:
    backends = list(INFERENCE_BACKENDS)
    if hardware_tier is not None:
        backends = [backend for backend in backends if backend.supports_hardware(hardware_tier)]
    if category is not None:
        backends = [backend for backend in backends if backend.category == category]
    return backends


def get_backend(name: str) -> InferenceBackend:
    for backend in INFERENCE_BACKENDS:
        if backend.name == name:
            return backend
    raise KeyError(name)


def default_backend_for_hardware(hardware_tier: str) -> InferenceBackend:
    for backend in INFERENCE_BACKENDS:
        if hardware_tier in backend.default_for:
            return backend
    for backend in INFERENCE_BACKENDS:
        if backend.supports_hardware(hardware_tier) and backend.category in {"serving_engine", "runtime", "orchestration"}:
            return backend
    raise KeyError(hardware_tier)


def backend_capability_report(*, hardware_tier: str, required_techniques: list[str]) -> dict[str, Any]:
    backends = list_backends(hardware_tier=hardware_tier)
    coverage: dict[str, list[str]] = {}
    for technique in required_techniques:
        coverage[technique] = [backend.name for backend in backends if backend.supports_technique(technique)]
    missing = [technique for technique, names in coverage.items() if not names]
    return {
        "hardware_tier": hardware_tier,
        "backend_count": len(backends),
        "default_backend": default_backend_for_hardware(hardware_tier).name,
        "coverage": coverage,
        "missing_techniques": missing,
        "backends": [backend.to_dict() for backend in backends],
    }
