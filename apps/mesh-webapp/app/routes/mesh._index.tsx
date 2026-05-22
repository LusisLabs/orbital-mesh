import { Activity, Power, RadioTower } from "lucide-react";

import { Badge } from "../components/primitives/Badge";
import { Button } from "../components/primitives/Button";
import { DataTable } from "../components/primitives/Table";
import { PageHeader } from "../components/primitives/PageHeader";

const activeRuns = [
  { id: "run_alpha", service: "payments-api", state: "awaiting approval", owner: "sre" },
  { id: "run_beta", service: "ingress", state: "investigating", owner: "platform" }
];

export default function MeshOverviewRoute() {
  return (
    <section className="page-stack">
      <PageHeader
        actions={<Button icon={<Power size={16} />} variant="danger">Kill switch</Button>}
        eyebrow="mesh.operator_dashboard_shell"
        title="Operator overview"
      />
      <div className="metric-grid">
        <article className="metric">
          <Activity aria-hidden="true" size={18} />
          <span>Readiness</span>
          <strong>Local shell</strong>
        </article>
        <article className="metric">
          <RadioTower aria-hidden="true" size={18} />
          <span>Realtime</span>
          <strong>Pending BFF</strong>
        </article>
        <article className="metric">
          <Power aria-hidden="true" size={18} />
          <span>Authority</span>
          <strong>Mesh only</strong>
        </article>
      </div>
      <DataTable>
        <thead>
          <tr>
            <th>Run</th>
            <th>Service</th>
            <th>State</th>
            <th>Owner</th>
          </tr>
        </thead>
        <tbody>
          {activeRuns.map((run) => (
            <tr key={run.id}>
              <td>{run.id}</td>
              <td>{run.service}</td>
              <td><Badge tone={run.state.includes("approval") ? "warn" : "neutral"}>{run.state}</Badge></td>
              <td>{run.owner}</td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </section>
  );
}
