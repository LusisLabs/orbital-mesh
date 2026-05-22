import { Check, X } from "lucide-react";

import { Badge } from "../components/primitives/Badge";
import { Button } from "../components/primitives/Button";
import { DataTable } from "../components/primitives/Table";
import { PageHeader } from "../components/primitives/PageHeader";

export default function ApprovalsRoute() {
  return (
    <section className="page-stack">
      <PageHeader eyebrow="mesh.operator_dashboard_shell" title="Approvals" />
      <DataTable>
        <thead>
          <tr>
            <th>Request</th>
            <th>Action</th>
            <th>State</th>
            <th>Decision</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>approval_alpha</td>
            <td>pause steering</td>
            <td><Badge tone="warn">pending</Badge></td>
            <td className="row-actions">
              <Button icon={<Check size={15} />} variant="primary">Approve</Button>
              <Button icon={<X size={15} />} variant="secondary">Reject</Button>
            </td>
          </tr>
        </tbody>
      </DataTable>
    </section>
  );
}
