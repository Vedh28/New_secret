/**
 * SECRET frontend API client (Phase 7).
 *
 * Thin typed wrapper over the FastAPI backend. Exposes the endpoints the frozen
 * UI consumes (auth, graph, criminals, cases) and centralizes the auth token.
 *
 * The backend base URL can be overridden via `VITE_API_URL` (defaults to the
 * local FastAPI dev server on :8000).
 */

export const API_BASE_URL =
  (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

let accessToken: string | null = localStorage.getItem("secret.access_token");

export function setAccessToken(token: string | null): void {
  accessToken = token;
  if (token) localStorage.setItem("secret.access_token", token);
  else localStorage.removeItem("secret.access_token");
}

export function getAccessToken(): string | null {
  return accessToken;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (accessToken) {
    headers.Authorization = `Bearer ${accessToken}`;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(0, `Backend unreachable at ${API_BASE_URL}`);
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// --- Types (mirror the backend Pydantic schemas) ----------------------------

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface UserRead {
  id: number;
  username: string;
  email: string;
  full_name?: string | null;
  role: string;
  status: string;
  created_at: string;
  last_login_at?: string | null;
}

export interface GraphNode {
  id: string;
  type: string;
  name: string;
  properties: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  properties: Record<string, unknown>;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface CriminalProfile {
  id: number;
  secret_id: string;
  profile_type: string;
  name: string;
  aliases: string[];
  risk_score: number;
  risk_level: string;
  confidence: number;
  status: string;
  attributes: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CriminalList {
  total: number;
  limit: number;
  offset: number;
  items: CriminalProfile[];
}

export interface CaseRead {
  id: number;
  case_number: string;
  title: string;
  description?: string | null;
  status: string;
  priority: string;
  created_at: string;
  updated_at: string;
  closed_at?: string | null;
}

export interface CaseList {
  total: number;
  limit: number;
  offset: number;
  items: CaseRead[];
}

// --- Auth -------------------------------------------------------------------

export async function apiLogin(username: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password } satisfies LoginRequest),
  });
}

export async function apiMe(): Promise<UserRead> {
  return request<UserRead>("/api/v1/auth/me");
}

// --- Graph ------------------------------------------------------------------

export async function apiGetNetwork(params: {
  node_types?: string[];
  rel_types?: string[];
  limit?: number;
} = {}): Promise<GraphResponse> {
  const search = new URLSearchParams();
  params.node_types?.forEach((t) => search.append("node_types", t));
  params.rel_types?.forEach((t) => search.append("rel_types", t));
  if (params.limit) search.append("limit", String(params.limit));
  const qs = search.toString();
  return request<GraphResponse>(`/api/v1/graph/network${qs ? `?${qs}` : ""}`);
}

export async function apiGetEntity(entityId: string): Promise<GraphNode> {
  return request<GraphNode>(`/api/v1/graph/entities/${encodeURIComponent(entityId)}`);
}

// --- Criminals --------------------------------------------------------------

export async function apiListCriminals(params: {
  q?: string;
  profile_type?: string;
  skip?: number;
  limit?: number;
} = {}): Promise<CriminalList> {
  const search = new URLSearchParams();
  if (params.q) search.append("q", params.q);
  if (params.profile_type) search.append("profile_type", params.profile_type);
  if (params.skip) search.append("skip", String(params.skip));
  if (params.limit) search.append("limit", String(params.limit));
  const qs = search.toString();
  return request<CriminalList>(`/api/v1/criminals${qs ? `?${qs}` : ""}`);
}

// --- Cases ------------------------------------------------------------------

export async function apiListCases(params: {
  q?: string;
  status?: string;
  priority?: string;
  limit?: number;
} = {}): Promise<CaseList> {
  const search = new URLSearchParams();
  if (params.q) search.append("q", params.q);
  if (params.status) search.append("status", params.status);
  if (params.priority) search.append("priority", params.priority);
  if (params.limit) search.append("limit", String(params.limit));
  const qs = search.toString();
  return request<CaseList>(`/api/v1/cases${qs ? `?${qs}` : ""}`);
}

export interface CaseCreateInput {
  title: string;
  case_number?: string;
  description?: string;
  status?: string;
  priority?: string;
}

export async function apiCreateCase(input: CaseCreateInput): Promise<CaseRead> {
  return request<CaseRead>("/api/v1/cases", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

// --- Case data sources + ingestion (Phase 15 intake) -------------------------

export interface SourceRead {
  id: number;
  source_id: string;
  filename: string;
  file_type?: string | null;
  source_type?: string | null;
  status: string;
  record_count?: number | null;
  processing_error?: string | null;
  metadata_json: Record<string, unknown>;
  uploaded_at: string;
  processed_at?: string | null;
}

export interface SourceUploadResult {
  source_id: string;
  filename: string;
  case_id: number;
  format: string;
  status: string;
  record_count: number;
  quality: Record<string, unknown>;
  error: string | null;
}

export interface SourceProcessResult {
  source_id: string;
  filename: string;
  case_id: number;
  status: string;
  record_count: number;
  metrics: Record<string, unknown>;
}

export async function apiListSources(caseKey: string): Promise<SourceRead[]> {
  return request<SourceRead[]>(`/api/v1/cases/${encodeURIComponent(caseKey)}/sources`);
}

export async function apiUploadSource(
  caseKey: string,
  file: File,
  sourceType: string,
): Promise<SourceUploadResult> {
  const form = new FormData();
  form.append("file", file);
  form.append("source_type", sourceType);
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/cases/${encodeURIComponent(caseKey)}/sources/upload`, {
      method: "POST",
      headers,
      body: form,
    });
  } catch {
    throw new ApiError(0, `Backend unreachable at ${API_BASE_URL}`);
  }
  if (!response.ok) {
    let detail = `Upload failed (${response.status})`;
    try {
      const body = await response.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch { /* ignore */ }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as SourceUploadResult;
}

export async function apiProcessSource(caseKey: string, sourceId: string): Promise<SourceProcessResult> {
  return request<SourceProcessResult>(
    `/api/v1/cases/${encodeURIComponent(caseKey)}/sources/${encodeURIComponent(sourceId)}/process`,
    { method: "POST" },
  );
}

export async function apiDeleteSource(caseKey: string, sourceId: string): Promise<void> {
  return request<void>(`/api/v1/cases/${encodeURIComponent(caseKey)}/sources/${encodeURIComponent(sourceId)}`, {
    method: "DELETE",
  });
}

// --- Persisted case entities + relationships (ingestion read-back) -----------

export interface EntityRead {
  entity_id: string;
  entity_type: string;
  name: string;
  confidence: number;
  attributes: Record<string, unknown>;
  source_ids: string[];
  created_at: string;
}

export interface RelationshipRead {
  rel_type: string;
  source_id: string;
  target_id: string;
  confidence: number;
  source_ids: string[];
  attributes: Record<string, unknown>;
  created_at: string;
}

export async function apiListCaseEntities(caseKey: string): Promise<EntityRead[]> {
  return request<EntityRead[]>(`/api/v1/cases/${encodeURIComponent(caseKey)}/entities`);
}

export async function apiListCaseRelationships(caseKey: string): Promise<RelationshipRead[]> {
  return request<RelationshipRead[]>(`/api/v1/cases/${encodeURIComponent(caseKey)}/relationships`);
}

/** Case-scoped network graph: only the selected case's entities + relationships. */
export async function apiCaseGraph(caseKey: string): Promise<GraphResponse> {
  return request<GraphResponse>(`/api/v1/cases/${encodeURIComponent(caseKey)}/graph`);
}

// --- Evidence integrity / blockchain ledger (integrity layer) ---------------

export interface IntegrityEvent {
  transaction_id: string;
  case_id: string;
  event_type: string;
  entity_type: string | null;
  entity_id: string | null;
  payload_hash: string;
  payload_json: Record<string, unknown>;
  block_index: number | null;
  block_hash: string | null;
  previous_block_hash: string | null;
  actor_id: number | null;
  status: string;
  created_at: string;
}

export interface IntegrityBlock {
  index: number;
  timestamp: string;
  previous_hash: string;
  data_hash: string;
  block_hash: string;
  case_id: string;
  events: Record<string, unknown>[];
}

export interface IntegritySummary {
  case_id: string;
  chain_status: "VALID" | "WARNING" | "MISMATCH" | "UNAVAILABLE";
  chain_valid: boolean;
  blocks: number;
  events: number;
  evidence_registered: number;
  evidence_verified: number;
  mismatches: number;
  verified_snapshots: number;
  verified_reports: number;
  latest_block: IntegrityBlock | null;
  issues?: string[];
}

export interface EvidenceIntegrityInfo {
  case_id: string;
  source_id: string;
  evidence_hash: string;
  content_hash: string;
  hash_algorithm: string;
  version: number;
  status: string;
  transaction_id: string | null;
  block_index: number | null;
  created_at: string;
}

export interface RecordVerification {
  verified: boolean;
  status: string;
  record_hash?: string;
  merkle_root?: string | null;
  record_count?: number;
  transaction_id?: string | null;
  block_index?: number | null;
  reason?: string;
  versions?: unknown[];
}

export async function apiIntegritySummary(caseKey: string): Promise<IntegritySummary> {
  return request<IntegritySummary>(`/api/v1/integrity/${encodeURIComponent(caseKey)}`);
}

export async function apiIntegrityEvents(caseKey: string): Promise<{ case_id: string; events: IntegrityEvent[]; pending: number }> {
  return request(`/api/v1/integrity/${encodeURIComponent(caseKey)}/events`);
}

export async function apiIntegrityLedger(caseKey: string): Promise<{ case_id: string; blocks: IntegrityBlock[] }> {
  return request(`/api/v1/integrity/${encodeURIComponent(caseKey)}/ledger`);
}

export async function apiEvidenceIntegrity(caseKey: string, sourceId: string): Promise<RecordVerification> {
  return request(`/api/v1/integrity/${encodeURIComponent(caseKey)}/evidence/${encodeURIComponent(sourceId)}`);
}

export async function apiEvidenceHistory(caseKey: string, sourceId: string): Promise<{ case_id: string; source_id: string; versions: EvidenceIntegrityInfo[] }> {
  return request(`/api/v1/integrity/${encodeURIComponent(caseKey)}/evidence/${encodeURIComponent(sourceId)}/history`);
}

export async function apiVerifyIntegrity(caseKey: string): Promise<{
  case_id: string;
  chain_status: string;
  chain_valid: boolean;
  blocks: number;
  evidence_checked: number;
  evidence_verified: number;
  mismatches: unknown[];
}> {
  return request(`/api/v1/integrity/${encodeURIComponent(caseKey)}/verify`, { method: "POST" });
}

export async function apiVerifyEvidence(caseKey: string, sourceId: string): Promise<RecordVerification> {
  return request(`/api/v1/integrity/${encodeURIComponent(caseKey)}/verify/evidence/${encodeURIComponent(sourceId)}`, { method: "POST" });
}

export async function apiVerifyRecord(caseKey: string, sourceId: string, recordId: string): Promise<RecordVerification> {
  return request(`/api/v1/integrity/${encodeURIComponent(caseKey)}/verify/record/${encodeURIComponent(sourceId)}/${encodeURIComponent(recordId)}`, { method: "POST" });
}

export async function apiVerifyReport(caseKey: string, reportId: string): Promise<RecordVerification> {
  return request(`/api/v1/integrity/${encodeURIComponent(caseKey)}/verify/report/${encodeURIComponent(reportId)}`, { method: "POST" });
}

export async function apiVerifyIntelligence(caseKey: string): Promise<RecordVerification> {
  return request(`/api/v1/integrity/${encodeURIComponent(caseKey)}/verify/intelligence`, { method: "POST" });
}

export async function apiMaterializeGraph(): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/api/v1/graph/materialize", { method: "POST" });
}

// --- Per-case analysis (comms / transactions / timeline / locations) ---------

export interface CommsResponse {
  total_communications: number;
  top_contacts: { entity_id: string; count: number }[];
  flows: { source: string; target: string; count: number }[];
  bursts: { entity_id: string; window: string; count: number }[];
}

export interface TransResponse {
  total_transactions: number;
  total_amount: number;
  flows: { source: string; target: string; count: number; total_amount: number }[];
  top_senders: { account_id: string; total_amount: number; count: number }[];
}

export interface TimelineEvent {
  timestamp: string;
  record_id: string;
  source_id: string;
  summary: string;
  location: string | null;
}

export interface LocationsResponse {
  locations: { name: string; observations: number }[];
  visits: { location: string; entity_id: string; latitude?: string; longitude?: string; observations: number;
            linked_entity_id?: string; linked_entity_name?: string }[];
}

export async function apiCaseCommunications(caseKey: string): Promise<CommsResponse> {
  return request<CommsResponse>(`/api/v1/cases/${encodeURIComponent(caseKey)}/communications`);
}

export async function apiCaseTransactions(caseKey: string): Promise<TransResponse> {
  return request<TransResponse>(`/api/v1/cases/${encodeURIComponent(caseKey)}/transactions`);
}

export async function apiCaseTimeline(caseKey: string): Promise<TimelineEvent[]> {
  return request<TimelineEvent[]>(`/api/v1/cases/${encodeURIComponent(caseKey)}/timeline`);
}

export async function apiCaseLocations(caseKey: string): Promise<LocationsResponse> {
  return request<LocationsResponse>(`/api/v1/cases/${encodeURIComponent(caseKey)}/locations`);
}

// --- Alerts (Phase 18) -------------------------------------------------------

export interface AlertRead {
  id: number;
  case_id: number | string | null;
  profile_id: number | null;
  severity: string;
  status: string;
  title: string;
  description: string | null;
  score: number;
  confidence: number;
  source_ids: string[];
  reviewed_by: number | null;
  reviewed_at: string | null;
  created_at: string;
}

export async function apiCaseAlerts(caseKey: string): Promise<AlertRead[]> {
  return request<AlertRead[]>(`/api/v1/cases/${encodeURIComponent(caseKey)}/alerts`);
}

export async function apiGenerateAlerts(caseKey: string): Promise<{ created: number; alerts: AlertRead[] }> {
  return request<{ created: number; alerts: AlertRead[] }>(
    `/api/v1/cases/${encodeURIComponent(caseKey)}/alerts/generate`,
    { method: "POST" },
  );
}

export async function apiUpdateAlert(caseKey: string, alertId: number, status: string): Promise<AlertRead> {
  return request<AlertRead>(`/api/v1/cases/${encodeURIComponent(caseKey)}/alerts/${alertId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

// --- Reports (Phase 9) -------------------------------------------------------

export interface ReportResponse {
  id: string;
  report_type: string;
  title: string;
  generated_at: string;
  generated_by: string;
  sections: { heading: string; body: string[] }[];
  artifact: string;
  artifact_mime: string;
}

export interface ReportMeta {
  id: string;
  report_type: string;
  title: string;
  generated_at: string;
  generated_by: string;
  sections: number;
}

export async function apiGenerateReport(payload: {
  report_type: string;
  case_number?: string;
  entity_id?: string;
  title?: string;
}): Promise<ReportResponse> {
  return request<ReportResponse>("/api/v1/reports/generate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function apiListReports(): Promise<ReportMeta[]> {
  return request<ReportMeta[]>("/api/v1/reports");
}

export async function apiGetReport(reportId: string): Promise<ReportResponse> {
  return request<ReportResponse>(`/api/v1/reports/${encodeURIComponent(reportId)}`);
}

export function downloadReport(report: ReportResponse): void {
  const bytes = Uint8Array.from(atob(report.artifact), (c) => c.charCodeAt(0));
  const blob = new Blob([bytes], { type: report.artifact_mime || "application/pdf" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${report.title || "report"}.pdf`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// --- Dashboard (Command Center) ----------------------------------------------

export interface DashboardSummary {
  cases: number;
  criminals: number;
  entities: number;
  relationships: number;
  sources: number;
  alerts: number;
  anomaly_signals: number;
  priority_distribution: Record<string, number>;
}

export async function apiDashboardSummary(): Promise<DashboardSummary> {
  return request<DashboardSummary>("/api/v1/dashboard/summary");
}

// --- Graph communities (cluster count for Network Intelligence) ---------------

export interface CommunityResult {
  community_id: number;
  size: number;
  entities: string[];
}

export interface CommunityResponse {
  communities: CommunityResult[];
  count: number;
  network_density: number;
}

export async function apiCommunities(): Promise<CommunityResponse> {
  return request<CommunityResponse>("/api/v1/graph/analytics/communities");
}

// --- Intelligence layer (Phases 14-17) ---------------------------------------

export interface Anomaly {
  kind: string;
  entity_id: string;
  baseline: number;
  observed: number;
  deviation: number;
  score: number;
  timestamp: string;
  evidence: string[];
  explanation: string;
}

export interface PotentialLink {
  source: string;
  target: string;
  score: number;
  supporting_signals: string[];
  contradictory_signals: string[];
  evidence_ids: string[];
  confidence: number;
  explanation: string;
}

export interface EvidenceGap {
  subject: string;
  known_evidence: string[];
  missing_evidence: string[];
  importance: number;
  recommended_source: string;
  window: string;
  explanation: string;
}

export interface NetworkDNA {
  density: number;
  centralization: number;
  community_count: number;
  clustering: number;
  bridge_dependence: string;
  bridge_ratio: number;
  temporal_volatility: number;
  communication_activity: string;
  transaction_anomaly: string;
  evidence_coverage: number;
  fragmentation: number;
}

export interface PriorityScore {
  subject: string;
  priority: number;
  factors: Record<string, number>;
  explanation: string[];
}

export interface Recommendation {
  kind: string;
  subject: string;
  priority: number;
  info_gain: number;
  reasoning: string[];
  evidence_ids: string[];
  entity_ids: string[];
  recommended_data: string;
  window: string;
}

export interface TemporalChange {
  kind: string;
  source: string;
  target: string;
  window: string;
  before: number;
  after: number;
  score: number;
  explanation: string;
}

export interface IntelEntity {
  id: string;
  type: string;
  name: string;
  aliases?: string[];
  source_ids?: string[];
  confidence?: number;
  metadata?: Record<string, unknown>;
}

export interface IntelRel {
  source: string;
  target: string;
  rel_type: string;
  confidence: number;
  source_ids?: string[];
  first_seen?: string;
  last_seen?: string;
  [key: string]: unknown;
}

export interface IntelEvidence {
  id: string;
  source_type: string;
  source_id: string;
  timestamp?: string;
  entity_ids?: string[];
  summary?: string;
  record_id?: string;
  [key: string]: unknown;
}

export interface CaseIntelligence {
  case_id: number;
  entities: IntelEntity[];
  relationships: IntelRel[];
  evidence: IntelEvidence[];
  evidence_fusion: Record<string, unknown>;
  temporal_changes: TemporalChange[];
  anomalies: Anomaly[];
  potential_links: PotentialLink[];
  link_decisions: Record<string, unknown>;
  evidence_gaps: EvidenceGap[];
  network_dna: NetworkDNA;
  entity_priorities: PriorityScore[];
  relationship_priorities: PriorityScore[];
  recommendations: Recommendation[];
}

export interface LeadRead {
  id: number;
  case_id: number;
  kind: string;
  title: string;
  description: string | null;
  priority: number;
  info_gain: number;
  status: string;
  entity_ids: string[];
  evidence_ids: string[];
  recommended_action: string | null;
  recommended_source: string | null;
  explanation: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface SimulationResult {
  operation: string;
  subject: string;
  before_nodes: number;
  after_nodes: number;
  before_edges: number;
  after_edges: number;
  before_communities: number;
  after_communities: number;
  connectivity_change: number;
  bridge_before: string;
  bridge_after: string;
  affected_communities: number;
  interpretation: string;
  explanation: string;
}

export async function apiCaseIntelligence(caseKey: string): Promise<CaseIntelligence> {
  return request<CaseIntelligence>(`/api/v1/cases/${encodeURIComponent(caseKey)}/intelligence`);
}

export async function apiCaseHiddenLinks(caseKey: string): Promise<PotentialLink[]> {
  return request<PotentialLink[]>(`/api/v1/cases/${encodeURIComponent(caseKey)}/hidden-links`);
}

export async function apiCaseNetworkDNA(caseKey: string): Promise<NetworkDNA> {
  return request<NetworkDNA>(`/api/v1/cases/${encodeURIComponent(caseKey)}/network-dna`);
}

export async function apiSimulate(caseKey: string, operation: string, subject: string): Promise<SimulationResult> {
  return request<SimulationResult>(`/api/v1/cases/${encodeURIComponent(caseKey)}/simulate`, {
    method: "POST",
    body: JSON.stringify({ operation, subject }),
  });
}

// --- Analyst confirmation on potential links (P1.3) --------------------------

export interface LinkDecisionEntry {
  id: number;
  case_id: number;
  entity_a: string;
  entity_b: string;
  previous_status: string;
  new_status: string;
  decision: string;
  analyst_id: number | null;
  evidence_ids: string[];
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export async function apiListLinkDecisions(caseKey: string): Promise<LinkDecisionEntry[]> {
  return request<LinkDecisionEntry[]>(`/api/v1/cases/${encodeURIComponent(caseKey)}/potential-links/decisions`);
}

export async function apiRecordLinkDecision(
  caseKey: string,
  source: string,
  target: string,
  decision: "CONFIRM" | "REJECT" | "DEFER",
  evidence_ids?: string[],
  notes?: string,
): Promise<LinkDecisionEntry> {
  return request<LinkDecisionEntry>(`/api/v1/cases/${encodeURIComponent(caseKey)}/potential-links/decision`, {
    method: "POST",
    body: JSON.stringify({ source, target, decision, evidence_ids: evidence_ids ?? [], notes: notes ?? null }),
  });
}

export async function apiCaseLeads(caseKey: string): Promise<LeadRead[]> {
  return request<LeadRead[]>(`/api/v1/cases/${encodeURIComponent(caseKey)}/leads`);
}

export async function apiCreateLead(caseKey: string, lead: Partial<LeadRead>): Promise<LeadRead> {
  return request<LeadRead>(`/api/v1/cases/${encodeURIComponent(caseKey)}/leads`, {
    method: "POST",
    body: JSON.stringify(lead),
  });
}

export async function apiUpdateLead(caseKey: string, leadId: number, patch: Partial<LeadRead>): Promise<LeadRead> {
  return request<LeadRead>(`/api/v1/cases/${encodeURIComponent(caseKey)}/leads/${leadId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

// --- Analysis: temporal + location (Phase 9) --------------------------------

export interface TimeWindowResult {
  window_start: string;
  count: number;
  sources: string[];
}
export interface EventItem {
  record_id: string;
  timestamp: string;
  source: string;
  summary: string;
  location?: string | null;
}
export interface LocationActivityEntry {
  location: string;
  events: number;
  level: string;
}
export interface TemporalLocationResponse {
  windows: TimeWindowResult[];
  event_sequence: EventItem[];
  communication_bursts: { window_start: string; count: number }[];
  location_activity: LocationActivityEntry[];
  movement: EventItem[];
}

export async function apiTemporalLocation(params: { scenario?: string; entity_id?: string } = {}): Promise<TemporalLocationResponse> {
  const search = new URLSearchParams();
  if (params.scenario) search.append("scenario", params.scenario);
  if (params.entity_id) search.append("entity_id", params.entity_id);
  const qs = search.toString();
  return request<TemporalLocationResponse>(`/api/v1/analysis/temporal-location${qs ? `?${qs}` : ""}`);
}

// --- Investigation engine workflow (Phase 10) -------------------------------

export async function apiRunInvestigation(scenario = "NORMAL_NETWORK"): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>(`/api/v1/analysis/investigation?scenario=${encodeURIComponent(scenario)}`, {
    method: "POST",
  });
}

// --- AI Assistant (Phase 11) ------------------------------------------------

export interface KeyFinding {
  label: string;
  detail: string;
}

export interface AssistantEntity {
  id: string;
  type: string;
  name: string;
  priority: number;
}

export interface AssistantRelItem {
  source: string;
  target: string;
  kind: string; // CONFIRMED | POTENTIAL
  confidence: number;
}

export interface AssistantRecommendation {
  kind: string;
  subject: string;
  priority: number;
  info_gain: number;
  reasoning: string[];
  recommended_data: string;
  window: string;
}

export interface IntelligenceResponse {
  type: string;
  query: string;
  summary: string;
  key_findings: KeyFinding[];
  entities: AssistantEntity[];
  relationships: AssistantRelItem[];
  anomalies: string[];
  evidence: string[];
  evidence_gaps: string[];
  next_best_action: AssistantRecommendation | null;
  source_ids: string[];
  found: boolean;
}

export interface AssistantResponse {
  question: string;
  answer: string;
  source_ids: string[];
  found: boolean;
  structured?: IntelligenceResponse | null;
}

export async function apiAskAssistant(question: string, caseKey?: string): Promise<AssistantResponse> {
  return request<AssistantResponse>("/api/v1/analysis/assistant", {
    method: "POST",
    body: JSON.stringify({ question, case_key: caseKey || null }),
  });
}

// --- Audit (Phase 13) -------------------------------------------------------

export interface AuditEntry {
  id: number;
  user_id?: number | null;
  action: string;
  object_type?: string | null;
  object_id?: string | null;
  result: Record<string, unknown>;
  created_at: string;
}

export async function apiListAudit(limit = 50): Promise<AuditEntry[]> {
  return request<AuditEntry[]>(`/api/v1/audit?limit=${limit}`);
}

export interface CaseEntity {
  entity_id: string;
  entity_type: string;
  name: string;
  confidence: number;
  attributes: Record<string, unknown>;
  source_ids: string[];
  created_at: string;
}

export async function apiUpdateCaseEntity(caseKey: string, entityId: string, input: {
  name: string;
  confidence: number;
  source_ids: string[];
  note?: string;
  location_name?: string;
  latitude?: number;
  longitude?: number;
}): Promise<CaseEntity> {
  return request<CaseEntity>(`/api/v1/cases/${encodeURIComponent(caseKey)}/entities/${encodeURIComponent(entityId)}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function apiRecordAudit(payload: {
  action: string;
  object_type?: string;
  object_id?: string;
  result?: Record<string, unknown>;
}): Promise<AuditEntry> {
  return request<AuditEntry>("/api/v1/audit", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// --- Simulation / Demo mode (Phase 15) --------------------------------------

export interface SimulationStep {
  label: string;
  count: number;
  sample: string;
}
export interface SimulationResponse {
  scenario: string;
  steps: SimulationStep[];
  entities: number;
  relationships: number;
  nodes_written: number;
  insights: Record<string, unknown>;
  elapsed_seconds: number;
}

export async function apiRunSimulation(scenario = "NORMAL_NETWORK"): Promise<SimulationResponse> {
  return request<SimulationResponse>(`/api/v1/analysis/simulation?scenario=${encodeURIComponent(scenario)}`, {
    method: "POST",
  });
}
