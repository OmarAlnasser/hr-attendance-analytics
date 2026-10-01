"""Load generated master data into the database.

Demo accounts get a password from HR_DEMO_PASSWORD, or a random one that is
written to instance/demo_credentials.txt (git-ignored). No credential is
stored in the source code.
"""
from __future__ import annotations

import secrets
from datetime import date
from pathlib import Path

import pandas as pd
from werkzeug.security import generate_password_hash

from ..db import repos
from ..db.connection import transaction
from ..domain.scoring import DEFAULT_WEIGHTS
from ..i18n import N_
from ..security.scope import load_user_context
from .evaluations import save_evaluation


def _none(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) or v == "" else v


def load_master_data(conn, data_dir: str | Path, *, settings, demo_password: str | None = None,
                     first_period: str | None = None) -> dict:
    data_dir = Path(data_dir) / "master"
    shifts = pd.read_csv(data_dir / "shifts.csv", dtype=str)
    depts = pd.read_csv(data_dir / "departments.csv", dtype=str)
    emps = pd.read_csv(data_dir / "employees.csv", dtype=str, keep_default_na=False)
    for col in ("full_name_ar", "gender", "job_title_ar"):         # older generated files lack these
        if col not in emps:
            emps[col] = ""
    assigns = pd.read_csv(data_dir / "shift_assignments.csv", dtype=str, keep_default_na=False)
    hols = pd.read_csv(data_dir / "holidays.csv", dtype=str)
    leaves = pd.read_csv(data_dir / "leave_requests.csv", dtype=str)
    users = pd.read_csv(data_dir / "users.csv", dtype=str)

    if conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]:
        raise RuntimeError("The database already contains employees. Start from a fresh database: python -m hr_analytics init-db --reset")

    password = demo_password or secrets.token_urlsafe(10)
    with transaction(conn):
        shift_ids = {}
        for r in shifts.to_dict("records"):
            shift_ids[r["code"]] = repos.save_shift(conn, {**r, "name_ar": _none(r.get("name_ar")), "is_active": 1})
        dept_ids = {r["code"]: repos.save_department(conn, {"code": r["code"], "name": r["name"],
                                                            "name_ar": _none(r.get("name_ar"))})
                    for r in depts.to_dict("records")}
        emp_ids = {}
        for r in emps.to_dict("records"):
            emp_ids[r["employee_code"]] = repos.save_employee(conn, {
                "employee_code": r["employee_code"], "badge_id": r["badge_id"], "full_name": r["full_name"],
                "full_name_ar": _none(r["full_name_ar"]), "gender": _none(r["gender"]),
                "email": r["email"], "job_title": r["job_title"], "job_title_ar": _none(r["job_title_ar"]),
                "department_id": dept_ids[r["department_code"]],
                "manager_employee_id": None, "hire_date": r["hire_date"],
                "termination_date": _none(r["termination_date"]), "is_synthetic": 1})
        for r in emps.to_dict("records"):
            if _none(r["manager_code"]):
                conn.execute("UPDATE employees SET manager_employee_id = ? WHERE employee_id = ?",
                             (emp_ids[r["manager_code"]], emp_ids[r["employee_code"]]))
        for r in depts.to_dict("records"):
            conn.execute("UPDATE departments SET manager_employee_id = ? WHERE department_id = ?",
                         (emp_ids[r["manager_employee_code"]], dept_ids[r["code"]]))
        conn.executemany("INSERT INTO employee_shift_assignments(employee_id, shift_id, effective_from, effective_to) "
                         "VALUES (?,?,?,?)",
                         [(emp_ids[a["employee_code"]], shift_ids[a["shift_code"]], a["effective_from"],
                           _none(a["effective_to"])) for a in assigns.to_dict("records")])
        conn.executemany("INSERT INTO holidays(holiday_date, name, name_ar, is_illustrative) VALUES (?,?,?,?)",
                         [(h["holiday_date"], h["name"], _none(h.get("name_ar")), int(h["is_illustrative"]))
                          for h in hols.to_dict("records")])
        conn.executemany("INSERT INTO leave_requests(employee_id, leave_type, start_date, end_date, status) "
                         "VALUES (?,?,?,?,?)",
                         [(emp_ids[lv["employee_code"]], lv["leave_type"], lv["start_date"], lv["end_date"], lv["status"])
                          for lv in leaves.to_dict("records")])
        for u in users.to_dict("records"):
            repos.create_user(conn, u["username"], generate_password_hash(password, method=settings.PASSWORD_HASH_METHOD),
                              u["role"], emp_ids[u["employee_code"]])
        first_period = first_period or settings.SYNTHETIC_START[:7]
        repos.upsert_weights(conn, first_period, DEFAULT_WEIGHTS, None)
        repos.audit(conn, None, "seed", "database", None, {"employees": len(emp_ids), "source": str(data_dir)})

    cred_file = None
    if not demo_password:
        cred_file = Path(settings.INSTANCE_DIR) / "demo_credentials.txt"
        cred_file.parent.mkdir(parents=True, exist_ok=True)
        gm_users = users[users.role == "gm"].username.tolist()
        hr_users = users[users.role == "hr"].username.tolist()
        mgr_users = users[users.role == "manager"].username.tolist()
        cred_file.write_text(
            "SYNTHETIC DEMO ACCOUNTS — local testing only, not real credentials.\n"
            f"Shared demo password: {password}\n"
            f"General Manager: {', '.join(gm_users)}\n"
            f"HR accounts: {', '.join(hr_users)}\n"
            f"Manager accounts: {', '.join(mgr_users)}\n"
            "Employee accounts: every other employee code in lower case (e.g. e0010)\n",
            encoding="utf-8")
    return {"employees": len(emp_ids), "users": len(users), "credentials_file": str(cred_file) if cred_file else None}


def load_evaluations(conn, data_dir: str | Path, today: date | None = None) -> dict:
    df = pd.read_csv(Path(data_dir) / "evaluations" / "evaluations.csv", dtype=str, keep_default_na=False)
    user_ids = {r["username"]: r["user_id"] for r in conn.execute("SELECT username, user_id FROM users")}
    emp_ids = {r["employee_code"]: r["employee_id"] for r in conn.execute("SELECT employee_code, employee_id FROM employees")}
    contexts: dict = {}
    saved, failed = 0, []
    for r in df.to_dict("records"):
        uid = user_ids.get(r["evaluator_username"])
        if uid is None:
            failed.append((r["employee_code"], r["period"], "unknown evaluator"))
            continue
        ctx = contexts.setdefault(uid, load_user_context(conn, uid))
        res = save_evaluation(conn, ctx, emp_ids[r["employee_code"]], r["period"],
                              {k: r[k] for k in ("punctuality", "communication", "task_completion", "teamwork")},
                              r["comments"], today=today)
        if res.ok:
            saved += 1
        else:
            failed.append((r["employee_code"], r["period"], "; ".join(res.errors)))
    return {"saved": saved, "failed": failed}


def seed_demo_requests(conn, settings, max_each: int = 4) -> dict:
    """Demo only: a few pending self-service requests so Approvals and My requests are not empty.

    Corrections are created for real single-punch days in the last processed month
    and pass the same validation as the web form (with "now" = the day after the data ends)."""
    from datetime import datetime, timedelta

    from . import requests as rq
    last = repos.latest_attendance_date(conn)
    if not last:
        return {"corrections": 0, "leave": 0}
    now = datetime.fromisoformat(last) + timedelta(days=1, hours=9)
    candidates = conn.execute(
        """SELECT a.employee_id, a.shift_date, a.scheduled_start, a.scheduled_end, a.notes, u.user_id
           FROM attendance_daily a JOIN users u ON u.employee_id = a.employee_id AND u.role = 'employee'
           JOIN shifts s ON s.shift_id = a.shift_id
           WHERE a.status = 'incomplete' AND a.shift_date >= ? AND s.code = 'DAY'
           ORDER BY a.shift_date DESC, a.employee_id""", (last[:8] + "01",)).fetchall()
    made, used = 0, set()
    # stored in English like any typed reason; the Arabic pages show these demo sentences in Arabic
    reasons = [N_("Badge reader at the main gate was not responding"),
               N_("Forgot my badge at home, signed the visitor log"),
               N_("Left through the warehouse exit which has no reader"),
               N_("Clock showed an error, security can confirm")]
    for c in candidates:
        if made >= max_each or c["employee_id"] in used:
            continue
        missing_out = c["notes"] and "missing_out" in c["notes"]
        base = datetime.fromisoformat(c["scheduled_end"] if missing_out else c["scheduled_start"])
        when = base + timedelta(minutes=3 if missing_out else 4)
        emp = repos.get_employee(conn, c["employee_id"])
        v = rq.validate_correction(conn, settings, emp, {"punch_kind": "out" if missing_out else "in",
                                                         "punch_time": when.isoformat(sep=" "),
                                                         "reason": reasons[made % len(reasons)]}, now)
        if v.ok:
            with transaction(conn):
                repos.insert_correction(conn, v.data | {"requested_by_user_id": c["user_id"]})
            made += 1
            used.add(c["employee_id"])
    leave_made = 0
    # leave dates in the real future, so the demo requests look like upcoming leave whenever the demo is run
    start = max(date.fromisoformat(last), date.today()) + timedelta(days=14)
    people = conn.execute("""SELECT MIN(e.employee_id) AS employee_id FROM employees e
                             JOIN users u ON u.employee_id = e.employee_id AND u.role = 'employee'
                             WHERE e.termination_date IS NULL GROUP BY e.department_id
                             ORDER BY e.department_id""").fetchall()
    for i, p in enumerate(people[:3]):
        s0 = start + timedelta(days=7 * i)
        emp = repos.get_employee(conn, p["employee_id"])
        v = rq.validate_leave(conn, emp, {"leave_type": "annual", "start_date": s0.isoformat(),
                                          "end_date": (s0 + timedelta(days=2 + i)).isoformat(),
                                          "reason": N_("Family visit") if i == 0 else ""}, date.today())
        if v.ok:
            with transaction(conn):
                uid = conn.execute("SELECT user_id FROM users WHERE employee_id = ?", (emp["employee_id"],)).fetchone()[0]
                repos.insert_leave_request(conn, emp["employee_id"], "annual", v.data["start_date"],
                                           v.data["end_date"], v.data["reason"], uid)
            leave_made += 1
    return {"corrections": made, "leave": leave_made}
