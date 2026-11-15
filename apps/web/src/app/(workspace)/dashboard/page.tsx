import type { Metadata } from "next";
import Link from "next/link";
import { Database, Plus, Sparkles } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { EmptyState, PageHeader } from "@/components/workspace/page-header";
import { engineFetch, requireUser } from "@/lib/server/auth";
import { formatBytes } from "@/lib/format";

export const metadata: Metadata = { title: "Overview" };

type Overview = {
  dataset_count: number;
  analysis_count: number;
  conversation_count: number;
  storage_bytes: number;
  storage_limit_bytes: number;
  recent_datasets: { id: string; name: string; status: string; row_count: number; column_count: number; is_sample: boolean }[];
  recent_conversations: { id: string; title: string; dataset_id: string; updated_at: string }[];
};

async function loadOverview(): Promise<Overview | null> {
  try {
    const res = await engineFetch("/api/overview");
    return res.ok ? ((await res.json()) as Overview) : null;
  } catch {
    return null;
  }
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border bg-card p-5">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-2 text-2xl font-semibold tabular-nums tracking-tight">{value}</p>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

export default async function DashboardPage() {
  const user = await requireUser();
  const data = await loadOverview();

  return (
    <>
      <PageHeader
        title={`Welcome${user.display_name ? `, ${user.display_name}` : ""}`}
        description="Your datasets and analytical activity."
        action={
          <Link href="/analyst" className={buttonVariants({ size: "lg" })}>
            <Plus /> Start a New Analysis
          </Link>
        }
      />

      {!data ? (
        <EmptyState
          title="Could not load your workspace data"
          body="The analytics engine is not responding. It may be waking up on the free hosting tier. Refresh in a few seconds."
        />
      ) : (
        <div className="space-y-8">
          <div className="grid gap-4 sm:grid-cols-3">
            <Stat label="Datasets" value={String(data.dataset_count)} />
            <Stat label="Analyses" value={String(data.analysis_count)} hint={`${data.conversation_count} conversation${data.conversation_count === 1 ? "" : "s"}`} />
            <Stat
              label="Storage used"
              value={formatBytes(data.storage_bytes)}
              hint={`of ${formatBytes(data.storage_limit_bytes)} per account`}
            />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <section aria-labelledby="recent-datasets">
              <div className="mb-3 flex items-center justify-between">
                <h2 id="recent-datasets" className="text-sm font-semibold">Recent datasets</h2>
                <Link href="/datasets" className="text-sm text-muted-foreground hover:text-foreground">View all</Link>
              </div>
              {data.recent_datasets.length === 0 ? (
                <EmptyState
                  title="No datasets yet"
                  body="Upload a CSV to profile it and start asking questions."
                  action={
                    <Link href="/datasets" className={buttonVariants({ variant: "outline" })}>
                      <Database /> Go to datasets
                    </Link>
                  }
                />
              ) : (
                <ul className="divide-y rounded-lg border bg-card">
                  {data.recent_datasets.map((d) => (
                    <li key={d.id}>
                      <Link href={`/datasets/${d.id}`} className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-accent/50">
                        <span className="min-w-0 truncate text-sm font-medium">{d.name}</span>
                        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                          {d.row_count.toLocaleString("en-GB")} rows · {d.column_count} cols
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-labelledby="recent-activity">
              <div className="mb-3 flex items-center justify-between">
                <h2 id="recent-activity" className="text-sm font-semibold">Recent analytical activity</h2>
                <Link href="/history" className="text-sm text-muted-foreground hover:text-foreground">View all</Link>
              </div>
              {data.recent_conversations.length === 0 ? (
                <EmptyState
                  title="No analyses yet"
                  body="Questions you ask the AI Analyst, and the insights they produce, will appear here."
                  action={
                    <Link href="/analyst" className={buttonVariants({ variant: "outline" })}>
                      <Sparkles /> Open AI Analyst
                    </Link>
                  }
                />
              ) : (
                <ul className="divide-y rounded-lg border bg-card">
                  {data.recent_conversations.map((c) => (
                    <li key={c.id}>
                      <Link href={`/analyst?c=${c.id}`} className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-accent/50">
                        <span className="min-w-0 truncate text-sm font-medium">{c.title}</span>
                        <time dateTime={c.updated_at} className="shrink-0 text-xs text-muted-foreground">
                          {new Date(c.updated_at).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
                        </time>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </div>
      )}
    </>
  );
}
