import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

const ENGINE_URL = (process.env.PYTHON_ANALYTICS_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const SESSION_COOKIE = "ql_session";

export type User = { id: string; email: string; display_name: string | null };

/** Server-side call to the engine, forwarding the user's session cookie. */
export async function engineFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  return fetch(`${ENGINE_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: { ...(init.headers ?? {}), ...(token ? { Cookie: `${SESSION_COOKIE}=${token}` } : {}) },
  });
}

/** Validates the session with the engine. Memoised per request. */
export const getCurrentUser = cache(async (): Promise<User | null> => {
  try {
    const res = await engineFetch("/api/auth/me");
    return res.ok ? ((await res.json()) as User) : null;
  } catch {
    return null;
  }
});

/** Data access layer guard: use in server components and layouts that need a user. */
export async function requireUser(): Promise<User> {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  return user;
}
