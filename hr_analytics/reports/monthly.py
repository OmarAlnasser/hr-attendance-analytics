"""Monthly HR attendance & performance report (PDF, ReportLab + matplotlib).

The report is in English: ReportLab cannot shape Arabic script without extra
libraries (arabic-reshaper + python-bidi). See docs/assumptions.md.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,  # noqa: E402
                                Table, TableStyle)

from ..db import repos  # noqa: E402
from ..domain.metrics import evaluable_employee_months, attendance_kpis, fmt_num, fmt_pct, grouped_attendance_kpis, performance_kpis  # noqa: E402
from ..domain.scoring import parse_period  # noqa: E402
from ..security.scope import UserContext  # noqa: E402
from ..services.review import RULES, review_cases  # noqa: E402

INK = colors.HexColor("#1D2B3A")
ACCENT = colors.HexColor("#1F6F5C")
MUTED = colors.HexColor("#5B6B7B")
RULE = colors.HexColor("#D5DBE1")
BAND = colors.HexColor("#EEF2F5")
WARN = colors.HexColor("#9A3B34")
SYSTEM_USER = UserContext(user_id=0, username="system", role="hr", employee_id=None)
from ..domain.metrics import EVALUABLE_MIN_DAYS  # noqa: E402,F811  (re-exported)
C_PRESENT, C_LATE, C_ABSENT = "#3A8F6B", "#D99A1E", "#C2453D"


def _styles():
    ss = getSampleStyleSheet()
    base = dict(fontName="Helvetica", textColor=INK, alignment=TA_LEFT)
    return {
        "title": ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold", fontSize=18, leading=22,
                                textColor=INK, alignment=TA_LEFT, spaceAfter=2),
        "h2": ParagraphStyle("h2", parent=ss["Heading2"], fontName="Helvetica-Bold", fontSize=12.5, leading=16,
                             textColor=INK, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("b", parent=ss["BodyText"], fontSize=9.2, leading=12.5, **base),
        "small": ParagraphStyle("s", parent=ss["BodyText"], fontSize=8, leading=10.5, textColor=MUTED,
                                fontName="Helvetica"),
        "warn": ParagraphStyle("w", parent=ss["BodyText"], fontSize=8.6, leading=11, textColor=WARN,
                               fontName="Helvetica-Bold"),
        "cell": ParagraphStyle("c", fontName="Helvetica", fontSize=8.2, leading=10, textColor=INK),
    }


def _table(data, col_widths, header=True, zebra=True):
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8.4),
        ("TEXTCOLOR", (0, 0), (-1, -1), INK),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
        ("LINEBELOW", (0, -1), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style.append(("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.4))
    if zebra:
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), BAND))
    t.setStyle(TableStyle(style))
    return t


def _fig_to_image(fig, width_mm: float) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    img = Image(buf)
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth = width_mm * mm
    img.drawHeight = width_mm * mm * ratio
    return img


def _style_axes(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#9AA7B4")
    ax.tick_params(colors="#1D2B3A", labelsize=8)
    ax.grid(axis="y", color="#E4E8EC", linewidth=0.6)
    ax.set_axisbelow(True)


def _daily_chart(att: pd.DataFrame):
    exp = att[att.status.isin(["present", "incomplete", "absent"])].copy()
    if exp.empty:
        return None
    exp["attended"] = exp.status.isin(["present", "incomplete"]).astype(int)
    exp["late"] = ((exp.is_late == 1) & (exp.attended == 1)).astype(int)
    daily = exp.groupby("shift_date").agg(expected=("status", "size"), attended=("attended", "sum"), late=("late", "sum"))
    daily["attendance_rate"] = daily.attended / daily.expected
    daily["late_rate"] = daily.late / daily.attended.where(daily.attended > 0)
    x = pd.to_datetime(daily.index)
    fig, ax = plt.subplots(figsize=(7.2, 1.9))
    ax.plot(x, daily.attendance_rate * 100, color=C_PRESENT, lw=1.8, label="Attendance rate")
    ax.plot(x, daily.late_rate * 100, color=C_LATE, lw=1.4, label="Late rate (of attended)")
    ax.set_ylim(0, 105)
    ax.set_ylabel("%", fontsize=8, color="#1D2B3A")
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d %b"))
    _style_axes(ax)
    ax.legend(frameon=False, fontsize=7.5, loc="center left", ncol=2)
    return fig


def _dept_chart(dept: pd.DataFrame):
    if dept.empty or len(dept) < 2:
        return None
    d = dept.sort_values("attendance_rate")
    fig, ax = plt.subplots(figsize=(7.2, 0.35 * len(d) + 0.9))
    y = range(len(d))
    ax.barh([i + 0.2 for i in y], d.attendance_rate * 100, height=0.38, color=C_PRESENT, label="Attendance rate")
    ax.barh([i - 0.2 for i in y], d.late_rate.fillna(0) * 100, height=0.38, color=C_LATE, label="Late rate")
    ax.set_yticks(list(y))
    ax.set_yticklabels(d.department_name, fontsize=8)
    ax.set_xlim(0, 100)
    ax.set_xlabel("%", fontsize=8)
    _style_axes(ax)
    ax.grid(axis="x", color="#E4E8EC", linewidth=0.6)
    ax.grid(axis="y", visible=False)
    ax.legend(frameon=False, fontsize=7.5, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
    return fig


def _score_chart(ev: pd.DataFrame, threshold: float):
    if ev.empty:
        return None
    fig, ax = plt.subplots(figsize=(7.2, 1.8))
    bins = [1 + 0.25 * i for i in range(17)]
    ax.hist(ev.weighted_score, bins=bins, color="#3D7CC9", edgecolor="white")
    ax.axvline(threshold, color=C_ABSENT, lw=1.2, ls="--")
    top = ax.get_ylim()[1] * 1.18
    ax.set_ylim(0, top)
    ax.text(threshold - 0.04, top * 0.9, f"review threshold {threshold:g}", fontsize=7.5, color=C_ABSENT, ha="right")
    ax.set_xlim(1, 5)
    ax.set_xlabel("Weighted score (1-5)", fontsize=8)
    ax.set_ylabel("Employees", fontsize=8)
    _style_axes(ax)
    return fig


def build_monthly_report(conn, *, period: str, department_id: int | None, settings, out_path: str | Path) -> Path:
    first, last = parse_period(period)
    s = _styles()
    user = SYSTEM_USER
    dept_name = None
    if department_id:
        dept = repos.get_department(conn, department_id)
        dept_name = dept["name"] if dept else f"#{department_id}"

    att = repos.attendance_frame(conn, user, first.isoformat(), last.isoformat(), department_id)
    ev = repos.evaluations_frame(conn, user, period, period, department_id)
    emps = repos.employees_frame(conn, user, department_id)
    ak = attendance_kpis(att)
    pk = performance_kpis(ev, evaluable_employee_months(emps, first, last), settings.LOW_SCORE_THRESHOLD)
    by_dept = grouped_attendance_kpis(att, "department_name") if not att.empty else pd.DataFrame()
    cases = review_cases(conn, user, period, threshold=settings.LOW_SCORE_THRESHOLD, department_id=department_id)

    lo_dt, hi_dt = f"{first} 00:00:00", f"{last} 23:59:59"
    batches = repos.batches_overlapping(conn, lo_dt, hi_dt)
    rejects = repos.reject_summary(conn, [b["batch_id"] for b in batches]) if batches else []
    exceptions = repos.exceptions_summary(conn, lo_dt, f"{last} 23:59:59", user)
    illustrative = conn.execute("SELECT holiday_date, name FROM holidays WHERE is_illustrative = 1 "
                                "AND holiday_date BETWEEN ? AND ?", (first.isoformat(), last.isoformat())).fetchall()
    synthetic = conn.execute("SELECT COUNT(*) FROM employees WHERE is_synthetic = 1").fetchone()[0] > 0

    story = []
    story.append(Paragraph("HR Attendance &amp; Performance — Monthly Report", s["title"]))
    story.append(Paragraph(f"Period <b>{first:%d %b %Y} – {last:%d %b %Y}</b> &nbsp;|&nbsp; "
                           f"Scope <b>{dept_name or 'All departments'}</b> &nbsp;|&nbsp; "
                           f"Generated {datetime.now():%Y-%m-%d %H:%M} &nbsp;|&nbsp; Rules {settings.RULE_VERSION}",
                           s["small"]))
    story.append(Spacer(1, 4))
    if synthetic:
        story.append(Paragraph("Synthetic demonstration data. These figures show how the system works; they are "
                               "not evidence of any real organisation's attendance or performance.", s["warn"]))
    story.append(Paragraph(f"Filters applied: period = {period}; department = {dept_name or 'all'}; "
                           f"employees counted only on days they were employed; review threshold = "
                           f"{settings.LOW_SCORE_THRESHOLD:g}.", s["small"]))

    story.append(Paragraph("Attendance", s["h2"]))
    rows = [["Indicator", "Value", "Basis"],
            ["Employees with records", f"{ak['employees']}", "distinct employees in scope"],
            ["Attendance rate", fmt_pct(ak["attendance_rate"]), f"{ak['attended_days']:,} / {ak['expected_days']:,} expected days"],
            ["Absence rate", fmt_pct(ak["absence_rate"]), f"{ak['absent_days']:,} absent days"],
            ["Late rate", fmt_pct(ak["late_rate"]), f"{ak['late_days']:,} late / {ak['attended_days']:,} attended days"],
            ["Average lateness (late days)", f"{fmt_num(ak['avg_late_minutes'])} min", "minutes after scheduled start"],
            ["Incomplete punches", fmt_pct(ak["incomplete_rate"]), f"{ak['incomplete_days']:,} single-punch days"],
            ["Early leave days", f"{ak['early_leave_days']:,}", "left before end minus grace"],
            ["Presence span (present days)", f"{fmt_num(ak['avg_presence_span_hours'], 2)} h",
             "first-to-last punch, not verified work time"],
            ["Approved leave / holiday days", f"{ak['leave_days']:,} / {ak['holiday_days']:,}", "excluded from rates"]]
    story.append(_table(rows, [58 * mm, 30 * mm, 86 * mm]))
    fig = _daily_chart(att)
    if fig:
        story.append(Spacer(1, 6))
        story.append(_fig_to_image(fig, 172))

    story.append(Paragraph("Performance", s["h2"]))
    rows = [["Indicator", "Value", "Basis"],
            ["Evaluations recorded", f"{pk['evaluations']}", f"of {pk['evaluable_employee_months']} evaluable employees"],
            ["Evaluation coverage", fmt_pct(pk["coverage"]), f"employed at least {EVALUABLE_MIN_DAYS} days in the month"],
            ["Average weighted score", fmt_num(pk["avg_weighted_score"], 2), "scale 1-5, weights snapshot per evaluation"],
            ["Below review threshold", f"{pk['low_score_count']} ({fmt_pct(pk['low_score_rate'])})",
             f"weighted score < {pk['threshold']:g}"]]
    story.append(_table(rows, [58 * mm, 30 * mm, 86 * mm]))
    fig = _score_chart(ev, settings.LOW_SCORE_THRESHOLD)
    if fig:
        story.append(Spacer(1, 6))
        story.append(_fig_to_image(fig, 172))

    if not by_dept.empty and not department_id:
        story.append(PageBreak())
        story.append(Paragraph("Department comparison", s["h2"]))
        story.append(Paragraph("Rates are pooled over expected days, so departments of different size are comparable. "
                               f"Departments with fewer than {settings.SMALL_SAMPLE_EMPLOYEES} employees are marked "
                               "and should be read with caution.", s["small"]))
        avg_score = ev.groupby("department_name").weighted_score.mean() if not ev.empty else pd.Series(dtype=float)
        rows = [["Department", "Employees", "Expected days", "Attendance", "Absence", "Late", "Avg score"]]
        for r in by_dept.sort_values("department_name").to_dict("records"):
            small = " *" if r["employees"] < settings.SMALL_SAMPLE_EMPLOYEES else ""
            rows.append([f"{r['department_name']}{small}", r["employees"], f"{r['expected_days']:,}",
                         fmt_pct(r["attendance_rate"]), fmt_pct(r["absence_rate"]), fmt_pct(r["late_rate"]),
                         fmt_num(avg_score.get(r["department_name"]), 2)])
        story.append(_table(rows, [50 * mm, 18 * mm, 24 * mm, 22 * mm, 20 * mm, 18 * mm, 22 * mm]))
        fig = _dept_chart(by_dept)
        if fig:
            story.append(Spacer(1, 6))
            story.append(_fig_to_image(fig, 172))

    story.append(Paragraph("Cases for human review", s["h2"]))
    story.append(Paragraph("Flags come from transparent rules, not from a prediction. They indicate where a "
                           "supportive conversation may help and must not be used for automatic or disciplinary "
                           "decisions.", s["small"]))
    if cases.empty:
        story.append(Paragraph("No rule was triggered in this period.", s["body"]))
    else:
        summary = cases.groupby("rule_code").employee_id.nunique()
        rows = [["Rule", "Employees"]] + [[RULES[k], int(v)] for k, v in summary.items()]
        story.append(_table(rows, [140 * mm, 34 * mm]))
        story.append(Spacer(1, 5))
        detail = cases.head(40)
        rows = [["Employee", "Department", "Rule", "Evidence"]] + [
            [r.employee_code, Paragraph(r.department_name, s["cell"]), r.rule_code, Paragraph(str(r.value), s["cell"])]
            for r in detail.itertuples()]
        t = _table(rows, [22 * mm, 42 * mm, 50 * mm, 60 * mm])
        t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "LEFT")]))
        story.append(t)
        if len(cases) > 40:
            story.append(Paragraph(f"{len(cases) - 40} more flags are listed on the Review page of the app.", s["small"]))

    story.append(Paragraph("Data quality", s["h2"]))
    dq = [["Check", "Result"],
          ["Import batches covering this period", str(len(batches))],
          ["Rows quarantined in those batches",
           ", ".join(f"{r['reason_code']}: {r['n']}" for r in rejects) or "none"],
          ["Punches outside employment / outside any shift window",
           ", ".join(f"{r['reason']}: {r['n']}" for r in exceptions) or "none"],
          ["Single-punch (incomplete) days", f"{ak['incomplete_days']:,}"],
          ["Days still pending (shift not finished when processed)", f"{ak['pending_days']:,}"],
          ["Work on days off or holidays (excluded from rates)", f"{ak['unscheduled_days']:,}"],
          ["Evaluable employees without an evaluation",
           str(max(0, pk["evaluable_employee_months"] - pk["evaluations"]))]]
    if illustrative:
        dq.append(["Holidays with illustrative (unverified) dates",
                   ", ".join(sorted({r['holiday_date'] for r in illustrative}))])
    t = _table([[Paragraph(str(c), s["cell"]) for c in row] for row in dq], [95 * mm, 79 * mm])
    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "LEFT")]))
    story.append(t)

    story.append(KeepTogether([
        Paragraph("Definitions", s["h2"]),
        Paragraph("<b>Expected day</b>: scheduled working day inside employment, not on approved leave or a public "
                  "holiday, whose shift has ended. <b>Attended</b>: at least one punch. <b>Late</b>: first punch "
                  "(minute resolution) after start + grace; exactly at the grace limit is on time. "
                  "<b>Absent</b>: expected day with no punch, decided only after the shift ends. "
                  "<b>Incomplete</b>: one punch only. <b>Presence span</b>: first to last punch; breaks and "
                  "unrecorded exits are unknown, so this is not confirmed working time. Night shifts count on the "
                  "date they start. <b>Weighted score</b>: sum(score x weight)/100 on a 1-5 scale.", s["body"]),
    ]))

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def on_page(canvas, doc):
        canvas.saveState()
        w, h = A4
        canvas.setFillColor(ACCENT)
        canvas.rect(0, h - 6 * mm, w, 6 * mm, stroke=0, fill=1)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        label = "SYNTHETIC DEMO DATA — not evidence of real outcomes" if synthetic else "Confidential — HR internal"
        canvas.drawString(18 * mm, 10 * mm, f"{label}   |   {period}   |   {dept_name or 'All departments'}")
        canvas.drawRightString(w - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=14 * mm, bottomMargin=18 * mm,
                            title=f"HR monthly report {period}", author="HR Analytics System",
                            subject="Synthetic demonstration data" if synthetic else "HR monthly report")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return out_path
