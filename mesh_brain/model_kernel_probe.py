from __future__ import annotations

import argparse
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .runtime import stable_digest, utc_now


Matrix = list[list[float]]
Weights = dict[str, Matrix]
Gradients = dict[str, Matrix]

GRADIENT_TOLERANCE = 1e-6
FORWARD_TOLERANCE = 1e-12
Q412_DRIFT_TOLERANCE = 0.01


@dataclass(frozen=True)
class MicroTransformerCorrectnessProbe:
    probe_id: str
    generated_at: str
    passed: bool
    loss_before: float
    loss_after_adam: float
    max_forward_delta: float
    max_gradient_relative_error: float
    q412_max_logit_delta: float
    deterministic_digest: str
    checks: dict[str, Any]
    source_influences: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MicroRuntimeBenchmark:
    benchmark_id: str
    generated_at: str
    local_target: dict[str, Any]
    guidance_targets: list[dict[str, Any]]
    gate: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelKernelProbeResult:
    result_id: str
    generated_at: str
    status: str
    release_decision: str
    correctness: MicroTransformerCorrectnessProbe
    runtime_benchmark: MicroRuntimeBenchmark
    gate: dict[str, Any]
    artifact_paths: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "generated_at": self.generated_at,
            "status": self.status,
            "release_decision": self.release_decision,
            "correctness": self.correctness.to_dict(),
            "runtime_benchmark": self.runtime_benchmark.to_dict(),
            "gate": dict(self.gate),
            "artifact_paths": dict(self.artifact_paths),
        }


def run_micro_transformer_correctness_probe() -> MicroTransformerCorrectnessProbe:
    weights = _reference_weights()
    forward = _forward_full_sequence(weights)
    token_forward = _forward_token_by_token(weights)
    max_forward_delta = _max_delta(forward["y"], token_forward["y"])
    gradients = _backward(weights, forward)
    max_gradient_error = _max_gradient_relative_error(weights, gradients)
    updated = _adam_step(weights, gradients, learning_rate=0.005)
    loss_after = float(_forward_full_sequence(updated)["loss"])
    q412_logits = _forward_full_sequence(_dequantize_q412(_quantize_q412(weights)))["y"]
    q412_delta = _max_delta(forward["y"], q412_logits)
    checks = {
        "full_sequence_matches_token_by_token": max_forward_delta <= FORWARD_TOLERANCE,
        "explicit_gradients_match_finite_difference": max_gradient_error <= GRADIENT_TOLERANCE,
        "adam_step_reduces_loss": loss_after < float(forward["loss"]),
        "q4_12_quantization_within_tolerance": q412_delta <= Q412_DRIFT_TOLERANCE,
        "gradient_tolerance": GRADIENT_TOLERANCE,
        "forward_tolerance": FORWARD_TOLERANCE,
        "q4_12_drift_tolerance": Q412_DRIFT_TOLERANCE,
    }
    digest = stable_digest(
        {
            "loss_before": _round_metric(float(forward["loss"])),
            "loss_after_adam": _round_metric(loss_after),
            "max_forward_delta": _round_metric(max_forward_delta),
            "max_gradient_relative_error": _round_metric(max_gradient_error),
            "q412_max_logit_delta": _round_metric(q412_delta),
            "y": _round_matrix(forward["y"]),
            "gradients": {name: _round_matrix(value) for name, value in gradients.items()},
        }
    )
    return MicroTransformerCorrectnessProbe(
        probe_id=f"mesh_brain_micro_transformer_{digest[:12]}",
        generated_at=utc_now(),
        passed=all(
            bool(checks[name])
            for name in (
                "full_sequence_matches_token_by_token",
                "explicit_gradients_match_finite_difference",
                "adam_step_reduces_loss",
                "q4_12_quantization_within_tolerance",
            )
        ),
        loss_before=_round_metric(float(forward["loss"])),
        loss_after_adam=_round_metric(loss_after),
        max_forward_delta=_round_metric(max_forward_delta),
        max_gradient_relative_error=_round_metric(max_gradient_error),
        q412_max_logit_delta=_round_metric(q412_delta),
        deterministic_digest=digest,
        checks=checks,
        source_influences=[
            "microgpt.apl: explicit matrix gradients, no autograd dependency, full-sequence versus KV-style parity",
            "talos-vs-macbook: batch-1 tiny-model runtime overhead, fixed-point drift, Apple Silicon CPU-first guidance",
        ],
    )


def run_micro_runtime_benchmark(*, iterations: int = 2000) -> MicroRuntimeBenchmark:
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    weights = _reference_weights()
    start = time.perf_counter()
    checksum = 0.0
    for _ in range(iterations):
        result = _forward_token_by_token(weights)
        checksum += float(result["y"][-1][-1])
    elapsed = max(time.perf_counter() - start, 1e-12)
    tokens_per_second = iterations / elapsed
    local_target = {
        "name": "python_reference_token_by_token",
        "status": "executed",
        "hardware_tier": "local_cpu",
        "implementation": "pure_python_reference",
        "iterations": iterations,
        "elapsed_seconds": round(elapsed, 6),
        "tokens_per_second": round(tokens_per_second, 2),
        "checksum": _round_metric(checksum),
        "role": "correctness_and_overhead_floor_only",
        "promotion_use": "does_not_set_production_throughput_claims",
    }
    guidance_targets = [
        {
            "name": "apple_silicon_native_cpu",
            "status": "profile_only",
            "hardware_tier": "apple_silicon",
            "implementation": "native_cpu_neon_or_equivalent",
            "guidance": "prefer for tiny batch-1 kernels when framework dispatch dominates arithmetic",
            "required_mesh_gate": "must provide measured local artifact before serving promotion",
        },
        {
            "name": "apple_silicon_mlx_gpu",
            "status": "profile_only",
            "hardware_tier": "apple_silicon",
            "implementation": "mlx_gpu",
            "guidance": "do not assume GPU wins for tiny batch-1 probes; require batching or measured latency proof",
            "required_mesh_gate": "backend_matrix_or_load_smoke_with_p50_p95_p99",
        },
        {
            "name": "q4_12_fixed_point",
            "status": "drift_checked_by_correctness_probe",
            "hardware_tier": "cpu_edge_or_fpga",
            "implementation": "fixed_point_q4_12",
            "guidance": "acceptable only when quantization drift stays below the deterministic logit-delta threshold",
            "required_mesh_gate": "q4_12_quantization_within_tolerance",
        },
    ]
    gate = {
        "passed": tokens_per_second > 0.0 and math.isfinite(tokens_per_second),
        "decision": "pass" if tokens_per_second > 0.0 and math.isfinite(tokens_per_second) else "block",
        "reasons": [] if tokens_per_second > 0.0 and math.isfinite(tokens_per_second) else ["runtime_benchmark_failed"],
        "required": ["local_reference_executes", "no_production_throughput_claim_without_measured_backend_artifact"],
    }
    digest = stable_digest({"local_target": local_target, "guidance_targets": guidance_targets, "gate": gate})
    return MicroRuntimeBenchmark(
        benchmark_id=f"mesh_brain_micro_runtime_{digest[:12]}",
        generated_at=utc_now(),
        local_target=local_target,
        guidance_targets=guidance_targets,
        gate=gate,
    )


def run_model_kernel_probe(
    *,
    output_directory: str | Path,
    benchmark_iterations: int = 2000,
) -> ModelKernelProbeResult:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    correctness = run_micro_transformer_correctness_probe()
    runtime_benchmark = run_micro_runtime_benchmark(iterations=benchmark_iterations)
    gate = _model_kernel_gate(correctness=correctness, runtime_benchmark=runtime_benchmark)
    release_decision = str(gate["decision"])
    status = "completed" if release_decision == "pass" else "blocked"
    result_id = f"mesh_brain_model_kernel_{stable_digest({'correctness': correctness.probe_id, 'runtime': runtime_benchmark.benchmark_id, 'gate': gate})[:12]}"
    artifact_paths = write_model_kernel_probe_artifacts(
        output_directory=output_path,
        result={
            "result_id": result_id,
            "generated_at": utc_now(),
            "status": status,
            "release_decision": release_decision,
            "correctness": correctness.to_dict(),
            "runtime_benchmark": runtime_benchmark.to_dict(),
            "gate": gate,
        },
    )
    return ModelKernelProbeResult(
        result_id=result_id,
        generated_at=utc_now(),
        status=status,
        release_decision=release_decision,
        correctness=correctness,
        runtime_benchmark=runtime_benchmark,
        gate=gate,
        artifact_paths=artifact_paths,
    )


def write_model_kernel_probe_artifacts(*, output_directory: str | Path, result: dict[str, Any]) -> dict[str, str]:
    import json

    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    files = {
        "model_kernel_correctness.json": result["correctness"],
        "model_kernel_runtime_benchmark.json": result["runtime_benchmark"],
        "model_kernel_gate.json": result["gate"],
        "model_kernel_probe_summary.json": result,
    }
    written: dict[str, str] = {}
    for name, payload in files.items():
        path = output_path / name
        path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
        written[name.removesuffix(".json")] = str(path)
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Mesh Brain deterministic model-kernel probe.")
    parser.add_argument("--output", required=True, help="Directory for model-kernel probe artifacts.")
    parser.add_argument("--benchmark-iterations", type=int, default=2000)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    import json

    args = build_parser().parse_args(argv)
    result = run_model_kernel_probe(
        output_directory=args.output,
        benchmark_iterations=args.benchmark_iterations,
    )
    if args.json:
        print(json.dumps(result.to_dict(), sort_keys=True, default=str))
    else:
        print(f"status={result.status}")
        print(f"release_decision={result.release_decision}")
        print(f"max_gradient_relative_error={result.correctness.max_gradient_relative_error}")
        print(f"q412_max_logit_delta={result.correctness.q412_max_logit_delta}")
    return 0 if result.release_decision == "pass" else 1


def _model_kernel_gate(
    *,
    correctness: MicroTransformerCorrectnessProbe,
    runtime_benchmark: MicroRuntimeBenchmark,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not correctness.passed:
        reasons.extend([name for name, passed in correctness.checks.items() if isinstance(passed, bool) and not passed])
    if not runtime_benchmark.gate["passed"]:
        reasons.extend(runtime_benchmark.gate["reasons"])
    return {
        "decision": "pass" if not reasons else "block",
        "passed": not reasons,
        "reasons": reasons,
        "required": [
            "full_sequence_token_by_token_parity",
            "explicit_gradient_finite_difference_parity",
            "adam_step_reduces_loss",
            "fixed_point_q4_12_drift_bound",
            "runtime_reference_executes",
        ],
        "metrics": {
            "loss_before": correctness.loss_before,
            "loss_after_adam": correctness.loss_after_adam,
            "max_forward_delta": correctness.max_forward_delta,
            "max_gradient_relative_error": correctness.max_gradient_relative_error,
            "q412_max_logit_delta": correctness.q412_max_logit_delta,
            "reference_tokens_per_second": runtime_benchmark.local_target["tokens_per_second"],
        },
    }


def _reference_inputs() -> Matrix:
    return [
        [0.35, -0.20],
        [0.10, 0.45],
        [-0.30, 0.25],
    ]


def _reference_targets() -> Matrix:
    return [
        [0.12, -0.05],
        [-0.03, 0.18],
        [0.07, 0.02],
    ]


def _reference_weights() -> Weights:
    return {
        "wq": [[0.21, -0.17], [0.08, 0.14]],
        "wk": [[-0.11, 0.19], [0.16, 0.07]],
        "wv": [[0.13, -0.05], [-0.09, 0.22]],
        "wo": [[0.18, -0.12], [0.05, 0.09]],
    }


def _forward_full_sequence(weights: Weights) -> dict[str, Any]:
    x = _reference_inputs()
    target = _reference_targets()
    q = _matmul(x, weights["wq"])
    k = _matmul(x, weights["wk"])
    v = _matmul(x, weights["wv"])
    scale = 1.0 / math.sqrt(float(len(x[0])))
    scores = _zeros(len(x), len(x))
    attention = _zeros(len(x), len(x))
    for row in range(len(x)):
        row_scores = []
        for column in range(row + 1):
            score = _dot(q[row], k[column]) * scale
            scores[row][column] = score
            row_scores.append(score)
        row_attention = _softmax(row_scores)
        for column, value in enumerate(row_attention):
            attention[row][column] = value
    hidden = _matmul(attention, v)
    y = _matmul(hidden, weights["wo"])
    loss = _mse_loss(y, target)
    return {
        "x": x,
        "target": target,
        "q": q,
        "k": k,
        "v": v,
        "scores": scores,
        "attention": attention,
        "hidden": hidden,
        "y": y,
        "loss": loss,
    }


def _forward_token_by_token(weights: Weights) -> dict[str, Any]:
    x = _reference_inputs()
    target = _reference_targets()
    keys: Matrix = []
    values: Matrix = []
    outputs: Matrix = []
    scale = 1.0 / math.sqrt(float(len(x[0])))
    for position, token in enumerate(x):
        q = _vecmat(token, weights["wq"])
        keys.append(_vecmat(token, weights["wk"]))
        values.append(_vecmat(token, weights["wv"]))
        logits = [_dot(q, keys[index]) * scale for index in range(position + 1)]
        attn = _softmax(logits)
        hidden = [sum(attn[index] * values[index][dim] for index in range(position + 1)) for dim in range(len(values[0]))]
        outputs.append(_vecmat(hidden, weights["wo"]))
    return {"y": outputs, "loss": _mse_loss(outputs, target)}


def _backward(weights: Weights, cache: dict[str, Any]) -> Gradients:
    x = cache["x"]
    target = cache["target"]
    q = cache["q"]
    k = cache["k"]
    v = cache["v"]
    attention = cache["attention"]
    hidden = cache["hidden"]
    y = cache["y"]
    count = float(len(y) * len(y[0]))
    dy = [[(y[row][col] - target[row][col]) / count for col in range(len(y[0]))] for row in range(len(y))]
    dwo = _matmul(_transpose(hidden), dy)
    dhidden = _matmul(dy, _transpose(weights["wo"]))
    dattention = _matmul(dhidden, _transpose(v))
    dv = _matmul(_transpose(attention), dhidden)
    dscores = _zeros(len(attention), len(attention))
    for row in range(len(attention)):
        allowed = row + 1
        dot_da_a = sum(dattention[row][column] * attention[row][column] for column in range(allowed))
        for column in range(allowed):
            dscores[row][column] = attention[row][column] * (dattention[row][column] - dot_da_a)
    scale = 1.0 / math.sqrt(float(len(x[0])))
    dq = _zeros(len(q), len(q[0]))
    dk = _zeros(len(k), len(k[0]))
    for row in range(len(q)):
        for column in range(len(k)):
            if dscores[row][column] == 0.0:
                continue
            for dim in range(len(q[0])):
                dq[row][dim] += dscores[row][column] * k[column][dim] * scale
                dk[column][dim] += dscores[row][column] * q[row][dim] * scale
    return {
        "wq": _matmul(_transpose(x), dq),
        "wk": _matmul(_transpose(x), dk),
        "wv": _matmul(_transpose(x), dv),
        "wo": dwo,
    }


def _max_gradient_relative_error(weights: Weights, gradients: Gradients) -> float:
    epsilon = 1e-5
    max_error = 0.0
    for name, matrix in weights.items():
        for row in range(len(matrix)):
            for column in range(len(matrix[row])):
                plus = _copy_weights(weights)
                minus = _copy_weights(weights)
                plus[name][row][column] += epsilon
                minus[name][row][column] -= epsilon
                numerical = (float(_forward_full_sequence(plus)["loss"]) - float(_forward_full_sequence(minus)["loss"])) / (2.0 * epsilon)
                explicit = gradients[name][row][column]
                denominator = max(1e-12, abs(numerical) + abs(explicit))
                max_error = max(max_error, abs(numerical - explicit) / denominator)
    return max_error


def _adam_step(
    weights: Weights,
    gradients: Gradients,
    *,
    learning_rate: float,
    beta1: float = 0.9,
    beta2: float = 0.999,
    epsilon: float = 1e-8,
) -> Weights:
    updated = _copy_weights(weights)
    for name, matrix in weights.items():
        for row in range(len(matrix)):
            for column in range(len(matrix[row])):
                grad = gradients[name][row][column]
                moment = (1.0 - beta1) * grad
                velocity = (1.0 - beta2) * grad * grad
                moment_hat = moment / (1.0 - beta1)
                velocity_hat = velocity / (1.0 - beta2)
                updated[name][row][column] = matrix[row][column] - learning_rate * moment_hat / (math.sqrt(velocity_hat) + epsilon)
    return updated


def _quantize_q412(weights: Weights) -> dict[str, list[list[int]]]:
    quantized: dict[str, list[list[int]]] = {}
    for name, matrix in weights.items():
        quantized[name] = [
            [max(-32768, min(32767, int(round(value * 4096.0)))) for value in row]
            for row in matrix
        ]
    return quantized


def _dequantize_q412(weights: dict[str, list[list[int]]]) -> Weights:
    return {
        name: [[value / 4096.0 for value in row] for row in matrix]
        for name, matrix in weights.items()
    }


def _matmul(left: Matrix, right: Matrix) -> Matrix:
    if not left or not right:
        return []
    right_t = _transpose(right)
    return [[_dot(row, column) for column in right_t] for row in left]


def _vecmat(vector: list[float], matrix: Matrix) -> list[float]:
    return [_dot(vector, column) for column in _transpose(matrix)]


def _transpose(matrix: Matrix) -> Matrix:
    return [list(column) for column in zip(*matrix)]


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _softmax(values: list[float]) -> list[float]:
    maximum = max(values)
    exps = [math.exp(value - maximum) for value in values]
    total = sum(exps)
    return [value / total for value in exps]


def _mse_loss(values: Matrix, target: Matrix) -> float:
    total = 0.0
    count = 0
    for row in range(len(values)):
        for column in range(len(values[row])):
            diff = values[row][column] - target[row][column]
            total += 0.5 * diff * diff
            count += 1
    return total / float(count)


def _zeros(rows: int, columns: int) -> Matrix:
    return [[0.0 for _ in range(columns)] for _ in range(rows)]


def _copy_weights(weights: Weights) -> Weights:
    return {name: [list(row) for row in matrix] for name, matrix in weights.items()}


def _max_delta(left: Matrix, right: Matrix) -> float:
    return max(
        abs(left[row][column] - right[row][column])
        for row in range(len(left))
        for column in range(len(left[row]))
    )


def _round_matrix(matrix: Matrix) -> Matrix:
    return [[_round_metric(value) for value in row] for row in matrix]


def _round_metric(value: float) -> float:
    return round(float(value), 12)


if __name__ == "__main__":
    raise SystemExit(main())
