"""Self-service requests: leave and missed-punch corrections (schema v2).

Pure business rules on a DB connection (no Flask), so the web app, the CLI
and the tests share them. Every function that changes data leaves the
transaction to the caller except `approve_correction`, which must insert the
manual batch, the punch and the decision atomically.

Workflow
--------
employee   submits a request for their OWN record; can cancel it while pending
           (and cancel approved leave that has not started yet)
manager    decides requests of employees in departments they manage, never their own
hr         decides any request except their own

An approved leave is picked up by attendance processing like any HR-entered
leave. An approved correction becomes a raw punch with device_id 'MANUAL' in
its own import batch (source_type 'manual'), so it goes through exactly the
same rules as a device punch and stays traceable to the request and approver.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..db import repos
from ..db.connection import now_str, transaction
from ..domain.attendance_rules import RuleConfig, ShiftDef, window
from ..i18n import _
from ..labels import leave_type_label, punch_kind_label, request_status_label
from ..pipeline.processor import process_attendance

LEAVE_TYPES = ("annual", "sick", "unpaid", "other")
PUNCH_KINDS = ("in", "out")
MAX_LEAVE_DAYS = 180
LEAVE_BACKDATE_DAYS = 90          # e.g. sick leave reported after the fact
LEAVE_AHEAD_DAYS = 365
CORRECTION_BACKDATE_DAYS = 60
MANUAL_DEVICE = "MANUAL"


@dataclass
class Validated:
    data: dict
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def _parse_date(value: str | None, label: str, errors: list[str]) -> date | None:
    value = (value or "").strip()
    if not value:
        errors.append(_("{label} is required.", label=label))
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(_("{label} is not a valid date.", label=label))
        return None


def _employment_errors(emp: dict, start: date, end: date) -> list[str]:
    errs = []
    if start < date.fromisoformat(emp["hire_date"]):
        errs.append(_("The dates start before the joining date ({date}).", date=emp["hire_date"]))
    if emp["termination_date"] and end > date.fromisoformat(emp["termination_date"]):
        errs.append(_("The dates run past the last day of employment ({date}).", date=emp["termination_date"]))
    return errs


# ------------------------------------------------------------------ leave --

def validate_leave(conn, emp: dict, form: dict, today: date) -> Validated:
    errors: list[str] = []
    ltype = (form.get("leave_type") or "").strip()
    if ltype not in LEAVE_TYPES:
        errors.append(_("Choose a leave type."))
    start = _parse_date(form.get("start_date"), _("Start date"), errors)
    end = _parse_date(form.get("end_date"), _("End date"), errors)
    reason = (form.get("reason") or "").strip()[:500] or None
    if ltype == "other" and not reason:
        errors.append(_("Please give a short reason when the leave type is Other."))
    if start and end:
        if end < start:
            errors.append(_("The end date is before the start date."))
        elif (end - start).days + 1 > MAX_LEAVE_DAYS:
            errors.append(_("One request can cover at most {n} days. Please split longer leave into several requests.",
                            n=MAX_LEAVE_DAYS))
        if start < today - timedelta(days=LEAVE_BACKDATE_DAYS):
            errors.append(_("Leave can be requested up to {n} days after it started. For anything older, please contact HR.",
                            n=LEAVE_BACKDATE_DAYS))
        if end > today + timedelta(days=LEAVE_AHEAD_DAYS):
            errors.append(_("Leave can be requested up to one year ahead."))
        if not errors:
            errors += _employment_errors(emp, start, end)
        if not errors:
            clash = repos.overlapping_leave(conn, emp["employee_id"], start.isoformat(), end.isoformat())
            if clash:
                errors.append(_("These dates overlap another request: {kind} from {start} to {end} ({status}).",
                                kind=leave_type_label(clash["leave_type"]), start=clash["start_date"],
                                end=clash["end_date"], status=request_status_label(clash["status"])))
    return Validated({"employee_id": emp["employee_id"], "leave_type": ltype,
                      "start_date": start.isoformat() if start else None,
                      "end_date": end.isoformat() if end else None, "reason": reason}, errors)


def leave_cancellable_by_employee(leave: dict, today: date) -> bool:
    return leave["status"] == "pending" or (leave["status"] == "approved" and leave["start_date"] > today.isoformat())


# ------------------------------------------------------------ corrections --

def shift_date_for_punch(conn, settings, employee_id: int, ts: datetime) -> date | None:
    """The shift date whose punch window contains `ts` (same windows as processing)."""
    cfg = RuleConfig.from_settings(settings)
    shifts = {r["shift_id"]: ShiftDef.from_row(r) for r in repos.list_shifts(conn)}
    assigns = repos.assignments(conn, [employee_id])
    best = None
    for d in (ts.date() - timedelta(days=1), ts.date()):
        ds = d.isoformat()
        sh = None
        for a in reversed(assigns):
            if a["effective_from"] <= ds and (a["effective_to"] is None or a["effective_to"] >= ds):
                sh = shifts.get(a["shift_id"])
                break
        if sh is None:
            continue
        ws, we = window(sh, d, cfg)
        if ws <= ts <= we:
            s_, e_ = sh.bounds(d)
            dist = min(abs((ts - s_).total_seconds()), abs((ts - e_).total_seconds()))
            if best is None or dist < best[0]:
                best = (dist, d)
    return best[1] if best else None


def validate_correction(conn, settings, emp: dict, form: dict, now: datetime) -> Validated:
    errors: list[str] = []
    kind = (form.get("punch_kind") or "").strip()
    if kind not in PUNCH_KINDS:
        errors.append(_("Choose whether the missed punch was a clock-in or a clock-out."))
    raw = (form.get("punch_time") or "").strip().replace("T", " ")
    ts = None
    try:
        ts = datetime.fromisoformat(raw).replace(second=0, microsecond=0)
    except ValueError:
        errors.append(_("Enter the date and time of the missed punch."))
    reason = (form.get("reason") or "").strip()
    if not 5 <= len(reason) <= 500:
        errors.append(_("Briefly explain what happened, in 5 to 500 characters (for example: the badge reader at gate 2 was not working)."))
    shift_date = None
    if ts is not None:
        if ts > now:
            errors.append(_("The punch time is in the future."))
        elif ts < now - timedelta(days=CORRECTION_BACKDATE_DAYS):
            errors.append(_("Missed punches can be reported for the last {n} days only.", n=CORRECTION_BACKDATE_DAYS))
        else:
            shift_date = shift_date_for_punch(conn, settings, emp["employee_id"], ts)
            if shift_date is None:
                errors.append(_("That time is not close to any of your shifts, so it would not count towards any "
                                "day. Please check the date, or contact HR."))
            else:
                errors += _employment_errors(emp, shift_date, shift_date)
    if not errors and ts is not None and shift_date is not None:
        near = repos.punches_near(conn, emp["employee_id"], ts.isoformat(sep=" "), settings.PUNCH_DEBOUNCE_MINUTES)
        if near:
            errors.append(_("A punch at {time} is already recorded around that time.",
                            time=near[0]["punch_time_local"][11:16]))
        elif repos.pending_correction_for(conn, emp["employee_id"], shift_date.isoformat(), kind):
            errors.append(_("You have already reported this missed punch ({kind}) for {date}, and it is waiting "
                            "for a decision.", kind=punch_kind_label(kind), date=shift_date.isoformat()))
    return Validated({"employee_id": emp["employee_id"], "punch_kind": kind, "reason": reason,
                      "punch_time": ts.isoformat(sep=" ") if ts else None,
                      "shift_date": shift_date.isoformat() if shift_date else None}, errors)


def approve_correction(conn, corr: dict, settings, user_id: int, note: str | None) -> int:
    """Insert the manual batch + punch and mark the request approved, in one transaction.
    Returns the new punch_id. Raises ValueError if the request is no longer pending or the punch already exists."""
    digest = hashlib.sha256(f"manual-correction:{corr['correction_id']}".encode()).hexdigest()
    with transaction(conn):
        if repos.get_correction(conn, corr["correction_id"])["status"] != "pending":
            raise ValueError(_("This request has already been decided."))
        bid = repos.insert_batch(conn, {
            "source_type": "manual", "source_name": f"Correction #{corr['correction_id']} ({corr['employee_code']})",
            "stored_path": None, "source_device": MANUAL_DEVICE, "source_timezone": settings.ORG_TIMEZONE,
            "file_sha256": digest, "imported_by_user_id": user_id, "imported_at": now_str(), "status": "success",
            "rows_total": 1, "rows_accepted": 1, "rows_duplicate": 0, "rows_rejected": 0,
            "min_punch_time": corr["punch_time"], "max_punch_time": corr["punch_time"],
            "message": f"Approved missed-punch correction #{corr['correction_id']}: {corr['reason'][:200]}"})
        added = repos.insert_raw_punches(conn, [(bid, 1, corr["badge_id"], corr["employee_id"], corr["punch_time"],
                                                 corr["punch_time"], corr["punch_kind"].upper(), MANUAL_DEVICE)])
        if added != 1:
            raise ValueError(_("The same punch has already been added."))
        punch_id = repos.punch_id_in_batch(conn, bid)
        if not repos.decide_correction(conn, corr["correction_id"], "approved", user_id, note, punch_id):
            raise ValueError(_("This request has already been decided."))
        repos.audit(conn, user_id, "correction_approve", "attendance_correction", corr["correction_id"],
                    {"employee_id": corr["employee_id"], "punch_time": corr["punch_time"], "punch_id": punch_id,
                     "batch_id": bid})
    return punch_id


# ----------------------------------------------------------- reprocessing --

def reprocess_range(conn, settings, start: str | date, end: str | date, employee_ids: list[int] | None,
                    user_id: int | None, today: date | None = None) -> str | None:
    """Re-evaluate [start, end] clipped to the processed range and to today. Returns a message or None."""
    last = repos.latest_attendance_date(conn)
    if not last:
        return None
    today = today or date.today()
    lo = date.fromisoformat(str(start))
    hi = min(date.fromisoformat(str(end)), date.fromisoformat(last), today)
    if lo > hi:
        return None
    s = process_attendance(conn, lo, hi, settings=settings, employee_ids=employee_ids, user_id=user_id)
    return _("Attendance was recalculated from {start} to {end}.", start=s.start, end=s.end)
