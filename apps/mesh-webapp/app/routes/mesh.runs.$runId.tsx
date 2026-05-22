import type { LoaderFunctionArgs } from "@remix-run/node";
import { useLoaderData } from "@remix-run/react";

import { Badge } from "../components/primitives/Badge";
import { DetailCell } from "../components/primitives/DetailCell";
import { PageHeader } from "../components/primitives/PageHeader";

export function loader({ params }: LoaderFunctionArgs) {
  return {
    runId: params.runId || "unknown",
    stateSlice: "mesh.operator_dashboard_shell",
    authority: "control_plane_server.py"
  };
}

export default function RunDetailRoute() {
  const run = useLoaderData<typeof loader>();

  return (
    <section className="page-stack">
      <PageHeader eyebrow={run.stateSlice} title={run.runId} />
      <dl className="detail-grid">
        <DetailCell label="Authority" value={run.authority} />
        <DetailCell label="Evidence" value={<Badge tone="neutral">pending BFF</Badge>} />
        <DetailCell label="Merkle proof" value={<Badge tone="neutral">pending BFF</Badge>} />
        <DetailCell label="Vault preview" value={<Badge tone="neutral">pending BFF</Badge>} />
      </dl>
    </section>
  );
}
