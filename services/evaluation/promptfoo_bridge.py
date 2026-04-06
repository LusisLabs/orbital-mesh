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
from shared.mesh_runtime import Decision, Trigger, load_fixture

from .promptfoo_adapter import PromptfooResult, evaluate_decision_contract


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
        ok, detail = _run_promptfoo_eval(args.promptfoo_bin, trigger, decision)
        if ok:
            print(detail)
            return
        raise SystemExit(detail)

    payload = json.load(sys.stdin)
    trigger = Trigger.from_dict(payload["trigger"])
    decision = Decision.from_dict(payload["decision"])
    ok, detail = _run_promptfoo_eval(args.promptfoo_bin, trigger, decision)
    if not ok:
        raise SystemExit(detail)

    result = evaluate_decision_contract(trigger, decision, mode="promptfoo")
    notes = list(result.notes)
    notes.append(detail)
    _emit_result(
        PromptfooResult(
            passed=result.passed,
            score=result.score,
            notes=notes,
            mode=result.mode,
        )
    )


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
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")


def _run_promptfoo_eval(promptfoo_bin: str, trigger: Trigger, decision: Decision) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="mesh-promptfoo-") as tmp_dir:
        temp_root = Path(tmp_dir)
        _write_promptfoo_files(temp_root, trigger, decision)
        completed = subprocess.run(
            [
                promptfoo_bin,
                "eval",
                "-c",
                str(temp_root / "promptfooconfig.json"),
                "--no-cache",
            ],
            cwd=temp_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "promptfoo eval failed"
        return False, detail
    return True, "promptfoo eval completed via CLI bridge"


def _write_promptfoo_files(temp_root: Path, trigger: Trigger, decision: Decision) -> None:
    provider_path = temp_root / "provider.py"
    provider_path.write_text(
        "def call_api(prompt, options, context):\n"
        "    return {'output': prompt}\n"
    )

    assert_path = temp_root / "assert.py"
    assert_path.write_text(
        "def get_assert(output, context):\n"
        "    return {'pass': True, 'score': 1.0, 'reason': 'promptfoo bridge executed'}\n"
    )

    config = {
        "description": "mesh-intelligence promptfoo bridge",
        "prompts": [
            "Evaluate {{decision_id}} for trigger {{trigger_id}}",
        ],
        "providers": [
            "file://provider.py",
        ],
        "tests": [
            {
                "vars": {
                    "decision_id": decision.decision_id,
                    "trigger_id": trigger.trigger_id,
                    "decision_json": json.dumps(decision.to_dict(), sort_keys=True),
                    "trigger_json": json.dumps(trigger.to_dict(), sort_keys=True),
                },
                "assert": [
                    {
                        "type": "python",
                        "value": "file://assert.py",
                    }
                ],
            }
        ],
    }
    (temp_root / "promptfooconfig.json").write_text(json.dumps(config, indent=2))


def _sample_contract() -> tuple[Trigger, Decision]:
    signal = load_fixture("signals", "search_latency_regression.json")
    normalized = IngestService().normalize_signal(signal)
    trigger = TriggerService().detect(normalized)
    if trigger is None:
        raise RuntimeError("fixture signal did not produce a trigger")
    decision = DecisionService().decide(trigger)
    return trigger, decision


if __name__ == "__main__":
    main()
