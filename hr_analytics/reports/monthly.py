"""Monthly attendance and performance report (PDF, ReportLab + matplotlib).

Available in English and Arabic. Every sentence goes through `_()` and the
code labels in labels.py, so the PDF uses the same plain wording as the app.
The Arabic edition is laid out right to left: table columns are mirrored,
text is right-aligned, and Arabic script is shaped by reports/arabic.py.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_LEFT, TA_RIGHT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (Flowable, Image, KeepTogether, PageBreak, Paragraph,  # noqa: E402
                                SimpleDocTemplate, Spacer, Table, TableStyle)

from .. import labels as L  # noqa: E402
from ..db import repos  # noqa: E402
from ..domain.metrics import (EVALUABLE_MIN_DAYS, attendance_kpis, evaluable_employee_months, fmt_num,  # noqa: E402
                              fmt_pct, grouped_attendance_kpis, performance_kpis)
from ..domain.scoring import parse_period  # noqa: E402
from ..i18n import _, count, loc, use_lang  # noqa: E402
from ..security.scope import UserContext  # noqa: E402
from ..services.review import review_cases  # noqa: E402
from .arabic import AR_FONT, AR_FONT_BOLD, FONT_DIR, RTLParagraph, register_fonts, visual  # noqa: E402

INK = colors.HexColor("#1D2B3A")
ACCENT = colors.HexColor("#1F6F5C")
MUTED = colors.HexColor("#5B6B7B")
RULE = colors.HexColor("#D5DBE1")
BAND = colors.HexColor("#EEF2F5")
WARN = colors.HexColor("#9A3B34")
SYSTEM_USER = UserContext(user_id=0, username="system", role="hr", employee_id=None)
C_PRESENT, C_LATE, C_ABSENT = "#3A8F6B", "#D99A1E", "#C2453D"
_mpl_font_added = False


class Doc:
    """Language-aware building blocks: paragraphs, table cells, tables."""

    def __init__(self, lang: str):
        self.ar = lang == "ar"
        if self.ar:
            register_fonts()
        self.font = AR_FONT if self.ar else "Helvetica"
        self.bold = AR_FONT_BOLD if self.ar else "Helvetica-Bold"
        align = TA_RIGHT if self.ar else TA_LEFT
        # Arabic letters sit higher and need a little more line height
        lead = 1.18 if self.ar else 1.0

        def st(name, size, leading, color=INK, bold=False, before=0, after=0):
            return ParagraphStyle(name, fontName=self.bold if bold else self.font, fontSize=size,
                                  leading=leading * lead, textColor=color, alignment=align,
                                  spaceBefore=before, spaceAfter=after)
        self.s = {
            "title": st("title", 18, 23, bold=True, after=3),
            "h2": st("h2", 12.5, 16, bold=True, before=10, after=4),
            "body": st("body", 9.2, 12.5),
            "small": st("small", 8, 10.5, color=MUTED),
            "warn": st("warn", 8.6, 11, color=WARN, bold=True),
            "cell": st("cell", 8.2, 10),
        }

    def p(self, text, style="body") -> Flowable:
        if self.ar:
            return RTLParagraph(str(text), self.s[style])
        return Paragraph(escape(str(text)), self.s[style])

    def cell(self, text) -> Flowable:
        """A table cell that wraps long text."""
        return self.p(text, "cell")

    def t(self, text) -> str:
        """A short single-line string (table cell, chart label, page footer)."""
        return visual(text) if self.ar else str(text)

    def table(self, data, col_widths, align=None, zebra=True):
        """`align` gives 'L' or 'R' per column in reading order (default: first column 'L', the rest 'R').
        The Arabic edition mirrors the columns, so the first column ends up on the right."""
        n = len(col_widths)
        align = list(align or ["L"] + ["R"] * (n - 1))
        rows = [[c if isinstance(c, Flowable) else self.t(c) for c in row] for row in data]
        widths = list(col_widths)
        if self.ar:
            rows = [list(reversed(r)) for r in rows]
            widths.reverse()
            align = ["LEFT" if a == "R" else "RIGHT" for a in reversed(align)]
        else:
            align = ["LEFT" if a == "L" else "RIGHT" for a in align]
        tbl = Table(rows, colWidths=widths, repeatRows=1)
        style = [
            ("FONT", (0, 0), (-1, -1), self.font, 8.4),
            ("FONT", (0, 0), (-1, 0), self.bold, 8.4),
            ("TEXTCOLOR", (0, 0), (-1, -1), INK),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, INK),
            ("LINEBELOW", (0, -1), (-1, -1), 0.4, RULE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3 if not self.ar else 4),
        ]
        style += [("ALIGN", (i, 0), (i, -1), a) for i, a in enumerate(align)]
        if zebra:
            style += [("BACKGROUND", (0, i), (-1, i), BAND) for i in range(2, len(rows), 2)]
        tbl.setStyle(TableStyle(style))
        return tbl


# ------------------------------------------------------------------ charts --

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


def _chart_font(d: Doc) -> dict:
    global _mpl_font_added
    if not d.ar:
        return {}
    if not _mpl_font_added:
        for f in ("Tajawal-Regular.ttf", "Tajawal-Bold.ttf"):
            font_manager.fontManager.addfont(str(FONT_DIR / f))
        _mpl_font_added = True
    return {"font.family": "Tajawal"}


def _style_axes(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#9AA7B4")
    ax.tick_params(colors="#1D2B3A", labelsize=8)
    ax.grid(axis="y", color="#E4E8EC", linewidth=0.6)
    ax.set_axisbelow(True)


def _daily_chart(d: Doc, att: pd.DataFrame):
    exp = att[att.status.isin(["present", "incomplete", "absent"])].copy()
    if exp.empty:
        return None
    exp["attended"] = exp.status.isin(["present", "incomplete"]).astype(int)
    exp["late"] = ((exp.is_late == 1) & (exp.attended == 1)).astype(int)
    daily = exp.groupby("shift_date").agg(expected=("status", "size"), attended=("attended", "sum"),
                                          late=("late", "sum"))
    daily["attendance_rate"] = daily.attended / daily.expected
    daily["late_rate"] = daily.late / daily.attended.where(daily.attended > 0)
    x = pd.to_datetime(daily.index)
    with plt.rc_context(_chart_font(d)):
        fig, ax = plt.subplots(figsize=(7.2, 1.9))
        ax.plot(x, daily.attendance_rate * 100, color=C_PRESENT, lw=1.8, label=d.t(_("Attendance rate")))
        ax.plot(x, daily.late_rate * 100, color=C_LATE, lw=1.4, label=d.t(_("Late rate (share of days attended)")))
        ax.set_ylim(0, 105)
        ax.set_ylabel("%", fontsize=8, color="#1D2B3A")
        ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d/%m" if d.ar else "%d %b"))
        _style_axes(ax)
        ax.legend(frameon=False, fontsize=7.5, loc="center left", ncol=2)
    return fig


def _dept_chart(d: Doc, dept: pd.DataFrame):
    if dept.empty or len(dept) < 2:
        return None
    dd = dept.sort_values("attendance_rate")
    with plt.rc_context(_chart_font(d)):
        fig, ax = plt.subplots(figsize=(7.2, 0.35 * len(dd) + 0.9))
        y = range(len(dd))
        ax.barh([i + 0.2 for i in y], dd.attendance_rate * 100, height=0.38, color=C_PRESENT,
                label=d.t(_("Attendance rate")))
        ax.barh([i - 0.2 for i in y], dd.late_rate.fillna(0) * 100, height=0.38, color=C_LATE,
                label=d.t(_("Late rate")))
        ax.set_yticks(list(y))
        ax.set_yticklabels([d.t(n) for n in dd.label], fontsize=8)
        ax.set_xlim(0, 100)
        ax.set_xlabel("%", fontsize=8)
        _style_axes(ax)
        ax.grid(axis="x", color="#E4E8EC", linewidth=0.6)
        ax.grid(axis="y", visible=False)
        ax.legend(frameon=False, fontsize=7.5, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
    return fig


def _score_chart(d: Doc, ev: pd.DataFrame, threshold: float):
    if ev.empty:
        return None
    with plt.rc_context(_chart_font(d)):
        fig, ax = plt.subplots(figsize=(7.2, 1.8))
        bins = [1 + 0.25 * i for i in range(17)]
        ax.hist(ev.weighted_score, bins=bins, color="#3D7CC9", edgecolor="white")
        ax.axvline(threshold, color=C_ABSENT, lw=1.2, ls="--")
        top = ax.get_ylim()[1] * 1.18
        ax.set_ylim(0, top)
        ax.text(threshold - 0.04, top * 0.9, d.t(_("Review threshold {t}", t=f"{threshold:g}")), fontsize=7.5,
                color=C_ABSENT, ha="right")
        ax.set_xlim(1, 5)
        ax.set_xlabel(d.t(_("Weighted score (1 to 5)")), fontsize=8)
        ax.set_ylabel(d.t(_("Employees")), fontsize=8)
        _style_axes(ax)
    return fig


# ------------------------------------------------------------------ report --

def build_monthly_report(conn, *, period: str, department_id: int | None, settings, out_path: str | Path,
                         lang: str = "en") -> Path:
    with use_lang(lang):
        return _build(conn, period=period, department_id=department_id, settings=settings,
                      out_path=Path(out_path), lang=lang)


def _build(conn, *, period, department_id, settings, out_path: Path, lang: str) -> Path:
    first, last = parse_period(period)
    d = Doc(lang)
    user = SYSTEM_USER
    scope_name = _("All departments")
    if department_id:
        dept = repos.get_department(conn, department_id)
        scope_name = loc(dept, "name") if dept else f"#{department_id}"

    att = repos.attendance_frame(conn, user, first.isoformat(), last.isoformat(), department_id)
    ev = repos.evaluations_frame(conn, user, period, period, department_id)
    emps = repos.employees_frame(conn, user, department_id)
    ak = attendance_kpis(att)
    pk = performance_kpis(ev, evaluable_employee_months(emps, first, last), settings.LOW_SCORE_THRESHOLD)
    by_dept = grouped_attendance_kpis(att, "department_name") if not att.empty else pd.DataFrame()
    if not by_dept.empty:
        names = att.drop_duplicates("department_name").set_index("department_name")
        by_dept["label"] = [loc(names.loc[n], "department_name") for n in by_dept.department_name]
    cases = review_cases(conn, user, period, threshold=settings.LOW_SCORE_THRESHOLD, department_id=department_id)

    lo_dt, hi_dt = f"{first} 00:00:00", f"{last} 23:59:59"
    batches = repos.batches_overlapping(conn, lo_dt, hi_dt)
    rejects = repos.reject_summary(conn, [b["batch_id"] for b in batches]) if batches else []
    exceptions = repos.exceptions_summary(conn, lo_dt, hi_dt, user)
    estimated = conn.execute("SELECT holiday_date FROM holidays WHERE is_illustrative = 1 "
                             "AND holiday_date BETWEEN ? AND ?", (first.isoformat(), last.isoformat())).fetchall()
    synthetic = conn.execute("SELECT COUNT(*) FROM employees WHERE is_synthetic = 1").fetchone()[0] > 0
    threshold = f"{settings.LOW_SCORE_THRESHOLD:g}"
    rules_version = str(settings.RULE_VERSION).rsplit("-", 1)[-1]
    none = _("None")

    story: list = []
    story.append(d.p(_("Attendance and Performance: Monthly Report"), "title"))
    story.append(d.p(_("{start} to {end} · {scope} · Prepared {when} · Calculation rules version {v}",
                       start=L.long_date(first), end=L.long_date(last), scope=scope_name,
                       when=f"{L.long_date(datetime.now())} {datetime.now():%H:%M}", v=rules_version), "small"))
    story.append(Spacer(1, 4))
    if synthetic:
        story.append(d.p(_("Made-up demonstration data. These figures show how the system works; they say "
                           "nothing about any real organisation."), "warn"))
    story.append(d.p(_("What is counted: {month}, {scope}. Each employee is counted only on the days they were "
                       "employed. Scores below {t} are flagged for review.",
                       month=L.period_label(period), scope=scope_name, t=threshold), "small"))

    # ---- attendance
    story.append(d.p(_("Attendance"), "h2"))
    span = ak["avg_presence_span_hours"]
    rows = [[_("Measure"), _("Value"), _("How it is worked out")],
            [_("Employees with attendance records"), f"{ak['employees']}", d.cell(_("Everyone in scope who had at least one scheduled day"))],
            [_("Attendance rate"), fmt_pct(ak["attendance_rate"]),
             d.cell(_("Days attended: {a} of {b} working days", a=f"{ak['attended_days']:,}", b=f"{ak['expected_days']:,}"))],
            [_("Absence rate"), fmt_pct(ak["absence_rate"]),
             d.cell(_("Days absent without approved leave: {n}", n=f"{ak['absent_days']:,}"))],
            [_("Late rate"), fmt_pct(ak["late_rate"]),
             d.cell(_("Days late: {a}, out of {b} days attended", a=f"{ak['late_days']:,}", b=f"{ak['attended_days']:,}"))],
            [_("Average lateness"), _("{n} min", n=fmt_num(ak["avg_late_minutes"])),
             d.cell(_("Minutes after the shift start, on late days only"))],
            [_("Missing punches"), fmt_pct(ak["incomplete_rate"]),
             d.cell(_("Days with only one punch: {n}", n=f"{ak['incomplete_days']:,}"))],
            [_("Left early"), f"{ak['early_leave_days']:,}", d.cell(_("Days the last punch came before the shift end, allowing for the grace period"))],
            [_("Average hours present"), (_("{h} h", h=fmt_num(span, 2)) if span is not None else "–"),
             d.cell(_("First to last punch on full days; this is not confirmed working time"))],
            [_("Leave and public holidays"), f"{ak['leave_days']:,} / {ak['holiday_days']:,}",
             d.cell(_("Days on approved leave / public holidays; not counted in the rates"))]]
    story.append(d.table(rows, [56 * mm, 26 * mm, 92 * mm], align=["L", "R", "L"]))
    fig = _daily_chart(d, att)
    if fig:
        story += [Spacer(1, 6), _fig_to_image(fig, 172)]

    # ---- performance
    story.append(d.p(_("Performance"), "h2"))
    rows = [[_("Measure"), _("Value"), _("How it is worked out")],
            [_("Evaluations saved"), f"{pk['evaluations']}",
             d.cell(_("Employees who could be evaluated this month: {n}", n=pk["evaluable_employee_months"]))],
            [_("Evaluation coverage"), fmt_pct(pk["coverage"]),
             d.cell(_("Counts employees who worked at least {n} days in the month", n=EVALUABLE_MIN_DAYS))],
            [_("Average weighted score"), fmt_num(pk["avg_weighted_score"], 2),
             d.cell(_("On a scale of 1 to 5, using the weights in force when each evaluation was saved"))],
            [_("Below the review threshold"), f"{pk['low_score_count']} ({fmt_pct(pk['low_score_rate'])})",
             d.cell(_("Weighted score below {t}", t=f"{pk['threshold']:g}"))]]
    story.append(d.table(rows, [56 * mm, 26 * mm, 92 * mm], align=["L", "R", "L"]))
    fig = _score_chart(d, ev, settings.LOW_SCORE_THRESHOLD)
    if fig:
        story += [Spacer(1, 6), _fig_to_image(fig, 172)]

    # ---- departments
    if not by_dept.empty and not department_id:
        story.append(PageBreak())
        story.append(d.p(_("Departments side by side"), "h2"))
        story.append(d.p(_("Rates are calculated over working days, so large and small departments can be compared "
                           "fairly. Departments with fewer than {n} employees are marked with * and their figures "
                           "move a lot from month to month.", n=settings.SMALL_SAMPLE_EMPLOYEES), "small"))
        avg_score = ev.groupby("department_name").weighted_score.mean() if not ev.empty else pd.Series(dtype=float)
        rows = [[_("Department"), _("Employees"), _("Working days"), _("Attendance"), _("Absence"), _("Late"),
                 _("Average score")]]
        for r in by_dept.sort_values("label").to_dict("records"):
            small = " *" if r["employees"] < settings.SMALL_SAMPLE_EMPLOYEES else ""
            rows.append([f"{r['label']}{small}", r["employees"], f"{r['expected_days']:,}",
                         fmt_pct(r["attendance_rate"]), fmt_pct(r["absence_rate"]), fmt_pct(r["late_rate"]),
                         fmt_num(avg_score.get(r["department_name"]), 2)])
        story.append(d.table(rows, [50 * mm, 18 * mm, 24 * mm, 22 * mm, 20 * mm, 18 * mm, 22 * mm]))
        fig = _dept_chart(d, by_dept)
        if fig:
            story += [Spacer(1, 6), _fig_to_image(fig, 172)]

    # ---- review
    story.append(d.p(_("Employees worth a conversation"), "h2"))
    story.append(d.p(_("These flags come from simple rules anyone can check, not from a prediction. They point to "
                       "where a supportive conversation may help and must never be used on their own for a "
                       "decision about a person."), "small"))
    if cases.empty:
        story.append(d.p(_("No rule was triggered this month.")))
    else:
        summary = cases.groupby("rule_code").employee_id.nunique()
        rows = [[_("What was noticed"), _("Employees")]] + [
            [d.cell(f"{L.rule_title(k)}: {L.rule_description(k)}"), int(v)] for k, v in summary.items()]
        story.append(d.table(rows, [140 * mm, 34 * mm]))
        story.append(Spacer(1, 5))
        detail = cases.head(40)
        rows = [[_("Employee"), _("Department"), _("What was noticed"), _("The numbers")]] + [
            [d.cell(f"{r['employee_code']} · {loc(r, 'full_name')}"), d.cell(loc(r, "department_name")),
             d.cell(r["rule"]), d.cell(r["value"])]
            for r in detail.to_dict("records")]
        story.append(d.table(rows, [48 * mm, 36 * mm, 38 * mm, 52 * mm], align=["L", "L", "L", "L"]))
        if len(cases) > 40:
            story.append(d.p(_("{n} more are listed on the Review page of the app.", n=count(len(cases) - 40, "flag")),
                             "small"))

    # ---- data quality
    story.append(d.p(_("Data quality"), "h2"))
    rejected = L.reject_summary({r["reason_code"]: r["n"] for r in rejects}) or none
    unmatched = ("، " if d.ar else ", ").join(f"{L.exception_label(r['reason'])}: {r['n']}" for r in exceptions) or none
    dq = [[_("Check"), _("Result")],
          [_("Punch files imported for this month"), str(len(batches))],
          [_("Rows set aside during import"), rejected],
          [_("Punches that did not match a working day"), unmatched],
          [_("Days with a missing punch"), f"{ak['incomplete_days']:,}"],
          [_("Days whose shift had not finished when last calculated"), f"{ak['pending_days']:,}"],
          [_("Work on days off or public holidays (not counted in the rates)"), f"{ak['unscheduled_days']:,}"],
          [_("Employees still waiting for an evaluation"), str(max(0, pk["evaluable_employee_months"] - pk["evaluations"]))]]
    if estimated:
        dq.append([_("Public holidays whose dates are estimates, not confirmed"),
                   ", ".join(sorted({str(r[0]) for r in estimated}))])
    story.append(d.table([dq[0]] + [[d.cell(c) for c in row] for row in dq[1:]], [95 * mm, 79 * mm],
                         align=["L", "L"]))

    # ---- definitions
    terms = [
        (_("Working day"), _("A scheduled working day while the person is employed, not on approved leave or a "
                             "public holiday, and whose shift has ended.")),
        (_("Attended"), _("At least one punch on that day.")),
        (_("Late"), _("The first punch came after the shift start plus the grace period. A punch exactly at the end "
                      "of the grace period is on time.")),
        (_("Absent"), _("A working day with no punch at all. This is decided only after the shift has ended.")),
        (_("Missing punch"), _("Only one punch that day, so either the clock-in or the clock-out is missing.")),
        (_("Hours present"), _("Time from the first to the last punch. Breaks and unrecorded exits are unknown, so "
                               "this is not confirmed working time.")),
        (_("Night shift"), _("Counted on the date it starts.")),
        (_("Weighted score"), _("Each category score (1 to 5) multiplied by its weight, added up and divided by 100.")),
    ]
    rows = [[_("Term"), _("Meaning")]] + [[t, d.cell(m)] for t, m in terms]
    story.append(KeepTogether([d.p(_("Definitions"), "h2"),
                               d.table(rows, [38 * mm, 136 * mm], align=["L", "L"], zebra=False)]))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    footer = (_("Made-up demo data, not real results") if synthetic else _("Confidential: for HR use only"))
    footer = f"{footer}  ·  {L.period_label(period)}  ·  {scope_name}"

    def on_page(canvas, doc):
        canvas.saveState()
        w, h = A4
        canvas.setFillColor(ACCENT)
        canvas.rect(0, h - 6 * mm, w, 6 * mm, stroke=0, fill=1)
        canvas.setFont(d.font, 7.5)
        canvas.setFillColor(MUTED)
        page = _("Page {n}", n=doc.page)
        if d.ar:
            canvas.drawRightString(w - 18 * mm, 10 * mm, d.t(footer))
            canvas.drawString(18 * mm, 10 * mm, d.t(page))
        else:
            canvas.drawString(18 * mm, 10 * mm, footer)
            canvas.drawRightString(w - 18 * mm, 10 * mm, page)
        canvas.restoreState()

    title = _("Monthly attendance and performance report {period}", period=period)
    doc = SimpleDocTemplate(str(out_path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=14 * mm, bottomMargin=18 * mm, title=title, author=_("HR Analytics"),
                            subject=_("Made-up demonstration data") if synthetic else title, lang=lang)
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return out_path
