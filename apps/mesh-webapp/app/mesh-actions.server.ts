import { proxyControlPlaneRequest } from "./mesh-control-plane.server";

export const MESH_OPERATOR_ACTIONS_STATE_SLICE = "mesh.operator_actions";

export type OperatorActionKind = "approve" | "reject" | "pause" | "resume";

export async function proxyMeshJsonAction(
  request: Request,
  controlPlanePath: string,
  payload: Record<string, unknown>
): Promise<Response> {
  const headers = new Headers(request.headers);
  headers.set("content-type", "application/json");
  const proxiedRequest = new Request(request.url, {
    method: "POST",
    headers,
    body: JSON.stringify({
      ...payload,
      state_slice: MESH_OPERATOR_ACTIONS_STATE_SLICE
    })
  });
  return proxyControlPlaneRequest(proxiedRequest, controlPlanePath);
}

export async function readOperatorActionPayload(request: Request): Promise<Record<string, unknown>> {
  const contentType = request.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const payload = await request.json().catch(() => ({}));
    return payload && typeof payload === "object" && !Array.isArray(payload) ? payload as Record<string, unknown> : {};
  }
  const form = await request.formData().catch(() => new FormData());
  return Object.fromEntries(form.entries());
}

export function steeringPayload(action: OperatorActionKind, input: Record<string, unknown> = {}): Record<string, unknown> {
  const reason = typeof input.reason === "string" && input.reason.trim() ? input.reason.trim() : defaultReason(action);
  const command = action === "approve" ? "approve" : action === "reject" ? "cancel" : action;
  return {
    ...input,
    command,
    reason,
    backend_resource: "RunSession.steering",
    mutation: action,
    would_touch_state_slice: "mesh.run_steering.v1"
  };
}

export function killSwitchPayload(input: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ...input,
    backend_resource: "KillSwitchStatus",
    would_touch_state_slice: "mesh.kill_switch.v1"
  };
}

export function runLaunchPayload(input: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ...input,
    backend_resource: "RunSession",
    would_touch_state_slice: "mesh.run_admission.v1"
  };
}

function defaultReason(action: OperatorActionKind): string {
  switch (action) {
    case "approve":
      return "operator approved through Mesh web action";
    case "reject":
      return "operator rejected through Mesh web action";
    case "pause":
      return "operator paused steering through Mesh web action";
    case "resume":
      return "operator resumed steering through Mesh web action";
  }
}
