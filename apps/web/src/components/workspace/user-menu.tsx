"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Loader2, LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export function UserMenu({ email, name }: { email: string; name: string | null }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function logout() {
    setPending(true);
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <div className="flex items-center gap-3">
      <div className="hidden text-right leading-tight sm:block">
        {name && <p className="text-sm font-medium">{name}</p>}
        <p className="text-xs text-muted-foreground">{email}</p>
      </div>
      <Button variant="outline" size="sm" onClick={logout} disabled={pending}>
        {pending ? <Loader2 className="animate-spin" /> : <LogOut />}
        Log out
      </Button>
    </div>
  );
}
