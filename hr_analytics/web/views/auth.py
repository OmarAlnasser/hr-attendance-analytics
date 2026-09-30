"""Login, logout and password change."""
from __future__ import annotations

import secrets
import threading
import time

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from ...db import repos
from ...db.connection import transaction
from .. import get_db
from ..helpers import audit, login_required, safe_next

bp = Blueprint("auth", __name__)

# Simple in-process throttle: 5 failures per username+IP in 10 minutes.
# A multi-process deployment needs a shared store (see docs/production_migration.md).
MAX_FAILURES, WINDOW_SECONDS = 5, 600
_failures: dict[tuple[str, str], list[float]] = {}
_lock = threading.Lock()
_DUMMY_HASH: dict[str, str] = {}


def _recent_failures(key) -> int:
    now = time.time()
    with _lock:
        lst = [t for t in _failures.get(key, []) if now - t < WINDOW_SECONDS]
        _failures[key] = lst
        return len(lst)


def _record_failure(key) -> None:
    with _lock:
        _failures.setdefault(key, []).append(time.time())


def _dummy_hash() -> str:
    method = current_app.extensions["hr_settings"].PASSWORD_HASH_METHOD
    if method not in _DUMMY_HASH:
        _DUMMY_HASH[method] = generate_password_hash(secrets.token_hex(8), method=method)
    return _DUMMY_HASH[method]


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user is not None:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        key = (username, request.remote_addr or "")
        if _recent_failures(key) >= MAX_FAILURES:
            flash("Too many failed attempts. Wait a few minutes and try again.", "error")
            return render_template("login.html", username=username, demo=_demo_accounts(get_db())), 429
        conn = get_db()
        user = repos.get_user_by_username(conn, username) if username else None
        # Always run one hash check so response time does not reveal valid usernames.
        ok = check_password_hash(user["password_hash"] if user else _dummy_hash(), password)
        if user and ok and user["is_active"]:
            nxt = safe_next(request.args.get("next"))
            session.clear()                      # new session on login (fixation)
            session.permanent = True
            session["uid"] = user["user_id"]
            session["csrf"] = secrets.token_urlsafe(32)
            with transaction(conn):
                repos.touch_login(conn, user["user_id"])
                repos.audit(conn, user["user_id"], "login", "user", user["user_id"], None, request.remote_addr)
            return redirect(nxt or url_for("dashboard.index"))
        _record_failure(key)
        with transaction(conn):
            repos.audit(conn, None, "login_failed", "user", None, {"username": username[:64]}, request.remote_addr)
        flash("Username or password is incorrect.", "error")
        return render_template("login.html", username=username, demo=_demo_accounts(conn)), 401
    return render_template("login.html", username="", demo=_demo_accounts(get_db()))


def _demo_accounts(conn) -> list[dict]:
    """The one-click showcase accounts that exist, are active and belong to synthetic employees."""
    s = current_app.extensions["hr_settings"]
    labels = {"hr": "HR officer", "manager": "Department manager", "employee": "Employee"}
    blurbs = {"hr": "Whole organisation: Today board, approvals, imports, users, reports.",
              "manager": "Own department only: approve leave and punch corrections, evaluate the team.",
              "employee": "Own record: request leave, report a missed punch, see your month."}
    out = []
    for name in s.demo_usernames:
        u = repos.get_user_by_username(conn, name)
        emp = repos.get_employee(conn, u["employee_id"]) if u and u["employee_id"] else None
        if u and u["is_active"] and emp and emp["is_synthetic"]:
            out.append({"username": name, "role": u["role"], "label": labels[u["role"]], "blurb": blurbs[u["role"]],
                        "name": emp["full_name"], "department": emp["department_name"]})
    return out


@bp.route("/demo-login", methods=["POST"])
def demo_login():
    s = current_app.extensions["hr_settings"]
    if not s.DEMO_MODE:
        abort(404)
    conn = get_db()
    wanted = (request.form.get("username") or "").strip().lower()
    acct = next((a for a in _demo_accounts(conn) if a["username"] == wanted), None)
    if acct is None:
        abort(404)
    user = repos.get_user_by_username(conn, wanted)
    session.clear()
    session.permanent = True
    session["uid"] = user["user_id"]
    session["csrf"] = secrets.token_urlsafe(32)
    with transaction(conn):
        repos.touch_login(conn, user["user_id"])
        repos.audit(conn, user["user_id"], "demo_login", "user", user["user_id"], None, request.remote_addr)
    return redirect(url_for("dashboard.index"))


@bp.route("/logout", methods=["POST"])
def logout():
    if g.user is not None:
        with transaction(get_db()):
            audit("logout", "user", g.user.user_id)
    session.clear()
    flash("You have signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST" and current_app.extensions["hr_settings"].is_protected_demo_account(g.user.username):
        flash("This is a shared demo account, so its password cannot be changed.", "info")
        return redirect(url_for("auth.account"))
    if request.method == "POST":
        conn = get_db()
        user = repos.get_user(conn, g.user.user_id)
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        repeat = request.form.get("repeat_password") or ""
        errors = []
        if not check_password_hash(user["password_hash"], current):
            errors.append("Current password is incorrect.")
        if len(new) < 12:
            errors.append("New password must be at least 12 characters.")
        if new != repeat:
            errors.append("The two new passwords do not match.")
        if new and new == current:
            errors.append("Choose a password different from the current one.")
        if errors:
            for e in errors:
                flash(e, "error")
        else:
            method = current_app.extensions["hr_settings"].PASSWORD_HASH_METHOD
            with transaction(conn):
                repos.update_password(conn, g.user.user_id, generate_password_hash(new, method=method))
                audit("password_change", "user", g.user.user_id)
            flash("Password changed.", "success")
            return redirect(url_for("auth.account"))
    return render_template("account.html")
