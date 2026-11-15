"use client";

import Link from "next/link";
import { useState } from "react";
import { Database } from "lucide-react";
import { usePolling } from "@/hooks/use-polling";
import { listDatasets, type Dataset } from "@/lib/datasets";
import { formatBytes } from "@/lib/format";
import { EmptyState } from "@/components/workspace/page-header";
import { StatusBadge } from "./badges";
import { UploadPanel } from "./upload-panel";

export function DatasetsView({ initial }: { initial: Dataset[] }) {
  const [datasets, setDatasets] = useState(initial);
  const active = datasets.some((d) => d.status === "processing" || d.status === "cleaning");

  const refresh = async () => setDatasets(await listDatasets());
  usePolling(refresh, active);

  return (
    <div className="space-y-8">
      <UploadPanel onCreated={(d) => setDatasets((prev) => [d, ...prev.filter((p) => p.id !== d.id)])} />

      <section aria-labelledby="your-datasets">
        <h2 id="your-datasets" className="mb-3 text-sm font-semibold">
          Your datasets
        </h2>
        {datasets.length === 0 ? (
          <EmptyState title="No datasets yet" body="Upload a CSV above, or start with the sample dataset to see profiling and cleaning on real data." />
        ) : (
          <div className="overflow-x-auto rounded-lg border bg-card">
            <table className="w-full text-sm">
              <thead className="border-b text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Name</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 text-right font-medium">Rows</th>
                  <th className="px-4 py-2.5 text-right font-medium">Columns</th>
                  <th className="hidden px-4 py-2.5 text-right font-medium sm:table-cell">Size</th>
                  <th className="hidden px-4 py-2.5 font-medium md:table-cell">Uploaded</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {datasets.map((d) => (
                  <tr key={d.id} className="hover:bg-accent/40">
                    <td className="px-4 py-3">
                      <Link href={`/datasets/${d.id}`} className="flex items-center gap-2 font-medium hover:underline">
                        <Database className="size-4 shrink-0 text-muted-foreground" />
                        <span className="truncate">{d.name}</span>
                        {d.is_sample && <span className="rounded-md border px-1.5 py-0.5 text-[11px] font-normal text-muted-foreground">Synthetic</span>}
                      </Link>
                      {d.status === "failed" && d.error && <p className="mt-1 pl-6 text-xs text-destructive">{d.error}</p>}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={d.status} />
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">{d.status === "ready" ? d.row_count.toLocaleString("en-GB") : "—"}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{d.status === "ready" ? d.column_count : "—"}</td>
                    <td className="hidden px-4 py-3 text-right text-muted-foreground tabular-nums sm:table-cell">{d.size_bytes ? formatBytes(d.size_bytes) : "—"}</td>
                    <td className="hidden px-4 py-3 text-muted-foreground md:table-cell">
                      {new Date(d.created_at).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
