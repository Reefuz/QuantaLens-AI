import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { AuthForm } from "@/components/auth/auth-form";
import { getCurrentUser } from "@/lib/server/auth";

export const metadata: Metadata = { title: "Log in" };

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  if (await getCurrentUser()) redirect("/dashboard"); // a real session check, unlike the cookie-only proxy
  const { next } = await searchParams;
  return (
    <>
      <h1 className="mb-1.5 text-2xl font-semibold tracking-tight">Log in</h1>
      <p className="mb-7 text-sm text-muted-foreground">Welcome back. Continue your analysis.</p>
      <AuthForm mode="login" next={typeof next === "string" ? next : undefined} />
    </>
  );
}
