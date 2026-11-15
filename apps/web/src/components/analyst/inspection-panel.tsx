"use client";

import { useEffect, useState } from "react";
import { PanelRightClose } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ColumnsView } from "@/components/datasets/columns-view";
import { getDataset, getQuality, type DatasetDetail, type QualityReport } from "@/lib/datasets";
import type { Check, Payload, PythonRun, SqlRun } from "@/lib/analyst";
import { formatBytes } from "@/lib/format";
import { CheckBadge, RunStatusBadge, VALIDATION_EXPLANATION, ValidationBadge } from "./badges";
import { CodeBlock } from "./code-block";
import { RunTimeline } from "./run-timeline";

const Empty = ({ children }: { children: React.ReactNode }) => <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">{children}</p>;
const Stat = ({ label, value }: { label: string; value: React.ReactNode }) => (
  <div className="rounded-md border px-3 py-2"><dt className="text-[11px] text-muted-foreground">{label}</dt><dd className="mt-0.5 text-sm font-medium tabular-nums">{value}</dd></div>
);
const ms = (v: number | null) => (v === null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`);

function SqlCard({ run }: { run: SqlRun }) {
  const [showExec, setShowExec] = useState(false);
  return (
    <article id={`sql-${run.index}`} className="space-y-2.5 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">Query {run.index}</span>
        <RunStatusBadge status={run.status} />
      </div>
      {run.purpose && <p className="text-sm">{run.purpose}</p>}
      <dl className="grid grid-cols-3 gap-2">
        <Stat label="Duration" value={ms(run.duration_ms)} />
        <Stat label="Rows returned" value={run.row_count === null ? "—" : run.row_count.toLocaleString("en-GB") + (run.truncated ? "+" : "")} />
        <Stat label="Result" value={run.result_id ?? "—"} />
      </dl>
      <CodeBlock code={run.sql} lang="sql" title="Generated SQL" />
      <p className="text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Tables accessed:</span> {run.tables.length ? run.tables.join(", ") : "—"}
        {" · "}
        <span className="font-medium text-foreground">Columns:</span> {run.columns.length ? run.columns.join(", ") : "—"}
      </p>
      {run.notes.length > 0 && <ul className="text-xs text-muted-foreground">{run.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      {run.error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-2.5 py-1.5 text-xs text-destructive">{run.error}</p>}
      {run.executed_sql && (
        <div>
          <button type="button" onClick={() => setShowExec(!showExec)} aria-expanded={showExec} className="text-xs text-muted-foreground underline-offset-2 hover:underline">
            {showExec ? "Hide" : "Show"} the exact statement sent to the database
          </button>
          {showExec && (
            <div className="mt-2 space-y-1.5">
              <CodeBlock code={run.executed_sql} lang="sql" title="Executed statement" />
              <p className="text-xs text-muted-foreground">The server validated your query, replaced the table name <code>data</code> with this dataset&apos;s own table, and added a row limit. Nothing else was changed.</p>
            </div>
          )}
        </div>
      )}
    </article>
  );
}

function PythonCard({ run }: { run: PythonRun }) {
  return (
    <article id={`python-${run.index}`} className="space-y-2.5 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">Analysis {run.index}</span>
        <RunStatusBadge status={run.status} />
      </div>
      {run.purpose && <p className="text-sm">{run.purpose}</p>}
      <dl className="grid grid-cols-3 gap-2">
        <Stat label="Duration" value={ms(run.duration_ms)} />
        <Stat label="Result" value={run.result_id ?? "—"} />
        <Stat label="Limits" value={run.limits_enforced === null ? "—" : run.limits_enforced ? "Enforced" : "Time only"} />
      </dl>
      <CodeBlock code={run.code} lang="python" title="Generated Python" />
      {run.packages.length > 0 && <p className="text-xs text-muted-foreground"><span className="font-medium text-foreground">Packages:</span> {run.packages.map((p) => (run.versions?.[p] ? `${p} ${run.versions[p]}` : p)).join(", ")}</p>}
      {run.limits_enforced === false && <p className="text-xs text-muted-foreground">Memory and CPU limits are not available on this host, so only the time limit applied.</p>}
      {run.stdout && <div><p className="mb-1 text-[11px] font-medium text-muted-foreground uppercase">Output</p><pre className="max-h-48 overflow-auto rounded-md border bg-muted/40 p-2.5 font-mono text-xs whitespace-pre-wrap">{run.stdout}</pre></div>}
      {run.error && <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-2.5 py-1.5 text-xs text-destructive">{run.error}</p>}
    </article>
  );
}

function CheckCard({ c }: { c: Check }) {
  return (
    <article className="space-y-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2"><span className="text-sm font-semibold">{c.label}</span><CheckBadge status={c.status} /></div>
      {(c.claimed !== null || c.recomputed !== null) && (
        <dl className="grid grid-cols-2 gap-2">
          <Stat label="Reported" value={c.claimed === null ? "—" : String(typeof c.claimed === "number" ? c.claimed.toLocaleString("en-GB", { maximumFractionDigits: 4 }) : c.claimed)} />
          <Stat label="Recalculated" value={c.recomputed === null ? "—" : String(typeof c.recomputed === "number" ? c.recomputed.toLocaleString("en-GB", { maximumFractionDigits: 4 }) : c.recomputed)} />
        </dl>
      )}
      <p className="text-sm">{c.detail}</p>
      <p className="text-xs text-muted-foreground"><span className="font-medium text-foreground">Method:</span> {c.method}</p>
      {c.sql && <CodeBlock code={c.sql} lang="sql" title="Independent calculation" />}
    </article>
  );
}

function ProfileTab({ datasetId }: { datasetId: string }) {
  const [state, setState] = useState<{ detail: DatasetDetail; quality: QualityReport | null } | "error" | null>(null);
  useEffect(() => {
    let cancelled = false;
    Promise.all([getDataset(datasetId), getQuality(datasetId).catch(() => null)])
      .then(([detail, quality]) => !cancelled && setState({ detail, quality }))
      .catch(() => !cancelled && setState("error"));
    return () => { cancelled = true; };
  }, [datasetId]);
  if (state === null) return <p className="text-sm text-muted-foreground">Loading profile…</p>;
  if (state === "error") return <Empty>The dataset profile could not be loaded.</Empty>;
  const { detail, quality } = state;
  const cleaned = detail.has_cleaned && detail.cleaned_columns;
  const s = quality?.cleaned?.summary ?? quality?.summary;
  return (
    <div className="space-y-3">
      <dl className="grid grid-cols-2 gap-2">
        <Stat label="Dataset" value={detail.name} />
        <Stat label="Version analysed" value={cleaned ? "Cleaned" : "Original"} />
        <Stat label="Rows" value={(cleaned && quality?.cleaned ? quality.cleaned.summary.rows : detail.row_count).toLocaleString("en-GB")} />
        <Stat label="Size" value={formatBytes(detail.size_bytes)} />
        {s && <Stat label="Issues remaining" value={Object.entries(s.issue_counts).filter(([k]) => k !== "info").reduce((n, [, v]) => n + v, 0)} />}
        {s && <Stat label="Missing cells" value={s.missing_cells.toLocaleString("en-GB")} />}
      </dl>
      {!cleaned && <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs">Analyses use the original data, where every column is text. Generate the cleaned version on the dataset page for typed columns and independently verifiable totals.</p>}
      <ColumnsView compact columns={cleaned ? detail.cleaned_columns! : detail.columns} />
    </div>
  );
}

export function InspectionPanel({ payload, datasetId, tab, onTab, onClose }: { payload: Payload | null; datasetId: string | null; tab: string; onTab: (t: string) => void; onClose: () => void }) {
  const v = payload?.validation;
  const results = payload?.results ?? [];
  return (
    <aside aria-label="Inspection panel" className="flex h-full min-h-0 flex-col border-l bg-background">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <h2 className="text-sm font-semibold">Inspect</h2>
        <Button variant="ghost" size="icon-sm" aria-label="Collapse inspection panel" onClick={onClose}><PanelRightClose /></Button>
      </div>
      <Tabs value={tab} onValueChange={(t) => onTab(String(t))} className="flex min-h-0 flex-1 flex-col">
        <TabsList variant="line" className="h-auto w-full justify-start gap-0 overflow-x-auto border-b px-2 pb-1.5">
          {[["overview", "Overview"], ["sql", `SQL${payload?.sql.length ? ` (${payload.sql.length})` : ""}`], ["python", `Python${payload?.python.length ? ` (${payload.python.length})` : ""}`], ["profile", "Data profile"], ["validation", "Validation"]].map(([value, label]) => (
            <TabsTrigger key={value} value={value} className="flex-none px-2.5 py-1 text-xs">{label}</TabsTrigger>
          ))}
        </TabsList>
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <TabsContent value="overview" className="space-y-4">
            {!payload ? <Empty>Ask a question. The plan, every query and every check will appear here so you can inspect how the answer was produced.</Empty> : (
              <>
                <dl className="grid grid-cols-2 gap-2">
                  <Stat label="Duration" value={ms(payload.duration_ms)} />
                  <Stat label="Model" value={payload.model ?? "—"} />
                  <Stat label="Data analysed" value={payload.dataset ? `${payload.dataset.version === "cleaned" ? "Cleaned" : "Original"}, ${payload.dataset.rows.toLocaleString("en-GB")} rows` : "—"} />
                  <Stat label="Tool calls" value={payload.timeline.filter((s) => !["understand", "explain_results"].includes(s.key)).length} />
                </dl>
                {payload.plan && (
                  <section>
                    <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Analysis plan</h3>
                    <ol className="list-decimal space-y-1 pl-5 text-sm">{payload.plan.steps.map((s) => <li key={s}>{s}</li>)}</ol>
                    {payload.plan.assumptions.length > 0 && <p className="mt-2 text-xs text-muted-foreground">Assumptions: {payload.plan.assumptions.join("; ")}</p>}
                  </section>
                )}
                <section>
                  <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Execution</h3>
                  <RunTimeline steps={payload.timeline} onSelect={(s) => s.ref && onTab(s.ref.type === "validation" ? "validation" : s.ref.type)} />
                </section>
                {payload.results.length > 0 && (
                  <section>
                    <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground uppercase">Results stored</h3>
                    <ul className="space-y-1 text-xs">{results.map((r) => <li key={r.id} className="flex justify-between gap-3 rounded-md border px-2.5 py-1.5"><span className="truncate"><span className="font-medium">{r.id}</span> · {r.label}</span><span className="shrink-0 text-muted-foreground tabular-nums">{r.row_count.toLocaleString("en-GB")} rows</span></li>)}</ul>
                  </section>
                )}
              </>
            )}
          </TabsContent>
          <TabsContent value="sql" className="space-y-3">
            {!payload?.sql.length ? <Empty>No SQL was run for this answer.</Empty> : payload.sql.map((r) => <SqlCard key={r.index} run={r} />)}
          </TabsContent>
          <TabsContent value="python" className="space-y-3">
            {!payload?.python.length ? <Empty>No Python analysis was run for this answer.</Empty> : payload.python.map((r) => <PythonCard key={r.index} run={r} />)}
          </TabsContent>
          <TabsContent value="profile">{datasetId ? <ProfileTab datasetId={datasetId} /> : <Empty>Select a dataset to see its profile.</Empty>}</TabsContent>
          <TabsContent value="validation" className="space-y-3">
            {!v ? <Empty>Validation results appear here after an analysis.</Empty> : (
              <>
                <div className="space-y-1.5 rounded-lg border p-3">
                  <ValidationBadge status={v.status} />
                  <p className="text-sm">{VALIDATION_EXPLANATION[v.status]}</p>
                </div>
                {v.checks.map((c) => <CheckCard key={c.id} c={c} />)}
                {v.warnings.length > 0 && (
                  <section className="space-y-2">
                    <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Warnings</h3>
                    {v.warnings.map((w) => <div key={w.id} className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2"><p className="text-sm font-medium">{w.label}</p><p className="mt-0.5 text-xs text-muted-foreground">{w.detail}</p></div>)}
                  </section>
                )}
                {v.checks.length === 0 && v.warnings.length === 0 && <Empty>No checks were run.</Empty>}
              </>
            )}
          </TabsContent>
        </div>
      </Tabs>
    </aside>
  );
}
