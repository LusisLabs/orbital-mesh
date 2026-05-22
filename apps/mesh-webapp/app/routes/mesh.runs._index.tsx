import { Link } from "@remix-run/react";

import { Badge } from "../components/primitives/Badge";
import { DataTable } from "../components/primitives/Table";
import { PageHeader } from "../components/primitives/PageHeader";

const runs = [
  { id: "run_alpha", service: "payments-api", risk: "medium", status: "waiting" },
  { id: "run_beta", service: "ingress", risk: "low", status: "active" }
];

export default function RunsIndexRoute() {
  return (
    <section className="page-stack">
      <PageHeader eyebrow="mesh.operator_dashboard_shell" title="Runs" />
      <DataTable>
        <thead>
          <tr>
            <th>Run</th>
            <th>Service</th>
            <th>Risk</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td><Link to={`/mesh/runs/${run.id}`}>{run.id}</Link></td>
              <td>{run.service}</td>
              <td><Badge tone={run.risk === "medium" ? "warn" : "good"}>{run.risk}</Badge></td>
              <td>{run.status}</td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </section>
  );
}
