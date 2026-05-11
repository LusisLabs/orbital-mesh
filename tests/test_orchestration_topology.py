from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.orchestrator.agent_mesh import AgentMeshService
from shared.mesh_runtime import Decision, EvaluationResult, RuntimeConfig, Trigger, build_readiness
from shared.mesh_runtime.agent_workers import DEFAULT_AGENT_WORKERS
from shared.mesh_runtime.orchestration_topology import (
    ORCHESTRATION_TOPOLOGY_PROFILE_SCHEMA,
    load_orchestration_topology_profile,
    resolve_orchestration_topology,
)
from shared.mesh_runtime.schema_validation import load_schema


class OrchestrationTopologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_profile_schema_is_loadable(self) -> None:
        schema = load_schema(ORCHESTRATION_TOPOLOGY_PROFILE_SCHEMA)
        self.assertEqual(schema["properties"]["version"]["enum"], ["mesh.orchestration_topology_profile.v1"])
        self.assertIn("organization_profile", schema["required"])
        self.assertIn("model_provider_policy", schema["required"])

    def test_default_profile_resolves_centralized(self) -> None:
        trigger = self._trigger()
        decision = self._decision()
        config = self._config()
        resolution = resolve_orchestration_topology(
            profile_path=config.orchestration_topology_profile_path,
            trigger=trigger,
            decision=decision,
            candidate_lanes=["goose", "hermes"],
            configured_filter=[],
            ownership_registry_path=config.ownership_registry_path,
            connector_certification_registry_path=config.connector_certification_registry_path,
            policy_lifecycle_manifest_path=config.policy_lifecycle_manifest_path,
            threat_model_register_path=config.threat_model_register_path,
            state_directory=config.state_directory,
        )

        self.assertEqual(resolution["active_topology"], "centralized")
        self.assertEqual(resolution["rule_id"], "default")
        self.assertEqual(resolution["selected_agents"], ["goose", "hermes"])
        self.assertEqual(resolution["reconciliation"], "mesh_authoritative_single_decision")

    def test_readiness_exposes_topology_profile(self) -> None:
        readiness = build_readiness(self._config(readiness_profile="staging"), force=True).to_dict()

        self.assertTrue(readiness["orchestration_topology"]["ready"])
        self.assertTrue(readiness["orchestration_topology"]["org_profile_ready"])
        self.assertEqual(readiness["orchestration_topology"]["organization_profile"]["domain"], "platform_sre")
        self.assertTrue(readiness["required_checks"]["orchestration_topology_profile_configured"])

    def test_source_evidence_records_service_agent_registry_route(self) -> None:
        config = self._config()
        resolution = resolve_orchestration_topology(
            profile_path=config.orchestration_topology_profile_path,
            trigger=self._trigger(),
            decision=self._decision(),
            candidate_lanes=["hermes"],
            configured_filter=[],
            service_agent={
                "matched": True,
                "agent": {
                    "agent_id": "agent_search_ops",
                    "service": "search-api",
                    "agent_type": "service_owner",
                    "trust_level": "staging",
                },
            },
            ownership_registry_path=config.ownership_registry_path,
            connector_certification_registry_path=config.connector_certification_registry_path,
            policy_lifecycle_manifest_path=config.policy_lifecycle_manifest_path,
            threat_model_register_path=config.threat_model_register_path,
            state_directory=config.state_directory,
        )

        service_agent = resolution["source_evidence"]["service_agent"]
        self.assertEqual(service_agent["source_ref"], "state://service-agents")
        self.assertTrue(service_agent["matched"])
        self.assertEqual(service_agent["agent_id"], "agent_search_ops")
        self.assertEqual(resolution["context"]["trust_level"], "staging")

    def test_service_override_changes_routing_before_task_creation(self) -> None:
        profile_path = self._write_profile(
            [
                {
                    "rule_id": "search-hybrid",
                    "topology": "hybrid",
                    "match": {"services": ["search-api"], "action_classes": ["rollback_deployment"]},
                    "lanes": ["temporal", "kubernetes", "hermes"],
                    "lane_overrides": {
                        "temporal": {"topology_role": "supervisor_lane"},
                        "kubernetes": {"topology_role": "bounded_actuator_lane", "authority": "bounded_action"},
                        "hermes": {"topology_role": "peer_proposal_lane"},
                    },
                    "reason": "search rollback uses durable workflow plus Kubernetes actuator lane",
                }
            ]
        )
        config = self._config(profile_path=profile_path)
        config.kubernetes_live_execution_enabled = True
        config.kubernetes_allowed_contexts = ("prod-cluster",)
        config.kubernetes_allowed_namespaces = ("search",)
        task = AgentMeshService(config=config).build_tasks(
            run_id="run_topology_search",
            trigger=self._trigger(service="search-api", source="kubernetes"),
            decision=self._decision(action="rollback_deployment", system="kubernetes_service", risk="high"),
            evaluation=self._evaluation(),
            integration_readiness=build_readiness(config, force=True).to_dict(),
        )[0]

        self.assertEqual(task.orchestration_topology["active_topology"], "hybrid")
        self.assertEqual(task.orchestration_topology["rule_id"], "search-hybrid")
        self.assertEqual(task.agents, ["temporal", "kubernetes", "hermes"])
        kubernetes_lane = self._lane(task.orchestration_topology, "kubernetes")
        self.assertEqual(kubernetes_lane["authority"], "bounded_action")
        self.assertEqual(kubernetes_lane["topology_role"], "bounded_actuator_lane")
        self.assertIn("model_binding", kubernetes_lane)
        self.assertIn("source_evidence", kubernetes_lane)
        self.assertIn("reconciliation_mode", kubernetes_lane)

    def test_hierarchical_records_supervisor_and_workers(self) -> None:
        profile_path = self._write_profile(
            [
                {
                    "rule_id": "workflow-hierarchy",
                    "topology": "hierarchical",
                    "match": {"signal_sources": ["workflow"]},
                    "lanes": ["temporal", "airflow", "hermes"],
                }
            ]
        )
        resolution = self._resolve(profile_path, source="workflow", candidates=["temporal", "airflow", "hermes"])

        self.assertEqual(resolution["active_topology"], "hierarchical")
        self.assertEqual(self._lane(resolution, "temporal")["role"], "supervisor")
        self.assertEqual(self._lane(resolution, "airflow")["role"], "worker")

    def test_decentralized_records_peer_reconciliation(self) -> None:
        profile_path = self._write_profile(
            [
                {
                    "rule_id": "data-peers",
                    "topology": "decentralized",
                    "match": {"signal_sources": ["data"]},
                    "lanes": ["dagster", "prefect", "flyte"],
                }
            ]
        )
        resolution = self._resolve(profile_path, source="data", candidates=["dagster", "prefect", "flyte"])

        self.assertEqual(resolution["active_topology"], "decentralized")
        self.assertEqual(
            {lane["role"] for lane in resolution["selected_lanes"]},
            {"peer_proposal"},
        )
        self.assertEqual(resolution["reconciliation"], "mesh_reconciles_parallel_peer_proposals")

    def test_federated_blocks_unresolved_boundaries(self) -> None:
        profile_path = self._write_profile(
            [
                {
                    "rule_id": "federated-tenant",
                    "topology": "federated",
                    "match": {"services": ["unknown-service"]},
                    "lanes": ["hermes", "temporal"],
                }
            ]
        )
        resolution = self._resolve(profile_path, service="unknown-service", candidates=["hermes", "temporal"])

        self.assertEqual(resolution["active_topology"], "federated")
        self.assertIn("federated_ownership_boundary_unresolved", resolution["blockers"])
        self.assertIn("federated_data_boundary_missing", resolution["blockers"])

    def test_hybrid_can_match_risk_tier(self) -> None:
        profile_path = self._write_profile(
            [
                {
                    "rule_id": "high-risk-hybrid",
                    "topology": "hybrid",
                    "match": {"risk_tiers": ["high"]},
                    "lanes": ["hermes", "goose", "kubernetes"],
                }
            ]
        )
        resolution = self._resolve(profile_path, risk="high", candidates=["hermes", "goose", "kubernetes"])

        self.assertEqual(resolution["active_topology"], "hybrid")
        self.assertEqual(resolution["rule_id"], "high-risk-hybrid")

    def test_org_infra_profile_fields_drive_rule_matching(self) -> None:
        profile_path = self._write_profile(
            [
                {
                    "rule_id": "org-infra-match",
                    "topology": "hybrid",
                    "match": {
                        "org_domains": ["platform_sre"],
                        "teams": ["platform.search"],
                        "deployment_substrates": ["kubernetes"],
                        "data_boundaries": ["operational"],
                        "autonomy_tiers": ["approval_required"],
                        "allowed_model_providers": ["openai-compatible"],
                    },
                    "lanes": ["hermes", "temporal"],
                }
            ]
        )
        resolution = self._resolve(
            profile_path,
            source="kubernetes",
            candidates=["hermes", "temporal"],
        )

        self.assertEqual(resolution["rule_id"], "org-infra-match")
        self.assertEqual(resolution["context"]["org_domain"], "platform_sre")
        self.assertIn("platform.search", resolution["context"]["team_ids"])

    def test_model_bindings_are_recorded_without_secret_material(self) -> None:
        profile_path = self._write_profile(
            [
                {
                    "rule_id": "model-bound",
                    "topology": "centralized",
                    "match": {"signal_sources": ["otel"]},
                    "lanes": ["codex", "latentmas", "hermes"],
                }
            ]
        )
        config = self._config(profile_path=profile_path)
        config.latentmas_enabled = True
        task = AgentMeshService(config=config).build_tasks(
            run_id="run_topology_models",
            trigger=self._trigger(source="otel"),
            decision=self._decision(),
            evaluation=self._evaluation(),
            integration_readiness=build_readiness(config, force=True).to_dict(),
        )[0]

        codex = self._lane(task.orchestration_topology, "codex")
        latentmas = self._lane(task.orchestration_topology, "latentmas")
        self.assertEqual(codex["model_binding"]["provider"], "openai")
        self.assertEqual(codex["model_binding"]["model"], "MiniMax-M2.7")
        self.assertFalse(codex["model_binding"]["secret_material_present"])
        self.assertEqual(latentmas["model_binding"]["provider"], "huggingface")
        self.assertFalse(latentmas["model_binding"]["secret_material_present"])

    def test_shipped_profile_hybrid_mixes_supervisor_peer_federated_and_actuator_roles(self) -> None:
        resolution = self._resolve(
            Path(self._config().orchestration_topology_profile_path),
            source="kubernetes",
            action="rollback_deployment",
            risk="high",
            candidates=["temporal", "kubernetes", "hermes", "dagster"],
            parameters={"tenant_id": "tenant_a"},
        )

        roles = {lane["lane_id"]: lane["topology_role"] for lane in resolution["selected_lanes"]}
        self.assertEqual(resolution["rule_id"], "tenant-search-hybrid")
        self.assertEqual(roles["temporal"], "supervisor_lane")
        self.assertEqual(roles["hermes"], "peer_proposal_lane")
        self.assertEqual(roles["dagster"], "federated_tenant_lane")
        self.assertEqual(roles["kubernetes"], "bounded_actuator_lane")

    def test_configured_filter_is_preserved(self) -> None:
        config = self._config()
        config.agent_mesh_agents = ("hermes",)
        task = AgentMeshService(config=config).build_tasks(
            run_id="run_topology_filter",
            trigger=self._trigger(),
            decision=self._decision(),
            evaluation=self._evaluation(),
            integration_readiness=build_readiness(config, force=True).to_dict(),
        )[0]

        self.assertEqual(task.agents, ["hermes"])
        self.assertEqual(task.orchestration_topology["configured_filter"], ["hermes"])

    def test_resolver_applies_configured_filter_to_requested_rule_lanes(self) -> None:
        profile_path = self._write_profile(
            [
                {
                    "rule_id": "hermes-rule",
                    "topology": "centralized",
                    "match": {"signal_sources": ["otel"]},
                    "lanes": ["hermes"],
                }
            ]
        )
        config = self._config(profile_path=profile_path)
        resolution = resolve_orchestration_topology(
            profile_path=profile_path,
            trigger=self._trigger(source="otel"),
            decision=self._decision(),
            candidate_lanes=["goose", "hermes"],
            configured_filter=["goose"],
            ownership_registry_path=config.ownership_registry_path,
            connector_certification_registry_path=config.connector_certification_registry_path,
            policy_lifecycle_manifest_path=config.policy_lifecycle_manifest_path,
            threat_model_register_path=config.threat_model_register_path,
            state_directory=config.state_directory,
        )

        self.assertEqual(resolution["selected_agents"], ["goose"])
        self.assertIn(
            "topology_rule_lanes_filtered_by_agent_mesh_agents",
            resolution["blockers"],
        )
        self.assertNotIn("hermes", resolution["selected_agents"])

    def test_topology_rule_cannot_bypass_configured_filter(self) -> None:
        profile_path = self._write_profile(
            [
                {
                    "rule_id": "hermes-rule",
                    "topology": "centralized",
                    "match": {"signal_sources": ["otel"]},
                    "lanes": ["hermes"],
                }
            ]
        )
        config = self._config(profile_path=profile_path)
        config.agent_mesh_agents = ("goose",)
        task = AgentMeshService(config=config).build_tasks(
            run_id="run_topology_filter_authority",
            trigger=self._trigger(source="otel"),
            decision=self._decision(),
            evaluation=self._evaluation(),
            integration_readiness=build_readiness(config, force=True).to_dict(),
        )[0]

        self.assertEqual(task.agents, ["goose"])
        self.assertEqual(task.orchestration_topology["selected_agents"], ["goose"])
        self.assertIn(
            "topology_rule_lanes_filtered_by_agent_mesh_agents",
            task.orchestration_topology["blockers"],
        )
        self.assertNotIn("hermes", task.agents)

    def test_uncertified_external_connectors_remain_proposal_only(self) -> None:
        profile_path = self._write_profile(
            [
                {
                    "rule_id": "external-action",
                    "topology": "hybrid",
                    "match": {"action_classes": ["execute_external_workflow"]},
                    "lanes": ["n8n"],
                }
            ]
        )
        resolution = self._resolve(
            profile_path,
            action="execute_external_workflow",
            candidates=["n8n"],
        )

        lane = self._lane(resolution, "n8n")
        self.assertEqual(lane["authority"], "proposal_only")
        self.assertNotEqual(lane["authority"], "bounded_action")

    def test_profile_file_validates(self) -> None:
        profile = load_orchestration_topology_profile(self._config().orchestration_topology_profile_path)

        self.assertEqual(profile["version"], "mesh.orchestration_topology_profile.v1")
        self.assertEqual(profile["default_topology"], "centralized")

    def test_shipped_profile_declares_active_topology_modes(self) -> None:
        profile = load_orchestration_topology_profile(self._config().orchestration_topology_profile_path)

        modes = {profile["default_topology"], *(rule["topology"] for rule in profile["rules"])}
        self.assertEqual(modes, {"centralized", "hierarchical", "decentralized", "federated", "hybrid"})
        self.assertEqual(
            [rule["rule_id"] for rule in profile["rules"]],
            [
                "tenant-search-hybrid",
                "search-kubernetes-hybrid",
                "workflow-supervisor-hierarchy",
                "data-pipeline-peer-proposals",
                "tenant-model-federation",
            ],
        )

    def test_shipped_profile_resolves_non_default_modes(self) -> None:
        profile_path = Path(self._config().orchestration_topology_profile_path)

        workflow = self._resolve(profile_path, source="workflow", candidates=["temporal", "airflow", "hermes"])
        data = self._resolve(profile_path, source="data", candidates=["dagster", "prefect", "flyte"])
        federated = self._resolve(profile_path, source="ml", candidates=["flyte", "dagster", "hermes"])
        hybrid = self._resolve(
            profile_path,
            source="kubernetes",
            action="rollback_deployment",
            risk="high",
            candidates=["temporal", "kubernetes", "hermes"],
        )

        self.assertEqual(workflow["active_topology"], "hierarchical")
        self.assertEqual(data["active_topology"], "decentralized")
        self.assertEqual(federated["active_topology"], "federated")
        self.assertEqual(hybrid["active_topology"], "hybrid")
        self.assertEqual(self._lane(hybrid, "kubernetes")["authority"], "bounded_action")

    def test_shipped_profile_routes_medium_kubernetes_rollbacks_to_hybrid(self) -> None:
        resolution = self._resolve(
            Path(self._config().orchestration_topology_profile_path),
            source="kubernetes",
            action="rollback_deployment",
            risk="medium",
            candidates=["temporal", "kubernetes", "hermes"],
        )

        self.assertEqual(resolution["active_topology"], "hybrid")
        self.assertEqual(resolution["rule_id"], "tenant-search-hybrid")

    def test_shipped_profile_routes_compose_search_rollbacks_to_hybrid(self) -> None:
        resolution = self._resolve(
            Path(self._config().orchestration_topology_profile_path),
            service="semantic-search",
            source="kubernetes",
            action="rollback_deployment",
            risk="medium",
            candidates=["temporal", "kubernetes", "hermes"],
        )

        self.assertEqual(resolution["active_topology"], "hybrid")
        self.assertEqual(resolution["rule_id"], "tenant-search-hybrid")

    def test_latentmas_enabled_lane_is_topology_governed(self) -> None:
        config = self._config()
        config.latentmas_enabled = True
        config.agent_mesh_agents = ("latentmas",)
        task = AgentMeshService(config=config).build_tasks(
            run_id="run_topology_latentmas_filter",
            trigger=self._trigger(),
            decision=self._decision(),
            evaluation=self._evaluation(),
            integration_readiness=build_readiness(config, force=True).to_dict(),
        )[0]

        self.assertEqual(task.agents, ["latentmas"])
        self.assertEqual(task.orchestration_topology["selected_agents"], ["latentmas"])
        self.assertEqual([attempt.agent for attempt in task.attempts], ["latentmas"])

    def test_topology_rule_can_exclude_enabled_latentmas(self) -> None:
        profile_path = self._write_profile(
            [
                {
                    "rule_id": "hermes-only",
                    "topology": "centralized",
                    "match": {"signal_sources": ["otel"]},
                    "lanes": ["hermes"],
                }
            ]
        )
        config = self._config(profile_path=profile_path)
        config.latentmas_enabled = True
        task = AgentMeshService(config=config).build_tasks(
            run_id="run_topology_latentmas_excluded",
            trigger=self._trigger(source="otel"),
            decision=self._decision(),
            evaluation=self._evaluation(),
            integration_readiness=build_readiness(config, force=True).to_dict(),
        )[0]

        self.assertEqual(task.agents, ["hermes"])
        self.assertNotIn("latentmas", [attempt.agent for attempt in task.attempts])

    def _resolve(
        self,
        profile_path: Path,
        *,
        service: str = "search-api",
        source: str = "otel",
        action: str = "investigate",
        risk: str = "low",
        candidates: list[str] | None = None,
        parameters: dict[str, object] | None = None,
    ) -> dict[str, object]:
        config = self._config(profile_path=profile_path)
        return resolve_orchestration_topology(
            profile_path=profile_path,
            trigger=self._trigger(service=service, source=source),
            decision=self._decision(action=action, risk=risk, parameters=parameters),
            candidate_lanes=candidates or list(DEFAULT_AGENT_WORKERS),
            configured_filter=[],
            ownership_registry_path=config.ownership_registry_path,
            connector_certification_registry_path=config.connector_certification_registry_path,
            policy_lifecycle_manifest_path=config.policy_lifecycle_manifest_path,
            threat_model_register_path=config.threat_model_register_path,
            state_directory=config.state_directory,
        )

    def _write_profile(self, rules: list[dict[str, object]]) -> Path:
        path = self.state_dir / "topology.profile.json"
        path.write_text(
            json.dumps(
                {
                    "version": "mesh.orchestration_topology_profile.v1",
                    "default_topology": "centralized",
                    "source_refs": {
                        "ownership_registry": "config/ownership.registry.json",
                        "connector_certification_registry": "config/connector-certification.registry.json",
                        "policy_lifecycle_manifest": "config/policy-lifecycle.manifest.json",
                        "threat_model_register": "config/threat-model.register.json",
                        "readiness": "/api/readiness",
                        "historical_outcomes": "state://runs",
                        "trust_ladder": "state://learning/trust_ladder.json",
                    },
                    "organization_profile": {
                        "domain": "platform_sre",
                        "teams": [{"team_id": "platform.search", "owned_services": ["search-api"]}],
                        "tenants": [{"tenant_id": "tenant_a"}],
                        "ownership_boundaries": [{"source_ref": "config/ownership.registry.json"}],
                        "deployment_substrates": [{"substrate": "kubernetes"}, {"substrate": "workflow"}, {"substrate": "data"}, {"substrate": "ml"}],
                        "data_boundaries": [{"boundary_id": "tenant_a_operational", "classification": "operational"}],
                        "preferred_agents": ["hermes", "goose", "temporal", "kubernetes", "dagster", "latentmas"],
                        "allowed_model_providers": ["openai-compatible", "openai", "huggingface"],
                        "allowed_models": [
                            {"provider": "openai-compatible", "model": "MiniMax-M2.7"},
                            {"provider": "openai-compatible", "model": "MiniMax-M2.5"},
                            {"provider": "huggingface", "model": "Qwen/Qwen3-4B"},
                        ],
                        "autonomy_tier": "approval_required",
                        "risk_thresholds": {"bounded_action_maximum": "high"},
                        "required_evidence_refs": ["config/ownership.registry.json", "config/connector-certification.registry.json"],
                    },
                    "model_provider_policy": {
                        "allowed_providers": ["openai-compatible", "openai", "huggingface"],
                        "allowed_models": [
                            {"provider": "openai-compatible", "model": "MiniMax-M2.7"},
                            {"provider": "openai-compatible", "model": "MiniMax-M2.5"},
                            {"provider": "huggingface", "model": "Qwen/Qwen3-4B"},
                        ],
                        "lane_defaults": {
                            "hermes": {"provider": "openai-compatible", "model": "MiniMax-M2.5", "route": "hermes_bridge", "secret_ref_envs": ["OPENAI_API_KEY", "MINIMAX_API_KEY"]},
                            "deepagents": {"provider": "openai-compatible", "model": "MiniMax-M2.7", "route": "deepagents_sandbox", "secret_ref_envs": ["OPENAI_API_KEY", "MINIMAX_API_KEY"]},
                            "latentmas": {"provider": "huggingface", "model": "Qwen/Qwen3-4B", "route": "latentmas_http", "secret_ref_envs": []},
                        },
                    },
                    "rules": rules,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return path

    def _config(self, *, profile_path: Path | None = None, readiness_profile: str = "local") -> RuntimeConfig:
        return RuntimeConfig(
            state_directory=str(self.state_dir),
            vault_path=str(self.state_dir / "vault"),
            integrations_config_path=str(self.state_dir / "integrations.json"),
            orchestration_topology_profile_path=str(profile_path) if profile_path else RuntimeConfig().orchestration_topology_profile_path,
            readiness_profile=readiness_profile,
            promptfoo_command="/missing/promptfoo",
            hermes_command="/missing/hermes",
            goose_command="/missing/goose",
            evo_command="/missing/evo",
        )

    def _trigger(self, *, service: str = "search-api", source: str = "otel") -> Trigger:
        return Trigger(
            trigger_id="trg_topology",
            trigger_type=f"{source}_signal",
            triggered_at="2026-05-06T00:00:00Z",
            environment="production",
            service=service,
            endpoint="/search",
            flag_key=None,
            current_rollout_pct=None,
            comparison_window=None,
            segment={},
            metrics={},
            related_context={"signal_source": source},
        )

    def _decision(
        self,
        *,
        action: str = "investigate",
        system: str = "noop",
        risk: str = "low",
        parameters: dict[str, object] | None = None,
    ) -> Decision:
        return Decision(
            decision_id="dec_topology",
            trigger_id="trg_topology",
            summary="Topology test decision",
            decision_type="investigate",
            autonomy_tier="approval_required",
            reasoning={},
            expected_outcome={},
            risk={"level": risk},
            confidence=0.8,
            execution_plan={"system": system, "action": action, "parameters": parameters or {}},
        )

    def _evaluation(self) -> EvaluationResult:
        return EvaluationResult(
            evaluation_id="eval_topology",
            decision_id="dec_topology",
            passed=True,
            final_recommendation="execute",
            stage_results={},
            blocking_reasons=[],
        )

    def _lane(self, resolution: dict[str, object], lane_id: str) -> dict[str, object]:
        for lane in resolution["selected_lanes"]:
            if lane["lane_id"] == lane_id:
                return lane
        raise AssertionError(f"missing lane {lane_id}")
