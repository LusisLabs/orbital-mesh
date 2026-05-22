import { Badge } from "../components/primitives/Badge";
import { DataTable } from "../components/primitives/Table";
import { PageHeader } from "../components/primitives/PageHeader";

export default function VaultRoute() {
  return (
    <section className="page-stack">
      <PageHeader eyebrow="mesh.operator_dashboard_shell" title="Vault" />
      <DataTable>
        <thead>
          <tr>
            <th>Document</th>
            <th>Run</th>
            <th>Integrity</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>incident-summary.json</td>
            <td>run_alpha</td>
            <td><Badge tone="neutral">pending BFF</Badge></td>
          </tr>
        </tbody>
      </DataTable>
    </section>
  );
}
