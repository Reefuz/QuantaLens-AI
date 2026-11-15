"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { AlertCircle, ChevronLeft, ChevronRight, Loader2, MessageSquareQuote, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ExportMenu } from "@/components/analyst/export-menu";
import { ValidationBadge } from "@/components/analyst/badges";
import { EmptyState } from "@/components/workspace/page-header";
import { ApiError } from "@/lib/api";
import { getHistory, type HistoryPage } from "@/lib/history";
import type { Dataset } from "@/lib/datasets";

const STATUS_LABEL: Record<string, string> = { completed: "Answered", clarification: "Needed detail", failed: "Did not complete", running: "Running" };
const PAGE = 15;

/** The history list (mode "history") and the exportable-reports list (mode "reports") share one component and one API. */
export function HistoryView({ datasets, mode }: { datasets: Dataset[]; mode: "history" | "reports" }) {
  const [q, setQ] = useState("");
  const [dataset, setDataset] = useState("");
  const [status, setStatus] = useState(mode === "reports" ? "completed" : "");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<HistoryPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const latest = useRef(0);
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(q); setOffset(0); }, 300);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const id = ++latest.current;
    getHistory({ q: debounced, datasetId: dataset || undefined, status: status || undefined, offset, limit: PAGE })
      .then((p) => { if (id === latest.current) { setPage(p); setError(null); } })
      .catch((e) => id === latest.current && setError(e instanceof ApiError ? e.message : "Could not load your analyses."))
      .finally(() => id === latest.current && setLoading(false));
  }, [debounced, dataset, status, offset]);

  const total = page?.total ?? 0;
  const filtered = Boolean(debounced || dataset || (mode === "history" && status));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative w-full max-w-xs">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search questions" aria-label="Search questions" className="pl-8" />
        </div>
        <select aria-label="Filter by dataset" value={dataset} onChange={(e) => { setDataset(e.target.value); setOffset(0); setLoading(true); }} className="h-8 rounded-md border bg-background px-2 text-sm">
          <option value="">All datasets</option>
          {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
        {mode === "history" && (
          <select aria-label="Filter by outcome" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); setLoading(true); }} className="h-8 rounded-md border bg-background px-2 text-sm">
            <option value="">All outcomes</option>
            <option value="completed">Answered</option>
            <option value="clarification">Needed detail</option>
            <option value="failed">Did not complete</option>
          </select>
        )}
        {loading && <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="Loading" />}
      </div>

      {error && <p role="alert" className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive"><AlertCircle className="size-4" />{error}</p>}

      {page && page.items.length === 0 && !error && (
        <EmptyState
          title={filtered ? "No analyses match" : mode === "reports" ? "No reports to export yet" : "No analyses yet"}
          body={filtered ? "Try a different search or filter." : "Ask the AI Analyst a question. Each answer is saved here and can be exported as a PDF or Excel report."}
          action={!filtered ? <Link href="/analyst" className="text-sm font-medium underline underline-offset-2">Open the AI Analyst</Link> : undefined}
        />
      )}

      <ul className="space-y-3">
        {page?.items.map((i) => (
          <li key={i.session_id} className="rounded-lg border bg-card p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <Link href={`/analyst?d=${i.dataset_id}&c=${i.conversation_id}`} className="flex items-start gap-2 font-medium hover:underline">
                  <MessageSquareQuote className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
                  <span>{i.question}</span>
                </Link>
                <p className="mt-1 pl-6 text-xs text-muted-foreground">
                  {i.dataset_name} · {new Date(i.created_at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}
                  {i.duration_ms ? ` · ${(i.duration_ms / 1000).toFixed(1)}s` : ""}
                  {i.model ? ` · ${i.model}` : ""}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {i.validation_status && <ValidationBadge status={i.validation_status} />}
                {!i.validation_status && <span className="rounded-md border px-1.5 py-0.5 text-xs text-muted-foreground">{STATUS_LABEL[i.status] ?? i.status}</span>}
              </div>
            </div>
            {i.summary && <p className="mt-2 line-clamp-2 pl-6 text-sm text-muted-foreground">{i.summary}</p>}
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3 pl-6">
              <p className="text-xs text-muted-foreground tabular-nums">
                {i.sql_count} SQL · {i.python_count} Python · {i.chart_count} chart{i.chart_count === 1 ? "" : "s"}
              </p>
              {i.status === "completed" && i.message_id ? <ExportMenu messageId={i.message_id} results={i.results} /> : <Link href={`/analyst?d=${i.dataset_id}&c=${i.conversation_id}`} className="text-sm underline underline-offset-2">Open</Link>}
            </div>
          </li>
        ))}
      </ul>

      {page && total > PAGE && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span className="tabular-nums">{offset + 1}–{Math.min(total, offset + PAGE)} of {total}</span>
          <div className="flex gap-2">
            <Button variant="outline" size="icon-sm" aria-label="Previous page" disabled={offset === 0} onClick={() => { setLoading(true); setOffset(Math.max(0, offset - PAGE)); }}><ChevronLeft /></Button>
            <Button variant="outline" size="icon-sm" aria-label="Next page" disabled={offset + PAGE >= total} onClick={() => { setLoading(true); setOffset(offset + PAGE); }}><ChevronRight /></Button>
          </div>
        </div>
      )}
    </div>
  );
}
