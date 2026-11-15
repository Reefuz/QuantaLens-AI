import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import type { Step } from "@/lib/analyst";
import { cn } from "@/lib/utils";

/** Renders steps that the server reported. Nothing here is scripted: each row exists because that work ran. */
export function RunTimeline({ steps, onSelect, compact }: { steps: Step[]; onSelect?: (step: Step) => void; compact?: boolean }) {
  return (
    <ol className="space-y-0">
      {steps.map((s, i) => {
        const clickable = onSelect && s.ref && (s.ref.type === "sql" || s.ref.type === "python" || s.ref.type === "validation");
        const body = (
          <>
            <span className="relative mt-0.5 flex size-4 shrink-0 items-center justify-center">
              {s.status === "running" ? <Loader2 className="size-4 animate-spin text-brand" /> : s.status === "error" ? <AlertCircle className="size-4 text-destructive" /> : <CheckCircle2 className="size-4 text-success" />}
            </span>
            <span className="min-w-0 flex-1">
              <span className={cn("text-sm", s.status === "running" ? "font-medium" : "")}>{s.title}</span>
              {s.detail && <span className={cn("block text-xs text-muted-foreground", compact ? "truncate" : "")}>{s.detail}</span>}
            </span>
            {s.ms !== null && s.ms > 0 && <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{s.ms >= 1000 ? `${(s.ms / 1000).toFixed(1)}s` : `${s.ms}ms`}</span>}
          </>
        );
        return (
          <li key={s.id} className="relative">
            {i < steps.length - 1 && <span aria-hidden className="absolute top-5 bottom-0 left-[7px] w-px bg-border" />}
            {clickable ? (
              <button type="button" onClick={() => onSelect?.(s)} className="flex w-full items-start gap-2.5 rounded-md px-1 py-1.5 text-left hover:bg-accent/60">{body}</button>
            ) : (
              <div className="flex items-start gap-2.5 px-1 py-1.5">{body}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
