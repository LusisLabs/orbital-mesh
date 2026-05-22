import type { LoaderFunctionArgs } from "@remix-run/node";

import { proxyControlPlaneRequest } from "../mesh-control-plane.server";

export function loader({ request }: LoaderFunctionArgs) {
  return proxyControlPlaneRequest(request, "/api/approvals");
}
