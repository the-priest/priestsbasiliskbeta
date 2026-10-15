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
ck("...and are restored when a chat is opened",
   "self._load_spend(chat_id)" in _app)
ck("there is a chip, hidden until there is something to show",
   "spend_chip" in _app and "self.spend_chip.set_visible(False)" in _app)
ck("the chip is styled from palette values, so it themes",
   re.search(r"\.spend-chip\s*\{[^}]*#171716", _app) is not None)
ck("a '+' marks totals that are known to be incomplete",
   'txt += "+"' in _app)

print(f"\nspend: {_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
