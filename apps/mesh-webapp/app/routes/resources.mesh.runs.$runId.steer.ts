import type { ActionFunctionArgs } from "@remix-run/node";

import { encodeControlPlaneSegment } from "../mesh-control-plane.server";
import { proxyControlPlaneRequest } from "../mesh-control-plane.server";

export function action({ params, request }: ActionFunctionArgs) {
  const runId = encodeControlPlaneSegment(params.runId ?? "");
  return proxyControlPlaneRequest(request, `/api/runs/${runId}/steer`);
}
