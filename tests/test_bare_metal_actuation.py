"""Tests for the bare-metal actuation path: SSH systemd adapter + node ingesters.

Safety properties this locks in:

1. SSH refuses to execute when the enable flag is off.
2. SSH refuses to execute when a host is missing from the allowlist, or
   when the allowlist itself is empty (explicit > implicit).
3. SSH refuses to execute when a service is missing from the allowlist.
4. Command construction never introduces shell metacharacters or verbs
   outside the hardcoded allowlist.
5. Signal ingesters return None on RPC failure rather than emit a
   spurious signal — a monitoring outage must not look like a node fault.
6. The starter policy's Solana + geth rules match real signals and
   produce decisions routed to ``systemd_service``.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from services.actuators.systemd_ssh import SystemdSshAdapter
from services.decision.service import DecisionService
from services.evaluation.service import EvaluationService
from services.ingest.bare_metal_node import (
    BareMetalNodeTarget,
    EthereumNodeIngester,
    RethNodeIngester,
    RpcError,
    SolanaNodeIngester,
)
from services.ingest.service import IngestService
from services.trigger.service import TriggerService
from shared.mesh_runtime import RuntimeConfig, load_policy
from shared.mesh_runtime.metric_action_rules import load_metric_action_rules


def _bare_metal_config(**overrides) -> RuntimeConfig:
    """Build a RuntimeConfig with SSH execution enabled and allowlists set.

    Tests that want to exercise live-path guards should start from this
    and flip the field under test. Tests that want mock-mode can just
    construct a default RuntimeConfig.
    """
    defaults = dict(
        ssh_execution_enabled=True,
        ssh_allowed_hosts=("vault-prod-07", "vault-prod-08"),
        ssh_allowed_services=("solana-validator.service", "geth.service"),
    )
    defaults.update(overrides)
    return replace(RuntimeConfig(), **defaults)


# ---------------------------------------------------------------- SSH adapter


class SystemdSshSafetyTests(unittest.TestCase):
    """Lock in the four-part safety envelope. Each test covers one guard."""

    def test_mock_mode_never_invokes_subprocess(self) -> None:
        """When ssh_execution_enabled is False, the adapter must short-
        circuit without touching subprocess. The allowlists still need to
        be set because mock-mode validation mirrors live-mode validation —
        we want typos in rule parameters surfaced during testing, not
        silently masked because we're "only in mock mode"."""
        cfg = _bare_metal_config(ssh_execution_enabled=False)
        adapter = SystemdSshAdapter(config=cfg)
        with patch("subprocess.run") as fake_run:
            result = adapter.restart_service({
                "host": "vault-prod-07",
                "service": "solana-validator.service",
            })
        fake_run.assert_not_called()
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(result["external_refs"]["mock"])

    def test_empty_host_allowlist_rejects_all_hosts(self) -> None:
        """Live mode with no allowlist must refuse — explicit allowlisting
        is required before any real SSH can fire."""
        cfg = _bare_metal_config(ssh_allowed_hosts=())
        adapter = SystemdSshAdapter(config=cfg)
        result = adapter.restart_service({
            "host": "vault-prod-07",
            "service": "solana-validator.service",
        })
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["reason"], "host_allowlist_empty")

    def test_unlisted_host_is_rejected(self) -> None:
        cfg = _bare_metal_config()
        adapter = SystemdSshAdapter(config=cfg)
        result = adapter.restart_service({
            "host": "attacker-host",
            "service": "solana-validator.service",
        })
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["reason"], "host_not_allowed")

    def test_unlisted_service_is_rejected(self) -> None:
        cfg = _bare_metal_config()
        adapter = SystemdSshAdapter(config=cfg)
        result = adapter.restart_service({
            "host": "vault-prod-07",
            "service": "sshd.service",
        })
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["reason"], "service_not_allowed")

    def test_user_at_host_syntax_normalizes_for_allowlist(self) -> None:
        """Allowlist compares the bare hostname; `sre@vault-prod-07` is the
        same target as `vault-prod-07` from the allowlist's perspective."""
        cfg = _bare_metal_config()
        adapter = SystemdSshAdapter(config=cfg)
        with patch("subprocess.run") as fake_run:
            fake_run.return_value.returncode = 0
            fake_run.return_value.stdout = ""
            fake_run.return_value.stderr = ""
            result = adapter.restart_service({
                "host": "sre@vault-prod-07",
                "service": "solana-validator.service",
            })
        self.assertEqual(result["status"], "succeeded")
        # Command was issued against the user@host form (preserves login)
        args = fake_run.call_args[0][0]
        self.assertIn("sre@vault-prod-07", args)

    def test_service_name_with_or_without_service_suffix_both_allowed(self) -> None:
        """``solana-validator`` and ``solana-validator.service`` are the same
        unit to systemd; rules written either way must both pass the
        allowlist check."""
        cfg = _bare_metal_config(ssh_allowed_services=("solana-validator.service",))
        adapter = SystemdSshAdapter(config=cfg)
        with patch("subprocess.run") as fake_run:
            fake_run.return_value.returncode = 0
            fake_run.return_value.stdout = ""
            fake_run.return_value.stderr = ""
            result = adapter.restart_service({
                "host": "vault-prod-07",
                "service": "solana-validator",  # no suffix
            })
        self.assertEqual(result["status"], "succeeded")


class SystemdSshCommandConstructionTests(unittest.TestCase):
    """Every command goes through `_build_ssh_command`. Lock in its shape."""

    def test_restart_builds_expected_systemctl_command(self) -> None:
        cfg = _bare_metal_config()
        adapter = SystemdSshAdapter(config=cfg)
        command = adapter._build_ssh_command(
            "vault-prod-07",
            systemctl_verb="restart",
            systemctl_service="solana-validator.service",
            use_sudo=True,
        )
        # Expected shape: ssh <flags> <host> "sudo systemctl restart <service>"
        self.assertEqual(command[0], "ssh")
        self.assertIn("-o", command)
        self.assertIn("BatchMode=yes", command)
        self.assertEqual(command[-2], "vault-prod-07")
        self.assertEqual(command[-1], "sudo systemctl restart solana-validator.service")

    def test_status_omits_sudo_by_default(self) -> None:
        """Read-only status calls should not require sudo."""
        cfg = _bare_metal_config()
        adapter = SystemdSshAdapter(config=cfg)
        with patch("subprocess.run") as fake_run:
            fake_run.return_value.returncode = 0
            fake_run.return_value.stdout = "active (running)"
            fake_run.return_value.stderr = ""
            adapter.status_service({
                "host": "vault-prod-07",
                "service": "solana-validator.service",
            })
        cmd = fake_run.call_args[0][0]
        remote = cmd[-1]
        self.assertFalse(remote.startswith("sudo"))
        self.assertTrue(remote.startswith("systemctl status"))

    def test_diagnostic_command_allowlist_enforced(self) -> None:
        """Only df/free/uptime are permitted as diagnostic reads. Any other
        diagnostic verb must be rejected by `_build_ssh_command`."""
        cfg = _bare_metal_config()
        adapter = SystemdSshAdapter(config=cfg)
        with self.assertRaises(Exception) as ctx:
            adapter._build_ssh_command("vault-prod-07", diagnostic="rm", diagnostic_args=("-rf", "/"))
        self.assertIn("diagnostic_not_allowed", str(ctx.exception))

    def test_ssh_timeout_returns_failure(self) -> None:
        """subprocess.TimeoutExpired must become a structured ssh_timeout
        failure — it cannot bubble up as an exception past the adapter."""
        import subprocess
        cfg = _bare_metal_config()
        adapter = SystemdSshAdapter(config=cfg)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ssh", 30)):
            result = adapter.restart_service({
                "host": "vault-prod-07",
                "service": "solana-validator.service",
            })
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["reason"], "ssh_timeout")


# ---------------------------------------------------------------- ingesters


def _solana_target() -> BareMetalNodeTarget:
    return BareMetalNodeTarget.from_dict({
        "name": "vault-prod-07",
        "kind": "solana",
        "rpc_url": "http://127.0.0.1:8899",
        "host": "vault-prod-07",
        "service": "solana-validator.service",
        "region": "us-east-1",
    })


def _geth_target() -> BareMetalNodeTarget:
    return BareMetalNodeTarget.from_dict({
        "name": "eth-archival-02",
        "kind": "geth",
        "rpc_url": "http://127.0.0.1:8545",
        "host": "eth-archival-02",
        "service": "geth.service",
        "region": "us-east-1",
    })


def _reth_target() -> BareMetalNodeTarget:
    return BareMetalNodeTarget.from_dict({
        "name": "reth-mainnet-01",
        "kind": "reth",
        "rpc_url": "http://127.0.0.1:8545",
        "host": "reth-mainnet-01",
        "service": "reth.service",
        "region": "us-east-1",
        "deployment_mode": "systemd",
        "network": "mainnet",
        "role": "full",
        "consensus_client": "lighthouse",
        "min_peer_count": 3,
        "max_block_lag": 32,
    })


class SolanaIngesterTests(unittest.TestCase):
    def test_builds_signal_with_slot_lag(self) -> None:
        ingester = SolanaNodeIngester(_solana_target(), reference_rpc_url="http://reference:8899")
        # First call: node slot. Second: reference slot. Third: getVoteAccounts.
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[100_000, 100_200, {"delinquent": [], "current": []}],
        ):
            signal = ingester.build_signal()
        self.assertIsNotNone(signal)
        self.assertEqual(signal["metric_regression"]["metric_name"], "solana.slot_lag")
        self.assertEqual(signal["metric_regression"]["observed_value"], 200.0)
        # The host + service stamped on resource_attributes drive actuation later.
        self.assertEqual(signal["resource_attributes"]["mesh.node.host"], "vault-prod-07")
        self.assertEqual(signal["resource_attributes"]["mesh.node.service"], "solana-validator.service")

    def test_rpc_failure_returns_none(self) -> None:
        ingester = SolanaNodeIngester(_solana_target())
        with patch("services.ingest.bare_metal_node._rpc_call", side_effect=RpcError("conn refused")):
            signal = ingester.build_signal()
        self.assertIsNone(signal)

    def test_delinquency_stamps_related_metric(self) -> None:
        ingester = SolanaNodeIngester(_solana_target())
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[
                100_000,  # getSlot
                # No reference RPC, so only two calls: getSlot then getVoteAccounts
                {"delinquent": [{"nodePubkey": "abc123"}], "current": []},
            ],
        ):
            signal = ingester.build_signal()
        self.assertTrue(signal["metric_regression"]["attributes"]["delinquent"])
        self.assertEqual(signal["related_metrics"][0]["metric_name"], "solana.delinquent")
        self.assertEqual(signal["related_metrics"][0]["value"], 1.0)


class EthereumIngesterTests(unittest.TestCase):
    def test_low_peer_count_headlines_peer_metric(self) -> None:
        """When peers < minimum, peer_count becomes the primary metric so
        rules can threshold on it directly."""
        ingester = EthereumNodeIngester(_geth_target())
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[False, "0x1", "0x1234"],  # eth_syncing, net_peerCount=1, eth_blockNumber
        ):
            signal = ingester.build_signal()
        self.assertEqual(signal["metric_regression"]["metric_name"], "geth.peer_count")
        self.assertEqual(signal["metric_regression"]["observed_value"], 1.0)
        self.assertEqual(signal["metric_regression"]["baseline_value"], 3.0)  # min_peer_count default

    def test_healthy_peers_report_block_lag_instead(self) -> None:
        ingester = EthereumNodeIngester(_geth_target())
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[
                {"highestBlock": "0xa", "currentBlock": "0x5"},  # lag = 5
                "0xa",  # 10 peers
                "0x5",  # head block
            ],
        ):
            signal = ingester.build_signal()
        self.assertEqual(signal["metric_regression"]["metric_name"], "geth.block_lag")
        self.assertEqual(signal["metric_regression"]["observed_value"], 5.0)

    def test_rpc_failure_returns_none(self) -> None:
        ingester = EthereumNodeIngester(_geth_target())
        with patch("services.ingest.bare_metal_node._rpc_call", side_effect=RpcError("timeout")):
            self.assertIsNone(ingester.build_signal())


class RethNodeIngesterTests(unittest.TestCase):
    def test_builds_first_class_reth_signal_for_peer_starvation(self) -> None:
        ingester = RethNodeIngester(_reth_target())
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[False, "0x1", "0x1234", "reth/v2.1.0"],
        ):
            signal = ingester.build_signal()
        self.assertIsNotNone(signal)
        self.assertEqual(signal["signal_type"], "reth_node")
        self.assertEqual(signal["node"]["network"], "mainnet")
        self.assertEqual(signal["execution"]["peer_count"], 1)
        self.assertIn("peer_starvation", signal["logs"]["error_signatures"])
        self.assertIsNone(signal["consensus"]["engine_api_reachable"])
        self.assertIsNone(signal["consensus"]["jwt_configured"])
        self.assertEqual(signal["resource_attributes"]["mesh.node.host"], "reth-mainnet-01")
        self.assertEqual(signal["resource_attributes"]["mesh.node.service"], "reth.service")

    def test_reth_metrics_and_logs_drive_consensus_health(self) -> None:
        target = _reth_target()
        target.metrics_url = "http://127.0.0.1:9001"
        target.recent_log_lines = (
            "INFO Engine API forkchoiceUpdated received from Lighthouse",
            "INFO lighthouse beacon node healthy",
        )
        ingester = RethNodeIngester(
            target,
            metrics_fetcher=lambda url: "reth_engine_forkchoice_updated_total 42\n",
            jwt_metadata_provider=lambda _target: {"exists": True, "mode": "0600"},
        )
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[False, "0xa", "0x1234", "reth/v2.1.0"],
        ):
            signal = ingester.build_signal()

        self.assertTrue(signal["consensus"]["engine_api_reachable"])
        self.assertTrue(signal["consensus"]["forkchoice_updates_recent"])
        self.assertTrue(signal["consensus"]["jwt_configured"])
        self.assertEqual(signal["consensus"]["jwt_secret_mode"], "0600")

    def test_reth_diagnostics_surface_disk_and_jwt_risks(self) -> None:
        ingester = RethNodeIngester(
            _reth_target(),
            disk_diagnostics_provider=lambda _target: {
                "disk_used_pct": 95,
                "data_dir_free_bytes": 123,
                "diagnostic_source": "ssh_df",
            },
            jwt_metadata_provider=lambda _target: {"exists": True, "mode": "0644"},
        )
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[False, "0xa", "0x1234", "reth/v2.1.0"],
        ):
            signal = ingester.build_signal()

        self.assertEqual(signal["storage"]["disk_used_pct"], 95.0)
        self.assertEqual(signal["storage"]["diagnostic_source"], "ssh_df")
        self.assertIn("disk_pressure", signal["logs"]["error_signatures"])
        self.assertIn("jwt_secret_insecure_permissions", signal["logs"]["error_signatures"])

    def test_rpc_failure_returns_none(self) -> None:
        ingester = RethNodeIngester(_reth_target())
        with patch("services.ingest.bare_metal_node._rpc_call", side_effect=RpcError("timeout")):
            self.assertIsNone(ingester.build_signal())


# ---------------------------------------------------------------- end-to-end


class BareMetalDecisionFlowTests(unittest.TestCase):
    """Ingester → IngestService → TriggerService → DecisionService produces
    the expected `restart_systemd_service` decision for a real Solana signal.
    """

    def test_solana_lag_rule_end_to_end(self) -> None:
        # Build a signal as if SolanaNodeIngester produced it.
        ingester = SolanaNodeIngester(_solana_target(), reference_rpc_url="http://reference:8899")
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[100_000, 100_500, {"delinquent": [], "current": []}],  # 500-slot lag
        ):
            signal = ingester.build_signal()
        self.assertIsNotNone(signal)

        # Push it through the real ingest/trigger/decision pipeline.
        envelope = IngestService().normalize_signal(signal)
        trigger = TriggerService().detect(envelope)
        self.assertIsNotNone(trigger)

        load_metric_action_rules.cache_clear()
        decision = DecisionService().decide(trigger)

        # The starter rule should match and route to the systemd_service path.
        self.assertEqual(decision.decision_type, "restart_systemd_service")
        self.assertEqual(decision.execution_plan["system"], "systemd_service")
        self.assertEqual(decision.execution_plan["action"], "restart_systemd_service")
        self.assertEqual(decision.execution_plan["parameters"]["host"], "vault-prod-07")
        self.assertEqual(
            decision.execution_plan["parameters"]["service"],
            "solana-validator.service",
        )

    def test_geth_peer_starvation_rule_end_to_end(self) -> None:
        ingester = EthereumNodeIngester(_geth_target())
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[False, "0x1", "0x1234"],  # 1 peer — below min
        ):
            signal = ingester.build_signal()
        self.assertIsNotNone(signal)
        envelope = IngestService().normalize_signal(signal)
        trigger = TriggerService().detect(envelope)
        self.assertIsNotNone(trigger)
        load_metric_action_rules.cache_clear()
        decision = DecisionService().decide(trigger)
        self.assertEqual(decision.decision_type, "restart_systemd_service")
        self.assertEqual(decision.execution_plan["parameters"]["host"], "eth-archival-02")

    def test_reth_peer_starvation_is_approval_gated_systemd_restart(self) -> None:
        ingester = RethNodeIngester(_reth_target())
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[False, "0x1", "0x1234", "reth/v2.1.0"],
        ):
            signal = ingester.build_signal()
        self.assertIsNotNone(signal)
        envelope = IngestService().normalize_signal(signal)
        trigger = TriggerService().detect(envelope)
        self.assertIsNotNone(trigger)
        self.assertEqual(trigger.trigger_type, "reth_node_degraded")

        decision = DecisionService().decide(trigger)

        self.assertEqual(decision.decision_type, "restart_systemd_service")
        self.assertEqual(decision.autonomy_tier, "approval_required")
        self.assertEqual(decision.execution_plan["system"], "systemd_service")
        self.assertEqual(decision.execution_plan["parameters"]["host"], "reth-mainnet-01")
        self.assertEqual(decision.execution_plan["parameters"]["service"], "reth.service")

    def test_reth_consensus_disconnect_escalates_instead_of_restart(self) -> None:
        signal = RethNodeIngester(_reth_target()).build_signal
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[False, "0xa", "0x1234", "reth/v2.1.0"],
        ):
            payload = signal()
        self.assertIsNotNone(payload)
        payload["consensus"]["engine_api_reachable"] = False
        payload["consensus"]["forkchoice_updates_recent"] = False

        trigger = TriggerService().detect(IngestService().normalize_signal(payload))
        self.assertIsNotNone(trigger)
        decision = DecisionService().decide(trigger)

        self.assertEqual(decision.decision_type, "escalate")
        self.assertEqual(decision.execution_plan["system"], "incident_service")

    def test_reth_rpc_exposure_escalates_instead_of_restart(self) -> None:
        target = _reth_target()
        target.rpc_publicly_exposed = True
        target.authrpc_publicly_exposed = True
        ingester = RethNodeIngester(target)
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[False, "0xa", "0x1234", "reth/v2.1.0"],
        ):
            signal = ingester.build_signal()

        trigger = TriggerService().detect(IngestService().normalize_signal(signal))
        self.assertIn("rpc_exposed", trigger.related_context["error_signatures"])
        self.assertIn("authrpc_exposed", trigger.related_context["error_signatures"])
        decision = DecisionService().decide(trigger)
        self.assertEqual(decision.decision_type, "escalate")

    def test_reth_restart_frequency_cap_escalates(self) -> None:
        ingester = RethNodeIngester(_reth_target())
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[False, "0x1", "0x1234", "reth/v2.1.0"],
        ):
            signal = ingester.build_signal()
        signal["related_context"]["systemd_restarts_last_1h"] = 1

        trigger = TriggerService().detect(IngestService().normalize_signal(signal))
        decision = DecisionService().decide(trigger)

        self.assertEqual(decision.decision_type, "escalate")
        self.assertIn("restart_frequency_exceeded", decision.reasoning["evidence_pack"]["error_signatures"])

    def test_systemd_policy_only_allows_restart_for_reth_slice(self) -> None:
        policy = load_policy("autonomy.policy.json")
        self.assertEqual(policy["allowed_execution_actions"]["systemd_service"], ["restart_systemd_service"])

    def test_systemd_readiness_requires_allowlisted_target(self) -> None:
        ingester = RethNodeIngester(_reth_target())
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[False, "0x1", "0x1234", "reth/v2.1.0"],
        ):
            signal = ingester.build_signal()
        trigger = TriggerService().detect(IngestService().normalize_signal(signal))
        decision = DecisionService().decide(trigger)

        service = EvaluationService(config=RuntimeConfig())
        ready, notes = service._systemd_service_ready(decision)

        self.assertFalse(ready)
        self.assertIn("systemd host allowlist is empty", notes)
        self.assertIn("systemd service allowlist is empty", notes)

    def test_systemd_readiness_accepts_allowlisted_reth_target(self) -> None:
        ingester = RethNodeIngester(_reth_target())
        with patch(
            "services.ingest.bare_metal_node._rpc_call",
            side_effect=[False, "0x1", "0x1234", "reth/v2.1.0"],
        ):
            signal = ingester.build_signal()
        trigger = TriggerService().detect(IngestService().normalize_signal(signal))
        decision = DecisionService().decide(trigger)

        config = replace(
            RuntimeConfig(),
            ssh_allowed_hosts=("reth-mainnet-01",),
            ssh_allowed_services=("reth.service",),
        )
        service = EvaluationService(config=config)
        ready, notes = service._systemd_service_ready(decision)

        self.assertTrue(ready)
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
