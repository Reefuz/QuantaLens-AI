import { Download, FileSpreadsheet, FileText } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { reportUrl } from "@/lib/history";
import { cn } from "@/lib/utils";

/** Plain links: the browser downloads the file the server generates from the stored analysis. */
export function ExportMenu({ messageId, results, size = "sm" }: { messageId: string; results: { id: string; label: string; row_count: number }[]; size?: "sm" | "default" }) {
  const btn = buttonVariants({ variant: "outline", size });
  return (
    <div className="flex flex-wrap items-center gap-2">
      <a href={reportUrl(messageId, "pdf")} download className={btn}><FileText /> PDF report</a>
      <a href={reportUrl(messageId, "xlsx")} download className={btn}><FileSpreadsheet /> Excel</a>
      {results.length > 0 && (
        <details className="relative">
          <summary className={cn(btn, "cursor-pointer list-none [&::-webkit-details-marker]:hidden")}><Download /> CSV</summary>
          <ul className="absolute left-0 z-20 mt-1 max-h-64 min-w-60 overflow-auto rounded-md border bg-popover p-1 text-sm shadow-md">
            {results.map((r) => (
              <li key={r.id}>
                <a href={reportUrl(messageId, "csv", r.id)} download className="flex items-center justify-between gap-3 rounded px-2 py-1.5 hover:bg-accent">
                  <span className="truncate"><span className="font-medium">{r.id}</span> · {r.label || "Result"}</span>
                  <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{r.row_count.toLocaleString("en-GB")} rows</span>
                </a>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
