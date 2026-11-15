"""Smoke test against a deployed QuantaLens frontend (through its /api proxy).

Usage:
    python -m scripts.smoke_prod https://your-app.vercel.app [--engine https://engine.onrender.com]

Creates a throwaway account, uploads a small and a large CSV, checks the
session, then deletes the account (and with it all its data). Exits non-zero
if any check fails. The large upload measures whether the proxy path accepts
bodies over Vercel's 4.5 MB Function limit.
"""
from __future__ import annotations

import argparse
import secrets
import sys
import time

import httpx

H = {"X-Requested-With": "QuantaLens"}
failures = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global failures
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""), flush=True)
    if not ok:
        failures += 1
    return ok


def make_csv(target_bytes: int) -> bytes:
    lines = ["id,region,amount,note"]
    size = len(lines[0]) + 1
    i = 0
    while size < target_bytes:
        row = f"{i},{'north' if i % 2 else 'south'},{(i * 37) % 1000}.5,padding-text-for-size-{i}"
        lines.append(row)
        size += len(row) + 1
        i += 1
    return ("\n".join(lines) + "\n").encode()


def wait_ready(c: httpx.Client, dataset_id: str, timeout: float = 180) -> str:
    end = time.time() + timeout
    status = "?"
    while time.time() < end:
        r = c.get(f"/api/datasets/{dataset_id}")
        if r.status_code == 200:
            status = r.json().get("status", "?")
            if status in ("ready", "failed", "error"):
                return status
        time.sleep(2)
    return status


def upload(c: httpx.Client, name: str, data: bytes) -> httpx.Response:
    return c.post("/api/datasets", files={"file": (name, data, "text/csv")}, timeout=300)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--engine", help="engine URL, to check /health directly")
    a = ap.parse_args()
    base = a.base.rstrip("/")

    if a.engine:
        r = httpx.get(a.engine.rstrip("/") + "/health", timeout=90)  # free tier may cold start
        check("engine /health", r.status_code == 200 and r.json().get("status") == "ok", r.text[:80])
        check("engine AI key configured", bool(r.json().get("ai_configured")))

    anon = httpx.Client(base_url=base, headers=H, timeout=90, follow_redirects=False)
    check("anonymous /api/auth/me is 401 via proxy", anon.get("/api/auth/me").status_code == 401)

    email = f"smoke-{secrets.token_hex(5)}@example.com"
    password = "smoke-" + secrets.token_urlsafe(12)
    c = httpx.Client(base_url=base, headers=H, timeout=90, follow_redirects=False)
    try:
        r = c.post("/api/auth/register", json={"email": email, "password": password, "display_name": "Smoke"})
        if not check("register", r.status_code == 201, str(r.status_code)):
            return 1
        check("session cookie is HttpOnly + Secure", all(
            "httponly" in h.lower() and "secure" in h.lower()
            for h in r.headers.get_list("set-cookie") if "ql_session" in h), "")
        check("/api/auth/me with session", c.get("/api/auth/me").status_code == 200)

        r = upload(c, "small.csv", make_csv(50_000))
        if check("small upload accepted", r.status_code == 202, str(r.status_code)):
            check("small dataset becomes ready", wait_ready(c, r.json()["id"]) == "ready")

        r = upload(c, "large.csv", make_csv(8 * 1024 * 1024))
        ok = check("8 MB upload through proxy accepted", r.status_code == 202,
                   f"status {r.status_code}; if 413, set NEXT_PUBLIC_UPLOAD_URL to the engine URL")
        if ok:
            check("8 MB dataset becomes ready", wait_ready(c, r.json()["id"], 300) == "ready")

        r = c.post("/api/datasets/upload-token")
        check("upload token issued", r.status_code == 200 and "token" in r.json(), str(r.status_code))
    finally:
        r = c.post("/api/settings/delete-account", json={"password": password})
        check("cleanup: delete account", r.status_code == 204, str(r.status_code))
    print(f"\n{failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
