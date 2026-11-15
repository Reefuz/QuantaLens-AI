import type { Metadata } from "next";
import { PageHeader, PendingFeature } from "@/components/workspace/page-header";

export const metadata: Metadata = { title: "Analysis History" };

export default function HistoryPage() {
  return (
    <>
      <PageHeader title="Analysis History" description="Revisit and continue previous analyses." />
      <PendingFeature phase="Phase 5" summary="History appears here once you have run analyses." />
    </>
  );
}
