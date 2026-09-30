"""HR tools: login accounts and bulk employee onboarding (HR only).

Accounts
* create an account for an employee; the role follows the org chart (manager
  if the employee manages a department, otherwise employee) unless HR is granted
* disable / re-enable (takes effect on the user's next request), with a one-click
  clean-up for accounts of employees who have left
* reset password: a random temporary password is shown ONCE on the response
  page (never flashed, never stored in plain text, never in the session cookie)
  and the user must replace it at the next sign-in
* HR cannot disable, demote or reset their own account here (use Password)

Bulk import
* CSV with a header row; validate everything first, then insert all rows in one
  transaction or none ("Check only" runs the validation without saving)
"""
from __future__ import annotations

import io
import re
import secrets
from datetime import date

import pandas as pd
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for
from werkzeug.security import generate_password_hash

from ...db import repos
from ...db.connection import IntegrityError, transaction
from ...services.requests import reprocess_range
from .. import get_db
from ..helpers import audit, int_arg, roles_required

bp = Blueprint("users", __name__)

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,40}$")
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# no look-alike characters (0/O, 1/l/I) so a temporary password can be read out or typed
_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
IMPORT_COLUMNS = ["employee_code", "badge_id", "full_name", "email", "job_title", "department_code", "shift_code",
                  "hire_date"]
MAX_IMPORT_ROWS = 2000


def temp_password(n: int = 14) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def _hash(pw: str) -> str:
    return generate_password_hash(pw, method=current_app.extensions["hr_settings"].PASSWORD_HASH_METHOD)


def _derived_role(conn, employee_id: int | None) -> str:
    if employee_id is None:
        return "employee"
    return "manager" if repos.manages_a_department(conn, employee_id) else "employee"


def _target(user_id: int) -> dict:
    u = repos.get_user(get_db(), user_id)
    if u is None:
        abort(404)
    if u["user_id"] == g.user.user_id:
        flash("You cannot change your own account here. Use Password to change your password.", "error")
        return None
    if g.settings.is_protected_demo_account(u["username"]):
        flash(f"{u['username']} is one of the public demo accounts, so it cannot be disabled, reset or "
              "changed. Try it on any other account.", "info")
        return None
    return u


# ---------------------------------------------------------------- accounts --

@bp.route("/users")
@roles_required("hr")
def index(issued: list[dict] | None = None):
    conn = get_db()
    q = (request.args.get("q") or "").strip()[:60]
    role = request.args.get("role") if request.args.get("role") in ("hr", "manager", "employee") else None
    rows = repos.list_users(conn, q or None, role)
    leavers = [r for r in rows if r["is_active"] and r["termination_date"]
               and r["termination_date"] < date.today().isoformat()]
    return render_template("users.html", rows=rows, q=q, role=role, leavers=len(leavers), issued=issued or [],
                           now_date=date.today().isoformat(),
                           candidates=repos.employees_without_account(conn))


@bp.route("/users/create", methods=["POST"])
@roles_required("hr")
def create():
    conn = get_db()
    emp_id = int_arg("employee_id")
    emp = repos.get_employee(conn, emp_id) if emp_id else None
    if emp is None:
        flash("Choose an employee.", "error")
        return redirect(url_for("users.index"))
    username = (request.form.get("username") or emp["employee_code"]).strip().lower()
    if not USERNAME_RE.match(username):
        flash("Username: 3-40 lower-case letters, digits, '.', '_' or '-'.", "error")
        return redirect(url_for("users.index"))
    role = "hr" if request.form.get("grant_hr") else _derived_role(conn, emp_id)
    pw = temp_password()
    h = _hash(pw)
    try:
        with transaction(conn):
            uid = repos.create_user(conn, username, h, role, emp_id)
            repos.set_user_password(conn, uid, h, must_change=True)
            audit("user_create", "user", uid, {"username": username, "role": role, "employee_id": emp_id})
    except IntegrityError:
        flash("That username is taken, or this employee already has an account.", "error")
        return redirect(url_for("users.index"))
    return index(issued=[{"username": username, "name": emp["full_name"], "password": pw, "what": "new account"}])


@bp.route("/users/<int:user_id>/<action>", methods=["POST"])
@roles_required("hr")
def act(user_id: int, action: str):
    if action not in ("disable", "enable", "reset", "grant_hr", "revoke_hr"):
        abort(404)
    conn = get_db()
    u = _target(user_id)
    if u is None:
        return redirect(url_for("users.index"))
    if action in ("disable", "enable"):
        with transaction(conn):
            repos.set_user_active(conn, user_id, action == "enable")
            audit(f"user_{action}", "user", user_id, {"username": u["username"]})
        flash(f"Account {u['username']} {action}d.", "success")
        return redirect(url_for("users.index", q=request.args.get("q")))
    if action == "reset":
        pw = temp_password()
        with transaction(conn):
            repos.set_user_password(conn, user_id, _hash(pw), must_change=True)
            audit("password_reset", "user", user_id, {"username": u["username"]})
        emp = repos.get_employee(conn, u["employee_id"]) if u["employee_id"] else None
        return index(issued=[{"username": u["username"], "name": emp["full_name"] if emp else "",
                              "password": pw, "what": "password reset"}])
    new_role = "hr" if action == "grant_hr" else _derived_role(conn, u["employee_id"])
    with transaction(conn):
        repos.set_user_role(conn, user_id, new_role)
        audit("role_change", "user", user_id, {"from": u["role"], "to": new_role})
    flash(f"{u['username']} is now {new_role}.", "success")
    return redirect(url_for("users.index"))


@bp.route("/users/disable-leavers", methods=["POST"])
@roles_required("hr")
def disable_leavers():
    conn = get_db()
    today = date.today().isoformat()
    ids = [r["user_id"] for r in repos.list_users(conn)
           if r["is_active"] and r["termination_date"] and r["termination_date"] < today
           and r["user_id"] != g.user.user_id and not g.settings.is_protected_demo_account(r["username"])]
    with transaction(conn):
        for uid in ids:
            repos.set_user_active(conn, uid, False)
        audit("user_disable_leavers", "user", None, {"count": len(ids), "user_ids": ids})
    flash(f"Disabled {len(ids)} account(s) of employees who have left.", "success")
    return redirect(url_for("users.index"))


# ------------------------------------------------------------- bulk import --

def validate_employee_rows(conn, df: pd.DataFrame) -> tuple[list[dict], list[str]]:
    """Return (clean rows, errors). Row numbers in errors are spreadsheet rows (header = row 1)."""
    errors: list[str] = []
    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in IMPORT_COLUMNS if c not in df.columns and c not in ("email", "job_title")]
    if missing:
        return [], [f"Missing column(s): {', '.join(missing)}. Download the template for the expected header."]
    if len(df) == 0:
        return [], ["The file has no data rows."]
    if len(df) > MAX_IMPORT_ROWS:
        return [], [f"At most {MAX_IMPORT_ROWS} rows per file."]
    depts = {d["code"].upper(): d for d in repos.list_departments(conn)}
    shifts = {s["code"].upper(): s for s in repos.list_shifts(conn)}
    existing, badges, emails = repos.employee_identifiers(conn)
    seen_codes, seen_badges, seen_emails = set(), set(), set()
    clean = []
    df = df.astype(object).where(df.notna(), None)
    for i, r in enumerate(df.to_dict("records"), start=2):
        def val(k):
            v = r.get(k)
            return str(v).strip() if v is not None else ""
        row_err = []
        code, badge, name = val("employee_code").upper(), val("badge_id"), val("full_name")
        email = val("email").lower() or None
        if not CODE_RE.match(code):
            row_err.append("employee_code must be 1-20 letters, digits, '-' or '_'")
        elif code in existing:
            row_err.append(f"employee_code {code} already exists (edit that employee instead)")
        elif code in seen_codes:
            row_err.append(f"employee_code {code} appears twice in the file")
        if not CODE_RE.match(badge):
            row_err.append("badge_id must be 1-20 letters, digits, '-' or '_'")
        elif badge in badges or badge in seen_badges:
            row_err.append(f"badge_id {badge} is already used")
        if not 2 <= len(name) <= 120:
            row_err.append("full_name must be 2-120 characters")
        if email and not EMAIL_RE.match(email):
            row_err.append("email is not valid")
        elif email and (email in emails or email in seen_emails):
            row_err.append(f"email {email} is already used")
        dept = depts.get(val("department_code").upper())
        if dept is None:
            row_err.append(f"unknown department_code '{val('department_code')}'")
        shift = shifts.get(val("shift_code").upper())
        if shift is None:
            row_err.append(f"unknown shift_code '{val('shift_code')}'")
        hire = val("hire_date")[:10]
        try:
            date.fromisoformat(hire)
        except ValueError:
            row_err.append("hire_date must be YYYY-MM-DD")
        if row_err:
            errors.append(f"Row {i}: " + "; ".join(row_err) + ".")
            continue
        seen_codes.add(code)
        seen_badges.add(badge)
        if email:
            seen_emails.add(email)
        clean.append({"employee_code": code, "badge_id": badge, "full_name": name, "email": email,
                      "job_title": val("job_title") or None, "department_id": dept["department_id"],
                      "manager_employee_id": dept["manager_employee_id"], "hire_date": hire,
                      "termination_date": None, "shift_id": shift["shift_id"], "department": dept["name"],
                      "shift": shift["code"]})
    return clean, errors


@bp.route("/employees/import", methods=["GET", "POST"])
@roles_required("hr")
def bulk_import():
    if request.method == "GET":
        return render_template("employee_import.html", columns=IMPORT_COLUMNS, rows=None, errors=[], issued=[])
    conn = get_db()
    f = request.files.get("file")
    if f is None or not f.filename:
        flash("Choose a CSV file.", "error")
        return redirect(url_for("users.bulk_import"))
    try:
        df = pd.read_csv(io.BytesIO(f.read()), dtype=str, encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001 - any parse error is shown to HR
        flash(f"Could not read the CSV: {exc}", "error")
        return redirect(url_for("users.bulk_import"))
    rows, errors = validate_employee_rows(conn, df)
    commit = request.form.get("mode") == "import"
    if errors or not commit:
        return render_template("employee_import.html", columns=IMPORT_COLUMNS, rows=rows, errors=errors,
                               issued=[], checked=True, filename=f.filename), (422 if errors else 200)
    make_accounts = bool(request.form.get("create_accounts"))
    issued = []
    try:
        with transaction(conn):
            for r in rows:
                eid = repos.save_employee(conn, r)
                r["employee_id"] = eid
                repos.set_shift_assignment(conn, eid, r["shift_id"], r["hire_date"])
                if make_accounts:
                    pw = temp_password()
                    h = _hash(pw)
                    uid = repos.create_user(conn, r["employee_code"].lower(), h, "employee", eid)
                    repos.set_user_password(conn, uid, h, must_change=True)
                    issued.append({"username": r["employee_code"].lower(), "name": r["full_name"], "password": pw,
                                   "what": "new account"})
            audit("employee_bulk_import", "employee", None, {"file": f.filename, "rows": len(rows),
                                                              "accounts": len(issued)})
    except IntegrityError as exc:
        flash(f"Nothing was imported: a value clashed with an existing record ({exc}). "
              "If you ticked 'create accounts', a username may already be taken.", "error")
        return redirect(url_for("users.bulk_import"))
    msg = reprocess_range(conn, g.settings, min(r["hire_date"] for r in rows), date.today(),
                          [r["employee_id"] for r in rows], g.user.user_id)
    flash(f"Imported {len(rows)} employee(s){' with login accounts' if issued else ''}. {msg or ''}".strip(), "success")
    return render_template("employee_import.html", columns=IMPORT_COLUMNS, rows=rows, errors=[], issued=issued,
                           done=True, filename=f.filename)


@bp.route("/employees/import/template.csv")
@roles_required("hr")
def import_template():
    conn = get_db()
    d = (repos.list_departments(conn) or [{"code": "OPS"}])[0]["code"]
    s = (repos.list_shifts(conn) or [{"code": "DAY"}])[0]["code"]
    sample = pd.DataFrame([["E9001", "B9001", "New Starter", "new.starter@example.com", "Analyst", d, s,
                            date.today().isoformat()]], columns=IMPORT_COLUMNS)
    buf = io.BytesIO(sample.to_csv(index=False).encode("utf-8-sig"))
    return send_file(buf, mimetype="text/csv", as_attachment=True, download_name="employees_template.csv")
