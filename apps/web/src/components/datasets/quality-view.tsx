"use client";

import { useCallback, useEffect, useState } from "react";
import { Check, ChevronDown, ChevronRight, Loader2, Wand2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  applyCleaning,
  getCleaning,
  getQuality,
  setAllOperations,
  setDayFirst,
  setOperationStatus,
  type CleaningOp,
  type Dataset,
  type DatasetDetail,
  type Issue,
  type Preview,
  type QualityReport,
  type QualitySummary,
  type Severity,
} from "@/lib/datasets";
import { cn } from "@/lib/utils";
import { OpStatusBadge, SeverityBadge } from "./badges";

const SEVERITIES: { key: Severity; label: string }[] = [
  { key: "high", label: "High severity" },
  { key: "medium", label: "Medium severity" },
  { key: "low", label: "Low severity" },
  { key: "info", label: "Informational" },
];

function PreviewTable({ preview }: { preview: Preview }) {
  return (
    <div className="space-y-2">
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-xs">
          <thead className="bg-muted/50 text-left text-muted-foreground">
            <tr>
              <th className="px-3 py-1.5 font-medium">Row</th>
              <th className="px-3 py-1.5 font-medium">Before</th>
              <th className="px-3 py-1.5 font-medium">After</th>
            </tr>
          </thead>
          <tbody className="divide-y font-mono">
            {preview.rows.map((r, i) => (
              <tr key={i}>
                <td className="px-3 py-1.5 text-muted-foreground">{r.row}</td>
                <td className="px-3 py-1.5 whitespace-pre">{r.before}</td>
                <td className="px-3 py-1.5 whitespace-pre text-brand">{r.after}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Showing {preview.rows.length} of {preview.affected.toLocaleString("en-GB")} affected rows. This preview is produced by running the actual operation.
      </p>
      {preview.note && <p className="text-xs text-foreground">{preview.note}</p>}
    </div>
  );
}

function IssueCard({
  issue, op, busy, onToggle, onDayFirst,
}: {
  issue: Issue;
  op: CleaningOp | undefined;
  busy: boolean;
  onToggle: (op: CleaningOp, next: "approved" | "rejected" | "proposed") => void;
  onDayFirst: (op: CleaningOp, dayfirst: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const preview = op?.preview ?? issue.preview;
  const status = op?.status ?? issue.operation_status;
  const dayfirst = op?.params.dayfirst as boolean | undefined;

  return (
    <article className="rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold">{issue.title}</h3>
            <SeverityBadge severity={issue.severity} />
            {status && <OpStatusBadge status={status} />}
          </div>
          {issue.affected_rows > 0 && (
            <p className="mt-1 text-xs text-muted-foreground tabular-nums">
              {issue.affected_rows.toLocaleString("en-GB")} rows affected ({issue.affected_pct}%)
            </p>
          )}
        </div>
        {op && issue.fix && status !== "applied" && (
          <div className="flex items-center gap-1.5" role="group" aria-label={`Decision for ${issue.title}`}>
            <Button size="sm" variant={status === "approved" ? "default" : "outline"} disabled={busy} onClick={() => onToggle(op, status === "approved" ? "proposed" : "approved")}>
              <Check /> Approve
            </Button>
            <Button size="sm" variant={status === "rejected" ? "default" : "outline"} disabled={busy} onClick={() => onToggle(op, status === "rejected" ? "proposed" : "rejected")}>
              <X /> Reject
            </Button>
          </div>
        )}
        {op && issue.fix && status === "applied" && (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => onToggle(op, "rejected")}>
            Exclude from next build
          </Button>
        )}
      </div>

      <p className="mt-3 text-sm text-muted-foreground">{issue.description}</p>
      <p className="mt-2 text-sm">
        <span className="font-medium">Recommendation: </span>
        {issue.recommendation}
      </p>

      {op?.operation === "parse_dates" && (
        <label className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          <span className="font-medium">Day and month order</span>
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={dayfirst === false ? "month" : "day"}
            disabled={busy || status === "applied"}
            onChange={(e) => onDayFirst(op, e.target.value === "day")}
          >
            <option value="day">Day first (31/12/2024)</option>
            <option value="month">Month first (12/31/2024)</option>
          </select>
          {issue.ambiguous_dates && <span className="text-xs text-warning">The data cannot settle this. Check the preview.</span>}
        </label>
      )}

      {preview && preview.rows.length > 0 && (
        <div className="mt-3">
          <button type="button" className="inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
            Preview of the proposed change
          </button>
          {open && (
            <div className="mt-2">
              <PreviewTable preview={preview} />
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function SummaryStrip({ s, title }: { s: QualitySummary; title?: string }) {
  const items = [
    ["Rows", s.rows.toLocaleString("en-GB")],
    ["Columns", String(s.columns)],
    ["Issues found", String(Object.entries(s.issue_counts).filter(([k]) => k !== "info").reduce((a, [, v]) => a + v, 0))],
    ["High severity", String(s.issue_counts.high)],
    ["Missing cells", s.missing_cells.toLocaleString("en-GB")],
  ];
  return (
    <div>
      {title && <h3 className="mb-2 text-sm font-semibold">{title}</h3>}
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-5">
        {items.map(([k, v]) => (
          <div key={k} className="bg-card px-4 py-3">
            <dt className="text-xs text-muted-foreground">{k}</dt>
            <dd className="mt-1 text-lg font-semibold tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function QualityView({ dataset, onDatasetChange }: { dataset: DatasetDetail; onDatasetChange: (d: Dataset) => void }) {
  const [report, setReport] = useState<QualityReport | null>(null);
  const [ops, setOps] = useState<Record<string, CleaningOp>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const ready = dataset.status === "ready";

  const load = useCallback(async () => {
    try {
      const [q, c] = await Promise.all([getQuality(dataset.id), getCleaning(dataset.id)]);
      setReport(q);
      setOps(Object.fromEntries(c.operations.map((o) => [o.id, o])));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load the quality report.");
    }
  }, [dataset.id]);

  // Load on first view and whenever a cleaning job finishes.
  useEffect(() => {
    if (dataset.status !== "ready") return;
    let cancelled = false;
    Promise.all([getQuality(dataset.id), getCleaning(dataset.id)])
      .then(([q, c]) => {
        if (cancelled) return;
        setReport(q);
        setOps(Object.fromEntries(c.operations.map((o) => [o.id, o])));
        setError(null);
      })
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "Could not load the quality report."));
    return () => {
      cancelled = true;
    };
  }, [dataset.id, dataset.status, dataset.has_cleaned]);

  async function guarded(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "That change could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  const toggle = (op: CleaningOp, next: "approved" | "rejected" | "proposed") =>
    guarded(async () => {
      const updated = await setOperationStatus(dataset.id, op.id, next);
      setOps((m) => ({ ...m, [updated.id]: updated }));
    });
  const dayFirst = (op: CleaningOp, value: boolean) =>
    guarded(async () => {
      const updated = await setDayFirst(dataset.id, op.id, value);
      setOps((m) => ({ ...m, [updated.id]: updated }));
    });
  const approveAll = () =>
    guarded(async () => {
      await setAllOperations(dataset.id, "approved");
      await load();
    });
  const generate = () =>
    guarded(async () => {
      onDatasetChange(await applyCleaning(dataset.id));
    });

  if (dataset.status === "processing") {
    return <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Profiling your data. The report appears here when it is ready.</p>;
  }
  if (dataset.status === "failed") return <p className="text-sm text-destructive">{dataset.error}</p>;
  if (!report) {
    return error ? <p role="alert" className="text-sm text-destructive">{error}</p> : <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Loading report…</p>;
  }

  const allOps = Object.values(ops);
  const approved = allOps.filter((o) => o.status === "approved" || o.status === "applied").length;
  const cleaning = dataset.status === "cleaning";

  return (
    <div className="space-y-6 pb-44 md:pb-24">
      <SummaryStrip s={report.summary} />

      {report.warnings.length > 0 && (
        <div className="rounded-lg border border-warning/40 bg-warning/10 p-4 text-sm">
          <p className="font-medium">About the file</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-muted-foreground">
            {report.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {report.cleaned && (
        <div className="rounded-lg border border-success/30 bg-success/5 p-4">
          <p className="text-sm font-medium">Cleaned version generated</p>
          <p className="mt-1 text-sm text-muted-foreground tabular-nums">
            {report.cleaned.summary.rows_before?.toLocaleString("en-GB")} rows became {report.cleaned.summary.rows_after?.toLocaleString("en-GB")}. High-severity issues went from{" "}
            {report.summary.issue_counts.high} to {report.cleaned.summary.issue_counts.high}. Issues that remain need a decision from you. Outliers, for example, are flagged but never deleted.
          </p>
          <div className="mt-3">
            <SummaryStrip s={report.cleaned.summary} title="After cleaning" />
          </div>
        </div>
      )}

      {error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
      {dataset.error && dataset.status === "ready" && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{dataset.error}</p>}

      {SEVERITIES.map(({ key, label }) => {
        const group = report.issues.filter((i) => i.severity === key);
        if (group.length === 0) return null;
        return (
          <section key={key} aria-label={label} className="space-y-3">
            <h2 className="text-sm font-semibold">
              {label} <span className="font-normal text-muted-foreground">({group.length})</span>
            </h2>
            {group.map((issue) => (
              <IssueCard key={issue.id} issue={issue} op={issue.operation_id ? ops[issue.operation_id] : undefined} busy={busy || cleaning} onToggle={toggle} onDayFirst={dayFirst} />
            ))}
          </section>
        );
      })}

      {report.issues.length === 0 && <p className="text-sm text-muted-foreground">No data quality issues were found.</p>}

      <div className="fixed inset-x-0 bottom-0 z-20 border-t bg-background/95 backdrop-blur md:left-60">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-3 md:px-8">
          <p className="text-sm text-muted-foreground tabular-nums">
            {allOps.length === 0 ? "No automatic fixes are available." : `${approved} of ${allOps.length} operations approved. Your original data is never changed.`}
          </p>
          <div className="flex flex-wrap gap-2">
            {allOps.length > 0 && (
              <Button variant="outline" onClick={approveAll} disabled={!ready || busy}>
                Approve all recommended
              </Button>
            )}
            <Button onClick={generate} disabled={!ready || busy}>
              {cleaning ? <Loader2 className="animate-spin" /> : <Wand2 />}
              {cleaning ? "Generating…" : dataset.has_cleaned ? "Regenerate cleaned version" : "Generate cleaned version"}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function HistoryView({ datasetId, refreshKey }: { datasetId: string; refreshKey: string }) {
  const [ops, setOps] = useState<CleaningOp[] | null>(null);
  useEffect(() => {
    getCleaning(datasetId).then((c) => setOps(c.operations)).catch(() => setOps([]));
  }, [datasetId, refreshKey]);
  if (!ops) return <p className="text-sm text-muted-foreground">Loading…</p>;
  const touched = ops.filter((o) => o.status !== "proposed");
  if (touched.length === 0) {
    return <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">No cleaning operations have been approved or applied yet. Review proposals on the Data quality tab.</p>;
  }
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead className="border-b bg-muted/50 text-left text-xs text-muted-foreground">
          <tr>
            <th className="px-4 py-2.5 font-medium">Operation</th>
            <th className="px-4 py-2.5 font-medium">Column</th>
            <th className="px-4 py-2.5 text-right font-medium">Rows affected</th>
            <th className="px-4 py-2.5 font-medium">Status</th>
            <th className="px-4 py-2.5 font-medium">Applied</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {touched.map((o) => (
            <tr key={o.id} className={cn(o.status === "rejected" && "text-muted-foreground")}>
              <td className="px-4 py-2.5">{o.label}</td>
              <td className="px-4 py-2.5">{o.column_label ?? "All rows"}</td>
              <td className="px-4 py-2.5 text-right tabular-nums">{o.affected_rows.toLocaleString("en-GB")}</td>
              <td className="px-4 py-2.5"><OpStatusBadge status={o.status} /></td>
              <td className="px-4 py-2.5 text-muted-foreground">{o.applied_at ? new Date(o.applied_at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" }) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
