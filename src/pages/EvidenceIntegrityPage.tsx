import { useCallback, useEffect, useState } from "react";
import { HudPage } from "../components/HudPage";
import { HudCard, HoloList } from "../components/HudPrimitives";
import { useBackendStore } from "../store/backend";
import { useCaseSelection } from "../services/useCaseSelection";
import {
  apiEvidenceHistory,
  apiIntegrityEvents,
  apiIntegrityLedger,
  apiIntegritySummary,
  apiVerifyEvidence,
  apiVerifyIntegrity,
  type IntegrityBlock,
  type IntegrityEvent,
  type IntegritySummary,
} from "../services/api";

const STATUS_CLASS: Record<string, string> = {
  VALID: "status-ok",
  VERIFIED: "status-ok",
  WARNING: "status-warn",
  PENDING: "status-warn",
  MISMATCH: "status-bad",
  UNAVAILABLE: "status-mute",
};

function statusText(status: string | undefined): string {
  return status || "UNAVAILABLE";
}

function short(hash: string | null | undefined, length = 10): string {
  if (!hash) return "—";
  return `${hash.slice(0, length)}…${hash.slice(-6)}`;
}

export function EvidenceIntegrityPage() {
  const backend = useBackendStore((s) => s.mode);
  const { caseKey, setCaseKey, cases } = useCaseSelection();
  const [summary, setSummary] = useState<IntegritySummary | null>(null);
  const [events, setEvents] = useState<IntegrityEvent[]>([]);
  const [blocks, setBlocks] = useState<IntegrityBlock[]>([]);
  const [pending, setPending] = useState(0);
  const [detail, setDetail] = useState<IntegrityEvent | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<Record<string, unknown> | null>(null);
  const mismatches = (verifyResult as { mismatches?: unknown[] } | null)?.mismatches;
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (key: string) => {
    if (backend !== "backend" || !key) {
      setSummary(null);
      setEvents([]);
      setBlocks([]);
      return;
    }
    setError(null);
    try {
      const [s, ev, bl] = await Promise.all([
        apiIntegritySummary(key),
        apiIntegrityEvents(key),
        apiIntegrityLedger(key),
      ]);
      setSummary(s);
      setEvents(ev.events);
      setPending(ev.pending ?? 0);
      setBlocks(bl.blocks);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Integrity data unavailable");
      setSummary(null);
    }
  }, [backend]);

  useEffect(() => {
    void load(caseKey);
  }, [load, caseKey]);

  const verifyAll = async () => {
    if (!caseKey || backend !== "backend") return;
    setVerifying(true);
    setVerifyResult(null);
    try {
      setVerifyResult(await apiVerifyIntegrity(caseKey) as unknown as Record<string, unknown>);
      await load(caseKey);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed");
    } finally {
      setVerifying(false);
    }
  };

  const verifySource = async (sourceId: string) => {
    if (!caseKey) return;
    try {
      const result = await apiVerifyEvidence(caseKey, sourceId);
      setVerifyResult(result as unknown as Record<string, unknown>);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed");
    }
  };

  const showSourceHistory = async (sourceId: string) => {
    if (!caseKey) return;
    try {
      const history = await apiEvidenceHistory(caseKey, sourceId);
      setDetail({
        transaction_id: "",
        case_id: caseKey,
        event_type: "EVIDENCE_VERSIONS",
        entity_type: "source",
        entity_id: sourceId,
        payload_hash: "",
        payload_json: { versions: history.versions },
        block_index: null,
        block_hash: null,
        previous_block_hash: null,
        actor_id: null,
        status: "VERIFIED",
        created_at: "",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "History unavailable");
    }
  };

  const chainStatus = summary?.chain_status ?? "UNAVAILABLE";

  return (
    <HudPage
      title="EVIDENCE INTEGRITY LEDGER"
      subtitle="Cryptographic integrity, provenance and chain of custody — hashes only, evidence stays off-chain"
      rightMeta={<>{backend === "backend" ? <div>LIVE LEDGER</div> : <div>OFFLINE DEMO</div>}{summary ? <div>BLOCK {summary.latest_block?.index ?? 0}</div> : <div>NO CHAIN</div>}</>}
    >
      {backend === "backend" && (
        <HudCard label="Case" title="Investigation selector">
          <select className="control hud-search" value={caseKey} onChange={(e) => setCaseKey(e.target.value)}>
            {cases.map((c) => <option key={c.case_number} value={c.case_number}>{c.case_number} · {c.title}</option>)}
          </select>
        </HudCard>
      )}

      {error && <HudCard label="System" title="Unavailable"><div className="meta">{error}</div></HudCard>}

      {backend !== "backend" && (
        <HudCard label="Offline mode" title="Synthetic demo">
          <div className="meta">
            This console is live-only. Switch to SYNTHETIC OFFLINE DEMO mode in navigation when the backend
            is unavailable; offline demo sources are not presented as a live chain.
          </div>
        </HudCard>
      )}

      {backend === "backend" && summary && (
        <div className="hud-integrity-layout">
          <HudCard label="Chain status" title={`Ledger ${chainStatus}`}>
            <div className={`integrity-status-pill ${STATUS_CLASS[chainStatus] ?? "status-mute"}`}>{chainStatus}</div>
            <HoloList items={[
              { label: "Evidence registered", value: String(summary.evidence_registered) },
              { label: "Evidence verified", value: String(summary.evidence_verified) },
              { label: "Integrity mismatches", value: String(summary.mismatches) },
              { label: "Ledger events", value: String(summary.events) },
              { label: "Verified snapshots", value: String(summary.verified_snapshots) },
              { label: "Verified reports", value: String(summary.verified_reports) },
            ]} />
            {pending > 0 && <div className="meta" style={{ marginTop: 8 }}>{pending} pending integrity event(s) awaiting confirmation</div>}
            <button className="cta" onClick={verifyAll} disabled={verifying} style={{ marginTop: 12 }}>
              {verifying ? "VERIFYING..." : "VERIFY FULL CASE"}
            </button>
          </HudCard>

          <HudCard label="Latest block" title={summary.latest_block ? `#${summary.latest_block.index}` : "No blocks"}>
            {summary.latest_block ? (
              <div className="stack">
                <div className="meta"><b>Block hash</b> {short(summary.latest_block.block_hash)}</div>
                <div className="meta"><b>Previous hash</b> {short(summary.latest_block.previous_hash)}</div>
                <div className="meta"><b>Data hash</b> {short(summary.latest_block.data_hash)}</div>
                <div className="meta"><b>Timestamp</b> {summary.latest_block.timestamp}</div>
              </div>
            ) : (
              <div className="meta">No ledger blocks yet. Ingest a source to start the chain.</div>
            )}
            {summary.issues?.length ? <div className="meta" style={{ marginTop: 8, color: "var(--amber)" }}>{summary.issues.join(" · ")}</div> : null}
          </HudCard>

          {verifyResult && (
            <HudCard label="Verification" title="Latest verification run">
              <HoloList items={[
                { label: "Chain valid", value: String(Boolean(verifyResult.chain_valid ?? verifyResult.verified)) },
                { label: "Evidence checked", value: String(verifyResult.evidence_checked ?? (verifyResult.versions as unknown[] | undefined)?.length ?? "-") },
                { label: "Evidence verified", value: String(verifyResult.evidence_verified ?? "-") },
                { label: "Status", value: statusText(verifyResult.status as string), accent: STATUS_CLASS[String(verifyResult.status)] },
              ]} />
              {mismatches?.length ? (
                <div className="meta" style={{ marginTop: 8, color: "var(--red, #ff5f56)" }}>
                  {String(mismatches?.length)} integrity mismatch(es) detected.
                </div>
              ) : null}
              {typeof verifyResult.reason === "string" && <div className="meta" style={{ marginTop: 8 }}>{verifyResult.reason}</div>}
            </HudCard>
          )}

          <HudCard label="Chain of custody" title="Evidence lifecycle">
            <div className="mini-list compact-feed">
              {["Evidence Registered", "Evidence Processed", "Records Batched (Merkle)", "Entities Extracted", "Relationships Derived", "Analyst Review", "Decision", "Report Generated"].map((step, i) => (
                <div key={step} className="entity feed-row"><span className="meta">0{i + 1}</span><span>{step}</span></div>
              ))}
            </div>
            <div className="meta" style={{ marginTop: 10 }}>Only hashes and references are written to the ledger; evidence content stays in the case store.</div>
          </HudCard>

          <HudCard label="Blockchain activity" title="Recent ledger events">
            {events.length ? (
              <div className="stack">
                {events.slice(0, 8).map((event) => (
                  <button key={event.transaction_id} className="entity entity-tight" onClick={() => setDetail(event)}>
                    <div>
                      <div><span className="tag">#{event.block_index ?? "—"} {event.event_type}</span></div>
                      <div className="meta">{event.entity_id ?? event.case_id} · {event.transaction_id}</div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center" }}><VerifyGlyph event={event} /></div>
                  </button>
                ))}
              </div>
            ) : (
              <div className="meta">No ledger events yet.</div>
            )}
            <button className="pill" style={{ marginTop: 10 }} onClick={() => setDetail(null)}>Close detail</button>
          </HudCard>

          {detail && <EventDetail event={detail} onVerifySource={showSourceHistory} onVerify={verifySource} />}

          <HudCard label="Ledger blocks" title={`Chained blocks (${blocks.length})`}>
            <div className="stack">
              {[...blocks].reverse().slice(0, 10).map((block) => (
                <div key={block.index} className="entity entity-tight">
                  <div>
                    <div><span className="tag">#{block.index}</span> {block.events.length} event(s)</div>
                    <div className="meta">block {short(block.block_hash)} · previous {short(block.previous_hash)}</div>
                  </div>
                </div>
              ))}
              {!blocks.length && <div className="meta">Chain empty.</div>}
            </div>
          </HudCard>
        </div>
      )}
    </HudPage>
  );
}

function VerifyGlyph({ event }: { event: IntegrityEvent }) {
  const status = event.status?.toUpperCase();
  const cls = status === "REGISTERED" || status === "VERIFIED" ? "status-ok" : "status-mute";
  return <span className={cls}>◆</span>;
}

function EventDetail({ event, onVerifySource, onVerify }: {
  event: IntegrityEvent;
  onVerifySource: (id: string) => void;
  onVerify: (id: string) => void;
}) {
  const versions = (event.payload_json?.versions as unknown[] | undefined) ?? [];
  return (
    <HudCard label="Event detail" title={event.event_type}>
      <HoloList items={[
        { label: "Transaction", value: event.transaction_id || "—" },
        { label: "Block", value: event.block_index !== null ? `#${event.block_index}` : "pending" },
        { label: "Entity", value: `${event.entity_type ?? "—"} ${event.entity_id ?? "—"}` },
        { label: "Payload hash", value: short(event.payload_hash) },
        { label: "Previous block hash", value: short(event.previous_block_hash) },
        { label: "Block hash", value: short(event.block_hash) },
        { label: "Timestamp", value: event.created_at ? new Date(event.created_at).toLocaleString() : "—" },
      ]} />
      {versions.length > 0 && (
        <div className="stack" style={{ marginTop: 10 }}>
          <div className="meta"><b>Evidence versions</b></div>
          {versions.map((v) => (
            <div key={(v as { version?: number }).version} className="entity entity-tight">
              <div>
                <div>v{(v as { version?: number }).version} · {(v as { status?: string }).status}</div>
                <div className="meta">{(v as { transaction_id?: string }).transaction_id} · block {(v as { block_index?: number | null }).block_index ?? "—"}</div>
              </div>
            </div>
          ))}
        </div>
      )}
      {event.entity_type === "source" && event.entity_id && (
        <div className="filters hud-filters" style={{ marginTop: 10 }}>
          <button className="pill" onClick={() => onVerify(event.entity_id!)}>VERIFY SOURCE</button>
          {event.event_type === "EVIDENCE_REGISTERED" && <button className="pill" onClick={() => onVerifySource(event.entity_id!)}>VERSION HISTORY</button>}
        </div>
      )}
    </HudCard>
  );
}