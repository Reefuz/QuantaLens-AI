import type { Metadata } from "next";
import { AuthForm } from "@/components/auth/auth-form";

export const metadata: Metadata = { title: "Create account" };

export default function RegisterPage() {
  return (
    <>
      <h1 className="mb-1.5 text-2xl font-semibold tracking-tight">Create your account</h1>
      <p className="mb-7 text-sm text-muted-foreground">Your datasets are private to your account.</p>
      <AuthForm mode="register" />
    </>
  );
}
