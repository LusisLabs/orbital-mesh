use std::time::{Duration, SystemTime, UNIX_EPOCH};

use anyhow::{Context as AnyhowContext, Result, anyhow};
use serde::de::DeserializeOwned;
use serde_json::json;
use ureq::{Agent, AgentBuilder, Error};

use crate::model::{
    BenchmarksEnvelope, HealthSnapshot, IntegrationReadiness, KillSwitchStatus, MeshSnapshot,
    PilotGoNoGoPacket, RunsEnvelope, ServiceAgentsEnvelope, SimulationsEnvelope,
    TrustLadderEnvelope, WatcherStatus,
};

const DEFAULT_TIMEOUT: Duration = Duration::from_secs(3);
const USER_AGENT: &str = "orbital-mesh-gpui/0.1";

#[derive(Clone, Debug)]
pub struct MeshClient {
    base_url: String,
    timeout: Duration,
    operator: Option<OperatorContext>,
    agent: Agent,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OperatorContext {
    operator_id: String,
    roles: Vec<String>,
}

impl OperatorContext {
    pub fn new(
        operator_id: impl Into<String>,
        roles: impl IntoIterator<Item = impl Into<String>>,
    ) -> Self {
        let roles = roles
            .into_iter()
            .map(Into::into)
            .map(|role: String| role.trim().to_lowercase())
            .filter(|role| !role.is_empty())
            .collect();
        Self {
            operator_id: operator_id.into().trim().to_string(),
            roles,
        }
    }

    fn is_empty(&self) -> bool {
        self.operator_id.is_empty()
    }

    fn roles_header(&self) -> String {
        self.roles.join(",")
    }
}

impl MeshClient {
    pub fn from_env() -> Self {
        let base_url = std::env::var("MESH_GPUI_API_URL")
            .or_else(|_| std::env::var("MESH_API_URL"))
            .unwrap_or_else(|_| "http://127.0.0.1:8787".to_string());
        let timeout = std::env::var("MESH_GPUI_API_TIMEOUT_MS")
            .ok()
            .and_then(|raw| raw.parse::<u64>().ok())
            .filter(|millis| *millis > 0)
            .map(Duration::from_millis)
            .unwrap_or(DEFAULT_TIMEOUT);
        let operator = std::env::var("MESH_GPUI_OPERATOR")
            .ok()
            .map(|operator_id| {
                let roles = std::env::var("MESH_GPUI_ROLES")
                    .unwrap_or_else(|_| "viewer,launcher,approver,admin".to_string());
                OperatorContext::new(operator_id, roles.split(','))
            })
            .filter(|operator| !operator.is_empty());
        Self::new(base_url)
            .with_timeout(timeout)
            .with_operator(operator)
    }

    pub fn new(base_url: impl Into<String>) -> Self {
        let timeout = DEFAULT_TIMEOUT;
        Self {
            base_url: normalize_base_url(base_url.into()),
            timeout,
            operator: None,
            agent: build_agent(timeout),
        }
    }

    pub fn base_url(&self) -> &str {
        &self.base_url
    }

    pub fn timeout(&self) -> Duration {
        self.timeout
    }

    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self.agent = build_agent(timeout);
        self
    }

    pub fn with_operator(mut self, operator: Option<OperatorContext>) -> Self {
        self.operator = operator.filter(|operator| !operator.is_empty());
        self
    }

    pub fn load_snapshot(&self) -> MeshSnapshot {
        let mut snapshot = MeshSnapshot {
            collected_at: epoch_label(),
            ..MeshSnapshot::default()
        };

        match self.get::<HealthSnapshot>("/api/health") {
            Ok(value) => snapshot.health = Some(value),
            Err(error) => snapshot.errors.push(format!("health: {error}")),
        }
        match self.get::<IntegrationReadiness>("/api/readiness") {
            Ok(value) => snapshot.readiness = Some(value),
            Err(error) => snapshot.errors.push(format!("readiness: {error}")),
        }
        match self.get::<WatcherStatus>("/api/watchers") {
            Ok(value) => snapshot.watchers = Some(value),
            Err(error) => snapshot.errors.push(format!("watchers: {error}")),
        }
        match self.get::<KillSwitchStatus>("/api/kill-switch") {
            Ok(value) => snapshot.kill_switch = Some(value),
            Err(error) => snapshot.errors.push(format!("kill-switch: {error}")),
        }
        match self.get::<RunsEnvelope>("/api/runs?summary=1") {
            Ok(value) => snapshot.runs = value.runs,
            Err(error) => snapshot.errors.push(format!("runs: {error}")),
        }
        match self.get::<TrustLadderEnvelope>("/api/trust-ladder") {
            Ok(value) => snapshot.trust_ladder = value.entries,
            Err(error) => snapshot.errors.push(format!("trust-ladder: {error}")),
        }
        match self.get::<SimulationsEnvelope>("/api/simulations") {
            Ok(value) => snapshot.simulations = value.simulations,
            Err(error) => snapshot.errors.push(format!("simulations: {error}")),
        }
        match self.get::<BenchmarksEnvelope>("/api/benchmarks?limit=20") {
            Ok(value) => snapshot.benchmarks = value.benchmarks,
            Err(error) => snapshot.errors.push(format!("benchmarks: {error}")),
        }
        match self.get::<ServiceAgentsEnvelope>("/api/service-agents") {
            Ok(value) => snapshot.service_agents = value.service_agents,
            Err(error) => snapshot.errors.push(format!("service-agents: {error}")),
        }
        match self.get::<PilotGoNoGoPacket>("/api/pilot/go-no-go") {
            Ok(value) => snapshot.pilot_packet = Some(value),
            Err(error) => snapshot.errors.push(format!("pilot/go-no-go: {error}")),
        }

        snapshot
    }

    pub fn apply_full_stop(&self) -> Result<KillSwitchStatus> {
        self.post(
            "/api/kill-switch",
            json!({
                "stop_watchers": true,
                "disable_live_execution": true,
                "clear_namespace_allowlist": true,
                "force_approval_gate": true
            }),
        )
    }

    fn get<T: DeserializeOwned>(&self, path: &str) -> Result<T> {
        let url = self.url(path);
        let request = self.with_headers(self.agent.get(&url));
        let response = request
            .call()
            .map_err(|error| self.request_error("GET", path, error))?;
        response
            .into_json::<T>()
            .with_context(|| format!("GET {path} returned invalid JSON"))
    }

    fn post<T: DeserializeOwned>(&self, path: &str, body: serde_json::Value) -> Result<T> {
        let url = self.url(path);
        let request = self
            .with_headers(self.agent.post(&url))
            .set("Content-Type", "application/json");
        let response = request
            .send_json(body)
            .map_err(|error| self.request_error("POST", path, error))?;
        response
            .into_json::<T>()
            .with_context(|| format!("POST {path} returned invalid JSON"))
    }

    fn with_headers(&self, request: ureq::Request) -> ureq::Request {
        let request = request
            .set("Accept", "application/json")
            .set("User-Agent", USER_AGENT);
        match &self.operator {
            Some(operator) => request
                .set("X-Mesh-Operator", &operator.operator_id)
                .set("X-Mesh-Roles", &operator.roles_header()),
            None => request,
        }
    }

    fn request_error(&self, method: &str, path: &str, error: Error) -> anyhow::Error {
        match error {
            Error::Status(code, response) => {
                let detail = response
                    .into_json::<serde_json::Value>()
                    .ok()
                    .and_then(|body| {
                        body.get("detail")
                            .or_else(|| body.get("error"))
                            .or_else(|| body.get("message"))
                            .and_then(|value| value.as_str())
                            .map(str::to_string)
                    })
                    .unwrap_or_else(|| format!("HTTP {code}"));
                anyhow!("{method} {path} failed: {detail}")
            }
            other => anyhow!(
                "{method} {path} failed after {}ms timeout: {other}",
                self.timeout.as_millis()
            ),
        }
    }

    fn url(&self, path: &str) -> String {
        format!("{}{}", self.base_url, path)
    }
}

fn build_agent(timeout: Duration) -> Agent {
    AgentBuilder::new()
        .timeout(timeout)
        .timeout_connect(timeout)
        .timeout_read(timeout)
        .timeout_write(timeout)
        .build()
}

fn normalize_base_url(raw: String) -> String {
    let trimmed = raw.trim().trim_end_matches('/');
    if trimmed.is_empty() {
        "http://127.0.0.1:8787".to_string()
    } else {
        trimmed.to_string()
    }
}

fn epoch_label() -> String {
    match SystemTime::now().duration_since(UNIX_EPOCH) {
        Ok(duration) => format!("{}s", duration.as_secs()),
        Err(_) => "unknown".to_string(),
    }
}
