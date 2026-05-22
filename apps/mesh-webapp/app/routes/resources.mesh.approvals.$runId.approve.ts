import type { ActionFunctionArgs } from "@remix-run/node";

import { readOperatorActionPayload, proxyMeshJsonAction, steeringPayload } from "../mesh-actions.server";
import { encodeControlPlaneSegment } from "../mesh-control-plane.server";

export async function action({ params, request }: ActionFunctionArgs) {
  const runId = encodeControlPlaneSegment(params.runId ?? "");
  const input = await readOperatorActionPayload(request);
  return proxyMeshJsonAction(request, `/api/runs/${runId}/steer`, steeringPayload("approve", input));
}
