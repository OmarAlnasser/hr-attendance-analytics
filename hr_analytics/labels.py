"""Human wording for the codes the system stores.

The database keeps short codes (status 'incomplete', note 'missing_out_punch',
rule 'LATE_RATE_30', reason 'UNKNOWN_BADGE') because they are stable and easy
to query. People never see those codes: every screen, export and PDF goes
through the functions here, which return plain sentences in the page language.
Each entry is (English, Arabic).
"""
from __future__ import annotations

from .i18n import ar_count, current_lang


def pick(pair) -> str:
    return pair[1] if current_lang() == "ar" else pair[0]


def _lookup(table: dict, code, fallback: str | None = None) -> str:
    if code in table:
        return pick(table[code])
    return fallback if fallback is not None else (str(code or "").replace("_", " ").capitalize())


# ------------------------------------------------------------ daily status --
STATUS = {
    "present": ("Present", "حاضر"),
    "incomplete": ("Missing punch", "بصمة ناقصة"),
    "absent": ("Absent", "غائب"),
    "leave": ("On leave", "في إجازة"),
    "holiday": ("Public holiday", "إجازة رسمية"),
    "day_off": ("Day off", "يوم راحة"),
    "pending": ("Shift in progress", "الوردية لم تنتهِ"),
    "unscheduled_work": ("Worked on a day off", "عمل في يوم راحة"),
}
LATE = ("Late", "متأخر")
# The legend under the monthly ribbon (status key -> wording)
LEGEND = [
    ("present", ("On time", "في الموعد")), ("late", ("Late", "متأخر")),
    ("incomplete", ("Missing punch", "بصمة ناقصة")), ("absent", ("Absent", "غائب")),
    ("leave", ("Approved leave", "إجازة معتمدة")), ("holiday", ("Public holiday", "إجازة رسمية")),
    ("day_off", ("Day off", "يوم راحة")), ("unscheduled_work", ("Worked on a day off", "عمل في يوم راحة")),
    ("pending", ("Shift not finished", "الوردية لم تنتهِ")),
]


def status_label(code: str) -> str:
    return _lookup(STATUS, code)


def legend():
    return [(key, pick(text)) for key, text in LEGEND]


# ------------------------------------------------------------ day notes --
NOTES = {
    "missing_in_punch": ("No clock-in recorded", "لا توجد بصمة دخول"),
    "missing_out_punch": ("No clock-out recorded", "لا توجد بصمة خروج"),
    "open_shift": ("Shift still running", "الوردية ما زالت جارية"),
    "punches_on_approved_leave": ("Clocked in during approved leave", "سُجّلت بصمة خلال إجازة معتمدة"),
}
HIDDEN_NOTE_PREFIXES = ("collapsed_",)   # double taps merged into one punch: routine, not worth showing


def note_labels(notes: str | None) -> list[str]:
    out = []
    for code in (notes or "").split(";"):
        code = code.strip()
        if not code or code.startswith(HIDDEN_NOTE_PREFIXES):
            continue
        out.append(_lookup(NOTES, code))
    return out


def day_note(row) -> str:
    """One short line for the 'Notes' column of a day: leave type, holiday name or punch notes."""
    from .i18n import loc
    get = row.get if hasattr(row, "get") else (lambda k, d=None: getattr(row, k, d))
    if get("leave_type"):
        return leave_type_label(get("leave_type"))
    if get("holiday_name"):
        return str(loc(row, "holiday_name"))
    return " · ".join(note_labels(get("notes")))


# ------------------------------------------------------------ leave & requests --
LEAVE_TYPES = {
    "annual": ("Annual leave", "إجازة سنوية"),
    "sick": ("Sick leave", "إجازة مرضية"),
    "unpaid": ("Unpaid leave", "إجازة بدون راتب"),
    "other": ("Other leave", "إجازة أخرى"),
}
REQUEST_STATUS = {
    "pending": ("Waiting for a decision", "بانتظار القرار"),
    "approved": ("Approved", "معتمد"),
    "rejected": ("Rejected", "مرفوض"),
    "cancelled": ("Cancelled", "ملغى"),
}
PUNCH_KINDS = {"in": ("Clock-in", "بصمة دخول"), "out": ("Clock-out", "بصمة خروج")}


def leave_type_label(code: str) -> str:
    return _lookup(LEAVE_TYPES, code)


def request_status_label(code: str) -> str:
    return _lookup(REQUEST_STATUS, code)


def punch_kind_label(code: str) -> str:
    return _lookup(PUNCH_KINDS, code)


# ------------------------------------------------------------ roles --
# (English, Arabic for a man, Arabic for a woman)
ROLES = {
    "gm": ("General Manager", "المدير العام", "المديرة العامة"),
    "hr": ("HR officer", "مسؤول الموارد البشرية", "مسؤولة الموارد البشرية"),
    "manager": ("Department manager", "مدير القسم", "مديرة القسم"),
    "employee": ("Employee", "موظف", "موظفة"),
}


def role_label(role: str, gender: str | None = None) -> str:
    entry = ROLES.get(role)
    if entry is None:
        return str(role)
    if current_lang() == "ar":
        return entry[2] if gender == "F" else entry[1]
    return entry[0]


# ------------------------------------------------------------ review rules --
RULES = {
    "ABSENCE_3PLUS": (("Frequent absences", "غياب متكرر"),
                      ("Three or more unexcused absences in the month",
                       "ثلاثة أيام غياب أو أكثر دون عذر خلال الشهر")),
    "LATE_RATE_30": (("Often late", "تأخر متكرر"),
                     ("Late on at least 30% of the days attended (at least 5 days attended)",
                      "التأخر في 30% أو أكثر من أيام الحضور (بشرط حضور 5 أيام على الأقل)")),
    "INCOMPLETE_3PLUS": (("Repeated missing punches", "بصمات ناقصة متكررة"),
                         ("Three or more days with only one punch (no clock-in or no clock-out)",
                          "ثلاثة أيام أو أكثر ببصمة واحدة فقط (دون بصمة دخول أو خروج)")),
    "SCORE_BELOW_THRESHOLD": (("Low performance score", "درجة أداء منخفضة"),
                              ("Weighted performance score below the review threshold",
                               "الدرجة الموزونة للأداء أقل من حد المراجعة")),
    "SCORE_DROP_1": (("Sharp drop in score", "انخفاض حاد في الدرجة"),
                     ("Weighted score fell by 1.0 or more compared with the previous month",
                      "انخفضت الدرجة الموزونة بمقدار 1.0 أو أكثر مقارنة بالشهر السابق")),
}


def rule_title(code: str) -> str:
    return pick(RULES[code][0]) if code in RULES else str(code)


def rule_description(code: str) -> str:
    return pick(RULES[code][1]) if code in RULES else ""


def _days_ar(n: int) -> str:
    return ar_count(n, "يوم واحد", "يومان", "أيام", "يومًا")


def rule_evidence(code: str, f: dict) -> str:
    """The numbers behind one flag, as a short sentence."""
    ar = current_lang() == "ar"
    if code == "ABSENCE_3PLUS":
        n = int(f["n"])
        return f"غياب دون عذر: {_days_ar(n)}" if ar else f"{n} unexcused absences"
    if code == "LATE_RATE_30":
        n, of = int(f["n"]), int(f["of"])
        # digits after a colon avoid case endings; "of" is always 5 or more
        of_ar = f"{of} أيام حضور" if 3 <= of % 100 <= 10 else f"{of} يوم حضور"
        return (f"أيام التأخر: {n} من أصل {of_ar}" if ar
                else f"Late on {n} of {of} days attended")
    if code == "INCOMPLETE_3PLUS":
        n = int(f["n"])
        return f"بصمة ناقصة في {_days_ar(n)}" if ar else f"{n} days with a missing punch"
    if code == "SCORE_BELOW_THRESHOLD":
        return (f"الدرجة {f['score']:.2f} (حد المراجعة {f['threshold']:.2f})" if ar
                else f"Score {f['score']:.2f} (review below {f['threshold']:.2f})")
    if code == "SCORE_DROP_1":
        return (f"انخفضت من {f['previous']:.2f} إلى {f['score']:.2f}" if ar
                else f"Fell from {f['previous']:.2f} to {f['score']:.2f}")
    return ""


# ------------------------------------------------------------ import problems --
REJECT_REASONS = {
    "MISSING_BADGE": (("Badge number is empty", "رقم البطاقة فارغ"), ("missing badge number", "missing badge numbers"),
                      "أرقام بطاقات فارغة"),
    "UNKNOWN_BADGE": (("Badge is not linked to any employee", "البطاقة غير مرتبطة بأي موظف"),
                      ("unknown badge", "unknown badges"), "بطاقات غير معروفة"),
    "MISSING_TIMESTAMP": (("Time is empty", "وقت البصمة فارغ"), ("missing time", "missing times"), "أوقات فارغة"),
    "INVALID_TIMESTAMP": (("Time is in a format that cannot be read", "صيغة الوقت غير مقروءة"),
                          ("unreadable time", "unreadable times"), "أوقات بصيغة غير مقروءة"),
    "FUTURE_TIMESTAMP": (("Time is in the future", "الوقت في المستقبل"), ("time in the future", "times in the future"),
                         "أوقات في المستقبل"),
    "TIMESTAMP_TOO_OLD": (("Time is before the year 2000", "الوقت قبل عام 2000"),
                          ("time before 2000", "times before 2000"), "أوقات قبل عام 2000"),
}


def reject_reason_label(code: str) -> str:
    return pick(REJECT_REASONS[code][0]) if code in REJECT_REASONS else str(code)


def reject_summary(counts) -> str:
    """{'UNKNOWN_BADGE': 6, 'INVALID_TIMESTAMP': 4} -> '6 unknown badges, 4 unreadable times'."""
    items = counts.items() if hasattr(counts, "items") else counts
    parts = []
    for code, n in sorted(items, key=lambda kv: -int(kv[1])):
        n = int(n)
        entry = REJECT_REASONS.get(code)
        if entry is None:
            parts.append(f"{code}: {n}")
        elif current_lang() == "ar":
            parts.append(f"{entry[2]}: {n}")
        else:
            parts.append(f"{n} {entry[1][0] if n == 1 else entry[1][1]}")
    return ("، " if current_lang() == "ar" else ", ").join(parts)


# ------------------------------------------------------------ other statuses --
BATCH_STATUS = {
    "success": ("Loaded", "تم التحميل"),
    "partial": ("Loaded, some rows set aside", "تم التحميل مع استبعاد بعض الصفوف"),
    "failed": ("Failed", "تعذّر التحميل"),
}
REPORT_STATUS = {
    "success": ("Ready", "جاهز"),
    "running": ("Being prepared", "قيد الإعداد"),
    "failed": ("Failed", "تعذّر الإعداد"),
    "superseded": ("Replaced by a newer copy", "استُبدل بنسخة أحدث"),
}
EXCEPTIONS = {
    "outside_employment": ("Outside the employment dates", "خارج فترة التوظيف"),
    "no_shift_window": ("Not within any shift", "خارج أوقات الورديات"),
    "no_shift_assignment": ("No shift assigned", "لا توجد وردية مسندة"),
}
MODEL_METHODS = {"model": ("Model", "النموذج"), "rules": ("Rules", "القواعد")}
WEEKDAYS = {  # Python weekday() index -> (short English, Arabic, one-letter Arabic)
    0: ("Mon", "الاثنين", "ن"), 1: ("Tue", "الثلاثاء", "ث"), 2: ("Wed", "الأربعاء", "ر"), 3: ("Thu", "الخميس", "خ"),
    4: ("Fri", "الجمعة", "ج"), 5: ("Sat", "السبت", "س"), 6: ("Sun", "الأحد", "ح"),
}
WEEKDAY_BY_ABBR = {v[0]: k for k, v in WEEKDAYS.items()}


def batch_status_label(code: str) -> str:
    return _lookup(BATCH_STATUS, code)


def report_status_label(code: str) -> str:
    return _lookup(REPORT_STATUS, code)


def exception_label(code: str) -> str:
    return _lookup(EXCEPTIONS, code)


def model_method_label(code: str) -> str:
    return _lookup(MODEL_METHODS, code)


def weekday_name(index_or_abbr) -> str:
    i = WEEKDAY_BY_ABBR.get(index_or_abbr, index_or_abbr)
    en, ar, _letter = WEEKDAYS[int(i)]
    return ar if current_lang() == "ar" else en


def weekday_letter(index: int) -> str:
    en, _ar, letter = WEEKDAYS[int(index)]
    return letter if current_lang() == "ar" else en[0]


# ------------------------------------------------------------ audit log --
AUDIT_ACTIONS = {
    "login": ("Signed in", "تسجيل دخول"),
    "demo_login": ("Signed in to the demo", "دخول إلى النسخة التجريبية"),
    "login_failed": ("Failed sign-in", "محاولة دخول فاشلة"),
    "logout": ("Signed out", "تسجيل خروج"),
    "password_change": ("Changed password", "تغيير كلمة المرور"),
    "password_reset": ("Reset a password", "إعادة تعيين كلمة مرور"),
    "user_create": ("Created an account", "إنشاء حساب"),
    "user_disable": ("Disabled an account", "إيقاف حساب"),
    "user_enable": ("Re-enabled an account", "إعادة تفعيل حساب"),
    "user_disable_leavers": ("Disabled leavers' accounts", "إيقاف حسابات المنتهية خدماتهم"),
    "role_change": ("Changed a role", "تغيير صلاحية"),
    "employee_create": ("Added an employee", "إضافة موظف"),
    "employee_update": ("Edited an employee", "تعديل بيانات موظف"),
    "employee_bulk_import": ("Imported employees", "استيراد موظفين"),
    "department_create": ("Added a department", "إضافة قسم"),
    "department_update": ("Edited a department", "تعديل قسم"),
    "shift_create": ("Added a shift", "إضافة وردية"),
    "shift_update": ("Edited a shift", "تعديل وردية"),
    "holiday_save": ("Saved a public holiday", "حفظ إجازة رسمية"),
    "holiday_delete": ("Removed a public holiday", "حذف إجازة رسمية"),
    "leave_approve": ("Approved leave", "اعتماد إجازة"),
    "leave_reject": ("Rejected leave", "رفض إجازة"),
    "leave_request": ("Requested leave", "طلب إجازة"),
    "leave_cancel": ("Cancelled leave", "إلغاء إجازة"),
    "correction_request": ("Reported a missed punch", "الإبلاغ عن بصمة منسية"),
    "correction_approve": ("Approved a punch correction", "اعتماد تصحيح بصمة"),
    "correction_reject": ("Rejected a punch correction", "رفض تصحيح بصمة"),
    "correction_cancel": ("Withdrew a punch correction", "سحب تصحيح بصمة"),
    "evaluation_create": ("Saved an evaluation", "حفظ تقييم"),
    "evaluation_update": ("Changed an evaluation", "تعديل تقييم"),
    "weights_save": ("Changed score weights", "تعديل أوزان التقييم"),
    "import": ("Imported punches", "استيراد بصمات"),
    "process_attendance": ("Recalculated attendance", "إعادة احتساب الحضور"),
    "export": ("Exported data", "تصدير بيانات"),
    "report_success": ("Prepared a monthly report", "إعداد تقرير شهري"),
    "report_skipped": ("Asked for an existing report", "طلب تقرير موجود مسبقًا"),
    "report_failed": ("Monthly report failed", "تعذّر إعداد تقرير شهري"),
    "report_download": ("Downloaded a report", "تنزيل تقرير"),
    "seed": ("Loaded demo data", "تحميل البيانات التجريبية"),
    "create_user": ("Created an account (command line)", "إنشاء حساب من سطر الأوامر"),
}


def audit_action_label(code: str) -> str:
    return _lookup(AUDIT_ACTIONS, code)


# ------------------------------------------------------------ months and dates --
MONTHS = {
    1: ("Jan", "يناير"), 2: ("Feb", "فبراير"), 3: ("Mar", "مارس"), 4: ("Apr", "أبريل"), 5: ("May", "مايو"),
    6: ("Jun", "يونيو"), 7: ("Jul", "يوليو"), 8: ("Aug", "أغسطس"), 9: ("Sep", "سبتمبر"), 10: ("Oct", "أكتوبر"),
    11: ("Nov", "نوفمبر"), 12: ("Dec", "ديسمبر"),
}


def month_name(month: int) -> str:
    return pick(MONTHS[int(month)])


def long_date(d) -> str:
    """'1 Sep 2026' / '1 سبتمبر 2026'."""
    return f"{d.day} {month_name(d.month)} {d.year}"


def period_label(period: str) -> str:
    """'2026-09' -> 'Sep 2026' / 'سبتمبر 2026'."""
    year, month = str(period).split("-")[:2]
    return f"{month_name(int(month))} {year}"
