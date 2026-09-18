import { useEffect, useMemo } from "react";
import type React from "react";
import { useAppStore } from "./store";
import { useBackendStore } from "./store/backend";
import { Section } from "./types";
import { Layout } from "./components/Layout";
import { LoginScreen } from "./pages/Login";
import { CommandCenter } from "./pages/CommandCenter";
import { Investigation } from "./pages/Investigation";
import { CaseIntakePage } from "./pages/CaseIntakePage";
import { NetworkIntel } from "./pages/NetworkIntel";
import { EntityExplorer } from "./pages/EntityExplorer";
import { TimelinePage } from "./pages/TimelinePage";
import { AlertsPage } from "./pages/AlertsPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { LocationsPage } from "./pages/LocationsPage";
import { CommunicationsPage } from "./pages/Communications";
import { TransactionsPage } from "./pages/Transactions";
import { AssistantPage } from "./pages/AssistantPage";
import { SimulationPage } from "./pages/SimulationPage";
import { AuditPage } from "./pages/AuditPage";
import { EvidenceIntegrityPage } from "./pages/EvidenceIntegrityPage";
import { ErrorBoundary } from "./components/ErrorBoundary";

const pages: Record<Exclude<Section, "login">, React.JSX.Element> = {
  "command-center": <CommandCenter />,
  investigations: <Investigation />,
  "case-intake": <CaseIntakePage />,
  network: <NetworkIntel />,
  entities: <EntityExplorer />,
  timeline: <TimelinePage />,
  locations: <LocationsPage />,
  transactions: <TransactionsPage />,
  communications: <CommunicationsPage />,
  alerts: <AlertsPage />,
  reports: <ReportsPage />,
  settings: <SettingsPage />,
  assistant: <AssistantPage />,
  simulation: <SimulationPage />,
  audit: <AuditPage />,
  integrity: <EvidenceIntegrityPage />
};

export function App() {
  const { section } = useAppStore();
  const loginComplete = useAppStore((s) => s.loginComplete);
  const connect = useBackendStore((s) => s.connect);

  // Once the user enters the app, attempt to wire the live backend; if it is
  // unreachable the UI transparently falls back to synthetic mock data.
  useEffect(() => {
    if (loginComplete) {
      void connect();
    }
  }, [loginComplete, connect]);

  const content = useMemo(() => (section === "login" ? <LoginScreen /> : pages[section]), [section]);
  return section === "login" ? content : <Layout><ErrorBoundary key={section} fallback={<div className="panel"><h3>Command Center unavailable</h3><div className="meta">The visualization layer failed to load, but the app shell is still running.</div></div>}>{content}</ErrorBoundary></Layout>;
}
