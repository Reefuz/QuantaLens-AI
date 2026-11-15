import { cn } from "@/lib/utils";

/** QuantaLens mark: a lens ring containing three quantised bars. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className={cn("size-6", className)}
    >
      <circle cx="16" cy="16" r="13" stroke="currentColor" strokeWidth="2.25" />
      <rect x="9.5" y="16" width="3" height="6" rx="0.75" fill="currentColor" />
      <rect x="14.5" y="11.5" width="3" height="10.5" rx="0.75" fill="var(--brand)" />
      <rect x="19.5" y="13.5" width="3" height="8.5" rx="0.75" fill="currentColor" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <LogoMark />
      <span className="text-[15px] font-semibold tracking-tight">
        QuantaLens<span className="text-muted-foreground font-medium"> AI</span>
      </span>
    </span>
  );
}
