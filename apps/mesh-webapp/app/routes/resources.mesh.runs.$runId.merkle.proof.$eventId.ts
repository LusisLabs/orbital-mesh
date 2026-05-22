import type { LoaderFunctionArgs } from "@remix-run/node";

import { proxyControlPlaneRequest, requireControlPlaneSegment } from "../mesh-control-plane.server";

export function loader({ params, request }: LoaderFunctionArgs) {
  const runId = requireControlPlaneSegment(params.runId, "run id");
  const eventId = requireControlPlaneSegment(params.eventId, "event id");
  return proxyControlPlaneRequest(request, `/api/runs/${runId}/merkle/proof/${eventId}`);
}
