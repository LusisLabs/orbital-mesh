import { Badge } from "../components/primitives/Badge";
import { DetailCell } from "../components/primitives/DetailCell";
import { PageHeader } from "../components/primitives/PageHeader";

export default function PolicyRoute() {
  return (
    <section className="page-stack">
      <PageHeader eyebrow="mesh.operator_dashboard_shell" title="Policy" />
      <dl className="detail-grid">
        <DetailCell label="Runtime authority" value={<Badge tone="good">Mesh</Badge>} />
        <DetailCell label="Trigger import posture" value={<Badge tone="neutral">source-input only</Badge>} />
      </dl>
    </section>
  );
}
