import { api, ApiError } from "@/lib/api";

/** Mirrors the engine's default. The engine enforces the real limit and its message is shown if they differ. */
export const MAX_UPLOAD_MB = 50;

export type DatasetStatus = "processing" | "ready" | "cleaning" | "failed";

export type Dataset = {
  id: string;
  name: string;
  original_filename: string | null;
  status: DatasetStatus;
  error: string | null;
  is_sample: boolean;
  row_count: number;
  column_count: number;
  size_bytes: number;
  has_cleaned: boolean;
  created_at: string;
};

export type ColumnProfile = {
  name: string;
  original_name: string;
  kind: "empty" | "numeric" | "date" | "categorical" | "text";
  db_type?: string;
  missing_count: number;
  missing_pct: number | null;
  placeholder_count: number;
  distinct_count: number;
  samples: string[];
  is_identifier: boolean;
  min?: number | string;
  max?: number | string;
  mean?: number;
  median?: number;
};

export type DatasetDetail = Dataset & {
  columns: ColumnProfile[];
  warnings: string[];
  suggested_questions: string[];
  cleaned_columns: ColumnProfile[] | null;
};

export type Severity = "high" | "medium" | "low" | "info";

export type Preview = {
  rows: { row: string; before: string; after: string }[];
  affected: number;
  note: string | null;
};

export type Issue = {
  id: string;
  type: string;
  column: string | null;
  title: string;
  description: string;
  recommendation: string;
  affected_rows: number;
  affected_pct: number;
  severity: Severity;
  fix: { operation: string; column: string | null; params: Record<string, unknown>; label: string } | null;
  preview: Preview | null;
  operation_id: string | null;
  operation_status: OpStatus | null;
  ambiguous_dates?: boolean;
};

export type QualitySummary = {
  rows: number;
  columns: number;
  issue_counts: Record<Severity, number>;
  fixable_issues: number;
  missing_cells: number;
  rows_before?: number;
  rows_after?: number;
};

export type QualityReport = {
  summary: QualitySummary;
  issues: Issue[];
  warnings: string[];
  cleaned?: { summary: QualitySummary; issues: Issue[]; generated_at: string };
};

export type OpStatus = "proposed" | "approved" | "rejected" | "applied";

export type CleaningOp = {
  id: string;
  operation: string;
  label: string;
  column: string | null;
  column_label: string | null;
  status: OpStatus;
  affected_rows: number;
  params: Record<string, unknown>;
  issue_titles: string[];
  severity: Severity;
  recommendation: string | null;
  preview: Preview | null;
  applied_at: string | null;
  note: string | null;
};

export type RowsPage = {
  columns: { name: string; original_name: string; db_type: string }[];
  rows: Record<string, string | number | boolean | null>[];
  total: number;
  offset: number;
  limit: number;
  version: "original" | "cleaned";
};

export type RowFilter = { column: string; op: string; value?: string };

export const listDatasets = () => api<Dataset[]>("/datasets");
export const getDataset = (id: string) => api<DatasetDetail>(`/datasets/${id}`);
export const createSample = () => api<Dataset>("/datasets/sample", { method: "POST" });
export const renameDataset = (id: string, name: string) =>
  api<Dataset>(`/datasets/${id}`, { method: "PATCH", body: JSON.stringify({ name }) });
export const deleteDataset = (id: string) => api<void>(`/datasets/${id}`, { method: "DELETE" });
export const getQuality = (id: string) => api<QualityReport>(`/datasets/${id}/quality`);
export const getCleaning = (id: string) =>
  api<{ operations: CleaningOp[]; has_cleaned: boolean; status: DatasetStatus }>(`/datasets/${id}/cleaning`);
export const setOperationStatus = (id: string, opId: string, status: "proposed" | "approved" | "rejected") =>
  api<CleaningOp>(`/datasets/${id}/cleaning/${opId}`, { method: "PATCH", body: JSON.stringify({ status }) });
export const setDayFirst = (id: string, opId: string, dayfirst: boolean) =>
  api<CleaningOp>(`/datasets/${id}/cleaning/${opId}`, { method: "PATCH", body: JSON.stringify({ dayfirst }) });
export const setAllOperations = (id: string, status: "proposed" | "approved" | "rejected", ids?: string[]) =>
  api<{ updated: number }>(`/datasets/${id}/cleaning/status`, {
    method: "POST",
    body: JSON.stringify({ status, operation_ids: ids ?? null }),
  });
export const applyCleaning = (id: string) => api<Dataset>(`/datasets/${id}/cleaning/apply`, { method: "POST" });

export function getRows(
  id: string,
  p: { version: "original" | "cleaned"; offset: number; limit: number; sort?: string; desc?: boolean; search?: string; filters?: RowFilter[] },
) {
  const q = new URLSearchParams({ version: p.version, offset: String(p.offset), limit: String(p.limit) });
  if (p.sort) q.set("sort", p.sort);
  if (p.desc) q.set("desc", "true");
  if (p.search) q.set("search", p.search);
  if (p.filters?.length) q.set("filters", JSON.stringify(p.filters));
  return api<RowsPage>(`/datasets/${id}/rows?${q}`);
}

/** Upload with real progress events (fetch cannot report upload progress). */
export function uploadDataset(file: File, name: string, onProgress: (fraction: number) => void): Promise<Dataset> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/datasets");
    xhr.setRequestHeader("X-Requested-With", "QuantaLens");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onerror = () => reject(new ApiError(0, "Could not reach the server. Check your connection and try again."));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON error body */
      }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(body as Dataset);
      const detail = (body as { detail?: unknown } | null)?.detail;
      const fallback = xhr.status === 413 ? `The file is larger than ${MAX_UPLOAD_MB} MB.` : "The upload failed. Please try again.";
      reject(new ApiError(xhr.status, typeof detail === "string" ? detail : fallback));
    };
    const form = new FormData();
    form.append("file", file);
    if (name.trim()) form.append("name", name.trim());
    xhr.send(form);
  });
}
