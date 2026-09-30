-- HR Attendance & Performance Analytics System — schema v2 (see CHANGELOG.md)
-- Written in portable SQL. SQLite-specific notes:
--   * INTEGER PRIMARY KEY  -> use GENERATED ALWAYS AS IDENTITY on PostgreSQL / IDENTITY on SQL Server
--   * dates/times are stored as ISO-8601 TEXT in the organisation's local timezone
--     ('YYYY-MM-DD', 'YYYY-MM-DD HH:MM:SS'); map to DATE / TIMESTAMP on migration.
--   * partial unique indexes (WHERE ...) are supported by SQLite and PostgreSQL;
--     SQL Server supports them as "filtered indexes".

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- org ----
CREATE TABLE IF NOT EXISTS departments (
    department_id        INTEGER PRIMARY KEY,
    code                 TEXT NOT NULL UNIQUE,
    name                 TEXT NOT NULL,
    manager_employee_id  INTEGER REFERENCES employees(employee_id),
    is_active            INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS shifts (
    shift_id                   INTEGER PRIMARY KEY,
    code                       TEXT NOT NULL UNIQUE,
    name                       TEXT NOT NULL,
    start_time                 TEXT NOT NULL,          -- 'HH:MM'
    end_time                   TEXT NOT NULL,          -- 'HH:MM'; end <= start means the shift crosses midnight
    grace_minutes              INTEGER NOT NULL DEFAULT 15 CHECK (grace_minutes BETWEEN 0 AND 120),
    early_leave_grace_minutes  INTEGER NOT NULL DEFAULT 5 CHECK (early_leave_grace_minutes BETWEEN 0 AND 120),
    workdays                   TEXT NOT NULL DEFAULT 'SUN,MON,TUE,WED,THU',
    is_active                  INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS employees (
    employee_id          INTEGER PRIMARY KEY,
    employee_code        TEXT NOT NULL UNIQUE,
    badge_id             TEXT NOT NULL UNIQUE,     -- identifier used by the time-clock device
    full_name            TEXT NOT NULL,
    email                TEXT UNIQUE,              -- also the Power BI UPN for RLS
    job_title            TEXT,
    department_id        INTEGER NOT NULL REFERENCES departments(department_id),
    manager_employee_id  INTEGER REFERENCES employees(employee_id),
    hire_date            TEXT NOT NULL,
    termination_date     TEXT,
    is_synthetic         INTEGER NOT NULL DEFAULT 0,
    CHECK (termination_date IS NULL OR termination_date >= hire_date)
);
CREATE INDEX IF NOT EXISTS ix_employees_department ON employees(department_id);

CREATE TABLE IF NOT EXISTS employee_shift_assignments (
    assignment_id   INTEGER PRIMARY KEY,
    employee_id     INTEGER NOT NULL REFERENCES employees(employee_id),
    shift_id        INTEGER NOT NULL REFERENCES shifts(shift_id),
    effective_from  TEXT NOT NULL,
    effective_to    TEXT,                            -- inclusive; NULL = open-ended
    UNIQUE (employee_id, effective_from),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE TABLE IF NOT EXISTS holidays (
    holiday_date     TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    is_illustrative  INTEGER NOT NULL DEFAULT 0    -- 1 = approximate date, verify against the official calendar
);

CREATE TABLE IF NOT EXISTS leave_requests (
    leave_id             INTEGER PRIMARY KEY,
    employee_id          INTEGER NOT NULL REFERENCES employees(employee_id),
    leave_type           TEXT NOT NULL CHECK (leave_type IN ('annual', 'sick', 'unpaid', 'other')),
    start_date           TEXT NOT NULL,
    end_date             TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('approved', 'pending', 'rejected', 'cancelled')),
    approved_by_user_id  INTEGER REFERENCES users(user_id),   -- the decider (approve OR reject)
    -- v2: self-service workflow (NULL for records entered directly by HR or loaded from files)
    reason               TEXT,
    requested_by_user_id INTEGER REFERENCES users(user_id),
    requested_at         TEXT,
    decided_at           TEXT,
    decision_note        TEXT,
    CHECK (end_date >= start_date)
);
CREATE INDEX IF NOT EXISTS ix_leave_employee ON leave_requests(employee_id, start_date);
CREATE INDEX IF NOT EXISTS ix_leave_status ON leave_requests(status, employee_id);

-- -------------------------------------------------------------- users ----
CREATE TABLE IF NOT EXISTS users (
    user_id        INTEGER PRIMARY KEY,
    username       TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('hr', 'manager', 'employee')),
    employee_id    INTEGER UNIQUE REFERENCES employees(employee_id),
    is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    last_login_at  TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    must_change_password INTEGER NOT NULL DEFAULT 0 CHECK (must_change_password IN (0, 1))  -- v2
);

-- ------------------------------------------------------------ imports ----
CREATE TABLE IF NOT EXISTS import_batches (
    batch_id              INTEGER PRIMARY KEY,
    source_type           TEXT NOT NULL,           -- 'csv' | 'excel'
    source_name           TEXT NOT NULL,           -- original file name
    stored_path           TEXT,                    -- copy kept for provenance
    source_device         TEXT,
    source_timezone       TEXT NOT NULL,
    file_sha256           TEXT NOT NULL,
    imported_by_user_id   INTEGER REFERENCES users(user_id),
    imported_at           TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('success', 'partial', 'failed')),
    rows_total            INTEGER NOT NULL DEFAULT 0,
    rows_accepted         INTEGER NOT NULL DEFAULT 0,  -- new raw punches stored
    rows_duplicate        INTEGER NOT NULL DEFAULT 0,  -- valid but already stored
    rows_rejected         INTEGER NOT NULL DEFAULT 0,  -- quarantined in rejected_rows
    min_punch_time        TEXT,
    max_punch_time        TEXT,
    message               TEXT
);
-- the same file content can only be loaded successfully once
CREATE UNIQUE INDEX IF NOT EXISTS ux_import_file_once
    ON import_batches(file_sha256) WHERE status IN ('success', 'partial');

CREATE TABLE IF NOT EXISTS raw_punches (
    punch_id          INTEGER PRIMARY KEY,
    batch_id          INTEGER NOT NULL REFERENCES import_batches(batch_id),
    source_row        INTEGER NOT NULL,            -- 1-based data row in the source file
    badge_id          TEXT NOT NULL,
    employee_id       INTEGER NOT NULL REFERENCES employees(employee_id),
    punch_time_local  TEXT NOT NULL,               -- normalised to ORG_TIMEZONE
    punch_time_raw    TEXT NOT NULL,               -- exactly as received
    punch_type        TEXT NOT NULL DEFAULT 'UNKNOWN',  -- device-reported IN/OUT, informational only
    device_id         TEXT NOT NULL DEFAULT '',
    UNIQUE (employee_id, punch_time_local, device_id)
);
CREATE INDEX IF NOT EXISTS ix_raw_punches_emp_time ON raw_punches(employee_id, punch_time_local);

CREATE TABLE IF NOT EXISTS rejected_rows (
    reject_id      INTEGER PRIMARY KEY,
    batch_id       INTEGER NOT NULL REFERENCES import_batches(batch_id),
    source_row     INTEGER NOT NULL,
    raw_data       TEXT NOT NULL,                  -- JSON of the original row
    reason_code    TEXT NOT NULL,
    reason_detail  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rejected_batch ON rejected_rows(batch_id);

-- ---------------------------------------------------- attendance output ----
CREATE TABLE IF NOT EXISTS attendance_daily (
    employee_id          INTEGER NOT NULL REFERENCES employees(employee_id),
    shift_date           TEXT NOT NULL,            -- the date the shift STARTS on
    shift_id             INTEGER REFERENCES shifts(shift_id),
    scheduled_start      TEXT,
    scheduled_end        TEXT,
    scheduled_minutes    INTEGER,
    status               TEXT NOT NULL CHECK (status IN (
                            'present', 'incomplete', 'absent', 'leave', 'holiday',
                            'day_off', 'pending', 'unscheduled_work')),
    raw_punch_count      INTEGER NOT NULL DEFAULT 0,
    punch_count          INTEGER NOT NULL DEFAULT 0, -- after collapsing near-duplicates
    first_punch          TEXT,
    last_punch           TEXT,
    is_late              INTEGER NOT NULL DEFAULT 0,
    late_minutes         INTEGER NOT NULL DEFAULT 0,
    early_leave_minutes  INTEGER NOT NULL DEFAULT 0,
    span_minutes         INTEGER,                  -- last - first punch; NOT verified working time
    leave_type           TEXT,
    holiday_name         TEXT,
    notes                TEXT,
    rule_version         TEXT NOT NULL,
    processed_at         TEXT NOT NULL,
    PRIMARY KEY (employee_id, shift_date)
);
CREATE INDEX IF NOT EXISTS ix_attendance_date ON attendance_daily(shift_date);

CREATE TABLE IF NOT EXISTS punch_exceptions (
    punch_id          INTEGER PRIMARY KEY REFERENCES raw_punches(punch_id),
    employee_id       INTEGER NOT NULL,
    punch_time_local  TEXT NOT NULL,
    shift_date        TEXT,
    reason            TEXT NOT NULL CHECK (reason IN ('outside_employment', 'no_shift_window', 'no_shift_assignment')),
    detected_at       TEXT NOT NULL
);

-- -------------------------------------------------------- performance ----
CREATE TABLE IF NOT EXISTS evaluation_weights (
    weights_id          INTEGER PRIMARY KEY,
    effective_from      TEXT NOT NULL UNIQUE,      -- first period 'YYYY-MM' the weights apply to
    w_punctuality       REAL NOT NULL CHECK (w_punctuality BETWEEN 0 AND 100),
    w_communication     REAL NOT NULL CHECK (w_communication BETWEEN 0 AND 100),
    w_task_completion   REAL NOT NULL CHECK (w_task_completion BETWEEN 0 AND 100),
    w_teamwork          REAL NOT NULL CHECK (w_teamwork BETWEEN 0 AND 100),
    created_by_user_id  INTEGER REFERENCES users(user_id),
    created_at          TEXT NOT NULL,
    CHECK (abs(w_punctuality + w_communication + w_task_completion + w_teamwork - 100) < 0.001)
);

CREATE TABLE IF NOT EXISTS performance_evaluations (
    evaluation_id          INTEGER PRIMARY KEY,
    employee_id            INTEGER NOT NULL REFERENCES employees(employee_id),
    period                 TEXT NOT NULL,          -- 'YYYY-MM'
    evaluator_user_id      INTEGER NOT NULL REFERENCES users(user_id),
    score_punctuality      INTEGER NOT NULL CHECK (score_punctuality BETWEEN 1 AND 5),
    score_communication    INTEGER NOT NULL CHECK (score_communication BETWEEN 1 AND 5),
    score_task_completion  INTEGER NOT NULL CHECK (score_task_completion BETWEEN 1 AND 5),
    score_teamwork         INTEGER NOT NULL CHECK (score_teamwork BETWEEN 1 AND 5),
    weights_id             INTEGER NOT NULL REFERENCES evaluation_weights(weights_id),
    weighted_score         REAL NOT NULL CHECK (weighted_score BETWEEN 1 AND 5),
    comments               TEXT,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL,
    UNIQUE (employee_id, period)
);

CREATE TABLE IF NOT EXISTS evaluation_history (
    history_id          INTEGER PRIMARY KEY,
    evaluation_id       INTEGER NOT NULL REFERENCES performance_evaluations(evaluation_id),
    changed_by_user_id  INTEGER NOT NULL REFERENCES users(user_id),
    changed_at          TEXT NOT NULL,
    action              TEXT NOT NULL CHECK (action IN ('create', 'update')),
    old_values          TEXT,                      -- JSON
    new_values          TEXT NOT NULL              -- JSON
);

-- v2: employee-reported missed punches. An approved correction becomes a raw
-- punch in a 'manual' import batch (device_id 'MANUAL'), so it flows through
-- the normal rules and stays traceable to the request and the approver.
CREATE TABLE IF NOT EXISTS attendance_corrections (
    correction_id         INTEGER PRIMARY KEY,
    employee_id           INTEGER NOT NULL REFERENCES employees(employee_id),
    shift_date            TEXT NOT NULL,
    punch_time            TEXT NOT NULL,           -- 'YYYY-MM-DD HH:MM:SS' org-local
    punch_kind            TEXT NOT NULL CHECK (punch_kind IN ('in', 'out')),
    reason                TEXT NOT NULL,
    status                TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
    requested_by_user_id  INTEGER NOT NULL REFERENCES users(user_id),
    requested_at          TEXT NOT NULL,
    decided_by_user_id    INTEGER REFERENCES users(user_id),
    decided_at            TEXT,
    decision_note         TEXT,
    punch_id              INTEGER REFERENCES raw_punches(punch_id)
);
CREATE INDEX IF NOT EXISTS ix_corrections_status ON attendance_corrections(status, employee_id);

-- ------------------------------------------------------------- system ----
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id     INTEGER PRIMARY KEY,
    occurred_at  TEXT NOT NULL,
    user_id      INTEGER REFERENCES users(user_id),
    action       TEXT NOT NULL,
    entity       TEXT NOT NULL,
    entity_id    TEXT,
    details      TEXT,                              -- JSON
    remote_addr  TEXT
);
CREATE INDEX IF NOT EXISTS ix_audit_time ON audit_log(occurred_at);

CREATE TABLE IF NOT EXISTS report_runs (
    run_id        INTEGER PRIMARY KEY,
    report_type   TEXT NOT NULL,
    period        TEXT NOT NULL,
    scope_key     TEXT NOT NULL,                    -- 'org' or 'dept:<id>'
    status        TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed', 'superseded')),
    triggered_by  TEXT NOT NULL,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    output_path   TEXT,
    error         TEXT
);
-- at most one running-or-successful run per report/period/scope (prevents accidental duplicates)
CREATE UNIQUE INDEX IF NOT EXISTS ux_report_once
    ON report_runs(report_type, period, scope_key) WHERE status IN ('running', 'success');

CREATE TABLE IF NOT EXISTS risk_scores (
    employee_id     INTEGER NOT NULL REFERENCES employees(employee_id),
    feature_period  TEXT NOT NULL,
    target_period   TEXT NOT NULL,
    probability     REAL NOT NULL,
    method          TEXT NOT NULL CHECK (method IN ('model', 'rules')),
    model_version   TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (employee_id, target_period, model_version)
);

-- v2: generated files (model evaluation, PDF reports) kept in the database as well
-- as on disk, so a host with a temporary filesystem (e.g. a free cloud web
-- service) still serves them after a restart.
CREATE TABLE IF NOT EXISTS stored_files (
    path          TEXT PRIMARY KEY,                -- logical name, e.g. 'reports/hr_monthly_2026-08_org_run1.pdf'
    content       BLOB NOT NULL,
    content_type  TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
-- Fresh databases start at the current version; older ones are upgraded by
-- db/connection.py:migrate() (called by init-db and on web start-up).
INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '2');
