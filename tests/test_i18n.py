"""Arabic and English: every sentence has an Arabic version, pages switch direction,
no stored code ever reaches a reader, and the Arabic PDF is drawn with an Arabic font."""
import re
import unittest
from datetime import date

from hr_analytics import labels as L
from hr_analytics.i18n import ar_count, count, use_lang
from hr_analytics.i18n_ar import AR
from hr_analytics.reports.runner import report_language, run_monthly_report

from .i18n_strings import all_strings
from .test_web_access import WebTestBase

PLACEHOLDER = re.compile(r"{(\w+)}")
ARABIC = re.compile(r"[؀-ۿ]")
# codes the database stores; none of them may appear on a page or in a report
RAW_CODES = ("missing_out_punch", "missing_in_punch", "collapsed_", "near_duplicate", "UNKNOWN_BADGE",
             "INVALID_TIMESTAMP", "SCORE_BELOW_THRESHOLD", "LATE_RATE_30", "ABSENCE_3PLUS", "INCOMPLETE_3PLUS",
             "unscheduled_work", "day_off")


class DictionaryTests(unittest.TestCase):
    def test_every_sentence_has_an_arabic_version(self):
        missing = {k: where for k, where in all_strings().items() if k not in AR}
        self.assertEqual(missing, {}, "add these to hr_analytics/i18n_ar.py")

    def test_no_leftover_entries(self):
        used = all_strings()
        self.assertEqual([k for k in AR if k not in used], [], "remove sentences the code no longer uses")

    def test_placeholders_match_and_values_are_arabic(self):
        for en, ar in AR.items():
            self.assertEqual(set(PLACEHOLDER.findall(en)), set(PLACEHOLDER.findall(ar)), en)
            self.assertRegex(ar, ARABIC, en)

    def test_arabic_number_agreement(self):
        days = ("يوم واحد", "يومان", "أيام", "يومًا")
        self.assertEqual(ar_count(1, *days), "يوم واحد")
        self.assertEqual(ar_count(2, *days), "يومان")
        self.assertEqual(ar_count(3, *days), "3 أيام")
        self.assertEqual(ar_count(10, *days), "10 أيام")
        self.assertEqual(ar_count(11, *days), "11 يومًا")
        self.assertEqual(ar_count(99, *days), "99 يومًا")
        self.assertEqual(ar_count(100, *days), "100 يوم")
        self.assertEqual(ar_count(103, *days), "103 أيام")
        with use_lang("en"):
            self.assertEqual(count(1, "day"), "1 day")
            self.assertEqual(count(1200, "day"), "1,200 days")

    def test_labels_cover_every_code_in_both_languages(self):
        from hr_analytics.domain.attendance_rules import ALL_STATUSES
        from hr_analytics.services.requests import LEAVE_TYPES
        for lang in ("en", "ar"):
            with use_lang(lang):
                for s in ALL_STATUSES:
                    self.assertNotIn("_", L.status_label(s))
                for t in LEAVE_TYPES:
                    self.assertNotIn("_", L.leave_type_label(t))
                for code in L.REJECT_REASONS:
                    self.assertNotIn("_", L.reject_reason_label(code))
                self.assertEqual(L.note_labels("collapsed_2_near_duplicate_punches"), [],
                                 "merged double taps are routine and never shown")
        with use_lang("ar"):
            self.assertEqual(L.note_labels("missing_out_punch"), ["لا توجد بصمة خروج"])
            self.assertEqual(L.reject_summary({"UNKNOWN_BADGE": 6}), "بطاقات غير معروفة: 6")
            self.assertEqual(L.role_label("hr", "F"), "مسؤولة الموارد البشرية")
            self.assertEqual(L.long_date(date(2026, 9, 1)), "1 سبتمبر 2026")
        with use_lang("en"):
            self.assertEqual(L.reject_summary({"UNKNOWN_BADGE": 6, "INVALID_TIMESTAMP": 1}),
                             "6 unknown badges, 1 unreadable time")
            self.assertEqual(L.rule_evidence("SCORE_BELOW_THRESHOLD", {"score": 2.1, "threshold": 3}),
                             "Score 2.10 (review below 3.00)")


class ArabicPagesTests(WebTestBase, unittest.TestCase):
    PAGES = ("/", "/attendance?start=2026-03-01&end=2026-03-31", "/employees/{E002}?period=2026-03",
             "/today?date=2026-03-02&time=09:00", "/approvals", "/requests", "/evaluations/?period=2026-03",
             "/evaluations/weights", "/review/?period=2026-03", "/reports/", "/imports/", "/imports/1",
             "/employees", "/employees/import", "/users", "/departments", "/shifts", "/calendar", "/audit",
             "/account")

    def arabic_client(self, username):
        c = self.client_for(username)
        self.assertEqual(c.get("/lang/ar?next=/").status_code, 302)
        return c

    def test_switching_language_turns_the_page_right_to_left(self):
        c = self.client_for("hr1")
        self.assertIn('dir="ltr"', c.get("/").get_data(as_text=True))
        c.get("/lang/ar?next=/")
        page = c.get("/").get_data(as_text=True)
        self.assertIn('<html lang="ar" dir="rtl">', page)
        self.assertIn("نظرة عامة", page)
        c.get("/lang/en?next=/")
        self.assertIn('dir="ltr"', c.get("/").get_data(as_text=True))
        # an unknown language or an outside address is ignored
        self.assertEqual(c.get("/lang/xx?next=//evil.example/").headers["Location"], "/")

    def test_sign_in_page_offers_the_other_language(self):
        page = self.app.test_client().get("/login", headers={"Accept-Language": "ar-SA,ar;q=0.9"})
        self.assertIn('dir="rtl"', page.get_data(as_text=True), "Arabic browsers get Arabic first")

    def test_every_page_renders_in_arabic_without_codes(self):
        c = self.arabic_client("hr1")
        for path in self.PAGES:
            path = path.format(E002=self.ids["E002"])
            r = c.get(path)
            self.assertEqual(r.status_code, 200, path)
            html = r.get_data(as_text=True)
            self.assertIn('dir="rtl"', html, path)
            text = re.sub(r"<[^>]+>", " ", html)          # visible text only, not class names
            for code in RAW_CODES:
                self.assertNotIn(code, text, f"{code} shown on {path}")

    def test_profile_card_shows_name_role_and_initials(self):
        page = self.arabic_client("mgr_ops").get("/").get_data(as_text=True)
        self.assertIn('class="profile"', page)
        self.assertIn("مدير القسم", page)


class ArabicReportTests(WebTestBase, unittest.TestCase):
    def test_arabic_pdf_uses_an_arabic_font_and_is_kept_apart_from_english(self):
        en = run_monthly_report(self.conn, period="2026-03", department_id=None, settings=self.settings,
                                triggered_by="test")
        ar = run_monthly_report(self.conn, period="2026-03", department_id=None, settings=self.settings,
                                triggered_by="test", lang="ar")
        self.assertEqual((en.status, ar.status), ("success", "success"))
        self.assertNotEqual(en.output_path, ar.output_path)
        pdf = open(ar.output_path, "rb").read()
        self.assertIn(b"Tajawal", pdf)
        types = [r[0] for r in self.conn.execute("SELECT report_type FROM report_runs ORDER BY run_id")]
        self.assertEqual([report_language(t) for t in types], ["en", "ar"])
        again = run_monthly_report(self.conn, period="2026-03", department_id=None, settings=self.settings,
                                   triggered_by="test", lang="ar")
        self.assertEqual(again.status, "skipped", "one report per month, scope and language")

    def test_reports_page_prepares_an_arabic_report(self):
        c = self.client_for("hr1")
        from .support import token
        r = c.post("/reports/generate", data={"csrf_token": token(c), "period": "2026-03", "department_id": "",
                                              "lang": "ar"})
        self.assertEqual(r.status_code, 302)
        row = self.conn.execute("SELECT report_type, status FROM report_runs").fetchone()
        self.assertEqual(tuple(row), ("monthly_hr_ar", "success"))


if __name__ == "__main__":
    unittest.main()
