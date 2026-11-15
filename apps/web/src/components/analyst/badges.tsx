import { AlertTriangle, CheckCircle2, CircleDashed, HelpCircle, XCircle } from "lucide-react";
import { VALIDATION_LABEL, type CheckStatus, type ValidationStatus } from "@/lib/analyst";
import { cn } from "@/lib/utils";

const BASE = "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap";

const VSTYLE: Record<ValidationStatus, { cls: string; icon: typeof CheckCircle2 }> = {
  verified: { cls: "border-success/30 bg-success/10 text-success", icon: CheckCircle2 },
  partially_verified: { cls: "border-warning/40 bg-warning/15 text-foreground", icon: AlertTriangle },
  unverified: { cls: "border-border bg-muted text-muted-foreground", icon: HelpCircle },
  failed: { cls: "border-destructive/30 bg-destructive/10 text-destructive", icon: XCircle },
  not_validated: { cls: "border-dashed border-border text-muted-foreground", icon: CircleDashed },
};

export function ValidationBadge({ status, className }: { status: ValidationStatus; className?: string }) {
  const { cls, icon: Icon } = VSTYLE[status];
  return (
    <span className={cn(BASE, cls, className)}>
      <Icon className="size-3.5" />
      {VALIDATION_LABEL[status]}
    </span>
  );
}

const CSTYLE: Record<CheckStatus, string> = {
  verified: "border-success/30 bg-success/10 text-success",
  failed: "border-destructive/30 bg-destructive/10 text-destructive",
  unverified: "border-border bg-muted text-muted-foreground",
  warning: "border-warning/40 bg-warning/15 text-foreground",
};

export function CheckBadge({ status }: { status: CheckStatus }) {
  return <span className={cn(BASE, CSTYLE[status])}>{status[0].toUpperCase() + status.slice(1)}</span>;
}

export function RunStatusBadge({ status }: { status: "success" | "rejected" | "error" }) {
  const cls = status === "success" ? CSTYLE.verified : status === "rejected" ? CSTYLE.warning : CSTYLE.failed;
  return <span className={cn(BASE, cls)}>{status === "success" ? "Success" : status === "rejected" ? "Rejected" : "Error"}</span>;
}

export const VALIDATION_EXPLANATION: Record<ValidationStatus, string> = {
  verified: "Every check recalculated by a separate route matched.",
  partially_verified: "Some figures were independently confirmed. Others could not be, and are labelled below.",
  unverified: "No figure could be independently confirmed. Treat the numbers as the AI's unchecked output.",
  failed: "At least one independent recalculation disagreed with the reported figure. Do not rely on it until resolved.",
  not_validated: "No independent checks were run for this answer.",
};
