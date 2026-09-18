import { Fragment, useState } from "react";
import { useAppStore } from "../store";
import { useBackendStore } from "../store/backend";
import { Section } from "../types";
import { Bell, Building2, ChevronDown, FileText, Fingerprint, MapPin, MessageSquare, Play, Radar, ScrollText, Settings, Shield, Sparkles, TimerReset, Users, Upload } from "lucide-react";

type NavGroup = "OPERATIONS" | "ANALYZE" | "INTELLIGENCE" | "OUTPUT" | "ASSISTANT";

const items: { id: Exclude<Section, "login">; label: string; icon: React.ReactNode; group: NavGroup }[] = [
  { id: "command-center", label: "Command", icon: <Shield size={14} />, group: "OPERATIONS" },
  { id: "investigations", label: "Cases", icon: <Radar size={14} />, group: "OPERATIONS" },
  { id: "case-intake", label: "Intake", icon: <Upload size={14} />, group: "OPERATIONS" },
  { id: "network", label: "Network", icon: <Users size={14} />, group: "ANALYZE" },
  { id: "entities", label: "Entities", icon: <Building2 size={14} />, group: "ANALYZE" },
  { id: "timeline", label: "Timeline", icon: <TimerReset size={14} />, group: "ANALYZE" },
  { id: "locations", label: "Locations", icon: <MapPin size={14} />, group: "ANALYZE" },
  { id: "transactions", label: "Transactions", icon: <MessageSquare size={14} />, group: "ANALYZE" },
  { id: "communications", label: "Communications", icon: <Users size={14} />, group: "ANALYZE" },
  { id: "alerts", label: "Alerts", icon: <Bell size={14} />, group: "INTELLIGENCE" },
  { id: "integrity", label: "Evidence Integrity", icon: <Fingerprint size={14} />, group: "INTELLIGENCE" },
  { id: "simulation", label: "Simulation", icon: <Play size={14} />, group: "INTELLIGENCE" },
  { id: "reports", label: "Reports", icon: <FileText size={14} />, group: "OUTPUT" },
  { id: "audit", label: "Audit", icon: <ScrollText size={14} />, group: "OUTPUT" },
  { id: "settings", label: "Settings", icon: <Settings size={14} />, group: "OUTPUT" },
  { id: "assistant", label: "Assistant", icon: <Sparkles size={14} />, group: "ASSISTANT" },
];

const GROUP_ORDER: NavGroup[] = ["OPERATIONS", "ANALYZE", "INTELLIGENCE", "OUTPUT", "ASSISTANT"];

export function TopNav() {
  const { section, setSection } = useAppStore();
  const mode = useBackendStore((s) => s.mode);
  const [openGroup, setOpenGroup] = useState<NavGroup | null>(null);
  const grouped = GROUP_ORDER.map((g) => ({ group: g, items: items.filter((i) => i.group === g) }))
    .filter((g) => g.items.length > 0);
  const connected = mode === "backend";
  return (
    <header className="top-nav">
      <div className="top-nav-brand">
        <span className="brand-mark">S</span>
        <div>
          <div className="top-nav-title">SECRET</div>
          <div className="top-nav-subtitle">Smart Entity &amp; Criminal Relationship Exploration Tool</div>
        </div>
      </div>
      <nav className="top-nav-links" aria-label="Primary">
        {grouped.map((g) => (
          <Fragment key={g.group}>
            <div
              className={`top-nav-group ${openGroup === g.group ? "is-open" : ""}`}
              onMouseEnter={() => setOpenGroup(g.group)}
              onMouseLeave={() => setOpenGroup(null)}
              onFocus={() => setOpenGroup(g.group)}
            >
            <button
              className={`top-nav-main ${g.items.some((item) => section === item.id) ? "active" : ""}`}
              onClick={() => setOpenGroup((current) => current === g.group ? null : g.group)}
              aria-haspopup="true"
              title={`${g.group} menu`}
            >
              <span>{g.group}</span>
              <ChevronDown size={13} aria-hidden="true" />
            </button>
            <div className="top-nav-menu" role="menu">
              <div className="top-nav-menu-label">{g.group}</div>
              {g.items.map((item) => (
                <button
                  key={item.id}
                  className={`top-nav-item ${section === item.id ? "active" : ""}`}
                  onClick={() => {
                    setSection(item.id);
                    setOpenGroup(null);
                  }}
                  role="menuitem"
                  title={item.label}
                >
                  <span className="nav-icon">{item.icon}</span>
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
            </div>
          </Fragment>
        ))}
      </nav>
      <div className={`top-nav-mode ${connected ? "live" : "demo"}`} aria-label={connected ? "LIVE BACKEND" : "SYNTHETIC OFFLINE DEMO"}>
        <span className="top-nav-mode-dot" />
        <span>{connected ? "LIVE BACKEND" : "SYNTHETIC OFFLINE DEMO"}</span>
      </div>
    </header>
  );
}
