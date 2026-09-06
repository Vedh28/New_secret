import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./styles.css";
import districtsData from "./data/map/maharashtra-districts.json";

// Expose global MAHARASHTRA_DISTRICTS_DATA
if (typeof window !== "undefined") {
  (window as unknown as { MAHARASHTRA_DISTRICTS_DATA: unknown }).MAHARASHTRA_DISTRICTS_DATA = districtsData.districts;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
