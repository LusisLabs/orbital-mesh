from __future__ import annotations

import argparse
import copy
import curses
import json
import textwrap
from dataclasses import dataclass
from typing import Callable

from services.orchestrator.goose_adapter import GooseAdapter, GooseExecutionResult
from services.orchestrator.service import OrchestratorService
from services.pipeline import FirstSlicePipeline
from shared.mesh_runtime import RuntimeConfig, RuntimeStateStore, load_fixture


@dataclass
class ScenarioDefinition:
    key: str
    title: str
    description: str
    mutate_signal: Callable[[dict], None]
    expected_action: str
    intent_label: str
    operator_note: str
    sticky_signal_id: bool = False
    pipeline_factory: Callable[[RuntimeConfig, RuntimeStateStore], FirstSlicePipeline] | None = None


@dataclass(frozen=True)
class PanelBounds:
    top: int
    left: int
    height: int
    width: int


class RetryRecoveryAdapter(GooseAdapter):
    def __init__(self) -> None:
        self.calls = 0
        self.incident_calls = 0

    def execute_decision(self, decision, idempotency_key: str) -> GooseExecutionResult:
        self.calls += 1
        if self.calls < 3:
            return GooseExecutionResult(
                status="failed",
                external_refs={},
                failure={"reason": "transient_api_failure", "retry_after_seconds": 1},
                retryable=True,
            )
        return GooseExecutionResult(
            status="succeeded",
            external_refs={
                "audit_log_id": f"audit_{decision.decision_id}",
                "flag_change_id": "ffchg_retry_recovered",
            },
        )

    def open_execution_incident(self, decision, failure_reason: str) -> dict[str, str]:
        self.incident_calls += 1
        return {"incident_id": f"inc_{decision.decision_id}"}


class RetryExhaustedAdapter(GooseAdapter):
    def __init__(self) -> None:
        self.calls = 0
        self.incident_calls = 0

    def execute_decision(self, decision, idempotency_key: str) -> GooseExecutionResult:
        self.calls += 1
        return GooseExecutionResult(
            status="failed",
            external_refs={"audit_log_id": f"audit_{decision.decision_id}"},
            failure={"reason": "transient_api_failure", "retry_after_seconds": 31},
            retryable=True,
        )

    def open_execution_incident(self, decision, failure_reason: str) -> dict[str, str]:
        self.incident_calls += 1
        return {"incident_id": f"inc_{decision.decision_id}"}


def _no_op(_: dict) -> None:
    return None


def _reduce_rollout(signal: dict) -> None:
    signal["request_telemetry"]["observed"]["p95_latency_ms"] = 530
    signal["request_telemetry"]["observed"]["error_rate"] = 0.018
    signal["request_telemetry"]["observed"]["timeout_rate"] = 0.015
    signal["post_action_observations"]["10m"]["p95_latency_ms"] = 450
    signal["post_action_observations"]["10m"]["error_rate"] = 0.014
    signal["post_action_observations"]["30m"]["p95_latency_ms"] = 435
    signal["post_action_observations"]["30m"]["error_rate"] = 0.014


def _no_action(signal: dict) -> None:
    _reduce_rollout(signal)
    signal["request_telemetry"]["observed"]["timeout_rate"] = 0.01
    signal["related_context"]["flag_causality_confidence"] = 0.25
    signal["post_action_observations"]["10m"]["p95_latency_ms"] = 470


def _approval_required(signal: dict) -> None:
    signal["segment"]["customer_tier"] = "strategic"


def _guardrail_rollback(signal: dict) -> None:
    signal["post_action_observations"]["30m"]["business_guardrail_breached"] = True


def _recurrence(signal: dict) -> None:
    signal["related_context"]["regressions_last_7d"] = 3


def _with_retry_recovery(config: RuntimeConfig, state_store: RuntimeStateStore) -> FirstSlicePipeline:
    clock_state = {"now": 0.0}

    def fake_clock() -> float:
        return clock_state["now"]

    def fake_sleep(seconds: float) -> None:
        clock_state["now"] += seconds

    return FirstSlicePipeline(
        config=config,
        state_store=state_store,
        orchestrator=OrchestratorService(
            adapter=RetryRecoveryAdapter(),
            config=config,
            clock=fake_clock,
            sleeper=fake_sleep,
        ),
    )


def _with_retry_exhausted(config: RuntimeConfig, state_store: RuntimeStateStore) -> FirstSlicePipeline:
    clock_state = {"now": 0.0}

    def fake_clock() -> float:
        return clock_state["now"]

    def fake_sleep(seconds: float) -> None:
        clock_state["now"] += seconds

    return FirstSlicePipeline(
        config=config,
        state_store=state_store,
        orchestrator=OrchestratorService(
            adapter=RetryExhaustedAdapter(),
            config=config,
            clock=fake_clock,
            sleeper=fake_sleep,
        ),
    )


def build_scenarios() -> list[ScenarioDefinition]:
    return [
        ScenarioDefinition(
            "disable-flag",
            "Disable Flag",
            "Default sustained regression path.",
            _no_op,
            expected_action="set_rollout -> 0%",
            intent_label="containment",
            operator_note="Fast rollback path for a confident single-flag regression.",
        ),
        ScenarioDefinition(
            "reduce-rollout",
            "Reduce Rollout",
            "Moderate regression that reduces rollout to 10%.",
            _reduce_rollout,
            expected_action="set_rollout -> 10%",
            intent_label="progressive mitigation",
            operator_note="Preserves partial exposure while pulling blast radius down.",
        ),
        ScenarioDefinition(
            "no-action",
            "No Action",
            "Valid trigger with weak causality, audit only.",
            _no_action,
            expected_action="record_no_action",
            intent_label="observe",
            operator_note="Keeps the loop accountable when evidence is not strong enough to change production.",
        ),
        ScenarioDefinition(
            "approval-required",
            "Approval Required",
            "Protected customer tier forces human review.",
            _approval_required,
            expected_action="route_to_human_review",
            intent_label="governance",
            operator_note="Protected-scope rules should stop autonomous execution before actuation.",
        ),
        ScenarioDefinition(
            "duplicate-replay",
            "Duplicate Replay",
            "Keeps the same trigger identity to demonstrate duplicate suppression on repeated runs.",
            _no_op,
            expected_action="reject_duplicate",
            intent_label="idempotency",
            operator_note="Demonstrates evaluation ledger behavior across repeated trigger identities.",
            sticky_signal_id=True,
        ),
        ScenarioDefinition(
            "retry-recovery",
            "Retry Recovery",
            "Transient execution failures recover before the retry budget is exhausted.",
            _no_op,
            expected_action="retry_then_succeed",
            intent_label="resilience",
            operator_note="Exercises orchestration retries without human escalation.",
            pipeline_factory=_with_retry_recovery,
        ),
        ScenarioDefinition(
            "retry-exhausted",
            "Retry Exhausted",
            "Transient execution failures exceed the retry window and open an incident.",
            _no_op,
            expected_action="open_incident",
            intent_label="resilience",
            operator_note="Shows the fail-safe path when transient execution never stabilizes.",
            pipeline_factory=_with_retry_exhausted,
        ),
        ScenarioDefinition(
            "guardrail-rollback",
            "Guardrail Rollback",
            "Post-action business guardrail breach triggers rollback handling.",
            _guardrail_rollback,
            expected_action="rollback_on_guardrail",
            intent_label="post-action safety",
            operator_note="Surfaces when recovery metrics improve but business guardrails still fail.",
        ),
        ScenarioDefinition(
            "recurrence",
            "Recurrence Marker",
            "Successful recovery also marks the flag for human-owned remediation.",
            _recurrence,
            expected_action="mark_recurrence",
            intent_label="follow-up ownership",
            operator_note="Captures patterns that should move from runtime mitigation into remediation work.",
        ),
    ]


class MeshOperatorController:
    def __init__(self, state_directory: str | None = None):
        base_config = RuntimeConfig.from_env()
        self.state_directory = state_directory or base_config.state_directory
        self.state_store = RuntimeStateStore(self.state_directory)
        self.scenarios = build_scenarios()
        self._scenario_index = {scenario.key: scenario for scenario in self.scenarios}
        self._scenario_title_index = {scenario.title: scenario for scenario in self.scenarios}
        self._run_counter = 0

    def get_scenario(self, key: str) -> ScenarioDefinition:
        return self._scenario_index[key]

    def clear_state(self) -> None:
        self.state_store.reset()

    def list_recent_runs(self, limit: int = 12) -> list[dict]:
        return self.state_store.list_recent_runs(limit=limit)

    def list_evaluations(self) -> dict[str, dict]:
        return self.state_store.list_evaluations()

    def load_run_snapshot(self, run_id: str) -> dict | None:
        return self.state_store.load_run_snapshot(run_id)

    def dashboard_metrics(self, limit: int = 50) -> dict[str, int]:
        runs = self.list_recent_runs(limit=limit)
        successful = sum(1 for run in runs if run.get("feedback_outcome") == "successful")
        escalated = sum(1 for run in runs if run.get("feedback_outcome") == "escalated")
        review = sum(1 for run in runs if run.get("execution_status") == "rejected")
        duplicate_blocks = sum(1 for run in runs if run.get("final_recommendation") == "reject")
        total = len(runs)
        return {
            "total_runs": total,
            "successful_runs": successful,
            "escalated_runs": escalated,
            "review_runs": review,
            "duplicate_blocks": duplicate_blocks,
            "evaluation_records": len(self.list_evaluations()),
            "success_rate": int(round((successful / total) * 100)) if total else 0,
        }

    def scenario_activity(self, limit: int = 50) -> dict[str, dict[str, str | int | None]]:
        activity = {
            scenario.key: {
                "runs": 0,
                "badge": "idle",
                "decision_type": None,
                "execution_status": None,
                "feedback_outcome": None,
                "recorded_at": None,
            }
            for scenario in self.scenarios
        }
        for run in self.list_recent_runs(limit=limit):
            scenario = self._scenario_title_index.get(run.get("scenario_name", ""))
            if scenario is None:
                continue
            record = activity[scenario.key]
            record["runs"] = int(record["runs"]) + 1
            if record["recorded_at"] is None:
                record["badge"] = _run_badge(run)
                record["decision_type"] = run.get("decision_type")
                record["execution_status"] = run.get("execution_status")
                record["feedback_outcome"] = run.get("feedback_outcome")
                record["recorded_at"] = run.get("recorded_at")
        return activity

    def scenario_preview(self, key: str) -> dict[str, str | int | float]:
        scenario = self.get_scenario(key)
        signal = self._seed_signal(scenario, preview=True)
        baseline = signal["request_telemetry"]["baseline"]
        observed = signal["request_telemetry"]["observed"]
        post_observation = signal["post_action_observations"]["30m"]
        return {
            "title": scenario.title,
            "intent_label": scenario.intent_label,
            "expected_action": scenario.expected_action,
            "operator_note": scenario.operator_note,
            "environment": signal["environment"],
            "service": signal["service"],
            "endpoint": signal["endpoint"],
            "flag_key": signal["feature_flag"]["flag_key"],
            "current_rollout_pct": signal["feature_flag"]["current_rollout_pct"],
            "previous_rollout_pct": signal["feature_flag"]["previous_rollout_pct"],
            "customer_tier": signal["segment"]["customer_tier"],
            "region": signal["segment"]["region"],
            "regressions_last_7d": signal["related_context"]["regressions_last_7d"],
            "similar_prior_cases": signal["related_context"]["similar_prior_cases"],
            "baseline_p95_latency_ms": baseline["p95_latency_ms"],
            "observed_p95_latency_ms": observed["p95_latency_ms"],
            "baseline_error_rate": baseline["error_rate"],
            "observed_error_rate": observed["error_rate"],
            "baseline_timeout_rate": baseline["timeout_rate"],
            "observed_timeout_rate": observed["timeout_rate"],
            "predicted_30m_p95_latency_ms": post_observation.get("p95_latency_ms", 0),
            "predicted_30m_error_rate": post_observation.get("error_rate", 0.0),
        }

    def run_scenario(
        self,
        key: str,
        evaluation_mode: str,
        orchestration_mode: str,
    ) -> dict:
        scenario = self.get_scenario(key)
        signal = self._seed_signal(scenario, preview=False)
        config = RuntimeConfig.from_env()
        config.evaluation_mode = evaluation_mode
        config.orchestration_mode = orchestration_mode
        config.state_directory = self.state_directory
        pipeline = self._build_pipeline(scenario, config)
        return pipeline.run(signal, scenario_name=scenario.title)

    def _seed_signal(self, scenario: ScenarioDefinition, preview: bool) -> dict:
        signal = copy.deepcopy(load_fixture("signals", "search_latency_regression.json"))
        if preview:
            if not scenario.sticky_signal_id:
                signal["signal_id"] = f"{signal['signal_id']}_{scenario.key}_preview"
        else:
            self._run_counter += 1
            if not scenario.sticky_signal_id:
                signal["signal_id"] = f"{signal['signal_id']}_{scenario.key}_{self._run_counter:04d}"
        scenario.mutate_signal(signal)
        return signal

    def _build_pipeline(self, scenario: ScenarioDefinition, config: RuntimeConfig) -> FirstSlicePipeline:
        if scenario.pipeline_factory is not None:
            return scenario.pipeline_factory(config, self.state_store)
        return FirstSlicePipeline(config=config, state_store=self.state_store)


class MeshOperatorTUI:
    def __init__(self, controller: MeshOperatorController):
        self.controller = controller
        self.evaluation_modes = ["native", "promptfoo"]
        self.orchestration_modes = ["native", "goose", "hermes"]
        self.detail_tabs = ["overview", "evidence", "execution", "json"]
        self.evaluation_mode_index = 0
        self.orchestration_mode_index = 0
        self.detail_tab_index = 0
        self.scenario_index = 0
        self.run_index = 0
        self.detail_scroll = 0
        self.status_message = "Ready"
        self._active_run_id: str | None = None

    @property
    def evaluation_mode(self) -> str:
        return self.evaluation_modes[self.evaluation_mode_index]

    @property
    def orchestration_mode(self) -> str:
        return self.orchestration_modes[self.orchestration_mode_index]

    @property
    def detail_tab(self) -> str:
        return self.detail_tabs[self.detail_tab_index]

    def run(self) -> None:
        curses.wrapper(self._main)

    def _main(self, stdscr) -> None:
        _init_curses()
        stdscr.keypad(True)
        while True:
            runs = self.controller.list_recent_runs(limit=24)
            if runs:
                self.run_index = min(self.run_index, len(runs) - 1)
            else:
                self.run_index = 0
            selected_run = runs[self.run_index] if runs else None
            selected_run_id = selected_run["run_id"] if selected_run else None
            if selected_run_id != self._active_run_id:
                self._active_run_id = selected_run_id
                self.detail_scroll = 0
            snapshot = self.controller.load_run_snapshot(selected_run["run_id"]) if selected_run else None
            metrics = self.controller.dashboard_metrics(limit=50)
            activity = self.controller.scenario_activity(limit=50)
            preview = self.controller.scenario_preview(self.controller.scenarios[self.scenario_index].key)
            self._draw(stdscr, runs, snapshot, metrics, activity, preview)

            key = stdscr.getch()
            if key in (-1, curses.KEY_RESIZE):
                continue
            if key in (ord("q"), 27):
                return
            if key in (curses.KEY_UP, ord("k")):
                self.scenario_index = max(0, self.scenario_index - 1)
                self.detail_scroll = 0
            elif key in (curses.KEY_DOWN, ord("j")):
                self.scenario_index = min(len(self.controller.scenarios) - 1, self.scenario_index + 1)
                self.detail_scroll = 0
            elif key in (curses.KEY_LEFT, ord("h"), ord("p")) and runs:
                self.run_index = min(len(runs) - 1, self.run_index + 1)
                self.detail_scroll = 0
            elif key in (curses.KEY_RIGHT, ord("l"), ord("n")) and runs:
                self.run_index = max(0, self.run_index - 1)
                self.detail_scroll = 0
            elif key in (ord("["),):
                self.detail_tab_index = (self.detail_tab_index - 1) % len(self.detail_tabs)
                self.detail_scroll = 0
                self.status_message = f"inspector -> {self.detail_tab}"
            elif key in (ord("]"),):
                self.detail_tab_index = (self.detail_tab_index + 1) % len(self.detail_tabs)
                self.detail_scroll = 0
                self.status_message = f"inspector -> {self.detail_tab}"
            elif key == curses.KEY_HOME:
                self.run_index = 0
                self.detail_scroll = 0
            elif key == curses.KEY_END and runs:
                self.run_index = len(runs) - 1
                self.detail_scroll = 0
            elif key == curses.KEY_NPAGE:
                self.detail_scroll += 8
            elif key == curses.KEY_PPAGE:
                self.detail_scroll = max(0, self.detail_scroll - 8)
            elif key == ord("e"):
                self.evaluation_mode_index = (self.evaluation_mode_index + 1) % len(self.evaluation_modes)
                self.status_message = f"evaluation mode -> {self.evaluation_mode}"
            elif key == ord("o"):
                self.orchestration_mode_index = (self.orchestration_mode_index + 1) % len(self.orchestration_modes)
                self.status_message = f"orchestration mode -> {self.orchestration_mode}"
            elif ord("1") <= key <= ord("9"):
                scenario_index = key - ord("1")
                if scenario_index < len(self.controller.scenarios):
                    self.scenario_index = scenario_index
                    self.detail_scroll = 0
                    self.status_message = f"scenario -> {self.controller.scenarios[self.scenario_index].title}"
            elif key in (ord("r"), 10, 13):
                scenario = self.controller.scenarios[self.scenario_index]
                result = self.controller.run_scenario(
                    scenario.key,
                    evaluation_mode=self.evaluation_mode,
                    orchestration_mode=self.orchestration_mode,
                )
                self.status_message = _status_line_from_result(result)
                self.run_index = 0
                self.detail_scroll = 0
            elif key == ord("c"):
                self.controller.clear_state()
                self.status_message = "runtime state cleared"
                self.detail_scroll = 0

    def _draw(
        self,
        stdscr,
        runs: list[dict],
        snapshot: dict | None,
        metrics: dict[str, int],
        activity: dict[str, dict[str, str | int | None]],
        preview: dict[str, str | int | float],
    ) -> None:
        stdscr.erase()
        height, width = stdscr.getmaxyx()
        if width < 92 or height < 26:
            self._draw_too_small(stdscr, width, height)
            stdscr.refresh()
            return

        selected_scenario = self.controller.scenarios[self.scenario_index]
        evaluations = self.controller.list_evaluations()

        _write_line(
            stdscr,
            0,
            0,
            "Mesh Intelligence Command Center",
            _attr("accent", bold=True),
        )
        _write_line(
            stdscr,
            1,
            0,
            (
                f"env={preview['environment']}  scenario={selected_scenario.title}  "
                f"inspector={self.detail_tab}  state={self.controller.state_directory}"
            ),
            _attr("muted"),
        )
        _write_line(
            stdscr,
            2,
            0,
            (
                f"modes eval={self.evaluation_mode} exec={self.orchestration_mode}  "
                f"runs={metrics['total_runs']} stable={metrics['successful_runs']} "
                f"page={metrics['escalated_runs']} review={metrics['review_runs']} "
                f"dup={metrics['duplicate_blocks']} success={metrics['success_rate']}%"
            ),
            _attr("normal"),
        )

        body_top = 4
        body_height = height - body_top - 2
        if width >= 136:
            left_width = 34
            middle_width = 42
            right_width = width - left_width - middle_width - 2
            self._draw_scenario_panel(
                stdscr,
                PanelBounds(body_top, 0, body_height, left_width),
                selected_scenario,
                preview,
                activity,
            )
            self._draw_ops_panel(
                stdscr,
                PanelBounds(body_top, left_width + 1, body_height, middle_width),
                runs,
                snapshot,
                metrics,
                evaluations,
            )
            self._draw_inspector_panel(
                stdscr,
                PanelBounds(body_top, left_width + middle_width + 2, body_height, right_width),
                snapshot,
                selected_scenario,
                preview,
            )
        else:
            left_width = 34
            right_width = width - left_width - 1
            upper_height = max(12, min(16, body_height // 2))
            self._draw_scenario_panel(
                stdscr,
                PanelBounds(body_top, 0, body_height, left_width),
                selected_scenario,
                preview,
                activity,
            )
            self._draw_ops_panel(
                stdscr,
                PanelBounds(body_top, left_width + 1, upper_height, right_width),
                runs,
                snapshot,
                metrics,
                evaluations,
            )
            self._draw_inspector_panel(
                stdscr,
                PanelBounds(body_top + upper_height, left_width + 1, body_height - upper_height, right_width),
                snapshot,
                selected_scenario,
                preview,
            )

        self._draw_status_bar(stdscr, width, height)
        stdscr.refresh()

    def _draw_too_small(self, stdscr, width: int, height: int) -> None:
        _write_line(stdscr, 0, 0, "Mesh Intelligence Command Center", _attr("accent", bold=True))
        _write_line(
            stdscr,
            2,
            0,
            f"terminal too small for operator layout ({width}x{height}). enlarge to at least 92x26.",
            _attr("warning", bold=True),
        )
        _write_line(stdscr, 4, 0, f"status: {self.status_message}", _attr("muted"))
        _write_line(stdscr, 6, 0, "controls: j/k scenario  h/l runs  [/] inspector  r run  e/o modes  c clear  q quit")

    def _draw_scenario_panel(
        self,
        stdscr,
        bounds: PanelBounds,
        selected_scenario: ScenarioDefinition,
        preview: dict[str, str | int | float],
        activity: dict[str, dict[str, str | int | None]],
    ) -> None:
        inner = _draw_panel(stdscr, bounds, "Scenario Rail", selected_scenario.intent_label)
        if inner.height < 4:
            return

        row = inner.top
        list_height = min(len(self.controller.scenarios), max(5, inner.height // 2 - 1))
        for index, scenario in enumerate(self.controller.scenarios[:list_height]):
            scenario_activity = activity.get(scenario.key, {})
            badge = str(scenario_activity.get("badge", "idle"))
            line = f"{'>' if index == self.scenario_index else ' '} {scenario.title}"
            padded = _pad(line, inner.width)
            _write_line(stdscr, row, inner.left, padded, _attr("selected") if index == self.scenario_index else _attr("normal"))
            badge_text = _truncate(badge.upper(), min(10, inner.width - 4))
            _write_line(stdscr, row, inner.left + max(0, inner.width - len(badge_text)), badge_text, _status_attr(badge))
            row += 1

        row += 1
        row = _draw_section_divider(stdscr, row, inner.left, inner.width, "Briefing")
        lines = [
            f"Intent: {preview['intent_label']}",
            f"Action: {preview['expected_action']}",
            f"Service: {preview['service']}",
            f"Endpoint: {preview['endpoint']}",
            f"Flag: {preview['flag_key']}  rollout {preview['previous_rollout_pct']}% -> {preview['current_rollout_pct']}%",
            f"Segment: {preview['customer_tier']} / {preview['region']}",
            (
                f"P95: {preview['baseline_p95_latency_ms']} -> {preview['observed_p95_latency_ms']} ms "
                f"({_signed_delta_percent(int(preview['baseline_p95_latency_ms']), int(preview['observed_p95_latency_ms']))})"
            ),
            (
                f"Error: {_format_rate(float(preview['baseline_error_rate']))} -> "
                f"{_format_rate(float(preview['observed_error_rate']))}"
            ),
            (
                f"Timeout: {_format_rate(float(preview['baseline_timeout_rate']))} -> "
                f"{_format_rate(float(preview['observed_timeout_rate']))}"
            ),
            (
                f"History: regressions_7d={preview['regressions_last_7d']}  "
                f"prior_cases={preview['similar_prior_cases']}"
            ),
            f"Last result: {activity.get(selected_scenario.key, {}).get('badge', 'idle')}",
            f"Operator note: {selected_scenario.operator_note}",
        ]
        self._write_wrapped_block(stdscr, row, inner.left, inner.width, lines, inner.top + inner.height)

    def _draw_ops_panel(
        self,
        stdscr,
        bounds: PanelBounds,
        runs: list[dict],
        snapshot: dict | None,
        metrics: dict[str, int],
        evaluations: dict[str, dict],
    ) -> None:
        inner = _draw_panel(stdscr, bounds, "Ops Timeline", "recent activity")
        if inner.height < 4:
            return

        row = inner.top
        overview_lines = [
            (
                f"Window: {metrics['total_runs']} runs  "
                f"stable {metrics['successful_runs']}  page {metrics['escalated_runs']}  "
                f"review {metrics['review_runs']}  dup {metrics['duplicate_blocks']}"
            ),
            f"Evaluation ledger: {metrics['evaluation_records']} recorded triggers",
            f"Selected: {_run_headline(snapshot) if snapshot else 'no run selected'}",
        ]
        for line in overview_lines:
            _write_line(stdscr, row, inner.left, _truncate(line, inner.width), _attr("normal"))
            row += 1

        row = _draw_section_divider(stdscr, row, inner.left, inner.width, "Runs")
        run_rows = max(4, min(8, inner.height // 3))
        if not runs:
            _write_line(stdscr, row, inner.left, "No runs recorded. Press r to execute the selected scenario.", _attr("muted"))
            row += 1
        else:
            for index, run in enumerate(runs[:run_rows]):
                badge = _run_badge(run)
                run_title = _truncate(run.get("scenario_name", "unknown"), max(8, inner.width - 14))
                prefix = ">" if index == self.run_index else " "
                line = f"{prefix} {run_title}"
                _write_line(
                    stdscr,
                    row,
                    inner.left,
                    _pad(line, inner.width),
                    _attr("selected") if index == self.run_index else _attr("normal"),
                )
                label = _truncate(badge.upper(), min(12, inner.width - 4))
                _write_line(stdscr, row, inner.left + max(0, inner.width - len(label)), label, _status_attr(badge))
                row += 1

        if snapshot:
            row = _draw_section_divider(stdscr, row, inner.left, inner.width, "Pipeline")
            for line in _wrap_lines(_pipeline_line(snapshot), inner.width, 3):
                _write_line(stdscr, row, inner.left, line, _attr("normal"))
                row += 1
            for line in _snapshot_metric_headlines(snapshot, inner.width):
                if row >= inner.top + inner.height - 4:
                    break
                _write_line(stdscr, row, inner.left, line, _attr("muted"))
                row += 1

        row = _draw_section_divider(stdscr, row, inner.left, inner.width, "Duplicate Ledger")
        if not evaluations:
            _write_line(stdscr, row, inner.left, "No evaluated triggers recorded.", _attr("muted"))
            return

        available_rows = max(1, inner.top + inner.height - row)
        for offset, (trigger_id, record) in enumerate(list(evaluations.items())[:available_rows]):
            line = f"{_short_id(trigger_id)} -> {_short_id(record.get('decision_id', '-'))}"
            _write_line(stdscr, row + offset, inner.left, _truncate(line, inner.width), _attr("normal"))

    def _draw_inspector_panel(
        self,
        stdscr,
        bounds: PanelBounds,
        snapshot: dict | None,
        selected_scenario: ScenarioDefinition,
        preview: dict[str, str | int | float],
    ) -> None:
        inner = _draw_panel(stdscr, bounds, "Inspector", self.detail_tab)
        if inner.height < 5:
            return

        row = inner.top
        tabs = []
        for index, tab in enumerate(self.detail_tabs):
            label = f"[{tab}]" if index == self.detail_tab_index else f" {tab} "
            tabs.append(label)
        _write_line(stdscr, row, inner.left, _truncate(" ".join(tabs), inner.width), _attr("accent"))
        row += 1
        row = _draw_section_divider(stdscr, row, inner.left, inner.width, "Details")

        content_lines = _inspector_lines(snapshot, selected_scenario, preview, self.detail_tab, inner.width)
        visible_height = max(1, inner.top + inner.height - row - 1)
        max_scroll = max(0, len(content_lines) - visible_height)
        self.detail_scroll = min(self.detail_scroll, max_scroll)
        window = content_lines[self.detail_scroll : self.detail_scroll + visible_height]
        for offset, line in enumerate(window):
            _write_line(stdscr, row + offset, inner.left, _truncate(line, inner.width), _attr("normal"))

        if max_scroll > 0:
            footer = f"scroll {self.detail_scroll + 1}-{self.detail_scroll + len(window)}/{len(content_lines)}"
            _write_line(
                stdscr,
                inner.top + inner.height - 1,
                inner.left + max(0, inner.width - len(footer)),
                footer,
                _attr("muted"),
            )

    def _draw_status_bar(self, stdscr, width: int, height: int) -> None:
        shortcuts = "j/k scenario  h/l runs  [/] inspector  PgUp/PgDn scroll  r run  e/o modes  c clear  q quit"
        bar = _pad(shortcuts, width)
        _write_line(stdscr, height - 2, 0, bar, _attr("status"))
        status = _truncate(f"status: {self.status_message}", width)
        _write_line(stdscr, height - 1, 0, _pad(status, width), _attr("status_accent"))

    def _write_wrapped_block(
        self,
        stdscr,
        row: int,
        left: int,
        width: int,
        lines: list[str],
        limit_row: int,
    ) -> None:
        cursor = row
        for line in lines:
            for wrapped in _wrap_lines(line, width):
                if cursor >= limit_row:
                    return
                _write_line(stdscr, cursor, left, wrapped, _attr("normal"))
                cursor += 1


def _status_line_from_result(result: dict) -> str:
    run = result.get("run_metadata") or {}
    trigger = result.get("trigger")
    if trigger is None:
        return f"{run.get('scenario_name', 'run')} completed with no trigger"
    decision = (result.get("decision") or {}).get("decision_type", "unknown")
    execution = (result.get("execution") or {}).get("status", "unknown")
    feedback = (result.get("feedback") or {}).get("outcome", "unknown")
    return f"{run.get('scenario_name', 'run')} -> {decision} / {execution} / {feedback}"


def _inspector_lines(
    snapshot: dict | None,
    scenario: ScenarioDefinition,
    preview: dict[str, str | int | float],
    tab: str,
    width: int,
) -> list[str]:
    if snapshot is None:
        return _empty_state_lines(scenario, preview, width)
    if tab == "overview":
        return _overview_lines(snapshot, width)
    if tab == "evidence":
        return _evidence_lines(snapshot, width)
    if tab == "execution":
        return _execution_lines(snapshot, width)
    return _json_lines(snapshot)


def _empty_state_lines(
    scenario: ScenarioDefinition,
    preview: dict[str, str | int | float],
    width: int,
) -> list[str]:
    lines: list[str] = []
    lines.extend(_section_lines("Selected Scenario", [scenario.title, scenario.description], width))
    lines.extend(
        _section_lines(
            "Preflight",
            [
                f"Intent: {preview['intent_label']}",
                f"Expected action: {preview['expected_action']}",
                f"Surface: {preview['service']} | {preview['endpoint']}",
                (
                    f"Baseline -> observed latency: {preview['baseline_p95_latency_ms']} -> "
                    f"{preview['observed_p95_latency_ms']} ms"
                ),
                (
                    f"Baseline -> observed error: {_format_rate(float(preview['baseline_error_rate']))} -> "
                    f"{_format_rate(float(preview['observed_error_rate']))}"
                ),
                (
                    f"Predicted 30m recovery: {preview['predicted_30m_p95_latency_ms']} ms / "
                    f"{_format_rate(float(preview['predicted_30m_error_rate']))}"
                ),
                "Run the scenario to populate decision, evaluation, execution, and feedback traces.",
            ],
            width,
        )
    )
    return lines


def _overview_lines(snapshot: dict, width: int) -> list[str]:
    run_meta = snapshot.get("run_metadata") or {}
    trigger = snapshot.get("trigger") or {}
    decision = snapshot.get("decision") or {}
    evaluation = snapshot.get("evaluation") or {}
    execution = snapshot.get("execution") or {}
    feedback = snapshot.get("feedback") or {}
    lines: list[str] = []
    lines.extend(
        _section_lines(
            "Run",
            [
                f"Scenario: {run_meta.get('scenario_name', '-')}",
                f"Recorded: {run_meta.get('recorded_at', '-')}",
                (
                    f"Modes: eval={run_meta.get('evaluation_mode', '-')}  "
                    f"exec={run_meta.get('orchestration_mode', '-')}"
                ),
                f"Trigger: {trigger.get('trigger_type', 'none')} on {trigger.get('service', '-')}",
            ],
            width,
        )
    )
    lines.extend(
        _section_lines(
            "Decision",
            [
                f"Action: {decision.get('decision_type', '-')}",
                f"Autonomy: {decision.get('autonomy_tier', '-')}",
                f"Confidence: {decision.get('confidence', '-')}",
                f"Summary: {decision.get('summary', '-')}",
            ],
            width,
        )
    )
    lines.extend(_section_lines("Pipeline", [_pipeline_line(snapshot)], width))
    lines.extend(_section_lines("Metrics", _snapshot_metric_headlines(snapshot, width), width))
    lines.extend(
        _section_lines(
            "Outcome",
            [
                f"Recommendation: {evaluation.get('final_recommendation', '-')}",
                f"Execution: {execution.get('status', '-')} via {execution.get('executor', '-')}",
                f"Feedback: {feedback.get('outcome', '-')}  follow-up={feedback.get('recommended_follow_up', '-')}",
            ],
            width,
        )
    )
    return lines


def _evidence_lines(snapshot: dict, width: int) -> list[str]:
    decision = snapshot.get("decision") or {}
    evaluation = snapshot.get("evaluation") or {}
    trigger = snapshot.get("trigger") or {}
    lines: list[str] = []

    reasoning = decision.get("reasoning") or {}
    evidence = [f"Hypothesis: {reasoning.get('primary_hypothesis', '-')}"]
    evidence.extend(f"Evidence: {item}" for item in reasoning.get("evidence") or [])
    evidence.extend(f"Alternative: {item}" for item in reasoning.get("alternatives_considered") or [])
    lines.extend(_section_lines("Reasoning", evidence, width))

    stage_entries = []
    for stage_name, stage in (evaluation.get("stage_results") or {}).items():
        notes = ", ".join(stage.get("notes") or []) if isinstance(stage, dict) else ""
        passed = stage.get("passed") if isinstance(stage, dict) else None
        stage_entries.append(f"{stage_name}: passed={passed} {notes}".strip())
    if evaluation.get("blocking_reasons"):
        stage_entries.extend(f"Blocker: {reason}" for reason in evaluation.get("blocking_reasons") or [])
    lines.extend(_section_lines("Evaluation", stage_entries or ["No evaluation notes recorded."], width))

    related_context = trigger.get("related_context") or {}
    context_entries = [
        f"release_id: {related_context.get('release_id', '-')}",
        f"active_incidents: {related_context.get('active_incidents', '-')}",
        f"similar_prior_cases: {related_context.get('similar_prior_cases', '-')}",
        f"regressions_last_7d: {related_context.get('regressions_last_7d', '-')}",
        f"minutes_since_flag_change: {related_context.get('minutes_since_flag_change', '-')}",
        f"multi_service_impact: {related_context.get('multi_service_impact', '-')}",
    ]
    lines.extend(_section_lines("Context", context_entries, width))
    return lines


def _execution_lines(snapshot: dict, width: int) -> list[str]:
    decision = snapshot.get("decision") or {}
    execution = snapshot.get("execution") or {}
    feedback = snapshot.get("feedback") or {}
    lines: list[str] = []

    plan = decision.get("execution_plan") or {}
    lines.extend(
        _section_lines(
            "Execution Plan",
            [
                f"System: {plan.get('system', '-')}",
                f"Action: {plan.get('action', '-')}",
                f"Parameters: {json.dumps(plan.get('parameters') or {}, sort_keys=True)}",
                f"Rollback: {plan.get('rollback_plan', '-')}",
            ],
            width,
        )
    )

    execution_entries = [
        f"Status: {execution.get('status', '-')}",
        f"Executor: {execution.get('executor', '-')}",
        f"Started: {execution.get('started_at', '-')}",
        f"Completed: {execution.get('completed_at', '-')}",
        f"Idempotency: {execution.get('idempotency_key', '-')}",
    ]
    failure = execution.get("failure") or {}
    if failure:
        execution_entries.extend(f"Failure {key}: {value}" for key, value in failure.items())
    external_refs = execution.get("external_refs") or {}
    if external_refs:
        execution_entries.extend(f"Ref {key}: {value}" for key, value in external_refs.items())
    lines.extend(_section_lines("Execution Record", execution_entries, width))

    world_model_updates = feedback.get("world_model_updates") or {}
    feedback_entries = [
        f"Outcome: {feedback.get('outcome', '-')}",
        f"Measured at: {feedback.get('measured_at', '-')}",
        f"Follow-up: {feedback.get('recommended_follow_up', '-')}",
    ]
    feedback_entries.extend(f"World model {key}: {value}" for key, value in world_model_updates.items())
    side_effects = feedback.get("side_effects") or []
    if side_effects:
        feedback_entries.extend(f"Side effect: {item}" for item in side_effects)
    lines.extend(_section_lines("Feedback", feedback_entries, width))
    return lines


def _json_lines(snapshot: dict) -> list[str]:
    return json.dumps(snapshot, indent=2, sort_keys=True).splitlines()


def _section_lines(title: str, entries: list[str], width: int) -> list[str]:
    lines = [title]
    for entry in entries:
        lines.extend(_wrap_lines(entry, width))
    lines.append("")
    return lines


def _pipeline_line(snapshot: dict) -> str:
    decision = (snapshot.get("decision") or {}).get("decision_type", "-")
    recommendation = (snapshot.get("evaluation") or {}).get("final_recommendation", "-")
    execution = (snapshot.get("execution") or {}).get("status", "-")
    feedback = (snapshot.get("feedback") or {}).get("outcome", "-")
    return (
        "ingest -> trigger -> "
        f"decision:{decision} -> eval:{recommendation} -> exec:{execution} -> feedback:{feedback}"
    )


def _snapshot_metric_headlines(snapshot: dict, width: int) -> list[str]:
    trigger = snapshot.get("trigger") or {}
    feedback = snapshot.get("feedback") or {}
    metrics = trigger.get("metrics") or {}
    metric_comparison = feedback.get("metric_comparison") or {}
    lines = [
        (
            f"P95 latency: {metrics.get('baseline_p95_latency_ms', '-')} -> "
            f"{metrics.get('observed_p95_latency_ms', '-')} -> "
            f"{metric_comparison.get('post_action_p95_latency_ms', '-')}"
        ),
        (
            f"Error rate: {_format_rate(metrics.get('baseline_error_rate'))} -> "
            f"{_format_rate(metrics.get('observed_error_rate'))} -> "
            f"{_format_rate(metric_comparison.get('post_action_error_rate'))}"
        ),
    ]
    return [_truncate(line, width) for line in lines]


def _run_headline(snapshot: dict | None) -> str:
    if snapshot is None:
        return "no run selected"
    run_meta = snapshot.get("run_metadata") or {}
    decision = snapshot.get("decision") or {}
    execution = snapshot.get("execution") or {}
    feedback = snapshot.get("feedback") or {}
    return (
        f"{run_meta.get('scenario_name', '-')}: {decision.get('decision_type', '-')} / "
        f"{execution.get('status', '-')} / {feedback.get('outcome', '-')}"
    )


def _run_badge(run: dict) -> str:
    if run.get("final_recommendation") == "reject":
        return "dup"
    if run.get("feedback_outcome") == "successful":
        return "stable"
    if run.get("feedback_outcome") == "escalated" or run.get("execution_status") == "failed":
        return "page"
    if run.get("execution_status") == "rejected":
        return "review"
    return "idle"


def _short_id(value: str) -> str:
    return value[-10:] if len(value) > 10 else value


def _truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def _pad(text: str, width: int) -> str:
    return _truncate(text, width).ljust(max(0, width))


def _format_rate(value) -> str:
    if value in (None, "-"):
        return "-"
    return f"{float(value) * 100:.2f}%"


def _signed_delta_percent(baseline: int | float, observed: int | float) -> str:
    if not baseline:
        return "n/a"
    return f"{((float(observed) - float(baseline)) / float(baseline)) * 100:+.1f}%"


def _draw_section_divider(stdscr, row: int, left: int, width: int, label: str) -> int:
    if width < len(label) + 4:
        return row
    divider = f"-- {label} " + "-" * max(0, width - len(label) - 3)
    _write_line(stdscr, row, left, _truncate(divider, width), _attr("muted"))
    return row + 1


def _draw_panel(stdscr, bounds: PanelBounds, title: str, subtitle: str | None = None) -> PanelBounds:
    border_attr = _attr("border")
    if bounds.height < 3 or bounds.width < 4:
        return bounds

    top = bounds.top
    left = bounds.left
    bottom = bounds.top + bounds.height - 1
    right = bounds.left + bounds.width - 1

    try:
        stdscr.addch(top, left, curses.ACS_ULCORNER, border_attr)
        stdscr.addch(top, right, curses.ACS_URCORNER, border_attr)
        stdscr.addch(bottom, left, curses.ACS_LLCORNER, border_attr)
        stdscr.addch(bottom, right, curses.ACS_LRCORNER, border_attr)
        stdscr.hline(top, left + 1, curses.ACS_HLINE, max(0, bounds.width - 2), border_attr)
        stdscr.hline(bottom, left + 1, curses.ACS_HLINE, max(0, bounds.width - 2), border_attr)
        stdscr.vline(top + 1, left, curses.ACS_VLINE, max(0, bounds.height - 2), border_attr)
        stdscr.vline(top + 1, right, curses.ACS_VLINE, max(0, bounds.height - 2), border_attr)
    except curses.error:
        return PanelBounds(top + 1, left + 1, max(0, bounds.height - 2), max(0, bounds.width - 2))

    _write_line(stdscr, top, left + 2, f" {title} ", _attr("accent", bold=True))
    if subtitle:
        subtitle_text = _truncate(subtitle, max(0, bounds.width - len(title) - 8))
        _write_line(stdscr, top, max(left + 2, right - len(subtitle_text) - 1), subtitle_text, _attr("muted"))
    return PanelBounds(top + 1, left + 1, max(0, bounds.height - 2), max(0, bounds.width - 2))


def _init_curses() -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
    except curses.error:
        pass
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)
    curses.init_pair(4, curses.COLOR_RED, -1)
    curses.init_pair(5, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(7, curses.COLOR_BLUE, -1)
    curses.init_pair(8, curses.COLOR_WHITE, -1)


def _attr(name: str, bold: bool = False) -> int:
    if not curses.has_colors():
        base = curses.A_BOLD if bold else curses.A_NORMAL
        if name in {"status", "status_accent", "selected"}:
            return base | curses.A_REVERSE
        if name in {"muted", "border"}:
            return base | curses.A_DIM
        return base

    pair_map = {
        "accent": curses.color_pair(1),
        "success": curses.color_pair(2),
        "warning": curses.color_pair(3),
        "danger": curses.color_pair(4),
        "selected": curses.color_pair(5),
        "status": curses.color_pair(6),
        "status_accent": curses.color_pair(5),
        "border": curses.color_pair(7),
        "muted": curses.color_pair(7),
        "normal": curses.color_pair(8),
    }
    value = pair_map.get(name, curses.A_NORMAL)
    if bold:
        value |= curses.A_BOLD
    return value


def _status_attr(badge: str) -> int:
    if badge == "stable":
        return _attr("success", bold=True)
    if badge == "page":
        return _attr("danger", bold=True)
    if badge in {"review", "dup"}:
        return _attr("warning", bold=True)
    return _attr("muted", bold=True)


def _wrap_lines(text: str, width: int, max_lines: int | None = None) -> list[str]:
    wrapped = textwrap.wrap(text, width=max(10, width)) or [text]
    return wrapped if max_lines is None else wrapped[:max_lines]


def _write_line(stdscr, row: int, col: int, text: str, attr: int = 0) -> None:
    height, width = stdscr.getmaxyx()
    if row < 0 or row >= height or col >= width:
        return
    clipped = text[: max(0, width - col - 1)]
    try:
        stdscr.addstr(row, col, clipped, attr)
    except curses.error:
        return


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mesh intelligence operator TUI")
    parser.add_argument("--state-directory", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    controller = MeshOperatorController(state_directory=args.state_directory)
    MeshOperatorTUI(controller).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
