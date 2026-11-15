import { Logo } from "@/components/brand/logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { MobileNav, Sidebar } from "@/components/workspace/sidebar";
import { UserMenu } from "@/components/workspace/user-menu";
import { requireUser } from "@/lib/server/auth";

export default async function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  // Authoritative session check against the engine. The proxy only does an optimistic cookie check.
  const user = await requireUser();
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b px-4 md:px-6">
          <span className="md:hidden">
            <Logo />
          </span>
          <span className="hidden md:block" />
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <UserMenu email={user.email} name={user.display_name} />
          </div>
        </header>
        <MobileNav />
        <main className="flex-1 px-4 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </div>
  );
}
