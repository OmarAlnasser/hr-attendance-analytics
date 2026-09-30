"""Cases that need a human review.

These are transparent RULES, not predictions. A flag means "worth a
conversation", never an automatic consequence. Thresholds are deliberately
simple so an HR reviewer can verify each flag from the raw numbers.
"""
from __future__ import annotations

import pandas as pd

from ..db import repos
from ..domain.metrics import grouped_attendance_kpis
from ..domain.scoring import parse_period, shift_period
from ..security.scope import UserContext

RULES = {
    "ABSENCE_3PLUS": "3 or more unexcused absences in the month",
    "LATE_RATE_30": "Late on at least 30% of attended days (minimum 5 attended days)",
    "INCOMPLETE_3PLUS": "3 or more days with a single punch (missing IN or OUT)",
    "SCORE_BELOW_THRESHOLD": "Weighted performance score below the review threshold",
    "SCORE_DROP_1": "Weighted score dropped by 1.0 or more versus the previous month",
}


def review_cases(conn, user: UserContext, period: str, *, threshold: float,
                 department_id: int | None = None) -> pd.DataFrame:
    first, last = parse_period(period)
    att = repos.attendance_frame(conn, user, first.isoformat(), last.isoformat(), department_id)
    ev = repos.evaluations_frame(conn, user, shift_period(period, -1), period, department_id)
    cols = ["employee_id", "employee_code", "full_name", "department_name", "rule_code", "rule", "value"]
    flags = []

    if not att.empty:
        per_emp = grouped_attendance_kpis(att, "employee_id")
        names = att.drop_duplicates("employee_id").set_index("employee_id")[["employee_code", "full_name", "department_name"]]
        per_emp = per_emp.join(names, on="employee_id")
        for r in per_emp.to_dict("records"):
            base = {k: r[k] for k in ("employee_id", "employee_code", "full_name", "department_name")}
            if r["absent_days"] >= 3:
                flags.append({**base, "rule_code": "ABSENCE_3PLUS", "value": f"{r['absent_days']} absences"})
            if r["attended_days"] >= 5 and (r["late_rate"] or 0) >= 0.30:
                flags.append({**base, "rule_code": "LATE_RATE_30",
                              "value": f"{r['late_days']}/{r['attended_days']} days late"})
            if r["incomplete_days"] >= 3:
                flags.append({**base, "rule_code": "INCOMPLETE_3PLUS", "value": f"{r['incomplete_days']} days"})

    if not ev.empty:
        cur = ev[ev.period == period].set_index("employee_id")
        prev = ev[ev.period == shift_period(period, -1)].set_index("employee_id")["weighted_score"]
        for emp_id, r in cur.iterrows():
            base = {"employee_id": emp_id, "employee_code": r["employee_code"], "full_name": r["full_name"],
                    "department_name": r["department_name"]}
            if r["weighted_score"] < threshold:
                flags.append({**base, "rule_code": "SCORE_BELOW_THRESHOLD",
                              "value": f"{r['weighted_score']:.2f} < {threshold:.2f}"})
            if emp_id in prev.index and prev[emp_id] - r["weighted_score"] >= 1.0:
                flags.append({**base, "rule_code": "SCORE_DROP_1",
                              "value": f"{prev[emp_id]:.2f} -> {r['weighted_score']:.2f}"})

    df = pd.DataFrame(flags, columns=[c for c in cols if c != "rule"])
    df["rule"] = df["rule_code"].map(RULES)
    return df[cols].sort_values(["employee_code", "rule_code"]).reset_index(drop=True)
