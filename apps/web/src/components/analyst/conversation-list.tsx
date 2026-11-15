"use client";

import { useState } from "react";
import { Check, MessageSquare, Pencil, Plus, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Dataset } from "@/lib/datasets";
import type { Conversation } from "@/lib/analyst";
import { cn } from "@/lib/utils";

function when(iso: string) {
  const d = new Date(iso);
  const same = d.toDateString() === new Date().toDateString();
  return same ? d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function ConversationList({
  datasets, datasetId, onDataset, conversations, activeId, onOpen, onNew, onRename, onDelete, busy,
}: {
  datasets: Dataset[];
  datasetId: string | null;
  onDataset: (id: string) => void;
  conversations: Conversation[];
  activeId: string | null;
  onOpen: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  busy: boolean;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 border-b p-3">
        <label htmlFor="dataset-select" className="text-xs font-medium text-muted-foreground">Dataset</label>
        <select id="dataset-select" value={datasetId ?? ""} onChange={(e) => onDataset(e.target.value)} disabled={busy} className="h-8 w-full rounded-md border bg-background px-2 text-sm">
          {datasets.map((d) => <option key={d.id} value={d.id}>{d.name}{d.has_cleaned ? " (cleaned)" : ""}</option>)}
        </select>
        <Button className="w-full" onClick={onNew} disabled={busy || !datasetId}><Plus /> New analysis</Button>
      </div>
      <nav aria-label="Conversations" className="min-h-0 flex-1 overflow-y-auto p-2">
        {conversations.length === 0 ? (
          <p className="px-2 py-6 text-center text-xs text-muted-foreground">No analyses for this dataset yet. Ask a question to start one.</p>
        ) : (
          <ul className="space-y-0.5">
            {conversations.map((c) => (
              <li key={c.id}>
                {editing === c.id ? (
                  <form className="flex items-center gap-1 p-1" onSubmit={async (e) => { e.preventDefault(); await onRename(c.id, draft); setEditing(null); }}>
                    <Input value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={200} aria-label="Conversation title" className="h-7 text-xs" autoFocus onKeyDown={(e) => e.key === "Escape" && setEditing(null)} />
                    <Button type="submit" size="icon-xs" aria-label="Save title"><Check /></Button>
                    <Button type="button" size="icon-xs" variant="ghost" aria-label="Cancel rename" onClick={() => setEditing(null)}><X /></Button>
                  </form>
                ) : confirming === c.id ? (
                  <div className="space-y-1.5 rounded-md border border-destructive/30 bg-destructive/5 p-2">
                    <p className="text-xs">Delete this conversation and its results?</p>
                    <div className="flex gap-1.5">
                      <Button size="xs" variant="destructive" onClick={async () => { await onDelete(c.id); setConfirming(null); }}>Delete</Button>
                      <Button size="xs" variant="ghost" onClick={() => setConfirming(null)}>Cancel</Button>
                    </div>
                  </div>
                ) : (
                  <div className={cn("group flex items-center gap-1 rounded-md pr-1", c.id === activeId ? "bg-accent" : "hover:bg-accent/50")}>
                    <button type="button" onClick={() => onOpen(c.id)} aria-current={c.id === activeId ? "true" : undefined} className="flex min-w-0 flex-1 items-start gap-2 px-2 py-1.5 text-left">
                      <MessageSquare className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1"><span className="block truncate text-sm">{c.title}</span><span className="text-[11px] text-muted-foreground">{when(c.updated_at)} · {Math.ceil(c.message_count / 2)} question{Math.ceil(c.message_count / 2) === 1 ? "" : "s"}</span></span>
                    </button>
                    <div className="flex opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                      <Button size="icon-xs" variant="ghost" aria-label={`Rename ${c.title}`} disabled={busy} onClick={() => { setDraft(c.title); setEditing(c.id); }}><Pencil /></Button>
                      <Button size="icon-xs" variant="ghost" aria-label={`Delete ${c.title}`} disabled={busy} onClick={() => setConfirming(c.id)}><Trash2 /></Button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </nav>
    </div>
  );
}
