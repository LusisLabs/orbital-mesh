import type { ActionFunctionArgs, LoaderFunctionArgs } from "@remix-run/node";

import { proxyControlPlaneRequest } from "../mesh-control-plane.server";

export function loader({ request }: LoaderFunctionArgs) {
  return proxyControlPlaneRequest(request, "/api/kill-switch");
}

export function action({ request }: ActionFunctionArgs) {
  return proxyControlPlaneRequest(request, "/api/kill-switch");
}
