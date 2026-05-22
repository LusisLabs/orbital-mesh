import type { ActionFunctionArgs, LoaderFunctionArgs } from "@remix-run/node";

import { killSwitchPayload, proxyMeshJsonAction, readOperatorActionPayload } from "../mesh-actions.server";
import { proxyControlPlaneRequest } from "../mesh-control-plane.server";

export function loader({ request }: LoaderFunctionArgs) {
  return proxyControlPlaneRequest(request, "/api/kill-switch");
}

export async function action({ request }: ActionFunctionArgs) {
  const input = await readOperatorActionPayload(request);
  return proxyMeshJsonAction(request, "/api/kill-switch", killSwitchPayload(input));
}
