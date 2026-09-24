#!/usr/bin/env python3
"""
test_tokenchannel.py — a synthesized native call must reach the TOKEN channel,
not only the on_done payload.

THE BUG THIS PINS (found and fixed by the operator):
  DeepSeek delivers a tool call on the structured `delta.tool_calls` channel
  with EMPTY content. The backend folds it to canonical `<tool …>` text and put
  it in meta["text"] (the on_done payload) — but NOT through on_token. The
  streaming widget buffers TOKENS, and the host parses the WIDGET buffer, not
  the on_done payload. So the widget read as "" → no executable call → "response
  looked degraded" → an endless model retry, even though a perfect write_file /
  run call had arrived.

  test_structcalls.py already checked meta["text"], which is exactly why it
  stayed green while the app looped: the on_done payload was fine; the TOKEN
  stream was empty. This suite closes that gap by asserting on_token itself
  receives the synthesized call.

Stdlib only, faked HTTP layer, no GTK.

Run:  python3 tests/test_tokenchannel.py
"""

from __future__ import annotations

import json
import os
import sys
import types

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


def _sse(*objs):
    out = [("data: " + json.dumps(o)).encode() for o in objs]
    out.append(b"data: [DONE]")
    return out


class _R:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._lines)


def _spec():
    return types.SimpleNamespace(
        key="probe", base_url="https://example.invalid/v1",
        chain=["m"], extra_headers={}, engine="openai")


def _drive(frames):
    """Return (tokens_joined, on_done_payload). tokens_joined is EXACTLY what
    the streaming widget would have buffered — the reply the host parses."""
    b = C.OpenAICompatBackend(_spec(), api_key="k")
    toks = []
    out = {}

    def fake_urlopen(req, timeout=None):
        return _R(frames)

    real = C.urllib.request.urlopen
    C.urllib.request.urlopen = fake_urlopen
    try:
        b.stream_chat("m", [{"role": "user", "content": "x"}],
                      on_token=lambda t: toks.append(t),
                      on_done=lambda d: out.update(d or {}),
                      on_error=lambda e: out.update({"error": e}),
                      options={"max_tokens": 1024})
    finally:
        C.urllib.request.urlopen = real
    return "".join(toks), out


# ── 1. the empty-content structured call reaches the TOKEN stream ────
print("== a structured call with empty content reaches on_token ==")
_toks, _out = _drive(_sse(
    {"choices": [{"delta": {"reasoning_content": "planning..."}}]},
    {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"name": "write_file",
                                  "arguments": '{"path": "game.html",'}}]}}]},
    {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": ' "content": "<h1>hi</h1>"}'}}]}}]},
))
# THE point of this suite: parse the TOKEN buffer, not the on_done payload.
_wtoks = C.parse_tool_calls(_toks)
ck("the widget/token buffer carries the call (not just meta['text'])",
   len(_wtoks) == 1 and _wtoks[0].name == "write_file",
   repr(_toks))
ck("...with its arguments intact",
   bool(_wtoks) and _wtoks[0].args.get("path") == "game.html",
   str(_wtoks[0].args if _wtoks else None))
ck("...and no error", not _out.get("error"), str(_out.get("error")))
# and the on_done payload still agrees (belt and braces)
ck("on_done payload agrees with the token stream",
   len(C.parse_tool_calls(_out.get("text", ""))) == 1)

# ── 2. a run() call the same way (the other tool a build needs) ──────
print("\n== a structured run() call also reaches on_token ==")
_toks2, _ = _drive(_sse(
    {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"name": "run",
                                  "arguments": '{"command": "python -m pytest"}'}}]}}]},
))
_r2 = C.parse_tool_calls(_toks2)
ck("run call present in the token stream",
   len(_r2) == 1 and _r2[0].name == "run"
   and _r2[0].args.get("command") == "python -m pytest", repr(_toks2))

# ── 3. an ordinary textual reply is unaffected (no double emission) ──
print("\n== a normal textual answer is not touched ==")
_toks3, _out3 = _drive(_sse(
    {"choices": [{"delta": {"content": "Here is the plan: step one."}}]},
))
ck("plain content streams through unchanged",
   _toks3 == "Here is the plan: step one.", repr(_toks3))
ck("no phantom tool call invented from prose",
   len(C.parse_tool_calls(_toks3)) == 0)

# ── 4. a textual tool call is NOT doubled by the structured channel ──
print("\n== a textual call is not duplicated ==")
_toks4, _ = _drive(_sse(
    {"choices": [{"delta": {"content":
        '<tool name="run">{"command": "ls"}</tool>'}}]},
))
ck("exactly one call when the model wrote it as text",
   len(C.parse_tool_calls(_toks4)) == 1, repr(_toks4))


print(f"\n{_p} passed, {_f} failed")
sys.exit(1 if _f else 0)
