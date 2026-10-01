"""Flask application factory.

Security model (details in docs/production_migration.md):
* session cookie signed with HR_SECRET_KEY (from the environment, never in code)
* passwords stored as werkzeug hashes (scrypt by default)
* CSRF: a per-session token is required on every state-changing request
* authorisation is enforced in views AND in every data query (security.scope);
  menus are hidden for convenience only, never as protection
* security headers + a strict Content-Security-Policy (the UI uses no JavaScript)
"""
from __future__ import annotations

import hmac
import logging
import secrets
import warnings
from datetime import timedelta

from flask import Flask, abort, g, redirect, render_template, request, session, url_for
from markupsafe import Markup

from ..config import Settings
from ..db.connection import connect, ensure_schema
from ..domain.metrics import fmt_num, fmt_pct
from .. import labels
from ..i18n import LANGS, _, count, is_rtl, loc
from ..security.scope import AccessDenied, load_user_context

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
log = logging.getLogger("hr_analytics.web")


def get_db():
    if "db" not in g:
        g.db = connect(g.settings.db_target)
    return g.db


def csrf_token() -> str:
    tok = session.get("csrf")
    if not tok:
        tok = session["csrf"] = secrets.token_urlsafe(32)
    return tok


def csrf_field() -> Markup:
    return Markup(f'<input type="hidden" name="csrf_token" value="{csrf_token()}">')


def create_app(settings: Settings | None = None, **overrides) -> Flask:
    settings = settings or Settings.from_env(**overrides)
    settings.ensure_dirs()
    if settings.extra.get("ephemeral_secret") and not settings.TESTING:
        warnings.warn("HR_SECRET_KEY is not set; using an ephemeral random key. Sessions will not survive a "
                      "restart. Set it in .env (see .env.example).", RuntimeWarning, stacklevel=2)

    applied = ensure_schema(settings.db_target)
    if applied:
        log.warning("database upgraded in place: %s", "; ".join(applied))

    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(
        SECRET_KEY=settings.SECRET_KEY,
        SESSION_COOKIE_NAME="hr_session",
        SESSION_COOKIE_HTTPONLY=settings.SESSION_COOKIE_HTTPONLY,
        SESSION_COOKIE_SECURE=settings.SESSION_COOKIE_SECURE,
        SESSION_COOKIE_SAMESITE=settings.SESSION_COOKIE_SAMESITE,
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=settings.PERMANENT_SESSION_LIFETIME_MIN),
        MAX_CONTENT_LENGTH=settings.MAX_UPLOAD_MB * 1024 * 1024,
        TESTING=settings.TESTING,
    )
    app.extensions["hr_settings"] = settings
    if settings.BEHIND_PROXY:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)   # real client IP for the login throttle

    @app.route("/lang/<code>")
    def set_language(code: str):
        """Switch the interface language and return to the same page."""
        from .helpers import safe_next
        if code in LANGS:
            session["lang"] = code
        back = safe_next(request.args.get("next"))
        return redirect(back or url_for("dashboard.index"))

    @app.route("/healthz")
    def healthz():
        """Liveness + database check for the host (no login, no data)."""
        get_db().execute("SELECT 1").fetchone()
        return {"status": "ok", "database": "postgresql" if settings.DATABASE_URL else "sqlite"}

    @app.before_request
    def _load_context():
        g.settings = settings
        g.lang = session.get("lang") or request.accept_languages.best_match(list(LANGS)) or "en"
        g.user = None
        uid = session.get("uid")
        if uid is not None:
            g.user = load_user_context(get_db(), uid)
            if g.user is None:          # deactivated or deleted meanwhile
                session.clear()

    @app.before_request
    def _force_password_change():
        # After an HR reset the temporary password only opens the password page.
        u = g.get("user")
        if u is not None and u.must_change_password and request.endpoint not in (
                "auth.account", "auth.logout", "static"):
            from flask import flash
            flash(_("Your password was reset. Choose a new password to continue."), "info")
            return redirect(url_for("auth.account"))

    @app.before_request
    def _csrf_protect():
        if request.method in SAFE_METHODS:
            return
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        expected = session.get("csrf") or ""
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, description=_("This form has expired. Reload the page and try again."))

    @app.teardown_appcontext
    def _close_db(exc):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                "script-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if g.get("user") is not None:
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    def _error(code: int, title: str, message: str):
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(AccessDenied)
    def _denied(exc):
        log.warning("access denied: user=%s path=%s reason=%s",
                    getattr(g.get("user"), "username", None), request.path, exc)
        return _error(403, _("Not permitted"), str(exc) or _("You do not have access to this data."))

    @app.errorhandler(400)
    def _bad(exc):
        return _error(400, _("Something in the request was not right"),
                      getattr(exc, "description", "") or _("The request could not be processed."))

    @app.errorhandler(403)
    def _forbidden(exc):
        return _error(403, _("Not permitted"), getattr(exc, "description", "") or _("You do not have access to this page."))

    @app.errorhandler(404)
    def _missing(exc):
        return _error(404, _("Not found"), _("The page or record does not exist."))

    @app.errorhandler(413)
    def _too_large(exc):
        return _error(413, _("File too large"), _("Uploads are limited to {mb} MB.", mb=settings.MAX_UPLOAD_MB))

    @app.context_processor
    def _inject():
        synthetic, counts, profile = False, {"to_decide": 0, "mine": 0}, None
        if g.get("user") is not None:
            row = get_db().execute("SELECT 1 FROM employees WHERE is_synthetic = 1 LIMIT 1").fetchone()
            synthetic = row is not None
            from ..db.repos import pending_counts, user_profile
            counts = pending_counts(get_db(), g.user)
            profile = _profile_card(user_profile(get_db(), g.user.user_id))
        return {"current_user": g.get("user"), "synthetic_data": synthetic, "pending": counts, "profile": profile,
                "demo_mode": settings.DEMO_MODE, "lang": g.get("lang", "en"), "rtl": is_rtl(g.get("lang", "en"))}

    app.jinja_env.globals.update(csrf_token=csrf_token, csrf_field=csrf_field, fmt_pct=fmt_pct, fmt_num=fmt_num,
                                 _=_, count=count, loc=loc, L=labels, LANGS=LANGS)
    app.jinja_env.filters["pct"] = fmt_pct
    app.jinja_env.filters["month"] = _month_label
    app.jinja_env.filters["num"] = fmt_num
    app.jinja_env.filters["status"] = labels.status_label
    app.jinja_env.filters["leave_type"] = labels.leave_type_label
    app.jinja_env.filters["req_status"] = labels.request_status_label
    app.jinja_env.filters["punch_kind"] = labels.punch_kind_label

    from .views import register_blueprints
    register_blueprints(app)
    return app


AVATAR_COLOURS = {"gm": "#7A4E12", "hr": "#1F6F5C", "manager": "#9A6A0A", "employee": "#2F5F97"}


def _month_label(period) -> str:
    """'2026-08' -> 'Aug 2026' / 'أغسطس 2026' (anything else is shown as it is)."""
    try:
        return labels.period_label(period)
    except (ValueError, KeyError, AttributeError):
        return str(period)


def _profile_card(p: dict | None) -> dict | None:
    """Name, role and an initials picture for the account box at the bottom of the sidebar."""
    if p is None:
        return None
    name = loc(p, "full_name") or p["username"]
    if g.get("lang") == "ar" and p.get("full_name_ar"):
        initials = p["full_name_ar"].strip()[:1]                      # one Arabic letter reads cleanly
    else:
        parts = [w for w in (p.get("full_name") or p["username"]).replace("-", " ").split() if w[:1].isalpha()]
        initials = (parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else "")).upper() if parts else "?"
    return {"name": name, "initials": initials, "role": labels.role_label(p["role"], p.get("gender")),
            "title": loc(p, "job_title"), "department": loc(p, "department_name"), "username": p["username"],
            "colour": AVATAR_COLOURS.get(p["role"], "#4A5A6B")}
