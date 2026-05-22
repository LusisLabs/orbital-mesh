import { Outlet } from "@remix-run/react";

import { AppLayout } from "../components/layout/AppLayout";

export default function MeshLayout() {
  return (
    <AppLayout>
      <Outlet />
    </AppLayout>
  );
}
