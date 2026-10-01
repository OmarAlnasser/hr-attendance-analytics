"""Database connection handling: SQLite (default, local) or PostgreSQL (hosted).

This is the only module that imports a DB driver. Repositories receive a
DB-API-like connection and write SQL with `?` placeholders.

* `connect("path/to/file.sqlite3")`  -> sqlite3 connection (as in v1)
* `connect("postgresql://...")`      -> `PgConnection`, a thin adapter over
  psycopg 3 that gives the rest of the code the same surface it uses on SQLite:
    - `?` placeholders are rewritten to `%s` (literal `%` escaped)
    - rows support `row["col"]`, `row[0]`, `dict(row)` (like sqlite3.Row)
    - `cursor.lastrowid` after a single-row INSERT (via an added RETURNING)
    - `conn.total_changes`, `executemany`, `executescript`, `in_transaction`
    - `LIKE` becomes `ILIKE` (SQLite's LIKE is case-insensitive for ASCII)
    - date/datetime parameters are sent as ISO text, exactly as sqlite3 stores
      them, because dates are kept as ISO TEXT on both engines
    - NUMERIC results (e.g. AVG) come back as float, not Decimal
    - a SELECT issued outside a write transaction is committed at once, as
      sqlite3 does, so read-only requests never sit "idle in transaction"
  The PostgreSQL schema is `schema_postgres.sql`; a test keeps it in step
  with `schema.sql`.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
PG_SCHEMA_PATH = Path(__file__).with_name("schema_postgres.sql")
SCHEMA_VERSION = 3

# v3 columns: (table, column, SQL type). Added in place to older databases on both engines.
V3_COLUMNS = [("departments", "name_ar", "TEXT"), ("shifts", "name_ar", "TEXT"), ("holidays", "name_ar", "TEXT"),
              ("employees", "full_name_ar", "TEXT"), ("employees", "gender", "TEXT"),
              ("employees", "job_title_ar", "TEXT")]
ROLES = ("gm", "hr", "manager", "employee")

# Tables whose integer primary key is generated; used to emulate lastrowid on PostgreSQL.
PRIMARY_KEYS = {
    "departments": "department_id", "shifts": "shift_id", "employees": "employee_id",
    "employee_shift_assignments": "assignment_id", "leave_requests": "leave_id", "users": "user_id",
    "import_batches": "batch_id", "raw_punches": "punch_id", "rejected_rows": "reject_id",
    "evaluation_weights": "weights_id", "performance_evaluations": "evaluation_id",
    "evaluation_history": "history_id", "audit_log": "audit_id", "report_runs": "run_id",
    "attendance_corrections": "correction_id", "stored_files": None,
}
# Every application table, children first (for DROP on reset).
ALL_TABLES = ("stored_files", "attendance_corrections", "risk_scores", "report_runs", "audit_log",
              "evaluation_history", "performance_evaluations", "evaluation_weights", "punch_exceptions",
              "attendance_daily", "rejected_rows", "raw_punches", "import_batches", "leave_requests", "users",
              "holidays", "employee_shift_assignments", "employees", "shifts", "departments", "schema_meta")


def is_url(target: str) -> bool:
    return str(target).startswith(("postgres://", "postgresql://"))


def is_postgres(conn) -> bool:
    return isinstance(conn, PgConnection)


try:  # psycopg is only required when a PostgreSQL URL is used
    import psycopg
    from psycopg.pq import TransactionStatus
    from psycopg.types.numeric import FloatLoader
    IntegrityError: tuple = (sqlite3.IntegrityError, psycopg.IntegrityError)
    DatabaseError: tuple = (sqlite3.DatabaseError, psycopg.DatabaseError)
except ImportError:  # pragma: no cover - SQLite-only installs
    psycopg = None
    IntegrityError = (sqlite3.IntegrityError,)
    DatabaseError = (sqlite3.DatabaseError,)


def connect(target: str):
    target = str(target)
    if is_url(target):
        return PgConnection(target)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# ------------------------------------------------------------ PostgreSQL --

class PgRow(tuple):
    """Tuple that can also be read by column name, like sqlite3.Row."""

    def __new__(cls, values, names, index):
        row = super().__new__(cls, values)
        row._names, row._index = names, index
        return row

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index[key])
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._names)


def _row_factory(cursor):
    names = [c.name for c in cursor.description] if cursor.description else []
    index = {n: i for i, n in enumerate(names)}
    return lambda values: PgRow(values, names, index)


_LIKE = re.compile(r"\bLIKE\b", re.IGNORECASE)
_READ = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.IGNORECASE)


@lru_cache(maxsize=2048)
def translate(sql: str) -> str:
    """SQLite-flavoured SQL with ? placeholders -> psycopg SQL with %s."""
    out, in_quote = [], False
    for ch in sql:
        if ch == "'":
            in_quote = not in_quote
            out.append(ch)
        elif ch == "%":
            out.append("%%")
        elif ch == "?" and not in_quote:
            out.append("%s")
        else:
            out.append(ch)
    return _LIKE.sub("ILIKE", "".join(out))


def _param(v):
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    return v


def _params(params) -> list:
    if params is None:
        return []
    return [_param(v) for v in params]


class PgCursor:
    def __init__(self, cur, lastrowid=None):
        self._cur, self.lastrowid = cur, lastrowid

    @property
    def description(self):
        return [(c.name, None, None, None, None, None, None) for c in self._cur.description] \
            if self._cur.description else None

    @property
    def rowcount(self):
        return self._cur.rowcount

    def fetchone(self):
        return self._cur.fetchone() if self._cur.description else None

    def fetchall(self):
        return self._cur.fetchall() if self._cur.description else []

    def __iter__(self):
        return iter(self.fetchall())


class PgConnection:
    def __init__(self, url: str):
        if psycopg is None:
            raise RuntimeError("PostgreSQL URL given but psycopg is not installed: pip install 'psycopg[binary]'")
        # prepare_threshold=None: no server-side prepared statements, so poolers in any mode are safe
        self._c = psycopg.connect(url, row_factory=_row_factory, prepare_threshold=None, connect_timeout=15)
        self._c.adapters.register_loader("numeric", FloatLoader)
        self.total_changes = 0

    # -- sqlite3-compatible surface --
    def execute(self, sql: str, params=None) -> PgCursor:
        q = translate(sql)
        want_id = None
        m = _INSERT.match(q)
        if m and "RETURNING" not in q.upper():
            want_id = PRIMARY_KEYS.get(m.group(1).lower())
            if want_id:
                q += f" RETURNING {want_id}"
        was_idle = self._c.info.transaction_status == TransactionStatus.IDLE
        cur = self._c.cursor()
        cur.execute(q, _params(params))
        if cur.rowcount and cur.rowcount > 0 and not _READ.match(q):
            self.total_changes += cur.rowcount
        if was_idle and _READ.match(q):
            # Like sqlite3, a read outside a write transaction does not leave a transaction open
            # (results are already on the client). Avoids "idle in transaction" sessions.
            self._c.commit()
        lastrowid = None
        if want_id:
            row = cur.fetchone()
            lastrowid = row[0] if row else None
        return PgCursor(cur, lastrowid)

    def executemany(self, sql: str, seq) -> PgCursor:
        seq = [_params(p) for p in seq]
        cur = self._c.cursor()
        if seq:
            cur.executemany(translate(sql), seq)
            if cur.rowcount and cur.rowcount > 0:
                self.total_changes += cur.rowcount
        return PgCursor(cur)

    def executescript(self, script: str) -> None:
        self._c.execute(script)          # no parameters: several statements are allowed
        self._c.commit()

    def cursor(self):
        return self._c.cursor()

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        self._c.close()

    @property
    def in_transaction(self) -> bool:
        return self._c.info.transaction_status != TransactionStatus.IDLE


# ------------------------------------------------------------ common API --

@contextmanager
def transaction(conn) -> Iterator:
    """Commit on success, roll back on any exception."""
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def read_frame(conn, sql: str, params=None):
    """SQL -> pandas DataFrame on either engine (pandas only supports sqlite3 among raw DB-API connections)."""
    import pandas as pd
    cur = conn.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return pd.DataFrame.from_records([tuple(r) for r in cur.fetchall()], columns=cols, coerce_float=True)


def read_sql(sql: str, conn, params=None):
    """Drop-in for pd.read_sql_query(sql, conn, params=...) that works on both engines."""
    return read_frame(conn, sql, params)


def init_schema(conn) -> None:
    if is_postgres(conn):
        conn.executescript(PG_SCHEMA_PATH.read_text(encoding="utf-8"))
        return
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    migrate(conn)


def drop_all(conn) -> None:
    """PostgreSQL reset: drop this application's tables only (never the whole schema)."""
    conn.executescript("DROP TABLE IF EXISTS " + ", ".join(ALL_TABLES) + " CASCADE;")


def schema_version(conn) -> int:
    try:
        r = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    except DatabaseError:
        conn.rollback()
        return 0
    return int(r[0]) if r else 0


def _columns(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn) -> list[str]:
    """Upgrade an existing SQLite database in place. Safe to call repeatedly.

    PostgreSQL databases are created at the current version and need no steps here.
    Each step checks the actual table shape rather than trusting the version
    number alone, so a half-applied upgrade is completed on the next call.
    SQLite cannot alter a CHECK constraint, so leave_requests is rebuilt
    (copy -> drop -> rename) inside one transaction.
    Returns a list of human-readable steps that were applied."""
    applied: list[str] = []
    if is_postgres(conn) or schema_version(conn) == 0:
        return applied                      # empty database: init_schema creates the current version
    try:
        if not conn.in_transaction:
            conn.execute("BEGIN")
        if "requested_by_user_id" not in _columns(conn, "leave_requests"):
            conn.execute("""CREATE TABLE leave_requests_v2 (
                leave_id INTEGER PRIMARY KEY,
                employee_id INTEGER NOT NULL REFERENCES employees(employee_id),
                leave_type TEXT NOT NULL CHECK (leave_type IN ('annual', 'sick', 'unpaid', 'other')),
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('approved', 'pending', 'rejected', 'cancelled')),
                approved_by_user_id INTEGER REFERENCES users(user_id),
                reason TEXT,
                requested_by_user_id INTEGER REFERENCES users(user_id),
                requested_at TEXT,
                decided_at TEXT,
                decision_note TEXT,
                CHECK (end_date >= start_date))""")
            conn.execute("""INSERT INTO leave_requests_v2(leave_id, employee_id, leave_type, start_date, end_date,
                                                          status, approved_by_user_id)
                            SELECT leave_id, employee_id, leave_type, start_date, end_date, status, approved_by_user_id
                            FROM leave_requests""")
            conn.execute("DROP TABLE leave_requests")
            conn.execute("ALTER TABLE leave_requests_v2 RENAME TO leave_requests")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_leave_employee ON leave_requests(employee_id, start_date)")
            applied.append("leave_requests: self-service workflow columns and 'cancelled' status")
        if "must_change_password" not in _columns(conn, "users"):
            conn.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0 "
                         "CHECK (must_change_password IN (0, 1))")
            applied.append("users: must_change_password")
        # ---- v3: Arabic names and gender
        for table, column, sqltype in V3_COLUMNS:
            if column not in _columns(conn, table):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sqltype}")
                applied.append(f"{table}: {column}")
        # attendance_corrections and stored_files are created by schema.sql (CREATE TABLE IF NOT EXISTS)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_leave_status ON leave_requests(status, employee_id)")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    # v3: the General Manager role changes the users CHECK constraint (needs its own procedure)
    users_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'").fetchone()[0]
    if "'gm'" not in users_sql:
        _rebuild_users_for_gm(conn)
        applied.append("users: 'gm' (General Manager) role")
    conn.execute("INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?) "
                 "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (str(SCHEMA_VERSION),))
    conn.commit()
    return applied


def _rebuild_users_for_gm(conn) -> None:
    """SQLite cannot change a CHECK constraint, so the users table is copied into a new one.
    Many tables reference users, so foreign-key enforcement is paused for the swap (the
    documented SQLite procedure, which only works outside a transaction) and every
    reference is re-checked before the change is committed."""
    keep = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        conn.execute("""CREATE TABLE users_v3 (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('gm', 'hr', 'manager', 'employee')),
            employee_id INTEGER UNIQUE REFERENCES employees(employee_id),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
            last_login_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0, 1)))""")
        conn.execute(f"INSERT INTO users_v3({', '.join(keep)}) SELECT {', '.join(keep)} FROM users")
        conn.execute("DROP TABLE users")
        conn.execute("ALTER TABLE users_v3 RENAME TO users")
        problems = conn.execute("PRAGMA foreign_key_check").fetchall()
        if problems:
            raise RuntimeError(f"foreign key check failed after rebuilding users: {[tuple(p) for p in problems[:5]]}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _pg_upgrade(conn) -> list[str]:
    """Bring an existing PostgreSQL database to v3 (idempotent; cheap when already current)."""
    applied = []
    for table, column, sqltype in V3_COLUMNS:
        exists = conn.execute("SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() "
                              "AND table_name = ? AND column_name = ?", (table, column)).fetchone()
        if not exists:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sqltype}")
            applied.append(f"{table}: {column}")
    check = conn.execute("SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
                         "WHERE t.relname = 'users' AND t.relnamespace = current_schema()::regnamespace "
                         "AND c.contype = 'c' AND pg_get_constraintdef(c.oid) LIKE '%role%'").fetchone()
    if check and "'gm'" not in check[0]:
        conn.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
        conn.execute("ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('gm', 'hr', 'manager', 'employee'))")
        applied.append("users: 'gm' (General Manager) role")
    conn.execute("UPDATE schema_meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION),))
    conn.commit()
    return applied


def ensure_schema(target: str) -> list[str]:
    """Called on web start-up: bring an existing database to the current version.

    PostgreSQL: creates the tables if the database is empty (idempotent DDL)."""
    if is_url(target):
        conn = connect(target)
        try:
            if schema_version(conn) == 0:
                init_schema(conn)
                return ["postgresql: schema created"]
            conn.executescript(PG_SCHEMA_PATH.read_text(encoding="utf-8"))   # new tables / indexes only
            return _pg_upgrade(conn)
        finally:
            conn.close()
    if not Path(target).exists():
        return []
    conn = connect(target)
    try:
        if schema_version(conn) == 0:
            return []
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))   # new tables / indexes only
        return migrate(conn)
    finally:
        conn.close()


def now_str() -> str:
    """Server timestamp for audit columns (local server time, second precision)."""
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def in_clause(values) -> tuple[str, list]:
    """Return '(?,?,?)' and the parameter list for an IN filter."""
    values = list(values)
    if not values:
        return "(NULL)", []
    return "(" + ",".join("?" for _ in values) + ")", values
