"""Two interface languages: English (default) and Arabic.

Every sentence the user can see is written in English in the code and the
templates and passed through `_()`. When the page language is Arabic, `_()`
returns the matching entry from `i18n_ar.AR`. Those entries are written as
Arabic in their own right (natural word order, correct agreement, a neutral
tone that does not assume the reader's gender), not as word-for-word
translations. tests/test_i18n.py fails if any sentence lacks an Arabic version.

The language of a request comes from the session (the switch in the sidebar
and on the sign-in page), else from the browser's Accept-Language header.
Code that runs outside a request (the CLI, the PDF report) can pick a
language with `use_lang("ar")`.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar

LANGS = {"en": "English", "ar": "العربية"}
DEFAULT_LANG = "en"
_override: ContextVar[str | None] = ContextVar("hr_lang_override", default=None)


def current_lang() -> str:
    forced = _override.get()
    if forced:
        return forced
    try:
        from flask import g, has_request_context
        if has_request_context():
            return getattr(g, "lang", DEFAULT_LANG)
    except ImportError:  # pragma: no cover
        pass
    return DEFAULT_LANG


def is_rtl(lang: str | None = None) -> bool:
    return (lang or current_lang()) == "ar"


@contextmanager
def use_lang(lang: str):
    token = _override.set(lang if lang in LANGS else DEFAULT_LANG)
    try:
        yield
    finally:
        _override.reset(token)


# A date such as 2026-08-31 inside an Arabic sentence would be shown as 31-08-2026 by the
# bidirectional algorithm (digits after Arabic letters become "Arabic numbers", and a hyphen
# does not hold those together). On web pages the value is wrapped in Unicode isolate marks
# (LRI ... PDI) so it keeps its order. The PDF formats its dates with month names instead.
_ISO_VALUE = re.compile(r"^\d{4}-\d{2}(-\d{2})?([ T]\d{2}:\d{2}(:\d{2})?)?$")


def _isolate(value):
    s = str(value)
    return f"\u2066{s}\u2069" if _ISO_VALUE.match(s) else value


def _in_request() -> bool:
    try:
        from flask import has_request_context
        return has_request_context() and _override.get() is None
    except ImportError:  # pragma: no cover
        return False


def _(text: str, **kw) -> str:
    """Translate one sentence. Placeholders use {name} and are filled from keyword arguments."""
    if current_lang() == "ar":
        from .i18n_ar import AR
        text = AR.get(text, text)
        if kw and _in_request():
            kw = {k: _isolate(v) for k, v in kw.items()}
    return text.format(**kw) if kw else text


def N_(text: str) -> str:
    """Marks a sentence for translation without translating it yet (module-level constants
    that are translated later with `_()`). The coverage test collects these too."""
    return text


def ar_count(n: int, one: str, two: str, few: str, many: str) -> str:
    """Arabic counted noun with the right number agreement:
    1 -> 'يوم واحد', 2 -> 'يومان', 3-10 -> '3 أيام', 11-99 -> '11 يومًا', 100/200... -> '100 يوم'."""
    n = int(n)
    if n == 1:
        return one
    if n == 2:
        return two
    rem = n % 100
    if 3 <= rem <= 10:
        return f"{n} {few}"
    if n >= 100 and rem in (0, 1, 2):
        return f"{n} {one.split()[0]}"
    return f"{n} {many}"


# Arabic noun forms used with ar_count: (one, two, few 3-10, many 11+)
AR_NOUNS = {
    "day": ("يوم واحد", "يومان", "أيام", "يومًا"),
    "employee": ("موظف واحد", "موظفان", "موظفين", "موظفًا"),
    "request": ("طلب واحد", "طلبان", "طلبات", "طلبًا"),
    "row": ("صف واحد", "صفان", "صفوف", "صفًا"),
    "account": ("حساب واحد", "حسابان", "حسابات", "حسابًا"),
    "minute": ("دقيقة واحدة", "دقيقتان", "دقائق", "دقيقة"),
    "evaluation": ("تقييم واحد", "تقييمان", "تقييمات", "تقييمًا"),
    "flag": ("ملاحظة واحدة", "ملاحظتان", "ملاحظات", "ملاحظة"),
    "punch": ("بصمة واحدة", "بصمتان", "بصمات", "بصمة"),
}

# English noun forms: (singular, plural)
EN_NOUNS = {
    "day": ("day", "days"), "employee": ("employee", "employees"), "request": ("request", "requests"),
    "row": ("row", "rows"), "account": ("account", "accounts"), "minute": ("minute", "minutes"),
    "evaluation": ("evaluation", "evaluations"), "flag": ("flag", "flags"), "punch": ("punch", "punches"),
}


def count(n, noun: str) -> str:
    """'3 days' / '3 أيام', with the right plural in either language."""
    n = int(n or 0)
    if current_lang() == "ar":
        if n == 0:
            return f"0 {AR_NOUNS[noun][3]}"
        return ar_count(n, *AR_NOUNS[noun])
    one, many = EN_NOUNS[noun]
    return f"{n:,} {one if n == 1 else many}"


def loc(row, field: str):
    """The Arabic version of a data field (e.g. full_name_ar) when the page is in Arabic and
    one exists; otherwise the field itself. Works with dicts and pandas rows."""
    def get(key):
        try:
            v = row.get(key) if hasattr(row, "get") else getattr(row, key, None)
        except Exception:  # noqa: BLE001
            return None
        if v is None or v == "" or (isinstance(v, float) and v != v):
            return None
        return v
    if current_lang() == "ar":
        v = get(field + "_ar")
        if v is not None:
            return v
    v = get(field)
    return "" if v is None else v
