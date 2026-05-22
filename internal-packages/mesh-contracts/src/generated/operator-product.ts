/* eslint-disable */
// Generated from Mesh JSON Schemas. Do not edit by hand.
// Source of truth: shared/mesh_runtime/schemas/.

export interface MeshOperatorProductContracts {
  agent_flow_chat_response?: {
    agent: {
      authority?: string;
      id: string;
      name: string;
      source: string;
    };
    answer: string;
    authority_boundary: string;
    created_at: string;
    evidence: {
      id: string;
      kind: string;
      state_slice: string;
      summary: string;
    }[];
    lifecycle: {
      state_slice: string;
      tasks: {
        dependencies: string[];
        description: string;
        id: string;
        level: number;
        priority: string;
        status: string;
        subtasks: {
          description: string;
          id: string;
          priority: string;
          status: string;
          title: string;
          tools?: string[];
        }[];
        title: string;
      }[];
    };
    mutation_preview: {
      action: string;
      confirmation_required: boolean;
      endpoint: string;
      issued_at: string;
      issued_operator_id: string;
      issued_scope: string;
      preview_id: string;
      proof: {
        algorithm: string;
        bound_state_slice: string;
        signature: string;
      };
      proposed_resource: string;
      schema_version: string;
      side_effects_executed: boolean;
      state_slice: string;
      status: string;
      target: {
        [k: string]: any;
      };
      would_touch_state_slice: string;
    };
    schema_version: string;
    state_slice: string;
    state_slices: string[];
  };
  agent_flow_confirmation_response?: {
    confirmed_by: string;
    created_at: string;
    next_step: string;
    preview_id: string;
    proposed_resource: string;
    reason: string;
    routed_to: string;
    schema_version: string;
    side_effects_executed: boolean;
    state_slice: string;
    status: string;
    would_touch_state_slice: string;
  };
  agent_flow_livekit_session_response?: {
    agent: {
      authority?: string;
      id: string;
      name: string;
      source: string;
    };
    livekit_url: string;
    participant_identity: string;
    required_env: string[];
    room: string;
    schema_version: string;
    side_effects_executed: boolean;
    state_slice: string;
    status: string;
    token: string;
    token_expires_at: string | null;
  };
  auth_config?: {
    auth_mode: string;
    captcha: {
      configured: boolean;
      dev_bypass_enabled: boolean;
      provider: "disabled" | "hcaptcha" | "recaptcha" | "turnstile";
      site_key: string;
    };
    invite: {
      allowlist_enabled: boolean;
      configured: boolean;
      required: boolean;
    };
    oauth: {
      github: {
        configured: boolean;
      };
      google: {
        configured: boolean;
      };
    };
    password_auth_enabled: boolean;
    signup_enabled: boolean;
  };
  dashboard_payload?: {
    authority_boundary: string;
    mesh: {
      agent_flow: {
        agent: string;
        authority: string;
        chat_endpoint: string;
        confirmation_endpoint: string;
        livekit_configured: boolean;
        livekit_endpoint: string;
        schema_version: string;
        source: string;
        state_slice: string;
        status: string;
      };
      approvals: {
        [k: string]: any;
      };
      connectors: {
        [k: string]: any;
      };
      graph: {
        [k: string]: any;
      };
      health: {
        [k: string]: any;
      };
      kill_switch: {
        [k: string]: any;
      };
      memory: {
        active: {
          [k: string]: any;
        };
        graph: {
          [k: string]: any;
        };
        [k: string]: any;
      };
      pilot_go_no_go: {
        [k: string]: any;
      };
      praxis: {
        [k: string]: any;
      };
      read_model: {
        authority: string;
        degraded_reason: string;
        source: string;
        [k: string]: any;
      };
      readiness: {
        [k: string]: any;
      };
      runs: {
        runs: any[];
        [k: string]: any;
      };
      trust_ladder: {
        entries: any[];
        [k: string]: any;
      };
      watchers: {
        [k: string]: any;
      };
      [k: string]: any;
    };
    operator_preferences: {
      [k: string]: string | boolean | string[];
    };
    operator_preferences_schema: {
      [k: string]: {
        default: string | boolean | string[];
        description: string;
        kind: "enum" | "multi" | "boolean" | "string";
        values?: string[];
        [k: string]: any;
      };
    };
    operator_preferences_state: {
      operator_preferences: {
        [k: string]: string | boolean | string[];
      };
      operator_preferences_schema: {
        [k: string]: {
          default: string | boolean | string[];
          description: string;
          kind: "enum" | "multi" | "boolean" | "string";
          values?: string[];
          [k: string]: any;
        };
      };
      schema_version: string;
      scope: string;
      state_slice: string;
    };
    scope: {
      kind: "solo" | "team";
      team: {
        display_name: string;
        id: string;
        members: {
          email: string;
          role: string;
          status: string;
        }[];
        name: string;
        role: string;
        roles: string[];
        slug: string;
      } | null;
    };
    session: {
      active_team: {
        display_name: string;
        id: string;
        members: {
          email: string;
          role: string;
          status: string;
        }[];
        name: string;
        role: string;
        roles: string[];
        slug: string;
      } | null;
      settings: {
        [k: string]: string;
      };
      teams: {
        display_name: string;
        id: string;
        members: {
          email: string;
          role: string;
          status: string;
        }[];
        name: string;
        role: string;
        roles: string[];
        slug: string;
      }[];
      user: {
        display_name: string;
        email: string;
        id: string;
      };
    };
    settings: {
      [k: string]: string;
    };
    settings_schema: {
      [k: string]: {
        default: string;
        description: string;
        values: string[];
      };
    };
  };
  logout_response?: {
    status: string;
  };
  operator_preferences_update_response?: {
    audit: {
      fields: string[];
      recorded: boolean;
      scope: string;
      state_slice: string;
    };
    operator_preferences: {
      [k: string]: string | boolean | string[];
    };
    operator_preferences_schema: {
      [k: string]: {
        default: string | boolean | string[];
        description: string;
        kind: "enum" | "multi" | "boolean" | "string";
        values?: string[];
        [k: string]: any;
      };
    };
    state_slice: string;
  };
  session_payload?: {
    active_team: {
      display_name: string;
      id: string;
      members: {
        email: string;
        role: string;
        status: string;
      }[];
      name: string;
      role: string;
      roles: string[];
      slug: string;
    } | null;
    settings: {
      [k: string]: string;
    };
    teams: {
      display_name: string;
      id: string;
      members: {
        email: string;
        role: string;
        status: string;
      }[];
      name: string;
      role: string;
      roles: string[];
      slug: string;
    }[];
    user: {
      display_name: string;
      email: string;
      id: string;
    };
  };
  settings_update_response?: {
    audit: {
      fields: string[];
      recorded: boolean;
      scope: string;
      state_slice: string;
    };
    settings: {
      [k: string]: string;
    };
    settings_schema: {
      [k: string]: {
        default: string;
        description: string;
        values: string[];
      };
    };
  };
}
