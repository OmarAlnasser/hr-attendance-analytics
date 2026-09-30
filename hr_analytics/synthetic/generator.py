"""Reproducible synthetic HR data (seeded).

SYNTHETIC DATA — every person, badge and score here is invented. Relationships
between attendance and performance are *designed into this generator*; any
model trained on them only rediscovers these rules and says nothing about a
real organisation.

Edge cases deliberately injected
--------------------------------
* near-duplicate punches (double taps 5-70 s apart) and exact duplicate rows
* unknown badges, empty badges, malformed and far-future timestamps
* missing OUT and missing IN punches
* night shifts crossing midnight (22:00-06:00)
* one device exporting in UTC with a 'Z' suffix (time-zone conversion)
* approved / pending / rejected leave, punches on approved leave
* public holidays (Islamic holidays flagged as illustrative dates)
* late arrivals inside and beyond the grace period, early leaves, absences
* mid-period hires and terminations, badge used after termination
* shift changes mid-period (assignment history)
* different header spellings between CSV and Excel exports
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SHIFTS = [
    # code, name, start, end, grace, early grace, workdays
    ("DAY", "Day shift", "08:00", "16:00", 15, 5, "SUN,MON,TUE,WED,THU"),
    ("EVE", "Evening shift", "14:00", "22:00", 10, 5, "SUN,MON,TUE,WED,THU"),
    ("NIGHT", "Night shift", "22:00", "06:00", 15, 5, "SUN,MON,TUE,WED,THU"),
]
DEPARTMENTS = [
    # code, name, share of headcount, shift mix, device, job titles
    ("OPS", "Operations", 0.27, {"DAY": 0.5, "NIGHT": 0.5}, "D02-GATE", ["Operations Technician", "Shift Supervisor", "Logistics Coordinator"]),
    ("CS", "Customer Service", 0.20, {"DAY": 0.4, "EVE": 0.6}, "D01-MAIN", ["Customer Service Agent", "Service Team Lead"]),
    ("SAL", "Sales", 0.16, {"DAY": 1.0}, "D01-MAIN", ["Account Executive", "Sales Coordinator"]),
    ("IT", "Information Technology", 0.15, {"DAY": 0.8, "EVE": 0.2}, "D03-UTC", ["Systems Analyst", "Support Engineer", "Data Analyst"]),
    ("FIN", "Finance", 0.13, {"DAY": 1.0}, "D01-MAIN", ["Accountant", "Financial Analyst"]),
    ("HR", "Human Resources", 0.09, {"DAY": 1.0}, "D01-MAIN", ["HR Specialist", "Recruiter", "Payroll Officer"]),
]
FIRST_NAMES = ["Abdullah", "Mohammed", "Fahad", "Khalid", "Sultan", "Faisal", "Turki", "Nasser", "Yousef", "Omar",
               "Saad", "Majed", "Rakan", "Hamad", "Ziyad", "Nora", "Sara", "Reem", "Lama", "Haya", "Maha", "Dana",
               "Abeer", "Hind", "Lina", "Rana", "Shahad", "Joud", "Ghada", "Asma"]
FAMILY_NAMES = ["Al-Otaibi", "Al-Qahtani", "Al-Harbi", "Al-Shammari", "Al-Dosari", "Al-Mutairi", "Al-Zahrani",
                "Al-Ghamdi", "Al-Anazi", "Al-Subaie", "Al-Shehri", "Al-Omari", "Al-Malki", "Al-Rashidi", "Al-Juhani",
                "Al-Tamimi", "Al-Khaldi", "Al-Balawi", "Al-Hajri", "Al-Yami"]
HOLIDAYS = [
    # date, name, illustrative flag (1 = approximate Hijri-based date, verify officially)
    ("2025-09-23", "National Day", 0),
    ("2026-02-22", "Founding Day", 0),
    ("2026-03-19", "Eid al-Fitr (illustrative)", 1), ("2026-03-20", "Eid al-Fitr (illustrative)", 1),
    ("2026-03-21", "Eid al-Fitr (illustrative)", 1), ("2026-03-22", "Eid al-Fitr (illustrative)", 1),
    ("2026-05-26", "Eid al-Adha (illustrative)", 1), ("2026-05-27", "Eid al-Adha (illustrative)", 1),
    ("2026-05-28", "Eid al-Adha (illustrative)", 1), ("2026-05-29", "Eid al-Adha (illustrative)", 1),
]
WEEKDAY_CODES = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
EVALUABLE_MIN_DAYS = 10


@dataclass
class GeneratedSummary:
    out_dir: str
    employees: int
    punch_rows: int
    evaluations: int
    files: list


def _months(start: date, n: int) -> list[tuple[date, date]]:
    out, y, m = [], start.year, start.month
    for _ in range(n):
        first = date(y, m, 1)
        y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
        out.append((first, date(y2, m2, 1) - timedelta(days=1)))
        y, m = y2, m2
    return out


def _shift_times(code: str):
    s = next(x for x in SHIFTS if x[0] == code)
    st, en = time.fromisoformat(s[2]), time.fromisoformat(s[3])
    workdays = {WEEKDAY_CODES.index(t) for t in s[6].split(",")}
    return st, en, s[4], workdays


def generate(out_dir: str | Path, *, seed: int = 42, start: str = "2025-09-01", months: int = 12,
             n_employees: int = 110, n_new_hires: int = 10) -> GeneratedSummary:
    rng = np.random.default_rng(seed)
    out = Path(out_dir)
    (out / "master").mkdir(parents=True, exist_ok=True)
    (out / "punches").mkdir(parents=True, exist_ok=True)
    (out / "evaluations").mkdir(parents=True, exist_ok=True)
    period_start = date.fromisoformat(start)
    month_ranges = _months(period_start, months)
    period_end = month_ranges[-1][1]
    holidays = {d: n for d, n, _ in HOLIDAYS if period_start.isoformat() <= d <= period_end.isoformat()}

    # ------------------------------------------------------------ employees
    sizes = [max(2, int(round(d[2] * n_employees))) for d in DEPARTMENTS]
    sizes[0] += n_employees - sum(sizes)
    employees, assignments = [], []
    code_no = 0
    for (dcode, dname, _share, mix, device, titles), size in zip(DEPARTMENTS, sizes):
        for k in range(size):
            code_no += 1
            is_manager = k == 0
            shift = "DAY" if is_manager else rng.choice(list(mix), p=list(mix.values()))
            hire = date(2014, 1, 1) + timedelta(days=int(rng.integers(0, (period_start - date(2014, 1, 1)).days - 30)))
            employees.append({
                "employee_code": f"E{code_no:04d}", "badge_id": f"B{10000 + code_no}",
                "full_name": f"{rng.choice(FIRST_NAMES)} {rng.choice(FAMILY_NAMES)}",
                "email": f"e{code_no:04d}@example.com",
                "job_title": f"{dname} Manager" if is_manager else str(rng.choice(titles)),
                "department_code": dcode, "is_manager": is_manager, "hire_date": hire.isoformat(),
                "termination_date": None, "shift": str(shift), "device": device,
            })
    # mid-period hires
    for _ in range(n_new_hires):
        code_no += 1
        dept = DEPARTMENTS[int(rng.integers(0, len(DEPARTMENTS)))]
        shift = rng.choice(list(dept[3]), p=list(dept[3].values()))
        hire = month_ranges[min(len(month_ranges) - 1, int(rng.integers(1, max(2, months - 2))))][0] + \
            timedelta(days=int(rng.integers(0, 20)))
        employees.append({
            "employee_code": f"E{code_no:04d}", "badge_id": f"B{10000 + code_no}",
            "full_name": f"{rng.choice(FIRST_NAMES)} {rng.choice(FAMILY_NAMES)}",
            "email": f"e{code_no:04d}@example.com", "job_title": str(rng.choice(dept[5])),
            "department_code": dept[0], "is_manager": False, "hire_date": hire.isoformat(),
            "termination_date": None, "shift": str(shift), "device": dept[4],
        })
    # terminations (never managers)
    candidates = [i for i, e in enumerate(employees) if not e["is_manager"] and e["hire_date"] < start]
    n_term = max(1, int(round(0.07 * len(employees))))
    for i in rng.choice(candidates, size=min(n_term, len(candidates)), replace=False):
        term = month_ranges[int(rng.integers(max(1, months // 4), max(2, months - 1)))][0] + \
            timedelta(days=int(rng.integers(0, 25)))
        employees[int(i)]["termination_date"] = min(term, period_end).isoformat()

    managers = {e["department_code"]: e["employee_code"] for e in employees if e["is_manager"]}
    for e in employees:
        e["manager_code"] = None if e["is_manager"] else managers[e["department_code"]]
        assignments.append({"employee_code": e["employee_code"], "shift_code": e["shift"],
                            "effective_from": e["hire_date"], "effective_to": None})
    # shift changes mid-period for a few operations staff
    ops_day = [e for e in employees if e["department_code"] == "OPS" and e["shift"] == "DAY"
               and not e["is_manager"] and e["termination_date"] is None]
    for e in ops_day[:3]:
        change = month_ranges[months // 2][0]
        for a in assignments:
            if a["employee_code"] == e["employee_code"]:
                a["effective_to"] = (change - timedelta(days=1)).isoformat()
        assignments.append({"employee_code": e["employee_code"], "shift_code": "NIGHT",
                            "effective_from": change.isoformat(), "effective_to": None})

    # --------------------------------------------------------------- users
    users = []
    hr_staff = [e for e in employees if e["department_code"] == "HR"]
    for e in employees:
        if e["department_code"] == "HR" and (e["is_manager"] or e is hr_staff[1]):
            role = "hr"
        elif e["is_manager"]:
            role = "manager"
        else:
            role = "employee"
        users.append({"username": e["employee_code"].lower(), "role": role, "employee_code": e["employee_code"]})

    # ---------------------------------------------------------------- leave
    leaves, leave_days = [], {}
    for e in employees:
        hire = date.fromisoformat(e["hire_date"])
        term = date.fromisoformat(e["termination_date"]) if e["termination_date"] else period_end
        lo, hi = max(hire, period_start), min(term, period_end)
        if (hi - lo).days < 20:
            continue
        for kind, n_blocks, length in (("annual", int(rng.integers(1, 3)), (3, 9)), ("sick", int(rng.integers(0, 3)), (1, 3))):
            for _ in range(n_blocks):
                s = lo + timedelta(days=int(rng.integers(0, (hi - lo).days - 10)))
                en = s + timedelta(days=int(rng.integers(*length)) - 1)
                status = "approved" if rng.random() > 0.08 else str(rng.choice(["pending", "rejected"]))
                leaves.append({"employee_code": e["employee_code"], "leave_type": kind, "start_date": s.isoformat(),
                               "end_date": en.isoformat(), "status": status})
                if status == "approved":
                    d = s
                    while d <= en:
                        leave_days[(e["employee_code"], d)] = kind
                        d += timedelta(days=1)

    # ------------------------------------------------------------- behaviour
    traits = {}
    for e in employees:
        r = float(rng.beta(8, 2))
        q = float(np.clip(0.7 * (r - 0.8) / 0.12 + rng.normal(0, 0.6), -2.2, 2.2))
        decline = None
        if rng.random() < 0.18 and months >= 4:
            m0 = int(rng.integers(1, months - 2))
            decline = (m0, m0 + int(rng.integers(2, 5)))
        traits[e["employee_code"]] = {"r": r, "q": q, "decline": decline,
                                      "month_noise": rng.normal(0, 0.04, size=months)}

    def monthly_state(code: str, mi: int) -> tuple[float, float]:
        t = traits[code]
        dec = t["decline"] is not None and t["decline"][0] <= mi < t["decline"][1]
        r = float(np.clip(t["r"] + t["month_noise"][mi] - (0.28 if dec else 0), 0.2, 0.99))
        q = t["q"] - (1.4 if dec else 0.0)
        return r, q

    # --------------------------------------------------------------- punches
    rows_by_month: dict[int, list[dict]] = {i: [] for i in range(months)}
    month_stats: dict[tuple[str, int], dict] = {}
    by_code = {e["employee_code"]: e for e in employees}

    def shift_for(code: str, d: date) -> str:
        for a in assignments:
            if a["employee_code"] == code and a["effective_from"] <= d.isoformat() and \
                    (a["effective_to"] is None or a["effective_to"] >= d.isoformat()):
                return a["shift_code"]
        return by_code[code]["shift"]

    def emit(mi: int, e: dict, ts: datetime, ptype: str):
        device = e["device"]
        if device == "D03-UTC":
            value = (ts - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            value = ts.strftime("%Y-%m-%d %H:%M:%S")
        if rng.random() < 0.03:  # device reports the wrong direction now and then
            ptype = "OUT" if ptype == "IN" else "IN"
        row = {"badge_id": e["badge_id"], "punch_time": value, "device_id": device, "punch_type": ptype}
        rows_by_month[mi].append(row)
        if rng.random() < 0.004:  # exact duplicate row in the export
            rows_by_month[mi].append(dict(row))
        if rng.random() < 0.04:   # double tap a few seconds later
            rows_by_month[mi].append({**row, "punch_time": (
                (ts + timedelta(seconds=int(rng.integers(5, 70))) - (timedelta(hours=3) if device == "D03-UTC" else timedelta()))
                .strftime("%Y-%m-%dT%H:%M:%SZ" if device == "D03-UTC" else "%Y-%m-%d %H:%M:%S"))})

    for mi, (m_first, m_last) in enumerate(month_ranges):
        for e in employees:
            code = e["employee_code"]
            hire = date.fromisoformat(e["hire_date"])
            term = date.fromisoformat(e["termination_date"]) if e["termination_date"] else None
            r, _q = monthly_state(code, mi)
            stats = {"expected": 0, "attended": 0, "late": 0, "absent": 0, "days_employed": 0}
            d = m_first
            while d <= m_last:
                employed = d >= hire and (term is None or d <= term)
                if employed:
                    stats["days_employed"] += 1
                st, en, grace, workdays = _shift_times(shift_for(code, d))
                start_dt = datetime.combine(d, st)
                end_dt = datetime.combine(d + timedelta(days=1) if en <= st else d, en)
                is_work = d.weekday() in workdays and d.isoformat() not in holidays
                on_leave = (code, d) in leave_days
                if not employed:
                    # badge used shortly after termination (outside employment)
                    if term and term < d <= term + timedelta(days=3) and is_work and rng.random() < 0.5:
                        emit(mi, e, start_dt + timedelta(minutes=int(rng.integers(-10, 10))), "IN")
                    d += timedelta(days=1)
                    continue
                if not is_work or on_leave:
                    if on_leave and is_work and rng.random() < 0.01:
                        emit(mi, e, start_dt + timedelta(minutes=int(rng.integers(-15, 5))), "IN")
                        emit(mi, e, end_dt + timedelta(minutes=int(rng.integers(0, 20))), "OUT")
                    elif not is_work and e["department_code"] == "OPS" and rng.random() < 0.02:
                        emit(mi, e, start_dt + timedelta(minutes=int(rng.integers(-10, 10))), "IN")
                        emit(mi, e, end_dt - timedelta(minutes=int(rng.integers(0, 60))), "OUT")
                    d += timedelta(days=1)
                    continue
                stats["expected"] += 1
                if rng.random() < 0.01 + (1 - r) * 0.08:
                    stats["absent"] += 1
                    d += timedelta(days=1)
                    continue
                stats["attended"] += 1
                if rng.random() < 0.04 + (1 - r) * 0.35:
                    offset = grace + 1 + float(rng.exponential(18))
                    stats["late"] += 1
                else:
                    offset = float(np.clip(rng.normal(-8, 7), -45, grace))
                arrive = start_dt + timedelta(minutes=offset, seconds=int(rng.integers(0, 60)))
                if rng.random() < 0.02 + (1 - r) * 0.05:
                    leave_at = end_dt - timedelta(minutes=float(rng.uniform(10, 90)))
                else:
                    leave_at = end_dt + timedelta(minutes=float(np.clip(rng.normal(12, 12), -4, 90)))
                leave_at += timedelta(seconds=int(rng.integers(0, 60)))
                u = rng.random()
                if u < 0.004:
                    emit(mi, e, leave_at, "OUT")                    # missing IN
                elif u < 0.004 + 0.012 + (1 - r) * 0.02:
                    emit(mi, e, arrive, "IN")                       # missing OUT
                else:
                    emit(mi, e, arrive, "IN")
                    emit(mi, e, leave_at, "OUT")
                d += timedelta(days=1)
            month_stats[(code, mi)] = stats

        # noise rows: unknown badges and malformed records
        for _ in range(3):
            ts = datetime.combine(m_first + timedelta(days=int(rng.integers(0, 25))), time(8, int(rng.integers(0, 50))))
            rows_by_month[mi].append({"badge_id": f"B9{int(rng.integers(1000, 9999))}", "punch_time": ts.strftime("%Y-%m-%d %H:%M:%S"),
                                      "device_id": "D01-MAIN", "punch_type": "IN"})
        rows_by_month[mi] += [
            {"badge_id": employees[1]["badge_id"], "punch_time": f"{m_first:%Y-%m}-32 08:01:00", "device_id": "D01-MAIN", "punch_type": "IN"},
            {"badge_id": employees[2]["badge_id"], "punch_time": f"{m_first:%d/%m/%Y} 08:05", "device_id": "D01-MAIN", "punch_type": "IN"},
            {"badge_id": "", "punch_time": f"{m_first:%Y-%m-%d} 08:07:00", "device_id": "D01-MAIN", "punch_type": "IN"},
            {"badge_id": employees[3]["badge_id"], "punch_time": "2099-01-01 08:00:00", "device_id": "D01-MAIN", "punch_type": "IN"},
        ]

    files, total_rows = [], 0
    for mi, (m_first, _m_last) in enumerate(month_ranges):
        df = pd.DataFrame(rows_by_month[mi])
        df = df.sample(frac=1.0, random_state=seed + mi).reset_index(drop=True)  # devices do not export in order
        total_rows += len(df)
        if mi == months - 1:
            # the last month arrives as Excel with different header spellings
            df = df.rename(columns={"badge_id": "Badge No", "punch_time": "Date Time",
                                    "device_id": "Terminal", "punch_type": "State"})
            p = out / "punches" / f"device_export_{m_first:%Y-%m}.xlsx"
            df.to_excel(p, index=False)
        else:
            p = out / "punches" / f"device_export_{m_first:%Y-%m}.csv"
            df.to_csv(p, index=False)
        files.append(str(p))

    # ---------------------------------------------------------- evaluations
    evals = []
    hr_head = next(e for e in employees if e["department_code"] == "HR" and e["is_manager"])["employee_code"]
    hr_second = hr_staff[1]["employee_code"]
    for mi, (m_first, _m_last) in enumerate(month_ranges):
        for e in employees:
            code = e["employee_code"]
            s = month_stats.get((code, mi))
            if not s or s["days_employed"] < EVALUABLE_MIN_DAYS or rng.random() < 0.03:
                continue
            r, q = monthly_state(code, mi)
            late_rate = s["late"] / s["attended"] if s["attended"] else 0.0
            abs_rate = s["absent"] / s["expected"] if s["expected"] else 0.0

            def score(mu: float, sd: float = 0.55) -> int:
                return int(np.clip(round(mu + rng.normal(0, sd)), 1, 5))

            p = score(5.0 - 6 * late_rate - 10 * abs_rate, 0.45)
            c, t, w = score(3.4 + 0.55 * q), score(3.4 + 0.65 * q), score(3.5 + 0.45 * q)
            if code == hr_head:
                evaluator = hr_second
            elif e["is_manager"] or e["department_code"] == "HR" and code == hr_second:
                evaluator = hr_head
            else:
                evaluator = e["manager_code"]
            avg = (p + c + t + w) / 4
            comment = ("Consistently strong month." if avg >= 4.2 else
                       "Meets expectations." if avg >= 3.2 else
                       "Below expectations this month; follow-up conversation recommended.")
            evals.append({"employee_code": code, "period": f"{m_first:%Y-%m}", "evaluator_username": evaluator.lower(),
                          "punctuality": p, "communication": c, "task_completion": t, "teamwork": w,
                          "comments": f"[SYNTHETIC] {comment}"})

    # ---------------------------------------------------------------- write
    pd.DataFrame([{k: v for k, v in zip(("code", "name", "start_time", "end_time", "grace_minutes",
                                          "early_leave_grace_minutes", "workdays"), s)} for s in SHIFTS]
                 ).to_csv(out / "master" / "shifts.csv", index=False)
    pd.DataFrame([{"code": d[0], "name": d[1], "manager_employee_code": managers[d[0]]} for d in DEPARTMENTS]
                 ).to_csv(out / "master" / "departments.csv", index=False)
    pd.DataFrame([{k: e[k] for k in ("employee_code", "badge_id", "full_name", "email", "job_title",
                                     "department_code", "manager_code", "hire_date", "termination_date")}
                  for e in employees]).to_csv(out / "master" / "employees.csv", index=False)
    pd.DataFrame(assignments).to_csv(out / "master" / "shift_assignments.csv", index=False)
    pd.DataFrame([{"holiday_date": d, "name": n, "is_illustrative": f} for d, n, f in HOLIDAYS
                  if d in holidays]).to_csv(out / "master" / "holidays.csv", index=False)
    pd.DataFrame(leaves).to_csv(out / "master" / "leave_requests.csv", index=False)
    pd.DataFrame(users).to_csv(out / "master" / "users.csv", index=False)
    pd.DataFrame(evals).to_csv(out / "evaluations" / "evaluations.csv", index=False)
    meta = {"synthetic": True, "seed": seed, "start": start, "months": months, "employees": len(employees),
            "warning": "SYNTHETIC DEMO DATA. Not evidence of any real organisational outcome."}
    (out / "SYNTHETIC_DATA_README.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return GeneratedSummary(str(out), len(employees), total_rows, len(evals), files)
