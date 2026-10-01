"""Attendance rules — pure functions, no database access.

Definitions (also in docs/metrics_definitions.md)
------------------------------------------------
shift_date        The calendar date on which the shift STARTS. A 22:00-06:00
                  shift that starts on Sunday belongs to Sunday even though
                  its punches end on Monday.
punch window      A punch belongs to shift_date D if it falls inside
                  [start(D) - window_before, end(D) + window_after].
double taps      Punches closer than `debounce_minutes` to the previously
                  kept punch are treated as one (someone tapping twice).
minute resolution Rules compare times truncated to the minute (seconds dropped).
late              first punch (minute) > scheduled start + grace minutes.
                  Exactly at start + grace is ON TIME.
late_minutes      first punch - scheduled start (default), or
                  first punch - (start + grace) when LATE_MINUTES_FROM='grace_end'.
early leave       last punch (minute) < scheduled end - early-leave grace.
span_minutes      last punch - first punch. This is PRESENCE SPAN, not
                  verified working time: breaks, exits in between and
                  unpaired IN/OUT are not known from the device data.
absent            A scheduled working day with zero punches, decided only
                  once the shift has ended (as_of >= scheduled end).
                  Before that the day is 'pending'.
incomplete        Exactly one punch after the shift ended (missing IN or OUT).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

WEEKDAY_CODES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")  # index = date.weekday()

PRESENT = "present"
INCOMPLETE = "incomplete"
ABSENT = "absent"
LEAVE = "leave"
HOLIDAY = "holiday"
DAY_OFF = "day_off"
PENDING = "pending"
UNSCHEDULED = "unscheduled_work"

ALL_STATUSES = (PRESENT, INCOMPLETE, ABSENT, LEAVE, HOLIDAY, DAY_OFF, PENDING, UNSCHEDULED)
EXPECTED_STATUSES = frozenset({PRESENT, INCOMPLETE, ABSENT})   # attendance-rate denominator
ATTENDED_STATUSES = frozenset({PRESENT, INCOMPLETE})           # attendance-rate numerator


def parse_hhmm(value: str) -> time:
    try:
        hh, mm = value.strip().split(":")[:2]
        return time(int(hh), int(mm))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Invalid time '{value}', expected HH:MM") from exc


def parse_workdays(value: str) -> frozenset[int]:
    days = set()
    for token in (value or "").replace(" ", "").upper().split(","):
        if not token:
            continue
        if token not in WEEKDAY_CODES:
            raise ValueError(f"Unknown weekday code '{token}'. Use {', '.join(WEEKDAY_CODES)}")
        days.add(WEEKDAY_CODES.index(token))
    if not days:
        raise ValueError("A shift needs at least one working day")
    return frozenset(days)


@dataclass(frozen=True)
class ShiftDef:
    shift_id: int
    code: str
    start: time
    end: time
    grace_minutes: int = 15
    early_leave_grace_minutes: int = 5
    workdays: frozenset = frozenset({6, 0, 1, 2, 3})  # SUN-THU

    @classmethod
    def from_row(cls, row) -> "ShiftDef":
        return cls(
            shift_id=row["shift_id"],
            code=row["code"],
            start=parse_hhmm(row["start_time"]),
            end=parse_hhmm(row["end_time"]),
            grace_minutes=int(row["grace_minutes"]),
            early_leave_grace_minutes=int(row["early_leave_grace_minutes"]),
            workdays=parse_workdays(row["workdays"]),
        )

    @property
    def crosses_midnight(self) -> bool:
        return self.end <= self.start

    def bounds(self, shift_date: date) -> tuple[datetime, datetime]:
        start = datetime.combine(shift_date, self.start)
        end_day = shift_date + timedelta(days=1) if self.crosses_midnight else shift_date
        return start, datetime.combine(end_day, self.end)

    @property
    def length_minutes(self) -> int:
        s, e = self.bounds(date(2000, 1, 3))
        return int((e - s).total_seconds() // 60)

    def is_workday(self, d: date) -> bool:
        return d.weekday() in self.workdays


@dataclass(frozen=True)
class RuleConfig:
    debounce_minutes: int = 2
    window_before_start_min: int = 240
    window_after_end_min: int = 360
    late_minutes_from: str = "start"
    version: str = "attendance-rules-1.0"

    @classmethod
    def from_settings(cls, s) -> "RuleConfig":
        return cls(s.PUNCH_DEBOUNCE_MINUTES, s.WINDOW_BEFORE_START_MIN, s.WINDOW_AFTER_END_MIN,
                   s.LATE_MINUTES_FROM, s.RULE_VERSION)


def validate_shift(shift: ShiftDef, cfg: RuleConfig) -> list[str]:
    """Windows of consecutive days must not overlap, otherwise a punch is ambiguous."""
    errors = []
    length = shift.length_minutes
    if length <= 0 or length > 16 * 60:
        errors.append("Shift length must be between 1 minute and 16 hours.")
    if length + cfg.window_before_start_min + cfg.window_after_end_min >= 24 * 60:
        errors.append("Shift length plus punch windows must be under 24 hours "
                      "so consecutive days do not overlap.")
    if shift.grace_minutes >= length:
        errors.append("Grace period must be shorter than the shift.")
    return errors


def window(shift: ShiftDef, shift_date: date, cfg: RuleConfig) -> tuple[datetime, datetime]:
    start, end = shift.bounds(shift_date)
    return (start - timedelta(minutes=cfg.window_before_start_min),
            end + timedelta(minutes=cfg.window_after_end_min))


def to_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def collapse_punches(punches: list[datetime], debounce_minutes: int) -> list[datetime]:
    """Drop punches within `debounce_minutes` of the previously kept punch."""
    kept: list[datetime] = []
    for p in sorted(punches):
        if kept and (p - kept[-1]) < timedelta(minutes=debounce_minutes):
            continue
        kept.append(p)
    return kept


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def evaluate_day(
    shift_date: date,
    shift: ShiftDef,
    punches: list[datetime],
    *,
    as_of: datetime,
    cfg: RuleConfig,
    holiday_name: str | None = None,
    leave_type: str | None = None,
) -> dict:
    """Return the daily attendance record for one employee and one shift date."""
    start, end = shift.bounds(shift_date)
    kept = collapse_punches(punches, cfg.debounce_minutes)
    n = len(kept)
    notes: list[str] = []
    rec = {
        "shift_date": shift_date.isoformat(),
        "shift_id": shift.shift_id,
        "scheduled_start": start.isoformat(sep=" "),
        "scheduled_end": end.isoformat(sep=" "),
        "scheduled_minutes": _minutes(end - start),
        "raw_punch_count": len(punches),
        "punch_count": n,
        "first_punch": kept[0].isoformat(sep=" ") if n else None,
        "last_punch": kept[-1].isoformat(sep=" ") if n >= 2 else None,
        "is_late": 0,
        "late_minutes": 0,
        "early_leave_minutes": 0,
        "span_minutes": None,
        "leave_type": None,
        "holiday_name": holiday_name,
        "rule_version": cfg.version,
    }
    # Double taps merged into one punch are routine and not noted; raw_punch_count
    # versus punch_count still shows how many were merged.

    workday = shift.is_workday(shift_date)
    if leave_type:
        status = LEAVE
        rec["leave_type"] = leave_type
        if n:
            notes.append("punches_on_approved_leave")
    elif holiday_name and workday:
        status = HOLIDAY if n == 0 else UNSCHEDULED
    elif not workday:
        status = DAY_OFF if n == 0 else UNSCHEDULED
    else:
        shift_over = as_of >= end
        if n == 0:
            status = ABSENT if shift_over else PENDING
        elif n == 1:
            status = INCOMPLETE if shift_over else PENDING
        else:
            status = PRESENT

    # Punctuality applies only to scheduled working days that have punches.
    if status in (PRESENT, INCOMPLETE, PENDING) and n >= 1:
        first = to_minute(kept[0])
        single_near_end = n == 1 and abs(first - end) < abs(first - start)
        if single_near_end:
            # One punch close to the scheduled end: arrival time is unknown.
            notes.append("missing_in_punch" if status == INCOMPLETE else "open_shift")
        else:
            if n == 1 and status == INCOMPLETE:
                notes.append("missing_out_punch")
            grace_end = start + timedelta(minutes=shift.grace_minutes)
            if first > grace_end:
                ref = start if cfg.late_minutes_from == "start" else grace_end
                rec["is_late"] = 1
                rec["late_minutes"] = _minutes(first - ref)

    if n >= 2:
        rec["span_minutes"] = _minutes(kept[-1] - kept[0])
        if status == PRESENT:
            last = to_minute(kept[-1])
            cutoff = end - timedelta(minutes=shift.early_leave_grace_minutes)
            if last < cutoff:
                rec["early_leave_minutes"] = _minutes(end - last)

    rec["status"] = status
    rec["notes"] = ";".join(notes) or None
    return rec
