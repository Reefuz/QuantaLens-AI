import { api, ApiError } from "@/lib/api";

export type StepStatus = "running" | "done" | "error";
export type Step = {
  id: number;
  key: string;
  title: string;
  status: StepStatus;
  detail: string;
  ms: number | null;
  ref: { type: "sql" | "python" | "chart" | "validation"; index?: number; id?: string } | null;
};

export type SqlRun = {
  index: number;
  sql: string;
  purpose: string;
  status: "success" | "rejected" | "error";
  executed_sql: string | null;
  tables: string[];
  columns: string[];
  notes: string[];
  duration_ms: number | null;
  row_count: number | null;
  result_id: string | null;
  error: string | null;
  truncated?: boolean;
};

export type PythonRun = {
  index: number;
  code: string;
  purpose: string;
  status: "success" | "rejected" | "error";
  duration_ms: number | null;
  stdout: string;
  error: string | null;
  packages: string[];
  result_id: string | null;
  limits_enforced: boolean | null;
  versions?: Record<string, string>;
};

export type StoredResult = {
  id: string;
  source: "sql" | "python";
  step: number;
  label: string;
  columns: string[];
  rows: (string | number | boolean | null)[][];
  row_count: number;
  truncated: boolean;
  rows_in_payload: number;
};

export type ChartType = "bar" | "hbar" | "line" | "area" | "pie" | "donut" | "scatter" | "histogram" | "box" | "heatmap" | "correlation";
export type ChartSpec = {
  id: string;
  type: ChartType;
  title: string;
  x_label: string;
  y_label: string;
  x_key: string;
  y_keys: string[];
  data: Record<string, string | number | null | (number | null)[]>[];
  result_id: string;
  notes: string[];
  source_rows: number;
  series_values?: string[];
  x_values?: string[];
  y_values?: string[];
  stats?: Record<string, number>;
};

export type CheckStatus = "verified" | "failed" | "unverified" | "warning";
export type Check = {
  id: string;
  kind: string;
  label: string;
  status: CheckStatus;
  claimed: number | string | null;
  recomputed: number | string | null;
  method: string;
  detail: string;
  sql: string | null;
};
export type ValidationStatus = "verified" | "partially_verified" | "unverified" | "failed" | "not_validated";
export type Validation = {
  status: ValidationStatus;
  checks: Check[];
  warnings: { id: string; label: string; status: string; detail: string }[];
};

export type Finding = { finding: string; evidence: string; kind: "observed" | "statistical" | "possible_explanation" };
export type Answer = {
  executive_summary: string;
  key_findings: Finding[];
  business_implications: string[];
  recommendations: string[];
  limitations: string[];
  assumptions: string[];
  chart_ids: string[];
  follow_up_questions: string[];
};

export type Payload = {
  type: "answer" | "clarification" | "error";
  answer: Answer | null;
  question?: string;
  options?: string[];
  error?: string;
  plan: { steps: string[]; assumptions: string[] } | null;
  results: StoredResult[];
  charts: ChartSpec[];
  sql: SqlRun[];
  python: PythonRun[];
  validation: Validation;
  dataset: { id: string; name: string; version: "cleaned" | "original"; rows: number } | null;
  timeline: Step[];
  model: string | null;
  duration_ms: number;
  session_id?: string;
};

export type ChatMessage = { id: string; role: "user" | "assistant"; content: string; payload: Payload | null; created_at: string };

export type Conversation = { id: string; dataset_id: string; title: string; updated_at: string; created_at: string; message_count: number };
export type ConversationDetail = {
  conversation: Conversation;
  dataset: { id: string; name: string; status: string; has_cleaned: boolean } | null;
  messages: ChatMessage[];
  running: boolean;
};

export type StreamEvent =
  | { type: "start"; session_id: string; user_message: ChatMessage; title: string }
  | ({ type: "step" } & Step)
  | { type: "chart"; chart: ChartSpec }
  | { type: "notice"; message: string }
  | { type: "final"; message: ChatMessage; title: string }
  | { type: "error"; message: string }
  | { type: "ping" }
  | { type: "end" };

export const analystStatus = () => api<{ ai_configured: boolean; model: string | null }>("/analyst/status");
export const listConversations = (datasetId: string) => api<Conversation[]>(`/conversations?dataset_id=${datasetId}`);
export const createConversation = (datasetId: string) => api<Conversation>("/conversations", { method: "POST", body: JSON.stringify({ dataset_id: datasetId }) });
export const getConversation = (id: string) => api<ConversationDetail>(`/conversations/${id}`);
export const renameConversation = (id: string, title: string) => api<Conversation>(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify({ title }) });
export const deleteConversation = (id: string) => api<void>(`/conversations/${id}`, { method: "DELETE" });

/** Stream an analysis. Every event corresponds to work the server actually did. */
export async function askStream(conversationId: string, content: string, onEvent: (e: StreamEvent) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Requested-With": "QuantaLens" },
    body: JSON.stringify({ content }),
    signal,
  });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, typeof body?.detail === "string" ? body.detail : "The analysis could not be started.");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (line) onEvent(JSON.parse(line) as StreamEvent);
    }
  }
}

export const VALIDATION_LABEL: Record<ValidationStatus, string> = {
  verified: "Verified",
  partially_verified: "Partially verified",
  unverified: "Unverified",
  failed: "Verification failed",
  not_validated: "Not validated",
};
