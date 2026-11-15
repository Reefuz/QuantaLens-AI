import type { Metadata } from "next";
import { AnalystWorkspace } from "@/components/analyst/analyst-workspace";
import { EmptyState } from "@/components/workspace/page-header";
import type { ConversationDetail } from "@/lib/analyst";
import type { Dataset } from "@/lib/datasets";
import { engineFetch } from "@/lib/server/auth";

export const metadata: Metadata = { title: "AI Analyst" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : undefined);

export default async function AnalystPage({ searchParams }: PageProps<"/analyst">) {
  const sp = await searchParams;
  const d = one(sp.d), c = one(sp.c);
  let datasets: Dataset[] | null = null;
  let aiConfigured = false;
  let conversation: ConversationDetail | null = null;
  try {
    const [dsRes, statusRes] = await Promise.all([engineFetch("/api/datasets"), engineFetch("/api/analyst/status")]);
    if (dsRes.ok) datasets = ((await dsRes.json()) as Dataset[]).filter((x) => x.status === "ready");
    if (statusRes.ok) aiConfigured = Boolean(((await statusRes.json()) as { ai_configured: boolean }).ai_configured);
    if (c && UUID.test(c)) {
      const cr = await engineFetch(`/api/conversations/${c}`);
      if (cr.ok) conversation = (await cr.json()) as ConversationDetail;
    }
  } catch {
    /* handled below */
  }
  // Same negative margins as the workspace padding, so the analyst can use the full area.
  const frame = "-mx-4 -my-6 h-[calc(100dvh-3.5rem-3rem)] md:-mx-8 md:-my-8 md:h-[calc(100dvh-3.5rem)]";
  if (datasets === null) {
    return <div className="p-6"><EmptyState title="Could not load the analyst" body="The analytics engine is not responding. It may be waking up on the free hosting tier. Refresh in a few seconds." /></div>;
  }
  const datasetId = conversation?.conversation.dataset_id ?? (d && datasets.some((x) => x.id === d) ? d : datasets[0]?.id ?? null);
  return (
    <div className={frame}>
      <AnalystWorkspace
        key={`${datasetId}-${conversation?.conversation.id ?? "new"}`}
        datasets={datasets}
        initialDatasetId={datasetId}
        initialMessages={conversation?.messages ?? []}
        initialConversationId={conversation?.conversation.id ?? null}
        initialRunning={conversation?.running ?? false}
        initialTitle={conversation?.conversation.title ?? null}
        aiConfigured={aiConfigured}
      />
    </div>
  );
}
