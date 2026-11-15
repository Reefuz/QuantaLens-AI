import type { Metadata } from "next";
import { PageHeader, PendingFeature } from "@/components/workspace/page-header";

export const metadata: Metadata = { title: "AI Analyst" };

export default function AnalystPage() {
  return (
    <>
      <PageHeader title="AI Analyst" description="Ask questions about your data in plain English." />
      <PendingFeature phase="Phase 3" summary="The agent, SQL and Python execution, charts and validation need datasets first. They follow dataset ingestion." />
    </>
  );
}
