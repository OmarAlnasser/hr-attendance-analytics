"""Export a star schema for Power BI as UTF-8 CSV files.

Tables and grain
----------------
DimDate                 one row per calendar date (DateKey = yyyymmdd)
DimEmployee             one row per employee; department attributes denormalised (current department, SCD type 1)
DimShift                one row per shift
DimAttendanceStatus     one row per status code
FactAttendanceDaily     one row per employee per shift date
FactPerformanceMonthly  one row per employee per evaluated month (PeriodDateKey = first day of month)
FactEmployeeMonth       one row per employee per month employed (denominator for evaluation coverage)
FactReviewFlag          one row per employee per month per triggered review rule
FactRiskScore           one row per employee per target month (experimental model, may be empty)
SecurityManagerDepartment  UPN -> DepartmentKey for the Department Manager RLS role (hidden in the model)
ExportInfo              export metadata incl. synthetic flag and rule version
validation/expected_kpis.csv  numbers computed by Python to reconcile the DAX measures
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from ..db.connection import now_str, read_sql
from ..domain.attendance_rules import ALL_STATUSES, ATTENDED_STATUSES, EXPECTED_STATUSES
from ..domain.metrics import grouped_attendance_kpis
from ..domain.scoring import parse_period
from ..reports.monthly import EVALUABLE_MIN_DAYS, SYSTEM_USER
from .. import labels as L
from ..i18n import use_lang
from ..services.review import RULES, review_cases

# English and Arabic wording for each status (same words as the app and the PDF)
STATUS_LABELS = {code: pair[0] for code, pair in L.STATUS.items()}
STATUS_LABELS_AR = {code: pair[1] for code, pair in L.STATUS.items()}


def _key(d) -> int:
    d = d if isinstance(d, date) else date.fromisoformat(str(d)[:10])
    return d.year * 10000 + d.month * 100 + d.day


def export_powerbi(conn, out_dir: str | Path, *, settings) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation").mkdir(exist_ok=True)
    files = {}

    def write(name: str, df: pd.DataFrame, sub: str | None = None):
        p = (out / sub / f"{name}.csv") if sub else out / f"{name}.csv"
        df.to_csv(p, index=False, encoding="utf-8")
        files[name] = len(df)

    att = read_sql("SELECT * FROM attendance_daily", conn)
    ev = read_sql("SELECT p.*, w.w_punctuality, w.w_communication, w.w_task_completion, w.w_teamwork "
                           "FROM performance_evaluations p JOIN evaluation_weights w ON w.weights_id = p.weights_id", conn)
    emp = read_sql("""SELECT e.*, d.code AS department_code, d.name AS department_name,
                                      d.name_ar AS department_name_ar,
                                      (SELECT u.role FROM users u WHERE u.employee_id = e.employee_id) AS app_role
                               FROM employees e JOIN departments d ON d.department_id = e.department_id""", conn)
    hol = read_sql("SELECT * FROM holidays", conn)
    if att.empty:
        raise RuntimeError("No attendance results to export. Import and process punches first.")

    # ---------------------------------------------------------------- DimDate
    lo, hi = date.fromisoformat(att.shift_date.min()), date.fromisoformat(att.shift_date.max())
    lo, hi = date(lo.year, 1, 1), date(hi.year, 12, 31)   # full years: required by DAX time intelligence
    days = pd.date_range(lo, hi, freq="D")
    hol_map = dict(zip(hol.holiday_date, hol.name))
    dim_date = pd.DataFrame({"Date": days.date})
    dim_date["DateKey"] = dim_date.Date.map(_key)
    dim_date["Year"] = days.year
    dim_date["MonthNumber"] = days.month
    dim_date["MonthName"] = days.strftime("%b")
    dim_date["YearMonth"] = days.strftime("%Y-%m")
    dim_date["YearMonthSort"] = days.year * 100 + days.month
    dim_date["MonthStart"] = days.to_period("M").start_time.date
    dim_date["DayOfWeekNumber"] = (days.weekday + 1) % 7 + 1          # Sun = 1 ... Sat = 7
    dim_date["DayOfWeekName"] = days.strftime("%a")
    dim_date["WeekStart"] = (days - pd.to_timedelta((days.weekday + 1) % 7, unit="D")).date  # Sunday-based week
    dim_date["IsWeekend"] = days.weekday.isin([4, 5]).astype(int)    # Fri, Sat
    dim_date["IsPublicHoliday"] = dim_date.Date.astype(str).isin(hol_map).astype(int)
    dim_date["HolidayName"] = dim_date.Date.astype(str).map(hol_map)
    write("DimDate", dim_date)

    # ------------------------------------------------------------ DimEmployee
    dim_emp = pd.DataFrame({
        "EmployeeKey": emp.employee_id, "EmployeeCode": emp.employee_code, "EmployeeName": emp.full_name,
        "UserPrincipalName": emp.email.str.lower(), "JobTitle": emp.job_title,
        "DepartmentKey": emp.department_id, "DepartmentCode": emp.department_code,
        "DepartmentName": emp.department_name, "ManagerEmployeeKey": emp.manager_employee_id.astype("Int64"),
        "HireDate": emp.hire_date, "TerminationDate": emp.termination_date,
        "IsActive": emp.termination_date.isna().astype(int), "IsSynthetic": emp.is_synthetic,
        # schema v3: Arabic names for an Arabic report page, and the app role (gm/hr/manager/employee)
        "EmployeeNameAr": emp.full_name_ar, "JobTitleAr": emp.job_title_ar, "DepartmentNameAr": emp.department_name_ar,
        "Gender": emp.gender, "AppRole": emp.app_role})
    write("DimEmployee", dim_emp)

    shifts = read_sql("SELECT * FROM shifts", conn)
    write("DimShift", pd.DataFrame({
        "ShiftKey": shifts.shift_id, "ShiftCode": shifts.code, "ShiftName": shifts.name,
        "StartTime": shifts.start_time, "EndTime": shifts.end_time, "GraceMinutes": shifts.grace_minutes,
        "CrossesMidnight": (shifts.end_time <= shifts.start_time).astype(int), "Workdays": shifts.workdays}))

    write("DimAttendanceStatus", pd.DataFrame([{
        "StatusCode": s, "StatusLabel": STATUS_LABELS[s], "StatusLabelAr": STATUS_LABELS_AR[s],
        "IsExpected": int(s in EXPECTED_STATUSES),
        "IsAttended": int(s in ATTENDED_STATUSES), "SortOrder": i + 1} for i, s in enumerate(ALL_STATUSES)]))

    # ---------------------------------------------------- FactAttendanceDaily
    fact = pd.DataFrame({
        "EmployeeKey": att.employee_id, "DateKey": att.shift_date.map(_key), "ShiftKey": att.shift_id,
        "StatusCode": att.status,
        "IsExpected": att.status.isin(EXPECTED_STATUSES).astype(int),
        "IsAttended": att.status.isin(ATTENDED_STATUSES).astype(int),
        "IsAbsent": (att.status == "absent").astype(int),
        "IsIncomplete": (att.status == "incomplete").astype(int),
        "IsLate": ((att.is_late == 1) & att.status.isin(ATTENDED_STATUSES)).astype(int),
        "LateMinutes": att.late_minutes.where(att.is_late == 1, 0),
        "EarlyLeaveMinutes": att.early_leave_minutes,
        "PresenceSpanMinutes": att.span_minutes, "ScheduledMinutes": att.scheduled_minutes,
        "PunchCount": att.punch_count, "LeaveType": att.leave_type})
    write("FactAttendanceDaily", fact)

    # ------------------------------------------------- FactPerformanceMonthly
    write("FactPerformanceMonthly", pd.DataFrame({
        "EmployeeKey": ev.employee_id, "PeriodDateKey": (ev.period + "-01").map(_key), "Period": ev.period,
        "PunctualityScore": ev.score_punctuality, "CommunicationScore": ev.score_communication,
        "TaskCompletionScore": ev.score_task_completion, "TeamworkScore": ev.score_teamwork,
        "WeightedScore": ev.weighted_score, "WeightPunctuality": ev.w_punctuality,
        "WeightCommunication": ev.w_communication, "WeightTaskCompletion": ev.w_task_completion,
        "WeightTeamwork": ev.w_teamwork, "EvaluatorUserKey": ev.evaluator_user_id}))

    # ------------------------------------------------------ FactEmployeeMonth
    periods = sorted(att.shift_date.str[:7].unique())
    em_rows = []
    for p in periods:
        first, last = parse_period(p)
        for r in emp.itertuples():
            start = max(first, date.fromisoformat(r.hire_date))
            end = min(last, date.fromisoformat(r.termination_date)) if isinstance(r.termination_date, str) else last
            n = (end - start).days + 1
            if n > 0:
                em_rows.append({"EmployeeKey": r.employee_id, "PeriodDateKey": _key(first), "Period": p,
                                "DaysEmployed": n,
                                "IsEvaluable": int(n >= EVALUABLE_MIN_DAYS and getattr(r, "app_role", None) != "gm")})
    write("FactEmployeeMonth", pd.DataFrame(em_rows))

    # --------------------------------------------------------- FactReviewFlag
    flags = []
    for p in periods:
        c = review_cases(conn, SYSTEM_USER, p, threshold=settings.LOW_SCORE_THRESHOLD)
        for r in c.itertuples():
            with use_lang("ar"):
                title_ar, evidence_ar = L.rule_title(r.rule_code), L.rule_evidence(r.rule_code, r.facts)
            flags.append({"EmployeeKey": r.employee_id, "PeriodDateKey": _key(parse_period(p)[0]), "Period": p,
                          "RuleCode": r.rule_code, "RuleDescription": RULES[r.rule_code], "Evidence": r.value,
                          "Method": "rule", "RuleTitle": L.RULES[r.rule_code][0][0], "RuleTitleAr": title_ar,
                          "EvidenceAr": evidence_ar})
    write("FactReviewFlag", pd.DataFrame(flags, columns=["EmployeeKey", "PeriodDateKey", "Period", "RuleCode",
                                                         "RuleDescription", "Evidence", "Method", "RuleTitle",
                                                         "RuleTitleAr", "EvidenceAr"]))

    risk = read_sql("SELECT * FROM risk_scores", conn)
    write("FactRiskScore", pd.DataFrame({
        "EmployeeKey": risk.employee_id, "TargetPeriodDateKey": (risk.target_period + "-01").map(_key),
        "FeaturePeriod": risk.feature_period, "TargetPeriod": risk.target_period,
        "Probability": risk.probability, "Method": risk.method, "ModelVersion": risk.model_version}))

    # --------------------------------------------------------------- Security
    sec = read_sql("""SELECT lower(e.email) AS "UserPrincipalName", d.department_id AS "DepartmentKey"
                               FROM departments d JOIN employees e ON e.employee_id = d.manager_employee_id
                               JOIN users u ON u.employee_id = e.employee_id AND u.role = 'manager'""", conn)
    write("SecurityManagerDepartment", sec)
    roles = read_sql("""SELECT lower(e.email) AS "UserPrincipalName", u.role AS "AppRole"
                                 FROM users u JOIN employees e ON e.employee_id = u.employee_id""", conn)
    # reference for assigning Power BI roles, not loaded: gm and hr both map to the organisation-wide role
    write("SecurityRoleAssignment", roles, sub="validation")

    synthetic = int(emp.is_synthetic.sum() > 0)
    write("ExportInfo", pd.DataFrame([{"ExportedAt": now_str(), "RuleVersion": settings.RULE_VERSION,
                                       "IsSyntheticData": synthetic, "LowScoreThreshold": settings.LOW_SCORE_THRESHOLD,
                                       "Note": "SYNTHETIC DEMO DATA" if synthetic else ""}]))

    # ------------------------------------------------ reconciliation numbers
    a = att.copy()
    a["Period"] = a.shift_date.str[:7]
    a = a.merge(emp[["employee_id", "department_name"]], on="employee_id")
    org = grouped_attendance_kpis(a, "Period").assign(department_name="(All)")
    dept = grouped_attendance_kpis(a, ["Period", "department_name"])
    kpi = pd.concat([org, dept], ignore_index=True)
    evp = ev.merge(emp[["employee_id", "department_name"]], on="employee_id").rename(columns={"period": "Period"})
    s_org = evp.groupby("Period").weighted_score.agg(["mean", "count"]).reset_index().assign(department_name="(All)")
    s_dep = evp.groupby(["Period", "department_name"]).weighted_score.agg(["mean", "count"]).reset_index()
    scores = pd.concat([s_org, s_dep]).rename(columns={"mean": "avg_weighted_score", "count": "evaluations"})
    kpi = kpi.merge(scores, on=["Period", "department_name"], how="left")
    keep = ["Period", "department_name", "employees", "expected_days", "attended_days", "absent_days", "late_days",
            "incomplete_days", "attendance_rate", "absence_rate", "late_rate", "incomplete_rate", "avg_late_minutes",
            "evaluations", "avg_weighted_score"]
    write("expected_kpis", kpi[keep].sort_values(["Period", "department_name"]).round(6), sub="validation")
    return files
