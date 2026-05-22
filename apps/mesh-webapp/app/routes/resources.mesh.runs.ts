import type { ActionFunctionArgs, LoaderFunctionArgs } from "@remix-run/node";

import { proxyMeshJsonAction, readOperatorActionPayload, runLaunchPayload } from "../mesh-actions.server";
import { proxyControlPlaneRequest } from "../mesh-control-plane.server";

export function loader({ request }: LoaderFunctionArgs) {
  return proxyControlPlaneRequest(request, "/api/runs");
}

export async function action({ request }: ActionFunctionArgs) {
  const input = await readOperatorActionPayload(request);
  return proxyMeshJsonAction(request, "/api/runs", runLaunchPayload(input));
}
