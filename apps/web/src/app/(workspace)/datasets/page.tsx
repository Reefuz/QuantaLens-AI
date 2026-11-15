import type { Metadata } from "next";
import { DatasetsView } from "@/components/datasets/datasets-view";
import { EmptyState, PageHeader } from "@/components/workspace/page-header";
import { engineFetch } from "@/lib/server/auth";
import type { Dataset } from "@/lib/datasets";

export const metadata: Metadata = { title: "My Datasets" };

export default async function DatasetsPage() {
  let initial: Dataset[] | null = null;
  try {
    const res = await engineFetch("/api/datasets");
    if (res.ok) initial = (await res.json()) as Dataset[];
  } catch {
    /* engine unreachable: handled below */
  }
  return (
    <>
      <PageHeader title="My Datasets" description="Upload, inspect and clean your data. Originals are never modified." />
      {initial === null ? (
        <EmptyState title="Could not load your datasets" body="The analytics engine is not responding. It may be waking up on the free hosting tier. Refresh in a few seconds." />
      ) : (
        <DatasetsView initial={initial} />
      )}
    </>
  );
}
