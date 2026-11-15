"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { AlertTriangle, MessagesSquare, PanelRightOpen } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { usePolling } from "@/hooks/use-polling";
import { ApiError } from "@/lib/api";
import {
  askStream, createConversation, deleteConversation, getConversation, listConversations, renameConversation,
  type ChatMessage, type Conversation, type Payload, type Step, type StreamEvent,
} from "@/lib/analyst";
import { getDataset, type Dataset, type DatasetDetail } from "@/lib/datasets";
import { cn } from "@/lib/utils";
import { ConversationList } from "./conversation-list";
import { InspectionPanel } from "./inspection-panel";
import { Thread, type LiveRun } from "./thread";

const GENERIC_STARTERS = ["Give me an overview of this dataset.", "Identify unusual patterns in the data.", "What are the main risks you can see in this data?"];

const WIDE = "(min-width: 1024px)";
const subscribeWide = (cb: () => void) => {
  const mq = window.matchMedia(WIDE);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
};

function setUrl(datasetId: string | null, conversationId: string | null) {
  const q = new URLSearchParams();
  if (datasetId) q.set("d", datasetId);
  if (conversationId) q.set("c", conversationId);
  window.history.replaceState(null, "", `/analyst${q.size ? `?${q}` : ""}`);
}

export function AnalystWorkspace({
  datasets, initialDatasetId, initialMessages, initialConversationId, initialRunning, initialTitle, aiConfigured,
}: {
  datasets: Dataset[];
  initialDatasetId: string | null;
  initialMessages: ChatMessage[];
  initialConversationId: string | null;
  initialRunning: boolean;
  initialTitle: string | null;
  aiConfigured: boolean;
}) {
  const [datasetId, setDatasetId] = useState(initialDatasetId);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState(initialConversationId);
  const [title, setTitle] = useState(initialTitle);
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [live, setLive] = useState<LiveRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [serverRunning, setServerRunning] = useState(initialRunning);
  // The inspection panel sits beside the conversation on wide screens and overlays it on narrow ones, so it starts closed there.
  const isWide = useSyncExternalStore(subscribeWide, () => window.matchMedia(WIDE).matches, () => true);
  const [panelPref, setPanelOpen] = useState<boolean | null>(null);
  const panelOpen = panelPref ?? isWide;
  const [tab, setTab] = useState("overview");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const activeRef = useRef(activeId);
  useEffect(() => { activeRef.current = activeId; }, [activeId]);

  const running = streaming || serverRunning;
  // A run that continues on the server (after a reload or a dropped connection) still shows as work in progress.
  const shownLive: LiveRun | null = live ?? (serverRunning && !streaming ? { steps: [], notice: "This analysis is still running on the server. The answer will appear here when it finishes." } : null);
  const dataset = datasets.find((d) => d.id === datasetId) ?? null;

  const refreshList = useCallback(async (did: string) => {
    try { setConversations(await listConversations(did)); } catch { /* list is non-essential */ }
  }, []);

  useEffect(() => {
    if (!datasetId) return;
    let cancelled = false;
    listConversations(datasetId).then((c) => !cancelled && setConversations(c)).catch(() => {});
    getDataset(datasetId).then((d) => !cancelled && setDetail(d)).catch(() => {});
    return () => { cancelled = true; };
  }, [datasetId]);

  // A conversation that is still running on the server (opened from another tab, or after a dropped connection).
  usePolling(async () => {
    if (!activeRef.current) return;
    const d = await getConversation(activeRef.current);
    setMessages(d.messages);
    if (!d.running) {
      setServerRunning(false);
      setLive(null);
      if (datasetId) void refreshList(datasetId);
    }
  }, serverRunning && !streaming, 2000);

  const latest = useMemo(() => [...messages].reverse().find((m) => m.role === "assistant" && m.payload), [messages]);
  const selected: Payload | null = (messages.find((m) => m.id === selectedId)?.payload ?? latest?.payload) ?? null;

  function resetThread() {
    setActiveId(null); setTitle(null); setMessages([]); setLive(null); setError(null); setSelectedId(null); setServerRunning(false);
  }

  function newAnalysis() {
    resetThread();
    setUrl(datasetId, null);
    setListOpen(false);
  }

  function changeDataset(id: string) {
    setDatasetId(id);
    setConversations([]);
    setDetail(null);
    resetThread();
    setUrl(id, null);
  }

  async function openConversation(id: string) {
    setError(null); setLive(null); setListOpen(false);
    try {
      const d = await getConversation(id);
      setActiveId(id); setTitle(d.conversation.title); setMessages(d.messages); setServerRunning(d.running); setSelectedId(null);
      setUrl(d.conversation.dataset_id, id);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not open that conversation.");
    }
  }

  async function rename(id: string, t: string) {
    const trimmed = t.trim();
    if (!trimmed) return;
    try {
      const c = await renameConversation(id, trimmed);
      setConversations((cs) => cs.map((x) => (x.id === id ? { ...x, title: c.title } : x)));
      if (id === activeId) setTitle(c.title);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not rename the conversation.");
    }
  }

  async function remove(id: string) {
    try {
      await deleteConversation(id);
      setConversations((cs) => cs.filter((x) => x.id !== id));
      if (id === activeId) newAnalysis();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not delete the conversation.");
    }
  }

  async function ask(question: string) {
    if (!datasetId || running) return;
    setError(null);
    let convId = activeId;
    try {
      if (!convId) {
        const c = await createConversation(datasetId);
        convId = c.id;
        setActiveId(c.id); setTitle(c.title);
        setConversations((cs) => [c, ...cs]);
        setUrl(datasetId, c.id);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start a conversation.");
      return;
    }
    const tempId = `temp-${Date.now()}`;
    setMessages((m) => [...m, { id: tempId, role: "user", content: question, payload: null, created_at: new Date().toISOString() }]);
    setLive({ steps: [], notice: null });
    setStreaming(true);
    let started = false;
    const onEvent = (e: StreamEvent) => {
      if (e.type === "start") {
        started = true;
        setMessages((m) => m.map((x) => (x.id === tempId ? e.user_message : x)));
        setTitle(e.title);
        setConversations((cs) => cs.map((c) => (c.id === convId ? { ...c, title: e.title } : c)));
      } else if (e.type === "step") {
        const { type: _t, ...step } = e;
        void _t;
        setLive((l) => {
          const steps = [...(l?.steps ?? [])];
          const i = steps.findIndex((s) => s.id === step.id);
          if (i >= 0) steps[i] = step as Step; else steps.push(step as Step);
          return { steps, notice: l?.notice ?? null };
        });
      } else if (e.type === "notice") {
        setLive((l) => ({ steps: l?.steps ?? [], notice: e.message }));
      } else if (e.type === "final") {
        setMessages((m) => [...m, e.message]);
        setSelectedId(e.message.id);
        setTitle(e.title);
        setConversations((cs) => cs.map((c) => (c.id === convId ? { ...c, title: e.title, updated_at: new Date().toISOString(), message_count: c.message_count + 2 } : c)));
        setLive(null);
      } else if (e.type === "error") {
        setError(e.message);
      }
    };
    try {
      await askStream(convId!, question, onEvent);
    } catch (e) {
      if (!started) {
        setMessages((m) => m.filter((x) => x.id !== tempId));
        setLive(null);
        setError(e instanceof ApiError ? e.message : "Could not reach the server. Check your connection and try again.");
      } else {
        // The connection dropped, but the analysis keeps running on the server and will be saved.
        setServerRunning(true);
      }
    } finally {
      setStreaming(false);
    }
  }

  const disabledReason = !aiConfigured
    ? "The AI analyst is not configured on this server (AI_PROVIDER_API_KEY is not set). You can still explore the data in My Datasets."
    : !dataset ? "Select a dataset to begin." : serverRunning && !streaming ? "An analysis is still running in this conversation. Results will appear here when it finishes." : null;

  if (datasets.length === 0) {
    return (
      <div className="mx-auto max-w-lg space-y-3 px-6 py-16 text-center">
        <h2 className="text-lg font-semibold">You need a dataset first</h2>
        <p className="text-sm text-muted-foreground">Upload a CSV, or use the synthetic banking sample, then come back to ask questions about it.</p>
        <Link href="/datasets" className={buttonVariants()}>Go to My Datasets</Link>
      </div>
    );
  }

  const starters = detail?.suggested_questions?.length ? detail.suggested_questions : GENERIC_STARTERS;

  return (
    <div className="relative flex h-full min-h-0 bg-background">
      {/* Left: dataset, conversations */}
      <div className={cn("w-64 shrink-0 border-r bg-sidebar/50", listOpen ? "absolute inset-y-0 left-0 z-30 w-72 bg-background shadow-xl" : "hidden", "lg:static lg:block lg:w-64 lg:shadow-none")}>
        <ConversationList datasets={datasets} datasetId={datasetId} onDataset={changeDataset} conversations={conversations} activeId={activeId} onOpen={openConversation} onNew={newAnalysis} onRename={rename} onDelete={remove} busy={running} />
      </div>

      {/* Centre: conversation */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between gap-3 border-b px-4 py-2">
          <div className="flex min-w-0 items-center gap-2">
            <Button variant="ghost" size="icon-sm" className="lg:hidden" aria-label="Show conversations" onClick={() => setListOpen(!listOpen)}><MessagesSquare /></Button>
            <div className="min-w-0">
              <h1 className="truncate text-sm font-semibold">{title ?? "New analysis"}</h1>
              <p className="truncate text-xs text-muted-foreground">
                {dataset?.name}{dataset ? (dataset.has_cleaned ? " · cleaned version available" : " · original data") : ""}
              </p>
            </div>
          </div>
          {!panelOpen && <Button variant="outline" size="sm" onClick={() => setPanelOpen(true)}><PanelRightOpen /> Inspect</Button>}
        </div>
        {dataset && !dataset.has_cleaned && (
          <div className="flex items-start gap-2 border-b bg-warning/10 px-4 py-2 text-xs">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
            <p>This dataset has not been cleaned. The analyst works on the original text data, so some figures cannot be independently verified. <Link href={`/datasets/${dataset.id}`} className="font-medium underline underline-offset-2">Review and clean it</Link>.</p>
          </div>
        )}
        <div className="min-h-0 flex-1">
          <Thread
            messages={messages} live={shownLive} error={error} onAsk={ask} running={running} canAsk={aiConfigured && !!dataset && !(serverRunning && !streaming)}
            disabledReason={disabledReason} starters={starters} selectedId={selectedId}
            onInspect={(id, t) => { setSelectedId(id); setTab(t); setPanelOpen(true); }}
          />
        </div>
      </div>

      {/* Right: inspection */}
      {panelOpen && (
        <div className="absolute inset-y-0 right-0 z-30 w-[min(100%,440px)] shadow-xl lg:static lg:z-auto lg:w-[420px] lg:shadow-none">
          <InspectionPanel payload={selected} datasetId={datasetId} tab={tab} onTab={setTab} onClose={() => setPanelOpen(false)} />
        </div>
      )}
    </div>
  );
}
