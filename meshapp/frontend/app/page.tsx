"use client";

import { useMemo } from "react";

import Landing from "../pages/Landing";
import { shouldRenderLanding } from "../src/product/entryMode";
import OperatorApp from "../src/product/ProductApp";

export default function Home() {
  const renderLanding = useMemo(() => {
    if (typeof window === "undefined") return false;
    return shouldRenderLanding(window.location.hostname, window.location.search);
  }, []);

  return renderLanding ? <Landing /> : <OperatorApp />;
}
