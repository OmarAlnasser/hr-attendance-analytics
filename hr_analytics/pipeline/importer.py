"""Import time-clock exports (CSV or Excel) into raw_punches.

Guarantees
----------
* Provenance: every stored punch keeps batch_id, source row and the raw value.
* Quarantine: invalid rows go to rejected_rows with a reason code + detail.
* Idempotency (two layers):
    1. a file whose SHA-256 was already loaded successfully is not loaded again;
    2. raw_punches has UNIQUE(employee_id, punch_time_local, device_id), so an
       overlapping export from the same device cannot duplicate punches.
* Time zones: values with an explicit offset (e.g. ...Z, +03:00) are converted
  to ORG_TIMEZONE; naive values are interpreted in the batch's source timezone.

Reason codes
------------
MISSING_BADGE, UNKNOWN_BADGE, MISSING_TIMESTAMP, INVALID_TIMESTAMP,
FUTURE_TIMESTAMP, TIMESTAMP_TOO_OLD, DUPLICATE_IN_FILE is *not* a rejection:
exact duplicates are counted in rows_duplicate.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from ..db import repos
from ..db.connection import now_str, transaction

REQUIRED = ("badge_id", "punch_time")
ALIASES = {
    "badge": "badge_id", "badge_no": "badge_id", "badgeid": "badge_id", "card_no": "badge_id",
    "employee_badge": "badge_id", "user_id": "badge_id",
    "timestamp": "punch_time", "datetime": "punch_time", "date_time": "punch_time", "time": "punch_time",
    "device": "device_id", "terminal": "device_id", "terminal_id": "device_id",
    "type": "punch_type", "direction": "punch_type", "state": "punch_type",
}
MIN_VALID_DATE = datetime(2000, 1, 1)


@dataclass
class ImportResult:
    batch_id: int | None
    status: str                      # success | partial | failed | duplicate_file
    rows_total: int = 0
    rows_accepted: int = 0
    rows_duplicate: int = 0
    rows_rejected: int = 0
    min_punch_time: str | None = None
    max_punch_time: str | None = None
    message: str = ""
    reject_reasons: dict = field(default_factory=dict)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalise_header(name) -> str:
    key = str(name).strip().lower().replace(" ", "_").replace("-", "_")
    return ALIASES.get(key, key)


def read_source(path: Path) -> tuple[pd.DataFrame, str]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
        kind = "csv"
    elif suffix in (".xlsx", ".xlsm"):
        df = pd.read_excel(path, dtype=str, keep_default_na=False, engine="openpyxl")
        kind = "excel"
    else:
        raise ValueError(f"Unsupported file type '{suffix}'. Use .csv or .xlsx")
    df.columns = [_normalise_header(c) for c in df.columns]
    return df, kind


def parse_timestamp(value: str, source_tz: ZoneInfo, org_tz: ZoneInfo) -> datetime:
    """ISO-8601 only (no ambiguous dd/mm vs mm/dd). Returns naive org-local time."""
    text = str(value).strip()
    if not text:
        raise ValueError("empty")
    if ":" not in text:
        raise ValueError("a time of day is required")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=source_tz)
    return dt.astimezone(org_tz).replace(tzinfo=None, microsecond=0)


def import_punch_file(conn, path: str | Path, *, settings, imported_by_user_id: int | None = None,
                      source_timezone: str | None = None, source_device: str | None = None,
                      original_name: str | None = None, as_of: datetime | None = None,
                      keep_copy: bool = True) -> ImportResult:
    path = Path(path)
    original_name = original_name or path.name
    source_timezone = source_timezone or settings.DEFAULT_DEVICE_TIMEZONE
    try:
        src_tz, org_tz = ZoneInfo(source_timezone), ZoneInfo(settings.ORG_TIMEZONE)
    except ZoneInfoNotFoundError:
        return ImportResult(None, "failed", message=f"Unknown timezone '{source_timezone}'")
    as_of = as_of or datetime.now(org_tz).replace(tzinfo=None)
    digest = sha256_of(path)

    existing = repos.find_loaded_batch_by_hash(conn, digest)
    if existing:
        return ImportResult(existing["batch_id"], "duplicate_file",
                            message=f"This exact file was already imported as batch #{existing['batch_id']} "
                                    f"on {existing['imported_at']}. Nothing was added.")

    base_batch = {
        "source_name": original_name, "source_device": source_device, "source_timezone": source_timezone,
        "file_sha256": digest, "imported_by_user_id": imported_by_user_id, "imported_at": now_str(),
    }

    try:
        df, kind = read_source(path)
    except Exception as exc:  # noqa: BLE001 - any read error fails the batch with a message
        with transaction(conn):
            bid = repos.insert_batch(conn, {**base_batch, "source_type": path.suffix.lstrip("."),
                                            "status": "failed", "message": f"Could not read file: {exc}"})
        return ImportResult(bid, "failed", message=f"Could not read file: {exc}")

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        msg = (f"Missing required column(s): {', '.join(missing)}. "
               f"Found: {', '.join(df.columns)}. Required: badge_id, punch_time.")
        with transaction(conn):
            bid = repos.insert_batch(conn, {**base_batch, "source_type": kind, "status": "failed",
                                            "rows_total": len(df), "message": msg})
        return ImportResult(bid, "failed", rows_total=len(df), message=msg)

    for opt in ("device_id", "punch_type"):
        if opt not in df.columns:
            df[opt] = ""

    badges = repos.badge_map(conn)
    max_allowed = as_of + timedelta(minutes=5)   # tolerate small clock drift
    accepted, rejects, seen = [], [], set()
    in_file_dupes = 0
    reasons: dict[str, int] = {}

    def reject(row_no, row, code, detail):
        reasons[code] = reasons.get(code, 0) + 1
        rejects.append((row_no, json.dumps(row, ensure_ascii=False), code, detail))

    for idx, row in enumerate(df.to_dict("records"), start=1):
        badge = str(row.get("badge_id", "")).strip()
        raw_ts = str(row.get("punch_time", "")).strip()
        device = str(row.get("device_id", "")).strip() or (source_device or "")
        ptype = str(row.get("punch_type", "")).strip().upper()
        ptype = ptype if ptype in ("IN", "OUT") else "UNKNOWN"
        if not badge:
            reject(idx, row, "MISSING_BADGE", "badge_id is empty"); continue
        if not raw_ts:
            reject(idx, row, "MISSING_TIMESTAMP", "punch_time is empty"); continue
        try:
            local = parse_timestamp(raw_ts, src_tz, org_tz)
        except (ValueError, TypeError):
            reject(idx, row, "INVALID_TIMESTAMP", f"'{raw_ts}' is not ISO-8601 (YYYY-MM-DD HH:MM[:SS][+HH:MM])"); continue
        if local > max_allowed:
            reject(idx, row, "FUTURE_TIMESTAMP", f"{local} is after the import time {as_of:%Y-%m-%d %H:%M}"); continue
        if local < MIN_VALID_DATE:
            reject(idx, row, "TIMESTAMP_TOO_OLD", f"{local} is before {MIN_VALID_DATE:%Y-%m-%d}"); continue
        emp_id = badges.get(badge)
        if emp_id is None:
            reject(idx, row, "UNKNOWN_BADGE", f"badge '{badge}' is not linked to any employee"); continue
        key = (emp_id, local, device)
        if key in seen:
            in_file_dupes += 1
            continue
        seen.add(key)
        accepted.append((idx, badge, emp_id, local.isoformat(sep=" "), raw_ts, ptype, device))

    stored_path = None
    if keep_copy:
        dest_dir = Path(settings.UPLOAD_DIR)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{datetime.now():%Y%m%d%H%M%S}_{digest[:10]}{path.suffix.lower()}"
        if path.resolve() != dest.resolve():
            shutil.copyfile(path, dest)
        stored_path = str(dest)

    times = [a[3] for a in accepted]
    with transaction(conn):
        bid = repos.insert_batch(conn, {**base_batch, "source_type": kind, "stored_path": stored_path,
                                        "status": "failed", "rows_total": len(df)})
        inserted = repos.insert_raw_punches(conn, [(bid, *a) for a in accepted])
        repos.insert_rejects(conn, [(bid, *r) for r in rejects])
        duplicates = in_file_dupes + (len(accepted) - inserted)
        if not rejects:
            status = "success"
        elif accepted:
            status = "partial"
        else:
            status = "failed"
        msg = (f"{inserted} new punches stored, {duplicates} duplicates skipped, "
               f"{len(rejects)} rows quarantined.")
        repos.update_batch_counts(conn, bid, status=status, rows_accepted=inserted, rows_duplicate=duplicates,
                                  rows_rejected=len(rejects), min_punch_time=min(times) if times else None,
                                  max_punch_time=max(times) if times else None, message=msg)
        repos.audit(conn, imported_by_user_id, "import", "import_batch", bid,
                    {"file": original_name, "status": status, "accepted": inserted, "rejected": len(rejects)})

    return ImportResult(bid, status, len(df), inserted, duplicates, len(rejects),
                        min(times) if times else None, max(times) if times else None, msg, reasons)
