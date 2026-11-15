import type { ColumnProfile } from "@/lib/datasets";

const KIND_LABEL: Record<ColumnProfile["kind"], string> = {
  empty: "Empty",
  numeric: "Numeric",
  date: "Date",
  categorical: "Category",
  text: "Text",
};

function stats(c: ColumnProfile): string {
  const f = (v: number | string | undefined) => (typeof v === "number" ? v.toLocaleString("en-GB", { maximumFractionDigits: 2 }) : v);
  if (c.kind === "numeric" && c.min !== undefined) return `${f(c.min)} to ${f(c.max)}, mean ${f(c.mean)}, median ${f(c.median)}`;
  if (c.kind === "date" && c.min) return `${c.min} to ${c.max}`;
  return "";
}

export function ColumnsView({ columns, note }: { columns: ColumnProfile[]; note?: string }) {
  return (
    <div className="space-y-3">
      {note && <p className="text-sm text-muted-foreground">{note}</p>}
      <div className="overflow-x-auto rounded-lg border bg-card">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/50 text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-2.5 font-medium">Column</th>
              <th className="px-4 py-2.5 font-medium">Detected type</th>
              <th className="px-4 py-2.5 text-right font-medium">Missing</th>
              <th className="px-4 py-2.5 text-right font-medium">Distinct</th>
              <th className="px-4 py-2.5 font-medium">Range and summary</th>
              <th className="px-4 py-2.5 font-medium">Common values</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {columns.map((c) => (
              <tr key={c.name} className="align-top">
                <td className="px-4 py-2.5">
                  <p className="font-medium">{c.original_name}</p>
                  {c.original_name !== c.name && <p className="font-mono text-xs text-muted-foreground">{c.name}</p>}
                </td>
                <td className="px-4 py-2.5 whitespace-nowrap">
                  {KIND_LABEL[c.kind]}
                  {c.is_identifier && <span className="ml-1.5 rounded-md border px-1.5 py-0.5 text-[11px] text-muted-foreground">ID</span>}
                  {c.db_type && c.db_type !== "text" && <span className="ml-1.5 font-mono text-xs text-muted-foreground">{c.db_type}</span>}
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums whitespace-nowrap">
                  {c.missing_count.toLocaleString("en-GB")}
                  <span className="ml-1 text-xs text-muted-foreground">({c.missing_pct ?? 0}%)</span>
                </td>
                <td className="px-4 py-2.5 text-right tabular-nums">{c.distinct_count.toLocaleString("en-GB")}</td>
                <td className="px-4 py-2.5 text-xs text-muted-foreground">{stats(c)}</td>
                <td className="max-w-xs px-4 py-2.5 text-xs text-muted-foreground">
                  <span className="line-clamp-2">{c.samples.join(", ")}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
