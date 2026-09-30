"""Save monthly performance evaluations with validation and full change history."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..db import repos
from ..db.connection import transaction
from ..domain.scoring import CATEGORIES, validate_period_for_employee, validate_scores, weighted_score
from ..security.scope import UserContext, can_evaluate


@dataclass
class SaveResult:
    ok: bool
    evaluation_id: int | None = None
    action: str | None = None
    weighted_score: float | None = None
    errors: list[str] = field(default_factory=list)


def weights_dict(row: dict) -> dict:
    return {c: float(row[f"w_{c}"]) for c in CATEGORIES}


def save_evaluation(conn, actor: UserContext, employee_id: int, period: str, scores: dict,
                    comments: str | None, today: date | None = None, remote_addr: str | None = None) -> SaveResult:
    today = today or date.today()
    if not can_evaluate(conn, actor, employee_id):
        return SaveResult(False, errors=["You are not allowed to evaluate this employee."])
    emp = repos.get_employee(conn, employee_id)
    errors = validate_period_for_employee(period, emp["hire_date"], emp["termination_date"], today)
    errors += validate_scores(scores)
    comments = (comments or "").strip()
    if len(comments) > 2000:
        errors.append("Comments must be 2000 characters or fewer.")
    weights_row = None
    if not errors:
        weights_row = repos.weights_for_period(conn, period)
        if weights_row is None:
            errors.append(f"No evaluation weights are configured for {period}. Ask HR to set them.")
    if errors:
        return SaveResult(False, errors=errors)

    clean = {c: int(str(scores[c]).strip()) for c in CATEGORIES}
    ws = weighted_score(clean, weights_dict(weights_row))
    record = {
        "employee_id": employee_id, "period": period, "evaluator_user_id": actor.user_id,
        **{f"score_{c}": clean[c] for c in CATEGORIES},
        "weights_id": weights_row["weights_id"], "weighted_score": ws, "comments": comments or None,
    }
    with transaction(conn):
        existing = repos.get_evaluation(conn, employee_id, period)
        if existing:
            repos.update_evaluation(conn, existing["evaluation_id"], record)
            eid, action = existing["evaluation_id"], "update"
            old = {k: existing[k] for k in record}
        else:
            eid, action, old = repos.insert_evaluation(conn, record), "create", None
        repos.insert_evaluation_history(conn, eid, actor.user_id, action, old, record)
        repos.audit(conn, actor.user_id, f"evaluation_{action}", "performance_evaluation", eid,
                    {"employee_id": employee_id, "period": period, "weighted_score": ws}, remote_addr)
    return SaveResult(True, eid, action, ws)
