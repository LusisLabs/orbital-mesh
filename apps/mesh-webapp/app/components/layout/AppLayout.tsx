import type { ReactNode } from "react";

import { SideNav } from "../navigation/SideNav";

export function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="app-layout">
      <SideNav />
      <main className="main-panel">{children}</main>
    </div>
  );
}
