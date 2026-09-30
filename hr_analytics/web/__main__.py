"""Development server: python -m hr_analytics.web

For anything beyond local use run a WSGI server instead, e.g.
    waitress-serve --call hr_analytics.web:create_app      (Windows/Linux)
    gunicorn "hr_analytics.web:create_app()"                (Linux)
behind HTTPS with HR_SESSION_COOKIE_SECURE=1 (see docs/production_migration.md).
"""
import os

from dotenv import load_dotenv

from ..config import BASE_DIR

load_dotenv(BASE_DIR / ".env")

from . import create_app  # noqa: E402

if __name__ == "__main__":
    app = create_app()
    host = os.environ.get("HR_HOST", "127.0.0.1")
    port = int(os.environ.get("HR_PORT", "5000"))
    print(f"HR Analytics running on http://{host}:{port}  (Ctrl+C to stop)")
    app.run(host=host, port=port, debug=False)
