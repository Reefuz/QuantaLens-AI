import type { Metadata } from "next";
import { HistoryView } from "@/components/history/history-view";
import { PageHeader } from "@/components/workspace/page-header";
import { loadReadyDatasets } from "@/lib/server/datasets";

export const metadata: Metadata = { title: "Reports" };

export default async function ReportsPage() {
  return (
    <>
      <PageHeader title="Reports" description="Export any answered analysis as a PDF report, an Excel workbook, or a CSV of any result. Exports contain the actual stored results, queries, code and validation." />
      <HistoryView datasets={await loadReadyDatasets()} mode="reports" />
    </>
  );
}
