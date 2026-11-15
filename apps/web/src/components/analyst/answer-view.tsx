"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Code2, Database, ListChecks, MessageSquarePlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChartCard } from "@/components/charts/chart-card";
import type { Finding, Payload } from "@/lib/analyst";
import { cn } from "@/lib/utils";
import { ExportMenu } from "./export-menu";
import { ValidationBadge } from "./badges";
import { RunTimeline } from "./run-timeline";

const KIND: Record<Finding["kind"], { label: string; cls: string }> = {
  observed: { label: "Observed", cls: "border-border text-foreground" },
  statistical: { label: "Statistical", cls: "border-brand/40 bg-brand/10 text-brand" },
  possible_explanation: { label: "Possible explanation", cls: "border-warning/40 bg-warning/15 text-foreground" },
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h3>
      {children}
    </section>
  );
}

function List({ items }: { items: string[] }) {
  return (
    <ul className="space-y-1.5 text-sm">
      {items.map((t) => (
        <li key={t} className="flex gap-2"><span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-muted-foreground" /><span>{t}</span></li>
      ))}
    </ul>
  );
}

export function AnswerView({ payload, messageId, onInspect, onAsk, disabled }: { payload: Payload; messageId: string; onInspect: (tab: string) => void; onAsk: (q: string) => void; disabled: boolean }) {
  const [showSteps, setShowSteps] = useState(false);
  const a = payload.answer;
  if (!a) return null;
  const charts = payload.charts.filter((c) => a.chart_ids.includes(c.id));
  const byId = Object.fromEntries(payload.results.map((r) => [r.id, r]));
  const failed = payload.validation.status === "failed";

  return (
    <div className="space-y-6 rounded-lg border bg-card p-5">
      <div className="flex flex-wrap items-center gap-2">
        <ValidationBadge status={payload.validation.status} />
        <button type="button" onClick={() => onInspect("validation")} className="text-xs text-muted-foreground underline-offset-2 hover:underline">
          {payload.validation.checks.length} check{payload.validation.checks.length === 1 ? "" : "s"}{payload.validation.warnings.length ? `, ${payload.validation.warnings.length} warning${payload.validation.warnings.length === 1 ? "" : "s"}` : ""}
        </button>
        {payload.dataset && <span className="text-xs text-muted-foreground">{payload.dataset.version === "cleaned" ? "Cleaned data" : "Original data"}</span>}
      </div>

      {failed && (
        <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          An independent recalculation disagreed with a reported figure. See the Validation tab before relying on these numbers.
        </p>
      )}

      <Section title="Executive summary">
        <p className="text-[15px] leading-relaxed">{a.executive_summary}</p>
      </Section>

      <Section title="Key findings">
        <ul className="space-y-3">
          {a.key_findings.map((f, i) => (
            <li key={i} className="rounded-md border p-3">
              <div className="mb-1.5 flex items-center gap-2">
                <span className={cn("rounded-md border px-1.5 py-0.5 text-[11px] font-medium", KIND[f.kind].cls)}>{KIND[f.kind].label}</span>
              </div>
              <p className="text-sm font-medium">{f.finding}</p>
              {f.evidence && <p className="mt-1 text-xs text-muted-foreground">Evidence: {f.evidence}</p>}
            </li>
          ))}
        </ul>
      </Section>

      {charts.length > 0 && (
        <Section title="Visualisations">
          <div className="space-y-4">{charts.map((c) => <ChartCard key={c.id} spec={c} result={byId[c.result_id]} />)}</div>
        </Section>
      )}

      {a.business_implications.length > 0 && <Section title="Business implications"><List items={a.business_implications} /></Section>}
      {a.recommendations.length > 0 && <Section title="Recommendations"><List items={a.recommendations} /></Section>}
      {(a.limitations.length > 0 || a.assumptions.length > 0) && (
        <Section title="Limitations and assumptions">
          <List items={[...a.limitations, ...a.assumptions.map((x) => `Assumption: ${x}`)]} />
        </Section>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t pt-4">
        {payload.sql.length > 0 && <Button variant="outline" size="sm" onClick={() => onInspect("sql")}><Database /> SQL used ({payload.sql.length})</Button>}
        {payload.python.length > 0 && <Button variant="outline" size="sm" onClick={() => onInspect("python")}><Code2 /> Python used ({payload.python.length})</Button>}
        <Button variant="outline" size="sm" onClick={() => onInspect("validation")}><ListChecks /> Validation</Button>
        <Button variant="ghost" size="sm" onClick={() => setShowSteps(!showSteps)} aria-expanded={showSteps}>
          {showSteps ? <ChevronDown /> : <ChevronRight />} How this was produced
        </Button>
      </div>
      {showSteps && <div className="rounded-md border bg-muted/30 p-3"><RunTimeline steps={payload.timeline} compact /></div>}
      <div className="flex flex-wrap items-center gap-3"><span className="text-xs font-medium text-muted-foreground">Export</span><ExportMenu messageId={messageId} results={payload.results.map((r) => ({ id: r.id, label: r.label, row_count: r.row_count }))} /></div>

      {a.follow_up_questions.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {a.follow_up_questions.slice(0, 3).map((q) => (
            <Button key={q} variant="secondary" size="sm" disabled={disabled} onClick={() => onAsk(q)} className="h-auto min-h-7 whitespace-normal py-1 text-left">
              <MessageSquarePlus /> {q}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
