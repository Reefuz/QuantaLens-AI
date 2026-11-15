"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import { Loader2, LogOut, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { changePassword, deleteAccount, deleteAllData, getAccount, revokeOthers, updateProfile, type AccountSettings } from "@/lib/history";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";

type Notice = { kind: "ok" | "error"; text: string } | null;

function Section({ title, description, children, danger }: { title: string; description?: string; children: ReactNode; danger?: boolean }) {
  return (
    <section className={cn("rounded-lg border bg-card", danger && "border-destructive/30")}>
      <div className="border-b px-5 py-3.5">
        <h2 className={cn("text-sm font-semibold", danger && "text-destructive")}>{title}</h2>
        {description && <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>}
      </div>
      <div className="space-y-4 px-5 py-4">{children}</div>
    </section>
  );
}

function Message({ n }: { n: Notice }) {
  if (!n) return null;
  return <p role={n.kind === "error" ? "alert" : "status"} className={cn("rounded-md border px-3 py-2 text-sm", n.kind === "error" ? "border-destructive/30 bg-destructive/10 text-destructive" : "border-success/30 bg-success/10 text-success")}>{n.text}</p>;
}

function useAction() {
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);
  async function run(fn: () => Promise<string | void>) {
    setPending(true);
    setNotice(null);
    try {
      const ok = await fn();
      if (ok) setNotice({ kind: "ok", text: ok });
    } catch (e) {
      setNotice({ kind: "error", text: e instanceof ApiError ? e.message : "Something went wrong. Please try again." });
    } finally {
      setPending(false);
    }
  }
  return { pending, notice, run, setNotice };
}

function browserName(ua: string | null): string {
  if (!ua) return "Unknown device";
  const b = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "Browser";
  const os = /Windows/.test(ua) ? "Windows" : /Mac OS/.test(ua) ? "macOS" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Linux/.test(ua) ? "Linux" : "";
  return os ? `${b} on ${os}` : b;
}

export function SettingsView({ initial }: { initial: AccountSettings }) {
  const router = useRouter();
  const [acct, setAcct] = useState(initial);
  const [name, setName] = useState(initial.user.display_name ?? "");
  const profile = useAction(), password = useAction(), sessions = useAction(), erase = useAction(), close = useAction();
  const [eraseOpen, setEraseOpen] = useState(false);
  const [closeOpen, setCloseOpen] = useState(false);
  const used = acct.storage.limit_bytes ? Math.min(100, (acct.storage.used_bytes / acct.storage.limit_bytes) * 100) : 0;

  const refresh = async () => setAcct(await getAccount());

  return (
    <div className="max-w-2xl space-y-6">
      <Section title="Profile">
        <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); void profile.run(async () => { await updateProfile(name); router.refresh(); return "Saved."; }); }}>
          <div className="space-y-1.5"><Label htmlFor="email">Email</Label><Input id="email" value={acct.user.email} readOnly disabled /></div>
          <div className="space-y-1.5"><Label htmlFor="display">Display name</Label><Input id="display" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} /></div>
          <Message n={profile.notice} />
          <Button type="submit" disabled={profile.pending}>{profile.pending && <Loader2 className="animate-spin" />} Save profile</Button>
        </form>
      </Section>

      <Section title="Password" description="Changing your password signs you out everywhere else.">
        <form className="space-y-3" onSubmit={(e: FormEvent<HTMLFormElement>) => {
          e.preventDefault();
          const f = e.currentTarget;
          const data = new FormData(f);
          void password.run(async () => {
            await changePassword(String(data.get("current")), String(data.get("next")));
            f.reset();
            await refresh();
            return "Password changed. Other devices have been signed out.";
          });
        }}>
          <div className="space-y-1.5"><Label htmlFor="current">Current password</Label><Input id="current" name="current" type="password" autoComplete="current-password" required maxLength={128} /></div>
          <div className="space-y-1.5"><Label htmlFor="next">New password</Label><Input id="next" name="next" type="password" autoComplete="new-password" required minLength={10} maxLength={128} /><p className="text-xs text-muted-foreground">At least 10 characters. Common passwords and ones containing your email name are refused.</p></div>
          <Message n={password.notice} />
          <Button type="submit" disabled={password.pending}>{password.pending && <Loader2 className="animate-spin" />} Change password</Button>
        </form>
      </Section>

      <Section title="Signed-in devices" description="Sessions expire after seven days without use.">
        <ul className="divide-y rounded-md border">
          {acct.sessions.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm">
              <span><span className="font-medium">{browserName(s.user_agent)}</span>{s.current && <span className="ml-2 rounded-md border border-success/30 bg-success/10 px-1.5 py-0.5 text-xs text-success">This device</span>}</span>
              <span className="text-xs text-muted-foreground">Active {new Date(s.last_seen_at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" })}</span>
            </li>
          ))}
        </ul>
        <Message n={sessions.notice} />
        <Button variant="outline" disabled={sessions.pending || acct.sessions.length < 2} onClick={() => void sessions.run(async () => { const r = await revokeOthers(); await refresh(); return `Signed out ${r.revoked} other device${r.revoked === 1 ? "" : "s"}.`; })}>
          <LogOut /> Sign out other devices
        </Button>
      </Section>

      <Section title="AI analyst">
        <dl className="grid grid-cols-[130px_1fr] gap-y-2 text-sm">
          <dt className="text-muted-foreground">Status</dt><dd>{acct.ai.configured ? "Configured" : "Not configured. Set AI_PROVIDER_API_KEY on the engine."}</dd>
          {acct.ai.configured && <><dt className="text-muted-foreground">Model</dt><dd>{acct.ai.model}{acct.ai.fallback_model ? ` (falls back to ${acct.ai.fallback_model} when busy)` : ""}</dd></>}
          <dt className="text-muted-foreground">Upload limit</dt><dd>{acct.limits.max_upload_mb} MB per file</dd>
        </dl>
        <p className="text-xs text-muted-foreground">Questions, column names, a few example values and query result previews are sent to the AI provider. See SECURITY.md for what that means on a free API tier.</p>
      </Section>

      <Section title="Data and storage">
        <div>
          <div className="mb-1.5 flex justify-between text-sm"><span>{acct.storage.datasets} dataset{acct.storage.datasets === 1 ? "" : "s"}</span><span className="tabular-nums text-muted-foreground">{formatBytes(acct.storage.used_bytes)} of {formatBytes(acct.storage.limit_bytes)}</span></div>
          <div role="progressbar" aria-valuenow={Math.round(used)} aria-valuemin={0} aria-valuemax={100} aria-label="Storage used" className="h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full bg-brand" style={{ width: `${used}%` }} /></div>
        </div>
      </Section>

      <Section title="Danger zone" description="These actions cannot be undone. Your password is required." danger>
        <div className="space-y-2">
          <p className="text-sm font-medium">Delete all my data</p>
          <p className="text-xs text-muted-foreground">Removes every dataset, cleaned copy, conversation, analysis and chart. Your account stays.</p>
          {eraseOpen ? (
            <form className="flex flex-wrap items-end gap-2" onSubmit={(e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const p = String(new FormData(e.currentTarget).get("pw")); void erase.run(async () => { const r = await deleteAllData(p); setEraseOpen(false); await refresh(); router.refresh(); return `Deleted ${r.datasets_deleted} dataset${r.datasets_deleted === 1 ? "" : "s"} and everything derived from them.`; }); }}>
              <Input name="pw" type="password" required placeholder="Your password" aria-label="Password to confirm" className="w-56" autoComplete="current-password" />
              <Button type="submit" variant="destructive" disabled={erase.pending}>{erase.pending && <Loader2 className="animate-spin" />} Delete everything</Button>
              <Button type="button" variant="ghost" onClick={() => setEraseOpen(false)}>Cancel</Button>
            </form>
          ) : <Button variant="outline" onClick={() => setEraseOpen(true)}>Delete all my data…</Button>}
          <Message n={erase.notice} />
        </div>
        <div className="space-y-2 border-t pt-4">
          <p className="flex items-center gap-1.5 text-sm font-medium"><ShieldAlert className="size-4 text-destructive" /> Delete my account</p>
          <p className="text-xs text-muted-foreground">Deletes your account and all of your data, then signs you out.</p>
          {closeOpen ? (
            <form className="flex flex-wrap items-end gap-2" onSubmit={(e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const p = String(new FormData(e.currentTarget).get("pw")); void close.run(async () => { await deleteAccount(p); router.replace("/"); router.refresh(); }); }}>
              <Input name="pw" type="password" required placeholder="Your password" aria-label="Password to confirm account deletion" className="w-56" autoComplete="current-password" />
              <Button type="submit" variant="destructive" disabled={close.pending}>{close.pending && <Loader2 className="animate-spin" />} Delete my account</Button>
              <Button type="button" variant="ghost" onClick={() => setCloseOpen(false)}>Cancel</Button>
            </form>
          ) : <Button variant="outline" onClick={() => setCloseOpen(true)}>Delete my account…</Button>}
          <Message n={close.notice} />
        </div>
      </Section>
    </div>
  );
}
