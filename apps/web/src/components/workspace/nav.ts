import { Database, FileText, History, LayoutDashboard, Settings, Sparkles, type LucideIcon } from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon };

export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
  { href: "/datasets", label: "My Datasets", icon: Database },
  { href: "/analyst", label: "AI Analyst", icon: Sparkles },
  { href: "/history", label: "Analysis History", icon: History },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/settings", label: "Settings", icon: Settings },
];
