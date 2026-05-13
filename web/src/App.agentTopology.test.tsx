import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentMeshPanel, buildAgentConnectors } from "./App";
import type { AgentTask, IntegrationReadiness, IntegrationStatus, RunDetail } from "./types";

const integrationStatus = (name: string): IntegrationStatus => ({
  name,
  ready: false,
  detail: "not configured",
  command: null,
  url: null,
  primary_route: null,
  fallback_route: null,
  warnings: [],
  certification: "proposal-only",
  required_before: "expansion",
  posture: "proposal lane",
});

describe("AgentMeshPanel topology", () => {
  it("renders active topology, lane reasons, blockers, and authority posture", () => {
    const task: AgentTask = {
      task_id: "task_run_topology_root_cause",
      run_id: "run_topology",
      kind: "root_cause",
      status: "completed",
      created_at: "2026-05-06T00:00:00Z",
      updated_at: "2026-05-06T00:00:01Z",
      allowed_paths: [],
      test_commands: [],
      kubernetes_scope: {},
      memory_scope: {},
      memory_packet: {},
      memory_write_policy: {},
      open_questions: [],
      agents: ["temporal", "kubernetes"],
      orchestration_topology: {
        active_topology: "hybrid",
        rule_id: "search-hybrid",
        routing_reason: "search rollback uses durable workflow plus Kubernetes actuator lane",
        reconciliation: "mesh_reconciles_per_rule_topology_outputs",
        selected_lanes: [
          {
            lane_id: "temporal",
            role: "hybrid_lane",
            topology_role: "supervisor_lane",
            model_binding: {
              supported: false,
              provider: "none",
              model: "none",
            },
            authority: "proposal_only",
            certified_state: "proposal-only",
            source_evidence: {
              profile_rule_ref: "config/orchestration-topology.profile.json#rules.search-hybrid",
            },
            reconciliation_mode: "supervisor_summary_before_mesh_reconciliation",
            blockers: [],
          },
          {
            lane_id: "kubernetes",
            role: "hybrid_lane",
            topology_role: "bounded_actuator_lane",
            model_binding: {
              supported: false,
              provider: "none",
              model: "none",
            },
            authority: "bounded_action",
            certified_state: "pilot-ready",
            source_evidence: {
              profile_rule_ref: "config/orchestration-topology.profile.json#rules.search-hybrid",
            },
            reconciliation_mode: "bounded_action_evidence",
            blockers: ["operator_approval_required"],
          },
        ],
        blockers: ["operator_approval_required"],
        source_evidence: {
          ownership_boundary: {
            record_id: "own_search_api_pilot",
            tenant_id: "tenant_a",
          },
        },
      },
      lane_routing: {},
      attempts: [],
      selected_attempt_id: null,
    };
    const run = {
      run_id: "run_topology",
      artifacts: {},
    } as RunDetail;

    const html = renderToStaticMarkup(
      <AgentMeshPanel run={run} tasks={[task]} />,
    );

    expect(html).toContain("Hybrid");
    expect(html).toContain("search-hybrid");
    expect(html).toContain("search rollback uses durable workflow plus Kubernetes actuator lane");
    expect(html).toContain("Temporal");
    expect(html).toContain("Kubernetes");
    expect(html).toContain("Bounded Actuator Lane");
    expect(html).toContain("Bounded Action Evidence");
    expect(html).toContain("Bounded Action");
    expect(html).toContain("Operator Approval Required");
    expect(html).toContain("own_search_api_pilot");
  });

  it("lists orchestration platform lanes with connector certification posture", () => {
    const readiness: IntegrationReadiness = {
      checked_at: "2026-05-06T00:00:00Z",
      profile: "pilot",
      status: "blocked",
      required_checks: {},
      optional_checks: {},
      blockers: [],
      blocker_details: {},
      connector_certification: {
        airflow: {
          state: "proposal-only",
          required_before: "expansion",
          authority_posture: "DAG state can inform Mesh evaluation but cannot approve or execute production actions",
        },
        temporal: {
          state: "proposal-only",
          required_before: "expansion",
          authority_posture: "Workflow history can inform Mesh reconciliation",
        },
        kubernetes: {
          state: "pilot-ready",
          required_before: "pilot",
          authority_posture: "live execution requires explicit context and namespace allowlists",
        },
        n8n: {
          state: "proposal-only",
          required_before: "expansion",
          authority_posture: "workflow trace proposal lane",
        },
      },
      orchestration_topology: {},
      promptfoo: integrationStatus("Promptfoo"),
      hermes: integrationStatus("Hermes"),
      goose: integrationStatus("Goose"),
      evo: integrationStatus("Evo"),
      latentmas: integrationStatus("LatentMAS"),
      deepagents: integrationStatus("DeepAgents"),
      vault_path: ".mesh-runtime-state",
      state_path: ".mesh-runtime-state",
      integrations_config_path: "config/integrations.json",
    };

    const connectors = buildAgentConnectors(readiness, []);

    expect(connectors.map((connector) => connector.id)).toEqual(
      expect.arrayContaining(["airflow", "temporal", "dagster", "prefect", "flyte", "luigi", "oozie", "kubernetes", "n8n"]),
    );
    expect(connectors.find((connector) => connector.id === "kubernetes")?.state).toBe("pilot-ready");
    expect(connectors.find((connector) => connector.id === "airflow")?.boundary).toContain("DAG state");
  });
});
