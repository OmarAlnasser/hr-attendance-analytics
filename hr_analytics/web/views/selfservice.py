"""Self-service requests (leave, missed punches) and the approvals inbox.

Rules live in services/requests.py; authorisation in security/scope.py.
Every decision re-checks scope on the server, re-checks that the request is
still pending (so a double click or two approvers cannot decide twice), is
written to the audit log, and re-processes only the affected employee-days.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ...db import repos
from ...db.connection import transaction
from ...security.scope import AccessDenied, can_approve
from ...services import requests as rq
from .. import get_db
from ..helpers import audit, flash_errors, login_required, roles_required

bp = Blueprint("requests", __name__)

MAX_NOTE = 300


def _now() -> datetime:
    return datetime.now(ZoneInfo(g.settings.ORG_TIMEZONE)).replace(tzinfo=None)


def _own_employee() -> dict:
    if g.user.employee_id is None:
        raise AccessDenied("This account is not linked to an employee record, so it cannot file requests.")
    emp = repos.get_employee(get_db(), g.user.employee_id)
    if emp is None:
        abort(404)
    return emp


# ---------------------------------------------------------- my requests --

@bp.route("/requests", methods=["GET", "POST"])
@login_required
def mine():
    conn = get_db()
    emp = _own_employee()
    today = _now().date()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "new_leave":
            v = rq.validate_leave(conn, emp, request.form, today)
            if v.ok:
                with transaction(conn):
                    lid = repos.insert_leave_request(conn, emp["employee_id"], v.data["leave_type"],
                                                     v.data["start_date"], v.data["end_date"], v.data["reason"],
                                                     g.user.user_id)
                    audit("leave_request", "leave_request", lid, {k: v.data[k] for k in
                                                                  ("leave_type", "start_date", "end_date")})
                flash(f"Leave request sent for {v.data['start_date']} to {v.data['end_date']}. "
                      "Your manager or HR will decide it.", "success")
                return redirect(url_for("requests.mine"))
            flash_errors(v.errors)
            return _render_mine(emp, leave_form=request.form, tab="leave"), 422
        if action == "new_correction":
            v = rq.validate_correction(conn, g.settings, emp, request.form, _now())
            if v.ok:
                with transaction(conn):
                    cid = repos.insert_correction(conn, v.data | {"requested_by_user_id": g.user.user_id})
                    audit("correction_request", "attendance_correction", cid,
                          {k: v.data[k] for k in ("shift_date", "punch_time", "punch_kind")})
                flash(f"Missed clock-{v.data['punch_kind']} at {v.data['punch_time'][:16]} reported for the "
                      f"{v.data['shift_date']} shift. It counts once approved.", "success")
                return redirect(url_for("requests.mine"))
            flash_errors(v.errors)
            return _render_mine(emp, corr_form=request.form, tab="correction"), 422
        if action == "cancel_leave":
            lv = repos.get_leave(conn, _int_form("leave_id"))
            if lv is None or lv["employee_id"] != emp["employee_id"]:
                abort(404)
            if not rq.leave_cancellable_by_employee(lv, today):
                flash("Only pending leave, or approved leave that has not started, can be cancelled here. "
                      "Ask HR for anything else.", "error")
            else:
                was = lv["status"]
                with transaction(conn):
                    ok = repos.cancel_leave(conn, lv["leave_id"], ("pending", "approved"))
                    if ok:
                        audit("leave_cancel", "leave_request", lv["leave_id"], {"was": was})
                if ok and was == "approved":
                    rq.reprocess_range(conn, g.settings, lv["start_date"], lv["end_date"], [emp["employee_id"]],
                                       g.user.user_id, today)
                flash("Leave request cancelled." if ok else "That request had already changed.", "success" if ok else "error")
            return redirect(url_for("requests.mine"))
        if action == "cancel_correction":
            c = repos.get_correction(conn, _int_form("correction_id"))
            if c is None or c["employee_id"] != emp["employee_id"]:
                abort(404)
            with transaction(conn):
                ok = repos.cancel_correction(conn, c["correction_id"])
                if ok:
                    audit("correction_cancel", "attendance_correction", c["correction_id"])
            flash("Correction request withdrawn." if ok else "Only pending requests can be withdrawn.",
                  "success" if ok else "error")
            return redirect(url_for("requests.mine"))
        abort(400)
    # prefill from links such as "Report missed punch" on the employee page
    corr_form = {}
    if request.args.get("date"):
        kind = request.args.get("kind") if request.args.get("kind") in rq.PUNCH_KINDS else "in"
        corr_form = {"punch_kind": kind, "punch_time": (request.args.get("date") or "")[:10] + "T" +
                     (request.args.get("time") or "08:00")[:5]}
    return _render_mine(emp, corr_form=corr_form, tab="correction" if corr_form else "leave")


def _render_mine(emp, leave_form=None, corr_form=None, tab="leave"):
    conn = get_db()
    today = _now().date()
    leaves = repos.list_leave_requests(conn, g.user, employee_id=emp["employee_id"], limit=60)
    for lv in leaves:
        lv["can_cancel"] = rq.leave_cancellable_by_employee(lv, today)
    return render_template("requests_mine.html", emp=emp, leaves=leaves,
                           corrections=repos.list_corrections(conn, g.user, employee_id=emp["employee_id"], limit=60),
                           leave_form=leave_form or {}, corr_form=corr_form or {}, tab=tab,
                           leave_types=rq.LEAVE_TYPES, today=today.isoformat(),
                           max_leave=rq.MAX_LEAVE_DAYS, corr_days=rq.CORRECTION_BACKDATE_DAYS)


def _int_form(name: str) -> int:
    try:
        return int(request.form.get(name, ""))
    except ValueError:
        abort(400)


# ------------------------------------------------------------ approvals --

@bp.route("/approvals")
@roles_required("hr", "manager")
def approvals():
    conn = get_db()
    return render_template(
        "approvals.html", today=_now().date().isoformat(),
        leaves=repos.list_leave_requests(conn, g.user, statuses=("pending",), for_approval=True),
        corrections=repos.list_corrections(conn, g.user, statuses=("pending",), for_approval=True),
        recent_leaves=repos.list_leave_requests(conn, g.user, statuses=("approved", "rejected", "cancelled"),
                                                for_approval=True, limit=15),
        recent_corrections=repos.list_corrections(conn, g.user, statuses=("approved", "rejected", "cancelled"),
                                                  for_approval=True, limit=15))


@bp.route("/approvals/decide", methods=["POST"])
@roles_required("hr", "manager")
def decide():
    conn, s = get_db(), g.settings
    kind = request.form.get("kind")
    decision = request.form.get("decision")
    note = (request.form.get("note") or "").strip()[:MAX_NOTE] or None
    if kind not in ("leave", "correction") or decision not in ("approve", "reject"):
        abort(400)
    if decision == "reject" and not note:
        flash("Add a short note when rejecting, so the employee knows why.", "error")
        return redirect(url_for("requests.approvals"))
    rid = _int_form("id")
    today = _now().date()

    if kind == "leave":
        lv = repos.get_leave(conn, rid)
        if lv is None:
            abort(404)
        if not can_approve(conn, g.user, lv["employee_id"]):
            raise AccessDenied("You can only decide requests from employees you manage, and never your own.")
        if decision == "approve":
            clash = repos.overlapping_leave(conn, lv["employee_id"], lv["start_date"], lv["end_date"],
                                            exclude_id=lv["leave_id"])
            if clash and clash["status"] == "approved":
                flash(f"Cannot approve: overlaps approved leave {clash['start_date']} to {clash['end_date']}.", "error")
                return redirect(url_for("requests.approvals"))
        status = "approved" if decision == "approve" else "rejected"
        with transaction(conn):
            ok = repos.decide_leave(conn, rid, status, g.user.user_id, note)
            if ok:
                audit(f"leave_{decision}", "leave_request", rid, {"employee_id": lv["employee_id"], "note": note,
                                                                   "start": lv["start_date"], "end": lv["end_date"]})
        if not ok:
            flash("That request was already decided or withdrawn.", "error")
            return redirect(url_for("requests.approvals"))
        msg = rq.reprocess_range(conn, s, lv["start_date"], lv["end_date"], [lv["employee_id"]], g.user.user_id,
                                 today) if status == "approved" else None
        flash(f"Leave for {lv['employee_code']} {status}. {msg or ''}".strip(), "success")
        return redirect(url_for("requests.approvals"))

    c = repos.get_correction(conn, rid)
    if c is None:
        abort(404)
    if not can_approve(conn, g.user, c["employee_id"]):
        raise AccessDenied("You can only decide requests from employees you manage, and never your own.")
    if decision == "approve":
        try:
            rq.approve_correction(conn, c, s, g.user.user_id, note)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("requests.approvals"))
        msg = rq.reprocess_range(conn, s, c["shift_date"], c["shift_date"], [c["employee_id"]], g.user.user_id, today)
        flash(f"Correction for {c['employee_code']} approved: clock-{c['punch_kind']} {c['punch_time'][:16]} added. "
              f"{msg or ''}".strip(), "success")
    else:
        with transaction(conn):
            ok = repos.decide_correction(conn, rid, "rejected", g.user.user_id, note)
            if ok:
                audit("correction_reject", "attendance_correction", rid, {"employee_id": c["employee_id"], "note": note})
        flash(f"Correction for {c['employee_code']} rejected." if ok else "That request was already decided.",
              "success" if ok else "error")
    return redirect(url_for("requests.approvals"))
