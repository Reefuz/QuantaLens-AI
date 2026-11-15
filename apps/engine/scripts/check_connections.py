"""Smoke-test the Neon and LLM configuration. Prints status only, never secrets."""

import httpx
import psycopg

from app.config import get_settings


def check_database(url: str) -> None:
    try:
        with psycopg.connect(url, connect_timeout=15) as conn:
            role, version = conn.execute("select current_user, split_part(version(), ' ', 2)").fetchone()
            can_create = conn.execute(
                "select has_database_privilege(current_user, current_database(), 'CREATE')"
            ).fetchone()[0]
            print(f"NEON OK   role={role} postgres={version} can_create_schema={can_create}")
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        print(f"NEON FAIL {type(exc).__name__}")


def check_llm(base_url: str, api_key: str, model: str) -> None:
    try:
        resp = httpx.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
                "max_tokens": 200,
            },
            timeout=40,
        )
        if resp.is_success:
            print("GEMINI OK ", resp.json()["choices"][0]["message"]["content"].strip()[:40])
        else:
            body = resp.json()
            err = (body[0] if isinstance(body, list) else body).get("error", {})
            print("GEMINI FAIL", resp.status_code, str(err.get("message", ""))[:160])
    except Exception as exc:  # noqa: BLE001
        print(f"GEMINI FAIL {type(exc).__name__}")


if __name__ == "__main__":
    s = get_settings()
    check_database(s.database_url_psycopg)
    check_llm(s.ai_base_url, s.ai_provider_api_key.get_secret_value(), s.ai_model)
