"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowLeft, Check, Loader2, Pencil, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePolling } from "@/hooks/use-polling";
import { ApiError } from "@/lib/api";
import { deleteDataset, getDataset, renameDataset, type Dataset, type DatasetDetail } from "@/lib/datasets";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { StatusBadge } from "./badges";
import { ColumnsView } from "./columns-view";
import { DataTable } from "./data-table";
import { HistoryView, QualityView } from "./quality-view";

type Version = "original" | "cleaned";

function VersionToggle({ value, onChange }: { value: Version; onChange: (v: Version) => void }) {
  return (
    <div role="group" aria-label="Dataset version" className="inline-flex rounded-md border p-0.5 text-sm">
      {(["original", "cleaned"] as const).map((v) => (
        <button
          key={v}
          type="button"
          aria-pressed={value === v}
          onClick={() => onChange(v)}
          className={cn("rounded px-2.5 py-1 capitalize", value === v ? "bg-accent font-medium" : "text-muted-foreground hover:text-foreground")}
        >
          {v}
        </button>
      ))}
    </div>
  );
}

export function DatasetView({ initial }: { initial: DatasetDetail }) {
  const router = useRouter();
  const [detail, setDetail] = useState(initial);
  const [version, setVersion] = useState<Version>("original");
  const [tab, setTab] = useState("preview");
  const [renaming, setRenaming] = useState(false);
  const [draftName, setDraftName] = useState(initial.name);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const working = detail.status === "processing" || detail.status === "cleaning";
  usePolling(async () => setDetail(await getDataset(detail.id)), working);

  function merge(d: Dataset) {
    setDetail((prev) => ({ ...prev, ...d }));
  }

  async function saveName() {
    const name = draftName.trim();
    if (!name || name === detail.name) return setRenaming(false);
    setBusy(true);
    try {
      merge(await renameDataset(detail.id, name));
      setRenaming(false);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not rename the dataset.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await deleteDataset(detail.id);
      router.replace("/datasets");
      router.refresh();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not delete the dataset.");
      setBusy(false);
    }
  }

  const ready = detail.status === "ready";
  const shownVersion: Version = version === "cleaned" && detail.has_cleaned ? "cleaned" : "original";

  return (
    <div className="space-y-6">
      <div>
        <Link href="/datasets" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
          <ArrowLeft className="size-3.5" /> My Datasets
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            {renaming ? (
              <form
                className="flex items-center gap-2"
                onSubmit={(e) => {
                  e.preventDefault();
                  void saveName();
                }}
              >
                <Input value={draftName} onChange={(e) => setDraftName(e.target.value)} maxLength={200} aria-label="Dataset name" className="h-9 w-72 text-base" autoFocus onKeyDown={(e) => e.key === "Escape" && setRenaming(false)} />
                <Button type="submit" size="icon" aria-label="Save name" disabled={busy}>
                  <Check />
                </Button>
                <Button type="button" variant="ghost" size="icon" aria-label="Cancel rename" onClick={() => setRenaming(false)}>
                  <X />
                </Button>
              </form>
            ) : (
              <div className="flex items-center gap-2">
                <h1 className="truncate text-xl font-semibold tracking-tight md:text-2xl">{detail.name}</h1>
                <Button variant="ghost" size="icon-sm" aria-label="Rename dataset" onClick={() => { setDraftName(detail.name); setRenaming(true); }}>
                  <Pencil />
                </Button>
              </div>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground">
              <StatusBadge status={detail.status} />
              {ready && (
                <span className="tabular-nums">
                  {detail.row_count.toLocaleString("en-GB")} rows · {detail.column_count} columns · {formatBytes(detail.size_bytes)}
                </span>
              )}
              {detail.is_sample && <span>Synthetic demonstration data</span>}
              {detail.original_filename && <span className="truncate">{detail.original_filename}</span>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {confirmDelete ? (
              <>
                <span className="text-sm text-muted-foreground">Delete this dataset and everything derived from it?</span>
                <Button variant="destructive" onClick={remove} disabled={busy}>
                  {busy ? <Loader2 className="animate-spin" /> : <Trash2 />} Delete
                </Button>
                <Button variant="ghost" onClick={() => setConfirmDelete(false)} disabled={busy}>
                  Cancel
                </Button>
              </>
            ) : (
              <Button variant="outline" onClick={() => setConfirmDelete(true)}>
                <Trash2 /> Delete
              </Button>
            )}
          </div>
        </div>
        {error && <p role="alert" className="mt-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</p>}
        {detail.warnings.length > 0 && detail.status === "ready" && tab !== "quality" && (
          <p className="mt-3 text-sm text-muted-foreground">
            {detail.warnings.length} note{detail.warnings.length === 1 ? "" : "s"} about how the file was read. See the Data quality tab.
          </p>
        )}
      </div>

      {detail.status === "processing" && (
        <p className="flex items-center gap-2 rounded-lg border bg-card p-4 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Reading, profiling and storing your data. This usually takes a few seconds.
        </p>
      )}
      {detail.status === "failed" && <p role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">{detail.error}</p>}

      {(ready || detail.status === "cleaning") && (
        <Tabs value={tab} onValueChange={(v) => setTab(String(v))}>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-2">
            <TabsList variant="line" className="h-auto gap-1 p-0">
              <TabsTrigger value="preview" className="flex-none px-3 py-1.5">Preview</TabsTrigger>
              <TabsTrigger value="columns" className="flex-none px-3 py-1.5">Columns</TabsTrigger>
              <TabsTrigger value="quality" className="flex-none px-3 py-1.5">Data quality</TabsTrigger>
              <TabsTrigger value="history" className="flex-none px-3 py-1.5">Cleaning history</TabsTrigger>
            </TabsList>
            {detail.has_cleaned && (tab === "preview" || tab === "columns") && <VersionToggle value={shownVersion} onChange={setVersion} />}
          </div>
          <TabsContent value="preview" className="pt-4">
            {detail.status === "cleaning" && <p className="mb-3 flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" /> Building the cleaned version…</p>}
            <DataTable key={shownVersion} datasetId={detail.id} version={shownVersion} />
          </TabsContent>
          <TabsContent value="columns" className="pt-4">
            {shownVersion === "cleaned" && detail.cleaned_columns ? (
              <ColumnsView columns={detail.cleaned_columns} note="Types in the cleaned version, after your approved operations." />
            ) : (
              <ColumnsView columns={detail.columns} note="The original file keeps every value as text, exactly as uploaded. Detected types describe what each column appears to contain." />
            )}
          </TabsContent>
          <TabsContent value="quality" className="pt-4">
            <QualityView dataset={detail} onDatasetChange={merge} />
          </TabsContent>
          <TabsContent value="history" className="pt-4">
            <HistoryView datasetId={detail.id} refreshKey={`${detail.status}-${detail.has_cleaned}`} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
