import { useState } from "react";
import { motion } from "framer-motion";
import { useAppStore } from "../store";
import { ShieldCheck, Network, LockKeyhole, ArrowRight } from "lucide-react";

const MESH_ITEMS = [
  ["NODES", "1,248", "indexed"],
  ["SOURCES", "86", "connected"],
  ["LINKS", "3,902", "mapped"],
  ["ENTITIES", "742", "resolved"],
  ["ALERTS", "18", "active"],
  ["CASES", "12", "tracked"],
  ["COMMS", "2.8K", "signals"],
  ["TXNS", "946", "screened"],
  ["COVERAGE", "78%", "verified"],
] as const;

export function LoginScreen() {
  const login = useAppStore((s) => s.login);
  const enterApp = useAppStore((s) => s.enterApp);
  const loginError = useAppStore((s) => s.loginError);
  const loggingIn = useAppStore((s) => s.loggingIn);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    void login(username, password);
  };

  return (
    <div className="login">
      <div className="login-card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div className="glass-strip">SECRET / Secure Intelligence Workspace</div>
          <div className="glass-strip">System Online</div>
        </div>
        <div className="login-grid">
          <div className="stack">
            <h1 className="title">Smart Entity &amp; Criminal Relationship Exploration Tool</h1>
            <p className="headline">A premium intelligence-analysis workspace for network discovery, entity profiling, and operational awareness.</p>
            <form className="stack" onSubmit={submit}>
              <input
                className="control hud-search"
                placeholder="Operator username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
              />
              <input
                className="control hud-search"
                type="password"
                placeholder="Access passphrase"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
              {loginError ? <div className="meta" style={{ color: "var(--red, #ff5f56)" }}>{loginError}</div> : null}
              <button className="cta" disabled={loggingIn || !username || !password} type="submit">
                {loggingIn ? "AUTHENTICATING..." : "ACCESS INTELLIGENCE CONSOLE"}
                <ArrowRight size={16} style={{ display: "inline", marginLeft: 8 }} />
              </button>
              <button className="pill" type="button" onClick={enterApp}>
                OFFLINE DEMO MODE (SYNTHETIC DATA)
              </button>
            </form>
            <div className="meta">Demo operator: <b>admin</b> / <b>admin-secret</b></div>
          </div>
          <motion.div initial={{ opacity: 0.6, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 1.2 }} className="panel mini">
            <div className="row" style={{ justifyContent: "space-between" }}><h3 style={{ margin: 0 }}>Operational Mesh</h3><Network size={18} color="var(--blue)" /></div>
            <p className="meta">Live graph indices, source registry, and community analytics once connected to the backend.</p>
            <div className="mesh-grid">
              {MESH_ITEMS.map(([label, value, status]) => (
                <button className="mesh-node" key={label} type="button" title={`${label}: ${value} ${status}`}>
                  <span>{label}</span>
                  <strong>{value}</strong>
                  <small>{status}</small>
                </button>
              ))}
            </div>
            <div className="row" style={{ marginTop: 14 }}>
              <ShieldCheck size={16} color="var(--green)" />
              <span className="meta">JSON Web Token session</span>
              <LockKeyhole size={16} color="var(--muted)" />
            </div>
          </motion.div>
        </div>
      </div>
    </div>
  );
}
