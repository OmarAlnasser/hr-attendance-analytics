"""Collect every sentence marked for translation: `_("...")` and `N_("...")` in the
Python code (read with the ast module, so implicitly joined strings count as one),
and `_('...')` / `_("...")` in the Jinja templates."""
from __future__ import annotations

import ast
import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "hr_analytics"
_TEMPLATE_CALL = re.compile(r"""\b_\(\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")""")


def python_strings() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in PKG.rglob("*.py"):
        if path.name == "i18n_ar.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("_", "N_")
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.setdefault(node.args[0].value, f"{path.relative_to(PKG)}:{node.lineno}")
    return found


def template_strings() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in (PKG / "web" / "templates").glob("*.html"):
        text = path.read_text(encoding="utf-8")
        for m in _TEMPLATE_CALL.finditer(text):
            s = m.group(1) if m.group(1) is not None else m.group(2)
            s = s.replace("\\'", "'").replace('\\"', '"')
            found.setdefault(s, f"templates/{path.name}:{text.count(chr(10), 0, m.start()) + 1}")
    return found


def all_strings() -> dict[str, str]:
    return {**template_strings(), **python_strings()}


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(PKG.parent))
    from hr_analytics.i18n_ar import AR
    missing = {k: v for k, v in all_strings().items() if k not in AR}
    for k, where in sorted(missing.items(), key=lambda kv: kv[1]):
        print(f"{where}\t{k!r}")
    print(len(missing), "missing of", len(all_strings()), file=sys.stderr)
