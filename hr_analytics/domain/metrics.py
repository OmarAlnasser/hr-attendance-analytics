"""KPI definitions — one implementation used by the web app, PDF report and
the Power BI reconciliation file, so every surface shows the same numbers.

Grain of the input: one row per employee per shift_date (attendance_daily).

Expected days      rows with status in {present, incomplete, absent}
                   (excludes leave, holiday, day_off, pending, unscheduled_work
                   and any day outside employment, which never gets a row)
Attended days      rows with status in {present, incomplete}
Attendance rate    attended / expected                       -> None if expected = 0
Absence rate       absent / expected                         -> None if expected = 0
Late rate          late attended days / attended days         -> None if attended = 0
Incomplete rate    incomplete / attended                      -> None if attended = 0
Avg late minutes   sum(late_minutes on late days) / late days -> None if no late days
Avg presence span  mean(span_minutes) on 'present' days / 60  -> labelled as presence,
                   not verified working hours
Rates are pooled (day-weighted), which makes departments of different sizes
comparable; the number of employees and expected days is always shown next to
a rate so small samples are visible.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from .attendance_rules import ABSENT, ATTENDED_STATUSES, EXPECTED_STATUSES, HOLIDAY, INCOMPLETE, LEAVE, PENDING, UNSCHEDULED

EVALUABLE_MIN_DAYS = 10  # an employee-month is evaluable if employed >= 10 days of the month

WEEKDAY_ORDER = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def safe_div(numerator, denominator):
    if denominator is None or denominator == 0 or pd.isna(denominator):
        return None
    return float(numerator) / float(denominator)


def attendance_kpis(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        df = pd.DataFrame(columns=["status", "is_late", "late_minutes", "span_minutes",
                                   "early_leave_minutes", "employee_id"])
    status = df["status"]
    expected_mask = status.isin(EXPECTED_STATUSES)
    attended_mask = status.isin(ATTENDED_STATUSES)
    late_mask = attended_mask & (df["is_late"].fillna(0).astype(int) == 1)
    present_span = df.loc[status == "present", "span_minutes"].dropna()

    expected = int(expected_mask.sum())
    attended = int(attended_mask.sum())
    late_days = int(late_mask.sum())
    return {
        "employees": int(df["employee_id"].nunique()) if "employee_id" in df else 0,
        "expected_days": expected,
        "attended_days": attended,
        "absent_days": int((status == ABSENT).sum()),
        "incomplete_days": int((status == INCOMPLETE).sum()),
        "late_days": late_days,
        "early_leave_days": int((attended_mask & (df["early_leave_minutes"].fillna(0) > 0)).sum()),
        "leave_days": int((status == LEAVE).sum()),
        "holiday_days": int((status == HOLIDAY).sum()),
        "pending_days": int((status == PENDING).sum()),
        "unscheduled_days": int((status == UNSCHEDULED).sum()),
        "attendance_rate": safe_div(attended, expected),
        "absence_rate": safe_div(int((status == ABSENT).sum()), expected),
        "late_rate": safe_div(late_days, attended),
        "incomplete_rate": safe_div(int((status == INCOMPLETE).sum()), attended),
        "avg_late_minutes": safe_div(float(df.loc[late_mask, "late_minutes"].sum()), late_days),
        "avg_presence_span_hours": (float(present_span.mean()) / 60.0) if len(present_span) else None,
    }


def grouped_attendance_kpis(df: pd.DataFrame, by: str | list[str]) -> pd.DataFrame:
    """attendance_kpis() per group, vectorised: one groupby over indicator columns
    instead of one Python call per group (the review page groups by employee, and
    on a small cloud CPU the per-group loop dominated page time). Same keys and the
    same None-for-zero-denominator rules as attendance_kpis(); a test checks both agree."""
    if df.empty:
        return pd.DataFrame()
    keys = [by] if isinstance(by, str) else list(by)
    st = df["status"]
    attended = st.isin(ATTENDED_STATUSES)
    late = attended & (df["is_late"].fillna(0).astype(int) == 1)
    span = df["span_minutes"].where(st == "present")
    w = pd.DataFrame({k: df[k] for k in keys})
    w["_expected"] = st.isin(EXPECTED_STATUSES).astype(int)
    w["_attended"] = attended.astype(int)
    w["_absent"] = (st == ABSENT).astype(int)
    w["_incomplete"] = (st == INCOMPLETE).astype(int)
    w["_late"] = late.astype(int)
    w["_early"] = (attended & (df["early_leave_minutes"].fillna(0) > 0)).astype(int)
    w["_leave"] = (st == LEAVE).astype(int)
    w["_holiday"] = (st == HOLIDAY).astype(int)
    w["_pending"] = (st == PENDING).astype(int)
    w["_unscheduled"] = (st == UNSCHEDULED).astype(int)
    w["_late_minutes"] = df["late_minutes"].fillna(0).where(late, 0).astype(float)
    w["_span_sum"] = span.fillna(0).astype(float)
    w["_span_n"] = span.notna().astype(int)
    w["_emp"] = df["employee_id"] if "employee_id" in df else 0
    g = w.groupby(keys, dropna=False, sort=True)
    sums = g[[c for c in w.columns if c.startswith("_") and c != "_emp"]].sum()
    emps = g["_emp"].nunique() if "employee_id" in df else None
    rows = []
    for key, r in sums.iterrows():
        exp, att, late_n = int(r["_expected"]), int(r["_attended"]), int(r["_late"])
        k = {
            "employees": int(emps.loc[key]) if emps is not None else 0,
            "expected_days": exp,
            "attended_days": att,
            "absent_days": int(r["_absent"]),
            "incomplete_days": int(r["_incomplete"]),
            "late_days": late_n,
            "early_leave_days": int(r["_early"]),
            "leave_days": int(r["_leave"]),
            "holiday_days": int(r["_holiday"]),
            "pending_days": int(r["_pending"]),
            "unscheduled_days": int(r["_unscheduled"]),
            "attendance_rate": safe_div(att, exp),
            "absence_rate": safe_div(int(r["_absent"]), exp),
            "late_rate": safe_div(late_n, att),
            "incomplete_rate": safe_div(int(r["_incomplete"]), att),
            "avg_late_minutes": safe_div(float(r["_late_minutes"]), late_n),
            "avg_presence_span_hours": (float(r["_span_sum"]) / float(r["_span_n"]) / 60.0) if r["_span_n"] else None,
        }
        k.update(dict(zip(keys, key if isinstance(key, tuple) else (key,))))
        rows.append(k)
    return pd.DataFrame(rows)


def performance_kpis(evals: pd.DataFrame, active_employee_months: int, threshold: float) -> dict:
    n = 0 if evals is None else len(evals)
    scores = evals["weighted_score"] if n else pd.Series(dtype=float)
    return {
        "evaluations": n,
        "evaluable_employee_months": int(active_employee_months),
        "coverage": safe_div(n, active_employee_months),
        "avg_weighted_score": float(scores.mean()) if n else None,
        "low_score_rate": safe_div(int((scores < threshold).sum()), n),
        "low_score_count": int((scores < threshold).sum()) if n else 0,
        "threshold": threshold,
    }


def weekday_week_heatmap(df: pd.DataFrame) -> pd.DataFrame:
    """Attendance rate by week (Sunday-start) x weekday, expected days only."""
    exp = df[df["status"].isin(EXPECTED_STATUSES)].copy()
    if exp.empty:
        return pd.DataFrame()
    d = pd.to_datetime(exp["shift_date"])
    exp["weekday"] = d.dt.strftime("%a")
    exp["week_start"] = (d - pd.to_timedelta((d.dt.weekday + 1) % 7, unit="D")).dt.date
    exp["attended"] = exp["status"].isin(ATTENDED_STATUSES).astype(int)
    pivot = exp.pivot_table(index="week_start", columns="weekday", values="attended", aggfunc="mean")
    return pivot.reindex(columns=[c for c in WEEKDAY_ORDER if c in pivot.columns])


def fmt_pct(v, digits: int = 1) -> str:
    return "—" if v is None or pd.isna(v) else f"{v * 100:.{digits}f}%"


def fmt_num(v, digits: int = 1) -> str:
    return "—" if v is None or pd.isna(v) else f"{v:,.{digits}f}"


def evaluable_employee_months(emps: pd.DataFrame, first: date, last: date,
                              min_days: int = EVALUABLE_MIN_DAYS) -> int:
    """Employees employed for at least `min_days` days between first and last.
    Denominator of evaluation coverage."""
    n = 0
    for r in emps.itertuples():
        start = max(first, date.fromisoformat(r.hire_date))
        term = r.termination_date if isinstance(r.termination_date, str) and r.termination_date else None
        end = min(last, date.fromisoformat(term)) if term else last
        if (end - start).days + 1 >= min_days:
            n += 1
    return n
