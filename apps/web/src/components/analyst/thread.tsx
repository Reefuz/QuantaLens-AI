"use client";

import { useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowUp, Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ChatMessage, Step } from "@/lib/analyst";
import { AnswerView } from "./answer-view";
import { RunTimeline } from "./run-timeline";

const MAX = 2000;

export type LiveRun = { steps: Step[]; notice: string | null };

export function Thread({
  messages, live, error, onAsk, onInspect, selectedId, running, canAsk, disabledReason, starters,
}: {
  messages: ChatMessage[];
  live: LiveRun | null;
  error: string | null;
  onAsk: (q: string) => void;
  onInspect: (messageId: string, tab: string) => void;
  selectedId: string | null;
  running: boolean;
  canAsk: boolean;
  disabledReason: string | null;
  starters: string[];
}) {
  const [text, setText] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = scroller.current;
    if (el && stick.current) el.scrollTo({ top: el.scrollHeight });
  }, [messages, live]);

  function submit() {
    const q = text.trim();
    if (!q || running || !canAsk) return;
    setText("");
    stick.current = true;
    onAsk(q);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        ref={scroller}
        className="min-h-0 flex-1 overflow-y-auto px-4 py-6 md:px-8"
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
        }}
      >
        <div className="mx-auto max-w-3xl space-y-6">
          {messages.length === 0 && !live && (
            <div className="space-y-4 py-10">
              <div>
                <h2 className="text-lg font-semibold tracking-tight">Ask a question about your data</h2>
                <p className="mt-1 max-w-xl text-sm text-muted-foreground">The analyst plans the work, runs real SQL and Python, checks its own figures and shows you everything it did.</p>
              </div>
              {starters.length > 0 && (
                <div className="flex flex-col items-start gap-2">
                  {starters.map((q) => (
                    <Button key={q} variant="outline" disabled={!canAsk || running} onClick={() => onAsk(q)} className="h-auto whitespace-normal py-1.5 text-left"><Sparkles /> {q}</Button>
                  ))}
                </div>
              )}
            </div>
          )}

          {messages.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="flex justify-end">
                <p className="max-w-[85%] rounded-lg bg-primary px-4 py-2.5 text-sm text-primary-foreground whitespace-pre-wrap">{m.content}</p>
              </div>
            ) : m.payload?.type === "answer" ? (
              <div key={m.id} className={m.id === selectedId ? "rounded-lg ring-1 ring-brand/40" : ""}>
                <AnswerView payload={m.payload} disabled={running || !canAsk} onAsk={onAsk} onInspect={(tab) => onInspect(m.id, tab)} />
              </div>
            ) : m.payload?.type === "clarification" ? (
              <div key={m.id} className="space-y-3 rounded-lg border bg-card p-5">
                <p className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">The analyst needs one detail</p>
                <p className="text-sm">{m.payload.question}</p>
                {m.payload.options && m.payload.options.length > 0 && (
                  <div className="flex flex-wrap gap-2">{m.payload.options.map((o) => <Button key={o} variant="outline" size="sm" disabled={running || !canAsk} onClick={() => onAsk(o)}>{o}</Button>)}</div>
                )}
              </div>
            ) : (
              <div key={m.id} role="alert" className="flex gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4">
                <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
                <div className="space-y-1">
                  <p className="text-sm font-medium">The analysis did not complete</p>
                  <p className="text-sm text-muted-foreground">{m.payload?.error ?? m.content}</p>
                  {m.payload && m.payload.sql.length + m.payload.python.length > 0 && <button type="button" className="text-xs underline underline-offset-2" onClick={() => onInspect(m.id, "overview")}>Inspect what ran before it stopped</button>}
                </div>
              </div>
            ),
          )}

          {live && (
            <div className="space-y-2 rounded-lg border bg-card p-4" aria-live="polite" aria-label="Analysis in progress">
              <p className="flex items-center gap-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase"><Loader2 className="size-3.5 animate-spin" /> Working on it</p>
              <RunTimeline steps={live.steps} compact />
              {live.notice && <p className="rounded-md border border-warning/40 bg-warning/10 px-3 py-1.5 text-xs">{live.notice}</p>}
            </div>
          )}
          {error && (
            <div role="alert" className="flex gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4">
              <AlertCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
              <p className="text-sm">{error}</p>
            </div>
          )}
        </div>
      </div>

      <div className="border-t bg-background px-4 py-3 md:px-8">
        <div className="mx-auto max-w-3xl">
          {disabledReason && <p className="mb-2 text-xs text-muted-foreground">{disabledReason}</p>}
          <div className="flex items-end gap-2 rounded-lg border bg-card p-2 focus-within:ring-2 focus-within:ring-ring/40">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value.slice(0, MAX))}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }}
              rows={2}
              placeholder={canAsk ? "Ask about trends, segments, risks, anomalies…" : "Asking is unavailable right now"}
              aria-label="Your question"
              disabled={!canAsk || running}
              className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-muted-foreground disabled:opacity-60"
            />
            <Button size="icon-lg" aria-label="Send question" disabled={!text.trim() || running || !canAsk} onClick={submit}>{running ? <Loader2 className="animate-spin" /> : <ArrowUp />}</Button>
          </div>
          <p className="mt-1.5 text-[11px] text-muted-foreground">Enter to send, Shift+Enter for a new line. {text.length > 1500 ? `${MAX - text.length} characters left.` : ""}</p>
        </div>
      </div>
    </div>
  );
}
