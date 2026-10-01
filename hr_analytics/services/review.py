"""Cases that need a human review.

These are transparent RULES, not predictions. A flag means "worth a
conversation", never an automatic consequence. Thresholds are deliberately
simple so an HR reviewer can verify each flag from the raw numbers.

Each flag keeps its numbers in `facts`; the wording (rule title, the short
sentence with the evidence) comes from labels.py in the page language.
"""
from __future__ import annotations

import pandas as pd

from ..db import repos
from ..domain.metrics import grouped_attendance_kpis
from ..domain.scoring import parse_period, shift_period
from ..labels import RULES as RULE_TEXT
from ..labels import rule_description, rule_evidence, rule_title
from ..security.scope import UserContext

RULE_CODES = list(RULE_TEXT)
# English description per rule code (kept for the Power BI export and older callers)
RULES = {code: RULE_TEXT[code][1][0] for code in RULE_CODES}
NAME_COLS = ["employee_id", "employee_code", "full_name", "full_name_ar", "department_name", "department_name_ar"]


def rules_for_display() -> list[tuple[str, str, str]]:
    """(code, title, description) in the current language."""
    return [(c, rule_title(c), rule_description(c)) for c in RULE_CODES]


def review_cases(conn, user: UserContext, period: str, *, threshold: float,
                 department_id: int | None = None) -> pd.DataFrame:
    first, last = parse_period(period)
    att = repos.attendance_frame(conn, user, first.isoformat(), last.isoformat(), department_id)
    ev = repos.evaluations_frame(conn, user, shift_period(period, -1), period, department_id)
    flags = []

    if not att.empty:
        per_emp = grouped_attendance_kpis(att, "employee_id")
        names = att.drop_duplicates("employee_id").set_index("employee_id")[NAME_COLS[1:]]
        per_emp = per_emp.join(names, on="employee_id")
        for r in per_emp.to_dict("records"):
            base = {k: r[k] for k in NAME_COLS}
            if r["absent_days"] >= 3:
                flags.append({**base, "rule_code": "ABSENCE_3PLUS", "facts": {"n": r["absent_days"]}})
            if r["attended_days"] >= 5 and (r["late_rate"] or 0) >= 0.30:
                flags.append({**base, "rule_code": "LATE_RATE_30",
                              "facts": {"n": r["late_days"], "of": r["attended_days"]}})
            if r["incomplete_days"] >= 3:
                flags.append({**base, "rule_code": "INCOMPLETE_3PLUS", "facts": {"n": r["incomplete_days"]}})

    if not ev.empty:
        cur = ev[ev.period == period].set_index("employee_id")
        prev = ev[ev.period == shift_period(period, -1)].set_index("employee_id")["weighted_score"]
        for emp_id, r in cur.iterrows():
            base = {"employee_id": emp_id, **{k: r[k] for k in NAME_COLS[1:]}}
            if r["weighted_score"] < threshold:
                flags.append({**base, "rule_code": "SCORE_BELOW_THRESHOLD",
                              "facts": {"score": float(r["weighted_score"]), "threshold": float(threshold)}})
            if emp_id in prev.index and prev[emp_id] - r["weighted_score"] >= 1.0:
                flags.append({**base, "rule_code": "SCORE_DROP_1",
                              "facts": {"previous": float(prev[emp_id]), "score": float(r["weighted_score"])}})

    cols = NAME_COLS + ["rule_code", "rule", "value", "facts"]
    df = pd.DataFrame(flags, columns=[c for c in cols if c not in ("rule", "value")])
    df["rule"] = [rule_title(c) for c in df["rule_code"]]
    df["value"] = [rule_evidence(c, f) for c, f in zip(df["rule_code"], df["facts"])]
    return df[cols].sort_values(["employee_code", "rule_code"]).reset_index(drop=True)
