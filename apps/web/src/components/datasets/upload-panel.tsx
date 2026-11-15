"use client";

import { useRef, useState, type DragEvent } from "react";
import { FileSpreadsheet, Loader2, Sparkles, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { createSample, MAX_UPLOAD_MB, uploadDataset, type Dataset } from "@/lib/datasets";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

type Stage = { file: string; size: number; fraction: number; phase: "uploading" | "validating" };

export function UploadPanel({ onCreated }: { onCreated: (d: Dataset) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [stage, setStage] = useState<Stage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [sampling, setSampling] = useState(false);
  const busy = stage !== null || sampling;

  async function start(file: File) {
    setError(null);
    if (!file.name.toLowerCase().endsWith(".csv")) return setError("Only .csv files are supported.");
    if (file.size === 0) return setError("That file is empty.");
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return setError(`That file is ${formatBytes(file.size)}. The limit is ${MAX_UPLOAD_MB} MB.`);
    setStage({ file: file.name, size: file.size, fraction: 0, phase: "uploading" });
    try {
      const created = await uploadDataset(file, "", (fraction) =>
        setStage((s) => (s ? { ...s, fraction, phase: fraction >= 1 ? "validating" : "uploading" } : s)),
      );
      onCreated(created);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The upload failed. Please try again.");
    } finally {
      setStage(null);
      if (input.current) input.current.value = "";
    }
  }

  async function useSample() {
    setError(null);
    setSampling(true);
    try {
      onCreated(await createSample());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create the sample dataset.");
    } finally {
      setSampling(false);
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file && !busy) void start(file);
  }

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          "flex flex-col items-center gap-3 rounded-lg border border-dashed px-6 py-10 text-center transition-colors",
          dragging ? "border-brand bg-brand/5" : "bg-card",
        )}
      >
        {stage ? (
          <div className="w-full max-w-md space-y-3 text-left">
            <div className="flex items-center gap-2 text-sm">
              <FileSpreadsheet className="size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate font-medium">{stage.file}</span>
              <span className="text-xs text-muted-foreground tabular-nums">{formatBytes(stage.size)}</span>
            </div>
            <div
              role="progressbar"
              aria-valuenow={Math.round(stage.fraction * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
              className="h-1.5 overflow-hidden rounded-full bg-muted"
            >
              <div className="h-full bg-brand transition-[width]" style={{ width: `${Math.round(stage.fraction * 100)}%` }} />
            </div>
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" />
              {stage.phase === "uploading" ? `Uploading ${Math.round(stage.fraction * 100)}%` : "Upload complete. Validating and reading the file…"}
            </p>
          </div>
        ) : (
          <>
            <Upload className="size-5 text-muted-foreground" />
            <div>
              <p className="text-sm font-medium">Drop a CSV file here</p>
              <p className="mt-1 text-xs text-muted-foreground">Up to {MAX_UPLOAD_MB} MB. Your original file is never modified.</p>
            </div>
            <div className="flex flex-wrap justify-center gap-2">
              <Button onClick={() => input.current?.click()} disabled={busy}>
                <Upload /> Choose CSV file
              </Button>
              <Button variant="outline" onClick={useSample} disabled={busy}>
                {sampling ? <Loader2 className="animate-spin" /> : <Sparkles />}
                Use sample dataset
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">The sample is synthetic banking data with deliberate quality problems.</p>
          </>
        )}
        <input
          ref={input}
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          aria-label="Choose a CSV file"
          onChange={(e) => e.target.files?.[0] && void start(e.target.files[0])}
        />
      </div>
      {error && (
        <p role="alert" className="flex items-start justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
          <button type="button" aria-label="Dismiss" onClick={() => setError(null)}>
            <X className="size-4" />
          </button>
        </p>
      )}
    </div>
  );
}
