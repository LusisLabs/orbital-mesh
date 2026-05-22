import type { ReactNode } from "react";

export function PageHeader({
  actions,
  eyebrow,
  title
}: {
  actions?: ReactNode;
  eyebrow?: string;
  title: string;
}) {
  return (
    <header className="page-header">
      <div>
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}
