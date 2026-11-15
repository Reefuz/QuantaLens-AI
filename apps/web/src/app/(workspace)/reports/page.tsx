import type { Metadata } from "next";
import { PageHeader, PendingFeature } from "@/components/workspace/page-header";

export const metadata: Metadata = { title: "Reports" };

export default function ReportsPage() {
  return (
    <>
      <PageHeader title="Reports" description="Export analyses as PDF, CSV or Excel." />
      <PendingFeature phase="Phase 5" summary="Report export is built after the analysis workspace." />
    </>
  );
}
