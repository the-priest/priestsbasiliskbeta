#!/usr/bin/env python3
"""test_themes.py — the theme PICKER: 8 palettes generated from one stylesheet.

test_theme.py pins the ember stylesheet as authored. This suite pins the layer
above it: the substitution system that turns that one stylesheet into eight
themes at load time.

Why generated and not forked. The palette is inlined ~250 times because GTK CSS
has no cross-rule variables, so the obvious way to add a theme is to copy the
whole 2,000-line stylesheet and recolour the copy. Two stylesheets diverge on
the first widget anyone adds, and from then on one theme silently misses every
new rule. A theme here is a substitution over the ember values, so it cannot
miss a rule: it does not know what rules exist. `ember` is the identity, which
is what keeps the original theme bit-for-bit what it always was — and is why
test_theme.py still passes unchanged.

What this suite will catch:
  * a theme whose depth ladder has gone flat (bg/surface/card/line must stay
    strictly increasing in luminance, or card edges and focus rings vanish)
  * a theme whose text, dim text, accent or button fill has fallen below a
    legible contrast ratio
  * an accent that has drifted onto a semantic colour, or a re-tint that has
    swept a semantic colour up with it
  * coral left behind by an incomplete substitution
  * a bad `theme` setting crashing instead of falling back

Stdlib-only, no GTK needed.

Run:  python3 tests/test_themes.py
"""
import colorsys  # noqa: F401  (used by the exec'd theme block)
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


# ── load the theme block without importing GTK ───────────────────────
# basilisk.py imports gi at module scope, so the whole file cannot be imported
# in a headless test. The theme machinery is deliberately self-contained
# (stdlib + re), so it is exec'd on its own — the same trick test_theme.py uses
# to reach the CSS literal.
_src = open(os.path.join(_ROOT, "basilisk.py"), encoding="utf-8").read()
_start = _src.find("# ── the ember palette")
_end = _src.find("def _themed_css")
ck("the theme block is present and self-contained",
   _start > 0 and _end > _start, f"start={_start} end={_end}")

_ns = {"re": re, "load_settings": lambda: {}}
if _start > 0 and _end > _start:
    exec(compile(_src[_start:_end], "basilisk.py:themes", "exec"), _ns)

THEMES = _ns.get("THEMES", {})
ORDER = _ns.get("THEME_ORDER", ())
DEFAULT_THEME = _ns.get("DEFAULT_THEME", "")
_retint = _ns.get("_retint_css")
NEUT = _ns.get("_EMBER_NEUTRALS", ())
INK = _ns.get("_EMBER_INK", ())
ACC = _ns.get("_EMBER_ACCENT", ())

# The CSS, so substitutions can be checked against the real stylesheet.
_m = re.search(rb'CSS = b"""(.*?)"""',
               open(os.path.join(_ROOT, "basilisk.py"), "rb").read(), re.S)
_CSS = _m.group(1) if _m else b""

# Semantic colours: NOT themed, in any theme.
_SEMANTIC = ("#e5484d", "#f0a500", "#2ecc71")


def _lum(h):
    h = h.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    c = [(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
         for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _ratio(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


print("\n== the picker offers eight themes ==")
ck("eight themes are defined", len(THEMES) == 8, str(sorted(THEMES)))
ck("THEME_ORDER lists them all, for a stable dropdown",
   set(ORDER) == set(THEMES) and len(ORDER) == len(THEMES), str(ORDER))
ck("every theme has a human label",
   all(isinstance(THEMES[k][0], str) and len(THEMES[k][0]) > 3
       for k in THEMES))
ck("the default is a real theme", DEFAULT_THEME in THEMES, DEFAULT_THEME)
ck("the operator's requested default is the purple one",
   DEFAULT_THEME == "violet", DEFAULT_THEME)

print("\n== ember is the IDENTITY (this is what protects test_theme.py) ==")
ck("ember substitutes nothing", THEMES.get("ember", ("", None))[1] == {})
if _retint and _CSS:
    ck("retinting to ember returns the stylesheet byte-for-byte",
       _retint(_CSS, "ember") == _CSS)
    ck("an unknown theme name falls back to unchanged, not a crash",
       _retint(_CSS, "no-such-theme") == _CSS)
    ck("an empty theme name is survivable", _retint(_CSS, "") == _CSS)
    ck("None is survivable", _retint(_CSS, None) == _CSS)

print("\n== every theme keeps the DEPTH LADDER (or cards lose their edges) ==")
for k in ORDER:
    table = THEMES[k][1]
    sub = lambda c: table.get(c, c)          # noqa: E731
    lums = [_lum(sub(c)) for c in NEUT]
    mono = all(lums[i] < lums[i + 1] for i in range(len(lums) - 1))
    ck(f"{k}: bg < sidebar < surface < card < line", mono,
       " ".join(f"{x:.4f}" for x in lums))

print("\n== every theme is VISIBLY different, not just technically ==")
# THE BUG THIS PINS: the first generator re-hued each ember neutral while
# keeping its exact lightness. The ladder was preserved, the contrast was fine,
# every assertion above passed — and the themes were invisible. Ember's base is
# L=0.035, and at three per cent lightness there is no room for chroma, so every
# hue lands on the same near-black. Measured surfaces moved 1-13 of 255 per
# channel. The accent changed and the other 90% of the window did not.
#
# "The ladder is monotonic and the contrast is legal" is therefore NOT enough to
# say a theme works. It also has to differ from the one it is replacing, by
# enough to see. 12/255 on the darkest surface is about the floor of
# perceptible on a dark panel; the deeper surfaces have more room, so they are
# held to more.
#
# Rung 0 is held to less than the rest, and that is a physical limit rather
# than a concession: the base surface sits at L=0.062, and a theme whose whole
# point is to be near-neutral (slate) cannot move far from ember's near-neutral
# base without ceasing to be near-neutral. The rungs that carry most of the
# visible area — surfaces, cards, lines — are held to progressively more, and
# the pairwise check below is what actually guarantees eight distinct looks.
_MIN_DELTA = (8, 14, 18, 22, 30)    # per ladder rung, darkest first


def _chan_delta(a, b):
    a, b = a.lstrip("#"), b.lstrip("#")
    return max(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16))
               for i in (0, 2, 4))


for k in ORDER:
    if k == "ember":
        continue
    table = THEMES[k][1]
    worst = []
    for i, c in enumerate(NEUT):
        d = _chan_delta(c, table.get(c, c))
        if d < _MIN_DELTA[i]:
            worst.append(f"rung{i} moved {d} (need {_MIN_DELTA[i]})")
    ck(f"{k}: surfaces are visibly different from ember", not worst,
       "; ".join(worst))

# ...and from EACH OTHER, or the picker offers eight names and one look.
_seen = {}
for k in ORDER:
    table = THEMES[k][1]
    _seen[k] = tuple(table.get(c, c) for c in NEUT)
_dupes = [f"{a}=={b}" for i, a in enumerate(ORDER) for b in ORDER[i + 1:]
          if _seen[a] == _seen[b]]
ck("no two themes share a surface palette", not _dupes, str(_dupes))
for i, a in enumerate(ORDER):
    for b in ORDER[i + 1:]:
        d = max(_chan_delta(x, y) for x, y in zip(_seen[a], _seen[b]))
        ck(f"{a} vs {b}: tellable apart", d >= 20, f"max delta {d}")

print("\n== every theme stays legible ==")
for k in ORDER:
    table = THEMES[k][1]
    sub = lambda c: table.get(c, c)          # noqa: E731
    bg = sub(NEUT[0])
    r_text = _ratio(sub(INK[0]), bg)
    r_dim = _ratio(sub(INK[1]), bg)
    r_bright = _ratio(sub(ACC[1]), bg)
    r_fill = _ratio("#ffffff", sub(ACC[2]))
    ck(f"{k}: body text on bg >= 7:1 (AAA)", r_text >= 7.0, f"{r_text:.2f}")
    ck(f"{k}: dim text on bg >= 3.5:1", r_dim >= 3.5, f"{r_dim:.2f}")
    ck(f"{k}: bright accent on bg >= 4.5:1", r_bright >= 4.5,
       f"{r_bright:.2f}")
    # White button text sits on the FILL colour. Lime and bronze are
    # intrinsically light, which is why venom's and brass's fills are a step
    # darker than their deep colour would suggest.
    ck(f"{k}: white on the button fill >= 4:1", r_fill >= 4.0, f"{r_fill:.2f}")

print("\n== semantic colours are never themed ==")
for k in ORDER:
    table = THEMES[k][1]
    ck(f"{k}: danger/amber/success are not substituted",
       not [c for c in _SEMANTIC if c in table],
       str([c for c in _SEMANTIC if c in table]))
    # ...nor may an accent land ON one, which would make a destructive button
    # match the theme and stop being read.
    accents = [v.lower() for key, v in table.items() if key in ACC]
    ck(f"{k}: no accent collides with a semantic colour",
       not [a for a in accents if a in _SEMANTIC], str(accents))

print("\n== a re-tint actually recolours, and leaves no coral behind ==")
if _retint and _CSS:
    for k in ORDER:
        if k == "ember":
            continue
        out = _retint(_CSS, k)
        ck(f"{k}: the stylesheet changed", out != _CSS)
        ck(f"{k}: same length-ish (a substitution, not a truncation)",
           abs(len(out) - len(_CSS)) < len(_CSS) * 0.05,
           f"{len(_CSS)} -> {len(out)}")
        low = out.decode("utf-8").lower()
        for coral in ("#d97757", "#a94f34", "#c15f3c"):
            ck(f"{k}: no {coral} left", coral not in low)
        ck(f"{k}: no coral rgba glow left",
           not re.search(r"rgba\(\s*217\s*,\s*119\s*,\s*87", low))
        # the glow's ALPHA must survive — it is the whole point of the
        # alpha-preserving rgba rewrite
        ck(f"{k}: accent glow alphas preserved",
           low.count("0.063") == _CSS.decode("utf-8").count("0.063"))
        for sem in _SEMANTIC:
            ck(f"{k}: semantic {sem} survived the re-tint", sem in low)
        ck(f"{k}: still ASCII-only (GTK loads the stylesheet as bytes)",
           all(ord(ch) < 128 for ch in out.decode("utf-8")))

print("\n== the theme setting is wired end to end ==")
_core = open(os.path.join(_ROOT, "basilisk_core.py"), encoding="utf-8").read()
ck("basilisk_core ships a `theme` default",
   re.search(r'"theme"\s*:\s*"(\w+)"', _core) is not None)
_m2 = re.search(r'"theme"\s*:\s*"(\w+)"', _core)
ck("...and its value is one of the real themes",
   bool(_m2) and _m2.group(1) in THEMES, _m2.group(1) if _m2 else "none")
ck("the app reads the theme before first paint (no wrong-theme flash)",
   "_read_theme_setting()" in _src and "self._theme = _read_theme_setting()"
   in _src)
ck("startup loads the THEMED stylesheet",
   "_themed_css(self._theme, _UI_SCALE)" in _src)
ck("a scale reload keeps the current theme",
   re.search(r'_themed_css\(getattr\(self, "_theme"', _src) is not None)
ck("apply_theme reuses the SAME provider (two at one priority would fight)",
   "def apply_theme" in _src
   and _src.count("Gtk.StyleContext.add_provider_for_display") == 1)
ck("the Display page has a theme ComboRow",
   "_on_theme_changed" in _src and "Colour theme" in _src)
ck("picking a theme persists it", '_set("theme", key)' in _src)
ck("picking a theme applies it live", "self.win.app.apply_theme(key)" in _src)

print("\n== Tab / Shift+Tab mode switching ==")
# Assertions below read the METHOD BODY, not the whole file. `.*?` under
# re.DOTALL happily runs past the end of a method and matches something a
# thousand lines away, which made "neither writes the state field" fail on an
# assignment in __init__ — a test lying about code it had never looked at.
_mh = ""
_i = _src.find("def _mode_hotkey")
if _i > 0:
    _j = _src.find("\n    def ", _i + 1)
    _mh = _src[_i:_j if _j > 0 else len(_src)]
ck("there is one shared hotkey handler", _src.count("def _mode_hotkey") == 1)
ck("the method body was located", len(_mh) > 200, str(len(_mh)))
ck("the window handler delegates to it",
   re.search(r"KEY_ISO_Left_Tab\) and not ctrl and not alt:\s*\n\s*"
             r"return self\._mode_hotkey", _src) is not None)
ck("the COMPOSER handler delegates to it too — a TextView eats Tab itself, "
   "so without this the shortcut is dead while typing",
   _src.count("return self._mode_hotkey(keyval, state)") >= 2)
ck("Tab drives the agent toggle BUTTON, so every side effect fires",
   "agent_toggle" in _mh and "set_active" in _mh)
ck("Shift+Tab drives the unleash toggle BUTTON, likewise",
   "unleash_toggle" in _mh)
ck("neither writes the state field behind the button's back",
   not re.search(r"self\._(unleashed|current_agent_mode)\s*=", _mh))
ck("ISO_Left_Tab counts as Shift+Tab (X11 sends it instead)",
   "KEY_ISO_Left_Tab" in _mh)
ck("a chat restore cannot latch a mode via the keyboard",
   "_restoring_session" in _mh)
ck("Ctrl/Alt+Tab are left to the window manager",
   re.search(r"KEY_ISO_Left_Tab\) and not ctrl and not alt", _src) is not None)

print(f"\nthemes: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
