import { useState } from "react";
import { HudPage } from "../components/HudPage";
import { HudCard } from "../components/HudPrimitives";

export function SettingsPage() {
  const [density, setDensity] = useState<"compact" | "balanced" | "comfortable">("compact");
  return (
    <HudPage title="SETTINGS" subtitle="Appearance and visualization preferences" rightMeta={<><div>DENSITY {density.toUpperCase()}</div></>}>
      <div className="hud-settings-layout">
        <HudCard label="Profile" title="Interface Core" className="hud-settings-profile">
          <div className="hud-settings-profile-head"><div className="hud-settings-avatar">S</div><div><strong>SECRET Operator</strong><span>ADMIN ACCESS</span></div></div>
          <div className="meta">Professional desktop configuration surface for intelligence operations.</div>
        </HudCard>
        <HudCard label="Preference module" title="Interface Density" className="hud-settings-controls">
          <div className="meta">Choose how much information each workspace panel should show.</div>
          <div className="hud-settings-density-options">{(["compact", "balanced", "comfortable"] as const).map((option) => <button key={option} className={`pill ${density === option ? "selected" : ""}`} onClick={() => setDensity(option)}>{option.toUpperCase()}</button>)}</div>
          <div className="hud-settings-scale">
            <span className={density === "compact" ? "active" : ""} />
            <span className={density === "balanced" ? "active" : ""} />
            <span className={density === "comfortable" ? "active" : ""} />
          </div>
        </HudCard>
        <div className="stack hud-settings-stack">
          {["Appearance","Notifications","Visualization preferences","Data refresh preferences","Security preferences","About SECRET"].map((x) => (
            <HudCard label="Preference module" title={x} key={x}>
              <div className="meta">Native system screen styling with restrained micro-ornaments.</div>
            </HudCard>
          ))}
        </div>
      </div>
    </HudPage>
  );
}
