"""Attendance file import (HR only), validation results, and re-processing."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path
from zoneinfo import available_timezones

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from ...db import repos
from ...pipeline.importer import import_punch_file
from ...pipeline.processor import process_attendance, range_for_batch
from .. import get_db
from ..helpers import roles_required

bp = Blueprint("imports", __name__, url_prefix="/imports")
ALLOWED = {".csv", ".xlsx"}
COMMON_TZ = ["Asia/Riyadh", "UTC", "Asia/Dubai", "Asia/Kuwait", "Asia/Bahrain", "Asia/Qatar", "Africa/Cairo",
             "Europe/London"]


@bp.route("/", methods=["GET"])
@roles_required("hr")
def index():
    return render_template("imports.html", batches=repos.list_batches(get_db(), 60), timezones=COMMON_TZ,
                           default_tz=g.settings.DEFAULT_DEVICE_TIMEZONE)


@bp.route("/upload", methods=["POST"])
@roles_required("hr")
def upload():
    f = request.files.get("file")
    if f is None or not f.filename:
        flash("Choose a CSV or Excel file.", "error")
        return redirect(url_for("imports.index"))
    name = secure_filename(f.filename) or "upload"
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED:
        flash("Only .csv and .xlsx files are accepted.", "error")
        return redirect(url_for("imports.index"))
    tz = (request.form.get("timezone") or g.settings.DEFAULT_DEVICE_TIMEZONE).strip()
    if tz not in available_timezones():
        flash(f"Unknown timezone '{tz}'.", "error")
        return redirect(url_for("imports.index"))
    device = (request.form.get("device") or "").strip()[:40] or None
    conn = get_db()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        f.save(path)
        res = import_punch_file(conn, path, settings=g.settings, imported_by_user_id=g.user.user_id,
                                source_timezone=tz, source_device=device, original_name=f.filename[:200])
    if res.status == "duplicate_file":
        flash(res.message, "info")
        return redirect(url_for("imports.index"))
    if res.status == "failed" and res.batch_id is None:
        flash(res.message, "error")
        return redirect(url_for("imports.index"))
    rng = range_for_batch(res.min_punch_time, res.max_punch_time, conn, res.batch_id)
    if rng and res.rows_accepted > 0:
        summ = process_attendance(conn, rng[0], min(rng[1], date.today()), settings=g.settings,
                                  user_id=g.user.user_id)
        flash(f"Imported: {res.message} Attendance processed for {summ.start} to {summ.end} "
              f"({summ.rows_written:,} employee-days).", "success" if res.status == "success" else "warning")
    else:
        flash(f"{res.message} Nothing new to process.", "warning" if res.rows_rejected else "info")
    return redirect(url_for("imports.detail", batch_id=res.batch_id))


@bp.route("/<int:batch_id>")
@roles_required("hr")
def detail(batch_id: int):
    conn = get_db()
    b = repos.get_batch(conn, batch_id)
    if b is None:
        abort(404)
    return render_template("import_detail.html", b=b, rejects=repos.batch_rejects(conn, batch_id, 500),
                           reasons=repos.reject_summary(conn, [batch_id]))


@bp.route("/reprocess", methods=["POST"])
@roles_required("hr")
def reprocess():
    try:
        start = date.fromisoformat(request.form.get("start", ""))
        end = date.fromisoformat(request.form.get("end", ""))
    except ValueError:
        flash("Start and end must be dates (YYYY-MM-DD).", "error")
        return redirect(url_for("imports.index"))
    if end < start or (end - start).days > 400:
        flash("Choose a range of 1 to 400 days.", "error")
        return redirect(url_for("imports.index"))
    summ = process_attendance(get_db(), start, min(end, date.today()), settings=g.settings, user_id=g.user.user_id)
    flash(f"Re-processed {summ.rows_written:,} employee-days ({summ.start} to {summ.end}). "
          f"Statuses: {', '.join(f'{k} {v:,}' for k, v in sorted(summ.status_counts.items()))}.", "success")
    return redirect(url_for("imports.index"))
