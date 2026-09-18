import { useEffect, useMemo, useRef, useState } from "react";
import { HudPage } from "../components/HudPage";
import { HudCard, HoloList } from "../components/HudPrimitives";
import { useBackendStore } from "../store/backend";
import {
  apiCreateCase,
  apiGenerateAlerts,
  apiListCases,
  apiProcessSource,
  apiUploadSource,
  type CaseRead,
  type SourceProcessResult,
  type SourceUploadResult,
} from "../services/api";
import {
  analyzeFile,
  detectSourceType,
  formatBytes,
  SOURCE_TYPES,
  type FileAnalysis,
  type SourceType,
} from "../services/intake";
import { DEMO_FILES } from "../data/demoCorpus";
import { prototypeCases } from "../data/prototypeCase";

interface QueueItem {
  id: string;
  file: File;
  analysis: FileAnalysis | null;
  state: "pending" | "analyzing" | "ready" | "error";
  sourceType: SourceType;
  uploaded?: SourceUploadResult;
  processed?: SourceProcessResult;
  error?: string;
}

interface CaseTotal {
  total: number;
  limit: number;
  offset: number;
  items: CaseRead[];
}

const PROCESS_STAGES = [
  "UPLOAD",
  "VALIDATE",
  "PARSE",
  "EXTRACT ENTITIES",
  "BUILD RELATIONSHIPS",
  "PERSIST",
  "GRAPH UPDATE",
  "ANALYTICS",
  "DETECT ANOMALIES",
  "ACTIONABLE OUTPUT",
  "READY",
];

const prototypeCaseReads: CaseRead[] = prototypeCases.map((item, index) => ({
  id: index + 1,
  case_number: item.caseId,
  title: item.title,
  description: item.title,
  status: item.status,
  priority: item.priority,
  created_at: item.lastActivity,
  updated_at: item.lastActivity,
}));

export function CaseIntakePage() {
  const backend = useBackendStore((s) => s.mode);
  const refreshGraph = useBackendStore((s) => s.refreshGraph);
  const [cases, setCases] = useState<CaseRead[]>([]);
  const [selectedCase, setSelectedCase] = useState<string>("");
  const [creating, setCreating] = useState(false);
  const [newCase, setNewCase] = useState({ case_number: "", title: "", description: "", priority: "MEDIUM", status: "OPEN" });
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [stage, setStage] = useState<string>("");
  const [results, setResults] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const nextId = useRef(1);

  useEffect(() => {
    if (backend !== "backend") {
      setCases(prototypeCaseReads);
      setSelectedCase((prev) => prev || prototypeCaseReads[0]?.case_number || "");
      return;
    }
    apiListCases({ limit: 100 })
      .then((res: CaseTotal) => {
        setCases(res.items);
        setSelectedCase((prev) => prev || res.items[0]?.case_number || "");
      })
      .catch(() => {
        setCases(prototypeCaseReads);
        setSelectedCase((prev) => prev || prototypeCaseReads[0]?.case_number || "");
      });
  }, [backend]);

  const selectedCaseRead = useMemo(() => cases.find((c) => c.case_number === selectedCase) ?? null, [cases, selectedCase]);

  const addFiles = (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    nextId.current += 1;
    const batchId = nextId.current;
    const items: QueueItem[] = list.map((f) => ({
      id: `Q-${batchId}-${f.name}`,
      file: f,
      analysis: null,
      state: "pending",
      sourceType: detectSourceType(f.name),
    }));
    setQueue((q) => [...q, ...items]);
    list.forEach((file, i) => {
      const id = items[i].id;
      setQueue((q) => q.map((x) => (x.id === id ? { ...x, state: "analyzing" } : x)));
      analyzeFile(file, items[i].sourceType)
        .then((analysis) =>
          setQueue((q) =>
            q.map((x) =>
              x.id === id
                ? { ...x, analysis, state: analysis.errors.length ? "error" : "ready", sourceType: analysis.sourceType }
                : x,
            ),
          ),
        )
        .catch((e) =>
          setQueue((q) =>
            q.map((x) => (x.id === id ? { ...x, state: "error", error: e instanceof Error ? e.message : "Parsing failed" } : x)),
          ),
        );
    });
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files?.length) addFiles(e.dataTransfer.files);
  };

  const removeFile = (id: string) => setQueue((q) => q.filter((x) => x.id !== id));

  const createCaseFlow = async () => {
    if (backend !== "backend") {
      setError("Live backend access is required to create a case. Sign in instead of using Offline Demo Mode.");
      return;
    }
    if (!newCase.title.trim()) {
      setError("Enter a case name to create an investigation.");
      return;
    }
    setError(null);
    setCreating(true);
    try {
      const c = await apiCreateCase({
        title: newCase.title,
        case_number: newCase.case_number || undefined,
        description: newCase.description || undefined,
        status: newCase.status,
        priority: newCase.priority,
      });
      setCases((prev) => [c, ...prev.filter((x) => x.case_number !== c.case_number)]);
      setSelectedCase(c.case_number);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create case.");
    } finally {
      setCreating(false);
    }
  };

  const runProcess = async () => {
    if (!selectedCase) {
      setError("Select or create an investigation first.");
      return;
    }
    setError(null);
    setProcessing(true);
    setResults(null);
    setStage(PROCESS_STAGES[0]);
    try {
      if (backend === "backend") {
        // REAL pipeline: upload each ready file, then process each source.
        const ready = queue.filter((q) => q.analysis && !q.analysis.errors.length);
        if (!ready.length) {
          setError("No valid files to process. Fix or remove errored files first.");
          setProcessing(false);
          return;
        }
        const uploads: SourceUploadResult[] = [];
        for (const item of ready) {
          setStage("UPLOAD");
          const up = await apiUploadSource(selectedCase, item.file, item.sourceType);
          setQueue((q) => q.map((x) => (x.id === item.id ? { ...x, uploaded: up } : x)));
          uploads.push(up);
        }
        setStage("PERSIST");
        const processed: SourceProcessResult[] = [];
        for (const up of uploads) {
          if (up.status === "ERROR") continue;
          const res = await apiProcessSource(selectedCase, up.source_id);
          setQueue((q) => q.map((x) => (x.uploaded?.source_id === up.source_id ? { ...x, processed: res } : x)));
          processed.push(res);
        }
        setStage("GRAPH UPDATE");
        await refreshGraph();
        let alertsCreated = 0;
        try {
          const res = await apiGenerateAlerts(selectedCase);
          alertsCreated = res.created;
        } catch { /* alert generation is best-effort */ }
        setStage("READY");
        const entities = processed.reduce((s, r) => s + Number(r.metrics.entities_persisted ?? 0), 0);
        const relationships = processed.reduce((s, r) => s + Number(r.metrics.relationships_persisted ?? 0), 0);
        const processedBySource = new Map(processed.map((item) => [item.source_id, item]));
        setResults({
          mode: "live",
          sources: uploads.length,
          processed: processed.length,
          records: processed.reduce((s, r) => s + r.record_count, 0),
          entities,
          relationships,
          alerts_created: alertsCreated,
          extraction_provider: processed.find((item) => item.metrics.extraction_provider)?.metrics.extraction_provider ?? "deterministic",
          uploads: uploads.map((u) => ({
            source_id: u.source_id,
            filename: u.filename,
            status: processedBySource.get(u.source_id)?.status ?? u.status,
            format: u.format,
            quality: u.quality,
            error: u.error,
          })),
        });
      } else {
        // Offline demo mode: local analysis only — never fake a backend write.
        setStage("");
        setError("Backend offline. Files are analyzed locally; start the API and re-run to persist them.");
        setResults(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Processing failed.");
      setStage("");
    } finally {
      setProcessing(false);
    }
  };

  const importDemo = () => {
    // Real corpus files pushed through the same pipeline (upload -> parse -> process).
    const files = DEMO_FILES.map((d) => new File([d.content], d.name, { type: d.mime }));
    addFiles(files);
  };

  const quality = useMemo(() => {
    const ready = queue.filter((q) => q.analysis);
    const total = ready.reduce((s, q) => s + (q.analysis?.recordCount ?? 0), 0);
    const valid = ready.reduce((s, q) => s + (q.analysis?.valid ?? 0), 0);
    const invalid = ready.reduce((s, q) => s + (q.analysis?.invalid ?? 0), 0);
    const dups = ready.reduce((s, q) => s + (q.analysis?.duplicates ?? 0), 0);
    const missing = ready.reduce((s, q) => s + (q.analysis?.missing ?? 0), 0);
    const qualityPct = total ? Math.round(((valid - dups) / total) * 1000) / 10 : 0;
    return { total, valid, invalid, dups, missing, qualityPct };
  }, [queue]);

  return (
    <HudPage
      title="CASE INTAKE"
      subtitle="Import and prepare investigation data for analysis"
      rightMeta={<>{selectedCase ? <div>{selectedCase}</div> : <div>NO CASE SELECTED</div>}</>}
    >
      <div style={{ display: "grid", gap: 16 }}>
        {/* ---- Case selection / creation ---- */}
        <HudCard label="Investigation" title="Select or create a case">
          <div className="filters hud-filters">
            <select
              className="control hud-search"
              value={selectedCase}
              onChange={(e) => setSelectedCase(e.target.value)}
              aria-label="Select investigation"
            >
              <option value="">— Select investigation —</option>
              {cases.map((c) => (
                <option key={c.case_number} value={c.case_number}>
                  {c.case_number} · {c.title}
                </option>
              ))}
            </select>
            {selectedCaseRead && (
              <span className="glass-strip">{selectedCaseRead.status} · {selectedCaseRead.priority}</span>
            )}
          </div>
          <div className="stack" style={{ marginTop: 10 }}>
            <div className="meta" style={{ marginBottom: 4 }}>New investigation</div>
            <div className="panel" style={{ display: "grid", gridTemplateColumns: "1fr 1.4fr", gap: 10, padding: 12 }}>
              <input className="control hud-search" placeholder="Case ID (e.g. CASE-2026-XXXX)" value={newCase.case_number} onChange={(e) => setNewCase({ ...newCase, case_number: e.target.value })} aria-label="Case ID" />
              <input className="control hud-search" placeholder="Case name" value={newCase.title} onChange={(e) => setNewCase({ ...newCase, title: e.target.value })} aria-label="Case name" />
              <input className="control hud-search" placeholder="Description (optional)" style={{ gridColumn: "1 / -1" }} value={newCase.description} onChange={(e) => setNewCase({ ...newCase, description: e.target.value })} aria-label="Description" />
              <div style={{ display: "flex", gap: 8, gridColumn: "1 / -1" }}>
                <select className="control hud-search" value={newCase.priority} onChange={(e) => setNewCase({ ...newCase, priority: e.target.value })} aria-label="Priority">
                  {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((p) => <option key={p}>{p}</option>)}
                </select>
                <select className="control hud-search" value={newCase.status} onChange={(e) => setNewCase({ ...newCase, status: e.target.value })} aria-label="Status">
                  {["OPEN", "IN_PROGRESS", "CLOSED", "ARCHIVED"].map((s) => <option key={s}>{s}</option>)}
                </select>
                <button className="cta" onClick={createCaseFlow} disabled={creating || backend !== "backend"}>
                  {creating ? "CREATING..." : backend === "backend" ? "CREATE CASE" : "SIGN IN TO CREATE"}
                </button>
              </div>
            </div>
            {backend !== "backend" && <div className="meta" style={{ marginTop: 8 }}>Offline demo is view-only. Sign in to persist new cases and uploaded sources.</div>}
          </div>
        </HudCard>

        {error && <HudCard label="Error" title="Unable to proceed"><div className="meta">{error}</div></HudCard>}

        {/* ---- Upload dropzone ---- */}
        <input ref={fileInputRef} type="file" multiple accept=".csv,.tsv,.txt,.json,.xlsx" style={{ display: "none" }} aria-label="Upload case data files" onChange={(e) => e.target.files && addFiles(e.target.files)} />
        <HudCard label="Upload" title="Drop case data here">
          <div
            role="button"
            tabIndex={0}
            aria-label="Dropzone - browse or drop files"
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && fileInputRef.current?.click()}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
            style={{
              border: `1px dashed ${dragOver ? "rgba(63,115,255,.7)" : "rgba(87,116,220,.3)"}`,
              borderRadius: 12, padding: 28, textAlign: "center", cursor: "pointer",
              background: dragOver ? "rgba(63,115,255,.08)" : "transparent", transition: "background .15s, border-color .15s",
            }}
          >
            <div className="brand" style={{ fontSize: 26 }}>↑</div>
            <div>Drag &amp; drop files, or click to browse</div>
            <div className="meta">CSV · TSV · TXT · JSON · XLSX (multi-select supported)</div>
            <div className="hud-search-hints" style={{ marginTop: 10 }}>
              {SOURCE_TYPES.map((s) => (
                <button key={s.id} className="pill" type="button" onClick={(e) => e.stopPropagation()} title="Source type">{s.label}</button>
              ))}
            </div>
          </div>
        </HudCard>

        {/* ---- File queue ---- */}
        {queue.length > 0 && (
          <HudCard label="Upload queue" title="Imported files">
            <div className="stack">
              {queue.map((item) => (
                <div key={item.id} className="entity entity-tight">
                  <div>
                    <div>{item.analysis?.filename ?? "analyzing..."}</div>
                    <div className="meta">
                      {item.analysis ? (
                        <>
                          {item.analysis.sourceType} · {item.analysis.format} · {formatBytes(item.analysis.size)} · {item.analysis.recordCount} records
                          {item.analysis.errors.length ? ` · ${item.analysis.errors.join("; ")}` : ""}
                        </>
                      ) : (
                        item.state === "analyzing" ? "Analyzing..." : "Pending"
                      )}
                    </div>
                  </div>
                  <div className="risk">{item.processed ? `PROCESSED · ${item.processed.record_count} rec` : item.uploaded ? `${item.uploaded.status} · ${item.uploaded.quality.quality_score ?? 0}%` : item.analysis?.quality != null ? `${item.analysis.quality}%` : "..."}</div>
                  <button className="pill" onClick={() => removeFile(item.id)}>Remove</button>
                </div>
              ))}
            </div>
          </HudCard>
        )}

        {/* ---- Data quality panel ---- */}
        {queue.some((q) => q.analysis) && (
          <HudCard label="Data quality" title="Dataset summary">
            <HoloList
              items={[
                { label: "Total files", value: String(queue.filter((q) => q.analysis).length) },
                { label: "Total records", value: quality.total.toLocaleString() },
                { label: "Valid records", value: quality.valid.toLocaleString() },
                { label: "Invalid records", value: quality.invalid.toLocaleString() },
                { label: "Duplicates", value: quality.dups.toLocaleString() },
                { label: "Missing fields", value: quality.missing.toLocaleString() },
                { label: "Data quality", value: `${quality.qualityPct}%` },
              ]}
            />
          </HudCard>
        )}

        {/* ---- Process + results ---- */}
        <HudCard label="Pipeline" title="Process case data">
          <div className="filters hud-filters">
            <button className="cta" onClick={runProcess} disabled={processing || !selectedCase || queue.length === 0 || backend !== "backend"}>
              {processing ? "PROCESSING..." : backend === "backend" ? "PROCESS CASE DATA" : "SIGN IN TO PROCESS"}
            </button>
            <button className="pill" onClick={importDemo} disabled={processing}>IMPORT DEMO CASE (CDR)</button>
          </div>
          {stage && (
            <div className="mini-list compact-feed" style={{ marginTop: 10 }}>
              {PROCESS_STAGES.map((s) => (
                <div key={s} className="entity feed-row">
                  <span className={stage === s ? "risk" : "meta"}>
                    {PROCESS_STAGES.indexOf(stage) > PROCESS_STAGES.indexOf(s) ? "✓" : stage === s ? "◉" : "○"} {s}
                  </span>
                </div>
              ))}
            </div>
          )}
        </HudCard>

        {/* ---- Processing results (real) ---- */}
        {results && (
          <>
            <HudCard label="Ingestion" title="Pipeline result">
              {results.mode === "live" ? (
                <HoloList
                  items={[
                    { label: "Sources uploaded", value: String(results.sources) },
                    { label: "Sources processed", value: String(results.processed) },
                    { label: "Total records", value: Number(results.records).toLocaleString() },
                    { label: "Entities persisted", value: Number(results.entities).toLocaleString() },
                    { label: "Relationships persisted", value: Number(results.relationships).toLocaleString() },
                    { label: "Alert indicators", value: String(results.alerts_created ?? 0) },
                    { label: "Extraction provider", value: String(results.extraction_provider ?? "deterministic") },
                  ]}
                />
              ) : null}
              <div className="hud-search-hints" style={{ marginTop: 10 }}>
                {(results.uploads as { source_id: string; filename: string; status: string; quality: { quality_score?: number } }[]).map((u) => (
                  <span key={u.source_id} className="glass-strip">
                    {u.filename} → {u.status} · quality {u.quality?.quality_score ?? 0}%
                  </span>
                ))}
              </div>
            </HudCard>
          </>
        )}

        {/* ---- Empty state ---- */}
        {!queue.length && !results && (
          <HudCard label="State" title="No case data">
            <div className="meta">Upload FIRs, CDRs, transaction records or other investigation data to begin analysis.</div>
            <div className="filters hud-filters" style={{ marginTop: 10 }}>
              <button className="cta" onClick={() => fileInputRef.current?.click()}>UPLOAD DATA</button>
            </div>
          </HudCard>
        )}
      </div>
    </HudPage>
  );
}
