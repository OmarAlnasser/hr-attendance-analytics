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

from flask import Flask, abort, g, render_template, request, session
from markupsafe import Markup

from ..config import Settings
from ..db.connection import connect, ensure_schema
from ..domain.metrics import fmt_num, fmt_pct
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

    @app.route("/healthz")
    def healthz():
        """Liveness + database check for the host (no login, no data)."""
        get_db().execute("SELECT 1").fetchone()
        return {"status": "ok", "database": "postgresql" if settings.DATABASE_URL else "sqlite"}

    @app.before_request
    def _load_context():
        g.settings = settings
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
            from flask import flash, redirect, url_for
            flash("Your password was reset by HR. Choose a new password to continue.", "info")
            return redirect(url_for("auth.account"))

    @app.before_request
    def _csrf_protect():
        if request.method in SAFE_METHODS:
            return
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
        expected = session.get("csrf") or ""
        if not expected or not hmac.compare_digest(sent, expected):
            abort(400, description="Missing or invalid CSRF token. Reload the page and try again.")

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
        return _error(403, "Not permitted", str(exc) or "You do not have access to this data.")

    @app.errorhandler(400)
    def _bad(exc):
        return _error(400, "Bad request", getattr(exc, "description", "") or "The request could not be processed.")

    @app.errorhandler(403)
    def _forbidden(exc):
        return _error(403, "Not permitted", getattr(exc, "description", "") or "You do not have access to this page.")

    @app.errorhandler(404)
    def _missing(exc):
        return _error(404, "Not found", "The page or record does not exist.")

    @app.errorhandler(413)
    def _too_large(exc):
        return _error(413, "File too large", f"Uploads are limited to {settings.MAX_UPLOAD_MB} MB.")

    @app.context_processor
    def _inject():
        synthetic, counts = False, {"to_decide": 0, "mine": 0}
        if g.get("user") is not None:
            row = get_db().execute("SELECT 1 FROM employees WHERE is_synthetic = 1 LIMIT 1").fetchone()
            synthetic = row is not None
            from ..db.repos import pending_counts
            counts = pending_counts(get_db(), g.user)
        return {"current_user": g.get("user"), "synthetic_data": synthetic, "pending": counts,
                "demo_mode": settings.DEMO_MODE, "demo_note": settings.DEMO_RESET_NOTE}

    app.jinja_env.globals.update(csrf_token=csrf_token, csrf_field=csrf_field, fmt_pct=fmt_pct, fmt_num=fmt_num)
    app.jinja_env.filters["pct"] = fmt_pct
    app.jinja_env.filters["num"] = fmt_num

    from .views import register_blueprints
    register_blueprints(app)
    return app
