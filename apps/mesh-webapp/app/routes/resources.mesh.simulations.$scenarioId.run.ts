import type { ActionFunctionArgs } from "@remix-run/node";

import { readOperatorActionPayload, proxyMeshJsonAction, runLaunchPayload } from "../mesh-actions.server";
import { encodeControlPlaneSegment } from "../mesh-control-plane.server";

export async function action({ params, request }: ActionFunctionArgs) {
  const scenarioId = encodeControlPlaneSegment(params.scenarioId ?? "");
  const input = await readOperatorActionPayload(request);
  return proxyMeshJsonAction(request, `/api/simulations/${scenarioId}/run`, runLaunchPayload(input));
}
