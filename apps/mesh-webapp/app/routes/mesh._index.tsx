import type { LoaderFunctionArgs } from "@remix-run/node";
import type { ReactNode } from "react";
import { useLoaderData } from "@remix-run/react";
import { Activity, Power, RadioTower } from "lucide-react";

import { loadOverviewDashboard, type DashboardSection } from "../mesh-dashboard.server";
import { Badge } from "../components/primitives/Badge";
import { Button } from "../components/primitives/Button";
import { DataTable } from "../components/primitives/Table";
import { PageHeader } from "../components/primitives/PageHeader";

export function loader({ request }: LoaderFunctionArgs) {
  return loadOverviewDashboard(request);
}

export default function MeshOverviewRoute() {
  const dashboard = useLoaderData<typeof loader>();
  const readinessStatus = stringValue(dashboard.readiness.data.status) || dashboard.readiness.state;
  const connectorStatus = stringValue(dashboard.connectorCertification.data.status) || dashboard.connectorCertification.state;
  const liveExecution = booleanValue(dashboard.killSwitch.data.live_execution_enabled);
  const forceApproval = booleanValue(dashboard.killSwitch.data.force_approval_gate);

  return (
    <section className="page-stack">
      <PageHeader
        actions={
          <Button disabled icon={<Power size={16} />} variant={liveExecution ? "danger" : "secondary"}>
            Kill switch {liveExecution ? "armed" : "safe"}
          </Button>
        }
        eyebrow={dashboard.stateSlice}
        title="Operator overview"
      />
      <div className="metric-grid">
        <MetricCard
          icon={<Activity aria-hidden="true" size={18} />}
          label="Readiness"
          state={dashboard.readiness}
          value={readinessStatus}
        />
        <MetricCard
          icon={<RadioTower aria-hidden="true" size={18} />}
          label="Active runs"
          state={dashboard.runs}
          value={`${dashboard.runs.data.length}`}
        />
        <MetricCard
          icon={<Power aria-hidden="true" size={18} />}
          label="Authority"
          state={dashboard.killSwitch}
          value={forceApproval ? "approval gate" : liveExecution ? "live execution" : "manual"}
        />
      </div>

      <DataTable>
        <thead>
          <tr>
            <th>Signal</th>
            <th>State</th>
            <th>Mesh source</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Readiness</td>
            <td><SectionBadge section={dashboard.readiness} /></td>
            <td>/resources/mesh/readiness</td>
            <td>{readinessStatus}</td>
          </tr>
          <tr>
            <td>Connector certification</td>
            <td><SectionBadge section={dashboard.connectorCertification} /></td>
            <td>/resources/mesh/connector-certification</td>
            <td>{connectorStatus}</td>
          </tr>
          <tr>
            <td>Approvals</td>
            <td><SectionBadge section={dashboard.approvals} /></td>
            <td>/resources/mesh/approvals</td>
            <td>{dashboard.approvals.data.length} pending item(s)</td>
          </tr>
          <tr>
            <td>Kill switch</td>
            <td><SectionBadge section={dashboard.killSwitch} /></td>
            <td>/resources/mesh/kill-switch</td>
            <td>{liveExecution ? "live execution enabled" : "live execution disabled"}</td>
          </tr>
        </tbody>
      </DataTable>

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
                <td>{run.run_id}</td>
                <td>{run.scenario_key || "—"}</td>
                <td>{run.stage || "—"}</td>
                <td><Badge tone={run.status === "failed" ? "bad" : run.status === "paused" ? "warn" : "neutral"}>{run.status || "unknown"}</Badge></td>
                <td>{run.latest_merkle_root ? "rooted" : "pending"}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={5}>{emptyMessage(dashboard.runs)}</td>
            </tr>
          )}
        </tbody>
      </DataTable>
    </section>
  );
}

function MetricCard({ icon, label, state, value }: { icon: ReactNode; label: string; state: DashboardSection<unknown>; value: string }) {
  return (
    <article className="metric">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
      <SectionBadge section={state} />
    </article>
  );
}

function SectionBadge({ section }: { section: DashboardSection<unknown> }) {
  const tone = section.state === "ready" ? "good" : section.state === "blocked" || section.state === "degraded" ? "warn" : section.state === "empty" ? "neutral" : "bad";
  return <Badge tone={tone}>{section.state}</Badge>;
}

function emptyMessage(section: DashboardSection<unknown>) {
  return section.error ? `${section.state}: ${section.error}` : section.state === "empty" ? "No active runs reported by Mesh." : section.state;
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function booleanValue(value: unknown): boolean {
  return value === true;
}
