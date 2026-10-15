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

_ns_specs = _ns.get("_THEME_SPECS", ())
_ns_ladder = _ns.get("_NEUTRAL_LADDER", ())
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


print("\n== the picker offers nine themes ==")
ck("nine themes are defined", len(THEMES) == 9, str(sorted(THEMES)))
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


def _sat_of(hx):
    import colorsys as _c
    hx = hx.lstrip("#")
    r, g, b = (int(hx[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return _c.rgb_to_hls(r, g, b)[2]


def _chan_delta(a, b):
    a, b = a.lstrip("#"), b.lstrip("#")
    return max(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16))
               for i in (0, 2, 4))


_SPECS = {sp[0]: sp for sp in _ns_specs}
_LADDER = _ns_ladder
for k in ORDER:
    if k == "ember":
        continue
    table = THEMES[k][1]
    floor = _SPECS[k][6]
    worst = []
    for i, c in enumerate(NEUT):
        # A rung BELOW the theme's black floor is meant to be black, so it is
        # not expected to move away from ember's black. That is the two-tone
        # design, not a theme that failed to apply.
        if floor and _LADDER[i] < floor:
            continue
        new_c = table.get(c, c)
        d = _chan_delta(c, new_c)
        # Same chroma caveat as the pairwise check below: slate differs from
        # ember by being COOL GREY against WARM CHARCOAL, which is a
        # saturation/hue difference that a max-channel delta barely registers.
        # A rung also counts as changed when its chroma moved appreciably.
        _dc = abs(_sat_of(new_c) - _sat_of(c))
        if d < _MIN_DELTA[i] and _dc < 0.10:
            worst.append(f"rung{i} moved {d}, chroma {_dc:.2f} "
                         f"(need {_MIN_DELTA[i]} or 0.10)")
    ck(f"{k}: coloured surfaces are visibly different from ember", not worst,
       "; ".join(worst))

print("\n== a theme that CLAIMS two tones has two tones ==")
# THE COMPLAINT THIS PINS, in the operator's words: "half of things is black
# half is dark green, not like rest of ur themes where is basically one color
# even tho u say its two". That was accurate. Every theme mapped the whole
# stylesheet into one hue, so the canvas, the panels and the borders were three
# lightnesses of the same colour — truthful to the code, and not what anyone
# means by a two-colour theme.
#
# A theme with a black_floor must now show BOTH tones in its ladder: at least
# two rungs essentially unsaturated (black) and at least two carrying real
# chroma. A single-hue regression makes the first number zero and fails here.
import colorsys as _cs


def _sat(hx):
    hx = hx.lstrip("#")
    r, g, b = (int(hx[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return _cs.rgb_to_hls(r, g, b)[2]


for k in ORDER:
    sp = _SPECS[k]
    floor = sp[6]
    table = THEMES[k][1]
    sats = [_sat(table.get(c, c)) for c in NEUT]
    blacks = sum(1 for x in sats if x < 0.10)
    # 0.18, not 0.30: the surfaces were deliberately calmed to the
    # saturation real dark themes use (0.14-0.26). What matters is the
    # SPLIT against the ~0.02 black rungs, not an absolute vividness.
    cols = sum(1 for x in sats if x >= 0.18)
    if floor:
        ck(f"{k}: declares a black floor, so it must show BOTH tones "
           f"({blacks} black / {cols} coloured rungs)",
           blacks >= 2 and cols >= 2,
           " ".join(f"{x:.2f}" for x in sats))
    elif k == "slate":
        # slate's identity is NOT "zero chroma" — it is a cool grey, and a cool
        # grey has some. What makes it the monochrome option is that it has no
        # SPLIT: every rung sits at the same low saturation, where a two-tone
        # theme spans ~0.02 (black canvas) to ~0.34 (coloured panel). Asserting
        # the uniformity is asserting the actual design; asserting cols == 0
        # would force slate to be pure grey to satisfy the measurement.
        _spread = max(sats) - min(sats)
        ck("slate is uniform, not split (black + grey is not two tones)",
           _spread < 0.10 and max(sats) < 0.25,
           f"spread {_spread:.2f}, max {max(sats):.2f}")

# ...and from EACH OTHER, or the picker offers eight names and one look.
_seen = {}
for k in ORDER:
    table = THEMES[k][1]
    _seen[k] = tuple(table.get(c, c) for c in NEUT)
_dupes = [f"{a}=={b}" for i, a in enumerate(ORDER) for b in ORDER[i + 1:]
          if _seen[a] == _seen[b]]
ck("no two themes share a surface palette", not _dupes, str(_dupes))
def _mean_sat(pal):
    """Mean chroma of the COLOURED rungs only.

    Averaging the whole ladder includes the two near-black rungs, which are
    unsaturated in every two-tone theme and so drag every mean toward zero —
    making two themes look similar in chroma precisely because they agree
    about the part that carries no colour.
    """
    import colorsys as _c
    out = []
    for hx in pal[2:]:
        hx = hx.lstrip("#")
        r, g, bl = (int(hx[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
        out.append(_c.rgb_to_hls(r, g, bl)[2])
    return sum(out) / len(out)


for i, a in enumerate(ORDER):
    for b in ORDER[i + 1:]:
        d = max(_chan_delta(x, y) for x, y in zip(_seen[a], _seen[b]))
        # A MAX-CHANNEL DELTA UNDERSTATES A CHROMA DIFFERENCE, and slate is the
        # case that proves it: a grey panel beside a teal one is obviously not
        # the same colour, yet their largest single-channel gap is 12, because
        # the difference is in SATURATION rather than in any one channel. So a
        # pair also counts as distinguishable when their mean chroma is far
        # apart. Without this the test would demand slate be tinted until it
        # stopped being the monochrome option, i.e. break the theme to satisfy
        # the measurement.
        _ds = abs(_mean_sat(_seen[a]) - _mean_sat(_seen[b]))
        # 18/255 at the MOST-different rung. The darkest rungs are near-black
        # in every theme by design, so the comparison that matters is the one
        # the eye makes: panels and borders side by side.
        ck(f"{a} vs {b}: tellable apart", d >= 18 or _ds >= 0.12,
           f"max delta {d}, chroma gap {_ds:.2f}")

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

print("\n== the WHOLE stylesheet is recoloured, not just a listed palette ==")
# THE BUG THIS PINS: the first engine substituted a hand-written table of 14
# colours. The stylesheet carries 250 distinct hex colours and 928 rgba() uses
# — the frame, sidebar, composer, chips, every button state, scrollbars,
# terminal — so 69% of it stayed ember and each theme was a recoloured accent
# in an ember window. Coverage is now algorithmic: every colour is transformed
# except the deliberate exclusions below, so a widget added tomorrow is themed
# the day it is written.
_SEM = ("#e5484d", "#f0a500", "#2ecc71")       # danger / warning / success
_STRUCT = ("#ffffff", "#000000")               # shadows, scrims, overlays
if _retint and _CSS:
    _basetxt = _CSS.decode("utf-8")
    _bh = re.findall(r"#[0-9a-fA-F]{6}\b", _basetxt)
    _br = re.findall(r"rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+", _basetxt)
    for k in ORDER:
        if k == "ember":
            continue
        out = _retint(_CSS, k).decode("utf-8")
        oh = re.findall(r"#[0-9a-fA-F]{6}\b", out)
        orr = re.findall(r"rgba\(\s*\d+\s*,\s*\d+\s*,\s*\d+", out)
        hchg = sum(1 for a, b in zip(_bh, oh) if a.lower() != b.lower())
        rchg = sum(1 for a, b in zip(_br, orr)
                   if a.replace(" ", "") != b.replace(" ", ""))
        ck(f"{k}: most hex colours recoloured ({hchg}/{len(_bh)})",
           hchg >= len(_bh) * 0.80, f"{hchg}/{len(_bh)}")
        ck(f"{k}: most rgba colours recoloured ({rchg}/{len(_br)})",
           rchg >= len(_br) * 0.65, f"{rchg}/{len(_br)}")
        for sem in _SEM:
            ck(f"{k}: semantic {sem} count unchanged",
               out.lower().count(sem) == _basetxt.lower().count(sem))
        for st in _STRUCT:
            ck(f"{k}: structural {st} count unchanged (shadows keep their weight)",
               out.lower().count(st) == _basetxt.lower().count(st))
        a_in = re.findall(r"rgba\([^)]*?,\s*([0-9.]+)\s*\)", _basetxt)
        a_out = re.findall(r"rgba\([^)]*?,\s*([0-9.]+)\s*\)", out)
        ck(f"{k}: every alpha preserved ({len(a_in)})", a_in == a_out)

print("\n== the GTK tokens the window resolves stay legible after recolouring ==")
# The checks further up reason about the palette. These read the ACTUAL
# @define-color tokens out of the recoloured sheet — the values libadwaita
# resolves for the window, view, card, headerbar, popover and sidebar — because
# that is what the operator looks at. A transform that recoloured the surfaces
# but sank the text into them would pass every palette check above.
_PAIRS = [("window_fg_color", "window_bg_color"),
          ("view_fg_color", "view_bg_color"),
          ("card_fg_color", "card_bg_color"),
          ("headerbar_fg_color", "headerbar_bg_color"),
          ("popover_fg_color", "popover_bg_color"),
          ("sidebar_fg_color", "sidebar_bg_color")]
if _retint and _CSS:
    for k in ORDER:
        out = _retint(_CSS, k).decode("utf-8")
        tok = dict(re.findall(r"@define-color\s+([a-z_]+)\s+(#[0-9a-fA-F]{6});",
                              out))
        for fg, bg in _PAIRS:
            if fg in tok and bg in tok:
                r = _ratio(tok[fg], tok[bg])
                ck(f"{k}: {fg.split('_')[0]} text on its surface >= 7:1",
                   r >= 7.0, f"{r:.2f}")
        # The accent fill carries white button text. ember ships at 4.2 and is
        # pinned by test_theme.py, so it is held to its own shipped value; the
        # generated themes must clear the 4.5 UI-text floor.
        if "accent_bg_color" in tok:
            r = _ratio("#ffffff", tok["accent_bg_color"])
            floor = 4.2 if k == "ember" else 4.5
            ck(f"{k}: white on the accent fill >= {floor}:1", r >= floor,
               f"{r:.2f}")

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

# THE MIGRATION MUST NOT EAT IT. `theme` was a retired key in an older build,
# and _migrate_settings still carried `merged.pop("theme", None)` when the
# picker brought it back as a live setting. Every load deleted it, so a chosen
# theme survived exactly until the next start and then reverted to the default
# with nothing to explain why. A key that is revived has to be removed from the
# retired list in the same change; nothing else enforces that, so this does.
ck("the settings migration does not drop `theme`",
   'merged.pop("theme"' not in _core,
   "a retired-key pop is deleting the live theme setting on every load")
_retired = re.findall(r'merged\.pop\("([a-z_]+)"', _core)
ck("...and no retired-key pop names a key that is still declared",
   not [k for k in _retired if re.search(r'^\s+"%s":' % k, _core, re.M)],
   str([k for k in _retired if re.search(r'^\s+"%s":' % k, _core, re.M)]))

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

# ── THE RETINTED SHEET MUST STILL BE VALID CSS ───────────────────────
# Nothing above this checked SYNTAX, and syntax is the failure that would look
# exactly like the complaint the themes started from. GTK's CSS parser does not
# fail loudly: one malformed value and it logs to stderr (which nobody sees in
# a desktop launch) and drops the rest of the stylesheet from that point on.
# The app then renders in stock Adwaita and the theme "did nothing" -- the
# symptom being indistinguishable from a re-tint that did not take.
#
# A re-tint is a pure COLOUR substitution, so every one of these is an equality
# against the base sheet, not a judgement call: same selectors, same property
# names, same brace and paren counts, same declaration count. Anything else
# means the substitution ate structure.
print("\n== every theme's stylesheet is still valid, parseable CSS ==")

def _decomment(css):
    """CSS with /* ... */ removed.

    Needed because the sheet documents its own palette inside comments, in
    prose: `smoke  rgba(22, 11, 14, a)`. That is not a declaration and GTK
    never parses it, but a validator that reads it will report a malformed
    alpha channel in every theme. Applied to the base and to each theme alike,
    so the structural equalities below still hold."""
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)


_base = _decomment(_CSS.decode("ascii", "replace"))


def _structure(css):
    """Everything about a stylesheet that a COLOUR change must not alter."""
    return {
        "{": css.count("{"), "}": css.count("}"),
        "(": css.count("("), ")": css.count(")"),
        ";": css.count(";"),
        "props": sorted(re.findall(r"([-a-zA-Z]+)\s*:", css)),
        "at": sorted(re.findall(r"@[-a-z]+", css)),
    }


_HEX = re.compile(r"#[0-9a-fA-F]+")
_RGBA = re.compile(r"\brgba?\(([^()]*)\)")
_base_struct = _structure(_base)
ck("the base sheet parses as balanced",
   _base_struct["{"] == _base_struct["}"]
   and _base_struct["("] == _base_struct[")"],
   str({k: v for k, v in _base_struct.items() if k in "{}()"}))

for _key in ORDER:
    # THEMES[key] is (label, substitution table). The SHEET is what
    # _retint_css produces from it, and the sheet is what GTK parses.
    _raw = _retint(_CSS, _key).decode("ascii", "replace")
    _txt = _decomment(_raw)
    _st = _structure(_txt)

    ck(f"{_key}: braces balanced ({_st['{']}/{_st['}']})",
       _st["{"] == _st["}"] and _st["{"] == _base_struct["{"],
       "a colour substitution cannot add or lose a rule")
    ck(f"{_key}: parens balanced ({_st['(']}/{_st[')']})",
       _st["("] == _st[")"],
       "an unbalanced rgba() silently kills the rest of the sheet")
    ck(f"{_key}: same declaration count", _st[";"] == _base_struct[";"])
    ck(f"{_key}: same property names", _st["props"] == _base_struct["props"],
       "re-tinting must not touch structure")
    ck(f"{_key}: same at-rules (@define-color etc)",
       _st["at"] == _base_struct["at"])

    # Still ASCII. The CSS literal is a bytes object precisely so a stray
    # non-ASCII character is a build error; a re-tint that introduced one would
    # raise at set_style_sheet time instead.
    ck(f"{_key}: ASCII only",
       all(ord(c) < 128 for c in _raw),
       "the CSS is a bytes literal; non-ASCII would raise on load")

    # Every hex colour is 3, 4, 6 or 8 digits. "#12345" parses as nothing.
    _bad_hex = sorted({h for h in _HEX.findall(_txt)
                       if len(h) - 1 not in (3, 4, 6, 8)})
    ck(f"{_key}: every hex colour is a legal length", not _bad_hex,
       "malformed: " + ", ".join(_bad_hex[:5]))

    # Every rgba() has 3 or 4 components, channels 0-255, alpha 0-1.
    _bad_rgba = []
    for _args in _RGBA.findall(_txt):
        _parts = [x.strip() for x in _args.split(",")]
        if len(_parts) not in (3, 4):
            _bad_rgba.append(_args)
            continue
        try:
            _ch = [float(x) for x in _parts[:3]]
        except ValueError:
            _bad_rgba.append(_args)
            continue
        if any(v < 0 or v > 255 or v != int(v) for v in _ch):
            _bad_rgba.append(_args)
            continue
        if len(_parts) == 4:
            try:
                _a = float(_parts[3])
            except ValueError:
                _bad_rgba.append(_args)
                continue
            if _a < 0 or _a > 1:
                _bad_rgba.append(_args)
    ck(f"{_key}: every rgba() is in range", not _bad_rgba,
       "malformed: " + "; ".join(_bad_rgba[:3]))

    # No declaration left with an empty value -- the shape a substitution
    # produces when it matches a colour and replaces it with nothing.
    _empty = re.findall(r"[-a-zA-Z]+\s*:\s*(?=[;}])", _txt)
    ck(f"{_key}: no empty declarations", not _empty,
       f"{len(_empty)} property(ies) lost their value")

    # And the sheet stays about the same size: a runaway replace shows up here
    # before it shows up on screen.
    ck(f"{_key}: size within 10% of the base "
       f"({len(_txt)} vs {len(_base)})",
       abs(len(_txt) - len(_base)) <= len(_base) * 0.10)

print(f"\nthemes: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
