"""Arabic text in the PDF report.

ReportLab draws glyphs in the order it is given and does not join Arabic
letters, so Arabic text needs two steps before it is drawn:

1. arabic-reshaper picks the joined form of every letter (initial, medial,
   final or isolated), and
2. the Unicode bidirectional algorithm (python-bidi) puts the characters in
   visual order, so the sentence reads right to left while numbers and Latin
   codes such as E0101 still read left to right.

Line breaking has to happen *before* step 2, otherwise the first line of a
paragraph would show the end of the sentence. `RTLParagraph` does that:
it wraps the text in reading order, then reorders each line on its own.

The font is Tajawal (SIL Open Font License), shipped in web/static/fonts.
"""
from __future__ import annotations

from pathlib import Path

import arabic_reshaper
from bidi.algorithm import get_display  # the pure-Python version also mirrors brackets
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable

FONT_DIR = Path(__file__).resolve().parents[1] / "web" / "static" / "fonts"
AR_FONT, AR_FONT_BOLD = "Tajawal", "Tajawal-Bold"
_registered = False
_reshaper = None


def register_fonts() -> None:
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont(AR_FONT, str(FONT_DIR / "Tajawal-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(AR_FONT_BOLD, str(FONT_DIR / "Tajawal-Bold.ttf")))
    pdfmetrics.registerFontFamily(AR_FONT, normal=AR_FONT, bold=AR_FONT_BOLD, italic=AR_FONT, boldItalic=AR_FONT_BOLD)
    _registered = True


def _get_reshaper():
    # Tajawal draws isolated letters from the plain code points and has no glyphs for
    # word ligatures, so ask the reshaper for exactly what the font supports
    # (letter ligatures such as lam-alef only).
    global _reshaper
    if _reshaper is None:
        config = arabic_reshaper.config_for_true_type_font(str(FONT_DIR / "Tajawal-Regular.ttf"),
                                                           arabic_reshaper.ENABLE_LETTERS_LIGATURES)
        _reshaper = arabic_reshaper.ArabicReshaper(configuration=config)
    return _reshaper


def shape(text: str) -> str:
    """Reading-order text -> joined letters, still in reading order (for measuring)."""
    return _get_reshaper().reshape(str(text))


def visual(text: str) -> str:
    """Reading-order text -> a string ReportLab can draw left to right."""
    return get_display(shape(text), base_dir="R")


def wrap_lines(text: str, font: str, size: float, width: float) -> list[str]:
    """Greedy word wrap in reading order. Returns lines ready to draw (visual order)."""
    lines: list[str] = []
    for para in str(text).split("\n"):
        current = ""
        for word in para.split():
            candidate = f"{current} {word}" if current else word
            if current and stringWidth(shape(candidate), font, size) > width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return [visual(line) for line in lines]


class RTLParagraph(Flowable):
    """A right-aligned paragraph of Arabic text that wraps correctly and can split across pages."""

    def __init__(self, text: str, style: ParagraphStyle, lines: list[str] | None = None):
        super().__init__()
        self.text = text
        self.style = style
        self._lines = lines

    def wrap(self, avail_width, avail_height):
        self.width = avail_width
        if self._lines is None or getattr(self, "_wrapped_for", None) != avail_width:
            self._lines = wrap_lines(self.text, self.style.fontName, self.style.fontSize, avail_width)
            self._wrapped_for = avail_width
        self.height = len(self._lines) * self.style.leading
        return avail_width, self.height

    def split(self, avail_width, avail_height):
        self.wrap(avail_width, avail_height)
        fit = int(avail_height // self.style.leading)
        if fit <= 0 or fit >= len(self._lines):
            return [] if fit <= 0 else [self]
        head = RTLParagraph(self.text, self.style, self._lines[:fit])
        tail = RTLParagraph(self.text, self.style, self._lines[fit:])
        head._wrapped_for = tail._wrapped_for = avail_width
        return [head, tail]

    def draw(self):
        c = self.canv
        c.setFont(self.style.fontName, self.style.fontSize)
        c.setFillColor(self.style.textColor)
        # first baseline: same position ReportLab uses for a Paragraph
        y = self.height - self.style.fontSize
        for line in self._lines:
            c.drawRightString(self.width, y, line)
            y -= self.style.leading
