#!/usr/bin/env python3
"""test_readcaps.py — a raised default is worthless if the CALLER hardcodes the
old number.

This file exists because that exact mistake shipped twice.

tool_web_read's signature default was raised 6000 -> 24000. The app never used
it: the dispatch table in basilisk.py called

    self._web_read_gated(url, _safe_int(a.get("max_chars", 6000), 6000))

so every page kept coming back cut at ~6,000 characters, and the model kept
reporting "I could only read the first ~6,000 of 16,188 characters" long after
the cap was supposedly lifted. A default is only a default for callers that
omit the argument, and this one never did.

The same shape appeared in the research path (14000) and, in a different file
entirely, in install.sh and the README pointing at the stable repo after the
installer's own default had been fixed.

So this suite does not test the defaults. It tests the CALL SITES — the numbers
the app actually passes — and fails if any of them drops below the floor the
defaults promise.

Stdlib only, no GTK.

Run:  python3 tests/test_readcaps.py
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


_app = open(os.path.join(_ROOT, "basilisk.py"), encoding="utf-8").read()
_core = open(os.path.join(_ROOT, "basilisk_core.py"), encoding="utf-8").read()
_ws = open(os.path.join(_ROOT, "basilisk_ext", "workspace.py"),
           encoding="utf-8").read()

# The floor every read path must clear. 24000 chars is roughly 600 lines of
# source or a long article in full; 6000 is ~150 lines, which is where the
# complaints came from.
FLOOR = 24000

print("\n== the signature defaults ==")
for name, src, pat, want in [
    ("tool_web_read", _core,
     r"def tool_web_read\(url: str, max_chars: int = (\d+)\)", FLOOR),
    ("tool_workspace_read_many", _core,
     r"def tool_workspace_read_many\(paths: Any, max_chars: int = (\d+)\)",
     FLOOR),
    ("workspace.read_many", _ws,
     r"def read_many\(paths: Any, max_chars: int = (\d+)\)", FLOOR),
]:
    m = re.search(pat, src)
    ck(f"{name} defaults to >= {want}",
       bool(m) and int(m.group(1)) >= want,
       m.group(1) if m else "signature not found")

print("\n== THE CALL SITES — what the app actually passes ==")
# Every literal handed to _web_read_gated. This is the check that would have
# caught the 6000 that survived the "fix".
_gated = re.findall(r"_web_read_gated\(\s*[^,]+,\s*(\d+)\s*\)", _app)
ck("every _web_read_gated call passes a real cap",
   bool(_gated), "no call sites found - has the helper been renamed?")
for n in _gated:
    ck(f"_web_read_gated(..., {n}) is >= {FLOOR}", int(n) >= FLOOR, n)

# The dispatch entry reads max_chars out of the model's args with a fallback;
# BOTH numbers matter (the .get default and the _safe_int fallback), because
# the model usually omits the argument entirely.
m = re.search(r'"web_read":\s*lambda a: self\._tool_simple\(\s*\n\s*'
              r'lambda: self\._web_read_gated\(\s*\n\s*[^\n]+\n\s*'
              r'_safe_int\(a\.get\("max_chars",\s*(\d+)\),\s*(\d+)\)\)\)',
              _app)
ck("the web_read dispatch entry was found", bool(m),
   "pattern drifted - re-read the dispatch table")
if m:
    ck(f"dispatch .get default {m.group(1)} >= {FLOOR}",
       int(m.group(1)) >= FLOOR, m.group(1))
    ck(f"dispatch _safe_int fallback {m.group(2)} >= {FLOOR}",
       int(m.group(2)) >= FLOOR, m.group(2))

print("\n== no stale 6000 left on a read path ==")
# Comments explaining the old value are fine; a live 6000 passed as a cap
# is not. Looks only at executable lines.
_live = []
for fn, src in (("basilisk.py", _app), ("basilisk_core.py", _core),
                ("basilisk_ext/workspace.py", _ws)):
    for i, ln in enumerate(src.splitlines(), 1):
        st = ln.strip()
        if st.startswith("#") or not st:
            continue
        if re.search(r"max_chars[^#\n]*\b6000\b|\b6000\b[^#\n]*max_chars", st):
            _live.append(f"{fn}:{i}: {st[:70]}")
ck("no live max_chars=6000 anywhere", not _live, "; ".join(_live[:3]))

print("\n== a truncated read must announce itself ==")
# Raising the cap does not remove truncation, it moves it. When a read IS cut,
# the fact has to travel with the payload or the model reasons about a
# fragment believing it has the whole thing.
ck("web_read's truncation note names the total and the way to get more",
   "[truncated: showing" in _core and "web_read_full" in _core)
ck("read_many marks a cut file inside its content",
   "[CUT:" in _ws and "NOT read" in _ws)
ck("workspace read() marks an incomplete file inside its content",
   "[INCOMPLETE:" in _ws)

print(f"\nreadcaps: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
