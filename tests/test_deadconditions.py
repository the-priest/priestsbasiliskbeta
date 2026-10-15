#!/usr/bin/env python3
"""test_deadconditions.py — a condition that can never be false is not a
condition, it is a deletion with extra steps.

THE SHAPE
=========
There is one posture left: autonomous. `_migrate_settings` enforces that by
POPPING the key, with the comment "so nothing can re-enable a confirmation
prompt":

    merged.pop("approval_mode", None)

So every reader of it looks like this:

    if self.settings.get("approval_mode", "none") == "none":

and that test is ALWAYS true — the key is never present, so .get() always
returns its own default. Any `else` behind it is unreachable, and any
assignment inside it is unconditional.

THREE REAL BUGS HAVE COME OUT OF THAT ONE PATTERN
=================================================
  1. The adaptive-effort HEAVY RUNG. Guarded with `and not _auton`, which was
     always False, so the bigger reasoning budget was never granted and
     hard_engagement_model was never consulted. Found and fixed in
     basilisk_core; the comment there is the write-up.
  2. max_tool_steps DID NOTHING. The turn loop read it and then, inside this
     always-true branch, overwrote it with 0. An operator who set 20 got no
     cap; the 150 in DEFAULT_SETTINGS was fiction. Fixed by making 0 the
     documented default (uncapped, which IS the intended behaviour) and
     honouring any positive value, with a stored 150 — the old no-op default
     every install carries — migrated to 0 so no existing install is newly
     cut off mid-run.
  3. The propose/propose_edit/write_file split. The `else` arm drops those
     calls as "advisory, the operator will click the card"; there is no card
     and no operator. Harmless today only because the live arm is the right
     one.

This suite pins (2), proves the premise for the whole class, and PRINTS every
remaining site so the next one is found by reading this output rather than by
an operator noticing a setting that does nothing.

Stdlib only, no GTK.

Run:  python3 tests/test_deadconditions.py
"""
import io
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import basilisk_core as C  # noqa: E402

_SRC = io.open(os.path.join(_ROOT, "basilisk.py"), encoding="utf-8").read()

_p = _f = 0


def ck(name, cond, why=""):
    global _p, _f
    if cond:
        _p += 1
        print("  PASS", name)
    else:
        _f += 1
        print("  FAIL", name, ("  [" + why + "]") if why else "")


print("\n== the premise: approval_mode cannot survive a load ==")
for stored in ("none", "confirm", "every", "supervised"):
    _raw = {"approval_mode": stored}
    _m = dict(C.DEFAULT_SETTINGS)
    _m.update(_raw)
    C._migrate_settings(_m, _raw)
    ck(f"a stored approval_mode={stored!r} is dropped",
       "approval_mode" not in _m,
       "if this ever stops being true, every branch below changes meaning")
ck("...so .get('approval_mode', 'none') is always 'none'",
   C.load_settings().get("approval_mode", "none") == "none")

print("\n== (2) max_tool_steps is a real cap again ==")
ck("the shipped default is 0 (uncapped), not a number that does nothing",
   C.DEFAULT_SETTINGS.get("max_tool_steps") == 0,
   str(C.DEFAULT_SETTINGS.get("max_tool_steps")))
for stored, want, why in [
    (None, 0, "absent -> uncapped, the walk-away default"),
    (150, 0, "the OLD no-op default migrates to uncapped, so no existing "
             "install is newly cut off at 150 steps mid-run"),
    (20, 20, "a value the operator actually picked is honoured"),
    (0, 0, "an explicit 0 stays uncapped"),
    (9999, 9999, "a deliberately huge cap is still their choice"),
]:
    _raw = {} if stored is None else {"max_tool_steps": stored}
    _m = dict(C.DEFAULT_SETTINGS)
    _m.update(_raw)
    C._migrate_settings(_m, _raw)
    ck(f"stored {stored!r} -> {want}", _m.get("max_tool_steps") == want, why)

# And the turn loop must not throw the answer away again.
_i = _SRC.index("self._tool_chain_depth += 1")
_turn = _SRC[_i:_i + 3000]
ck("the turn loop reads max_tool_steps",
   'self.settings.get("max_tool_steps"' in _turn)
ck("...and does NOT overwrite it behind an approval_mode test",
   not re.search(r'approval_mode[^\n]*\n\s*_budget = 0', _turn),
   "that one line is what made the setting a no-op for every install")
ck("a negative value cannot disable the cap by accident",
   "_budget < 0" in _turn)

print("\n== the class: every remaining always-true approval_mode site ==")
# Informational, but it fails if the count GROWS: a new reader of a key that
# cannot be set is a new dead branch, and this is where it gets noticed.
_sites = [(i, l.strip()) for i, l in enumerate(_SRC.splitlines(), 1)
          if "approval_mode" in l and not l.strip().startswith("#")]
for ln, txt in _sites:
    print(f"     basilisk.py:{ln}: {txt[:88]}")
ck(f"no NEW always-true approval_mode branches ({len(_sites)} known)",
   len(_sites) <= 5,
   "each one is a condition that cannot be false; if you are adding a sixth, "
   "delete the dead arm instead and update this count")
ck("the budget site is no longer one of them",
   not any("_budget" in t for _, t in _sites))

print("\n== no setting in the file is read by nothing ==")
# The same disease, found by sweeping instead of by noticing: a key in
# DEFAULT_SETTINGS that no code ever reads is a promise the app does not keep.
# `plan_min_steps` was one ("jobs smaller than this need no plan" -- nothing
# read it, not the host, not tasks.py, not the persona).
# NB: the loop variable is _fn, not _f. _f is this file's failure
# counter, and shadowing it made the summary line print
# "19 passed, basilisk_ext/zdayfind.py failed".
_FILES = ["basilisk.py", "basilisk_core.py", "basilisk_persona.py",
          "basilisk_voice.py", "basilisk_scope.py", "basilisk_safety.py",
          "basilisk_ledger.py"]
_FILES += [os.path.join("basilisk_ext", f)
           for f in sorted(os.listdir(os.path.join(_ROOT, "basilisk_ext")))
           if f.endswith(".py")]
_blob = {}
for _fn in _FILES:
    try:
        _blob[_fn] = io.open(os.path.join(_ROOT, _fn),
                             encoding="utf-8").read()
    except OSError:
        pass
_unread = []
for _k in sorted(C.DEFAULT_SETTINGS):
    _n = 0
    for _fn, _t in _blob.items():
        _c = len(re.findall(r'["\']%s["\']' % re.escape(_k), _t))
        if _fn == "basilisk_core.py":
            _c -= 1                     # its own entry in DEFAULT_SETTINGS
        _n += max(0, _c)
    # Provider keys are generated and read through f"{provider}_model" /
    # f"{provider}_api_key", so a literal search cannot see them.
    if _n == 0 and not re.search(r"_(model|api_key|base_url)$", _k):
        _unread.append(_k)
ck(f"every setting is read somewhere ({len(C.DEFAULT_SETTINGS)} keys)",
   not _unread,
   "read by nothing: " + ", ".join(_unread)
   + " -- wire it or delete it; a knob that does nothing is worse than no knob")

print("\n== (1) the heavy rung's write-up is still beside the code ==")
_core = io.open(os.path.join(_ROOT, "basilisk_core.py"),
                encoding="utf-8").read()
ck("basilisk_core records why the heavy rung never fired",
   "_auton = self.settings.get" in _core and "always False" in _core,
   "the comment is the only thing stopping that guard being re-added")
ck("adaptive effort can still be turned off outright",
   '"adaptive_effort"' in _core)

print(f"\ndeadconditions: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
