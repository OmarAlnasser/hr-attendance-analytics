"""Repository functions — the data-access layer.

Nearly all SQL lives here; the few other statements are listed in
docs/production_migration.md so a database migration has a complete checklist.
Functions that return user-facing data take a UserContext and apply
`scope_clause` so authorisation is enforced at the query level.
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd

from ..security.scope import UserContext, scope_clause
from .connection import in_clause, now_str, read_sql, rows_to_dicts

# =========================================================== organisation ==

def list_departments(conn, department_ids: set[int] | None = None) -> list[dict]:
    sql = """SELECT d.*, m.full_name AS manager_name, m.full_name_ar AS manager_name_ar,
                    (SELECT COUNT(*) FROM employees e WHERE e.department_id = d.department_id
                       AND e.termination_date IS NULL) AS active_headcount
             FROM departments d LEFT JOIN employees m ON m.employee_id = d.manager_employee_id"""
    params: list = []
    if department_ids is not None:
        marks, params = in_clause(department_ids)
        sql += f" WHERE d.department_id IN {marks}"
    return rows_to_dicts(conn.execute(sql + " ORDER BY d.name", params))


def get_department(conn, department_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM departments WHERE department_id = ?", (department_id,)).fetchone()
    return dict(r) if r else None


def save_department(conn, data: dict, department_id: int | None = None) -> int:
    if department_id:
        conn.execute("UPDATE departments SET code=?, name=?, name_ar=?, manager_employee_id=?, is_active=? WHERE department_id=?",
                     (data["code"], data["name"], data.get("name_ar"), data.get("manager_employee_id"),
                      data.get("is_active", 1), department_id))
        return department_id
    cur = conn.execute("INSERT INTO departments(code, name, name_ar, manager_employee_id, is_active) VALUES (?,?,?,?,?)",
                       (data["code"], data["name"], data.get("name_ar"), data.get("manager_employee_id"),
                        data.get("is_active", 1)))
    return cur.lastrowid


def list_shifts(conn) -> list[dict]:
    return rows_to_dicts(conn.execute("SELECT * FROM shifts ORDER BY start_time"))


def get_shift(conn, shift_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM shifts WHERE shift_id = ?", (shift_id,)).fetchone()
    return dict(r) if r else None


def save_shift(conn, data: dict, shift_id: int | None = None) -> int:
    cols = ("code", "name", "name_ar", "start_time", "end_time", "grace_minutes", "early_leave_grace_minutes",
            "workdays", "is_active")
    vals = [data.get(c) for c in cols]
    if shift_id:
        conn.execute(f"UPDATE shifts SET {', '.join(c + '=?' for c in cols)} WHERE shift_id=?", (*vals, shift_id))
        return shift_id
    cur = conn.execute(f"INSERT INTO shifts({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
    return cur.lastrowid


def list_employees(conn, user: UserContext, department_id: int | None = None, q: str | None = None,
                   include_terminated: bool = True, limit: int = 500) -> list[dict]:
    clause, params = scope_clause(user, "e")
    sql = f"""SELECT e.*, d.name AS department_name, d.name_ar AS department_name_ar, d.code AS department_code,
                     (SELECT s.code FROM employee_shift_assignments a JOIN shifts s ON s.shift_id = a.shift_id
                       WHERE a.employee_id = e.employee_id ORDER BY a.effective_from DESC LIMIT 1) AS shift_code
              FROM employees e JOIN departments d ON d.department_id = e.department_id
              WHERE {clause}"""
    if department_id:
        sql += " AND e.department_id = ?"
        params.append(department_id)
    if q:
        sql += " AND (e.full_name LIKE ? OR e.full_name_ar LIKE ? OR e.employee_code LIKE ? OR e.badge_id LIKE ?)"
        params += [f"%{q}%"] * 4
    if not include_terminated:
        sql += " AND e.termination_date IS NULL"
    sql += " ORDER BY e.employee_code LIMIT ?"
    params.append(limit)
    return rows_to_dicts(conn.execute(sql, params))


def get_employee(conn, employee_id: int) -> dict | None:
    r = conn.execute("""SELECT e.*, d.name AS department_name, d.name_ar AS department_name_ar,
                               (SELECT u.role FROM users u WHERE u.employee_id = e.employee_id) AS app_role
                        FROM employees e
                        JOIN departments d ON d.department_id = e.department_id WHERE e.employee_id = ?""",
                     (employee_id,)).fetchone()
    return dict(r) if r else None


def save_employee(conn, data: dict, employee_id: int | None = None) -> int:
    cols = ("employee_code", "badge_id", "full_name", "full_name_ar", "gender", "email", "job_title", "job_title_ar",
            "department_id", "manager_employee_id", "hire_date", "termination_date")
    vals = [data.get(c) for c in cols]
    if employee_id:
        conn.execute(f"UPDATE employees SET {', '.join(c + '=?' for c in cols)} WHERE employee_id=?", (*vals, employee_id))
        return employee_id
    cur = conn.execute(f"INSERT INTO employees({', '.join(cols)}, is_synthetic) VALUES ({','.join('?' * len(cols))}, ?)",
                       (*vals, int(data.get("is_synthetic", 0))))
    return cur.lastrowid


def badge_map(conn) -> dict[str, int]:
    return {r["badge_id"]: r["employee_id"] for r in conn.execute("SELECT badge_id, employee_id FROM employees")}


def employment_rows(conn, employee_ids=None) -> list[dict]:
    sql = "SELECT employee_id, hire_date, termination_date, department_id FROM employees"
    params: list = []
    if employee_ids is not None:
        marks, params = in_clause(employee_ids)
        sql += f" WHERE employee_id IN {marks}"
    return rows_to_dicts(conn.execute(sql, params))


def assignments(conn, employee_ids=None) -> list[dict]:
    sql = "SELECT * FROM employee_shift_assignments"
    params: list = []
    if employee_ids is not None:
        marks, params = in_clause(employee_ids)
        sql += f" WHERE employee_id IN {marks}"
    return rows_to_dicts(conn.execute(sql + " ORDER BY employee_id, effective_from", params))


def current_assignment(conn, employee_id: int) -> dict | None:
    r = conn.execute("""SELECT * FROM employee_shift_assignments WHERE employee_id = ?
                        ORDER BY effective_from DESC LIMIT 1""", (employee_id,)).fetchone()
    return dict(r) if r else None


def set_shift_assignment(conn, employee_id: int, shift_id: int, effective_from: str) -> None:
    """Close the open assignment the day before and start a new one."""
    cur = current_assignment(conn, employee_id)
    if cur and cur["shift_id"] == shift_id and cur["effective_to"] is None:
        return
    if cur and cur["effective_from"] >= effective_from:
        conn.execute("DELETE FROM employee_shift_assignments WHERE assignment_id = ?", (cur["assignment_id"],))
    elif cur and cur["effective_to"] is None:
        prev_day = date.fromordinal(date.fromisoformat(effective_from).toordinal() - 1).isoformat()
        conn.execute("UPDATE employee_shift_assignments SET effective_to = ? WHERE assignment_id = ?",
                     (prev_day, cur["assignment_id"]))
    conn.execute("INSERT INTO employee_shift_assignments(employee_id, shift_id, effective_from) VALUES (?,?,?)",
                 (employee_id, shift_id, effective_from))


def holidays_between(conn, start: str, end: str) -> dict[str, str]:
    return {r["holiday_date"]: r["name"] for r in conn.execute(
        "SELECT holiday_date, name FROM holidays WHERE holiday_date BETWEEN ? AND ?", (start, end))}


def list_holidays(conn) -> list[dict]:
    return rows_to_dicts(conn.execute("SELECT * FROM holidays ORDER BY holiday_date"))


def approved_leaves(conn, start: str, end: str, employee_ids=None) -> list[dict]:
    sql = """SELECT employee_id, leave_type, start_date, end_date FROM leave_requests
             WHERE status = 'approved' AND end_date >= ? AND start_date <= ?"""
    params: list = [start, end]
    if employee_ids is not None:
        marks, extra = in_clause(employee_ids)
        sql += f" AND employee_id IN {marks}"
        params += extra
    return rows_to_dicts(conn.execute(sql, params))


# ============================================================== imports ==

def find_loaded_batch_by_hash(conn, sha256: str) -> dict | None:
    r = conn.execute("SELECT * FROM import_batches WHERE file_sha256 = ? AND status IN ('success','partial')",
                     (sha256,)).fetchone()
    return dict(r) if r else None


def insert_batch(conn, b: dict) -> int:
    cols = ("source_type", "source_name", "stored_path", "source_device", "source_timezone", "file_sha256",
            "imported_by_user_id", "imported_at", "status", "rows_total", "rows_accepted", "rows_duplicate",
            "rows_rejected", "min_punch_time", "max_punch_time", "message")
    cur = conn.execute(f"INSERT INTO import_batches({', '.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                       [b.get(c, 0 if c.startswith("rows_") else None) for c in cols])
    return cur.lastrowid


def update_batch_counts(conn, batch_id: int, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE import_batches SET {sets} WHERE batch_id = ?", (*fields.values(), batch_id))


def insert_raw_punches(conn, rows: list[tuple]) -> int:
    """rows: (batch_id, source_row, badge_id, employee_id, punch_time_local, punch_time_raw, punch_type, device_id).
    Returns the number of NEW rows; exact duplicates of stored punches are skipped."""
    if not rows:
        return 0
    before = conn.total_changes
    conn.executemany(
        """INSERT INTO raw_punches(batch_id, source_row, badge_id, employee_id, punch_time_local,
                                   punch_time_raw, punch_type, device_id)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT (employee_id, punch_time_local, device_id) DO NOTHING""", rows)
    return conn.total_changes - before


def insert_rejects(conn, rows: list[tuple]) -> None:
    """rows: (batch_id, source_row, raw_json, reason_code, reason_detail)"""
    if rows:
        conn.executemany("INSERT INTO rejected_rows(batch_id, source_row, raw_data, reason_code, reason_detail) "
                         "VALUES (?,?,?,?,?)", rows)


def list_batches(conn, limit: int = 100) -> list[dict]:
    return rows_to_dicts(conn.execute(
        """SELECT b.*, u.username AS imported_by FROM import_batches b
           LEFT JOIN users u ON u.user_id = b.imported_by_user_id ORDER BY b.batch_id DESC LIMIT ?""", (limit,)))


def get_batch(conn, batch_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM import_batches WHERE batch_id = ?", (batch_id,)).fetchone()
    return dict(r) if r else None


def batch_rejects(conn, batch_id: int, limit: int = 500) -> list[dict]:
    return rows_to_dicts(conn.execute("SELECT * FROM rejected_rows WHERE batch_id = ? ORDER BY source_row LIMIT ?",
                                      (batch_id, limit)))


def reject_summary(conn, batch_ids=None, start: str | None = None, end: str | None = None) -> list[dict]:
    sql = """SELECT r.reason_code, COUNT(*) AS n FROM rejected_rows r
             JOIN import_batches b ON b.batch_id = r.batch_id WHERE 1=1"""
    params: list = []
    if batch_ids is not None:
        marks, extra = in_clause(batch_ids)
        sql += f" AND r.batch_id IN {marks}"
        params += extra
    if start and end:
        sql += " AND b.imported_at BETWEEN ? AND ?"
        params += [start, end]
    return rows_to_dicts(conn.execute(sql + " GROUP BY r.reason_code ORDER BY n DESC", params))


def batches_overlapping(conn, start_dt: str, end_dt: str) -> list[dict]:
    return rows_to_dicts(conn.execute(
        """SELECT * FROM import_batches WHERE min_punch_time <= ? AND max_punch_time >= ?
           ORDER BY batch_id""", (end_dt, start_dt)))


# =========================================================== attendance ==

def punches_between(conn, start_dt: str, end_dt: str, employee_ids=None) -> list[dict]:
    sql = """SELECT punch_id, employee_id, punch_time_local FROM raw_punches
             WHERE punch_time_local >= ? AND punch_time_local < ?"""
    params: list = [start_dt, end_dt]
    if employee_ids is not None:
        marks, extra = in_clause(employee_ids)
        sql += f" AND employee_id IN {marks}"
        params += extra
    return rows_to_dicts(conn.execute(sql + " ORDER BY employee_id, punch_time_local", params))


ATTENDANCE_COLS = ("employee_id", "shift_date", "shift_id", "scheduled_start", "scheduled_end", "scheduled_minutes",
                   "status", "raw_punch_count", "punch_count", "first_punch", "last_punch", "is_late", "late_minutes",
                   "early_leave_minutes", "span_minutes", "leave_type", "holiday_name", "notes", "rule_version",
                   "processed_at")


def replace_attendance(conn, start: str, end: str, employee_ids: list[int], records: list[dict]) -> None:
    """Idempotent: delete the (employee, date) range then insert freshly computed rows."""
    for i in range(0, len(employee_ids), 500):
        chunk = employee_ids[i:i + 500]
        marks, params = in_clause(chunk)
        conn.execute(f"DELETE FROM attendance_daily WHERE shift_date BETWEEN ? AND ? AND employee_id IN {marks}",
                     [start, end, *params])
    conn.executemany(
        f"INSERT INTO attendance_daily({', '.join(ATTENDANCE_COLS)}) VALUES ({','.join('?' * len(ATTENDANCE_COLS))})",
        [[r.get(c) for c in ATTENDANCE_COLS] for r in records])


def replace_exceptions(conn, start_dt: str, end_dt: str, employee_ids: list[int], rows: list[tuple]) -> None:
    for i in range(0, len(employee_ids), 500):
        chunk = employee_ids[i:i + 500]
        marks, params = in_clause(chunk)
        conn.execute(f"""DELETE FROM punch_exceptions WHERE punch_time_local >= ? AND punch_time_local < ?
                         AND employee_id IN {marks}""", [start_dt, end_dt, *params])
    conn.executemany("""INSERT INTO punch_exceptions(punch_id, employee_id, punch_time_local, shift_date, reason, detected_at)
                        VALUES (?,?,?,?,?,?) ON CONFLICT (punch_id) DO UPDATE SET
                        shift_date = excluded.shift_date, reason = excluded.reason, detected_at = excluded.detected_at""",
                     rows)


def attendance_frame(conn, user: UserContext, start: str, end: str, department_id: int | None = None,
                     employee_id: int | None = None, status: str | None = None) -> pd.DataFrame:
    clause, params = scope_clause(user, "e")
    sql = f"""SELECT a.*, e.employee_code, e.full_name, e.full_name_ar, e.department_id, d.name AS department_name,
                     d.name_ar AS department_name_ar, s.code AS shift_code, s.name AS shift_name,
                     s.name_ar AS shift_name_ar, h.name_ar AS holiday_name_ar
              FROM attendance_daily a
              JOIN employees e ON e.employee_id = a.employee_id
              JOIN departments d ON d.department_id = e.department_id
              LEFT JOIN shifts s ON s.shift_id = a.shift_id
              LEFT JOIN holidays h ON h.holiday_date = a.shift_date AND a.holiday_name IS NOT NULL
              WHERE a.shift_date BETWEEN ? AND ? AND {clause}"""
    params = [start, end, *params]
    if department_id:
        sql += " AND e.department_id = ?"
        params.append(department_id)
    if employee_id:
        sql += " AND e.employee_id = ?"
        params.append(employee_id)
    if status:
        sql += " AND a.status = ?"
        params.append(status)
    return read_sql(sql + " ORDER BY a.shift_date, e.employee_code", conn, params=params)


def exceptions_summary(conn, start_dt: str, end_dt: str, user: UserContext) -> list[dict]:
    clause, params = scope_clause(user, "e")
    return rows_to_dicts(conn.execute(
        f"""SELECT x.reason, COUNT(*) AS n FROM punch_exceptions x JOIN employees e ON e.employee_id = x.employee_id
            WHERE x.punch_time_local >= ? AND x.punch_time_local < ? AND {clause} GROUP BY x.reason""",
        [start_dt, end_dt, *params]))


# ========================================================== performance ==

def weights_for_period(conn, period: str) -> dict | None:
    r = conn.execute("""SELECT * FROM evaluation_weights WHERE effective_from <= ?
                        ORDER BY effective_from DESC LIMIT 1""", (period,)).fetchone()
    return dict(r) if r else None


def list_weights(conn) -> list[dict]:
    return rows_to_dicts(conn.execute("""SELECT w.*, u.username AS created_by FROM evaluation_weights w
                                         LEFT JOIN users u ON u.user_id = w.created_by_user_id
                                         ORDER BY effective_from DESC"""))


def upsert_weights(conn, effective_from: str, w: dict, user_id: int | None) -> int:
    existing = conn.execute("SELECT weights_id FROM evaluation_weights WHERE effective_from = ?",
                            (effective_from,)).fetchone()
    used = existing and conn.execute("SELECT 1 FROM performance_evaluations WHERE weights_id = ? LIMIT 1",
                                     (existing["weights_id"],)).fetchone()
    if used:
        raise ValueError("These weights are already used by saved evaluations. "
                         "Create a new version with a later effective period instead.")
    vals = (w["punctuality"], w["communication"], w["task_completion"], w["teamwork"])
    if existing:
        conn.execute("""UPDATE evaluation_weights SET w_punctuality=?, w_communication=?, w_task_completion=?,
                        w_teamwork=?, created_by_user_id=?, created_at=? WHERE weights_id=?""",
                     (*vals, user_id, now_str(), existing["weights_id"]))
        return existing["weights_id"]
    cur = conn.execute("""INSERT INTO evaluation_weights(effective_from, w_punctuality, w_communication,
                          w_task_completion, w_teamwork, created_by_user_id, created_at) VALUES (?,?,?,?,?,?,?)""",
                       (effective_from, *vals, user_id, now_str()))
    return cur.lastrowid


def get_evaluation(conn, employee_id: int, period: str) -> dict | None:
    r = conn.execute("SELECT * FROM performance_evaluations WHERE employee_id = ? AND period = ?",
                     (employee_id, period)).fetchone()
    return dict(r) if r else None


EVAL_COLS = ("employee_id", "period", "evaluator_user_id", "score_punctuality", "score_communication",
             "score_task_completion", "score_teamwork", "weights_id", "weighted_score", "comments")


def insert_evaluation(conn, ev: dict) -> int:
    ts = now_str()
    cur = conn.execute(f"""INSERT INTO performance_evaluations({', '.join(EVAL_COLS)}, created_at, updated_at)
                           VALUES ({','.join('?' * len(EVAL_COLS))}, ?, ?)""",
                       (*[ev[c] for c in EVAL_COLS], ts, ts))
    return cur.lastrowid


def update_evaluation(conn, evaluation_id: int, ev: dict) -> None:
    cols = [c for c in EVAL_COLS if c not in ("employee_id", "period")]
    conn.execute(f"UPDATE performance_evaluations SET {', '.join(c + '=?' for c in cols)}, updated_at=? "
                 f"WHERE evaluation_id=?", (*[ev[c] for c in cols], now_str(), evaluation_id))


def insert_evaluation_history(conn, evaluation_id: int, user_id: int, action: str, old: dict | None, new: dict) -> None:
    conn.execute("""INSERT INTO evaluation_history(evaluation_id, changed_by_user_id, changed_at, action,
                    old_values, new_values) VALUES (?,?,?,?,?,?)""",
                 (evaluation_id, user_id, now_str(), action,
                  json.dumps(old, default=str) if old else None, json.dumps(new, default=str)))


def evaluation_history(conn, evaluation_id: int) -> list[dict]:
    return rows_to_dicts(conn.execute("""SELECT h.*, u.username FROM evaluation_history h
                                         JOIN users u ON u.user_id = h.changed_by_user_id
                                         WHERE evaluation_id = ? ORDER BY history_id""", (evaluation_id,)))


def evaluations_frame(conn, user: UserContext, period_from: str, period_to: str, department_id: int | None = None,
                      employee_id: int | None = None) -> pd.DataFrame:
    clause, params = scope_clause(user, "e")
    sql = f"""SELECT p.*, e.employee_code, e.full_name, e.full_name_ar, e.department_id, d.name AS department_name,
                     d.name_ar AS department_name_ar,
                     u.username AS evaluator, ue.full_name AS evaluator_name, ue.full_name_ar AS evaluator_name_ar
              FROM performance_evaluations p
              JOIN employees e ON e.employee_id = p.employee_id
              JOIN departments d ON d.department_id = e.department_id
              JOIN users u ON u.user_id = p.evaluator_user_id
              LEFT JOIN employees ue ON ue.employee_id = u.employee_id
              WHERE p.period BETWEEN ? AND ? AND {clause}"""
    params = [period_from, period_to, *params]
    if department_id:
        sql += " AND e.department_id = ?"
        params.append(department_id)
    if employee_id:
        sql += " AND e.employee_id = ?"
        params.append(employee_id)
    return read_sql(sql + " ORDER BY p.period, e.employee_code", conn, params=params)


def employees_frame(conn, user: UserContext, department_id: int | None = None) -> pd.DataFrame:
    clause, params = scope_clause(user, "e")
    sql = f"""SELECT e.employee_id, e.employee_code, e.full_name, e.full_name_ar, e.email, e.department_id,
                     e.hire_date, e.termination_date, d.name AS department_name, d.name_ar AS department_name_ar,
                     (SELECT u.role FROM users u WHERE u.employee_id = e.employee_id) AS app_role
              FROM employees e JOIN departments d ON d.department_id = e.department_id WHERE {clause}"""
    if department_id:
        sql += " AND e.department_id = ?"
        params.append(department_id)
    return read_sql(sql, conn, params=params)


# =============================================================== system ==

def get_user_by_username(conn, username: str) -> dict | None:
    r = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(r) if r else None


def create_user(conn, username: str, password_hash: str, role: str, employee_id: int | None) -> int:
    cur = conn.execute("INSERT INTO users(username, password_hash, role, employee_id) VALUES (?,?,?,?)",
                       (username, password_hash, role, employee_id))
    return cur.lastrowid


def touch_login(conn, user_id: int) -> None:
    conn.execute("UPDATE users SET last_login_at = ? WHERE user_id = ?", (now_str(), user_id))


def audit(conn, user_id: int | None, action: str, entity: str, entity_id=None, details: dict | None = None,
          remote_addr: str | None = None) -> None:
    conn.execute("""INSERT INTO audit_log(occurred_at, user_id, action, entity, entity_id, details, remote_addr)
                    VALUES (?,?,?,?,?,?,?)""",
                 (now_str(), user_id, action, entity, None if entity_id is None else str(entity_id),
                  json.dumps(details, default=str) if details else None, remote_addr))


def list_audit(conn, limit: int = 300) -> list[dict]:
    return rows_to_dicts(conn.execute("""SELECT a.*, u.username FROM audit_log a
                                         LEFT JOIN users u ON u.user_id = a.user_id
                                         ORDER BY a.audit_id DESC LIMIT ?""", (limit,)))


def replace_risk_scores(conn, target_period: str, model_version: str, rows: list[tuple]) -> None:
    conn.execute("DELETE FROM risk_scores WHERE target_period = ? AND model_version = ?", (target_period, model_version))
    conn.executemany("""INSERT INTO risk_scores(employee_id, feature_period, target_period, probability, method,
                        model_version, created_at) VALUES (?,?,?,?,?,?,?)""", rows)


def risk_frame(conn, user: UserContext, target_period: str) -> pd.DataFrame:
    clause, params = scope_clause(user, "e")
    return read_sql(
        f"""SELECT r.*, e.employee_code, e.full_name, e.full_name_ar, d.name AS department_name,
                   d.name_ar AS department_name_ar
            FROM risk_scores r JOIN employees e ON e.employee_id = r.employee_id
            JOIN departments d ON d.department_id = e.department_id
            WHERE r.target_period = ? AND {clause} ORDER BY r.probability DESC""",
        conn, params=[target_period, *params])


# ============================================================ web helpers ==

def latest_attendance_date(conn) -> str | None:
    r = conn.execute("SELECT MAX(shift_date) FROM attendance_daily").fetchone()
    return r[0] if r else None


def monthly_attendance_summary(conn, user: UserContext, start: str, end: str, department_id: int | None = None,
                               employee_id: int | None = None) -> list[dict]:
    """Per-month counts using the same status sets as domain.metrics."""
    clause, params = scope_clause(user, "e")
    sql = f"""SELECT substr(a.shift_date, 1, 7) AS period,
                     SUM(CASE WHEN a.status IN ('present','incomplete','absent') THEN 1 ELSE 0 END) AS expected_days,
                     SUM(CASE WHEN a.status IN ('present','incomplete') THEN 1 ELSE 0 END) AS attended_days,
                     SUM(CASE WHEN a.status = 'absent' THEN 1 ELSE 0 END) AS absent_days,
                     SUM(CASE WHEN a.status IN ('present','incomplete') AND a.is_late = 1 THEN 1 ELSE 0 END) AS late_days,
                     SUM(CASE WHEN a.status = 'incomplete' THEN 1 ELSE 0 END) AS incomplete_days,
                     COUNT(DISTINCT a.employee_id) AS employees
              FROM attendance_daily a JOIN employees e ON e.employee_id = a.employee_id
              WHERE a.shift_date BETWEEN ? AND ? AND {clause}"""
    params = [start, end, *params]
    if department_id:
        sql += " AND e.department_id = ?"
        params.append(department_id)
    if employee_id:
        sql += " AND e.employee_id = ?"
        params.append(employee_id)
    return rows_to_dicts(conn.execute(sql + " GROUP BY period ORDER BY period", params))


def monthly_score_summary(conn, user: UserContext, period_from: str, period_to: str,
                          department_id: int | None = None, employee_id: int | None = None) -> list[dict]:
    clause, params = scope_clause(user, "e")
    sql = f"""SELECT p.period, COUNT(*) AS evaluations, AVG(p.weighted_score) AS avg_score
              FROM performance_evaluations p JOIN employees e ON e.employee_id = p.employee_id
              WHERE p.period BETWEEN ? AND ? AND {clause}"""
    params = [period_from, period_to, *params]
    if department_id:
        sql += " AND e.department_id = ?"
        params.append(department_id)
    if employee_id:
        sql += " AND e.employee_id = ?"
        params.append(employee_id)
    return rows_to_dicts(conn.execute(sql + " GROUP BY p.period ORDER BY p.period", params))


def save_holiday(conn, holiday_date: str, name: str, name_ar: str | None = None) -> None:
    conn.execute("""INSERT INTO holidays(holiday_date, name, name_ar, is_illustrative) VALUES (?,?,?,0)
                    ON CONFLICT (holiday_date) DO UPDATE SET name = excluded.name, name_ar = excluded.name_ar,
                    is_illustrative = 0""",
                 (holiday_date, name, name_ar))


def delete_holiday(conn, holiday_date: str) -> None:
    conn.execute("DELETE FROM holidays WHERE holiday_date = ?", (holiday_date,))


def list_leaves(conn, user: UserContext, limit: int = 200, employee_id: int | None = None) -> list[dict]:
    clause, params = scope_clause(user, "e")
    sql = f"""SELECT l.*, e.employee_code, e.full_name, e.full_name_ar, u.username AS approved_by
              FROM leave_requests l JOIN employees e ON e.employee_id = l.employee_id
              LEFT JOIN users u ON u.user_id = l.approved_by_user_id WHERE {clause}"""
    if employee_id:
        sql += " AND e.employee_id = ?"
        params.append(employee_id)
    return rows_to_dicts(conn.execute(sql + " ORDER BY l.start_date DESC LIMIT ?", [*params, limit]))


def insert_leave(conn, employee_id: int, leave_type: str, start_date: str, end_date: str, status: str,
                 approved_by_user_id: int | None, decision_note: str | None = None) -> int:
    decided_at = now_str() if approved_by_user_id else None
    cur = conn.execute("""INSERT INTO leave_requests(employee_id, leave_type, start_date, end_date, status,
                          approved_by_user_id, decided_at, decision_note) VALUES (?,?,?,?,?,?,?,?)""",
                       (employee_id, leave_type, start_date, end_date, status, approved_by_user_id, decided_at,
                        decision_note))
    return cur.lastrowid


def get_employee_by_code(conn, code: str) -> dict | None:
    r = conn.execute("SELECT * FROM employees WHERE employee_code = ?", (code,)).fetchone()
    return dict(r) if r else None


def update_password(conn, user_id: int, password_hash: str) -> None:
    """The user's own change: also clears a pending forced change."""
    conn.execute("UPDATE users SET password_hash = ?, must_change_password = 0 WHERE user_id = ?",
                 (password_hash, user_id))


def get_user(conn, user_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return dict(r) if r else None


def evaluation_by_id(conn, evaluation_id: int) -> dict | None:
    r = conn.execute("""SELECT p.*, e.employee_code, e.full_name, e.full_name_ar, e.department_id, u.username AS evaluator
                        FROM performance_evaluations p JOIN employees e ON e.employee_id = p.employee_id
                        JOIN users u ON u.user_id = p.evaluator_user_id WHERE p.evaluation_id = ?""",
                     (evaluation_id,)).fetchone()
    return dict(r) if r else None


def latest_risk_period(conn) -> str | None:
    r = conn.execute("SELECT MAX(target_period) FROM risk_scores").fetchone()
    return r[0] if r else None


def get_run(conn, run_id: int) -> dict | None:
    r = conn.execute("SELECT * FROM report_runs WHERE run_id = ?", (run_id,)).fetchone()
    return dict(r) if r else None


# ============================================== v2: self-service requests ==
# Leave requests and missed-punch corrections. Listing functions take a
# UserContext and apply scope_clause like every other user-facing query.

def overlapping_leave(conn, employee_id: int, start: str, end: str, exclude_id: int | None = None) -> dict | None:
    sql = """SELECT * FROM leave_requests WHERE employee_id = ? AND status IN ('pending','approved')
             AND end_date >= ? AND start_date <= ?"""
    params: list = [employee_id, start, end]
    if exclude_id is not None:
        sql += " AND leave_id <> ?"
        params.append(exclude_id)
    r = conn.execute(sql + " ORDER BY start_date LIMIT 1", params).fetchone()
    return dict(r) if r else None


def insert_leave_request(conn, employee_id: int, leave_type: str, start_date: str, end_date: str, reason: str | None,
                         requested_by_user_id: int) -> int:
    cur = conn.execute("""INSERT INTO leave_requests(employee_id, leave_type, start_date, end_date, status, reason,
                          requested_by_user_id, requested_at) VALUES (?,?,?,?, 'pending', ?,?,?)""",
                       (employee_id, leave_type, start_date, end_date, reason, requested_by_user_id, now_str()))
    return cur.lastrowid


def get_leave(conn, leave_id: int) -> dict | None:
    r = conn.execute("""SELECT l.*, e.employee_code, e.full_name, e.full_name_ar, e.department_id FROM leave_requests l
                        JOIN employees e ON e.employee_id = l.employee_id WHERE l.leave_id = ?""", (leave_id,)).fetchone()
    return dict(r) if r else None


def decide_leave(conn, leave_id: int, status: str, user_id: int, note: str | None) -> bool:
    """pending -> approved/rejected. Returns False if the request was no longer pending (double click, race)."""
    cur = conn.execute("""UPDATE leave_requests SET status = ?, approved_by_user_id = ?, decided_at = ?, decision_note = ?
                          WHERE leave_id = ? AND status = 'pending'""", (status, user_id, now_str(), note, leave_id))
    return cur.rowcount == 1


def cancel_leave(conn, leave_id: int, from_statuses: tuple[str, ...]) -> bool:
    marks, params = in_clause(from_statuses)
    cur = conn.execute(f"""UPDATE leave_requests SET status = 'cancelled', decided_at = COALESCE(decided_at, ?)
                           WHERE leave_id = ? AND status IN {marks}""", (now_str(), leave_id, *params))
    return cur.rowcount == 1


def insert_correction(conn, c: dict) -> int:
    cur = conn.execute("""INSERT INTO attendance_corrections(employee_id, shift_date, punch_time, punch_kind, reason,
                          status, requested_by_user_id, requested_at) VALUES (?,?,?,?,?, 'pending', ?,?)""",
                       (c["employee_id"], c["shift_date"], c["punch_time"], c["punch_kind"], c["reason"],
                        c["requested_by_user_id"], now_str()))
    return cur.lastrowid


def get_correction(conn, correction_id: int) -> dict | None:
    r = conn.execute("""SELECT c.*, e.employee_code, e.full_name, e.full_name_ar, e.badge_id, e.department_id
                        FROM attendance_corrections c JOIN employees e ON e.employee_id = c.employee_id
                        WHERE c.correction_id = ?""", (correction_id,)).fetchone()
    return dict(r) if r else None


def pending_correction_for(conn, employee_id: int, shift_date: str, kind: str) -> dict | None:
    r = conn.execute("""SELECT * FROM attendance_corrections WHERE employee_id = ? AND shift_date = ?
                        AND punch_kind = ? AND status = 'pending'""", (employee_id, shift_date, kind)).fetchone()
    return dict(r) if r else None


def decide_correction(conn, correction_id: int, status: str, user_id: int, note: str | None,
                      punch_id: int | None = None) -> bool:
    cur = conn.execute("""UPDATE attendance_corrections SET status = ?, decided_by_user_id = ?, decided_at = ?,
                          decision_note = ?, punch_id = ? WHERE correction_id = ? AND status = 'pending'""",
                       (status, user_id, now_str(), note, punch_id, correction_id))
    return cur.rowcount == 1


def cancel_correction(conn, correction_id: int) -> bool:
    cur = conn.execute("""UPDATE attendance_corrections SET status = 'cancelled', decided_at = ?
                          WHERE correction_id = ? AND status = 'pending'""", (now_str(), correction_id))
    return cur.rowcount == 1


def punches_near(conn, employee_id: int, ts: str, minutes: int) -> list[dict]:
    from datetime import datetime, timedelta
    t = datetime.fromisoformat(ts)
    lo, hi = (t - timedelta(minutes=minutes)).isoformat(sep=" "), (t + timedelta(minutes=minutes)).isoformat(sep=" ")
    return rows_to_dicts(conn.execute(
        """SELECT punch_id, punch_time_local, device_id FROM raw_punches WHERE employee_id = ?
           AND punch_time_local BETWEEN ? AND ?""", (employee_id, lo, hi)))


def _approver_clause(user: UserContext, emp_alias: str = "e") -> tuple[str, list]:
    """Rows this user may decide: their scope minus their own requests (nobody approves themselves)."""
    clause, params = scope_clause(user, emp_alias)
    if user.role == "employee":
        return "1=0", []
    if user.employee_id is not None:
        clause = f"({clause}) AND {emp_alias}.employee_id <> ?"
        params = [*params, user.employee_id]
    if not user.is_gm:     # requests from HR staff and the General Manager go to the General Manager
        clause += (f" AND NOT EXISTS (SELECT 1 FROM users ux WHERE ux.employee_id = {emp_alias}.employee_id"
                   " AND ux.role IN ('hr', 'gm'))")
    return clause, params


def list_leave_requests(conn, user: UserContext, *, statuses: tuple[str, ...] | None = None,
                        employee_id: int | None = None, for_approval: bool = False, limit: int = 200) -> list[dict]:
    clause, params = _approver_clause(user) if for_approval else scope_clause(user, "e")
    sql = f"""SELECT l.*, e.employee_code, e.full_name, e.full_name_ar, d.name AS department_name,
                     d.name_ar AS department_name_ar,
                     u.username AS decided_by, r.username AS requested_by,
                     ue.full_name AS decided_by_name, ue.full_name_ar AS decided_by_name_ar
              FROM leave_requests l JOIN employees e ON e.employee_id = l.employee_id
              JOIN departments d ON d.department_id = e.department_id
              LEFT JOIN users u ON u.user_id = l.approved_by_user_id
              LEFT JOIN employees ue ON ue.employee_id = u.employee_id
              LEFT JOIN users r ON r.user_id = l.requested_by_user_id
              WHERE {clause}"""
    if statuses:
        marks, extra = in_clause(statuses)
        sql += f" AND l.status IN {marks}"
        params = [*params, *extra]
    if employee_id:
        sql += " AND l.employee_id = ?"
        params = [*params, employee_id]
    order = "l.requested_at, l.start_date" if statuses == ("pending",) else "COALESCE(l.decided_at, l.requested_at) DESC, l.start_date DESC"
    rows = rows_to_dicts(conn.execute(sql + f" ORDER BY {order} LIMIT ?", [*params, limit]))
    for r in rows:   # computed here, not in SQL, to keep the statement portable
        r["calendar_days"] = (date.fromisoformat(r["end_date"]) - date.fromisoformat(r["start_date"])).days + 1
    return rows


def list_corrections(conn, user: UserContext, *, statuses: tuple[str, ...] | None = None,
                     employee_id: int | None = None, for_approval: bool = False, limit: int = 200,
                     start: str | None = None, end: str | None = None) -> list[dict]:
    clause, params = _approver_clause(user) if for_approval else scope_clause(user, "e")
    sql = f"""SELECT c.*, e.employee_code, e.full_name, e.full_name_ar, d.name AS department_name,
                     d.name_ar AS department_name_ar, u.username AS decided_by,
                     ue.full_name AS decided_by_name, ue.full_name_ar AS decided_by_name_ar,
                     a.status AS day_status, a.first_punch, a.last_punch, a.punch_count
              FROM attendance_corrections c JOIN employees e ON e.employee_id = c.employee_id
              JOIN departments d ON d.department_id = e.department_id
              LEFT JOIN users u ON u.user_id = c.decided_by_user_id
              LEFT JOIN employees ue ON ue.employee_id = u.employee_id
              LEFT JOIN attendance_daily a ON a.employee_id = c.employee_id AND a.shift_date = c.shift_date
              WHERE {clause}"""
    if statuses:
        marks, extra = in_clause(statuses)
        sql += f" AND c.status IN {marks}"
        params = [*params, *extra]
    if employee_id:
        sql += " AND c.employee_id = ?"
        params = [*params, employee_id]
    if start and end:
        sql += " AND c.shift_date BETWEEN ? AND ?"
        params = [*params, start, end]
    order = "c.requested_at" if statuses == ("pending",) else "COALESCE(c.decided_at, c.requested_at) DESC"
    return rows_to_dicts(conn.execute(sql + f" ORDER BY {order} LIMIT ?", [*params, limit]))


def pending_counts(conn, user: UserContext) -> dict:
    """Sidebar badges: requests waiting for this user's decision, and the user's own open requests."""
    out = {"to_decide": 0, "mine": 0}
    if user.has_team:
        clause, params = _approver_clause(user)
        out["to_decide"] = conn.execute(
            f"""SELECT (SELECT COUNT(*) FROM leave_requests l JOIN employees e ON e.employee_id = l.employee_id
                        WHERE l.status = 'pending' AND {clause})
                     + (SELECT COUNT(*) FROM attendance_corrections c JOIN employees e ON e.employee_id = c.employee_id
                        WHERE c.status = 'pending' AND {clause})""", [*params, *params]).fetchone()[0]
    if user.employee_id is not None:
        out["mine"] = conn.execute(
            """SELECT (SELECT COUNT(*) FROM leave_requests WHERE employee_id = ? AND status = 'pending')
                    + (SELECT COUNT(*) FROM attendance_corrections WHERE employee_id = ? AND status = 'pending')""",
            (user.employee_id, user.employee_id)).fetchone()[0]
    return out


# ======================================================= v2: user admin ==

def list_users(conn, q: str | None = None, role: str | None = None, limit: int = 500) -> list[dict]:
    sql = """SELECT u.user_id, u.username, u.role, u.employee_id, u.is_active, u.last_login_at, u.created_at,
                    u.must_change_password, e.employee_code, e.full_name, e.full_name_ar, e.gender, e.termination_date,
                    d.name AS department_name, d.name_ar AS department_name_ar
             FROM users u LEFT JOIN employees e ON e.employee_id = u.employee_id
             LEFT JOIN departments d ON d.department_id = e.department_id WHERE 1=1"""
    params: list = []
    if q:
        sql += " AND (u.username LIKE ? OR e.full_name LIKE ? OR e.full_name_ar LIKE ? OR e.employee_code LIKE ?)"
        params += [f"%{q}%"] * 4
    if role:
        sql += " AND u.role = ?"
        params.append(role)
    return rows_to_dicts(conn.execute(sql + " ORDER BY u.is_active DESC, u.username LIMIT ?", [*params, limit]))


def set_user_active(conn, user_id: int, active: bool) -> None:
    conn.execute("UPDATE users SET is_active = ? WHERE user_id = ?", (1 if active else 0, user_id))


def set_user_password(conn, user_id: int, password_hash: str, must_change: bool) -> None:
    conn.execute("UPDATE users SET password_hash = ?, must_change_password = ? WHERE user_id = ?",
                 (password_hash, 1 if must_change else 0, user_id))


def set_user_role(conn, user_id: int, role: str) -> None:
    conn.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))


def employees_without_account(conn, limit: int = 2000) -> list[dict]:
    return rows_to_dicts(conn.execute(
        """SELECT e.employee_id, e.employee_code, e.full_name, e.full_name_ar FROM employees e
           LEFT JOIN users u ON u.employee_id = e.employee_id
           WHERE u.user_id IS NULL AND e.termination_date IS NULL ORDER BY e.employee_code LIMIT ?""", (limit,)))


def latest_punch_time(conn) -> str | None:
    return conn.execute("SELECT MAX(punch_time_local) FROM raw_punches").fetchone()[0]


def latest_present_date(conn) -> str | None:
    return conn.execute("SELECT MAX(shift_date) FROM attendance_daily WHERE status = 'present'").fetchone()[0]


def manages_a_department(conn, employee_id: int) -> bool:
    return conn.execute("SELECT 1 FROM departments WHERE manager_employee_id = ?", (employee_id,)).fetchone() is not None


def punch_id_in_batch(conn, batch_id: int) -> int:
    return conn.execute("SELECT MIN(punch_id) FROM raw_punches WHERE batch_id = ?", (batch_id,)).fetchone()[0]


def employee_identifiers(conn) -> tuple[set[str], set[str], set[str]]:
    """(employee codes upper-cased, badge ids, emails) already in use: for bulk-import validation."""
    rows = conn.execute("SELECT employee_code, badge_id, email FROM employees").fetchall()
    return ({r["employee_code"].upper() for r in rows}, {r["badge_id"] for r in rows},
            {r["email"] for r in rows if r["email"]})


# ================================================ v2: generated files ==
# Copies of generated files (model evaluation, PDF reports), so hosts whose disk
# is wiped on restart can still serve them. Disk stays the first place to look.

def save_file(conn, path: str, content: bytes, content_type: str) -> None:
    conn.execute("""INSERT INTO stored_files(path, content, content_type, updated_at) VALUES (?,?,?,?)
                    ON CONFLICT (path) DO UPDATE SET content = excluded.content,
                    content_type = excluded.content_type, updated_at = excluded.updated_at""",
                 (path, content, content_type, now_str()))


def load_file(conn, path: str) -> bytes | None:
    r = conn.execute("SELECT content FROM stored_files WHERE path = ?", (path,)).fetchone()
    return bytes(r[0]) if r else None


def stored_paths(conn, prefix: str) -> set[str]:
    return {r[0] for r in conn.execute("SELECT path FROM stored_files WHERE path LIKE ?", (prefix + "%",))}



def user_profile(conn, user_id: int) -> dict | None:
    """What the sidebar card shows: name (both languages), gender, job title, department."""
    r = conn.execute("""SELECT u.username, u.role, e.employee_id, e.full_name, e.full_name_ar, e.gender, e.job_title,
                               e.job_title_ar, d.name AS department_name, d.name_ar AS department_name_ar
                        FROM users u LEFT JOIN employees e ON e.employee_id = u.employee_id
                        LEFT JOIN departments d ON d.department_id = e.department_id
                        WHERE u.user_id = ?""", (user_id,)).fetchone()
    return dict(r) if r else None


def user_role_of_employee(conn, employee_id: int) -> str | None:
    r = conn.execute("SELECT role FROM users WHERE employee_id = ?", (employee_id,)).fetchone()
    return r[0] if r else None
