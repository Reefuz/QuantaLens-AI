"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, ApiError } from "@/lib/api";

type Mode = "login" | "register";

/** Only same-site relative paths are allowed as post-login destinations. */
export function safeNext(next: string | undefined): string {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.includes("\\") ? next : "/dashboard";
}

export function AuthForm({ mode, next }: { mode: Mode; next?: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const isRegister = mode === "register";

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setError(null);
    setPending(true);
    try {
      await api(`/auth/${mode}`, {
        method: "POST",
        body: JSON.stringify({
          email: String(form.get("email") ?? ""),
          password: String(form.get("password") ?? ""),
          ...(isRegister ? { display_name: String(form.get("name") ?? "").trim() || null } : {}),
        }),
      });
      router.replace(safeNext(next));
      router.refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server. Check your connection and try again.");
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4" noValidate={false}>
      {isRegister && (
        <div className="space-y-1.5">
          <Label htmlFor="name">Name (optional)</Label>
          <Input id="name" name="name" autoComplete="name" maxLength={120} />
        </div>
      )}
      <div className="space-y-1.5">
        <Label htmlFor="email">Email</Label>
        <Input id="email" name="email" type="email" autoComplete="email" required />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          name="password"
          type="password"
          autoComplete={isRegister ? "new-password" : "current-password"}
          required
          minLength={isRegister ? 10 : undefined}
          maxLength={128}
        />
        {isRegister && <p className="text-xs text-muted-foreground">At least 10 characters.</p>}
      </div>
      {error && (
        <p role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </p>
      )}
      <Button type="submit" size="lg" className="h-9 w-full" disabled={pending}>
        {pending && <Loader2 className="size-4 animate-spin" />}
        {isRegister ? "Create account" : "Log in"}
      </Button>
      <p className="text-center text-sm text-muted-foreground">
        {isRegister ? "Already have an account? " : "New to QuantaLens? "}
        <Link href={isRegister ? "/login" : "/register"} className="font-medium text-foreground underline-offset-4 hover:underline">
          {isRegister ? "Log in" : "Create an account"}
        </Link>
      </p>
    </form>
  );
}
