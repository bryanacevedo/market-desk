"""Text colours against the grounds they sit on, measured from the CSS tokens: 4.5:1 for all text, 7:1 for the label colour used
under 13 px (WCAG 2.1 AA, and AAA where it was cheap)."""
from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web" / "src"


def tokens() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in ("styles.css", "market.css"):          # market.css overrides the shell's accent and status colours
        css = (WEB / name).read_text()
        root = re.search(r":root\s*\{([^}]*)\}", css, re.S).group(1)
        out.update({k: v for k, v in re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", root)})
    return out


def lum(h: str) -> float:
    r, g, b = (int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def ratio(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


GROUNDS = ("ground", "well", "well-2", "accent-wash")


def test_grey_text_is_at_least_4_5_to_1_on_every_ground():
    t = tokens()
    bad = {(fg, bg): round(ratio(t[fg], t[bg]), 2) for fg in ("mute", "faint", "ink-2", "ink", "label") for bg in GROUNDS if ratio(t[fg], t[bg]) < 4.5}
    assert not bad, bad


def test_the_label_colour_for_small_text_is_at_least_7_to_1_on_the_page_grounds():
    t = tokens()
    bad = {bg: round(ratio(t["label"], t[bg]), 2) for bg in ("ground", "well") if ratio(t["label"], t[bg]) < 7}
    assert not bad, bad


def test_status_and_link_colours_are_readable_as_text():
    t = tokens()
    bad = {(fg, bg): round(ratio(t[fg], t[bg]), 2) for fg in ("accent", "accent-2", "wait", "ok", "stop") for bg in ("ground", "well") if ratio(t[fg], t[bg]) < 4.5}
    assert not bad, bad


def test_the_small_label_selectors_use_the_label_colour():
    css = (WEB / "styles.css").read_text()
    for sel in (".nav .group", ".acting label", ".ledger .row.head", ".clock .note", ".fig > span", ".phone-nav a"):
        rule = next(line for line in css.splitlines() if line.startswith(sel) or f"  {sel} " in line and "{" in line)
        assert "var(--label)" in rule, sel
