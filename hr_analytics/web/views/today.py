"""Live 'Today' board: who is in, late, not in yet, expected later, or on leave.

Nothing is written. The same rules as nightly processing are evaluated in
memory for one shift date "as of" a moment:
* live mode (no parameters): today, now; the page refreshes itself every 60 s
  with a meta refresh (the app runs without JavaScript under a strict CSP)
* replay mode (?date=&time=): any past moment; punches after it are ignored,
  so HR can see exactly what the board showed at 09:30 last Tuesday

The board is only as current as the last punch import. The page says when the
latest punch arrived, so a stale feed is never mistaken for mass absence.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, g, render_template, request

from ...db import repos
from ...i18n import _, loc
from ...labels import leave_type_label
from ...pipeline.processor import compute_attendance
from .. import get_db
from ..helpers import department_options, get_department_filter, roles_required

bp = Blueprint("today", __name__)

def columns() -> list[tuple[str, str, str]]:
    """key, title, css class"""
    return [
        ("missing", _("Not in yet"), "b-missing"),
        ("late", _("Arrived late"), "b-late"),
        ("in", _("In, on time"), "b-in"),
        ("later", _("Expected later"), "b-later"),
        ("done", _("Clocked out"), "b-done"),
        ("leave", _("On leave"), "b-leave"),
    ]


def _hhmm(ts: str | None) -> str:
    return ts[11:16] if ts else ""


def classify(rec: dict, as_of: datetime, grace_minutes: int, holiday: str | None = None) -> tuple[str, str]:
    """(column, detail text) for one computed attendance record."""
    st = rec["status"]
    if st == "leave":
        return "leave", leave_type_label(rec.get("leave_type") or "other")
    if st in ("holiday", "day_off"):
        return "off", holiday or rec.get("holiday_name") or _("Day off")
    start = datetime.fromisoformat(rec["scheduled_start"])
    end = datetime.fromisoformat(rec["scheduled_end"])
    n = rec["punch_count"]
    first = _hhmm(rec["first_punch"])
    if st == "unscheduled_work":
        return "in", _("Working on a day off, in at {time}", time=first)
    if n == 0:
        due = start + timedelta(minutes=grace_minutes)
        if as_of < due:
            return "later", _("Due at {time}", time=f"{start:%H:%M}")
        if as_of >= end:
            return "missing", _("No punch for the whole shift")
        return "missing", _("{n} min past the {time} start", n=int((as_of - start).total_seconds() // 60),
                            time=f"{start:%H:%M}")
    if n >= 2:
        last = _hhmm(rec["last_punch"])
        if rec.get("early_leave_minutes"):
            return "done", _("{start} to {end}, left {n} min early", start=first, end=last,
                             n=rec["early_leave_minutes"])
        return "done", _("{start} to {end}", start=first, end=last)
    if rec.get("is_late"):
        return "late", _("In at {time}, {n} min late", time=first, n=rec["late_minutes"])
    return "in", _("In at {time}", time=first)


@bp.route("/today")
@roles_required("hr", "manager")
def index():
    conn, s = get_db(), g.settings
    now = datetime.now(ZoneInfo(s.ORG_TIMEZONE)).replace(tzinfo=None, second=0, microsecond=0)
    raw_date, raw_time = (request.args.get("date") or "").strip(), (request.args.get("time") or "").strip()
    live = not raw_date and not raw_time
    try:
        d = date.fromisoformat(raw_date) if raw_date else now.date()
        t = time.fromisoformat(raw_time[:5]) if raw_time else (now.time() if d == now.date() else time(23, 59))
    except ValueError:
        abort(400, description=_("Enter the date as 2026-08-31 and the time as 09:30."))
    as_of = datetime.combine(d, t)
    if d > now.date():
        abort(400, description=_("The board cannot show a time in the future."))
    as_of = min(as_of, now)
    dept = get_department_filter()

    ds = d.isoformat()
    emps = [e for e in repos.list_employees(conn, g.user, dept, limit=100000)
            if e["hire_date"] <= ds and (e["termination_date"] is None or e["termination_date"] >= ds)]
    by_id = {e["employee_id"]: e for e in emps}
    shifts = {r["shift_id"]: r for r in repos.list_shifts(conn)}
    cols: dict[str, list] = {key: [] for key, _t, _c in columns()}
    cols["off"] = []
    hol = conn.execute("SELECT name, name_ar FROM holidays WHERE holiday_date = ?", (ds,)).fetchone()
    holiday = loc(dict(hol), "name") if hol else None
    if by_id:
        comp = compute_attendance(conn, d, d, settings=s, as_of=as_of, employee_ids=sorted(by_id),
                                  ignore_punches_after=as_of)
        for rec in comp.records:
            sh = shifts.get(rec["shift_id"]) or {}
            col, detail = classify(rec, as_of, sh.get("grace_minutes", 0), holiday)
            e = by_id[rec["employee_id"]]
            cols[col].append({"employee_id": e["employee_id"], "code": e["employee_code"], "name": loc(e, "full_name"),
                              "dept": loc(e, "department_name"), "shift": sh.get("code", ""), "detail": detail,
                              "sort": rec["scheduled_start"] or ""})
    for k in cols:
        cols[k].sort(key=lambda r: (r["sort"], r["code"]))

    last_punch = repos.latest_punch_time(conn)
    stale = last_punch is None or last_punch < (as_of - timedelta(hours=2)).isoformat(sep=" ")
    scheduled = sum(len(cols[k]) for k in ("missing", "late", "in", "later", "done"))
    return render_template("today.html", cols=cols, columns=columns(), as_of=as_of, live=live, dept=dept,
                           departments=department_options(), last_punch=last_punch, stale=stale,
                           scheduled=scheduled, day=d, now=now,
                           replay_hint=_replay_hint(conn) if stale else None)


def _replay_hint(conn) -> str | None:
    """Latest working day with data, to offer a replay when the live feed is behind."""
    return repos.latest_present_date(conn)
