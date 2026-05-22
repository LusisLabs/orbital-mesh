import type { ReactNode } from "react";

export function DataTable({ children }: { children: ReactNode }) {
  return (
    <div className="table-shell">
      <table>{children}</table>
    </div>
  );
}
