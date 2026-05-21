from __future__ import annotations

import json
from typing import Any


def operator_product_schema() -> dict[str, Any]:
    string_map = {"type": "object", "additionalProperties": {"type": "string"}}
    team_profile = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "name", "display_name", "slug", "role", "roles", "members"],
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "display_name": {"type": "string"},
            "slug": {"type": "string"},
            "role": {"type": "string"},
            "roles": {"type": "array", "items": {"type": "string"}},
            "members": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["email", "role", "status"],
                    "properties": {
                        "email": {"type": "string"},
                        "role": {"type": "string"},
                        "status": {"type": "string"},
                    },
                },
            },
        },
    }
    session_payload = {
        "type": "object",
        "additionalProperties": False,
        "required": ["user", "teams", "active_team", "settings"],
        "properties": {
            "user": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "email", "display_name"],
                "properties": {
                    "id": {"type": "string"},
                    "email": {"type": "string"},
                    "display_name": {"type": "string"},
                },
            },
            "teams": {"type": "array", "items": team_profile},
            "active_team": {"type": ["object", "null"], **{k: v for k, v in team_profile.items() if k != "type"}},
            "settings": string_map,
        },
    }
    settings_schema = {
        "type": "object",
        "additionalProperties": {
            "type": "object",
            "additionalProperties": False,
            "required": ["values", "default", "description"],
            "properties": {
                "values": {"type": "array", "items": {"type": "string"}},
                "default": {"type": "string"},
                "description": {"type": "string"},
            },
        },
    }
    operator_preferences = {
        "type": "object",
        "additionalProperties": {
            "anyOf": [
                {"type": "string"},
                {"type": "boolean"},
                {"type": "array", "items": {"type": "string"}},
            ]
        },
    }
    operator_preferences_schema = {
        "type": "object",
        "additionalProperties": {
            "type": "object",
            "additionalProperties": True,
            "required": ["kind", "default", "description"],
            "properties": {
                "kind": {"enum": ["enum", "multi", "boolean", "string"]},
                "values": {"type": "array", "items": {"type": "string"}},
                "default": {
                    "anyOf": [
                        {"type": "string"},
                        {"type": "boolean"},
                        {"type": "array", "items": {"type": "string"}},
                    ]
                },
                "description": {"type": "string"},
            },
        },
    }
    operator_preferences_state = {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "state_slice", "scope", "operator_preferences", "operator_preferences_schema"],
        "properties": {
            "schema_version": {"type": "string"},
            "state_slice": {"type": "string"},
            "scope": {"type": "string"},
            "operator_preferences": operator_preferences,
            "operator_preferences_schema": operator_preferences_schema,
        },
    }
    agent_flow_agent = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "name", "source"],
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "source": {"type": "string"},
            "authority": {"type": "string"},
        },
    }
    agent_flow_lifecycle_subtask = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "title", "description", "status", "priority"],
        "properties": {
            "id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string"},
            "priority": {"type": "string"},
            "tools": {"type": "array", "items": {"type": "string"}},
        },
    }
    agent_flow_lifecycle_task = {
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "title", "description", "status", "priority", "level", "dependencies", "subtasks"],
        "properties": {
            "id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string"},
            "priority": {"type": "string"},
            "level": {"type": "integer"},
            "dependencies": {"type": "array", "items": {"type": "string"}},
            "subtasks": {"type": "array", "items": agent_flow_lifecycle_subtask},
        },
    }
    agent_flow_mutation_preview = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "state_slice",
            "preview_id",
            "status",
            "proposed_resource",
            "action",
            "target",
            "endpoint",
            "would_touch_state_slice",
            "confirmation_required",
            "side_effects_executed",
            "issued_scope",
            "issued_operator_id",
            "issued_at",
            "proof",
        ],
        "properties": {
            "schema_version": {"type": "string"},
            "state_slice": {"type": "string"},
            "preview_id": {"type": "string"},
            "status": {"type": "string"},
            "proposed_resource": {"type": "string"},
            "action": {"type": "string"},
            "target": {"type": "object", "additionalProperties": True},
            "endpoint": {"type": "string"},
            "would_touch_state_slice": {"type": "string"},
            "confirmation_required": {"type": "boolean"},
            "side_effects_executed": {"type": "boolean"},
            "issued_scope": {"type": "string"},
            "issued_operator_id": {"type": "string"},
            "issued_at": {"type": "string"},
            "proof": {
                "type": "object",
                "additionalProperties": False,
                "required": ["algorithm", "bound_state_slice", "signature"],
                "properties": {
                    "algorithm": {"type": "string"},
                    "bound_state_slice": {"type": "string"},
                    "signature": {"type": "string"},
                },
            },
        },
    }
    agent_flow_dashboard = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "state_slice",
            "status",
            "agent",
            "source",
            "chat_endpoint",
            "livekit_endpoint",
            "confirmation_endpoint",
            "livekit_configured",
            "authority",
        ],
        "properties": {
            "schema_version": {"type": "string"},
            "state_slice": {"type": "string"},
            "status": {"type": "string"},
            "agent": {"type": "string"},
            "source": {"type": "string"},
            "chat_endpoint": {"type": "string"},
            "livekit_endpoint": {"type": "string"},
            "confirmation_endpoint": {"type": "string"},
            "livekit_configured": {"type": "boolean"},
            "authority": {"type": "string"},
        },
    }
    agent_flow_chat_response = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "state_slice",
            "agent",
            "answer",
            "state_slices",
            "evidence",
            "lifecycle",
            "mutation_preview",
            "authority_boundary",
            "created_at",
        ],
        "properties": {
            "schema_version": {"type": "string"},
            "state_slice": {"type": "string"},
            "agent": agent_flow_agent,
            "answer": {"type": "string"},
            "state_slices": {"type": "array", "items": {"type": "string"}},
            "evidence": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "kind", "state_slice", "summary"],
                    "properties": {
                        "id": {"type": "string"},
                        "kind": {"type": "string"},
                        "state_slice": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                },
            },
            "lifecycle": {
                "type": "object",
                "additionalProperties": False,
                "required": ["state_slice", "tasks"],
                "properties": {
                    "state_slice": {"type": "string"},
                    "tasks": {"type": "array", "items": agent_flow_lifecycle_task},
                },
            },
            "mutation_preview": agent_flow_mutation_preview,
            "authority_boundary": {"type": "string"},
            "created_at": {"type": "string"},
        },
    }
    agent_flow_livekit_session = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "state_slice",
            "agent",
            "status",
            "livekit_url",
            "room",
            "participant_identity",
            "token",
            "token_expires_at",
            "required_env",
            "side_effects_executed",
        ],
        "properties": {
            "schema_version": {"type": "string"},
            "state_slice": {"type": "string"},
            "agent": agent_flow_agent,
            "status": {"type": "string"},
            "livekit_url": {"type": "string"},
            "room": {"type": "string"},
            "participant_identity": {"type": "string"},
            "token": {"type": "string"},
            "token_expires_at": {"type": ["string", "null"]},
            "required_env": {"type": "array", "items": {"type": "string"}},
            "side_effects_executed": {"type": "boolean"},
        },
    }
    agent_flow_confirmation = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "state_slice",
            "preview_id",
            "status",
            "confirmed_by",
            "reason",
            "proposed_resource",
            "would_touch_state_slice",
            "routed_to",
            "side_effects_executed",
            "next_step",
            "created_at",
        ],
        "properties": {
            "schema_version": {"type": "string"},
            "state_slice": {"type": "string"},
            "preview_id": {"type": "string"},
            "status": {"type": "string"},
            "confirmed_by": {"type": "string"},
            "reason": {"type": "string"},
            "proposed_resource": {"type": "string"},
            "would_touch_state_slice": {"type": "string"},
            "routed_to": {"type": "string"},
            "side_effects_executed": {"type": "boolean"},
            "next_step": {"type": "string"},
            "created_at": {"type": "string"},
        },
    }
    dashboard_mesh = {
        "type": "object",
        "required": [
            "health",
            "read_model",
            "agent_flow",
            "readiness",
            "connectors",
            "approvals",
            "kill_switch",
            "pilot_go_no_go",
            "praxis",
            "trust_ladder",
            "watchers",
            "graph",
            "runs",
            "memory",
        ],
        "properties": {
            "health": {"type": "object"},
            "read_model": {
                "type": "object",
                "required": ["source", "authority", "degraded_reason"],
                "properties": {
                    "source": {"type": "string"},
                    "authority": {"type": "string"},
                    "degraded_reason": {"type": "string"},
                },
            },
            "readiness": {"type": "object"},
            "agent_flow": agent_flow_dashboard,
            "connectors": {"type": "object"},
            "approvals": {"type": "object"},
            "kill_switch": {"type": "object"},
            "pilot_go_no_go": {"type": "object"},
            "praxis": {"type": "object"},
            "trust_ladder": {
                "type": "object",
                "required": ["entries"],
                "properties": {"entries": {"type": "array"}},
            },
            "watchers": {"type": "object"},
            "graph": {"type": "object"},
            "runs": {
                "type": "object",
                "required": ["runs"],
                "properties": {"runs": {"type": "array"}},
            },
            "memory": {
                "type": "object",
                "required": ["active", "graph"],
                "properties": {
                    "active": {"type": "object"},
                    "graph": {"type": "object"},
                },
            },
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "operator-product.schema.json",
        "title": "Mesh operator product contracts",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "auth_config": {
                "type": "object",
                "additionalProperties": False,
                "required": ["auth_mode", "signup_enabled", "password_auth_enabled", "captcha", "oauth", "invite"],
                "properties": {
                    "auth_mode": {"type": "string"},
                    "signup_enabled": {"type": "boolean"},
                    "password_auth_enabled": {"type": "boolean"},
                    "captcha": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["provider", "site_key", "configured", "dev_bypass_enabled"],
                        "properties": {
                            "provider": {"enum": ["disabled", "hcaptcha", "recaptcha", "turnstile"]},
                            "site_key": {"type": "string"},
                            "configured": {"type": "boolean"},
                            "dev_bypass_enabled": {"type": "boolean"},
                        },
                    },
                    "oauth": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["google", "github"],
                        "properties": {
                            "google": {"type": "object", "additionalProperties": False, "required": ["configured"], "properties": {"configured": {"type": "boolean"}}},
                            "github": {"type": "object", "additionalProperties": False, "required": ["configured"], "properties": {"configured": {"type": "boolean"}}},
                        },
                    },
                    "invite": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["required", "configured", "allowlist_enabled"],
                        "properties": {
                            "required": {"type": "boolean"},
                            "configured": {"type": "boolean"},
                            "allowlist_enabled": {"type": "boolean"},
                        },
                    },
                },
            },
            "session_payload": session_payload,
            "dashboard_payload": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "scope",
                    "session",
                    "settings",
                    "settings_schema",
                    "operator_preferences",
                    "operator_preferences_schema",
                    "operator_preferences_state",
                    "mesh",
                    "authority_boundary",
                ],
                "properties": {
                    "scope": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["kind", "team"],
                        "properties": {
                            "kind": {"enum": ["solo", "team"]},
                            "team": {"type": ["object", "null"], **{k: v for k, v in team_profile.items() if k != "type"}},
                        },
                    },
                    "session": session_payload,
                    "settings": string_map,
                    "settings_schema": settings_schema,
                    "operator_preferences": operator_preferences,
                    "operator_preferences_schema": operator_preferences_schema,
                    "operator_preferences_state": operator_preferences_state,
                    "mesh": dashboard_mesh,
                    "authority_boundary": {"type": "string"},
                },
            },
            "agent_flow_chat_response": agent_flow_chat_response,
            "agent_flow_livekit_session_response": agent_flow_livekit_session,
            "agent_flow_confirmation_response": agent_flow_confirmation,
            "settings_update_response": {
                "type": "object",
                "additionalProperties": False,
                "required": ["settings", "settings_schema", "audit"],
                "properties": {
                    "settings": string_map,
                    "settings_schema": settings_schema,
                    "audit": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["recorded", "state_slice", "scope", "fields"],
                        "properties": {
                            "recorded": {"type": "boolean"},
                            "state_slice": {"type": "string"},
                            "scope": {"type": "string"},
                            "fields": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
            "operator_preferences_update_response": {
                "type": "object",
                "additionalProperties": False,
                "required": ["state_slice", "operator_preferences", "operator_preferences_schema", "audit"],
                "properties": {
                    "state_slice": {"type": "string"},
                    "operator_preferences": operator_preferences,
                    "operator_preferences_schema": operator_preferences_schema,
                    "audit": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["recorded", "state_slice", "scope", "fields"],
                        "properties": {
                            "recorded": {"type": "boolean"},
                            "state_slice": {"type": "string"},
                            "scope": {"type": "string"},
                            "fields": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
            "logout_response": {
                "type": "object",
                "additionalProperties": False,
                "required": ["status"],
                "properties": {"status": {"type": "string"}},
            },
        },
    }


def render_typescript_types() -> str:
    return """/* eslint-disable */
// Generated by scripts/generate_operator_product_contracts.py. Do not edit manually.

export type CaptchaProvider = "disabled" | "hcaptcha" | "recaptcha" | "turnstile";

export interface AuthConfig {
  auth_mode: string;
  signup_enabled: boolean;
  password_auth_enabled: boolean;
  captcha: {
    provider: CaptchaProvider;
    site_key: string;
    configured: boolean;
    dev_bypass_enabled: boolean;
  };
  oauth: {
    google: { configured: boolean };
    github: { configured: boolean };
  };
  invite: {
    required: boolean;
    configured: boolean;
    allowlist_enabled: boolean;
  };
}

export interface UserProfile {
  id: string;
  email: string;
  display_name: string;
}

export interface TeamProfile {
  id: string;
  name: string;
  display_name: string;
  slug: string;
  role: string;
  roles: string[];
  members: { email: string; role: string; status: string }[];
}

export interface SessionPayload {
  user: UserProfile;
  teams: TeamProfile[];
  active_team: TeamProfile | null;
  settings: Record<string, string>;
}

export interface AgentFlowLifecycleTask {
  id: string;
  title: string;
  description: string;
  status: "completed" | "in-progress" | "pending" | "need-help" | "failed";
  priority: "high" | "medium" | "low";
  level: number;
  dependencies: string[];
  subtasks: Array<{
    id: string;
    title: string;
    description: string;
    status: "completed" | "in-progress" | "pending" | "need-help" | "failed";
    priority: "high" | "medium" | "low";
    tools?: string[];
  }>;
}

export interface AgentFlowMutationPreview {
  schema_version: string;
  state_slice: string;
  preview_id: string;
  status: string;
  proposed_resource: string;
  action: string;
  target: Record<string, any>;
  endpoint: string;
  would_touch_state_slice: string;
  confirmation_required: boolean;
  side_effects_executed: boolean;
  issued_scope: string;
  issued_operator_id: string;
  issued_at: string;
  proof: {
    algorithm: string;
    bound_state_slice: string;
    signature: string;
  };
}

export interface AgentFlowChatResponse {
  schema_version: string;
  state_slice: string;
  agent: { id: string; name: string; source: string; authority?: string };
  answer: string;
  state_slices: string[];
  evidence: Array<{ id: string; kind: string; state_slice: string; summary: string }>;
  lifecycle: { state_slice: string; tasks: AgentFlowLifecycleTask[] };
  mutation_preview: AgentFlowMutationPreview;
  authority_boundary: string;
  created_at: string;
}

export interface AgentFlowLiveKitSessionResponse {
  schema_version: string;
  state_slice: string;
  agent: { id: string; name: string; source: string; authority?: string };
  status: string;
  livekit_url: string;
  room: string;
  participant_identity: string;
  token: string;
  token_expires_at: string | null;
  required_env: string[];
  side_effects_executed: boolean;
}

export interface AgentFlowConfirmationResponse {
  schema_version: string;
  state_slice: string;
  preview_id: string;
  status: string;
  confirmed_by: string;
  reason: string;
  proposed_resource: string;
  would_touch_state_slice: string;
  routed_to: string;
  side_effects_executed: boolean;
  next_step: string;
  created_at: string;
}

export interface AgentFlowDashboard {
  schema_version: string;
  state_slice: string;
  status: string;
  agent: string;
  source: string;
  chat_endpoint: string;
  livekit_endpoint: string;
  confirmation_endpoint: string;
  livekit_configured: boolean;
  authority: string;
}

export interface DashboardMesh {
  agent_flow: AgentFlowDashboard;
  [key: string]: any;
}

export interface DashboardPayload {
  scope: { kind: "solo" | "team"; team: TeamProfile | null };
  session: SessionPayload;
  settings: Record<string, string>;
  settings_schema: Record<string, { values: string[]; default: string; description: string }>;
  operator_preferences: Record<string, string | boolean | string[]>;
  operator_preferences_schema: Record<string, { kind: "enum" | "multi" | "boolean" | "string"; values?: string[]; default: string | boolean | string[]; description: string }>;
  operator_preferences_state: {
    schema_version: string;
    state_slice: string;
    scope: string;
    operator_preferences: Record<string, string | boolean | string[]>;
    operator_preferences_schema: Record<string, { kind: "enum" | "multi" | "boolean" | "string"; values?: string[]; default: string | boolean | string[]; description: string }>;
  };
  mesh: DashboardMesh;
  authority_boundary: string;
}

export interface SettingsUpdateResponse {
  settings: Record<string, string>;
  settings_schema: Record<string, { values: string[]; default: string; description: string }>;
  audit: {
    recorded: boolean;
    state_slice: string;
    scope: string;
    fields: string[];
  };
}

export interface OperatorPreferencesUpdateResponse {
  state_slice: string;
  operator_preferences: Record<string, string | boolean | string[]>;
  operator_preferences_schema: Record<string, { kind: "enum" | "multi" | "boolean" | "string"; values?: string[]; default: string | boolean | string[]; description: string }>;
  audit: {
    recorded: boolean;
    state_slice: string;
    scope: string;
    fields: string[];
  };
}

export interface LogoutResponse {
  status: string;
}
"""


def render_schema_text() -> str:
    return json.dumps(operator_product_schema(), indent=2, sort_keys=True) + "\n"
