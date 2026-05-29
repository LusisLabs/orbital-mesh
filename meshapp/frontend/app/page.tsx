"use client";

import { useEffect, useState } from "react";

import Landing from "../pages/Landing";
import { shouldRenderLanding } from "../src/product/entryMode";
import OperatorApp from "../src/product/ProductApp";

function RouteBootScreen() {
  return (
    <div className="product-boot" aria-busy="true" aria-label="Loading">
      <span className="mesh-logo compact">
        <img src="/orbital-mesh-logo.svg" alt="" />
      </span>
      <span>Loading</span>
    </div>
  );
}

export default function Home() {
  const [routeReady, setRouteReady] = useState(false);
  const [renderLanding, setRenderLanding] = useState(false);

  useEffect(() => {
    setRenderLanding(shouldRenderLanding(window.location.hostname, window.location.search));
    setRouteReady(true);
  }, []);

  if (!routeReady) {
    return <RouteBootScreen />;
  }

  return renderLanding ? <Landing /> : <OperatorApp />;
}
