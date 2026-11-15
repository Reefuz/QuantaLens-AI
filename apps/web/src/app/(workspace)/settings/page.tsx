import type { Metadata } from "next";
import { SettingsView } from "@/components/settings/settings-view";
import { EmptyState, PageHeader } from "@/components/workspace/page-header";
import type { AccountSettings } from "@/lib/history";
import { engineFetch } from "@/lib/server/auth";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage() {
  let initial: AccountSettings | null = null;
  try {
    const res = await engineFetch("/api/settings");
    if (res.ok) initial = (await res.json()) as AccountSettings;
  } catch {
    /* handled below */
  }
  return (
    <>
      <PageHeader title="Settings" description="Your account, security and data." />
      {initial ? <SettingsView initial={initial} /> : <EmptyState title="Could not load your settings" body="The analytics engine is not responding. Refresh in a few seconds." />}
    </>
  );
}
