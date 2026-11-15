import { api } from "@/lib/api";
import type { ValidationStatus } from "@/lib/analyst";

export type HistoryItem = {
  session_id: string;
  message_id: string | null;
  conversation_id: string;
  conversation_title: string;
  dataset_id: string;
  dataset_name: string;
  question: string;
  status: "completed" | "clarification" | "failed" | "running";
  summary: string | null;
  validation_status: ValidationStatus | null;
  model: string | null;
  duration_ms: number | null;
  sql_count: number;
  python_count: number;
  chart_count: number;
  results: { id: string; label: string; row_count: number }[];
  created_at: string;
};
export type HistoryPage = { items: HistoryItem[]; total: number; offset: number; limit: number };

export function getHistory(p: { datasetId?: string; q?: string; status?: string; offset?: number; limit?: number }) {
  const q = new URLSearchParams({ offset: String(p.offset ?? 0), limit: String(p.limit ?? 20) });
  if (p.datasetId) q.set("dataset_id", p.datasetId);
  if (p.q?.trim()) q.set("q", p.q.trim());
  if (p.status) q.set("status", p.status);
  return api<HistoryPage>(`/history?${q}`);
}

export const reportUrl = (messageId: string, kind: "pdf" | "xlsx" | "csv", result?: string) =>
  `/api/reports/${messageId}/${kind}${kind === "csv" && result ? `?result=${result}` : ""}`;

export type AccountSettings = {
  user: { id: string; email: string; display_name: string | null; created_at: string };
  sessions: { id: string; created_at: string; last_seen_at: string; user_agent: string | null; current: boolean }[];
  storage: { datasets: number; used_bytes: number; limit_bytes: number };
  ai: { configured: boolean; model: string | null; fallback_model: string | null };
  limits: { max_upload_mb: number };
};
export const getAccount = () => api<AccountSettings>("/settings");
export const updateProfile = (display_name: string) => api("/settings/profile", { method: "PATCH", body: JSON.stringify({ display_name }) });
export const changePassword = (current_password: string, new_password: string) => api<void>("/settings/password", { method: "POST", body: JSON.stringify({ current_password, new_password }) });
export const revokeOthers = () => api<{ revoked: number }>("/settings/sessions/revoke-others", { method: "POST" });
export const deleteAllData = (password: string) => api<{ datasets_deleted: number }>("/settings/delete-data", { method: "POST", body: JSON.stringify({ password }) });
export const deleteAccount = (password: string) => api<void>("/settings/delete-account", { method: "POST", body: JSON.stringify({ password }) });
