use gpui::*;
use gpui_component::{Root, Sizable, StyledExt, button::*, scroll::ScrollableElement};
use mesh_gpui::api::MeshClient;
use mesh_gpui::model::{
    BenchmarkRecord, HealthSnapshot, IntegrationReadiness, IntegrationStatus, KillSwitchStatus,
    MeshSnapshot, PilotGoNoGoPacket, RunSession, ServiceAgentRecord, SimulationScenario,
    TrustLadderEntry,
};
use serde_json::Value;

const APP_BG: u32 = 0x11100e;
const HEADER_BG: u32 = 0x171512;
const SIDEBAR_BG: u32 = 0x151817;
const PANEL_BG: u32 = 0x191d1b;
const PANEL_ALT: u32 = 0x20251f;
const ROW_BG: u32 = 0x161917;
const BORDER: u32 = 0x343a34;
const BORDER_SUBTLE: u32 = 0x252b27;
const TEXT: u32 = 0xeee9df;
const MUTED: u32 = 0xa9a195;
const SUBTLE: u32 = 0xcac2b5;
const ACCENT: u32 = 0x2f8f83;
const GOOD: u32 = 0x23734d;
const WARN: u32 = 0x9f6b25;
const DANGER: u32 = 0x8f2937;
const INFO: u32 = 0x2c6074;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ConsoleSection {
    Command,
    Runs,
    Readiness,
    Simulator,
    Trust,
    Connectors,
    PilotPacket,
    KillSwitch,
    Roadmap,
}

impl ConsoleSection {
    fn id(self) -> &'static str {
        match self {
            ConsoleSection::Command => "command",
            ConsoleSection::Runs => "runs",
            ConsoleSection::Readiness => "readiness",
            ConsoleSection::Simulator => "simulator",
            ConsoleSection::Trust => "trust",
            ConsoleSection::Connectors => "connectors",
            ConsoleSection::PilotPacket => "pilot-packet",
            ConsoleSection::KillSwitch => "kill-switch",
            ConsoleSection::Roadmap => "roadmap",
        }
    }

    fn label(self) -> &'static str {
        match self {
            ConsoleSection::Command => "Command",
            ConsoleSection::Runs => "Runs",
            ConsoleSection::Readiness => "Readiness",
            ConsoleSection::Simulator => "Simulator",
            ConsoleSection::Trust => "Trust",
            ConsoleSection::Connectors => "Connectors",
            ConsoleSection::PilotPacket => "Pilot Packet",
            ConsoleSection::KillSwitch => "Kill Switch",
            ConsoleSection::Roadmap => "Roadmap",
        }
    }
}

struct MeshConsole {
    client: MeshClient,
    active: ConsoleSection,
    snapshot: MeshSnapshot,
    last_error: Option<String>,
}

impl MeshConsole {
    fn new(_: &mut Context<Self>) -> Self {
        let client = MeshClient::from_env();
        let snapshot = client.load_snapshot();
        Self {
            client,
            active: ConsoleSection::Command,
            snapshot,
            last_error: None,
        }
    }

    fn refresh(&mut self, cx: &mut Context<Self>) {
        self.snapshot = self.client.load_snapshot();
        self.last_error = None;
        cx.notify();
    }

    fn apply_kill_switch(&mut self, cx: &mut Context<Self>) {
        match self.client.apply_full_stop() {
            Ok(status) => {
                self.snapshot.kill_switch = Some(status);
                self.snapshot = self.client.load_snapshot();
                self.last_error = None;
            }
            Err(error) => {
                self.last_error = Some(error.to_string());
            }
        }
        cx.notify();
    }

    fn nav_button(&self, section: ConsoleSection, cx: &mut Context<Self>) -> impl IntoElement {
        let button = Button::new(section.id())
            .label(section.label())
            .small()
            .on_click(cx.listener(move |this, _, _, cx| {
                this.active = section;
                cx.notify();
            }));

        if self.active == section {
            button.primary()
        } else {
            button.ghost()
        }
    }

    fn active_view(&self, cx: &mut Context<Self>) -> AnyElement {
        match self.active {
            ConsoleSection::Command => self.render_command(cx).into_any_element(),
            ConsoleSection::Runs => self.render_runs().into_any_element(),
            ConsoleSection::Readiness => self.render_readiness(),
            ConsoleSection::Simulator => self.render_simulator().into_any_element(),
            ConsoleSection::Trust => self.render_trust_ladder().into_any_element(),
            ConsoleSection::Connectors => self.render_connectors().into_any_element(),
            ConsoleSection::PilotPacket => self.render_pilot_packet(),
            ConsoleSection::KillSwitch => self.render_kill_switch(cx).into_any_element(),
            ConsoleSection::Roadmap => self.render_roadmap().into_any_element(),
        }
    }

    fn render_header(&self, cx: &mut Context<Self>) -> impl IntoElement {
        let health = self.snapshot.health.as_ref();
        let readiness = self.snapshot.readiness.as_ref();
        let status = readiness
            .map(|readiness| readiness.status.as_str())
            .or_else(|| health.map(|health| health.status.as_str()))
            .unwrap_or("offline");
        let profile = readiness
            .map(|readiness| readiness.profile.as_str())
            .unwrap_or("unknown");

        div()
            .h_flex()
            .justify_between()
            .items_center()
            .gap_4()
            .p_4()
            .border_b_1()
            .border_color(rgb(BORDER_SUBTLE))
            .bg(rgb(HEADER_BG))
            .child(
                div()
                    .v_flex()
                    .gap_1()
                    .child(
                        div()
                            .text_size(px(22.0))
                            .font_weight(FontWeight::SEMIBOLD)
                            .text_color(rgb(ACCENT))
                            .child("Orbital Mesh"),
                    )
                    .child(
                        div()
                            .text_color(rgb(MUTED))
                            .child("GPUI operator console for evidence-first production control"),
                    ),
            )
            .child(
                div()
                    .h_flex()
                    .items_center()
                    .gap_3()
                    .child(self.metric_chip("API", self.client.base_url()))
                    .child(self.metric_chip("Profile", profile))
                    .child(self.metric_chip("Status", status))
                    .child(self.metric_chip("Snapshot", &self.snapshot.collected_at))
                    .child(
                        Button::new("refresh")
                            .label("Refresh")
                            .primary()
                            .small()
                            .on_click(cx.listener(|this, _, _, cx| {
                                this.refresh(cx);
                            })),
                    ),
            )
    }

    fn render_sidebar(&self, cx: &mut Context<Self>) -> impl IntoElement {
        div()
            .v_flex()
            .gap_2()
            .w(px(188.0))
            .p_3()
            .border_r_1()
            .border_color(rgb(BORDER_SUBTLE))
            .bg(rgb(SIDEBAR_BG))
            .child(self.nav_button(ConsoleSection::Command, cx))
            .child(self.nav_button(ConsoleSection::Runs, cx))
            .child(self.nav_button(ConsoleSection::Readiness, cx))
            .child(self.nav_button(ConsoleSection::Simulator, cx))
            .child(self.nav_button(ConsoleSection::Trust, cx))
            .child(self.nav_button(ConsoleSection::Connectors, cx))
            .child(self.nav_button(ConsoleSection::PilotPacket, cx))
            .child(self.nav_button(ConsoleSection::KillSwitch, cx))
            .child(self.nav_button(ConsoleSection::Roadmap, cx))
    }

    fn render_command(&self, cx: &mut Context<Self>) -> impl IntoElement {
        let readiness = self.snapshot.readiness.as_ref();
        let health = self.snapshot.health.as_ref();
        let kill_switch = self.snapshot.kill_switch.as_ref();
        let packet = self.snapshot.pilot_packet.as_ref();
        let active_runs = self
            .snapshot
            .runs
            .iter()
            .filter(|run| !matches!(run.status.as_str(), "completed" | "failed" | "cancelled"))
            .count();
        let watchers_running = kill_switch
            .map(|status| &status.watchers)
            .or(self.snapshot.watchers.as_ref())
            .map(|watchers| {
                watchers
                    .watchers
                    .iter()
                    .filter(|watcher| watcher.running)
                    .count()
            })
            .unwrap_or_default();

        div()
            .v_flex()
            .gap_4()
            .child(self.section_title(
                "Command Center",
                "Named operators launch, inspect, approve, audit, and stop Mesh here.",
            ))
            .child(
                div()
                    .grid()
                    .grid_cols(4)
                    .gap_3()
                    .child(
                        self.status_card(
                            "Control Plane",
                            health.map(|h| h.status.as_str()).unwrap_or("offline"),
                            health
                                .map(format_health_detail)
                                .unwrap_or_else(|| "No /api/health response".to_string()),
                        ),
                    )
                    .child(
                        self.status_card(
                            "Readiness",
                            readiness.map(|r| r.status.as_str()).unwrap_or("unknown"),
                            readiness
                                .map(|r| {
                                    format!(
                                        "{} blockers in {} profile",
                                        r.blockers.len(),
                                        r.profile
                                    )
                                })
                                .unwrap_or_else(|| "No readiness snapshot".to_string()),
                        ),
                    )
                    .child(self.status_card(
                        "Active Runs",
                        &active_runs.to_string(),
                        format!(
                            "{} total runs in the current state store",
                            self.snapshot.runs.len()
                        ),
                    ))
                    .child(
                        self.status_card(
                            "Watchers",
                            &watchers_running.to_string(),
                            self.snapshot
                                .watchers
                                .as_ref()
                                .map(|s| format!("{} registered sources", s.watchers.len()))
                                .or_else(|| {
                                    kill_switch.map(|s| {
                                        format!("{} registered sources", s.watchers.watchers.len())
                                    })
                                })
                                .unwrap_or_else(|| "No watcher registry status".to_string()),
                        ),
                    ),
            )
            .child(self.render_authority_band())
            .child(
                div()
                    .grid()
                    .grid_cols(2)
                    .gap_3()
                    .child(
                        self.panel(
                            "Operator Work Queue",
                            div()
                                .v_flex()
                                .gap_2()
                                .children(self.snapshot.runs.iter().take(6).map(render_run_row))
                                .child(empty_state(
                                    self.snapshot.runs.is_empty(),
                                    "No runs recorded yet",
                                )),
                        ),
                    )
                    .child(self.panel("Pilot Entry", render_pilot_summary(packet))),
            )
            .child(self.render_error_strip())
            .child(
                div()
                    .h_flex()
                    .gap_2()
                    .child(
                        Button::new("command-refresh")
                            .label("Refresh Snapshot")
                            .primary()
                            .on_click(cx.listener(|this, _, _, cx| {
                                this.refresh(cx);
                            })),
                    )
                    .child(
                        Button::new("command-kill")
                            .label("Full Stop")
                            .danger()
                            .on_click(cx.listener(|this, _, _, cx| {
                                this.apply_kill_switch(cx);
                            })),
                    ),
            )
    }

    fn render_runs(&self) -> impl IntoElement {
        div()
            .v_flex()
            .gap_4()
            .child(self.section_title(
                "Runs",
                "Evidence-first inspection starts with stage, steering, Merkle, and terminal state.",
            ))
            .child(
                div()
                    .v_flex()
                    .gap_2()
                    .children(self.snapshot.runs.iter().map(render_run_row))
                    .child(empty_state(self.snapshot.runs.is_empty(), "No runs returned by /api/runs")),
            )
    }

    fn render_readiness(&self) -> AnyElement {
        match self.snapshot.readiness.as_ref() {
            Some(readiness) => div()
                .v_flex()
                .gap_4()
                .child(self.section_title(
                    "Readiness",
                    "Tiered profile checks separate required production gates from optional lanes.",
                ))
                .child(render_readiness_overview(readiness))
                .child(
                    div().grid().grid_cols(3).gap_3().children(
                        readiness
                            .integrations()
                            .into_iter()
                            .map(|(label, status)| render_integration_card(label, status)),
                    ),
                )
                .child(render_blockers(readiness))
                .into_any_element(),
            None => self
                .empty_panel(
                    "Readiness unavailable",
                    "/api/readiness did not return a snapshot",
                )
                .into_any_element(),
        }
    }

    fn render_simulator(&self) -> impl IntoElement {
        div()
            .v_flex()
            .gap_4()
            .child(self.section_title(
                "Policy Simulator",
                "Fixture and live-captured signals are replayed without mutation before authority expands.",
            ))
            .child(
                div()
                    .grid()
                    .grid_cols(2)
                    .gap_3()
                    .child(self.panel(
                        "Scenario Library",
                        div()
                            .v_flex()
                            .gap_2()
                            .children(self.snapshot.simulations.iter().map(render_simulation_row))
                            .child(empty_state(
                                self.snapshot.simulations.is_empty(),
                                "No simulator scenarios exposed",
                            )),
                    ))
                    .child(self.panel(
                        "Benchmark Evidence",
                        div()
                            .v_flex()
                            .gap_2()
                            .children(self.snapshot.benchmarks.iter().map(render_benchmark_row))
                            .child(empty_state(
                                self.snapshot.benchmarks.is_empty(),
                                "No benchmark records exposed",
                            )),
                    )),
            )
    }

    fn render_trust_ladder(&self) -> impl IntoElement {
        div()
            .v_flex()
            .gap_4()
            .child(self.section_title(
                "Trust Ladder",
                "Autonomy remains service and action-class specific, with visible promotion evidence.",
            ))
            .child(
                div()
                    .v_flex()
                    .gap_2()
                    .children(self.snapshot.trust_ladder.iter().map(render_trust_row))
                    .child(empty_state(
                        self.snapshot.trust_ladder.is_empty(),
                        "No trust ladder entries recorded",
                    )),
            )
    }

    fn render_connectors(&self) -> impl IntoElement {
        div()
            .v_flex()
            .gap_4()
            .child(self.section_title(
                "Component Integrations",
                "Connector maturity is explicit: mock, read-only, staging-ready, pilot-ready, or production-ready.",
            ))
            .child(
                div()
                    .grid()
                    .grid_cols(2)
                    .gap_3()
                    .child(self.panel(
                        "Certified Connectors",
                        self.snapshot
                            .readiness
                            .as_ref()
                            .map(render_connector_matrix)
                            .unwrap_or_else(|| self.muted_line("No readiness connector matrix").into_any_element()),
                    ))
                    .child(self.panel(
                        "Service Agents",
                        div()
                            .v_flex()
                            .gap_2()
                            .children(self.snapshot.service_agents.iter().map(render_service_agent_row))
                            .child(empty_state(
                                self.snapshot.service_agents.is_empty(),
                                "No service-agent records exposed",
                            )),
                    )),
            )
    }

    fn render_pilot_packet(&self) -> AnyElement {
        match self.snapshot.pilot_packet.as_ref() {
            Some(packet) => div()
                .v_flex()
                .gap_4()
                .child(self.section_title(
                    "Pilot Go/No-Go Packet",
                    "Production entry is generated from observed evidence, not assembled by hand.",
                ))
                .child(render_pilot_packet(packet))
                .into_any_element(),
            None => self
                .empty_panel(
                    "Pilot packet unavailable",
                    "/api/pilot/go-no-go did not return a packet",
                )
                .into_any_element(),
        }
    }

    fn render_kill_switch(&self, cx: &mut Context<Self>) -> impl IntoElement {
        let status = self.snapshot.kill_switch.as_ref();
        div()
            .v_flex()
            .gap_4()
            .child(self.section_title(
                "Kill Switch",
                "Operators can stop watchers, disable live execution, clear namespaces, and force approval gates.",
            ))
            .child(match status {
                Some(status) => render_kill_switch_status(status).into_any_element(),
                None => self
                    .empty_panel("Kill switch unavailable", "/api/kill-switch did not return state")
                    .into_any_element(),
            })
            .child(self.render_error_strip())
            .child(
                Button::new("apply-full-stop")
                    .label("Apply Full Stop")
                    .danger()
                    .on_click(cx.listener(|this, _, _, cx| {
                        this.apply_kill_switch(cx);
                    })),
            )
    }

    fn render_roadmap(&self) -> impl IntoElement {
        div()
            .v_flex()
            .gap_4()
            .child(self.section_title(
                "Roadmap Operating Model",
                "The desktop app is organized around the production gates instead of a cosmetic theme.",
            ))
            .child(
                div()
                    .grid()
                    .grid_cols(2)
                    .gap_3()
                    .child(self.roadmap_card(
                        "Phase 1: Local Production-Like E2E",
                        "Live Kubernetes run launch, evidence graph, policy simulator, failure library, invariant tests, and blocked actuator calls.",
                    ))
                    .child(self.roadmap_card(
                        "Phase 2: Private Staging",
                        "Identity, RBAC, readiness profiles, threat model, connector certification, trust ladder, and operator export review.",
                    ))
                    .child(self.roadmap_card(
                        "Phase 3: Production Pilot",
                        "SSO ingress, least-privilege production access, go/no-go packet, live action proof, drills, SLOs, and design-partner packet.",
                    ))
                    .child(self.roadmap_card(
                        "Phase 4: Production Expansion",
                        "Postgres default, concurrency validation, external adapters, formal release gates, DR drills, procurement package, and public proof.",
                    )),
            )
    }

    fn metric_chip(&self, label: &str, value: &str) -> impl IntoElement {
        div()
            .h_flex()
            .gap_1()
            .items_center()
            .px_2()
            .py_1()
            .rounded_md()
            .border_1()
            .border_color(rgb(BORDER))
            .bg(rgb(PANEL_BG))
            .child(div().text_color(rgb(MUTED)).child(label.to_string()))
            .child(
                div()
                    .font_weight(FontWeight::MEDIUM)
                    .child(value.to_string()),
            )
    }

    fn section_title(&self, title: &str, detail: &str) -> impl IntoElement {
        div()
            .v_flex()
            .gap_1()
            .child(
                div()
                    .text_size(px(20.0))
                    .font_weight(FontWeight::SEMIBOLD)
                    .child(title.to_string()),
            )
            .child(div().text_color(rgb(MUTED)).child(detail.to_string()))
    }

    fn status_card(&self, label: &str, value: &str, detail: String) -> impl IntoElement {
        div()
            .v_flex()
            .gap_2()
            .p_4()
            .rounded_md()
            .border_1()
            .border_color(rgb(tone_color(value)))
            .bg(rgb(PANEL_BG))
            .child(div().text_color(rgb(MUTED)).child(label.to_string()))
            .child(
                div()
                    .text_size(px(24.0))
                    .font_weight(FontWeight::SEMIBOLD)
                    .child(value.to_string()),
            )
            .child(div().text_color(rgb(SUBTLE)).child(detail))
    }

    fn panel(&self, title: &str, body: impl IntoElement) -> impl IntoElement {
        div()
            .v_flex()
            .gap_3()
            .p_4()
            .rounded_md()
            .border_1()
            .border_color(rgb(BORDER))
            .bg(rgb(PANEL_BG))
            .child(
                div()
                    .font_weight(FontWeight::SEMIBOLD)
                    .child(title.to_string()),
            )
            .child(body)
    }

    fn empty_panel(&self, title: &str, detail: &str) -> impl IntoElement {
        self.panel(title, self.muted_line(detail))
    }

    fn muted_line(&self, text: &str) -> impl IntoElement {
        div().text_color(rgb(MUTED)).child(text.to_string())
    }

    fn roadmap_card(&self, title: &str, detail: &str) -> impl IntoElement {
        self.panel(
            title,
            div().text_color(rgb(SUBTLE)).child(detail.to_string()),
        )
    }

    fn render_authority_band(&self) -> impl IntoElement {
        let kill_switch = self.snapshot.kill_switch.as_ref();
        let readiness = self.snapshot.readiness.as_ref();
        let live_execution = kill_switch
            .map(|status| {
                if status.live_execution_enabled {
                    "enabled"
                } else {
                    "disabled"
                }
            })
            .unwrap_or("unknown");
        let approval_gate = kill_switch
            .map(|status| {
                if status.force_approval_gate {
                    "forced"
                } else {
                    status.default_steering_mode.as_str()
                }
            })
            .unwrap_or("unknown");
        let blockers = readiness
            .map(|readiness| readiness.blockers.len().to_string())
            .unwrap_or_else(|| "unknown".to_string());

        div()
            .h_flex()
            .items_center()
            .justify_between()
            .gap_3()
            .p_3()
            .rounded_md()
            .border_1()
            .border_color(rgb(BORDER))
            .bg(rgb(PANEL_ALT))
            .child(
                div()
                    .v_flex()
                    .gap_1()
                    .child(
                        div()
                            .font_weight(FontWeight::SEMIBOLD)
                            .child("Authority Boundary"),
                    )
                    .child(
                        div()
                            .text_color(rgb(MUTED))
                            .child("Mutations stay behind identity, RBAC, policy, evaluation, and rollback gates."),
                    ),
            )
            .child(
                div()
                    .h_flex()
                    .gap_2()
                    .child(status_summary("Live", live_execution))
                    .child(status_summary("Approval", approval_gate))
                    .child(status_summary("Blockers", &blockers)),
            )
    }

    fn render_error_strip(&self) -> impl IntoElement {
        let mut errors = self.snapshot.errors.clone();
        if let Some(error) = &self.last_error {
            errors.push(error.clone());
        }

        div()
            .v_flex()
            .gap_2()
            .children(errors.iter().map(|error: &String| {
                div()
                    .p_3()
                    .rounded_md()
                    .border_1()
                    .border_color(rgb(DANGER))
                    .bg(rgb(0x281416))
                    .text_color(rgb(0xf0b7b7))
                    .child(error.to_string())
            }))
    }
}

impl Render for MeshConsole {
    fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        div()
            .v_flex()
            .size_full()
            .bg(rgb(APP_BG))
            .text_color(rgb(TEXT))
            .child(self.render_header(cx))
            .child(
                div()
                    .h_flex()
                    .flex_1()
                    .child(self.render_sidebar(cx))
                    .child(
                        div()
                            .flex_1()
                            .p_5()
                            .overflow_y_scrollbar()
                            .child(self.active_view(cx)),
                    ),
            )
    }
}

fn render_run_row(run: &RunSession) -> impl IntoElement {
    let title = if run.run_id.is_empty() {
        "unknown run".to_string()
    } else {
        run.run_id.clone()
    };
    let target = run
        .scenario_key
        .clone()
        .or_else(|| run.goal_id.clone())
        .unwrap_or_else(|| "manual or live signal".to_string());
    div()
        .h_flex()
        .justify_between()
        .items_center()
        .gap_3()
        .p_3()
        .rounded_md()
        .border_1()
        .border_color(rgb(BORDER_SUBTLE))
        .bg(rgb(ROW_BG))
        .child(
            div()
                .v_flex()
                .gap_1()
                .child(div().font_weight(FontWeight::MEDIUM).child(title))
                .child(div().text_color(rgb(MUTED)).child(target)),
        )
        .child(
            div()
                .v_flex()
                .items_end()
                .gap_1()
                .child(status_pill(&run.status))
                .child(
                    div()
                        .text_color(rgb(MUTED))
                        .child(format!("{} events", run.latest_event_sequence)),
                ),
        )
}

fn render_readiness_overview(readiness: &IntegrationReadiness) -> impl IntoElement {
    div()
        .grid()
        .grid_cols(4)
        .gap_3()
        .child(summary_tile("Profile", &readiness.profile))
        .child(summary_tile("Status", &readiness.status))
        .child(summary_tile(
            "Required",
            &readiness.required_checks.len().to_string(),
        ))
        .child(summary_tile(
            "Blockers",
            &readiness.blockers.len().to_string(),
        ))
}

fn render_integration_card(label: &str, status: &IntegrationStatus) -> impl IntoElement {
    let detail = if status.detail.is_empty() {
        "No detail provided".to_string()
    } else {
        status.detail.clone()
    };

    div()
        .v_flex()
        .gap_2()
        .p_4()
        .rounded_md()
        .border_1()
        .border_color(rgb(if status.ready { GOOD } else { DANGER }))
        .bg(rgb(PANEL_BG))
        .child(
            div()
                .h_flex()
                .justify_between()
                .items_center()
                .child(
                    div()
                        .font_weight(FontWeight::SEMIBOLD)
                        .child(label.to_string()),
                )
                .child(status_pill(if status.ready { "ready" } else { "blocked" })),
        )
        .child(
            div()
                .text_color(rgb(SUBTLE))
                .child(format!("{} / {}", status.certification, status.posture)),
        )
        .child(div().text_color(rgb(MUTED)).child(detail))
}

fn render_blockers(readiness: &IntegrationReadiness) -> impl IntoElement {
    div()
        .v_flex()
        .gap_2()
        .child(
            div()
                .font_weight(FontWeight::SEMIBOLD)
                .child("Readiness Blockers"),
        )
        .children(readiness.blockers.iter().map(|blocker| {
            div()
                .p_3()
                .rounded_md()
                .border_1()
                .border_color(rgb(DANGER))
                .bg(rgb(0x281416))
                .text_color(rgb(0xf0b7b7))
                .child(blocker.to_string())
        }))
        .child(empty_state(
            readiness.blockers.is_empty(),
            "No blockers reported for the active readiness profile",
        ))
}

fn render_simulation_row(row: &SimulationScenario) -> impl IntoElement {
    div()
        .v_flex()
        .gap_1()
        .p_3()
        .rounded_md()
        .border_1()
        .border_color(rgb(BORDER_SUBTLE))
        .bg(rgb(ROW_BG))
        .child(
            div()
                .font_weight(FontWeight::MEDIUM)
                .child(row.title.clone()),
        )
        .child(
            div()
                .text_color(rgb(MUTED))
                .child(format!("{} / {}", row.scenario_id, row.fault_type)),
        )
        .child(div().text_color(rgb(SUBTLE)).child(row.tags.join(", ")))
}

fn render_benchmark_row(row: &BenchmarkRecord) -> impl IntoElement {
    div()
        .h_flex()
        .justify_between()
        .items_center()
        .gap_3()
        .p_3()
        .rounded_md()
        .border_1()
        .border_color(rgb(BORDER_SUBTLE))
        .bg(rgb(ROW_BG))
        .child(
            div()
                .v_flex()
                .gap_1()
                .child(
                    div()
                        .font_weight(FontWeight::MEDIUM)
                        .child(row.benchmark_id.clone()),
                )
                .child(
                    div()
                        .text_color(rgb(MUTED))
                        .child(format!("{} / {}", row.scenario_id, row.run_id)),
                ),
        )
        .child(status_pill(if row.passed { "passed" } else { "failed" }))
}

fn render_trust_row(row: &TrustLadderEntry) -> impl IntoElement {
    div()
        .grid()
        .grid_cols(4)
        .gap_3()
        .p_3()
        .rounded_md()
        .border_1()
        .border_color(rgb(BORDER_SUBTLE))
        .bg(rgb(ROW_BG))
        .child(
            div()
                .font_weight(FontWeight::MEDIUM)
                .child(row.service.clone()),
        )
        .child(
            div()
                .text_color(rgb(SUBTLE))
                .child(row.action_class.clone()),
        )
        .child(status_pill(&row.level))
        .child(div().text_color(rgb(MUTED)).child(format!(
            "{}/{} successful, {:.1}% success",
            row.successful_runs,
            row.total_runs,
            row.success_rate * 100.0
        )))
}

fn render_connector_matrix(readiness: &IntegrationReadiness) -> AnyElement {
    div()
        .v_flex()
        .gap_2()
        .children(
            readiness
                .connector_certification
                .iter()
                .map(|(name, value)| {
                    div()
                        .h_flex()
                        .justify_between()
                        .gap_3()
                        .p_3()
                        .rounded_md()
                        .border_1()
                        .border_color(rgb(BORDER_SUBTLE))
                        .bg(rgb(ROW_BG))
                        .child(div().font_weight(FontWeight::MEDIUM).child(name.clone()))
                        .child(status_pill(&short_value(value)))
                }),
        )
        .child(empty_state(
            readiness.connector_certification.is_empty(),
            "No connector certification matrix returned",
        ))
        .into_any_element()
}

fn render_service_agent_row(row: &ServiceAgentRecord) -> impl IntoElement {
    div()
        .v_flex()
        .gap_1()
        .p_3()
        .rounded_md()
        .border_1()
        .border_color(rgb(BORDER_SUBTLE))
        .bg(rgb(ROW_BG))
        .child(
            div()
                .font_weight(FontWeight::MEDIUM)
                .child(row.service.clone()),
        )
        .child(
            div()
                .text_color(rgb(MUTED))
                .child(format!("lanes: {}", row.preferred_lanes.join(", "))),
        )
        .child(
            div()
                .text_color(rgb(SUBTLE))
                .child(format!("{} scoped resource groups", row.scope.len())),
        )
}

fn render_pilot_summary(packet: Option<&PilotGoNoGoPacket>) -> AnyElement {
    match packet {
        Some(packet) => div()
            .v_flex()
            .gap_2()
            .child(status_pill(&packet.status))
            .child(
                div()
                    .text_color(rgb(SUBTLE))
                    .child(format!("{} observed runs", packet.observed.run_count)),
            )
            .child(div().text_color(rgb(MUTED)).child(format!(
                "{} missing evidence items",
                packet.missing_evidence.len()
            )))
            .into_any_element(),
        None => div()
            .text_color(rgb(MUTED))
            .child("No pilot packet generated")
            .into_any_element(),
    }
}

fn render_pilot_packet(packet: &PilotGoNoGoPacket) -> impl IntoElement {
    div()
        .grid()
        .grid_cols(2)
        .gap_3()
        .child(
            div()
                .v_flex()
                .gap_3()
                .p_4()
                .rounded_md()
                .border_1()
                .border_color(rgb(BORDER))
                .bg(rgb(PANEL_BG))
                .child(summary_tile("Packet", &packet.packet_version))
                .child(summary_tile("Status", &packet.status))
                .child(summary_tile("Generated", &packet.generated_at))
                .child(summary_tile(
                    "Observed Runs",
                    &packet.observed.run_count.to_string(),
                )),
        )
        .child(
            div()
                .v_flex()
                .gap_2()
                .p_4()
                .rounded_md()
                .border_1()
                .border_color(rgb(BORDER))
                .bg(rgb(PANEL_BG))
                .child(
                    div()
                        .font_weight(FontWeight::SEMIBOLD)
                        .child("Evidence Checks"),
                )
                .children(packet.checks.iter().map(|(check, passed)| {
                    div()
                        .h_flex()
                        .justify_between()
                        .child(check.clone())
                        .child(status_pill(if *passed { "passed" } else { "missing" }))
                }))
                .child(empty_state(
                    packet.missing_evidence.is_empty(),
                    "No missing evidence in the generated packet",
                )),
        )
}

fn render_kill_switch_status(status: &KillSwitchStatus) -> impl IntoElement {
    let running = status
        .watchers
        .watchers
        .iter()
        .filter(|watcher| watcher.running)
        .count();

    div()
        .grid()
        .grid_cols(2)
        .gap_3()
        .child(summary_tile(
            "Live Execution",
            if status.live_execution_enabled {
                "enabled"
            } else {
                "disabled"
            },
        ))
        .child(summary_tile(
            "Approval Gate",
            if status.force_approval_gate {
                "forced"
            } else {
                "configured"
            },
        ))
        .child(summary_tile("Running Watchers", &running.to_string()))
        .child(summary_tile(
            "Allowed Namespaces",
            &status.allowed_namespaces.len().to_string(),
        ))
}

fn summary_tile(label: &str, value: &str) -> impl IntoElement {
    div()
        .v_flex()
        .gap_1()
        .p_3()
        .rounded_md()
        .border_1()
        .border_color(rgb(BORDER_SUBTLE))
        .bg(rgb(ROW_BG))
        .child(div().text_color(rgb(MUTED)).child(label.to_string()))
        .child(
            div()
                .font_weight(FontWeight::SEMIBOLD)
                .child(value.to_string()),
        )
}

fn status_summary(label: &str, value: &str) -> impl IntoElement {
    div()
        .v_flex()
        .gap_1()
        .px_3()
        .py_2()
        .rounded_md()
        .border_1()
        .border_color(rgb(tone_color(value)))
        .bg(rgb(ROW_BG))
        .child(div().text_color(rgb(MUTED)).child(label.to_string()))
        .child(
            div()
                .font_weight(FontWeight::SEMIBOLD)
                .child(value.to_string()),
        )
}

fn status_pill(value: &str) -> impl IntoElement {
    div()
        .px_2()
        .py_1()
        .rounded_md()
        .bg(rgb(tone_color(value)))
        .text_color(rgb(0xfffbf2))
        .child(value.to_string())
}

fn tone_color(value: &str) -> u32 {
    match value {
        "ready" | "ok" | "go" | "passed" | "completed" | "running" => GOOD,
        "enabled" => WARN,
        "blocked" | "failed" | "missing" | "disabled" | "offline" => DANGER,
        "approval_gate" | "draft" | "review" | "forced" | "configured" => WARN,
        "unknown" => INFO,
        _ => BORDER,
    }
}

fn empty_state(show: bool, text: &str) -> AnyElement {
    if show {
        div()
            .p_3()
            .rounded_md()
            .border_1()
            .border_color(rgb(BORDER_SUBTLE))
            .bg(rgb(ROW_BG))
            .text_color(rgb(MUTED))
            .child(text.to_string())
            .into_any_element()
    } else {
        div().into_any_element()
    }
}

fn format_health_detail(health: &HealthSnapshot) -> String {
    format!(
        "{} / {} / {}",
        empty_fallback(&health.environment, "env"),
        empty_fallback(&health.version, "version"),
        empty_fallback(&health.commit, "commit")
    )
}

fn empty_fallback(value: &str, fallback: &str) -> String {
    if value.is_empty() {
        fallback.to_string()
    } else {
        value.to_string()
    }
}

fn short_value(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        Value::Bool(flag) => flag.to_string(),
        Value::Object(map) => map
            .get("certification")
            .or_else(|| map.get("status"))
            .or_else(|| map.get("posture"))
            .map(short_value)
            .unwrap_or_else(|| "configured".to_string()),
        Value::Null => "unknown".to_string(),
        other => other.to_string(),
    }
}

fn main() {
    gpui_platform::application()
        .with_assets(gpui_component_assets::Assets)
        .run(move |cx| {
            gpui_component::init(cx);

            cx.spawn(async move |cx| {
                cx.open_window(WindowOptions::default(), |window, cx| {
                    let view = cx.new(MeshConsole::new);
                    cx.new(|cx| Root::new(view, window, cx))
                })
                .expect("failed to open Mesh GPUI console");
            })
            .detach();
        });
}
