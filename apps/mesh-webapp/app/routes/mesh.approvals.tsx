import type { LoaderFunctionArgs } from "@remix-run/node";
import { useLoaderData } from "@remix-run/react";

import { Badge } from "../components/primitives/Badge";
import { DataTable } from "../components/primitives/Table";
import { PageHeader } from "../components/primitives/PageHeader";
import { loadOverviewDashboard, type OverviewApproval } from "../mesh-dashboard.server";

export function loader({ request }: LoaderFunctionArgs) {
  return loadOverviewDashboard(request);
}

export default function ApprovalsRoute() {
  const dashboard = useLoaderData<typeof loader>();

  return (
    <section className="page-stack">
      <PageHeader eyebrow={dashboard.stateSlice} title="Approvals" />
      <DataTable>
        <thead>
          <tr>
            <th>Request</th>
            <th>Run</th>
            <th>Stage</th>
            <th>State</th>
            <th>Recommendation</th>
          </tr>
        </thead>
        <tbody>
          {dashboard.approvals.data.length > 0 ? (
            dashboard.approvals.data.map((approval, index) => (
              <tr key={approvalKey(approval, index)}>
                <td>{approval.queue_id || approval.run_id || `approval-${index + 1}`}</td>
                <td>{approval.run_id || "—"}</td>
                <td>{approval.stage || "—"}</td>
                <td><Badge tone={approval.approval_state === "approved" ? "good" : approval.approval_state === "rejected" ? "bad" : "warn"}>{approval.approval_state || "pending"}</Badge></td>
                <td>{approval.final_recommendation || approval.risk_level || "Mesh decision pending"}</td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={5}>{dashboard.approvals.error ? `${dashboard.approvals.state}: ${dashboard.approvals.error}` : "No Mesh approvals pending."}</td>
            </tr>
          )}
        </tbody>
      </DataTable>
    </section>
  );
}

function approvalKey(approval: OverviewApproval, index: number): string {
  return approval.queue_id || `${approval.run_id || "approval"}-${approval.stage || index}`;
}
