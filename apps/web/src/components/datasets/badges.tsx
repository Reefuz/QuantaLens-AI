import { cn } from "@/lib/utils";
import type { DatasetStatus, OpStatus, Severity } from "@/lib/datasets";

const base = "inline-flex items-center rounded-md border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap";

const SEVERITY: Record<Severity, string> = {
  high: "border-destructive/30 bg-destructive/10 text-destructive",
  medium: "border-warning/40 bg-warning/15 text-foreground",
  low: "border-border bg-muted text-muted-foreground",
  info: "border-border text-muted-foreground",
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={cn(base, SEVERITY[severity])}>{severity === "info" ? "Info" : `${severity[0].toUpperCase()}${severity.slice(1)}`}</span>;
}

const STATUS: Record<DatasetStatus, { label: string; cls: string }> = {
  processing: { label: "Processing", cls: "border-warning/40 bg-warning/15" },
  cleaning: { label: "Cleaning", cls: "border-warning/40 bg-warning/15" },
  ready: { label: "Ready", cls: "border-success/30 bg-success/10 text-success" },
  failed: { label: "Failed", cls: "border-destructive/30 bg-destructive/10 text-destructive" },
};

export function StatusBadge({ status }: { status: DatasetStatus }) {
  const s = STATUS[status];
  return <span className={cn(base, s.cls)}>{s.label}</span>;
}

const OP: Record<OpStatus, { label: string; cls: string }> = {
  proposed: { label: "Awaiting review", cls: "border-border text-muted-foreground" },
  approved: { label: "Approved", cls: "border-brand/40 bg-brand/10 text-brand" },
  rejected: { label: "Rejected", cls: "border-border bg-muted text-muted-foreground line-through" },
  applied: { label: "Applied", cls: "border-success/30 bg-success/10 text-success" },
};

export function OpStatusBadge({ status }: { status: OpStatus }) {
  const s = OP[status];
  return <span className={cn(base, s.cls)}>{s.label}</span>;
}
