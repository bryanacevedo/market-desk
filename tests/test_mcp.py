"""The MCP server answers from the desk, reads no money, and cannot write."""
from __future__ import annotations

import asyncio
import json

from market import db, mcp_server


def test_every_tool_is_read_only(demo):
    tools = asyncio.run(mcp_server.server.list_tools())
    assert {t.name for t in tools} == {"find_accounts", "why_tier", "segment_figures", "who_owns"}
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)


def test_answers_and_unknowns(demo):
    with db.tx() as cur:
        domain = db.val(cur, "select primary_domain from companies where lifecycle = 'prospect' order by id limit 1")
    out = mcp_server.why_tier(domain)
    assert out["domain"] == domain and out["fit"]["tier"] in ("A", "B", "C", "X")
    assert "error" in mcp_server.why_tier("no-such-company.example")
    assert "error" in mcp_server.segment_figures("nothing")
    assert mcp_server.segment_figures("Developer tools")["key"] == "devtools"
    assert mcp_server.find_accounts(domain[:5])


def test_no_money_anywhere(demo):
    text = json.dumps([mcp_server.segment_figures("software"), mcp_server.who_owns(), mcp_server.who_owns("maya.okafor@lumenledger.example")])
    for k in ("tam_low", "sam_high", "som_low", "acv", "amount_cents", "expected_value", "pipeline_cents", '"ev"'):
        assert k not in text, k
