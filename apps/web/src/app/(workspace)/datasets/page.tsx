import type { Metadata } from "next";
import { PageHeader, PendingFeature } from "@/components/workspace/page-header";

export const metadata: Metadata = { title: "My Datasets" };

export default function DatasetsPage() {
  return (
    <>
      <PageHeader title="My Datasets" description="Upload, preview, profile and clean your data." />
      <PendingFeature phase="Phase 2" summary="CSV upload, previews, the data quality report and approved cleaning operations are the next piece being built." />
    </>
  );
}
