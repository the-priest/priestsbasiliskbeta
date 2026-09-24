#!/usr/bin/env python3
"""
test_writemode.py — write_file must accept the "create" mode the persona tells
the model to use.

THE BUG THIS PINS (found and fixed by the operator):
  The write_file contract and the big-file recipe in the persona both instruct
  the model to open a NEW file with `"mode": "create"`. But the mode normaliser
  only knew "replace" and "append", so it rejected "create" with
  "unknown mode 'create'" — the host refusing its OWN documented instruction.
  On a build ("make me a game"), the model emitted a perfectly good
  write_file(mode="create") call and got back an error, so it announced
  "building it now" and never landed a file: the announce-and-stall loop.

  "create" means "write this content to a new file", which is exactly what
  "replace" does (parent dirs are created regardless). So create → replace, and
  a genuinely unknown mode is still named and refused.

Stdlib only, writes into a temp dir, no GTK, no network.

Run:  python3 tests/test_writemode.py
"""

from __future__ import annotations

import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import basilisk_core as C  # noqa: E402

_p = _f = 0


def ck(name, cond, detail=""):
    global _p, _f
    if cond:
        _p += 1
        print(f"  PASS {name}")
    else:
        _f += 1
        print(f"  FAIL {name}" + (f"   [{detail}]" if detail else ""))


_tmp = tempfile.mkdtemp(prefix="priest_writemode_")


def _p_join(name):
    return os.path.join(_tmp, name)


# ── 1. "create" opens a brand-new file (the persona's documented mode) ──
print('== "create" writes a new file ==')
_target = _p_join("game.html")
_res = C.tool_write_file(_target, "<!DOCTYPE html><h1>Darth Slots</h1>",
                         make_backup=False, mode="create")
ck('create mode returns ok:True (not "unknown mode")',
   _res.get("ok") is True, str(_res))
ck("...and the file actually exists with the content",
   os.path.isfile(_target)
   and "Darth Slots" in open(_target, encoding="utf-8").read(),
   _target)

# ── 2. every create alias the normaliser maps behaves the same ──
print("\n== create aliases all write ==")
for i, alias in enumerate(("create", "create_new", "create-new",
                           "createfile", "create_file", "new")):
    t = _p_join(f"f{i}.txt")
    r = C.tool_write_file(t, f"body-{alias}", make_backup=False, mode=alias)
    ck(f'mode={alias!r} -> ok', r.get("ok") is True, str(r))

# ── 3. "create" into a NESTED path creates the parent dirs ──
print("\n== create makes parent directories ==")
_nested = _p_join("a/b/c/deep.txt")
_r = C.tool_write_file(_nested, "deep", make_backup=False, mode="create")
ck("nested create succeeds", _r.get("ok") is True, str(_r))
ck("...and the nested file exists", os.path.isfile(_nested))

# ── 4. replace and append still work exactly as before ──
print("\n== replace / append unchanged ==")
_rp = _p_join("rp.txt")
C.tool_write_file(_rp, "first", make_backup=False, mode="create")
C.tool_write_file(_rp, "second", make_backup=False, mode="replace")
ck("replace overwrites",
   open(_rp, encoding="utf-8").read() == "second")
C.tool_write_file(_rp, "-third", make_backup=False, mode="append")
ck("append adds to the end",
   open(_rp, encoding="utf-8").read() == "second-third")

# ── 5. a genuinely unknown mode is STILL refused (no silent accept) ──
print("\n== an unknown mode is still refused ==")
_bad = C.tool_write_file(_p_join("x.txt"), "x", make_backup=False,
                         mode="obliterate")
ck("unknown mode is refused", _bad.get("ok") is False, str(_bad))
ck("...and the error names the mode",
   "obliterate" in (_bad.get("error") or ""), str(_bad.get("error")))


print(f"\n{_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
