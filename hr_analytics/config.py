"""Central configuration.

Every sensitive or environment-specific value is read from environment
variables (optionally loaded from a local `.env` file that is never committed).
Nothing in this module contains real credentials.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field, fields
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    if isinstance(default, bool):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    return raw


def with_password(url: str, password: str) -> str:
    """postgresql://user@host/db + password -> postgresql://user:<encoded>@host/db (unchanged if it has one)."""
    from urllib.parse import quote
    scheme, sep, rest = url.partition("://")
    if not sep or "@" not in rest:
        return url
    userinfo, host = rest.rsplit("@", 1)
    user = userinfo.split(":", 1)[0]
    if ":" in userinfo and userinfo.split(":", 1)[1] not in ("", "[YOUR-PASSWORD]"):
        return url                                  # a real password is already there
    return f"{scheme}://{user}:{quote(password.strip(), safe='')}@{host}"


@dataclass
class Settings:
    # --- security -------------------------------------------------------
    SECRET_KEY: str = ""
    SESSION_COOKIE_SECURE: bool = False
    SESSION_COOKIE_HTTPONLY: bool = True
    SESSION_COOKIE_SAMESITE: str = "Lax"
    PERMANENT_SESSION_LIFETIME_MIN: int = 480
    MAX_UPLOAD_MB: int = 20
    PASSWORD_HASH_METHOD: str = "scrypt"   # werkzeug method string; tests use a cheaper one

    # --- storage --------------------------------------------------------
    DATABASE_PATH: str = str(BASE_DIR / "instance" / "hr_analytics.sqlite3")
    # When set (postgresql://user:pass@host:5432/db), PostgreSQL is used instead of the SQLite file.
    # DATABASE_URL (without the HR_ prefix, as set by most hosts) is also accepted.
    DATABASE_URL: str = ""
    # Optional: the password on its own, so the URL (not secret) and the password (secret) can be
    # stored separately by a host. It is URL-encoded and inserted into DATABASE_URL.
    DATABASE_PASSWORD: str = ""
    INSTANCE_DIR: str = str(BASE_DIR / "instance")
    DATA_DIR: str = str(BASE_DIR / "data")
    REPORTS_DIR: str = str(BASE_DIR / "output" / "reports")
    EXPORTS_DIR: str = str(BASE_DIR / "output" / "powerbi")
    MODELS_DIR: str = str(BASE_DIR / "output" / "models")
    UPLOAD_DIR: str = str(BASE_DIR / "instance" / "uploads")

    # --- time -----------------------------------------------------------
    ORG_TIMEZONE: str = "Asia/Riyadh"
    DEFAULT_DEVICE_TIMEZONE: str = "Asia/Riyadh"

    # --- attendance rules (see docs/metrics_definitions.md) --------------
    PUNCH_DEBOUNCE_MINUTES: int = 2
    WINDOW_BEFORE_START_MIN: int = 240
    WINDOW_AFTER_END_MIN: int = 360
    LATE_MINUTES_FROM: str = "start"  # "start" or "grace_end"
    RULE_VERSION: str = "attendance-rules-1.0"

    # --- performance / review -------------------------------------------
    LOW_SCORE_THRESHOLD: float = 3.0
    SMALL_SAMPLE_EMPLOYEES: int = 5

    # --- demo ------------------------------------------------------------
    SYNTHETIC_SEED: int = 42
    SYNTHETIC_START: str = "2025-09-01"
    SYNTHETIC_MONTHS: int = 12
    SYNTHETIC_EMPLOYEES: int = 110
    SYNTHETIC_NEW_HIRES: int = 10

    # --- public demo / hosting (see docs/deployment.md) -------------------
    # DEMO_MODE shows one-click "Explore as ..." buttons on the login page and
    # protects those showcase accounts from being changed by visitors.
    # Never enable it on a database with real people in it: the buttons skip passwords
    # (they also refuse to work for any employee not flagged synthetic).
    DEMO_MODE: bool = False
    DEMO_ACCOUNTS: str = "e0101,e0001,e0060"          # HR, department manager, employee
    DEMO_RESET_NOTE: str = "Everything you change is reset every night."
    BEHIND_PROXY: bool = False                          # trust one proxy's X-Forwarded-For/Proto (Render, Railway...)

    TESTING: bool = False
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        values = {}
        for f in fields(cls):
            if f.name == "extra":
                continue
            values[f.name] = _env(f"HR_{f.name}", f.default)
        values.update({k: v for k, v in overrides.items() if k in values})
        if not values.get("DATABASE_URL") and os.environ.get("DATABASE_URL") and "DATABASE_URL" not in overrides:
            values["DATABASE_URL"] = os.environ["DATABASE_URL"]
        if values.get("DATABASE_URL") and values.get("DATABASE_PASSWORD"):
            values["DATABASE_URL"] = with_password(values["DATABASE_URL"], values["DATABASE_PASSWORD"])
        settings = cls(**values)
        if not settings.SECRET_KEY:
            # The web app warns about this at start-up (see web.create_app).
            settings.SECRET_KEY = secrets.token_hex(32)
            settings.extra["ephemeral_secret"] = True
        if settings.LATE_MINUTES_FROM not in {"start", "grace_end"}:
            raise ValueError("HR_LATE_MINUTES_FROM must be 'start' or 'grace_end'")
        return settings

    @property
    def demo_usernames(self) -> list[str]:
        return [u.strip().lower() for u in self.DEMO_ACCOUNTS.split(",") if u.strip()] if self.DEMO_MODE else []

    def is_protected_demo_account(self, username: str | None) -> bool:
        return bool(username) and username.lower() in self.demo_usernames

    @property
    def db_target(self) -> str:
        """What connect() receives: the PostgreSQL URL if configured, else the SQLite file path."""
        return self.DATABASE_URL or self.DATABASE_PATH

    @property
    def db_label(self) -> str:
        if self.DATABASE_URL:
            host = self.DATABASE_URL.split("@")[-1].split("/")[0].split("?")[0]
            return f"PostgreSQL at {host}"          # never print the password
        return f"SQLite file {self.DATABASE_PATH}"

    def ensure_dirs(self) -> None:
        for p in (self.INSTANCE_DIR, self.REPORTS_DIR, self.EXPORTS_DIR,
                  self.MODELS_DIR, self.UPLOAD_DIR):
            Path(p).mkdir(parents=True, exist_ok=True)
        Path(self.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
        (Path(self.REPORTS_DIR).parent / "logs").mkdir(parents=True, exist_ok=True)
