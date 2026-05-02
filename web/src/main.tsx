import React from "react";
import ReactDOM from "react-dom/client";
import "@vscode/codicons/dist/codicon.css";
import "@xyflow/react/dist/style.css";

import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
