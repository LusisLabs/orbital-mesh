import "./globals.css";

import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Orbital Mesh Operator",
  description: "Operator console for bounded Mesh production readiness, evidence runs, approvals, and pilot packets.",
  openGraph: {
    title: "Orbital Mesh Operator",
    description: "Bounded production operator console for Mesh control-plane readiness.",
    type: "website",
  },
};

export const viewport: Viewport = {
  colorScheme: "dark",
  themeColor: "#0e1013",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
