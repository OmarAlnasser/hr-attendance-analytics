"""Shared test fixtures: isolated settings, a small hand-built organisation, and a web login helper."""
from __future__ import annotations

import os
import re
import tempfile
import uuid
from pathlib import Path

from werkzeug.security import generate_password_hash

from hr_analytics.config import Settings
from hr_analytics.db import repos
from hr_analytics.db.connection import connect, init_schema, transaction
from hr_analytics.domain.scoring import DEFAULT_WEIGHTS

PASSWORD = "test-password-123"
HASH_METHOD = "pbkdf2:sha256:1000"      # fast for tests; production default is scrypt


# Set HR_TEST_DATABASE_URL=postgresql://... to run the whole suite against PostgreSQL.
# Each test then gets its own schema (created and dropped around the test).
PG_URL = os.environ.get("HR_TEST_DATABASE_URL", "")


def pg_schema_url(schema: str) -> str:
    sep = "&" if "?" in PG_URL else "?"
    return f"{PG_URL}{sep}options=-csearch_path%3D{schema}"


def pg_create_schema() -> str:
    import psycopg
    name = "t_" + uuid.uuid4().hex[:12]
    with psycopg.connect(PG_URL, autocommit=True) as c:
        c.execute(f"CREATE SCHEMA {name}")
    return name


def pg_drop_schema(name: str) -> None:
    import psycopg
    with psycopg.connect(PG_URL, autocommit=True) as c:
        # connections the code under test left open (e.g. CLI commands run in-process) would block the DROP
        c.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() "
                  "AND pid <> pg_backend_pid() AND state LIKE 'idle%%'")
        c.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")


def make_settings(tmp: str | Path, **overrides) -> Settings:
    tmp = Path(tmp)
    base = dict(TESTING=True, SECRET_KEY="test-secret-key", DATABASE_PATH=str(tmp / "test.sqlite3"),
                INSTANCE_DIR=str(tmp / "instance"), DATA_DIR=str(tmp / "data"), REPORTS_DIR=str(tmp / "reports"),
                EXPORTS_DIR=str(tmp / "powerbi"), MODELS_DIR=str(tmp / "models"), UPLOAD_DIR=str(tmp / "uploads"),
                PASSWORD_HASH_METHOD=HASH_METHOD, ORG_TIMEZONE="Asia/Riyadh", DEFAULT_DEVICE_TIMEZONE="Asia/Riyadh")
    base.update(overrides)
    s = Settings.from_env(**base)
    s.ensure_dirs()
    return s


class TempDirMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._pg_schema = pg_create_schema() if PG_URL else None
        extra = {"DATABASE_URL": pg_schema_url(self._pg_schema)} if self._pg_schema else {}
        self.settings = make_settings(self.tmp, **extra)
        self.conn = connect(self.settings.db_target)
        init_schema(self.conn)

    def tearDown(self):
        self.conn.close()
        if self._pg_schema:
            pg_drop_schema(self._pg_schema)
        self._tmp.cleanup()


def build_small_org(conn) -> dict:
    """Three departments, two shifts, seven employees, users for every role.

    March 2026: the 1st is a Sunday (workweek SUN-THU, Fri/Sat off)."""
    ids: dict = {}
    with transaction(conn):
        ids["DAY"] = repos.save_shift(conn, {"code": "DAY", "name": "Day", "start_time": "08:00", "end_time": "16:00",
                                             "grace_minutes": 15, "early_leave_grace_minutes": 5,
                                             "workdays": "SUN,MON,TUE,WED,THU", "is_active": 1})
        ids["NIGHT"] = repos.save_shift(conn, {"code": "NIGHT", "name": "Night", "start_time": "22:00",
                                               "end_time": "06:00", "grace_minutes": 15,
                                               "early_leave_grace_minutes": 5, "workdays": "SUN,MON,TUE,WED,THU",
                                               "is_active": 1})
        for code, name in (("OPS", "Operations"), ("IT", "Information Technology"), ("HR", "Human Resources")):
            ids[code] = repos.save_department(conn, {"code": code, "name": name})
        people = [  # code, badge, dept, hire, termination, shift
            ("E001", "B001", "OPS", "2024-01-01", None, "DAY"),     # OPS manager
            ("E002", "B002", "OPS", "2024-01-01", None, "DAY"),     # OPS employee
            ("E003", "B003", "IT", "2024-01-01", None, "DAY"),      # IT employee
            ("E004", "B004", "IT", "2024-01-01", None, "DAY"),      # IT manager
            ("E005", "B005", "OPS", "2024-01-01", None, "NIGHT"),   # night shift
            ("E006", "B006", "OPS", "2026-03-10", None, "DAY"),     # hired mid-month
            ("E007", "B007", "OPS", "2024-01-01", "2026-03-05", "DAY"),  # left early in the month
            ("E009", "B009", "HR", "2024-01-01", None, "DAY"),      # HR officer
        ]
        for code, badge, dept, hire, term, shift in people:
            eid = repos.save_employee(conn, {"employee_code": code, "badge_id": badge, "full_name": f"Person {code}",
                                             "email": f"{code.lower()}@example.com", "job_title": "Staff",
                                             "department_id": ids[dept], "manager_employee_id": None,
                                             "hire_date": hire, "termination_date": term})
            ids[code] = eid
            conn.execute("INSERT INTO employee_shift_assignments(employee_id, shift_id, effective_from) VALUES (?,?,?)",
                         (eid, ids[shift], hire))
        conn.execute("UPDATE departments SET manager_employee_id = ? WHERE department_id = ?", (ids["E001"], ids["OPS"]))
        conn.execute("UPDATE departments SET manager_employee_id = ? WHERE department_id = ?", (ids["E004"], ids["IT"]))
        conn.execute("UPDATE departments SET manager_employee_id = ? WHERE department_id = ?", (ids["E009"], ids["HR"]))
        h = generate_password_hash(PASSWORD, method=HASH_METHOD)
        for username, role, emp in (("mgr_ops", "manager", "E001"), ("emp_ops", "employee", "E002"),
                                    ("emp_it", "employee", "E003"), ("mgr_it", "manager", "E004"),
                                    ("hr1", "hr", "E009")):
            ids["user_" + username] = repos.create_user(conn, username, h, role, ids[emp])
        repos.upsert_weights(conn, "2025-01", DEFAULT_WEIGHTS, None)
    return ids


def write_csv(path: Path, rows: list[tuple], header=("badge_id", "punch_time", "device_id", "punch_type")) -> Path:
    lines = [",".join(header)] + [",".join(str(v) for v in r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def csrf_from(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "no CSRF token in page"
    return m.group(1)


def login(client, username: str, password: str = PASSWORD):
    token = csrf_from(client.get("/login").get_data(as_text=True))
    return client.post("/login", data={"username": username, "password": password, "csrf_token": token})


def token(client) -> str:
    return csrf_from(client.get("/account").get_data(as_text=True))
