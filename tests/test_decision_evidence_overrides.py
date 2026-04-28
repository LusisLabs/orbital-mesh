"""Tests for the safety overrides ``_decide_reth_node`` applies on top
of the deterministic policy match.

These exist because the EvidenceService and DecisionService share a
contract that's invisible to the policy file. We want a regression
test that proves a fast-path-flagged pack escalates even when the
policy wouldn't on its own — defense in depth against a future policy
edit dropping a signature from ``escalation_signatures``.
"""

from __future__ import annotations

import unittest

from services.decision.hypothesis_engine import HypothesisEngine
from services.decision.service import DecisionService
from shared.mesh_runtime import Trigger


def _trigger(error_signatures: list[str], extra_context: dict | None = None) -> Trigger:
    related = {
        "error_signatures": error_signatures,
        "node": {"role": "rpc", "network": "mainnet"},
        "execution": {"peer_count": 0, "block_lag": 0, "syncing": False},
        "consensus": {
            "engine_api_reachable": True,
            "forkchoice_updates_recent": True,
        },
        "storage": {"disk_used_pct": 60.0},
        "resource_attributes": {},
    }
    if extra_context:
        related.update(extra_context)
    return Trigger(
        trigger_id="trig_test_overrides",
        trigger_type="reth_node_degraded",
        triggered_at="2026-04-26T00:00:00Z",
        environment="prod",
        service="reth-mainnet-07",
        endpoint="reth.rpc",
        flag_key=None,
        current_rollout_pct=None,
        comparison_window={"baseline": "PT1H", "observed": "PT5M"},
        segment={"customer_tier": "system", "region": "us-east-1"},
        metrics={
            "baseline_p95_latency_ms": None,
            "observed_p95_latency_ms": None,
            "baseline_error_rate": None,
            "observed_error_rate": None,
            "baseline_timeout_rate": None,
            "observed_timeout_rate": None,
            "sample_size": 1,
        },
        related_context=related,
    )


class FastPathForceEscalateTests(unittest.TestCase):
    def test_fast_path_forces_escalate_even_when_policy_silent(self):
        """Synthetic scenario: fast-path was triggered for a signature
        the deterministic policy doesn't know about. Without this
        defensive check the pipeline would fall through to no_action
        for an unsafe condition.
        """
        # Build a trigger that the deterministic policy would route to
        # ``no_action`` (no error signatures matched). The evidence pack
        # carries a fast-path flag for an out-of-policy signature.
        trigger = _trigger(error_signatures=[])
        evidence_pack = {
            "pack": {
                "signal_type": "reth_node",
                "execution": {"peer_count": 0, "syncing": False, "block_lag": 0},
                "rpc": {"http_reachable": True},
                "consensus": {},
                "storage": {},
            },
            "source": "fast_path_skip",
            "sufficient": True,  # Fast-path skipped probes; not "insufficient"
            "missing_fields": [],
            "fast_path_signatures": ["mystery_unsafe_signature"],
        }

        decision = DecisionService().decide(trigger, evidence_pack=evidence_pack)
        self.assertEqual(decision.decision_type, "escalate")
        self.assertEqual(decision.autonomy_tier, "escalated")

    def test_fast_path_with_known_escalation_signature_still_escalates(self):
        """Both paths agree: fast-path + policy escalation_signature →
        escalate. Sanity check that adding the override didn't break
        the normal flow."""
        trigger = _trigger(error_signatures=["authrpc_exposed"])
        evidence_pack = {
            "pack": {
                "signal_type": "reth_node",
                "execution": {"peer_count": 12, "syncing": False, "block_lag": 0},
                "rpc": {"http_reachable": True, "authrpc_publicly_exposed": True},
                "consensus": {},
                "storage": {},
            },
            "source": "fast_path_skip",
            "sufficient": True,
            "missing_fields": [],
            "fast_path_signatures": ["authrpc_exposed"],
        }
        decision = DecisionService().decide(trigger, evidence_pack=evidence_pack)
        self.assertEqual(decision.decision_type, "escalate")

    def test_no_fast_path_no_force_escalate(self):
        """Negative control: when fast_path_signatures is empty,
        the override does not fire. Normal restart path stands only
        when evidence and hypothesis ranking support it."""
        trigger = _trigger(error_signatures=["peer_starvation"])
        evidence_pack = {
            "pack": {
                "signal_type": "reth_node",
                "execution": {"peer_count": 0, "syncing": False, "block_lag": 0},
                "rpc": {"http_reachable": True},
                "consensus": {"engine_api_reachable": True},
                "storage": {"disk_used_pct": 60.0},
            },
            "source": "inline_signal",
            "sufficient": True,
            "missing_fields": [],
            "fast_path_signatures": [],
        }
        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(
            trigger,
            evidence_pack=evidence_pack,
        )
        self.assertEqual(decision.decision_type, "restart_systemd_service")

    def test_restartable_reth_signal_without_evidence_escalates(self):
        """A restartable signature is only a lead. Without an evidence
        pack and a supporting hypothesis, Mesh must route the node to
        review rather than restarting a stateful blockchain process from
        signal text alone.
        """
        trigger = _trigger(error_signatures=["peer_starvation"])

        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(trigger)

        self.assertEqual(decision.decision_type, "escalate")
        self.assertEqual(decision.autonomy_tier, "escalated")


class ValidatorDutyImminentTests(unittest.TestCase):
    """A restartable Reth symptom + paired-CL validator duty pending =
    must escalate. Restarting an EL while its paired CL has an
    attestation or proposal duty in the next 30 seconds risks the
    validator missing the duty (or worst case double-signing on
    restart if slashing protection is misconfigured).

    The CL-side exporter stamps ``consensus.validator_attestation_pending``
    and ``consensus.validator_proposer_within_seconds``; absence means
    "no opinion" and the normal decision path runs.
    """

    def _trigger_with_consensus(self, consensus_extras: dict) -> Trigger:
        consensus = {
            "engine_api_reachable": True,
            "forkchoice_updates_recent": True,
            **consensus_extras,
        }
        return _trigger(
            error_signatures=["peer_starvation"],
            extra_context={"consensus": consensus},
        )

    def _evidence_pack(self, consensus_overrides: dict) -> dict:
        return {
            "pack": {
                "signal_type": "reth_node",
                "execution": {"peer_count": 0, "syncing": False, "block_lag": 0},
                "rpc": {"http_reachable": True},
                "consensus": {
                    "engine_api_reachable": True,
                    **consensus_overrides,
                },
                "storage": {"disk_used_pct": 60.0},
            },
            "source": "inline_signal",
            "sufficient": True,
            "missing_fields": [],
            "fast_path_signatures": [],
        }

    def test_attestation_pending_forces_escalate(self):
        trigger = self._trigger_with_consensus({"validator_attestation_pending": True})
        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(
            trigger,
            evidence_pack=self._evidence_pack({"validator_attestation_pending": True}),
        )
        self.assertEqual(decision.decision_type, "escalate")
        self.assertEqual(decision.autonomy_tier, "escalated")

    def test_proposer_within_30s_forces_escalate(self):
        trigger = self._trigger_with_consensus({"validator_proposer_within_seconds": 12})
        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(
            trigger,
            evidence_pack=self._evidence_pack({"validator_proposer_within_seconds": 12}),
        )
        self.assertEqual(decision.decision_type, "escalate")

    def test_proposer_far_in_future_does_not_force_escalate(self):
        # 600s away — plenty of slack. The validator-duty guard must
        # not fire; the normal path with hypothesis engine + sufficient
        # evidence allows the approval-gated restart.
        trigger = self._trigger_with_consensus({"validator_proposer_within_seconds": 600})
        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(
            trigger,
            evidence_pack=self._evidence_pack({"validator_proposer_within_seconds": 600}),
        )
        self.assertEqual(decision.decision_type, "restart_systemd_service")

    def test_no_validator_fields_does_not_force_escalate(self):
        # Neither field present — guard is "no opinion". Normal path
        # decides.
        trigger = self._trigger_with_consensus({})
        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(
            trigger,
            evidence_pack=self._evidence_pack({}),
        )
        self.assertEqual(decision.decision_type, "restart_systemd_service")


class DoppelgangerWindowTests(unittest.TestCase):
    """``consensus.doppelganger_protection_active=true`` means the
    paired CL is in the 2-epoch listening window after key import.
    Restarting the EL during that window forces re-arm and masks any
    real duplicate-VC. Hard rule: refuse, regardless of any other
    symptom."""

    def _trigger_with_doppelganger(self, value: bool | None) -> Trigger:
        consensus = {
            "engine_api_reachable": True,
            "forkchoice_updates_recent": True,
        }
        if value is not None:
            consensus["doppelganger_protection_active"] = value
        return _trigger(
            error_signatures=["peer_starvation"],
            extra_context={"consensus": consensus},
        )

    def _evidence(self, doppelganger: bool | None) -> dict:
        consensus = {"engine_api_reachable": True}
        if doppelganger is not None:
            consensus["doppelganger_protection_active"] = doppelganger
        return {
            "pack": {
                "signal_type": "reth_node",
                "execution": {"peer_count": 0, "syncing": False, "block_lag": 0},
                "rpc": {"http_reachable": True},
                "consensus": consensus,
                "storage": {"disk_used_pct": 60.0},
            },
            "source": "inline_signal",
            "sufficient": True,
            "missing_fields": [],
            "fast_path_signatures": [],
        }

    def test_doppelganger_active_forces_escalate(self):
        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(
            self._trigger_with_doppelganger(True),
            evidence_pack=self._evidence(True),
        )
        self.assertEqual(decision.decision_type, "escalate")

    def test_doppelganger_inactive_allows_normal_path(self):
        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(
            self._trigger_with_doppelganger(False),
            evidence_pack=self._evidence(False),
        )
        self.assertEqual(decision.decision_type, "restart_systemd_service")

    def test_doppelganger_absent_allows_normal_path(self):
        # No opinion → normal decision path.
        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(
            self._trigger_with_doppelganger(None),
            evidence_pack=self._evidence(None),
        )
        self.assertEqual(decision.decision_type, "restart_systemd_service")


class SlashingDbFreshnessTests(unittest.TestCase):
    """A non-null ``consensus.slashing_db_restored_within_seconds``
    below 3600 means the operator (or their automation) just restored
    the slashing-protection DB — historically the #1 cause of mainnet
    slashing. Hard rule: refuse all action."""

    def _trigger_with_slashing_age(self, seconds: int | None) -> Trigger:
        consensus = {
            "engine_api_reachable": True,
            "forkchoice_updates_recent": True,
        }
        if seconds is not None:
            consensus["slashing_db_restored_within_seconds"] = seconds
        return _trigger(
            error_signatures=["peer_starvation"],
            extra_context={"consensus": consensus},
        )

    def _evidence(self, seconds: int | None) -> dict:
        consensus = {"engine_api_reachable": True}
        if seconds is not None:
            consensus["slashing_db_restored_within_seconds"] = seconds
        return {
            "pack": {
                "signal_type": "reth_node",
                "execution": {"peer_count": 0, "syncing": False, "block_lag": 0},
                "rpc": {"http_reachable": True},
                "consensus": consensus,
                "storage": {"disk_used_pct": 60.0},
            },
            "source": "inline_signal",
            "sufficient": True,
            "missing_fields": [],
            "fast_path_signatures": [],
        }

    def test_recent_restore_forces_escalate(self):
        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(
            self._trigger_with_slashing_age(60),
            evidence_pack=self._evidence(60),
        )
        self.assertEqual(decision.decision_type, "escalate")

    def test_old_restore_allows_normal_path(self):
        # 7200 seconds ago = 2 hours. Past the cap; the guard treats
        # this as "old enough to be safe."
        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(
            self._trigger_with_slashing_age(7200),
            evidence_pack=self._evidence(7200),
        )
        self.assertEqual(decision.decision_type, "restart_systemd_service")

    def test_no_restore_field_allows_normal_path(self):
        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(
            self._trigger_with_slashing_age(None),
            evidence_pack=self._evidence(None),
        )
        self.assertEqual(decision.decision_type, "restart_systemd_service")


class CrossRunRestartCooldownTests(unittest.TestCase):
    """Mesh's own restart history (via ``LearningStore``) should cap
    the rate even when the inbound trigger doesn't carry a count.
    The guard uses ``max(trigger_count, learning_store_count)`` so the
    safety floor is never lowered."""

    def _make_trigger(self, host_stamped_count: int = 0) -> Trigger:
        return _trigger(
            error_signatures=["peer_starvation"],
            extra_context={
                "consensus": {"engine_api_reachable": True, "forkchoice_updates_recent": True},
                "systemd_restarts_last_1h": host_stamped_count,
            },
        )

    def _make_evidence(self) -> dict:
        return {
            "pack": {
                "signal_type": "reth_node",
                "execution": {"peer_count": 0, "syncing": False, "block_lag": 0},
                "rpc": {"http_reachable": True},
                "consensus": {"engine_api_reachable": True},
                "storage": {"disk_used_pct": 60.0},
            },
            "source": "inline_signal",
            "sufficient": True,
            "missing_fields": [],
            "fast_path_signatures": [],
        }

    def test_learning_store_count_promotes_to_escalate(self):
        # Trigger says 0 restarts in last hour, but Mesh's learning
        # store says 1 — at the cap. Guard fires.
        from unittest.mock import MagicMock
        store = MagicMock()
        store.count_recent_decisions.return_value = 1  # >= max_restarts_per_window=1
        decision = DecisionService(
            learning_store=store,
            hypothesis_engine=HypothesisEngine(),
        ).decide(self._make_trigger(host_stamped_count=0), evidence_pack=self._make_evidence())
        self.assertEqual(decision.decision_type, "escalate")
        store.count_recent_decisions.assert_called_once()
        kwargs = store.count_recent_decisions.call_args.kwargs
        self.assertEqual(kwargs["decision_type"], "restart_systemd_service")
        self.assertEqual(kwargs["service"], "reth-mainnet-07")
        # The window comes from the policy (3600s default).
        self.assertEqual(kwargs["within_seconds"], 3600)

    def test_zero_count_from_both_sources_allows_restart(self):
        from unittest.mock import MagicMock
        store = MagicMock()
        store.count_recent_decisions.return_value = 0
        decision = DecisionService(
            learning_store=store,
            hypothesis_engine=HypothesisEngine(),
        ).decide(self._make_trigger(host_stamped_count=0), evidence_pack=self._make_evidence())
        self.assertEqual(decision.decision_type, "restart_systemd_service")

    def test_learning_store_failure_falls_back_to_trigger_count(self):
        from unittest.mock import MagicMock
        store = MagicMock()
        store.count_recent_decisions.side_effect = RuntimeError("db unreachable")
        # Trigger says no recent restarts → fallback path lets restart through.
        decision = DecisionService(
            learning_store=store,
            hypothesis_engine=HypothesisEngine(),
        ).decide(self._make_trigger(host_stamped_count=0), evidence_pack=self._make_evidence())
        self.assertEqual(decision.decision_type, "restart_systemd_service")

    def test_no_learning_store_uses_trigger_count(self):
        # No store bound. Trigger says 1 → cap hit → escalate.
        decision = DecisionService(hypothesis_engine=HypothesisEngine()).decide(
            self._make_trigger(host_stamped_count=1),
            evidence_pack=self._make_evidence(),
        )
        self.assertEqual(decision.decision_type, "escalate")


if __name__ == "__main__":
    unittest.main()
