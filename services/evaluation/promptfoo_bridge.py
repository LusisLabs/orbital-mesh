from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from services.decision.service import DecisionService
from services.ingest.service import IngestService
from services.trigger.service import TriggerService
from shared.mesh_runtime import Decision, Trigger, load_fixture, log_runtime_event

from .promptfoo_adapter import PromptfooResult


MESH_ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Mesh Intelligence Promptfoo bridge")
    parser.add_argument("--promptfoo-bin", required=True, help="Path to the promptfoo binary")
    parser.add_argument("--version", action="store_true", help="Print the upstream promptfoo version")
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Run a minimal promptfoo eval and exit 0 on success",
    )
    args = parser.parse_args()

    if args.version:
        raise SystemExit(_passthrough(args.promptfoo_bin, ["--version"]))

    if args.healthcheck:
        trigger, decision = _sample_contract()
        result = _run_promptfoo_eval(args.promptfoo_bin, trigger, decision)
        if result.passed:
            print("promptfoo bridge healthcheck passed")
            return
        raise SystemExit("; ".join(result.notes))

    payload = json.load(sys.stdin)
    trigger = Trigger.from_dict(payload["trigger"])
    decision = Decision.from_dict(payload["decision"])
    _emit_result(_run_promptfoo_eval(args.promptfoo_bin, trigger, decision))


def _passthrough(promptfoo_bin: str, extra_args: list[str]) -> int:
    completed = subprocess.run(
        [promptfoo_bin] + extra_args,
        cwd=MESH_ROOT,
        check=False,
        text=True,
    )
    return completed.returncode


def _emit_result(result: PromptfooResult) -> None:
    json.dump(
        {
            "passed": result.passed,
            "score": result.score,
            "notes": result.notes,
            "mode": result.mode,
            "artifacts": result.artifacts,
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")


def _run_promptfoo_eval(promptfoo_bin: str, trigger: Trigger, decision: Decision) -> PromptfooResult:
    with tempfile.TemporaryDirectory(prefix="mesh-promptfoo-") as tmp_dir:
        temp_root = Path(tmp_dir)
        results_path = _write_promptfoo_files(temp_root, trigger, decision)
        completed = subprocess.run(
            [
                promptfoo_bin,
                "eval",
                "-c",
                str(temp_root / "promptfooconfig.json"),
                "--no-cache",
                "--output",
                str(results_path),
            ],
            cwd=temp_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        artifact = _parse_promptfoo_output(results_path)
        stdout_note = completed.stdout.strip()
        stderr_note = completed.stderr.strip()

    if completed.returncode != 0:
        notes = []
        if stderr_note:
            notes.append(stderr_note)
        elif stdout_note:
            notes.append(stdout_note)
        else:
            notes.append("promptfoo eval failed")
        if artifact is not None:
            notes.extend(artifact.get("notes", []))
        result = PromptfooResult(
            passed=False,
            score=0.0,
            notes=notes,
            mode="cli_error",
            artifacts=artifact,
        )
        log_runtime_event("promptfoo_bridge_failed", passed=False, notes=notes, has_artifact=artifact is not None)
        return result

    if artifact is None:
        result = PromptfooResult(
            passed=False,
            score=0.0,
            notes=["promptfoo eval completed but produced no parseable JSON output"],
            mode="cli_error",
        )
        log_runtime_event("promptfoo_bridge_failed", passed=False, notes=result.notes, has_artifact=False)
        return result

    notes = list(artifact.get("notes", []))
    if stdout_note:
        notes.append(stdout_note)
    if not notes:
        notes.append("promptfoo eval completed via CLI bridge")
    result = PromptfooResult(
        passed=bool(artifact["passed"]),
        score=float(artifact["score"]),
        notes=notes,
        mode="promptfoo",
        artifacts=artifact,
    )
    log_runtime_event(
        "promptfoo_bridge_completed",
        passed=result.passed,
        score=result.score,
        assertion_count=len(result.artifacts.get("assertions", [])) if result.artifacts else 0,
    )
    return result


def _write_promptfoo_files(temp_root: Path, trigger: Trigger, decision: Decision) -> Path:
    provider_path = temp_root / "provider.py"
    provider_path.write_text(
        "def call_api(prompt, options, context):\n"
        "    return {'output': prompt}\n"
    )

    contract_json = json.dumps(
        {
            "trigger": trigger.to_dict(),
            "decision": decision.to_dict(),
        },
        sort_keys=True,
    )
    _write_assert_file(temp_root / "assert_regression.py", ASSERT_REGRESSION)
    _write_assert_file(temp_root / "assert_confidence.py", ASSERT_CONFIDENCE)
    _write_assert_file(temp_root / "assert_action.py", ASSERT_ACTION)
    _write_assert_file(temp_root / "assert_risk.py", ASSERT_RISK)

    config = {
        "description": "mesh-intelligence promptfoo bridge",
        "prompts": [
            "{{contract_json}}",
        ],
        "providers": [
            "file://provider.py",
        ],
        "tests": [
            {
                "vars": {
                    "contract_json": contract_json,
                },
                "assert": [
                    {
                        "type": "python",
                        "value": "file://assert_regression.py",
                    },
                    {
                        "type": "python",
                        "value": "file://assert_confidence.py",
                    },
                    {
                        "type": "python",
                        "value": "file://assert_action.py",
                    },
                    {
                        "type": "python",
                        "value": "file://assert_risk.py",
                    },
                ],
            }
        ],
    }
    (temp_root / "promptfooconfig.json").write_text(json.dumps(config, indent=2))
    return temp_root / "results.json"


def _write_assert_file(path: Path, body: str) -> None:
    path.write_text(body)


def _parse_promptfoo_output(results_path: Path) -> dict | None:
    if not results_path.exists():
        return None
    data = json.loads(results_path.read_text())
    outputs = data.get("results", {}).get("outputs", [])
    if not outputs:
        return None
    first_output = outputs[0]
    passed = bool(first_output.get("pass", first_output.get("success", False)))
    score = float(first_output.get("score", 0.0))
    assertions = _extract_assertions(first_output)
    notes = [item["reason"] for item in assertions if item.get("reason")] or [f"promptfoo pass={passed} score={score}"]
    return {
        "passed": passed,
        "score": score,
        "notes": notes,
        "assertions": assertions,
        "result_file": results_path.name,
        "stats": data.get("results", {}).get("stats", {}),
    }


def _extract_assertions(output: dict) -> list[dict]:
    grading = output.get("gradingResult", {})
    candidates = (
        grading.get("componentResults")
        or grading.get("assertions")
        or grading.get("results")
        or output.get("assertions")
        or []
    )
    normalized: list[dict] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "type": item.get("assertion", {}).get("type") or item.get("type"),
                "passed": bool(item.get("pass", item.get("success", False))),
                "score": item.get("score"),
                "reason": item.get("reason") or item.get("metric"),
            }
        )
    return normalized


def _sample_contract() -> tuple[Trigger, Decision]:
    signal = load_fixture("signals", "search_latency_regression.json")
    normalized = IngestService().normalize_signal(signal)
    trigger = TriggerService().detect(normalized)
    if trigger is None:
        raise RuntimeError("fixture signal did not produce a trigger")
    decision = DecisionService().decide(trigger)
    return trigger, decision


ASSERT_HELPERS = """
import json


def _contract(output):
    return json.loads(output)


def _trigger(output):
    return _contract(output)["trigger"]


def _decision(output):
    return _contract(output)["decision"]
"""


ASSERT_REGRESSION = ASSERT_HELPERS + """
def get_assert(output, context):
    trigger = _trigger(output)
    baseline = trigger["metrics"]["baseline_p95_latency_ms"]
    observed = trigger["metrics"]["observed_p95_latency_ms"]
    passed = observed > baseline
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "observed latency exceeds baseline" if passed else "observed latency does not exceed baseline",
    }
"""


ASSERT_CONFIDENCE = ASSERT_HELPERS + """
def get_assert(output, context):
    decision = _decision(output)
    passed = decision["confidence"] >= 0.75
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "confidence meets minimum threshold" if passed else "confidence is below minimum threshold",
    }
"""


ASSERT_ACTION = ASSERT_HELPERS + """
def get_assert(output, context):
    decision = _decision(output)
    passed = decision["execution_plan"]["action"] in {"set_rollout", "open_incident", "record_no_action", "investigate_and_patch"}
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "action matches allowed contract" if passed else "action falls outside the allowed contract",
    }
"""


ASSERT_RISK = ASSERT_HELPERS + """
def get_assert(output, context):
    decision = _decision(output)
    passed = decision["risk"]["level"] != "high"
    return {
        "pass": passed,
        "score": 1.0 if passed else 0.0,
        "reason": "risk remains inside the automated boundary" if passed else "risk is too high for automated execution",
    }
"""


if __name__ == "__main__":
    main()
