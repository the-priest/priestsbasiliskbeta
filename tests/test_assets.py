#!/usr/bin/env python3
"""
test_assets.py — the repo's asset layout and its three consumers.

Art loading fails SILENTLY: a missing PNG just means the button falls back to a
symbolic icon, and nobody notices until a screenshot looks wrong. That makes it
exactly the kind of thing that rots after a reorganisation, so the layout is
pinned here instead.

Three consumers have to agree, and they disagree in different ways:
  1. basilisk.py resolves assets at runtime (repo layout AND installed layout).
  2. install.sh fetches them remotely and copies them locally.
  3. index.html / README.md reference them as web paths.

Run:  python3 tests/test_assets.py
"""

from __future__ import annotations

import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_p = _f = 0


def ck(name: str, cond: bool, detail: str = "") -> None:
    global _p, _f
    if cond:
        _p += 1
        print(f"  PASS {name}")
    else:
        _f += 1
        print(f"  FAIL {name}" + (f"   [{detail}]" if detail else ""))


def _rel(*parts: str) -> str:
    return os.path.join(_ROOT, *parts)


# ── 1. the files are where the layout says ───────────────────────────
print("== asset layout ==")
APP_ART = [
    "basilisk-avatar.png", "basilisk-logo.png", "basilisk-priest.png",
    "basilisk-watermark.png", "basilisk-cross.svg", "basilisk-dragon.svg",
    "basilisk-sigil.svg", "org.thepriest.basilisk.svg",
] + [f"basilisk-btn-{n}.png" for n in
     ("settings", "bell", "terminal", "minimise", "close", "expand",
      "attach", "camera", "suggest", "sound", "unleash")]
BRAND_ART = ["banner.png", "basilisk-icon.png", "architecture.svg", "dragon.png"]

for f in APP_ART:
    ck(f"assets/app/{f}", os.path.isfile(_rel("assets", "app", f)))
for f in BRAND_ART:
    ck(f"assets/brand/{f}", os.path.isfile(_rel("assets", "brand", f)))

# Nothing image-shaped should be loose at the repo root any more.
loose = [f for f in os.listdir(_ROOT)
         if f.lower().endswith((".png", ".jpg", ".jpeg", ".svg"))]
ck("no loose images at repo root", not loose, str(loose))


# ── 2. GitHub-critical files must stay AT the root ───────────────────
# Moving any of these breaks Pages or Search Console silently — the site keeps
# serving, it just serves wrong (Jekyll eats _-prefixed paths without
# .nojekyll; verification drops if the google*.html moves).
print("\n== files that must remain at repo root ==")
for f in (".nojekyll", ".gitignore", "index.html", "robots.txt", "sitemap.xml",
          "LICENSE", "README.md", "install.sh",
          "org.thepriest.basilisk.desktop"):
    ck(f"root: {f}", os.path.isfile(_rel(f)))
ck("root: google site-verification html",
   any(f.startswith("google") and f.endswith(".html") for f in os.listdir(_ROOT)))


# ── 3. basilisk.py resolves every runtime asset ──────────────────────
print("\n== basilisk.py runtime resolution ==")
import types


class _Meta(type):
    def __getattr__(cls, n):
        if n.startswith("__"):
            raise AttributeError(n)
        return _Obj


class _Obj(metaclass=_Meta):
    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return _Obj()

    def __getattr__(self, n):
        return _Obj()


class _Mod(types.ModuleType):
    def __getattr__(self, n):
        if n.startswith("__"):
            raise AttributeError(n)
        return _Obj

    def require_version(self, *a, **k):
        pass


for _m in ("gi", "gi.repository", "gi.repository.Gtk", "gi.repository.Adw",
           "gi.repository.GLib", "gi.repository.Gio", "gi.repository.Gdk",
           "gi.repository.GdkPixbuf", "gi.repository.Pango",
           "gi.repository.GObject", "gi.repository.GtkSource",
           "gi.repository.Vte", "gi.repository.Soup"):
    sys.modules[_m] = _Mod(_m)
sys.modules["gi"].require_version = lambda *a, **k: None

import basilisk as B  # noqa: E402

ck("dragon emblem resolves", bool(B._DRAGON_SVG_PATH), str(B._DRAGON_SVG_PATH))
ck("avatar resolves", bool(B._AVATAR_PNG_PATH))
ck("watermark resolves", bool(B._WATERMARK_SVG_PATH))
for f in ("basilisk-logo.png", "basilisk-priest.png", "basilisk-cross.svg",
          "basilisk-sigil.svg"):
    ck(f"resolves {f}", bool(B._find_asset(f)))
_missing_btn = [n for n in ("settings", "bell", "terminal", "minimise", "close",
                            "expand", "attach", "camera", "suggest", "sound",
                            "unleash") if not B._find_btn_png(n)]
ck("all 11 button icons resolve", not _missing_btn, str(_missing_btn))

# The installed layout is FLAT and must stay searched, or upgrading breaks
# every existing install.
_paths = B._asset_paths("basilisk-logo.png")
ck("installed (flat) path still searched",
   any(".local/share/basilisk/basilisk-logo.png" in p for p in _paths))
ck("repo assets/app path searched",
   any(os.path.join("assets", "app") in p for p in _paths))
ck("legacy alongside-module path still searched", len(_paths) >= 3)


# ── 4. install.sh agrees with what basilisk.py wants ─────────────────
print("\n== install.sh coverage ==")
_sh = open(_rel("install.sh"), encoding="utf-8").read()
m = re.search(r"^OPTIONAL_ART=\(([^)]*)\)", _sh, re.M)
ck("OPTIONAL_ART array present", bool(m))
if m:
    listed = set(m.group(1).split())
    missing = [f for f in APP_ART if f not in listed]
    ck("install.sh ships every runtime asset", not missing, str(missing))
ck("ASSET_DIR defined", 'ASSET_DIR="assets/app"' in _sh)
ck("remote fetch flattens with basename", 'basename "${f}"' in _sh)
ck("local copy falls back to flat layout", '"${SRC_DIR}/${_art}"' in _sh)
ck("icon install knows the new path", '${SRC_DIR}/${ASSET_DIR}/${APP_ID}.svg' in _sh)
ck("basilisk_scope.py still in REQUIRED_FILES",
   re.search(r"^REQUIRED_FILES=\(.*basilisk_scope\.py", _sh, re.M) is not None)


# ── 5. web references resolve to real files ──────────────────────────
print("\n== web/doc references ==")
_broken = []
for page in ("index.html", "README.md"):
    txt = open(_rel(page), encoding="utf-8").read()
    for mm in re.finditer(r'(?:src|href)="([^"]+\.(?:png|svg|jpg))"', txt):
        rel = mm.group(1)
        if rel.startswith("http"):
            continue
        if not os.path.isfile(_rel(rel)):
            _broken.append(f"{page}:{rel}")
    for mm in re.finditer(
            r'https://the-priest\.github\.io/PriestsBasilisk/([^"\s]+\.(?:png|svg))',
            txt):
        if not os.path.isfile(_rel(mm.group(1))):
            _broken.append(f"{page}:ABS:{mm.group(1)}")
ck("every referenced image exists", not _broken, str(_broken))


# ── 6. the installer asks for the key the app actually needs ─────────
# A brand-new install used to prompt for a GROQ key -- "Groq is FREE and
# FAST" -- and never for the SiliconFlow one. SiliconFlow is the only
# registered provider and DEFAULT_SETTINGS pins active_provider to it, so the
# first turn after install returned an API error with nothing on screen to
# explain why. Groq's key is still worth asking for, but for what it does now:
# Whisper speech-to-text, which is a fallback, not chat.
print("\n== the installer's key prompt matches the provider registry ==")
sys.path.insert(0, _rel("."))
import basilisk_core as _kc  # noqa: E402

_provider_keys = [p.key for p in _kc.PROVIDERS]
ck(f"the registry has exactly the providers the installer should ask about "
   f"({_provider_keys})", _provider_keys == ["siliconflow"],
   "if a provider was added, the installer's prompt needs it too")
ck("DEFAULT_SETTINGS still points at that provider",
   _kc.DEFAULT_SETTINGS.get("active_provider") in _provider_keys)

for _needed in ("SILICONFLOW_API_KEY", "siliconflow_api_key",
                "cloud.siliconflow.com/account/ak"):
    ck(f"install.sh knows about {_needed}", _needed in _sh)
ck("the chat-key prompt comes BEFORE the optional Groq one",
   _sh.index("SiliconFlow API key (chat)")
   < _sh.index("Groq API key (optional"),
   "the first thing asked for should be the thing that makes it work")
ck("the Groq prompt says chat does not use it",
   "Chat does NOT use this" in _sh)
ck("no key is still called out as fatal for chat",
   "chat will fail until you add one" in _sh)
ck("the settings writer carries the chat key",
   "NEW_SF_KEY" in _sh and "out['siliconflow_api_key'] = new_sf_key" in _sh)
ck("it no longer claims Groq is the primary cloud backend",
   "Groq Python library (cloud backend, primary)" not in _sh)
ck("it no longer pip-installs a library nothing imports",
   "installing groq (~few MB) via pip" not in _sh,
   "GroqBackend is never constructed: the one provider's engine is "
   "openai_compat, and Groq's STT is a plain HTTPS POST")
# Checked against what the installer PRINTS, not what it says about itself:
# the comment above the key prompt quotes the old wording on purpose.
_sh_live = "\n".join(l for l in _sh.splitlines()
                     if not l.lstrip().startswith("#"))
ck("it no longer offers providers that were removed",
   "Novita, GitHub, or Google" not in _sh_live)
ck("...and nothing it prints still calls Groq free and fast",
   "Groq is FREE and FAST" not in _sh_live)
ck("--no-systemd is documented as inert, not as installing a unit",
   "don't install the systemd unit" not in _sh
   and "is still accepted and does nothing" in _sh)
ck("SKIP_SYSTEMD, which nothing read, is gone",
   "SKIP_SYSTEMD=0" not in _sh and "SKIP_SYSTEMD=1" not in _sh)
# The import-failed fallback dict must still name a REAL theme.
_m = re.search(r'"theme":\s*"([a-z]+)"', _sh)
ck("the fallback settings name a real theme", bool(_m))
if _m:
    _themes = re.findall(
        r'\("([a-z]+)",\s*"[A-Z]',
        open(_rel("basilisk.py"), encoding="utf-8").read())
    ck(f"...and {_m.group(1)!r} is one of the shipped themes",
       _m.group(1) in (_themes or ["ember"]),
       f"shipped: {_themes}")

print(f"\nassets: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
