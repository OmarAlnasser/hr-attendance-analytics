"""Command line: python -m hr_analytics <command>

Typical first run (synthetic demo):
    python -m hr_analytics demo
Individual steps:
    init-db, generate-data, seed, import-punches, process, train-model,
    report, run-monthly, export-powerbi, create-user
"""
from __future__ import annotations

import getpass
import json
import sys
from datetime import date, datetime
from pathlib import Path

import click
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

from .config import BASE_DIR, Settings

load_dotenv(BASE_DIR / ".env")


def _ctx():
    from .db.connection import connect
    s = Settings.from_env()
    s.ensure_dirs()
    return s, connect(s.db_target)


@click.group()
def cli():
    """HR Attendance & Performance Analytics System."""


@cli.command("init-db")
@click.option("--reset", is_flag=True, help="Delete the existing database file first.")
def init_db(reset):
    from .db.connection import connect, drop_all, init_schema
    s = Settings.from_env()
    s.ensure_dirs()
    if reset and not s.DATABASE_URL:
        p = Path(s.DATABASE_PATH)
        for suffix in ("", "-wal", "-shm"):
            Path(str(p) + suffix).unlink(missing_ok=True)
    conn = connect(s.db_target)
    if reset and s.DATABASE_URL:
        drop_all(conn)          # this application's tables only
    init_schema(conn)
    click.echo(f"Database ready: {s.db_label}")


@cli.command("generate-data")
@click.option("--out", default=None, help="Output folder (default data/synthetic)")
@click.option("--seed", type=int, default=None)
@click.option("--employees", type=int, default=None, help="Initial headcount (default 110)")
@click.option("--new-hires", type=int, default=None)
@click.option("--months", type=int, default=None)
@click.option("--start", default=None, help="First month, YYYY-MM-01")
def generate_data(out, seed, employees, new_hires, months, start):
    from .synthetic.generator import generate
    s = Settings.from_env()
    res = generate(out or Path(s.DATA_DIR) / "synthetic", seed=seed if seed is not None else s.SYNTHETIC_SEED,
                   start=start or s.SYNTHETIC_START, months=months or s.SYNTHETIC_MONTHS,
                   n_employees=employees or s.SYNTHETIC_EMPLOYEES,
                   n_new_hires=new_hires if new_hires is not None else s.SYNTHETIC_NEW_HIRES)
    click.echo(f"Synthetic data written to {res.out_dir}: {res.employees} employees, "
               f"{res.punch_rows:,} punch rows in {len(res.files)} files, {res.evaluations:,} evaluations.")


@cli.command("seed")
@click.option("--data-dir", default=None, help="Folder produced by generate-data")
@click.option("--with-evaluations/--no-evaluations", default=True)
def seed(data_dir, with_evaluations):
    from .services.seed import load_evaluations, load_master_data
    s, conn = _ctx()
    data_dir = data_dir or Path(s.DATA_DIR) / "synthetic"
    import os
    res = load_master_data(conn, data_dir, settings=s, demo_password=os.environ.get("HR_DEMO_PASSWORD") or None)
    click.echo(f"Loaded {res['employees']} employees and {res['users']} demo accounts.")
    if res["credentials_file"]:
        click.echo(f"Demo password written to {res['credentials_file']} (git-ignored).")
    if with_evaluations:
        ev = load_evaluations(conn, data_dir)
        click.echo(f"Evaluations saved: {ev['saved']:,}; rejected: {len(ev['failed'])}")
        for f in ev["failed"][:5]:
            click.echo(f"  - {f}")


def _import_paths(paths):
    for p in paths:
        p = Path(p)
        if p.is_dir():
            yield from sorted(x for x in p.iterdir() if x.suffix.lower() in (".csv", ".xlsx"))
        else:
            yield p


@cli.command("import-punches")
@click.argument("paths", nargs=-1, required=True)
@click.option("--tz", default=None, help="Timezone of naive timestamps (default HR_DEFAULT_DEVICE_TIMEZONE)")
@click.option("--device", default=None, help="Device name to record when the file has no device column")
@click.option("--process/--no-process", default=True, help="Rebuild daily attendance for affected dates")
def import_punches(paths, tz, device, process):
    from .pipeline.importer import import_punch_file
    from .pipeline.processor import process_attendance, range_for_batch
    s, conn = _ctx()
    lo, hi = None, None
    for p in _import_paths(paths):
        r = import_punch_file(conn, p, settings=s, source_timezone=tz, source_device=device)
        reasons = ", ".join(f"{k}={v}" for k, v in sorted(r.reject_reasons.items()))
        click.echo(f"[{r.status:>14}] {p.name}: {r.message}" + (f" ({reasons})" if reasons else ""))
        rng = (range_for_batch(r.min_punch_time, r.max_punch_time, conn, r.batch_id)
               if r.status in ("success", "partial") else None)
        if rng:
            lo = rng[0] if lo is None else min(lo, rng[0])
            hi = rng[1] if hi is None else max(hi, rng[1])
    if process and lo:
        summ = process_attendance(conn, lo, hi, settings=s)
        click.echo(f"Processed {summ.rows_written:,} employee-days {summ.start}..{summ.end}: {summ.status_counts}")
        if summ.exceptions:
            click.echo(f"Punch exceptions: {summ.exceptions}")


@cli.command("process")
@click.option("--start", required=True, type=click.DateTime(["%Y-%m-%d"]))
@click.option("--end", required=True, type=click.DateTime(["%Y-%m-%d"]))
@click.option("--as-of", type=click.DateTime(["%Y-%m-%d %H:%M", "%Y-%m-%d"]), default=None,
              help="Evaluate as if now were this time (absence is only decided after shift end)")
def process(start, end, as_of):
    from .pipeline.processor import process_attendance
    s, conn = _ctx()
    summ = process_attendance(conn, start.date(), end.date(), settings=s, as_of=as_of)
    click.echo(json.dumps(summ.__dict__, indent=2))


@cli.command("train-model")
@click.option("--test-months", default=3, show_default=True)
def train_model(test_months):
    from .ml.risk_model import score_latest, train_and_evaluate
    s, conn = _ctx()
    rep = train_and_evaluate(conn, threshold=s.LOW_SCORE_THRESHOLD, models_dir=s.MODELS_DIR, n_test_months=test_months)
    click.echo(f"Model status: {rep.status}. {rep.reason}")
    if rep.status == "model":
        m, b = rep.model_metrics, rep.baseline_metrics
        click.echo(f"Test n={m['n']}  model P/R/F1={m['precision']:.3f}/{m['recall']:.3f}/{m['f1']:.3f}  "
                   f"baseline P/R/F1={b['precision']:.3f}/{b['recall']:.3f}/{b['f1']:.3f}")
        click.echo(json.dumps(score_latest(conn, s.MODELS_DIR)))
    click.echo(f"Evaluation report: {Path(s.MODELS_DIR) / 'model_evaluation_report.md'}")


def _dept_id(conn, code):
    if not code:
        return None
    row = conn.execute("SELECT department_id FROM departments WHERE code = ?", (code.upper(),)).fetchone()
    if not row:
        raise click.BadParameter(f"Unknown department code {code}")
    return row[0]


@cli.command("report")
@click.option("--period", required=True, help="YYYY-MM")
@click.option("--department", default=None, help="Department code; omit for the whole organisation")
@click.option("--force", is_flag=True, help="Regenerate even if a successful run exists")
def report(period, department, force):
    from .reports.runner import run_monthly_report
    s, conn = _ctx()
    out = run_monthly_report(conn, period=period, department_id=_dept_id(conn, department), settings=s,
                             triggered_by="cli", force=force)
    click.echo(f"[{out.status}] {out.message} {out.output_path or ''}")
    sys.exit(0 if out.status in ("success", "skipped") else 1)


@cli.command("run-monthly")
@click.option("--period", default=None, help="Defaults to the previous calendar month")
@click.option("--all-departments", is_flag=True, help="Also produce one report per department")
def run_monthly(period, all_departments):
    """Entry point for cron / Task Scheduler. Safe to run repeatedly."""
    from .reports.runner import previous_period, run_monthly_report
    s, conn = _ctx()
    period = period or previous_period()
    scopes = [None]
    if all_departments:
        scopes += [r[0] for r in conn.execute("SELECT department_id FROM departments WHERE is_active = 1")]
    failed = 0
    for dept in scopes:
        out = run_monthly_report(conn, period=period, department_id=dept, settings=s, triggered_by="scheduler")
        failed += out.status in ("failed", "busy")
        click.echo(f"[{out.status}] {period} {'org' if dept is None else f'dept {dept}'}: {out.message}")
    sys.exit(1 if failed else 0)


@cli.command("export-powerbi")
@click.option("--out", default=None)
def export_pbi(out):
    from .exports.powerbi import export_powerbi
    s, conn = _ctx()
    files = export_powerbi(conn, out or s.EXPORTS_DIR, settings=s)
    for k, v in files.items():
        click.echo(f"{k:28s} {v:>8,} rows")


@cli.command("create-user")
@click.option("--username", required=True)
@click.option("--role", type=click.Choice(["hr", "manager", "employee"]), required=True)
@click.option("--employee-code", default=None)
def create_user(username, role, employee_code):
    from .db import repos
    from .db.connection import transaction
    s, conn = _ctx()
    emp_id = None
    if employee_code:
        row = conn.execute("SELECT employee_id FROM employees WHERE employee_code = ?", (employee_code,)).fetchone()
        if not row:
            raise click.BadParameter("Unknown employee code")
        emp_id = row[0]
    pw = getpass.getpass("Password (min 12 characters): ")
    if len(pw) < 12 or pw != getpass.getpass("Repeat: "):
        raise click.ClickException("Passwords must match and be at least 12 characters.")
    with transaction(conn):
        uid = repos.create_user(conn, username, generate_password_hash(pw, method=s.PASSWORD_HASH_METHOD), role, emp_id)
        repos.audit(conn, None, "create_user", "user", uid, {"username": username, "role": role})
    click.echo(f"User {username} created.")


@cli.command("demo")
@click.option("--employees", type=int, default=None)
@click.option("--months", type=int, default=None)
@click.pass_context
def demo(ctx, employees, months):
    """Reset the DB and run the full synthetic pipeline end to end."""
    s = Settings.from_env()
    data_dir = str(Path(s.DATA_DIR) / "synthetic")
    ctx.invoke(init_db, reset=True)
    ctx.invoke(generate_data, out=data_dir, employees=employees, months=months)
    ctx.invoke(seed, data_dir=data_dir, with_evaluations=True)
    ctx.invoke(import_punches, paths=(str(Path(data_dir) / "punches"),), tz=None, device=None, process=True)
    ctx.invoke(train_model, test_months=3)
    ctx.invoke(export_pbi, out=None)
    s2, conn = _ctx()
    from .services.seed import seed_demo_requests
    made = seed_demo_requests(conn, s2)
    click.echo(f"demo self-service requests: {made['corrections']} punch corrections, {made['leave']} leave requests "
               "(pending, see Approvals)")
    last = conn.execute("SELECT MAX(substr(shift_date,1,7)) FROM attendance_daily").fetchone()[0]
    from .reports.runner import run_monthly_report
    out = run_monthly_report(conn, period=last, department_id=None, settings=s2, triggered_by="demo", force=True)
    click.echo(f"[{out.status}] sample report: {out.output_path}")
    click.echo("Next: python -m hr_analytics.web  (then open http://127.0.0.1:5000)")


if __name__ == "__main__":
    cli()
