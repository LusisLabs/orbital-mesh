import type { ReactNode } from "react";

export function DetailCell({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="detail-cell">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
