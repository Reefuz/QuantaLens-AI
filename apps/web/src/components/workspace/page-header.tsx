import type { ReactNode } from "react";

export function PageHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight md:text-2xl">{title}</h1>
        {description && <p className="mt-1 max-w-xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {action}
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed p-6">
      <div>
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-1 max-w-md text-sm text-muted-foreground">{body}</p>
      </div>
      {action}
    </div>
  );
}

/** Honest placeholder for a section whose backend is not built yet. */
export function PendingFeature({ phase, summary }: { phase: string; summary: string }) {
  return (
    <div className="rounded-lg border bg-card p-6">
      <p className="text-xs font-medium tracking-wide text-warning uppercase">Not available yet · {phase}</p>
      <p className="mt-2 max-w-lg text-sm text-muted-foreground">{summary}</p>
    </div>
  );
}
