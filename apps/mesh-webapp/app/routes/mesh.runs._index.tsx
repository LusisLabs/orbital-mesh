import type { LoaderFunctionArgs } from "@remix-run/node";
import { Link, useLoaderData } from "@remix-run/react";

import { Badge } from "../components/primitives/Badge";
import { DataTable } from "../components/primitives/Table";
import { PageHeader } from "../components/primitives/PageHeader";
import { loadOverviewDashboard } from "../mesh-dashboard.server";

export function loader({ request }: LoaderFunctionArgs) {
  return loadOverviewDashboard(request);
}

export default function RunsIndexRoute() {
  const dashboard = useLoaderData<typeof loader>();

  return (
    <section className="page-stack">
      <PageHeader eyebrow={dashboard.stateSlice} title="Runs" />
      <DataTable>
        <thead>
          <tr>
            <th>Run</th>
            <th>Scenario</th>
            <th>Stage</th>
            <th>Status</th>
            <th>Merkle</th>
          </tr>
        </thead>
        <tbody>
          {dashboard.runs.data.length > 0 ? (
            dashboard.runs.data.map((run) => (
              <tr key={run.run_id}>
                <td><Link to={`/mesh/runs/${encodeURIComponent(run.run_id)}`}>{run.run_id}</Link></td>
                <td>{run.scenario_key || "—"}</td>
                <td>{run.stage || "—"}</td>
                <td><Badge tone={run.status === "failed" ? "bad" : run.status === "paused" ? "warn" : "neutral"}>{run.status || "unknown"}</Badge></td>
                <td>{run.latest_merkle_root ? "rooted" : "pending"}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={5}>{dashboard.runs.error ? `${dashboard.runs.state}: ${dashboard.runs.error}` : "No Mesh runs reported."}</td>
            </tr>
          )}
        </tbody>
      </DataTable>
    </section>
  );
}
