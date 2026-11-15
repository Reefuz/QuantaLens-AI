import type { Metadata } from "next";
import { HistoryView } from "@/components/history/history-view";
import { PageHeader } from "@/components/workspace/page-header";
import { loadReadyDatasets } from "@/lib/server/datasets";

export const metadata: Metadata = { title: "Analysis History" };

export default async function HistoryPage() {
  return (
    <>
      <PageHeader title="Analysis History" description="Every question you have asked, with its answer, the SQL and Python behind it, and its validation status." />
      <HistoryView datasets={await loadReadyDatasets()} mode="history" />
    </>
  );
}
