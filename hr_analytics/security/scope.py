"""Authorisation rules.

These functions are pure (no Flask) so that the same rules protect the web
app, the CLI and the tests. Every data query in the web layer passes a
`UserContext` through `scope_clause()`; hiding UI elements is never relied on.

Roles
-----
hr        organisation-wide data
manager   employees whose *current* department is managed by the user
          (departments.manager_employee_id = user's employee), plus own record
employee  own record only
"""
from __future__ import annotations

from dataclasses import dataclass, field


class AccessDenied(Exception):
    pass


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
        return self.role == "hr"

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


def can_evaluate(conn, user: UserContext, employee_id: int) -> bool:
    """HR may evaluate anyone except themselves; managers their department except themselves."""
    if user.employee_id is not None and user.employee_id == employee_id:
        return False
    if user.is_hr:
        return conn.execute("SELECT 1 FROM employees WHERE employee_id = ?", (employee_id,)).fetchone() is not None
    if user.is_manager and user.managed_department_ids:
        row = conn.execute("SELECT department_id FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
        return row is not None and row["department_id"] in user.managed_department_ids
    return False


def can_approve(conn, user: UserContext, employee_id: int) -> bool:
    """Leave and correction requests: HR decides anyone's, managers their departments'. Never one's own."""
    if user.employee_id is not None and user.employee_id == employee_id:
        return False
    if user.is_hr:
        return True
    if user.is_manager and user.managed_department_ids:
        row = conn.execute("SELECT department_id FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
        return row is not None and row["department_id"] in user.managed_department_ids
    return False


def can_view_department(user: UserContext, department_id: int | None) -> bool:
    if user.is_hr:
        return True
    if department_id is None:  # organisation-wide scope
        return False
    return user.is_manager and department_id in user.managed_department_ids


def require(condition: bool, message: str = "Not permitted") -> None:
    if not condition:
        raise AccessDenied(message)
