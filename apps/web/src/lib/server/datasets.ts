import { engineFetch } from "@/lib/server/auth";
import type { Dataset } from "@/lib/datasets";

export async function loadReadyDatasets(): Promise<Dataset[]> {
  try {
    const res = await engineFetch("/api/datasets");
    return res.ok ? ((await res.json()) as Dataset[]).filter((d) => d.status === "ready") : [];
  } catch {
    return [];
  }
}
