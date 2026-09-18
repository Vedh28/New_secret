/**
 * CASE INTAKE — real client-side file analysis.
 *
 * No fake parsing: CSV/JSON/TSV are actually parsed; records are actually
 * counted, validated, deduped and quality-scored. Unsupported formats report
 * UNSUPPORTED instead of pretending to work.
 */

export type SourceType =
  | "FIR"
  | "CDR"
  | "TRANSACTION"
  | "VEHICLE"
  | "SURVEILLANCE"
  | "INTELLIGENCE"
  | "CRIMINAL_HISTORY"
  | "LOCATION"
  | "SOCIAL"
  | "OTHER";

export const SOURCE_TYPES: { id: SourceType; label: string; match: RegExp }[] = [
  { id: "FIR", label: "FIR / Reports", match: /fir|report|police|complaint/i },
  { id: "CDR", label: "CDR / Communications", match: /cdr|call|phone|communication/i },
  { id: "TRANSACTION", label: "Transactions", match: /txn|trans|payment|bank|finance|ledger|amount/i },
  { id: "VEHICLE", label: "Vehicle Records", match: /veh|vehicle|reg|plate|chassis/i },
  { id: "SURVEILLANCE", label: "Surveillance", match: /surv|cctv|watch|monitor|camera/i },
  { id: "INTELLIGENCE", label: "Intelligence Reports", match: /intel|intelligence|info|brief/i },
  { id: "CRIMINAL_HISTORY", label: "Criminal History", match: /criminal|history|conviction|bail|custody/i },
  { id: "LOCATION", label: "Location Data", match: /loc|geo|coordinate|sector|position/i },
  { id: "SOCIAL", label: "Social Intelligence", match: /social|post|message|chat|media/i },
];

export const SUPPORTED_EXT = ["csv", "tsv", "txt", "json"];

export interface FileAnalysis {
  filename: string;
  ext: string;
  size: number;
  format: "CSV" | "TSV" | "JSON" | "TEXT" | "UNSUPPORTED";
  sourceType: SourceType;
  columns: string[];
  recordCount: number;
  valid: number;
  invalid: number;
  duplicates: number;
  missing: number;
  quality: number;
  errors: string[];
}

export function detectSourceType(filename: string): SourceType {
  const lower = `${filename}`.toLowerCase();
  for (const s of SOURCE_TYPES) {
    if (s.match.test(lower)) return s.id;
  }
  return "OTHER";
}

export function detectFormat(filename: string, size: number): FileAnalysis["format"] {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (!SUPPORTED_EXT.includes(ext)) return "UNSUPPORTED";
  if (ext === "csv") return "CSV";
  if (ext === "tsv") return "TSV";
  if (ext === "json") return "JSON";
  return "TEXT";
}

function parseDelimited(content: string, delim: string): { headers: string[]; rows: string[][] } {
  const lines = content.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (!lines.length) return { headers: [], rows: [] };
  const headers = lines[0].split(delim).map((h) => h.trim());
  const rows = lines.slice(1).map((l) => l.split(delim).map((c) => c.trim()));
  return { headers, rows };
}

export async function analyzeFile(file: File, sourceTypeOverride?: SourceType): Promise<FileAnalysis> {
  const filename = file.name;
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const size = file.size;
  const format = detectFormat(filename, size);
  const base: FileAnalysis = {
    filename,
    ext,
    size,
    format,
    sourceType: sourceTypeOverride ?? detectSourceType(filename),
    columns: [],
    recordCount: 0,
    valid: 0,
    invalid: 0,
    duplicates: 0,
    missing: 0,
    quality: 0,
    errors: [],
  };

  if (format === "UNSUPPORTED") {
    base.errors.push(`Unsupported format (.${ext}). Supported: ${SUPPORTED_EXT.join(", ")}.`);
    return base;
  }

  const raw = await file.text();
  if (!raw.trim()) {
    base.errors.push("File is empty.");
    return base;
  }

  if (format === "JSON") {
    try {
      const data = JSON.parse(raw) as unknown;
      const arr: Record<string, unknown>[] = (Array.isArray(data) ? data : (data as { records?: Record<string, unknown>[] }).records) ?? [];
      base.columns = arr.length ? Object.keys(arr[0]) : [];
      base.recordCount = arr.length;
      base.valid = arr.filter((r) => r && Object.keys(r).length > 0).length;
      base.invalid = base.recordCount - base.valid;
      const seen = new Set(arr.map((r) => JSON.stringify(r)));
      base.duplicates = arr.length - seen.size;
    } catch {
      base.errors.push("Malformed JSON file.");
      base.format = "TEXT";
    }
  } else if (format === "CSV" || format === "TSV") {
    const delim = format === "TSV" ? "\t" : ",";
    const { headers, rows } = parseDelimited(raw, delim);
    base.columns = headers;
    base.recordCount = rows.length;
    const seen = new Set<string>();
    for (const row of rows) {
      const key = JSON.stringify(row);
      if (seen.has(key)) base.duplicates += 1;
      seen.add(key);
      const missingCells = row.filter((c) => c === "" || c == null).length;
      base.missing += missingCells;
      if (row.some((c) => c !== "") && row.length === headers.length) base.valid += 1;
      else base.invalid += 1;
    }
    if (!headers.length || rows.some((r) => r.length !== headers.length)) {
      base.errors.push("Detected rows with mismatched column counts.");
    }
  } else {
    // TEXT
    base.recordCount = raw.split(/\r?\n/).filter((l) => l.trim()).length;
    base.valid = base.recordCount;
  }

  base.quality = base.recordCount
    ? Math.round(((base.valid - base.duplicates - base.invalid) / base.recordCount) * 1000) / 10
    : 0;
  return base;
}

export function formatBytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(2)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}
