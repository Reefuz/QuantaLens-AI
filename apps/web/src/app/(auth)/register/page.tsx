import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { AuthForm } from "@/components/auth/auth-form";
import { getCurrentUser } from "@/lib/server/auth";

export const metadata: Metadata = { title: "Create account" };

export default async function RegisterPage() {
  if (await getCurrentUser()) redirect("/dashboard");
  return (
    <>
      <h1 className="mb-1.5 text-2xl font-semibold tracking-tight">Create your account</h1>
      <p className="mb-7 text-sm text-muted-foreground">Your datasets are private to your account.</p>
      <AuthForm mode="register" />
    </>
  );
}
