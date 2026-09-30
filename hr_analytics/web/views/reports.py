"""Monthly PDF reports: generate and download with server-side scope checks."""
from __future__ import annotations

import io

from pathlib import Path

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for

from ...db import repos
from ...domain.scoring import parse_period
from ...reports.runner import list_runs, previous_period, run_monthly_report, scope_key
from ...security.scope import AccessDenied, can_view_department
from .. import get_db
from ..helpers import audit, department_options, roles_required

bp = Blueprint("reports", __name__, url_prefix="/reports")


def allowed_scope_keys() -> list[str] | None:
    """None = everything (HR)."""
    if g.user.is_hr:
        return None
    return [scope_key(d) for d in sorted(g.user.managed_department_ids)]


@bp.route("/")
@roles_required("hr", "manager")
def index():
    conn = get_db()
    runs = list_runs(conn, allowed_scope_keys(), 100)
    depts = {d["department_id"]: d["name"] for d in repos.list_departments(conn)}
    stored = repos.stored_paths(conn, "reports/")
    for r in runs:
        r["scope_label"] = "All departments" if r["scope_key"] == "org" else depts.get(
            int(r["scope_key"].split(":")[1]), r["scope_key"])
        r["file_exists"] = bool(r["output_path"]) and (Path(r["output_path"]).exists()
                                                       or "reports/" + Path(r["output_path"]).name in stored)
    return render_template("reports.html", runs=runs, departments=department_options(),
                           default_period=previous_period())


@bp.route("/generate", methods=["POST"])
@roles_required("hr", "manager")
def generate():
    period = (request.form.get("period") or "").strip()
    try:
        parse_period(period)
    except ValueError:
        flash("Period must look like YYYY-MM.", "error")
        return redirect(url_for("reports.index"))
    raw = (request.form.get("department_id") or "").strip()
    dept = int(raw) if raw.isdigit() else None
    if not can_view_department(g.user, dept):
        raise AccessDenied("Managers can only generate reports for the departments they manage.")
    force = request.form.get("force") == "1"
    out = run_monthly_report(get_db(), period=period, department_id=dept, settings=g.settings,
                             triggered_by=f"web:{g.user.username}", force=force)
    audit("report_" + out.status, "report_run", out.run_id, {"period": period, "department_id": dept,
                                                            "force": force})
    get_db().commit()
    level = {"success": "success", "skipped": "info", "busy": "warning", "failed": "error"}[out.status]
    flash(out.message, level)
    return redirect(url_for("reports.index"))


@bp.route("/<int:run_id>/download")
@roles_required("hr", "manager")
def download(run_id: int):
    run = repos.get_run(get_db(), run_id)
    if run is None or run["status"] not in ("success", "superseded"):
        abort(404)
    keys = allowed_scope_keys()
    if keys is not None and run["scope_key"] not in keys:
        raise AccessDenied("This report is outside your scope.")
    path = Path(run["output_path"] or "")
    reports_dir = Path(g.settings.REPORTS_DIR).resolve()
    on_disk = path.exists() and reports_dir in path.resolve().parents
    content = None if on_disk else repos.load_file(get_db(), "reports/" + path.name)
    if not on_disk and content is None:
        abort(404)
    audit("report_download", "report_run", run_id)
    get_db().commit()
    if on_disk:
        return send_file(path, mimetype="application/pdf", as_attachment=True, download_name=path.name)
    return send_file(io.BytesIO(content), mimetype="application/pdf", as_attachment=True, download_name=path.name)
