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
from ...i18n import N_, _
from ...labels import punch_kind_label
from ...security.scope import AccessDenied, can_approve
from ...services import requests as rq
from .. import get_db
from ..helpers import audit, flash_errors, login_required, roles_required

bp = Blueprint("requests", __name__)

MAX_NOTE = 300
AUTO_NOTE = N_("Approved automatically: this is the General Manager's own request.")


def NOT_YOURS() -> str:  # noqa: N802 - reads like a constant at the call sites
    return _("You can only decide requests from people you are responsible for, and never your own.")


def _now() -> datetime:
    return datetime.now(ZoneInfo(g.settings.ORG_TIMEZONE)).replace(tzinfo=None)


def _own_employee() -> dict:
    if g.user.employee_id is None:
        raise AccessDenied(_("This account is not linked to an employee record, so it cannot send requests."))
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
                if g.user.is_gm:
                    # nobody sits above the General Manager, so their own leave is approved on the spot
                    with transaction(conn):
                        repos.decide_leave(conn, lid, "approved", g.user.user_id, AUTO_NOTE)
                        audit("leave_approve", "leave_request", lid, {"employee_id": emp["employee_id"],
                                                                      "note": AUTO_NOTE, "automatic": True})
                    rq.reprocess_range(conn, g.settings, v.data["start_date"], v.data["end_date"],
                                       [emp["employee_id"]], g.user.user_id, today)
                    flash(_("Leave from {start} to {end} is recorded and approved.", start=v.data["start_date"],
                            end=v.data["end_date"]), "success")
                else:
                    flash(_("Leave request sent for {start} to {end}. Your manager or HR will decide it.",
                            start=v.data["start_date"], end=v.data["end_date"]), "success")
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
                if g.user.is_gm:
                    try:
                        rq.approve_correction(conn, repos.get_correction(conn, cid), g.settings, g.user.user_id,
                                              AUTO_NOTE)
                        rq.reprocess_range(conn, g.settings, v.data["shift_date"], v.data["shift_date"],
                                           [emp["employee_id"]], g.user.user_id, today)
                        flash(_("The missed punch ({kind}) at {time} has been added to your record.",
                                kind=punch_kind_label(v.data["punch_kind"]), time=v.data["punch_time"][:16]),
                              "success")
                    except ValueError as exc:
                        flash(str(exc), "error")
                else:
                    flash(_("Missed punch ({kind}) at {time} reported for the shift of {date}. It will count once "
                            "it is approved.", kind=punch_kind_label(v.data["punch_kind"]),
                            time=v.data["punch_time"][:16], date=v.data["shift_date"]), "success")
                return redirect(url_for("requests.mine"))
            flash_errors(v.errors)
            return _render_mine(emp, corr_form=request.form, tab="correction"), 422
        if action == "cancel_leave":
            lv = repos.get_leave(conn, _int_form("leave_id"))
            if lv is None or lv["employee_id"] != emp["employee_id"]:
                abort(404)
            if not rq.leave_cancellable_by_employee(lv, today):
                flash(_("Only leave that is waiting for a decision, or approved leave that has not started yet, "
                        "can be cancelled here. Please ask HR for anything else."), "error")
            else:
                was = lv["status"]
                with transaction(conn):
                    ok = repos.cancel_leave(conn, lv["leave_id"], ("pending", "approved"))
                    if ok:
                        audit("leave_cancel", "leave_request", lv["leave_id"], {"was": was})
                if ok and was == "approved":
                    rq.reprocess_range(conn, g.settings, lv["start_date"], lv["end_date"], [emp["employee_id"]],
                                       g.user.user_id, today)
                flash(_("Leave request cancelled.") if ok else _("That request had already changed."),
                      "success" if ok else "error")
            return redirect(url_for("requests.mine"))
        if action == "cancel_correction":
            c = repos.get_correction(conn, _int_form("correction_id"))
            if c is None or c["employee_id"] != emp["employee_id"]:
                abort(404)
            with transaction(conn):
                ok = repos.cancel_correction(conn, c["correction_id"])
                if ok:
                    audit("correction_cancel", "attendance_correction", c["correction_id"])
            flash(_("Missed punch report withdrawn.") if ok else _("Only requests waiting for a decision can be withdrawn."),
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
        flash(_("Please add a short note when rejecting, so the employee knows why."), "error")
        return redirect(url_for("requests.approvals"))
    rid = _int_form("id")
    today = _now().date()

    if kind == "leave":
        lv = repos.get_leave(conn, rid)
        if lv is None:
            abort(404)
        if not can_approve(conn, g.user, lv["employee_id"]):
            raise AccessDenied(NOT_YOURS())
        if decision == "approve":
            clash = repos.overlapping_leave(conn, lv["employee_id"], lv["start_date"], lv["end_date"],
                                            exclude_id=lv["leave_id"])
            if clash and clash["status"] == "approved":
                flash(_("This cannot be approved because it overlaps approved leave from {start} to {end}.",
                        start=clash["start_date"], end=clash["end_date"]), "error")
                return redirect(url_for("requests.approvals"))
        status = "approved" if decision == "approve" else "rejected"
        with transaction(conn):
            ok = repos.decide_leave(conn, rid, status, g.user.user_id, note)
            if ok:
                audit(f"leave_{decision}", "leave_request", rid, {"employee_id": lv["employee_id"], "note": note,
                                                                   "start": lv["start_date"], "end": lv["end_date"]})
        if not ok:
            flash(_("That request has already been decided or withdrawn."), "error")
            return redirect(url_for("requests.approvals"))
        msg = rq.reprocess_range(conn, s, lv["start_date"], lv["end_date"], [lv["employee_id"]], g.user.user_id,
                                 today) if status == "approved" else None
        name = f"{lv['employee_code']}"
        done = (_("Leave for {who} approved.", who=name) if status == "approved"
                else _("Leave for {who} rejected.", who=name))
        flash(f"{done} {msg or ''}".strip(), "success")
        return redirect(url_for("requests.approvals"))

    c = repos.get_correction(conn, rid)
    if c is None:
        abort(404)
    if not can_approve(conn, g.user, c["employee_id"]):
        raise AccessDenied(NOT_YOURS())
    if decision == "approve":
        try:
            rq.approve_correction(conn, c, s, g.user.user_id, note)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("requests.approvals"))
        msg = rq.reprocess_range(conn, s, c["shift_date"], c["shift_date"], [c["employee_id"]], g.user.user_id, today)
        done = _("Approved for {who}: the {kind} at {time} has been added.", who=c["employee_code"],
                 kind=punch_kind_label(c["punch_kind"]), time=c["punch_time"][:16])
        flash(f"{done} {msg or ''}".strip(), "success")
    else:
        with transaction(conn):
            ok = repos.decide_correction(conn, rid, "rejected", g.user.user_id, note)
            if ok:
                audit("correction_reject", "attendance_correction", rid, {"employee_id": c["employee_id"], "note": note})
        flash(_("The missed punch report from {who} was rejected.", who=c["employee_code"]) if ok
              else _("That request has already been decided."), "success" if ok else "error")
    return redirect(url_for("requests.approvals"))
