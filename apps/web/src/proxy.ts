import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const SESSION_COOKIE = "ql_session";
const PROTECTED = ["/dashboard", "/datasets", "/analyst", "/history", "/reports", "/settings"];
const AUTH_PAGES = ["/login", "/register"];

/**
 * Optimistic redirect only. It checks that a session cookie exists, not that it is valid.
 * Real authentication happens in the workspace layout via the engine (see lib/server/auth.ts),
 * and again on every engine API call.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasCookie = request.cookies.has(SESSION_COOKIE);
  const isProtected = PROTECTED.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  if (isProtected && !hasCookie) {
    const url = new URL("/login", request.url);
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  if (AUTH_PAGES.includes(pathname) && hasCookie) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/datasets/:path*", "/analyst/:path*", "/history/:path*", "/reports/:path*", "/settings/:path*", "/login", "/register"],
};
