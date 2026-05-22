import { env, type MeshWebEnvironment } from "./env.server";

export const MESH_CONTROL_PLANE_PROXY_STATE_SLICE = "mesh.control_plane_proxy";

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade"
]);

const DEFAULT_OPERATOR_HEADER_NAMES = [
  "x-mesh-operator",
  "x-mesh-roles",
  "x-mesh-scope",
  "x-mesh-tenant"
];

export function buildControlPlaneUrl(
  apiPath: string,
  requestUrl: string,
  meshEnv: Pick<MeshWebEnvironment, "MESH_CONTROL_PLANE_URL"> = env
): URL {
  const upstream = new URL(apiPath, `${meshEnv.MESH_CONTROL_PLANE_URL.replace(/\/+$/, "")}/`);
  const incoming = new URL(requestUrl);
  upstream.search = incoming.search;
  return upstream;
}

function configuredOperatorHeaderNames(meshEnv: Pick<MeshWebEnvironment, "MESH_OPERATOR_IDENTITY_HEADER">): string[] {
  const configured = meshEnv.MESH_OPERATOR_IDENTITY_HEADER?.trim();
  return configured ? [configured.toLowerCase()] : [];
}

export function forwardedControlPlaneHeaders(
  request: Request,
  meshEnv: Pick<MeshWebEnvironment, "MESH_OPERATOR_IDENTITY_HEADER"> = env
): Headers {
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const accept = request.headers.get("accept");
  if (contentType) headers.set("content-type", contentType);
  if (accept) headers.set("accept", accept);

  const allowedOperatorHeaders = new Set([
    ...DEFAULT_OPERATOR_HEADER_NAMES,
    ...configuredOperatorHeaderNames(meshEnv)
  ]);
  for (const [name, value] of request.headers.entries()) {
    const normalized = name.toLowerCase();
    if (allowedOperatorHeaders.has(normalized) && value.trim()) {
      headers.set(name, value);
    }
  }
  return headers;
}

function proxiedResponseHeaders(upstreamHeaders: Headers): Headers {
  const headers = new Headers();
  for (const [name, value] of upstreamHeaders.entries()) {
    if (!HOP_BY_HOP_HEADERS.has(name.toLowerCase())) {
      headers.set(name, value);
    }
  }
  return headers;
}

function proxyFailureResponse(error: unknown): Response {
  return new Response(
    JSON.stringify({
      error: "Mesh control plane unavailable",
      detail: error instanceof Error ? error.message : String(error),
      state_slice: MESH_CONTROL_PLANE_PROXY_STATE_SLICE
    }),
    {
      status: 502,
      headers: { "content-type": "application/json" }
    }
  );
}

export async function proxyControlPlaneRequest(
  request: Request,
  apiPath: string,
  meshEnv: Pick<MeshWebEnvironment, "MESH_CONTROL_PLANE_URL" | "MESH_OPERATOR_IDENTITY_HEADER"> = env
): Promise<Response> {
  const upstreamUrl = buildControlPlaneUrl(apiPath, request.url, meshEnv);
  const method = request.method.toUpperCase();
  const init: RequestInit = {
    method,
    headers: forwardedControlPlaneHeaders(request, meshEnv)
  };
  if (method !== "GET" && method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  try {
    const upstream = await fetch(upstreamUrl, init);
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: proxiedResponseHeaders(upstream.headers)
    });
  } catch (error) {
    return proxyFailureResponse(error);
  }
}

export function encodeControlPlaneSegment(segment: string): string {
  return encodeURIComponent(segment);
}

export function requireControlPlaneSegment(segment: string | undefined, label: string): string {
  if (!segment || !segment.trim()) {
    throw new Response(`Missing Mesh ${label}`, {
      status: 400,
      headers: { "content-type": "text/plain; charset=utf-8" }
    });
  }
  return encodeControlPlaneSegment(segment);
}
