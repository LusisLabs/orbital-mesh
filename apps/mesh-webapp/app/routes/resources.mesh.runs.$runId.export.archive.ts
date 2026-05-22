import type { ActionFunctionArgs } from "@remix-run/node";

import { proxyControlPlaneRequest, requireControlPlaneSegment } from "../mesh-control-plane.server";

export function action({ params, request }: ActionFunctionArgs) {
  const runId = requireControlPlaneSegment(params.runId, "run id");
  return proxyControlPlaneRequest(request, `/api/runs/${runId}/export/archive`);
}
