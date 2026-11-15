import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DatasetView } from "@/components/datasets/dataset-view";
import { EmptyState } from "@/components/workspace/page-header";
import { engineFetch } from "@/lib/server/auth";
import type { DatasetDetail } from "@/lib/datasets";

export const metadata: Metadata = { title: "Dataset" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function DatasetPage({ params }: PageProps<"/datasets/[id]">) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  let res: Response;
  try {
    res = await engineFetch(`/api/datasets/${id}`);
  } catch {
    return <EmptyState title="Could not load this dataset" body="The analytics engine is not responding. It may be waking up on the free hosting tier. Refresh in a few seconds." />;
  }
  if (res.status === 404) notFound();
  if (!res.ok) return <EmptyState title="Could not load this dataset" body="Something went wrong. Please refresh and try again." />;
  return <DatasetView initial={(await res.json()) as DatasetDetail} />;
}
