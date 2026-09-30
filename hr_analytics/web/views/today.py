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
from ...pipeline.processor import compute_attendance
from .. import get_db
from ..helpers import department_options, get_department_filter, roles_required

bp = Blueprint("today", __name__)

COLUMNS = [  # key, title, css
    ("missing", "Not in yet", "b-missing"),
    ("late", "Arrived late", "b-late"),
    ("in", "In, on time", "b-in"),
    ("later", "Expected later", "b-later"),
    ("done", "Clocked out", "b-done"),
    ("leave", "On leave", "b-leave"),
]


def _hhmm(ts: str | None) -> str:
    return ts[11:16] if ts else ""


def classify(rec: dict, as_of: datetime, grace_minutes: int) -> tuple[str, str]:
    """(column, detail text) for one computed attendance record."""
    st = rec["status"]
    if st == "leave":
        return "leave", (rec.get("leave_type") or "").title()
    if st in ("holiday", "day_off"):
        return "off", rec.get("holiday_name") or "Day off"
    start = datetime.fromisoformat(rec["scheduled_start"])
    end = datetime.fromisoformat(rec["scheduled_end"])
    n = rec["punch_count"]
    if st == "unscheduled_work":
        return "in", f"working on a day off, in {_hhmm(rec['first_punch'])}"
    if n == 0:
        due = start + timedelta(minutes=grace_minutes)
        if as_of < due:
            return "later", f"due {start:%H:%M}"
        if as_of >= end:
            return "missing", "absent, no punch all shift"
        return "missing", f"{int((as_of - start).total_seconds() // 60)} min past {start:%H:%M}"
    if n >= 2:
        early = f", left {rec['early_leave_minutes']} min early" if rec.get("early_leave_minutes") else ""
        return "done", f"{_hhmm(rec['first_punch'])} to {_hhmm(rec['last_punch'])}{early}"
    if rec.get("is_late"):
        return "late", f"in {_hhmm(rec['first_punch'])}, {rec['late_minutes']} min late"
    return "in", f"in {_hhmm(rec['first_punch'])}"


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
        abort(400, description="Use date YYYY-MM-DD and time HH:MM.")
    as_of = datetime.combine(d, t)
    if d > now.date():
        abort(400, description="The board cannot show the future.")
    as_of = min(as_of, now)
    dept = get_department_filter()

    ds = d.isoformat()
    emps = [e for e in repos.list_employees(conn, g.user, dept, limit=100000)
            if e["hire_date"] <= ds and (e["termination_date"] is None or e["termination_date"] >= ds)]
    by_id = {e["employee_id"]: e for e in emps}
    shifts = {r["shift_id"]: r for r in repos.list_shifts(conn)}
    cols: dict[str, list] = {k: [] for k, _, _ in COLUMNS}
    cols["off"] = []
    if by_id:
        comp = compute_attendance(conn, d, d, settings=s, as_of=as_of, employee_ids=sorted(by_id),
                                  ignore_punches_after=as_of)
        for rec in comp.records:
            sh = shifts.get(rec["shift_id"]) or {}
            col, detail = classify(rec, as_of, sh.get("grace_minutes", 0))
            e = by_id[rec["employee_id"]]
            cols[col].append({"employee_id": e["employee_id"], "code": e["employee_code"], "name": e["full_name"],
                              "dept": e["department_code"], "shift": sh.get("code", ""), "detail": detail,
                              "sort": rec["scheduled_start"] or ""})
    for k in cols:
        cols[k].sort(key=lambda r: (r["sort"], r["code"]))

    last_punch = repos.latest_punch_time(conn)
    stale = last_punch is None or last_punch < (as_of - timedelta(hours=2)).isoformat(sep=" ")
    scheduled = sum(len(cols[k]) for k in ("missing", "late", "in", "later", "done"))
    return render_template("today.html", cols=cols, columns=COLUMNS, as_of=as_of, live=live, dept=dept,
                           departments=department_options(), last_punch=last_punch, stale=stale,
                           scheduled=scheduled, day=d, now=now,
                           replay_hint=_replay_hint(conn) if stale else None)


def _replay_hint(conn) -> str | None:
    """Latest working day with data, to offer a replay when the live feed is behind."""
    return repos.latest_present_date(conn)
