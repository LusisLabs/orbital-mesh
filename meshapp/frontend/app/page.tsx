"use client";

import dynamic from "next/dynamic";

const OperatorApp = dynamic(() => import("../src/App"), {
  ssr: false,
});

export default function Home() {
  return <OperatorApp />;
}
