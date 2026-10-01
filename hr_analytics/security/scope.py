"""Authorisation rules.

These functions are pure (no Flask) so that the same rules protect the web
app, the CLI and the tests. Every data query in the web layer passes a
`UserContext` through `scope_clause()`; hiding UI elements is never relied on.

Roles (highest first)
---------------------
gm        General Manager. Everything HR can do, plus the decisions HR must not
          take about its own people: granting or removing HR access, managing
          HR accounts, deciding HR staff's requests and evaluating HR staff.
hr        organisation-wide data and administration, except over HR/GM accounts
manager   employees whose *current* department is managed by the user
          (departments.manager_employee_id = user's employee), plus own record
employee  own record only

Nobody approves or evaluates their own record. The General Manager's own
requests are recorded as approved (there is no one above to decide them).
"""
from __future__ import annotations

from dataclasses import dataclass, field


class AccessDenied(Exception):
    pass


ORG_WIDE_ROLES = frozenset({"gm", "hr"})      # see the whole organisation
SENIOR_ROLES = frozenset({"gm", "hr"})        # accounts that only the General Manager may decide about


@dataclass(frozen=True)
class UserContext:
    user_id: int
    username: str
    role: str
    employee_id: int | None
    managed_department_ids: frozenset = field(default_factory=frozenset)
    must_change_password: bool = False

    @property
    def is_hr(self) -> bool:
        """Organisation-wide access (HR, and the General Manager who has every HR power)."""
        return self.role in ORG_WIDE_ROLES

    @property
    def is_gm(self) -> bool:
        return self.role == "gm"

    @property
    def has_team(self) -> bool:
        """Sees other people's data: General Manager, HR, department managers."""
        return self.role in ("gm", "hr", "manager")

    @property
    def is_manager(self) -> bool:
        return self.role == "manager"


def load_user_context(conn, user_id: int) -> UserContext | None:
    row = conn.execute(
        "SELECT user_id, username, role, employee_id, is_active, must_change_password FROM users WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None or not row["is_active"]:
        return None
    managed = frozenset()
    if row["role"] == "manager" and row["employee_id"] is not None:
        managed = frozenset(
            r[0] for r in conn.execute(
                "SELECT department_id FROM departments WHERE manager_employee_id = ?",
                (row["employee_id"],),
            )
        )
    return UserContext(row["user_id"], row["username"], row["role"], row["employee_id"], managed,
                       bool(row["must_change_password"]))


def scope_clause(user: UserContext, emp_alias: str = "e") -> tuple[str, list]:
    """SQL predicate restricting rows to employees the user may see.

    The query must join `employees` under `emp_alias`.
    """
    if user.is_hr:
        return "1=1", []
    if user.is_manager and user.managed_department_ids:
        ids = sorted(user.managed_department_ids)
        marks = ",".join("?" for _ in ids)
        own = f" OR {emp_alias}.employee_id = ?" if user.employee_id else ""
        params = list(ids) + ([user.employee_id] if user.employee_id else [])
        return f"({emp_alias}.department_id IN ({marks}){own})", params
    if user.employee_id is not None:
        return f"{emp_alias}.employee_id = ?", [user.employee_id]
    return "1=0", []  # account not linked to an employee: sees nothing


def visible_department_ids(conn, user: UserContext) -> set[int] | None:
    """None means 'all departments'."""
    if user.is_hr:
        return None
    if user.is_manager:
        return set(user.managed_department_ids)
    return set()


def can_view_employee(conn, user: UserContext, employee_id: int) -> bool:
    clause, params = scope_clause(user, "e")
    row = conn.execute(
        f"SELECT 1 FROM employees e WHERE e.employee_id = ? AND {clause}",
        [employee_id, *params],
    ).fetchone()
    return row is not None


def _target_role(conn, employee_id: int) -> str | None:
    r = conn.execute("SELECT role FROM users WHERE employee_id = ?", (employee_id,)).fetchone()
    return r[0] if r else None


def _decides_about(conn, user: UserContext, employee_id: int) -> bool:
    """Shared rule for evaluations and requests: the General Manager decides about anyone;
    HR about anyone except HR/GM accounts; managers about their department. Never oneself."""
    if user.employee_id is not None and user.employee_id == employee_id:
        return False
    row = conn.execute("SELECT department_id FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
    if row is None:
        return False
    if user.is_gm:
        return True
    if _target_role(conn, employee_id) in SENIOR_ROLES:
        return False
    if user.is_hr:
        return True
    return user.is_manager and row["department_id"] in user.managed_department_ids


def can_evaluate(conn, user: UserContext, employee_id: int) -> bool:
    return _decides_about(conn, user, employee_id)


def can_approve(conn, user: UserContext, employee_id: int) -> bool:
    """Leave and correction requests follow the same rule as evaluations."""
    return _decides_about(conn, user, employee_id)


def can_manage_account(user: UserContext, target_user_id: int, target_role: str) -> bool:
    """Account administration: the General Manager manages every account but his own;
    HR manages manager and employee accounts only."""
    if target_user_id == user.user_id:
        return False
    if user.is_gm:
        return True
    return user.is_hr and target_role not in SENIOR_ROLES


def can_view_department(user: UserContext, department_id: int | None) -> bool:
    if user.is_hr:
        return True
    if department_id is None:  # organisation-wide scope
        return False
    return user.is_manager and department_id in user.managed_department_ids


def require(condition: bool, message: str = "Not permitted") -> None:
    if not condition:
        raise AccessDenied(message)
