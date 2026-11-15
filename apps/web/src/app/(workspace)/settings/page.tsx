import type { Metadata } from "next";
import { PageHeader } from "@/components/workspace/page-header";
import { requireUser } from "@/lib/server/auth";

export const metadata: Metadata = { title: "Settings" };

export default async function SettingsPage() {
  const user = await requireUser();
  const rows: [string, string][] = [
    ["Name", user.display_name ?? "Not set"],
    ["Email", user.email],
  ];
  return (
    <>
      <PageHeader title="Settings" description="Your account." />
      <dl className="max-w-xl divide-y rounded-lg border bg-card">
        {rows.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[120px_1fr] gap-4 px-5 py-3.5 text-sm">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className="font-medium break-all">{v}</dd>
          </div>
        ))}
      </dl>
    </>
  );
}
