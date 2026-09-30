"""The PostgreSQL schema is generated from schema.sql; make sure it has not drifted,
and (when a server is configured) that the adapter behaves like sqlite3 where the code relies on it."""
import re
import unittest
from pathlib import Path

from hr_analytics.db.connection import PG_SCHEMA_PATH, SCHEMA_PATH, translate

from .support import PG_URL, pg_create_schema, pg_drop_schema, pg_schema_url

BUILD = Path(__file__).resolve().parent.parent / "scripts" / "build_pg_schema.py"


def tables(sql: str) -> dict[str, set[str]]:
    out = {}
    for name, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", sql, re.S):
        cols = set()
        for line in body.splitlines():
            m = re.match(r"\s+(\w+)\s+(INTEGER|TEXT|REAL|BLOB|DOUBLE|BYTEA)", line)
            if m and m.group(1).upper() not in ("CHECK", "UNIQUE", "PRIMARY"):
                cols.add(m.group(1))
        out[name] = cols
    return out


class SchemaParityTests(unittest.TestCase):
    def test_generated_file_is_current(self):
        ns: dict = {"__file__": str(BUILD), "__name__": "build_pg_schema"}
        exec(compile(BUILD.read_text(encoding="utf-8"), str(BUILD), "exec"), ns)
        expected = ns["build"](SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(PG_SCHEMA_PATH.read_text(encoding="utf-8"), expected,
                         "schema_postgres.sql is stale: run python scripts/build_pg_schema.py")

    def test_same_tables_and_columns(self):
        a = tables(SCHEMA_PATH.read_text(encoding="utf-8"))
        b = tables(PG_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(a, b)
        self.assertGreaterEqual(len(a), 21)

    def test_placeholder_translation(self):
        self.assertEqual(translate("SELECT * FROM t WHERE a = ? AND b LIKE ?"),
                         "SELECT * FROM t WHERE a = %s AND b ILIKE %s")
        self.assertEqual(translate("SELECT '?' , x FROM t WHERE y LIKE '20%' AND z = ?"),
                         "SELECT '?' , x FROM t WHERE y ILIKE '20%%' AND z = %s")


@unittest.skipUnless(PG_URL, "set HR_TEST_DATABASE_URL to run PostgreSQL adapter tests")
class PostgresAdapterTests(unittest.TestCase):
    def setUp(self):
        from hr_analytics.db.connection import connect, init_schema
        self.schema = pg_create_schema()
        self.conn = connect(pg_schema_url(self.schema))
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        pg_drop_schema(self.schema)

    def test_rows_lastrowid_numeric_and_dates(self):
        from datetime import date
        c = self.conn
        dep = c.execute("INSERT INTO departments(code, name) VALUES (?, ?)", ("OPS", "Operations")).lastrowid
        self.assertIsInstance(dep, int)
        row = c.execute("SELECT department_id, code FROM departments WHERE department_id = ?", (dep,)).fetchone()
        self.assertEqual((row[0], row["code"], dict(row)), (dep, "OPS", {"department_id": dep, "code": "OPS"}))
        avg = c.execute("SELECT AVG(x) FROM (SELECT 1 AS x UNION ALL SELECT 2) q").fetchone()[0]
        self.assertIsInstance(avg, float, "NUMERIC comes back as float, not Decimal")
        c.execute("INSERT INTO holidays(holiday_date, name) VALUES (?, ?)", (date(2026, 9, 23), "National Day"))
        self.assertEqual(c.execute("SELECT holiday_date FROM holidays").fetchone()[0], "2026-09-23",
                         "dates are stored as ISO text, like sqlite3 does")
        self.assertEqual(c.execute("SELECT name FROM holidays WHERE name LIKE ?", ("national%",)).fetchone()[0],
                         "National Day", "LIKE is case-insensitive on both engines")
        before = c.total_changes
        c.executemany("INSERT INTO holidays(holiday_date, name) VALUES (?, ?) ON CONFLICT (holiday_date) DO NOTHING",
                      [("2026-09-23", "dup"), ("2026-02-22", "Founding Day")])
        self.assertEqual(c.total_changes - before, 1, "total_changes counts only rows actually inserted")
        c.commit()
