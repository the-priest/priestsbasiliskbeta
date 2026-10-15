#!/usr/bin/env python3
"""test_theme.py — the Claude-coloured dark theme is pinned, not described.

The accent has migrated red -> blue -> grey -> (interim green) -> Claude coral.
Each migration left cold accent hexes hardcoded in dozens of custom-widget rules
that a token-only change did not touch — which is exactly why the UI "still
looked black and grey" after the accent token alone was changed. This suite
fails if any of the retired accent colours creep back, if the coral stops
carrying the accent, or if a semantic colour (danger/amber/success) gets
swept up in a re-tint. Stdlib-only, no GTK needed.

Run:  python3 tests/test_theme.py
"""
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_p = _f = 0


def ck(name, cond, detail=""):
    global _p, _f
    if cond:
        _p += 1
        print(f"  PASS {name}")
    else:
        _f += 1
        print(f"  FAIL {name}" + (f"   [{detail}]" if detail else ""))


_bsrc = open(os.path.join(_ROOT, "basilisk.py"), "rb").read()
_m = re.search(rb'CSS = b"""(.*?)"""', _bsrc, re.S)
ck("the CSS bytes literal is present", bool(_m))
_css_bytes = _m.group(1) if _m else b""
_css = _css_bytes.decode("latin-1")

print("\n== the bytes literal stays ASCII-only (GTK loads it as bytes) ==")
ck("CSS is ASCII-only",
   all(b < 128 for b in _css_bytes),
   str([hex(b) for b in _css_bytes if b > 127][:5]))

print("\n== retired accent colours are gone ==")
# Every accent colour from a previous era must be fully migrated — no stragglers
# hiding in a custom-widget rule.
for retired, era in (("#45484a", "grey accent-hi"),
                     ("#292a2b", "grey accent-base"),
                     ("#55c295", "interim phosphor-green"),
                     ("rgba(69, 72, 74", "grey accent glow"),
                     ("rgba(85, 194, 149", "green accent glow")):
    ck(f"no {era} ({retired}) remains", _css.count(retired) == 0,
       f"{_css.count(retired)} left")

print("\n== Claude coral carries the accent ==")
ck("coral #d97757 is used widely (not just one token)",
   _css.count("#d97757") >= 20, str(_css.count("#d97757")))
ck("a deeper coral #a94f34 provides the two-tone accent",
   _css.count("#a94f34") >= 1, str(_css.count("#a94f34")))
ck("coral glow rgba(217, 119, 87 is present",
   _css.count("rgba(217, 119, 87") >= 1, str(_css.count("rgba(217, 119, 87")))
ck("the accent token is coral",
   "@define-color accent_color              #d97757;" in _css
   or re.search(r"accent_color\s+#d97757;", _css) is not None)
ck("suggested-action fill is coral (#c15f3c), white text",
   re.search(r"accent_bg_color\s+#c15f3c;", _css) is not None
   and re.search(r"accent_fg_color\s+#ffffff;", _css) is not None)
ck("the online 'ready' dot is coral",
   re.search(r"\.online-dot\.online\s*\{[^}]*#d97757", _css) is not None)

print("\n== semantic colours were NOT swept into the re-tint ==")
ck("danger red #e5484d survived", _css.count("#e5484d") >= 5,
   str(_css.count("#e5484d")))
ck("warning amber #f0a500 survived", _css.count("#f0a500") >= 3,
   str(_css.count("#f0a500")))
ck("success green #2ecc71 survived", _css.count("#2ecc71") >= 3,
   str(_css.count("#2ecc71")))
# coral must not collide with danger red — they must stay distinguishable
ck("coral and danger red are different colours",
   "#d97757" != "#e5484d")

print("\n== the theme still describes itself honestly ==")
ck("the palette comment names the Claude/coral theme, not the old blue/Kali one",
   "Claude" in _css and "dragon-blue accent (#a94f34" not in _css)


# ── THE UI-SCALE REWRITER MUST READ A NUMBER AS A NUMBER ─────────────
# _PX_RE was r'(\d+)px'. In "0.8px" that matches only the "8", so _scale_css
# read a 0.8px hairline as EIGHT pixels, scaled it, and pasted the result back
# after the "0." -- turning 0.8px into 0.12px at ui_scale 1.5. A 7x shrink in
# the wrong direction. "10.5px" grew by 0.3px instead of 50% for the same
# reason. Seven values in the sheet were affected, and only at a ui_scale
# other than 1.0, which is why nothing caught it: every test ran at 1.0, where
# _scale_css returns early and the regex never runs.
print("\n== the px scaler reads whole numbers, decimals included ==")

_app_src = _bsrc.decode("utf-8", "replace")
_px_src = re.search(r"_PX_RE = re\.compile\((r'[^']*')\)", _app_src)
ck("_PX_RE was found", _px_src is not None)
_PX = re.compile(eval(_px_src.group(1))) if _px_src else None


def _scaled(text, mult):
    """_scale_css's replacement, driven by the shipped regex."""
    def repl(m):
        raw = m.group(1)
        n = float(raw)
        if n <= 2:
            return f"{raw}px"
        out = max(1.0, n * mult)
        if abs(out - round(out)) < 0.05:
            return f"{int(round(out))}px"
        return f"{round(out, 1):g}px"
    return _PX.sub(repl, text)


if _PX:
    ck("the pattern matches a decimal value whole",
       _PX.findall("0.8px") == ["0.8"], str(_PX.findall("0.8px")))
    ck("...and a value with digits on both sides",
       _PX.findall("10.5px") == ["10.5"], str(_PX.findall("10.5px")))
    ck("...and a plain integer, as before",
       _PX.findall("16px") == ["16"])

    for _v, _want, _why in [
        ("16px", "24px", "an integer scales as it always did"),
        ("14px", "21px", "and stays an integer, not 21.0px"),
        ("1px", "1px", "a hairline is left alone"),
        ("2px", "2px", "so is 2px"),
        ("0.8px", "0.8px", "a SUB-pixel hairline is left alone - it used to "
                           "come out as 0.12px"),
        ("0.5px", "0.5px", "same"),
        ("10.5px", "15.8px", "a fractional value over 2px scales properly - "
                             "it used to come out as 10.8px"),
        ("2.2px", "3.3px", "and so does one just over the hairline floor"),
    ]:
        _got = _scaled(_v, 1.5)
        ck(f"at 1.5x, {_v} -> {_want}", _got == _want, f"got {_got}: {_why}")

    # And nothing in the real sheet comes out malformed at any scale.
    for _mult in (1.25, 1.5, 2.0):
        _out = _scaled(_css, _mult)
        _bad = re.findall(r"\d*\.\d+\.\d+px", _out)
        ck(f"the whole sheet survives {_mult}x with no malformed number",
           not _bad, str(_bad[:4]))
        ck(f"...and no 0.12px-style corruption at {_mult}x",
           "0.12px" not in _out)

print(f"\ntheme: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
