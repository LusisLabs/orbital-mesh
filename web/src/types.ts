export type SteeringMode = "approval_gate" | "interruptible_auto";
export type RuntimeMode = "native" | "promptfoo" | "goose" | "hermes";
export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";
export type InspectorTab =
  | "overview"
  | "evidence"
  | "policy"
  | "execution"
  | "feedback"
  | "agents"
  | "vault"
  | "merkle"
  | "code"
  | "research";

export interface GoalRecord {
  goal_id: string;
  title: string;
  objective: string;
  success_criteria: string[];
  status: string;
  created_at: string;
  updated_at: string;
  tags: string[];
  note_path?: string | null;
}

export interface ScenarioRecord {
  key: string;
  title: string;
  file: string;
  summary: {
    service: string;
    endpoint: string;
    flag_key: string;
    latency_delta_ms: number;
  };
}

export interface RunEventRecord {
  event_id: string;
  run_id: string;
  sequence: number;
  stage: string;
  event_type: string;
  recorded_at: string;
  payload: Record<string, unknown>;
  summary?: Record<string, unknown> | null;
  merkle_leaf_hash?: string | null;
  artifact_key?: string | null;
  integration_name?: string | null;
  status?: string | null;
}

export interface AgentAttempt {
  attempt_id: string;
  task_id: string;
  run_id: string;
  agent: "latentmas" | "goose" | "hermes" | "codex" | "claudecode" | "openclaw" | "evo" | string;
  adapter: string;
  status: string;
  started_at: string;
  completed_at: string;
  summary: string;
  changed_files: string[];
  test_results: Array<Record<string, unknown>>;
  risk_flags: string[];
  recommended_action: string;
  output: Record<string, unknown>;
}

export interface AgentTask {
  task_id: string;
  run_id: string;
  kind: "root_cause" | "patch" | "review" | "rollback_plan" | string;
  status: string;
  created_at: string;
  updated_at: string;
  allowed_paths: string[];
  test_commands: string[];
  kubernetes_scope: Record<string, unknown>;
  agents: string[];
  attempts: AgentAttempt[];
  selected_attempt_id?: string | null;
}

export interface EvoLaunchRecord {
  launch_id: string;
  action: string;
  status: string;
  requested_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  repo_path: string;
  target_path: string;
  benchmark_command?: string | null;
  metric?: string | null;
  instrumentation_mode?: string | null;
  gate_command?: string | null;
  workspace_detected: boolean;
  dashboard_url?: string | null;
  steps: Array<{
    argv: string[];
    returncode: number;
    stdout: string;
    stderr: string;
    duration_seconds: number;
  }>;
  experiment_id?: string | null;
  error?: string | null;
}

/** Goose / MiniMax autoresearch filesystem session (not a Mesh pipeline run). */
export interface ResearchSessionRecord {
  session_id: string;
  directory: string;
  question: string;
  status: string;
  minimax_model?: string | null;
  minimax_route?: string | null;
  goose?: Record<string, unknown> | null;
  updated_at: string;
  has_final_report: boolean;
  research_intelligence?: ResearchIntelligence;
}

export interface ResearchSessionDetail {
  session_id: string;
  directory: string;
  manifest: Record<string, unknown>;
  final_report_markdown: string | null;
  final_report_relative: string | null;
  research_intelligence?: ResearchIntelligence;
}

export interface ResearchAnchor {
  key: string;
  label: string;
  terms: string[];
  score: number;
}

export interface ResearchIntelligence {
  classification: "repo_grounded" | "mixed" | "off_domain" | "needs_review";
  repo_grounding_score: number;
  off_domain_score: number;
  flags: string[];
  anchors: ResearchAnchor[];
  repo_terms?: string[];
  off_domain_terms?: string[];
  unsupported_claim_terms?: string[];
  evidence_limit_terms?: string[];
  extracted_claims?: string[];
  extracted_risks?: string[];
  extracted_actions?: string[];
  documents_read?: string[];
  redacted_reasoning_blocks?: number;
}

export interface ResearchCorpusIntelligence {
  sessions_analyzed: number;
  classification_counts: Record<string, number>;
  recurring_flags: Record<string, number>;
  accepted_anchors: Array<{ key: string; label: string; session_count: number }>;
  drift_sessions: Array<{ session_id: string; directory: string; off_domain_terms: string[] }>;
  next_actions: string[];
}

export interface RunSessionRecord {
  run_id: string;
  created_at: string;
  updated_at: string;
  goal_id?: string | null;
  scenario_key?: string | null;
  stage: string;
  status: string;
  steering_mode: SteeringMode;
  auto_mode: boolean;
  pause_points: string[];
  pending_pause_stage?: string | null;
  evaluation_mode: RuntimeMode | "native";
  orchestration_mode: RuntimeMode | "native";
  latest_event_id?: string | null;
  latest_event_sequence: number;
  latest_merkle_root?: string | null;
  operator_notes: string[];
  artifacts: Record<string, any>;
  error?: string | null;
}

export interface MerkleSnapshot {
  run_id: string;
  root_hash: string;
  leaf_count: number;
  event_ids: string[];
}

export interface MerkleProof {
  run_id: string;
  event_id: string;
  leaf_hash: string;
  root_hash: string;
  valid: boolean;
  proof: Array<{ position: string; hash: string }>;
}

export interface RunDetail extends RunSessionRecord {
  events: RunEventRecord[];
  merkle: MerkleSnapshot;
}

export interface IntegrationStatus {
  name: string;
  ready: boolean;
  detail: string;
  command?: string | null;
  url?: string | null;
  primary_route?: string | null;
  fallback_route?: string | null;
  warnings?: string[];
}

export interface IntegrationReadiness {
  checked_at: string;
  promptfoo: IntegrationStatus;
  hermes: IntegrationStatus;
  goose: IntegrationStatus;
  evo: IntegrationStatus;
  latentmas: IntegrationStatus;
  deepagents: IntegrationStatus;
  vault_path: string;
  state_path: string;
  integrations_config_path: string;
}

export interface SystemSnapshot {
  timestamp: string;
  runs: RunSessionRecord[];
  readiness: IntegrationReadiness;
  active_runs: RunSessionRecord[];
}

export interface VaultTreeEntry {
  path: string;
  name: string;
  type: "file" | "directory";
  children?: VaultTreeEntry[];
}

export interface ToastMessage {
  id: string;
  variant: "success" | "error" | "info" | "warning";
  title: string;
  description?: string;
  duration?: number;
}
