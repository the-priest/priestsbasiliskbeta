#!/usr/bin/env python3
"""test_spend.py — the session token/cost readout.

What this covers, and why each rule exists rather than being obvious:

  * Counts come from the PROVIDER's usage chunk, never estimated from
    characters. An estimate that is 30% out is worse than no number: it reads
    as authoritative and is not.
  * The usage chunk arrives with an EMPTY `choices` list, so it has to be read
    before the "no choices, skip" branch — which is exactly where it used to be
    discarded. Pinned here because that one line silently disables the feature.
  * A turn the provider did not meter counts as UNKNOWN, not as free. Treating
    an unmetered turn as $0 is how a readout drifts quietly under the real bill.
  * Prices resolve operator-override -> catalogue -> default, because the
    catalogue is maintained by hand and a provider can reprice overnight.
  * Cached input is billed at its own cheaper rate where the catalogue has one;
    ignoring that overstates a long session badly.

Stdlib only, no GTK, no network.

Run:  python3 tests/test_spend.py
"""
import os
import re
import sys

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


print("\n== prices resolve override -> catalogue -> default ==")
ck("an unlisted model falls back to the default price",
   C.model_price("nobody/such-model")[:2] == C.DEFAULT_PRICE)
_cat = C.SILICONFLOW_CATALOGUE[0]
ck("a catalogue model uses the catalogue price",
   C.model_price(_cat.id)[:2] == (_cat.in_usd, _cat.out_usd))
ck("the operator's override beats the catalogue",
   C.model_price(_cat.id, {"model_prices": {_cat.id: [9.0, 9.5]}})[:2]
   == (9.0, 9.5))
ck("a malformed override is ignored, not crashed on",
   C.model_price(_cat.id, {"model_prices": {_cat.id: "nonsense"}})[:2]
   == (_cat.in_usd, _cat.out_usd))
# THE BUG THIS PINS: an earlier draft looked the catalogue up under the name
# `MODELS`, which does not exist. The NameError was swallowed by a broad
# `except` and every cost came back $0 — a readout that fails to zero is worse
# than one that fails loudly, because nothing looks wrong.
ck("the catalogue lookup actually resolves (not silently $0)",
   C.usage_cost({"in": 1_000_000, "out": 0}, _cat.id) > 0,
   "a NameError here would read as free")

print("\n== the arithmetic ==")
ck("1M in + 1M out at 0.15/0.60 is $0.75",
   abs(C.usage_cost({"in": 1_000_000, "out": 1_000_000}, "x",
                    {"model_prices": {"x": [0.15, 0.60]}}) - 0.75) < 1e-9)
ck("output is priced separately from input",
   C.usage_cost({"in": 0, "out": 1_000_000}, "x",
                {"model_prices": {"x": [0.15, 0.60]}}) >
   C.usage_cost({"in": 1_000_000, "out": 0}, "x",
                {"model_prices": {"x": [0.15, 0.60]}}))
_cached = C.usage_cost({"in": 1_000_000, "out": 0, "cached_in": 1_000_000},
                       _cat.id)
_fresh = C.usage_cost({"in": 1_000_000, "out": 0, "cached_in": 0}, _cat.id)
ck("cached input is cheaper than fresh input",
   _cached < _fresh if _cat.cached_in_usd else _cached == _fresh,
   f"cached={_cached} fresh={_fresh}")
ck("cached_in larger than in cannot go negative",
   C.usage_cost({"in": 10, "out": 0, "cached_in": 10_000}, _cat.id) >= 0)

print("\n== unmetered is UNKNOWN, never free ==")
ck("no usage dict costs nothing to add", C.usage_cost(None, "x") == 0.0)
ck("a non-dict usage is survivable", C.usage_cost("nope", "x") == 0.0)
ck("non-numeric counts do not crash",
   C.usage_cost({"in": "a", "out": None}, "x") == 0.0)

print("\n== formatting tells the truth about small numbers ==")
ck("sub-cent spend is NOT shown as $0.00", C.fmt_cost(0.00042) != "$0.00")
ck("...and keeps enough digits to be true",
   C.fmt_cost(0.00042).startswith("$0.0004"), C.fmt_cost(0.00042))
ck("real zero is $0", C.fmt_cost(0) == "$0")
ck("dollars get two decimals and a thousands separator",
   C.fmt_cost(1234.5) == "$1,234.50", C.fmt_cost(1234.5))
ck("tokens compact: 940", C.fmt_tokens(940) == "940")
ck("tokens compact: 12.3k", C.fmt_tokens(12345) == "12.3k", C.fmt_tokens(12345))
ck("tokens compact: 1.21M", C.fmt_tokens(1_210_000) == "1.21M",
   C.fmt_tokens(1_210_000))
ck("a junk token count does not crash", C.fmt_tokens("x") == "0")

print("\n== the total survives closing the app ==")
# It did not. _spend_by_chat was a plain dict on the window under a docstring
# that said "per CHAT, not per process" — and it was per process exactly: every
# chat read zero on the next launch, including one that had been running all
# afternoon. A cost readout that resets is not a cost readout.
import json as _json
import tempfile as _tf
_prev = C.SPEND_LEDGER_JSON
try:
    C.SPEND_LEDGER_JSON = __import__("pathlib").Path(
        _tf.mkdtemp(prefix="spendtest-")) / "spend.json"
    ck("an absent ledger reads as empty, not as a crash",
       C.load_spend_ledger() == {})
    C.save_spend_ledger({"7": [120, 340, 0.00231, 1]})
    _back = C.load_spend_ledger()
    ck("a saved row comes back with its four numbers",
       _back.get("7") == [120, 340, 0.00231, 1], str(_back))
    ck("keys are strings (JSON has no integer keys, so int would split a chat)",
       all(isinstance(k, str) for k in _back))
    C.save_spend_ledger({"9": [1, 2, 3.0, 0], "bad": "junk", "x": [1]})
    _back = C.load_spend_ledger()
    ck("a malformed row is dropped, the good ones kept",
       list(_back) == ["9"], str(_back))
    open(C.SPEND_LEDGER_JSON, "w").write("{not json")
    ck("a corrupt file costs the history, not the app",
       C.load_spend_ledger() == {})
    C.save_spend_ledger({str(i): [i, i, float(i), 0]
                         for i in range(C.SPEND_LEDGER_MAX + 50)})
    ck("the file is bounded so a long-lived install cannot grow it forever",
       len(C.load_spend_ledger()) <= C.SPEND_LEDGER_MAX,
       str(len(C.load_spend_ledger())))
finally:
    C.SPEND_LEDGER_JSON = _prev

print("\n== the wiring that makes any of it possible ==")
_src = open(os.path.join(_ROOT, "basilisk_core.py"), encoding="utf-8").read()
ck("the stream asks the provider to report usage",
   '"stream_options"' in _src and '"include_usage": True' in _src)
# The usage chunk carries an EMPTY choices list. If it is read after the
# `if not choices: continue`, it is never seen at all.
_i_usage = _src.find('_u = obj.get("usage")')
_i_skip = _src.find("if not choices:\n                            continue")
ck("usage is read BEFORE the empty-choices skip",
   0 < _i_usage < _i_skip, f"usage@{_i_usage} skip@{_i_skip}")
ck("usage is handed back to the caller", '"usage": _usage,' in _src)
ck("it starts as None, so 'unreported' is distinguishable from zero",
   "_usage = None" in _src)
# A provider that 400s on stream_options must not lose the whole turn.
ck("a provider that rejects include_usage is retried without it",
   "_usage_rejected" in _src and "stream_option" in _src.lower())

_app = open(os.path.join(_ROOT, "basilisk.py"), encoding="utf-8").read()
ck("the app folds each turn's usage into a running total",
   "_account_turn" in _app and "self._account_turn(meta)" in _app)
ck("an unmetered turn increments the unknown counter",
   "_spend_unknown" in _app)
ck("totals are kept per CHAT, not per process",
   "_spend_by_chat" in _app and "_load_spend" in _app)
ck("...and the map is SEEDED FROM DISK, so a restart does not zero it",
   "load_spend_ledger()" in _app and "save_spend_ledger(self._spend_by_chat)"
   in _app)
ck("the chip's tooltip names a settings page that exists",
   "Settings -> Display -> Token pricing" in _app
   and "Settings -> Models" not in _app)
ck("...and are restored when a chat is opened",
   "self._load_spend(chat_id)" in _app)
ck("there is a chip, hidden until there is something to show",
   "spend_chip" in _app and "self.spend_chip.set_visible(False)" in _app)
ck("the chip is styled from palette values, so it themes",
   re.search(r"\.spend-chip\s*\{[^}]*#171716", _app) is not None)

# ── IT HAS TO BE READABLE ────────────────────────────────────────────
# It shipped at 12px in the DIM ink (#8e8c88) -- the styling for something you
# are NOT meant to read -- and on a real screen the operator could not make
# out the number at all. This is a figure being actively watched, so these
# pin the two properties that decide whether it can be read: size and
# contrast. Palette values only, so the nine themes still re-tint it.
_chip = re.search(r"\.spend-chip\s*\{([^}]*)\}", _app)
ck("the chip rule was found", _chip is not None)
if _chip:
    _body = _chip.group(1)
    _fs = re.search(r"font-size:\s*(\d+)px", _body)
    ck("it names a font size", _fs is not None)
    # MEASURED AGAINST THE MESSAGE TEXT, not against a round number. This
    # sheet is authored in px that _scale_css multiplies by the detected
    # ui_scale, and that scale is 0.7 on a desktop monitor -- so the 12px this
    # shipped at rendered at about 8px, while the message text at 30px
    # rendered at 21px. An absolute floor here would have been a guess about
    # a number in a file; the ratio is the thing that decides whether it can
    # actually be read on screen.
    _msg = re.search(r"\.msg-assistant[^{]*\{[^}]*font-size:\s*(\d+)px",
                     _app, re.S)
    ck("the message-text size was found, to measure against", _msg is not None)
    if _fs and _msg:
        _ratio = int(_fs.group(1)) / int(_msg.group(1))
        ck(f"the chip is at least half the message text "
           f"({_fs.group(1)}px vs {_msg.group(1)}px = {_ratio:.2f})",
           _ratio >= 0.5,
           "12px against 30px body text is 0.40 - that is the ratio nobody "
           "could read")
        ck("...and still visibly secondary to it, not shouting",
           _ratio <= 0.85, f"{_ratio:.2f}")
    ck("it uses the FULL-CONTRAST ink, not the dim one",
       "#dfdedb" in _body and "#8e8c88" not in _body,
       "#8e8c88 is the colour for text that does not matter")
    ck("...and carries a weight so it reads at a glance",
       re.search(r"font-weight:\s*(\d+)", _body) is not None)
    ck("the padding gives the pill room for it",
       re.search(r"padding:\s*(\d+)px", _body) is not None
       and int(re.search(r"padding:\s*(\d+)px", _body).group(1)) >= 5)
ck("a '+' marks totals that are known to be incomplete",
   'txt += "+"' in _app)

print(f"\nspend: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
