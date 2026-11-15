"use client";

import { useRef, useState } from "react";
import { Download, FileImage, FileSpreadsheet } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ChartSpec, StoredResult } from "@/lib/analyst";
import { cn } from "@/lib/utils";
import { ChartBody, fmt } from "./chart-body";
import { exportChartCsv, exportChartPng, toCsv, slug } from "./export";

type View = "chart" | "table" | "raw";

function DataTable({ columns, rows, align }: { columns: string[]; rows: unknown[][]; align?: (i: number) => boolean }) {
  return (
    <div className="max-h-[320px] overflow-auto rounded-md border">
      <table className="w-full min-w-max text-xs">
        <thead className="sticky top-0 bg-muted/90 text-left text-muted-foreground backdrop-blur">
          <tr>{columns.map((c, i) => <th key={c} className={cn("px-3 py-1.5 font-medium whitespace-nowrap", align?.(i) && "text-right")}>{c}</th>)}</tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((r, i) => (
            <tr key={i}>{r.map((v, j) => <td key={j} className={cn("px-3 py-1 whitespace-nowrap", typeof v === "number" && "text-right tabular-nums")}>{Array.isArray(v) ? v.join(", ") : fmt(v)}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ChartCard({ spec, result }: { spec: ChartSpec; result?: StoredResult }) {
  const [view, setView] = useState<View>("chart");
  const ref = useRef<HTMLDivElement>(null);
  const keys = Array.from(new Set(spec.data.flatMap((d) => Object.keys(d))));

  return (
    <figure data-chart-card className="rounded-lg border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-2.5">
        <figcaption className="min-w-0">
          <p className="truncate text-sm font-semibold">{spec.title}</p>
          <p className="text-xs text-muted-foreground">From result {spec.result_id}{spec.stats?.pearson_r !== undefined ? ` · r = ${spec.stats.pearson_r} (n = ${spec.stats.n})` : ""}</p>
        </figcaption>
        <div className="flex items-center gap-1.5">
          <div role="group" aria-label="Chart view" className="inline-flex rounded-md border p-0.5 text-xs">
            {([["chart", "Chart"], ["table", "Table"], ["raw", "Raw data"]] as const).map(([v, label]) => (
              <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)} className={cn("rounded px-2 py-1", view === v ? "bg-accent font-medium" : "text-muted-foreground hover:text-foreground")}>{label}</button>
            ))}
          </div>
          <Button variant="ghost" size="icon-sm" aria-label="Download chart data as CSV" title="Download CSV" onClick={() => exportChartCsv(spec)}><FileSpreadsheet /></Button>
          <Button variant="ghost" size="icon-sm" aria-label="Download chart as PNG" title="Download PNG" disabled={view !== "chart"} onClick={() => ref.current && void exportChartPng(ref.current, spec.title)}><FileImage /></Button>
        </div>
      </div>
      <div ref={ref} className="p-3">
        {view === "chart" && <ChartBody spec={spec} />}
        {view === "table" && <DataTable columns={keys} rows={spec.data.map((d) => keys.map((k) => d[k] ?? null))} />}
        {view === "raw" && (result ? (
          <div className="space-y-2">
            <DataTable columns={result.columns} rows={result.rows} />
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>Result {result.id} ({result.source === "sql" ? "SQL" : "Python"}). Showing {result.rows.length.toLocaleString("en-GB")} of {result.row_count.toLocaleString("en-GB")} rows.</span>
              <Button variant="ghost" size="xs" onClick={() => {
                const blob = new Blob(["\ufeff" + toCsv(result.columns, result.rows)], { type: "text/csv;charset=utf-8" });
                const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `${slug(result.label || result.id)}.csv` });
                a.click();
                URL.revokeObjectURL(a.href);
              }}><Download /> Result CSV</Button>
            </div>
          </div>
        ) : <p className="p-4 text-sm text-muted-foreground">The underlying result is not available.</p>)}
      </div>
      {(spec.notes.length > 0 || spec.x_label || spec.y_label) && view === "chart" && spec.notes.length > 0 && (
        <ul className="space-y-0.5 border-t px-4 py-2 text-xs text-muted-foreground">{spec.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      )}
    </figure>
  );
}
