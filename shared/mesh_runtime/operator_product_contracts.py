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
    dashboard_mesh = {
        "type": "object",
        "required": [
            "health",
            "read_model",
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
                "required": ["scope", "session", "settings", "settings_schema", "mesh", "authority_boundary"],
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
                    "mesh": dashboard_mesh,
                    "authority_boundary": {"type": "string"},
                },
            },
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

export interface DashboardPayload {
  scope: { kind: "solo" | "team"; team: TeamProfile | null };
  session: SessionPayload;
  settings: Record<string, string>;
  settings_schema: Record<string, { values: string[]; default: string; description: string }>;
  mesh: Record<string, any>;
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

export interface LogoutResponse {
  status: string;
}
"""


def render_schema_text() -> str:
    return json.dumps(operator_product_schema(), indent=2, sort_keys=True) + "\n"
