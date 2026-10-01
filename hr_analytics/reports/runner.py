"""Run a report once per (type, period, scope) and log the outcome.

* A unique partial index on report_runs(report_type, period, scope_key) for
  status IN ('running','success') makes a second concurrent or repeated run
  fail fast instead of producing a duplicate.
* `force=True` marks the previous successful run as 'superseded' and creates
  a new one (used when data for a period was corrected).
* Failures are logged with the error text and can be retried.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ..db import repos
from ..db.connection import IntegrityError, now_str, transaction
from ..domain.scoring import period_of, shift_period
from .monthly import build_monthly_report

REPORT_TYPE = "monthly_hr"           # English; the Arabic edition is "monthly_hr_ar"


def report_type_for(lang: str) -> str:
    return REPORT_TYPE + ("_ar" if lang == "ar" else "")


def report_language(report_type: str | None) -> str:
    return "ar" if (report_type or "").endswith("_ar") else "en"


@dataclass
class RunOutcome:
    status: str          # success | skipped | failed | busy
    run_id: int | None
    output_path: str | None
    message: str


def scope_key(department_id: int | None) -> str:
    return f"dept:{department_id}" if department_id else "org"


def previous_period(today: date | None = None) -> str:
    return shift_period(period_of(today or date.today()), -1)


def run_monthly_report(conn, *, period: str, department_id: int | None, settings, triggered_by: str,
                       force: bool = False, lang: str = "en") -> RunOutcome:
    key = scope_key(department_id)
    rtype = report_type_for(lang)
    existing = conn.execute("""SELECT * FROM report_runs WHERE report_type = ? AND period = ? AND scope_key = ?
                               AND status IN ('running', 'success')""", (rtype, period, key)).fetchone()
    if existing and existing["status"] == "running":
        return RunOutcome("busy", existing["run_id"], None, "A run for this report is already in progress.")
    if existing and not force and existing["output_path"] and (
            Path(existing["output_path"]).exists()
            or repos.load_file(conn, "reports/" + Path(existing["output_path"]).name) is not None):
        return RunOutcome("skipped", existing["run_id"], existing["output_path"],
                          f"Report already generated on {existing['finished_at']}. Use force to regenerate.")
    try:
        with transaction(conn):
            if existing:
                conn.execute("UPDATE report_runs SET status = 'superseded' WHERE run_id = ?", (existing["run_id"],))
            cur = conn.execute("""INSERT INTO report_runs(report_type, period, scope_key, status, triggered_by, started_at)
                                  VALUES (?,?,?,?,?,?)""", (rtype, period, key, "running", triggered_by, now_str()))
            run_id = cur.lastrowid
    except IntegrityError:
        return RunOutcome("busy", None, None, "Another run started at the same time.")

    suffix = "_ar" if lang == "ar" else ""
    out = Path(settings.REPORTS_DIR) / f"hr_monthly_{period}_{key.replace(':', '-')}{suffix}_run{run_id}.pdf"
    try:
        build_monthly_report(conn, period=period, department_id=department_id, settings=settings, out_path=out,
                             lang=lang)
    except Exception as exc:  # noqa: BLE001 - logged and surfaced
        with transaction(conn):
            conn.execute("UPDATE report_runs SET status='failed', finished_at=?, error=? WHERE run_id=?",
                         (now_str(), f"{exc}\n{traceback.format_exc(limit=3)}", run_id))
        return RunOutcome("failed", run_id, None, f"Report failed: {exc}")
    with transaction(conn):
        conn.execute("UPDATE report_runs SET status='success', finished_at=?, output_path=? WHERE run_id=?",
                     (now_str(), str(out), run_id))
        repos.save_file(conn, "reports/" + out.name, out.read_bytes(), "application/pdf")
    return RunOutcome("success", run_id, str(out), "Report generated.")


def list_runs(conn, scope_keys: list[str] | None = None, limit: int = 100) -> list[dict]:
    sql = "SELECT * FROM report_runs"
    params: list = []
    if scope_keys is not None:
        if not scope_keys:
            return []
        sql += f" WHERE scope_key IN ({','.join('?' * len(scope_keys))})"
        params = list(scope_keys)
    return [dict(r) for r in conn.execute(sql + " ORDER BY run_id DESC LIMIT ?", (*params, limit))]
