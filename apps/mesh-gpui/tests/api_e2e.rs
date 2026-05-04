use std::{
    collections::BTreeMap,
    io::{BufRead, BufReader, Read, Write},
    net::{TcpListener, TcpStream},
    sync::{Arc, Mutex},
    thread,
    time::Duration,
};

use mesh_gpui::api::{MeshClient, OperatorContext};
use serde_json::{Value, json};

#[derive(Clone, Debug, Default)]
struct ObservedPost {
    path: String,
    operator: Option<String>,
    roles: Option<String>,
    body: Value,
}

#[test]
fn client_loads_snapshot_and_applies_full_stop_with_operator_headers() {
    let observed = Arc::new(Mutex::new(None));
    let server = FakeMeshServer::start(observed.clone(), 11);

    let client = MeshClient::new(server.base_url())
        .with_timeout(Duration::from_millis(800))
        .with_operator(Some(OperatorContext::new(
            "ops@example.test",
            ["viewer", "launcher", "approver", "admin"],
        )));

    let snapshot = client.load_snapshot();

    assert_eq!(snapshot.errors, Vec::<String>::new());
    assert_eq!(
        snapshot
            .health
            .as_ref()
            .map(|health| health.status.as_str()),
        Some("ok")
    );
    assert_eq!(
        snapshot
            .readiness
            .as_ref()
            .map(|readiness| readiness.status.as_str()),
        Some("ready")
    );
    assert_eq!(snapshot.runs.len(), 1);
    assert_eq!(snapshot.trust_ladder.len(), 1);
    assert_eq!(snapshot.simulations.len(), 1);
    assert_eq!(snapshot.benchmarks.len(), 1);
    assert_eq!(snapshot.service_agents.len(), 1);
    assert_eq!(
        snapshot
            .pilot_packet
            .as_ref()
            .map(|packet| packet.status.as_str()),
        Some("go")
    );

    let kill_switch = client
        .apply_full_stop()
        .expect("kill switch should succeed");
    assert_eq!(kill_switch.actions, vec!["watchers_stopped"]);

    let observed = observed
        .lock()
        .expect("post observation lock poisoned")
        .clone()
        .expect("server did not observe kill-switch POST");
    assert_eq!(observed.path, "/api/kill-switch");
    assert_eq!(observed.operator.as_deref(), Some("ops@example.test"));
    assert_eq!(
        observed.roles.as_deref(),
        Some("viewer,launcher,approver,admin")
    );
    assert_eq!(observed.body["stop_watchers"], true);
    assert_eq!(observed.body["disable_live_execution"], true);
    assert_eq!(observed.body["clear_namespace_allowlist"], true);
    assert_eq!(observed.body["force_approval_gate"], true);
}

#[test]
fn client_records_endpoint_failures_without_discarding_good_surfaces() {
    let server = FakeMeshServer::start_with_readiness_failure();
    let client = MeshClient::new(server.base_url()).with_timeout(Duration::from_millis(800));

    let snapshot = client.load_snapshot();

    assert!(snapshot.health.is_some());
    assert!(snapshot.readiness.is_none());
    assert!(snapshot.errors.iter().any(|error| {
        error.contains("readiness: GET /api/readiness failed: synthetic readiness failure")
    }));
}

struct FakeMeshServer {
    address: String,
}

impl FakeMeshServer {
    fn start(observed_post: Arc<Mutex<Option<ObservedPost>>>, expected_requests: usize) -> Self {
        Self::start_with(observed_post, expected_requests, false)
    }

    fn start_with_readiness_failure() -> Self {
        Self::start_with(Arc::new(Mutex::new(None)), 10, true)
    }

    fn start_with(
        observed_post: Arc<Mutex<Option<ObservedPost>>>,
        expected_requests: usize,
        fail_readiness: bool,
    ) -> Self {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind fake Mesh API");
        let address = listener
            .local_addr()
            .expect("fake Mesh API address")
            .to_string();

        thread::spawn(move || {
            for stream in listener.incoming().take(expected_requests) {
                let stream = stream.expect("fake Mesh API connection");
                handle_connection(stream, &observed_post, fail_readiness);
            }
        });

        Self { address }
    }

    fn base_url(&self) -> String {
        format!("http://{}", self.address)
    }
}

fn handle_connection(
    mut stream: TcpStream,
    observed_post: &Arc<Mutex<Option<ObservedPost>>>,
    fail_readiness: bool,
) {
    let mut reader = BufReader::new(stream.try_clone().expect("clone stream"));
    let mut request_line = String::new();
    reader.read_line(&mut request_line).expect("request line");
    let mut parts = request_line.split_whitespace();
    let method = parts.next().unwrap_or_default().to_string();
    let path = parts.next().unwrap_or_default().to_string();

    let mut headers = BTreeMap::new();
    loop {
        let mut line = String::new();
        reader.read_line(&mut line).expect("header line");
        let trimmed = line.trim_end();
        if trimmed.is_empty() {
            break;
        }
        if let Some((name, value)) = trimmed.split_once(':') {
            headers.insert(name.to_ascii_lowercase(), value.trim().to_string());
        }
    }

    let content_length = headers
        .get("content-length")
        .and_then(|value| value.parse::<usize>().ok())
        .unwrap_or_default();
    let mut body = vec![0; content_length];
    if content_length > 0 {
        reader.read_exact(&mut body).expect("request body");
    }

    if method == "POST" && path == "/api/kill-switch" {
        let body = serde_json::from_slice(&body).expect("kill-switch JSON body");
        *observed_post
            .lock()
            .expect("post observation lock poisoned") = Some(ObservedPost {
            path,
            operator: headers.get("x-mesh-operator").cloned(),
            roles: headers.get("x-mesh-roles").cloned(),
            body,
        });
        write_json(&mut stream, 200, kill_switch_response());
        return;
    }

    if fail_readiness && path == "/api/readiness" {
        write_json(
            &mut stream,
            503,
            json!({ "error": "synthetic readiness failure" }),
        );
        return;
    }

    let payload = match path.as_str() {
        "/api/health" => health_response(),
        "/api/readiness" => readiness_response(),
        "/api/watchers" => watchers_response(),
        "/api/kill-switch" => kill_switch_response(),
        "/api/runs?summary=1" => runs_response(),
        "/api/trust-ladder" => trust_ladder_response(),
        "/api/simulations" => simulations_response(),
        "/api/benchmarks?limit=20" => benchmarks_response(),
        "/api/service-agents" => service_agents_response(),
        "/api/pilot/go-no-go" => pilot_packet_response(),
        _ => json!({ "error": format!("unexpected path: {path}") }),
    };
    let status = if payload.get("error").is_some() {
        404
    } else {
        200
    };
    write_json(&mut stream, status, payload);
}

fn write_json(stream: &mut TcpStream, status: u16, body: Value) {
    let status_text = if status == 200 { "OK" } else { "ERROR" };
    let body = serde_json::to_vec(&body).expect("serialize response");
    let response = format!(
        "HTTP/1.1 {status} {status_text}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    );
    stream
        .write_all(response.as_bytes())
        .expect("write headers");
    stream.write_all(&body).expect("write body");
}

fn health_response() -> Value {
    json!({
        "status": "ok",
        "timestamp": "2026-05-04T17:30:00Z",
        "environment": "test",
        "version": "0.1.0",
        "commit": "abc123"
    })
}

fn integration_response() -> Value {
    json!({
        "name": "test",
        "ready": true,
        "detail": "ready",
        "warnings": [],
        "certification": "staging-ready",
        "required_before": "pilot",
        "posture": "proposal-only"
    })
}

fn readiness_response() -> Value {
    json!({
        "checked_at": "2026-05-04T17:30:00Z",
        "profile": "staging",
        "status": "ready",
        "required_checks": { "operator_identity": true },
        "optional_checks": {},
        "blockers": [],
        "connector_certification": {
            "kubernetes": { "certification": "staging-ready" }
        },
        "promptfoo": integration_response(),
        "hermes": integration_response(),
        "goose": integration_response(),
        "evo": integration_response(),
        "latentmas": integration_response(),
        "deepagents": integration_response(),
        "vault_path": ".mesh-runtime-state/vault",
        "state_path": ".mesh-runtime-state",
        "integrations_config_path": "config/integrations.json"
    })
}

fn kill_switch_response() -> Value {
    json!({
        "watchers": watchers_response(),
        "live_execution_enabled": false,
        "force_approval_gate": true,
        "default_steering_mode": "approval_gate",
        "allowed_contexts": [],
        "allowed_namespaces": [],
        "actions": ["watchers_stopped"],
        "operator": { "operator_id": "ops@example.test" }
    })
}

fn watchers_response() -> Value {
    json!({
        "watchers": [{
            "name": "kubernetes",
            "signal_source": "kubernetes",
            "interval_seconds": 10,
            "running": false,
            "detail": {}
        }]
    })
}

fn runs_response() -> Value {
    json!({
        "runs": [{
            "run_id": "run_001",
            "created_at": "2026-05-04T17:20:00Z",
            "updated_at": "2026-05-04T17:25:00Z",
            "goal_id": null,
            "scenario_key": "fixture.latency",
            "stage": "awaiting_operator",
            "status": "awaiting_operator",
            "steering_mode": "approval_gate",
            "auto_mode": false,
            "pause_points": ["evaluation_ready"],
            "pending_pause_stage": "evaluation_ready",
            "evaluation_mode": "mesh_native",
            "orchestration_mode": "proposal",
            "latest_event_id": "evt_001",
            "latest_event_sequence": 4,
            "latest_merkle_root": "root",
            "operator_notes": [],
            "artifacts": {}
        }]
    })
}

fn trust_ladder_response() -> Value {
    json!({
        "entries": [{
            "action_class": "restart",
            "service": "checkout",
            "level": "review",
            "previous_level": "draft",
            "total_runs": 10,
            "successful_runs": 9,
            "success_rate": 0.9,
            "consecutive_failures": 0,
            "promotion_count": 1,
            "demotion_count": 0,
            "override_count": 1
        }]
    })
}

fn simulations_response() -> Value {
    json!({
        "simulations": [{
            "scenario_id": "sim.denied_namespace",
            "title": "Denied namespace",
            "expected_decision_type": "deny",
            "expected_outcome": "blocked",
            "fault_type": "policy",
            "sandbox": {},
            "tags": ["policy"],
            "standards_refs": ["roadmap.phase_1"]
        }]
    })
}

fn benchmarks_response() -> Value {
    json!({
        "benchmarks": [{
            "benchmark_id": "bench_001",
            "run_id": "run_001",
            "scenario_id": "sim.denied_namespace",
            "recorded_at": "2026-05-04T17:26:00Z",
            "score": 1.0,
            "passed": true,
            "dimensions": {},
            "dataset_ref": null
        }]
    })
}

fn service_agents_response() -> Value {
    json!({
        "service_agents": [{
            "service": "checkout",
            "scope": { "paths": ["services/checkout"] },
            "runbook_path": "docs/runbooks/checkout.md",
            "preferred_lanes": ["hermes", "goose"],
            "autonomy_overrides": {}
        }]
    })
}

fn pilot_packet_response() -> Value {
    json!({
        "packet_version": "pilot.go_no_go.v1",
        "generated_at": "2026-05-04T17:30:00Z",
        "status": "go",
        "checks": {
            "readiness_green": true,
            "observed_run_evidence": true
        },
        "missing_evidence": [],
        "readiness": readiness_response(),
        "observed": {
            "run_count": 1,
            "approved_run_ids": ["run_001"],
            "live_action_run_ids": [],
            "denied_action_run_ids": ["run_001"],
            "merkle_run_ids": ["run_001"]
        }
    })
}
