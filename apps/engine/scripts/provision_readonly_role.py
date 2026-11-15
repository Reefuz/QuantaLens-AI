"""Create (or re-grant) the least-privilege role used to execute generated SQL.

The role can only SELECT from schema "qdata", has no write access anywhere, is read-only by default,
and has a statement timeout. Its credentials are written to ANALYTICS_DATABASE_URL in .env and never printed.

Usage:  python -m scripts.provision_readonly_role [--rotate]
"""

import re
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from psycopg import sql

from app.config import get_settings

ROLE = "quantalens_readonly"
ENV_FILE = Path(".env")


def build_url(admin_url: str, password: str) -> str:
    parts = urlsplit(admin_url)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return urlunsplit(parts._replace(netloc=f"{ROLE}:{quote(password, safe='')}@{host}{port}"))


def write_env(key: str, value: str) -> None:
    text = ENV_FILE.read_text()
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        text = re.sub(rf"^{key}=.*$", lambda _: line, text, flags=re.M)
    else:
        text += f"\n{line}\n"
    ENV_FILE.write_text(text)


def main() -> None:
    settings = get_settings()
    admin_url = settings.database_url_psycopg
    existing = settings.analytics_database_url.get_secret_value()
    rotate = "--rotate" in sys.argv
    password = secrets.token_urlsafe(32)

    with psycopg.connect(admin_url, autocommit=True) as conn:
        role_exists = conn.execute("select 1 from pg_roles where rolname = %s", (ROLE,)).fetchone()
        ident = sql.Identifier(ROLE)
        if not role_exists:
            conn.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(ident, sql.Literal(password)))
            write_env("ANALYTICS_DATABASE_URL", build_url(admin_url, password))
            print("created role and wrote ANALYTICS_DATABASE_URL")
        elif rotate or not existing:
            conn.execute(sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(ident, sql.Literal(password)))
            write_env("ANALYTICS_DATABASE_URL", build_url(admin_url, password))
            print("rotated role password and wrote ANALYTICS_DATABASE_URL")
        else:
            print("role exists; re-applying grants only")

        db = conn.execute("select current_database()").fetchone()[0]
        owner = conn.execute("select current_user").fetchone()[0]
        statements = [
            sql.SQL("REVOKE ALL ON SCHEMA public FROM {}").format(ident),
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(db), ident),
            sql.SQL("GRANT USAGE ON SCHEMA qdata TO {}").format(ident),
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA qdata TO {}").format(ident),
            sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA qdata GRANT SELECT ON TABLES TO {}").format(
                sql.Identifier(owner), ident
            ),
            sql.SQL("ALTER ROLE {} SET default_transaction_read_only = on").format(ident),
            sql.SQL("ALTER ROLE {} SET statement_timeout = '15s'").format(ident),
            sql.SQL("ALTER ROLE {} SET idle_in_transaction_session_timeout = '10s'").format(ident),
            sql.SQL("ALTER ROLE {} SET search_path = qdata").format(ident),
            sql.SQL("ALTER ROLE {} CONNECTION LIMIT 10").format(ident),
        ]
        for stmt in statements:
            conn.execute(stmt)
    print("grants applied")


if __name__ == "__main__":
    main()
