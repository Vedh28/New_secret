import React from "react";
import ReactDOM from "react-dom/client";
import "./styles.css";
import districtsData from "./data/map/maharashtra-districts.json";
import { ErrorBoundary } from "./components/ErrorBoundary";

// Expose global MAHARASHTRA_DISTRICTS_DATA
if (typeof window !== "undefined") {
  (window as unknown as { MAHARASHTRA_DISTRICTS_DATA: unknown }).MAHARASHTRA_DISTRICTS_DATA = districtsData.districts;
}

const root = ReactDOM.createRoot(document.getElementById("root")!);
import("./App")
  .then(({ App }) => root.render(
    <React.StrictMode>
      <ErrorBoundary fallback={<div className="panel" style={{ margin: 24 }}><h2>SECRET could not load</h2><div className="meta">Refresh the page after the application error is resolved.</div></div>}>
        <App />
      </ErrorBoundary>
    </React.StrictMode>,
  ))
  .catch((error: unknown) => root.render(
    <div className="panel" style={{ margin: 24 }}>
      <h2>SECRET could not load</h2>
      <div className="meta">{error instanceof Error ? error.message : "Application module failed to load."}</div>
    </div>,
  ));
