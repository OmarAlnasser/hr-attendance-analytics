"""Shared helpers for views: access decorators, filter parsing, small SVG charts."""
from __future__ import annotations

from datetime import date
from functools import wraps
from urllib.parse import urlparse

from flask import abort, flash, g, redirect, request, url_for
from markupsafe import Markup, escape

from ..db import repos
from ..domain.scoring import parse_period, period_of
from ..i18n import _
from ..security.scope import AccessDenied, visible_department_ids
from . import get_db


# ----------------------------------------------------------------- access --

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?") if request.method == "GET" else None))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    """Server-side role check. Hiding a menu item is never the protection."""
    def deco(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            # the General Manager holds every HR power
            if g.user.role not in roles and not (g.user.is_gm and "hr" in roles):
                raise AccessDenied(_("Your role does not allow this action."))
            return view(*args, **kwargs)
        return wrapped
    return deco


def safe_next(target: str | None) -> str | None:
    """Only same-site relative paths are accepted as a post-login redirect."""
    if not target:
        return None
    p = urlparse(target)
    if p.scheme or p.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


def audit(action: str, entity: str, entity_id=None, details: dict | None = None) -> None:
    repos.audit(get_db(), g.user.user_id if g.get("user") else None, action, entity, entity_id, details,
                request.remote_addr)


# ---------------------------------------------------------------- filters --

def default_period() -> str:
    last = repos.latest_attendance_date(get_db())
    return last[:7] if last else period_of(date.today())


def get_period(arg: str = "period") -> str:
    p = (request.args.get(arg) or "").strip() or default_period()
    try:
        parse_period(p)
    except ValueError:
        abort(400, description=_("The month must look like 2026-08 (year, then month)."))
    return p


def get_department_filter() -> int | None:
    """Department filter from the query string, validated against the user's scope.

    Asking for a department outside the scope is a 403, not an empty page, so
    probing for other departments' data is visible in the logs."""
    raw = request.args.get("department_id", "").strip()
    if not raw:
        return None
    try:
        dept_id = int(raw)
    except ValueError:
        abort(400, description=_("That department does not exist."))
    allowed = visible_department_ids(get_db(), g.user)
    if allowed is not None and dept_id not in allowed:
        raise AccessDenied(_("You can only view departments you manage."))
    return dept_id


def department_options() -> list[dict]:
    allowed = visible_department_ids(get_db(), g.user)
    if allowed is not None and not allowed:
        return []
    return repos.list_departments(get_db(), allowed)


def int_arg(name: str, default: int | None = None) -> int | None:
    raw = request.values.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        abort(400, description=_("One of the values in the address is not valid."))


def records(df, limit: int | None = None) -> list[dict]:
    """DataFrame -> list of dicts with NaN/NaT turned into None (templates test for None)."""
    if df is None or len(df) == 0:
        return []
    if limit is not None:
        df = df.head(limit)
    return df.astype(object).where(df.notna(), None).to_dict("records")


def flash_errors(errors: list[str]) -> None:
    for e in errors:
        flash(e, "error")


# ----------------------------------------------------------------- charts --
# Inline SVG keeps the UI free of JavaScript (strict CSP) and prints well.

def line_chart(labels: list[str], series: list[dict], *, height: int = 170, y_min: float = 0.0,
               y_max: float = 1.0, y_fmt=lambda v: f"{v * 100:.0f}%", ticks: int = 4) -> Markup:
    """series: [{"name", "values": [float|None], "cls": css class}]"""
    width, pad_l, pad_r, pad_t, pad_b = 520, 40, 10, 10, 24
    n = len(labels)
    if n == 0:
        return Markup(f'<p class="muted">{escape(_("No data for this selection."))}</p>')
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b

    def x(i):
        return pad_l + (iw * i / (n - 1) if n > 1 else iw / 2)

    def y(v):
        return pad_t + ih - (ih * (v - y_min) / (y_max - y_min) if y_max > y_min else 0)

    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img">']
    for k in range(ticks + 1):
        v = y_min + (y_max - y_min) * k / ticks
        parts.append(f'<line class="grid" x1="{pad_l}" x2="{width - pad_r}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>')
        parts.append(f'<text class="axis" x="{pad_l - 6}" y="{y(v) + 3:.1f}" text-anchor="end">{escape(y_fmt(v))}</text>')
    step = max(1, n // 8)
    for i, lab in enumerate(labels):
        if i % step == 0 or i == n - 1:
            parts.append(f'<text class="axis" x="{x(i):.1f}" y="{height - 8}" text-anchor="middle">{escape(lab)}</text>')
    for s in series:
        pts, seg = [], []
        for i, v in enumerate(s["values"]):
            if v is None:
                if seg:
                    pts.append(seg)
                seg = []
            else:
                seg.append(f"{x(i):.1f},{y(v):.1f}")
        if seg:
            pts.append(seg)
        for seg in pts:
            if len(seg) > 1:
                parts.append(f'<polyline class="line {s["cls"]}" points="{" ".join(seg)}"/>')
        for i, v in enumerate(s["values"]):
            if v is not None:
                parts.append(f'<circle class="dot {s["cls"]}" cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.6">'
                             f'<title>{escape(s["name"])} {escape(labels[i])}: {escape(y_fmt(v))}</title></circle>')
    parts.append("</svg>")
    legend = "".join(f'<span class="key {s["cls"]}">{escape(s["name"])}</span>' for s in series)
    return Markup(f'<figure class="chart-wrap">{"".join(parts)}<figcaption class="legend">{legend}</figcaption></figure>')


def heat_class(v) -> str:
    """Attendance-rate bucket -> CSS class (colour + text label keep it readable without colour)."""
    if v is None:
        return "h-none"
    if v >= 0.98:
        return "h-5"
    if v >= 0.95:
        return "h-4"
    if v >= 0.90:
        return "h-3"
    if v >= 0.80:
        return "h-2"
    return "h-1"
