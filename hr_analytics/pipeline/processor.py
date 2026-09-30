"""Build attendance_daily from raw punches, schedules, holidays and leave.

Re-running for the same range produces identical rows (delete + insert inside
one transaction), so imports can be repeated or corrected safely.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from ..db import repos
from ..db.connection import now_str, transaction
from ..domain.attendance_rules import RuleConfig, ShiftDef, evaluate_day, window


@dataclass
class ProcessSummary:
    start: str
    end: str
    employees: int
    rows_written: int
    status_counts: dict
    exceptions: dict
    days_without_shift: int


def _daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _shift_on(assigns: list[dict], d: date, shifts: dict[int, ShiftDef]) -> ShiftDef | None:
    ds = d.isoformat()
    for a in reversed(assigns):  # ordered by effective_from
        if a["effective_from"] <= ds and (a["effective_to"] is None or a["effective_to"] >= ds):
            return shifts.get(a["shift_id"])
    return None


@dataclass
class Computed:
    records: list
    exceptions: list
    emp_ids: list
    status_counts: dict
    exc_counts: dict
    no_shift_days: int
    range_lo: datetime
    range_hi: datetime


def process_attendance(conn, start: date, end: date, *, settings, as_of: datetime | None = None,
                       employee_ids: list[int] | None = None, user_id: int | None = None) -> ProcessSummary:
    as_of = as_of or datetime.now()
    c = compute_attendance(conn, start, end, settings=settings, as_of=as_of, employee_ids=employee_ids)
    with transaction(conn):
        repos.replace_attendance(conn, start.isoformat(), end.isoformat(), c.emp_ids, c.records)
        repos.replace_exceptions(conn, c.range_lo.isoformat(sep=" "), c.range_hi.isoformat(sep=" "), c.emp_ids,
                                 c.exceptions)
        repos.audit(conn, user_id, "process_attendance", "attendance_daily", None,
                    {"start": start.isoformat(), "end": end.isoformat(), "rows": len(c.records),
                     "as_of": as_of.isoformat(sep=" ")})
    return ProcessSummary(start.isoformat(), end.isoformat(), len(c.emp_ids), len(c.records),
                          c.status_counts, c.exc_counts, c.no_shift_days)


def compute_attendance(conn, start: date, end: date, *, settings, as_of: datetime | None = None,
                       employee_ids: list[int] | None = None, ignore_punches_after: datetime | None = None) -> Computed:
    """Evaluate attendance without writing anything (used by processing and by the live Today board).

    `ignore_punches_after` replays a past moment: punches later than it are treated as not yet received."""
    cfg = RuleConfig.from_settings(settings)
    as_of = as_of or datetime.now()
    shifts = {r["shift_id"]: ShiftDef.from_row(r) for r in repos.list_shifts(conn)}
    employment = {r["employee_id"]: r for r in repos.employment_rows(conn, employee_ids)}
    emp_ids = sorted(employment)
    assigns_by_emp: dict[int, list] = defaultdict(list)
    for a in repos.assignments(conn, emp_ids):
        assigns_by_emp[a["employee_id"]].append(a)

    holidays = repos.holidays_between(conn, start.isoformat(), end.isoformat())
    leave_by_emp_day: dict[tuple[int, str], str] = {}
    for lv in repos.approved_leaves(conn, start.isoformat(), end.isoformat(), emp_ids):
        for d in _daterange(date.fromisoformat(lv["start_date"]), date.fromisoformat(lv["end_date"])):
            leave_by_emp_day[(lv["employee_id"], d.isoformat())] = lv["leave_type"]

    # Load punches with margin so that windows at the range edges are complete.
    load_from = datetime.combine(start - timedelta(days=1), datetime.min.time())
    load_to = datetime.combine(end + timedelta(days=2), datetime.min.time())
    punches_by_emp: dict[int, list] = defaultdict(list)
    for p in repos.punches_between(conn, load_from.isoformat(sep=" "), load_to.isoformat(sep=" "), emp_ids):
        ts = datetime.fromisoformat(p["punch_time_local"])
        if ignore_punches_after is not None and ts > ignore_punches_after:
            continue
        punches_by_emp[p["employee_id"]].append((ts, p["punch_id"]))

    records, exceptions = [], []
    status_counts: dict[str, int] = defaultdict(int)
    exc_counts: dict[str, int] = defaultdict(int)
    no_shift_days = 0
    processed_at = now_str()
    range_lo = datetime.combine(start, datetime.min.time())
    range_hi = datetime.combine(end + timedelta(days=1), datetime.min.time())

    for emp_id in emp_ids:
        emp = employment[emp_id]
        hire = date.fromisoformat(emp["hire_date"])
        term = date.fromisoformat(emp["termination_date"]) if emp["termination_date"] else None
        assigns = assigns_by_emp.get(emp_id, [])

        # Windows for the range plus one day each side (a night shift of the day
        # before the range owns early-morning punches on the first day).
        wins = []
        for d in _daterange(start - timedelta(days=1), end + timedelta(days=1)):
            sh = _shift_on(assigns, d, shifts)
            if sh is not None:
                ws, we = window(sh, d, cfg)
                wins.append((ws, we, d, sh))
        wins.sort(key=lambda w: w[0])
        starts = [w[0] for w in wins]

        by_day: dict[date, list[datetime]] = defaultdict(list)
        for ts, punch_id in punches_by_emp.get(emp_id, []):
            i = bisect_right(starts, ts) - 1
            # Windows of one shift pattern never overlap, but they can when the
            # shift changes (e.g. night -> day). Pick the containing window whose
            # scheduled start or end is closest to the punch.
            candidates = [wins[j] for j in range(i, max(i - 3, -1), -1) if wins[j][0] <= ts <= wins[j][1]]
            match = None
            if candidates:
                def distance(w):
                    s_, e_ = w[3].bounds(w[2])
                    return min(abs((ts - s_).total_seconds()), abs((ts - e_).total_seconds()))
                match = min(candidates, key=distance)
            in_range = range_lo <= ts < range_hi
            if match is None:
                if in_range:
                    pd_ = ts.date()
                    if pd_ < hire or (term is not None and pd_ > term):
                        reason = "outside_employment"      # e.g. before the first shift assignment starts
                    else:
                        reason = "no_shift_window" if assigns else "no_shift_assignment"
                    exceptions.append((punch_id, emp_id, ts.isoformat(sep=" "), None, reason, processed_at))
                    exc_counts[reason] += 1
                continue
            d = match[2]
            employed = d >= hire and (term is None or d <= term)
            if not employed:
                if start <= d <= end:
                    exceptions.append((punch_id, emp_id, ts.isoformat(sep=" "), d.isoformat(),
                                       "outside_employment", processed_at))
                    exc_counts["outside_employment"] += 1
                continue
            by_day[d].append(ts)

        for d in _daterange(max(start, hire), min(end, term) if term else end):
            sh = _shift_on(assigns, d, shifts)
            if sh is None:
                no_shift_days += 1
                continue
            rec = evaluate_day(d, sh, by_day.get(d, []), as_of=as_of, cfg=cfg,
                               holiday_name=holidays.get(d.isoformat()),
                               leave_type=leave_by_emp_day.get((emp_id, d.isoformat())))
            rec["employee_id"] = emp_id
            rec["processed_at"] = processed_at
            records.append(rec)
            status_counts[rec["status"]] += 1

    return Computed(records, exceptions, emp_ids, dict(status_counts), dict(exc_counts), no_shift_days,
                    range_lo, range_hi)


# A batch updates shift dates from the day of its first punch up to the day of
# its last punch minus TRAILING_HOURS. The offset stops trailing night-shift
# clock-outs (e.g. 05:58 on the 1st of next month) from pulling in the next day,
# whose day-shift punches the file does not contain (those employees would
# otherwise be marked absent). The day before the first punch is included only
# when punches for it already exist from an earlier batch, so that a night shift
# whose clock-in came in the previous file gets its clock-out from this one.
TRAILING_HOURS = 8


def range_for_batch(min_punch_time: str | None, max_punch_time: str | None,
                    conn=None, batch_id: int | None = None) -> tuple[date, date] | None:
    """Shift dates that a batch can safely (re)evaluate."""
    if not min_punch_time or not max_punch_time:
        return None
    first = datetime.fromisoformat(min_punch_time)
    last = datetime.fromisoformat(max_punch_time)
    lo = first.date()
    hi = (last - timedelta(hours=TRAILING_HOURS)).date()
    if conn is not None:
        prev = lo - timedelta(days=1)
        sql = "SELECT 1 FROM raw_punches WHERE punch_time_local >= ? AND punch_time_local < ?"
        params: list = [f"{prev} 00:00:00", f"{lo} 00:00:00"]
        if batch_id is not None:
            sql += " AND batch_id <> ?"
            params.append(batch_id)
        exists = conn.execute(sql + " LIMIT 1", params).fetchone()
        if exists:
            lo = prev
    if hi < lo:
        hi = lo
    return lo, hi
