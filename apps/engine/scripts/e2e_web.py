"""End-to-end check through the Next.js proxy. Needs the web app (3000) and engine (8000) running.

Creates a throwaway user and deletes it afterwards. Exits non-zero if any check fails.
"""

import sys
import uuid

import httpx
from sqlalchemy import delete

from app.db import get_sessionmaker
from app.models import User

BASE = "http://localhost:3000"
H = {"X-Requested-With": "QuantaLens"}
results: list[bool] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    results.append(condition)
    print(f"{'PASS' if condition else 'FAIL'}  {label}{(' [' + detail + ']') if detail else ''}")


def main() -> int:
    email = f"e2e-{uuid.uuid4().hex[:8]}@example.com"
    try:
        anon = httpx.Client(base_url=BASE, follow_redirects=False)
        check("landing page public", anon.get("/").status_code == 200)
        r = anon.get("/dashboard")
        check("anonymous /dashboard redirects to login", r.status_code in (302, 307) and "/login" in r.headers["location"], r.headers.get("location", ""))
        check("login page public", anon.get("/login").status_code == 200)
        check("anonymous /api/auth/me is 401 via proxy", anon.get("/api/auth/me").status_code == 401)

        c = httpx.Client(base_url=BASE, follow_redirects=False, headers=H)
        r = c.post("/api/auth/register", json={"email": email, "password": "an-e2e-password-1", "display_name": "E2E User"})
        check("register via proxy", r.status_code == 201)
        cookie_header = r.headers.get("set-cookie", "").lower()
        check("session cookie is HttpOnly + SameSite=Lax", "httponly" in cookie_header and "samesite=lax" in cookie_header)
        check("password not echoed", "an-e2e-password" not in r.text)

        for path in ("/dashboard", "/settings", "/datasets", "/analyst", "/history", "/reports"):
            check(f"authenticated {path} renders", c.get(path).status_code == 200)
        check("authenticated /login redirects to dashboard", c.get("/login").status_code in (302, 307))
        html = c.get("/dashboard").text
        check("dashboard greets user by name", "E2E User" in html)
        check("dashboard shows real empty state (0 datasets)", "No datasets yet" in html)
        check("dashboard has primary action", "Start a New Analysis" in html)
        check("settings shows account email", email in c.get("/settings").text)

        no_header = httpx.Client(base_url=BASE, cookies=c.cookies)
        check("logout without CSRF header rejected", no_header.post("/api/auth/logout").status_code == 403)

        stolen = dict(c.cookies)
        check("logout", c.post("/api/auth/logout").status_code == 204)
        check("session invalid after logout", httpx.get(f"{BASE}/api/auth/me", cookies=stolen).status_code == 401)
        r = httpx.get(f"{BASE}/dashboard", cookies=stolen, follow_redirects=False)
        check("stale cookie cannot reach dashboard", r.status_code in (302, 307) and "/login" in r.headers.get("location", ""), str(r.status_code))
    finally:
        with get_sessionmaker()() as db:
            db.execute(delete(User).where(User.email == email))
            db.commit()
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
