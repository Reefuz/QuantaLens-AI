import { CheckCircle2, Code2, Database, ShieldCheck } from "lucide-react";

const PLAN = [
  "Inspect schema and column types",
  "Aggregate revenue by customer segment",
  "Run outlier detection on transaction amounts",
  "Recalculate totals independently",
];

const SQL = `SELECT customer_segment,
       SUM(transaction_amount) AS total_value
FROM   transactions
WHERE  transaction_status = 'Completed'
GROUP  BY customer_segment
ORDER  BY total_value DESC;`;

/**
 * Static illustration of the workspace layout. It deliberately shows no result
 * figures: real numbers only appear in the application, computed from a dataset.
 */
export function WorkflowDemo() {
  return (
    <section id="workflow" className="mx-auto max-w-6xl scroll-mt-20 px-5 pb-24">
      <div className="overflow-hidden rounded-xl border bg-card shadow-sm">
        <div className="flex items-center justify-between border-b px-4 py-2.5">
          <span className="text-xs font-medium text-muted-foreground">AI Analyst · synthetic banking transactions</span>
          <span className="rounded-md border px-2 py-0.5 text-[11px] text-muted-foreground">
            Illustration of the workspace. No figures shown.
          </span>
        </div>
        <div className="grid md:grid-cols-[1.15fr_1fr]">
          <div className="space-y-5 p-5 md:border-r">
            <div className="rounded-lg bg-muted px-4 py-3 text-sm">
              Which customer segments contribute the most transaction value, and are there unusual patterns?
            </div>
            <div>
              <p className="mb-2 text-xs font-medium tracking-wide text-muted-foreground uppercase">Analysis plan</p>
              <ol className="space-y-2">
                {PLAN.map((step) => (
                  <li key={step} className="flex items-start gap-2.5 text-sm">
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-brand" />
                    {step}
                  </li>
                ))}
              </ol>
            </div>
            <div className="flex items-start gap-3 rounded-lg border p-3.5 text-sm">
              <ShieldCheck className="mt-0.5 size-4 shrink-0 text-success" />
              <p className="text-muted-foreground">
                Every headline figure is recalculated independently. Anything that cannot be verified is labelled as
                unverified.
              </p>
            </div>
          </div>
          <div className="bg-muted/40 p-5">
            <div className="mb-3 flex items-center gap-4 text-xs font-medium text-muted-foreground">
              <span className="inline-flex items-center gap-1.5 text-foreground">
                <Database className="size-3.5" /> SQL
              </span>
              <span className="inline-flex items-center gap-1.5">
                <Code2 className="size-3.5" /> Python
              </span>
              <span>Validation</span>
            </div>
            <pre className="overflow-x-auto rounded-lg border bg-card p-4 font-mono text-[12.5px] leading-relaxed">
              <code>{SQL}</code>
            </pre>
            <p className="mt-3 text-xs text-muted-foreground">
              The query shown is the query that ran. Read-only, row-limited, scoped to your own data.
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
