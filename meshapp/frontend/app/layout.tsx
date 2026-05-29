import "./globals.css";

import { IBM_Plex_Mono, Inter } from "next/font/google";
import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
  variable: "--font-ibm-plex-mono",
});

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
  themeColor: "#111217",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className={`mesh-app-body ${inter.variable} ${ibmPlexMono.variable}`}>{children}</body>
    </html>
  );
}
