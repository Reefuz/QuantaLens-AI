"""Verify the read-only role can read qdata and nothing else. Exits non-zero on any failure."""

import sys

import psycopg

from app.config import get_settings

PROBE = "_probe_readonly"


def attempt(conn: psycopg.Connection, label: str, statement: str, should_succeed: bool) -> bool:
    try:
        conn.execute(statement)
        conn.rollback()
        ok = should_succeed
        outcome = "allowed"
    except psycopg.Error as exc:
        conn.rollback()
        ok = not should_succeed
        outcome = f"denied ({type(exc).__name__})"
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {outcome}")
    return ok


def main() -> int:
    s = get_settings()
    with psycopg.connect(s.database_url_psycopg, autocommit=True) as admin:
        admin.execute(f"CREATE TABLE IF NOT EXISTS qdata.{PROBE} (id int, v text)")
        admin.execute(f"INSERT INTO qdata.{PROBE} SELECT 1, 'x' WHERE NOT EXISTS (SELECT 1 FROM qdata.{PROBE})")
    try:
        with psycopg.connect(s.analytics_database_url.get_secret_value(), prepare_threshold=None) as ro:
            results = [
                attempt(ro, "SELECT from qdata table (new table, default privileges)", f"SELECT * FROM qdata.{PROBE}", True),
                attempt(ro, "SELECT via search_path", f"SELECT * FROM {PROBE}", True),
                attempt(ro, "INSERT into qdata", f"INSERT INTO qdata.{PROBE} VALUES (2, 'y')", False),
                attempt(ro, "UPDATE qdata", f"UPDATE qdata.{PROBE} SET v = 'z'", False),
                attempt(ro, "DELETE from qdata", f"DELETE FROM qdata.{PROBE}", False),
                attempt(ro, "DROP table in qdata", f"DROP TABLE qdata.{PROBE}", False),
                attempt(ro, "CREATE table in qdata", "CREATE TABLE qdata._x (a int)", False),
                attempt(ro, "CREATE table in public", "CREATE TABLE public._x (a int)", False),
                attempt(ro, "SELECT users table", "SELECT * FROM public.users", False),
                attempt(ro, "SELECT auth_sessions table", "SELECT * FROM public.auth_sessions", False),
                attempt(ro, "CREATE ROLE", "CREATE ROLE _evil LOGIN", False),
            ]
            timeout = ro.execute("SHOW statement_timeout").fetchone()[0]
            readonly = ro.execute("SHOW default_transaction_read_only").fetchone()[0]
            print(f"INFO  statement_timeout={timeout} default_transaction_read_only={readonly}")
            results.append(timeout == "15s" and readonly == "on")
    finally:
        with psycopg.connect(s.database_url_psycopg, autocommit=True) as admin:
            admin.execute(f"DROP TABLE IF EXISTS qdata.{PROBE}")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
