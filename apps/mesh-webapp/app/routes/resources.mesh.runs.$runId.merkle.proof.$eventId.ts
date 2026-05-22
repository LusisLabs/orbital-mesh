import type { LoaderFunctionArgs } from "@remix-run/node";

import { encodeControlPlaneSegment, proxyControlPlaneRequest } from "../mesh-control-plane.server";

export function loader({ params, request }: LoaderFunctionArgs) {
  const runId = encodeControlPlaneSegment(params.runId ?? "");
  const eventId = encodeControlPlaneSegment(params.eventId ?? "");
  return proxyControlPlaneRequest(request, `/api/runs/${runId}/merkle/proof/${eventId}`);
}
