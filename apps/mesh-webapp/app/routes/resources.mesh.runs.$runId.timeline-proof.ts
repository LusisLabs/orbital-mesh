import type { LoaderFunctionArgs } from "@remix-run/node";

import { encodeControlPlaneSegment, proxyControlPlaneRequest } from "../mesh-control-plane.server";

export function loader({ params, request }: LoaderFunctionArgs) {
  const runId = encodeControlPlaneSegment(params.runId ?? "");
  return proxyControlPlaneRequest(request, `/api/runs/${runId}/timeline-proof`);
}
