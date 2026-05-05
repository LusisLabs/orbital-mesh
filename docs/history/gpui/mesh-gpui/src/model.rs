use std::collections::BTreeMap;

use serde::Deserialize;
use serde_json::Value;

#[derive(Clone, Debug, Default)]
pub struct MeshSnapshot {
    pub collected_at: String,
    pub errors: Vec<String>,
    pub health: Option<HealthSnapshot>,
    pub readiness: Option<IntegrationReadiness>,
    pub watchers: Option<WatcherStatus>,
    pub kill_switch: Option<KillSwitchStatus>,
    pub runs: Vec<RunSession>,
    pub trust_ladder: Vec<TrustLadderEntry>,
    pub simulations: Vec<SimulationScenario>,
    pub benchmarks: Vec<BenchmarkRecord>,
    pub service_agents: Vec<ServiceAgentRecord>,
    pub pilot_packet: Option<PilotGoNoGoPacket>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct HealthSnapshot {
    pub status: String,
    pub timestamp: String,
    pub environment: String,
    pub version: String,
    pub commit: String,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct IntegrationReadiness {
    pub checked_at: String,
    pub profile: String,
    pub status: String,
    pub required_checks: BTreeMap<String, Value>,
    pub optional_checks: BTreeMap<String, Value>,
    pub blockers: Vec<String>,
    pub connector_certification: BTreeMap<String, Value>,
    pub promptfoo: IntegrationStatus,
    pub hermes: IntegrationStatus,
    pub goose: IntegrationStatus,
    pub evo: IntegrationStatus,
    pub latentmas: IntegrationStatus,
    pub deepagents: IntegrationStatus,
    pub vault_path: String,
    pub state_path: String,
    pub integrations_config_path: String,
}

impl IntegrationReadiness {
    pub fn integrations(&self) -> [(&'static str, &IntegrationStatus); 6] {
        [
            ("Promptfoo", &self.promptfoo),
            ("Hermes", &self.hermes),
            ("Goose", &self.goose),
            ("Evo", &self.evo),
            ("LatentMAS", &self.latentmas),
            ("Deep Agents", &self.deepagents),
        ]
    }
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct IntegrationStatus {
    pub name: String,
    pub ready: bool,
    pub detail: String,
    pub command: Option<String>,
    pub url: Option<String>,
    pub primary_route: Option<String>,
    pub fallback_route: Option<String>,
    pub warnings: Vec<String>,
    pub certification: String,
    pub required_before: String,
    pub posture: String,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct RunsEnvelope {
    pub runs: Vec<RunSession>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct RunSession {
    pub run_id: String,
    pub created_at: String,
    pub updated_at: String,
    pub goal_id: Option<String>,
    pub scenario_key: Option<String>,
    pub stage: String,
    pub status: String,
    pub steering_mode: String,
    pub auto_mode: bool,
    pub pause_points: Vec<String>,
    pub pending_pause_stage: Option<String>,
    pub evaluation_mode: String,
    pub orchestration_mode: String,
    pub latest_event_id: Option<String>,
    pub latest_event_sequence: u64,
    pub latest_merkle_root: Option<String>,
    pub operator_notes: Vec<String>,
    pub artifacts: BTreeMap<String, Value>,
    pub error: Option<String>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct WatcherStatus {
    pub watchers: Vec<WatcherRecord>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct WatcherRecord {
    pub name: String,
    pub signal_source: String,
    pub interval_seconds: f64,
    pub running: bool,
    pub detail: BTreeMap<String, Value>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct KillSwitchStatus {
    pub watchers: WatcherStatus,
    pub live_execution_enabled: bool,
    pub force_approval_gate: bool,
    pub default_steering_mode: String,
    pub allowed_contexts: Vec<String>,
    pub allowed_namespaces: Vec<String>,
    pub actions: Vec<String>,
    pub operator: Option<Value>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct TrustLadderEnvelope {
    pub entries: Vec<TrustLadderEntry>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct TrustLadderEntry {
    pub action_class: String,
    pub service: String,
    pub level: String,
    pub previous_level: String,
    pub total_runs: u64,
    pub successful_runs: u64,
    pub success_rate: f64,
    pub consecutive_failures: u64,
    pub promotion_count: u64,
    pub demotion_count: u64,
    pub override_count: u64,
    pub last_outcome: Option<String>,
    pub last_outcome_at: Option<String>,
    pub last_level_change_at: Option<String>,
    pub last_override_at: Option<String>,
    pub manual_override_reason: Option<String>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct SimulationsEnvelope {
    pub simulations: Vec<SimulationScenario>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct SimulationScenario {
    pub scenario_id: String,
    pub title: String,
    pub expected_decision_type: Option<String>,
    pub expected_outcome: Option<String>,
    pub fault_type: String,
    pub sandbox: BTreeMap<String, Value>,
    pub tags: Vec<String>,
    pub standards_refs: Vec<String>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct BenchmarksEnvelope {
    pub benchmarks: Vec<BenchmarkRecord>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct BenchmarkRecord {
    pub benchmark_id: String,
    pub run_id: String,
    pub scenario_id: String,
    pub recorded_at: String,
    pub score: f64,
    pub passed: bool,
    pub dimensions: BTreeMap<String, Value>,
    pub dataset_ref: Option<String>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct ServiceAgentsEnvelope {
    pub service_agents: Vec<ServiceAgentRecord>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct ServiceAgentRecord {
    pub service: String,
    pub scope: BTreeMap<String, Vec<String>>,
    pub runbook_path: Option<String>,
    pub preferred_lanes: Vec<String>,
    pub autonomy_overrides: BTreeMap<String, String>,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct PilotGoNoGoPacket {
    pub packet_version: String,
    pub generated_at: String,
    pub status: String,
    pub checks: BTreeMap<String, bool>,
    pub missing_evidence: Vec<String>,
    pub readiness: IntegrationReadiness,
    pub observed: PilotObserved,
}

#[derive(Clone, Debug, Default, Deserialize)]
#[serde(default)]
pub struct PilotObserved {
    pub run_count: u64,
    pub approved_run_ids: Vec<String>,
    pub live_action_run_ids: Vec<String>,
    pub denied_action_run_ids: Vec<String>,
    pub merkle_run_ids: Vec<String>,
}
