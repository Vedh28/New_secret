import { useEffect, useMemo, useState } from "react";
import { Shield, ChevronRight, Pin, Waves, ArrowUpRight } from "lucide-react";
import { HoloList, HudCard, StatRow } from "../components/HudPrimitives";
import { GlobeScene } from "../components/GlobeScene";
import {
  DnaPanel, PriorityPanel, RecommendationList, AnomalyList,
  PotentialLinksList, GapList, TemporalChangesList, IntelligenceSummary,
} from "../components/IntelligenceUi";
import { useBackendStore } from "../store/backend";
import { apiDashboardSummary, type DashboardSummary } from "../services/api";
import { useCaseIntelligence } from "../hooks/useCaseIntelligence";
import { useCaseSelection } from "../services/useCaseSelection";

/**
 * Command Center — executive investigative intelligence view.
 *
 * Answers: what cases are active, which entities matter, what changed recently,
 * what anomalies/potential links exist, what evidence is missing, and what to
 * investigate next. All values come from the case intelligence engine (live or
 * deterministic offline) — nothing is hardcoded.
 */
export function CommandCenter() {
  const [tick, setTick] = useState(0);
  const backend = useBackendStore((s) => s.mode);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const { caseKey } = useCaseSelection();
  const { intel } = useCaseIntelligence(caseKey);
  const live = backend === "backend";

  useEffect(() => { const t = setInterval(() => setTick((v) => v + 1), 2500); return () => clearInterval(t); }, []);
  useEffect(() => {
    if (!live) return;
    apiDashboardSummary().then(setSummary).catch(() => {});
  }, [live]);

  const today = new Date().toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" }).toUpperCase();
  const caseOverview = summary;

  // Primary insight: strongest recommendation (or fallback to top potential link).
  const topRec = intel?.recommendations?.[0] ?? null;
  const topAnomaly = (intel?.anomalies ?? [])[0];
  const topLink = (intel?.potential_links ?? [])[0];

  return (
    <div className="page command-center">
      <div className="app-background-globe" aria-hidden="true">
        <GlobeScene />
      </div>
      <div className="command-title-row">
        <div className="command-topline">
          <span>Intelligence</span>
          <span className="command-year">OPERATIONS</span>
        </div>
        <div className="command-hero">
          <div className="brand-lock">INVESTIGATIVE INTELLIGENCE</div>
          <div className="subtle">Smart Entity &amp; Criminal Relationship Exploration Tool</div>
        </div>
        <div className="system-meta command-clock">
          <div>SYSTEM {live ? "LIVE" : "ONLINE · DEMO DATA"}</div>
          <div>{today}</div>
          <div>{`21:${String((tick % 60) + 10).padStart(2, "0")}:14`}</div>
        </div>
      </div>

      {/* CASE OVERVIEW */}
      <div className="hud-bottom hud-bottom-command">
        <HudCard label="Case overview" title="Active investigations">
          {caseOverview ? (
            <HoloList items={[
              { label: "Active cases", value: String(caseOverview.cases) },
              { label: "Entities", value: caseOverview.entities.toLocaleString() },
              { label: "Relationships", value: caseOverview.relationships.toLocaleString() },
              { label: "Source files", value: String(caseOverview.sources) },
              { label: "Indicator alerts", value: String(caseOverview.alerts) },
            ]} />
          ) : (
            <div className="meta">No case selected / offline. Open a case to populate the overview.</div>
          )}
        </HudCard>

        <HudCard label="Recent intelligence" title="What changed" className="hud-recent-intelligence">
          <div className="mini-list compact-feed">
            {intel?.temporal_changes?.slice(0, 4).map((c, i) => (
              <div key={`${c.kind}-${c.source}-${i}`} className="entity feed-row">
                <div>
                  <div><span className="tag">{c.kind}</span> {c.source}{c.target ? ` ↔ ${c.target}` : ""}</div>
                  <div className="meta">{c.explanation}</div>
                </div>
                <ChevronRight size={14} color="var(--muted)" />
              </div>
            ))}
            {!(intel?.temporal_changes?.length) && <div className="meta">No network changes detected yet.</div>}
          </div>
        </HudCard>

        {topAnomaly ? (
          <HudCard label="Top signal" title="Most notable anomaly">
            <div className="alert high">
              <div>
                <div className="tag">{topAnomaly.kind} · score {topAnomaly.score}</div>
                <div>{topAnomaly.explanation}</div>
              </div>
            </div>
          </HudCard>
        ) : null}
      </div>

      <div className="hud-grid">
        <section className="hud-col" style={{ display: "grid", gap: 18 }}>
          {intel && (
            <div className="case-intelligence-flip" tabIndex={0} aria-label="Case intelligence and recent intelligence">
              <div className="case-intelligence-flip-inner">
                <div className="case-intelligence-flip-face case-intelligence-flip-front">
                  <HudCard label="Recent intelligence" title="What changed">
                    <div className="mini-list compact-feed">
                      {intel.temporal_changes?.slice(0, 4).map((c, i) => (
                        <div key={`${c.kind}-${c.source}-${i}`} className="entity feed-row">
                          <div>
                            <div><span className="tag">{c.kind}</span> {c.source}{c.target ? ` ↔ ${c.target}` : ""}</div>
                            <div className="meta">{c.explanation}</div>
                          </div>
                          <ChevronRight size={14} color="var(--muted)" />
                        </div>
                      ))}
                      {!(intel.temporal_changes?.length) && <div className="meta">No network changes detected yet.</div>}
                    </div>
                  </HudCard>
                </div>
                <div className="case-intelligence-flip-face case-intelligence-flip-back">
                  <IntelligenceSummary intel={intel} />
                </div>
              </div>
            </div>
          )}
          {intel && <PriorityPanel title="Investigation priority" items={intel.entity_priorities} />}
        </section>

        <section className="hud-center">
          <div className="hud-overview-panel">
            <div className="hud-title-bar">NETWORK OVERVIEW</div>
            <div className="hud-globe-anchors">
              <div className="glass-strip"><Pin size={12} /> Communities: {intel?.network_dna?.community_count ?? "—"}</div>
              <div className="glass-strip"><Waves size={12} /> Bridge: {intel?.network_dna?.bridge_dependence ?? "—"}</div>
              <div className="glass-strip"><ArrowUpRight size={12} /> Coverage: {intel?.network_dna?.evidence_coverage ?? 0}%</div>
            </div>
          </div>
          {intel && <div className="hud-dna-panel"><DnaPanel dna={intel.network_dna} /></div>}
        </section>

        <section className="hud-col" style={{ display: "grid", gap: 18 }}>
          {intel && <AnomalyList anomalies={intel.anomalies} />}
          {intel && <PotentialLinksList links={intel.potential_links} />}
          {intel && <GapList gaps={intel.evidence_gaps} />}
        </section>
      </div>

      {/* NEXT BEST ACTION — prominent */}
      {topRec && (
        <div className="hud-bottom hud-bottom-command hud-bottom-tight">
          <HudCard label="Next best action" title="Recommended investigation">
            <div className="entity entity-tight" style={{ alignItems: "flex-start" }}>
              <div>
                <div><b>{topRec.subject}</b> — {topRec.kind}</div>
                <div className="meta">Priority {Math.round(topRec.priority)} · Information gain {Math.round(topRec.info_gain)}</div>
                {topRec.reasoning?.slice(0, 3).map((r, i) => <div key={i} className="meta">• {r}</div>)}
                {topRec.recommended_data && <div className="meta">Data: {topRec.recommended_data}</div>}
              </div>
            </div>
          </HudCard>
          {topLink && (
            <HudCard label="Potential relationship" title="Hidden-link focus">
              <div className="entity entity-tight">
                <div>
                  <div><b>{topLink.source}</b> ↔ <b>{topLink.target}</b></div>
                  <div className="meta">{topLink.supporting_signals?.slice(0, 2).join(" · ")}</div>
                </div>
                <div className="risk">{Math.round(topLink.score)}%</div>
              </div>
            </HudCard>
          )}
        </div>
      )}
    </div>
  );
}
