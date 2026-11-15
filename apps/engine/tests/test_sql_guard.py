import pytest

from app.analysis.sql_guard import MAX_ROWS, SqlRejected, guard_sql

PHYSICAL = "ds_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
OTHER = "ds_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
COLS = ["customer_segment", "transaction_amount", "transaction_date", "transaction_status"]


def guard(sql):
    return guard_sql(sql, PHYSICAL, COLS)


class TestAllowed:
    @pytest.mark.parametrize("sql", [
        "SELECT customer_segment, SUM(transaction_amount) AS total FROM data GROUP BY customer_segment ORDER BY total DESC",
        "SELECT COUNT(*) FROM data",
        "SELECT date_trunc('month', transaction_date) AS m, COUNT(*) FROM data GROUP BY 1 ORDER BY 1",
        "WITH t AS (SELECT customer_segment, SUM(transaction_amount) s FROM data GROUP BY 1) SELECT *, s / SUM(s) OVER () AS share FROM t",
        "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY transaction_amount) FROM data",
        "SELECT corr(transaction_amount, transaction_amount) FROM data",
        "SELECT a.customer_segment FROM data a JOIN data b ON a.customer_segment = b.customer_segment LIMIT 5",
        "SELECT x FROM (SELECT customer_segment x FROM data) q",
        "SELECT customer_segment FROM data UNION SELECT transaction_status FROM data",
        "SELECT CAST(transaction_amount AS double precision) FROM data WHERE transaction_amount ~ '^[0-9.]+$'",
        "SELECT regexp_replace(transaction_amount, '[^0-9.]', '', 'g')::numeric FROM data",
        "SELECT lag(transaction_amount) OVER (ORDER BY transaction_date) FROM data",
        "SELECT customer_segment FROM data;",  # trailing semicolon is fine
        f"SELECT 1 FROM qdata.{PHYSICAL}",  # own physical table
        "select COALESCE(transaction_amount, '0') from DATA",
    ])
    def test_valid_queries_pass(self, sql):
        g = guard(sql)
        assert g.executed.lower().startswith(("select", "with"))

    def test_data_is_rewritten_to_physical_table_with_alias(self):
        g = guard("SELECT data.customer_segment FROM data")
        assert f'"qdata"."{PHYSICAL}" AS "data"' in g.executed or f"qdata.{PHYSICAL} AS data" in g.executed

    def test_custom_alias_is_preserved(self):
        g = guard("SELECT d.customer_segment FROM data AS d")
        assert " d" in g.executed.replace('"', "") and PHYSICAL in g.executed

    def test_original_text_is_kept_for_display(self):
        sql = "SELECT COUNT(*) FROM data"
        assert guard(sql).original == sql

    def test_columns_and_tables_reported(self):
        g = guard("SELECT customer_segment, SUM(transaction_amount) FROM data GROUP BY 1")
        assert g.tables == ["data"] and g.columns == ["customer_segment", "transaction_amount"]


class TestLimits:
    def test_limit_added_when_missing(self):
        g = guard("SELECT customer_segment FROM data")
        assert f"LIMIT {MAX_ROWS + 1}" in g.executed and g.notes

    def test_small_limit_is_kept(self):
        g = guard("SELECT customer_segment FROM data LIMIT 5")
        assert "LIMIT 5" in g.executed and not g.notes

    def test_huge_limit_is_lowered(self):
        g = guard("SELECT customer_segment FROM data LIMIT 99999999")
        assert f"LIMIT {MAX_ROWS + 1}" in g.executed and "99999999" not in g.executed

    def test_union_is_wrapped_and_limited(self):
        g = guard("SELECT customer_segment FROM data UNION ALL SELECT transaction_status FROM data")
        assert f"LIMIT {MAX_ROWS + 1}" in g.executed

    def test_non_literal_limit_is_replaced(self):
        g = guard("SELECT customer_segment FROM data LIMIT (SELECT 5)")
        assert f"LIMIT {MAX_ROWS + 1}" in g.executed


class TestRejected:
    @pytest.mark.parametrize("sql", [
        "INSERT INTO data VALUES (1)",
        "UPDATE data SET transaction_amount = '0'",
        "DELETE FROM data",
        "DROP TABLE data",
        "ALTER TABLE data ADD COLUMN x int",
        "TRUNCATE data",
        "CREATE TABLE x AS SELECT * FROM data",
        "GRANT ALL ON data TO public",
        "COPY data TO '/tmp/x'",
        "SET ROLE neondb_owner",
        "VACUUM data",
        "EXPLAIN ANALYZE SELECT * FROM data",
        "CALL do_things()",
        "DO $$ BEGIN PERFORM 1; END $$",
        "BEGIN; SELECT 1; COMMIT",
        "SELECT 1; DROP TABLE data",
        "SELECT * FROM data; SELECT * FROM data",
        "SELECT * INTO newt FROM data",
        "SELECT * FROM data FOR UPDATE",
        "WITH x AS (DELETE FROM data RETURNING *) SELECT * FROM x",
        "WITH x AS (INSERT INTO data VALUES (1) RETURNING *) SELECT * FROM x",
        "WITH x AS (UPDATE data SET transaction_amount='1' RETURNING *) SELECT * FROM x",
    ])
    def test_writes_ddl_and_multi_statement(self, sql):
        with pytest.raises(SqlRejected):
            guard(sql)

    @pytest.mark.parametrize("sql", [
        f"SELECT * FROM qdata.{OTHER}",  # another dataset's table
        f"SELECT * FROM {OTHER}",
        "SELECT * FROM public.users",
        "SELECT * FROM users",
        "SELECT * FROM auth_sessions",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM pg_catalog.pg_roles",
        "SELECT * FROM pg_shadow",
        "SELECT * FROM mydb.qdata.ds_x",
        f"SELECT * FROM data JOIN qdata.{OTHER} o ON true",
        f"SELECT * FROM (SELECT * FROM qdata.{OTHER}) q",
        f"WITH q AS (SELECT * FROM qdata.{OTHER}) SELECT * FROM q",
        f"SELECT (SELECT count(*) FROM qdata.{OTHER})",
        f"SELECT 1 WHERE EXISTS (SELECT 1 FROM qdata.{OTHER})",
        "WITH data AS (SELECT 1) SELECT * FROM data",  # shadowing the virtual table
    ])
    def test_other_tables_and_catalogs(self, sql):
        with pytest.raises(SqlRejected):
            guard(sql)

    @pytest.mark.parametrize("sql", [
        "SELECT pg_sleep(10)",
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_catalog.pg_read_file('/etc/passwd')",
        f"SELECT query_to_xml('select * from qdata.{OTHER}', true, false, '')",
        "SELECT table_to_xml('qdata.ds_x', true, false, '')",
        "SELECT current_setting('is_superuser')",
        "SELECT set_config('statement_timeout', '0', false)",
        "SELECT lo_import('/etc/passwd')",
        "SELECT dblink('host=evil', 'select 1')",
        "SELECT pg_terminate_backend(1)",
        "SELECT version()",
        "SELECT current_user",
        "SELECT session_user",
        "SELECT current_database()",
        "SELECT * FROM generate_series(1, 100000000)",
        "SELECT 'a'::regclass",
        "SELECT CAST('pg_roles' AS regclass)",
    ])
    def test_dangerous_functions_and_casts(self, sql):
        with pytest.raises(SqlRejected):
            guard(sql)

    @pytest.mark.parametrize("sql", ["", "   ", ";", "SELEC * FROM data", "SELECT FROM WHERE", "x" * 9000])
    def test_garbage(self, sql):
        with pytest.raises(SqlRejected):
            guard(sql)

    def test_comment_tricks_do_not_reach_the_database(self):
        g = guard("SELECT customer_segment /* ; DROP TABLE data */ FROM data -- ; DELETE FROM data")
        assert "DROP" not in g.executed.upper() and "DELETE" not in g.executed.upper() and "--" not in g.executed

    def test_string_literals_containing_keywords_are_fine(self):
        g = guard("SELECT customer_segment FROM data WHERE customer_segment = 'DROP TABLE users; --'")
        assert "DROP TABLE users" in g.executed  # data, not code

    def test_error_messages_are_safe_and_specific(self):
        with pytest.raises(SqlRejected, match=r"pg_sleep\(\) is not allowed"):
            guard("SELECT pg_sleep(1)")
        with pytest.raises(SqlRejected, match="Only a single SELECT"):
            guard("SELECT 1; SELECT 2")
