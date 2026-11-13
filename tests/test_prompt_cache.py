"""Prompt caching (bl_117): every live Claude request carries the cache marker on the stable system block, and the
per-request payload only appears after it, in the user message."""
import json
from types import SimpleNamespace

import pytest

from market import llm


class _Parsed:
    def model_dump(self):
        return {"ok": True}


def _fake_client(seen):
    def parse(**kw):
        seen.append(kw)
        usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_creation_input_tokens=700, cache_read_input_tokens=0)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=_Parsed(), usage=usage, model=kw["model"])
    return SimpleNamespace(messages=SimpleNamespace(parse=parse))


@pytest.mark.parametrize("task", sorted(llm.TASKS))
def test_system_block_is_marked_and_payload_comes_after(task, monkeypatch):
    import anthropic
    seen: list[dict] = []
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: _fake_client(seen))
    payload = {"company": "Marker-Probe Ltd", "facts": [{"id": "f1", "text": "unique-per-request-text"}]}
    out, usage = llm._live(task, payload)
    kw = seen[0]
    assert kw["system"] == [{"type": "text", "text": llm.TASKS[task]["system"], "cache_control": {"type": "ephemeral"}}]
    assert "unique-per-request-text" not in json.dumps(kw["system"])  # nothing per-request before the breakpoint
    assert kw["messages"][0]["role"] == "user" and "unique-per-request-text" in kw["messages"][0]["content"]
    assert usage["cache_creation_input_tokens"] == 700 and usage["cache_read_input_tokens"] == 0


def test_cache_tokens_priced_at_cache_rates():
    task = "classify"
    pin, pout = llm.PRICES[llm.model_of(task)]
    pread = llm.CACHE_READ_PRICES.get(llm.model_of(task), pin * 0.1)
    cents = llm.cost_cents(task, {"input_tokens": 1000, "cache_creation_input_tokens": 1000, "cache_read_input_tokens": 1000, "output_tokens": 100})
    assert cents == pytest.approx((1000 * pin + 1000 * pin * 1.25 + 1000 * pread + 100 * pout) / 1_000_000 * 100)
