"""Performance evaluation rules (pure functions).

Scale        integer 1-5 per category (1 = well below expectations, 5 = well above)
Weights      one percentage per category, each 0-100, total exactly 100
Weighted     sum(score_c * weight_c) / 100, so the result stays on the 1-5 scale
Snapshot     each evaluation stores the weights_id used, so later weight
             changes never rewrite historical scores
"""
from __future__ import annotations

import re
from datetime import date

from ..i18n import N_, _

CATEGORIES = ("punctuality", "communication", "task_completion", "teamwork")
CATEGORY_LABELS = {
    "punctuality": N_("Punctuality"),
    "communication": N_("Communication"),
    "task_completion": N_("Task completion"),
    "teamwork": N_("Teamwork"),
}
SCALE_MIN, SCALE_MAX = 1, 5
DEFAULT_WEIGHTS = {"punctuality": 25.0, "communication": 20.0, "task_completion": 35.0, "teamwork": 20.0}
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validate_weights(weights: dict) -> list[str]:
    errors = []
    for c in CATEGORIES:
        v = weights.get(c)
        if v is None:
            errors.append(_("Enter a weight for {category}.", category=_(CATEGORY_LABELS[c])))
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            errors.append(_("The weight for {category} must be a number.", category=_(CATEGORY_LABELS[c])))
            continue
        if not 0 <= v <= 100:
            errors.append(_("The weight for {category} must be between 0 and 100.", category=_(CATEGORY_LABELS[c])))
    if not errors:
        total = sum(float(weights[c]) for c in CATEGORIES)
        if abs(total - 100) > 0.001:
            errors.append(_("The weights must add up to 100% (they add up to {total}% now).", total=f"{total:g}"))
    return errors


def validate_scores(scores: dict) -> list[str]:
    errors = []
    for c in CATEGORIES:
        raw = scores.get(c)
        try:
            v = int(str(raw).strip())
            if str(raw).strip() != str(v):
                raise ValueError
        except (TypeError, ValueError):
            errors.append(_("The score for {category} must be a whole number from 1 to 5.", category=_(CATEGORY_LABELS[c])))
            continue
        if not SCALE_MIN <= v <= SCALE_MAX:
            errors.append(_("The score for {category} must be between 1 and 5.", category=_(CATEGORY_LABELS[c])))
    return errors


def weighted_score(scores: dict, weights: dict) -> float:
    if validate_scores(scores) or validate_weights(weights):
        raise ValueError("Invalid scores or weights")
    return round(sum(int(scores[c]) * float(weights[c]) for c in CATEGORIES) / 100.0, 4)


def parse_period(period: str) -> tuple[date, date]:
    if not isinstance(period, str) or not _PERIOD_RE.match(period):
        raise ValueError(_("The month must look like 2026-08 (year, then month)."))
    y, m = int(period[:4]), int(period[5:])
    first = date(y, m, 1)
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return first, date.fromordinal(nxt.toordinal() - 1)


def period_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def shift_period(period: str, months: int) -> str:
    y, m = int(period[:4]), int(period[5:])
    idx = y * 12 + (m - 1) + months
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def validate_period_for_employee(period: str, hire_date: str, termination_date: str | None,
                                 today: date) -> list[str]:
    try:
        first, last = parse_period(period)
    except ValueError as exc:
        return [str(exc)]
    errors = []
    if first > today:
        errors.append(_("A month that has not started yet cannot be evaluated."))
    if date.fromisoformat(hire_date) > last:
        errors.append(_("The employee had not joined yet in this month."))
    if termination_date and date.fromisoformat(termination_date) < first:
        errors.append(_("The employee had already left before this month."))
    return errors
