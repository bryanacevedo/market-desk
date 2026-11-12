"""The desk for an assistant: read-only questions over MCP. Find accounts, why an account has its tier, a segment's
figures, who owns what. It reads no money, writes nothing, and every query runs in a read-only transaction.
Modelled on Account Desk's src/outbound/mcp_server.py.

    python -m market mcp            # stdio, for Claude Desktop, Claude Code or any MCP client
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from . import catalog as C
from . import db
from .api import views

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

server = MCPServer(
    name="market-desk",
    title="Market Desk",
    instructions="Read-only questions about who a B2B team sells to: accounts and their tiers with the reasons, "
                 "segments and their figures, and who owns which accounts. No money figures.",
)


def _plain(x: Any) -> Any:
    return json.loads(json.dumps(x, default=lambda v: v.isoformat() if isinstance(v, (datetime, date))
                                 else float(v) if isinstance(v, Decimal) else str(v)))


def _read(fn):
    with db.tx() as cur:
        cur.execute("set transaction read only")
        return _plain(fn(cur))


def _company(cur, account: str) -> int | None:
    a = account.strip()
    if a.isdigit():
        return int(a)
    return db.val(cur, "select id from companies where not sole_trader and (primary_domain = lower(%s) or lower(name) = lower(%s)) order by id limit 1", a, a)


@server.tool(annotations=READ_ONLY)
def find_accounts(query: str, limit: int = 10) -> list[dict]:
    """Companies whose name or domain contains the query, with tier and segment under the published profile."""
    return _read(lambda cur: db.all(cur, """
        select c.id, c.name, c.primary_domain, c.lifecycle, f.tier, f.judged, f.score, f.segment
        from companies c join account_fit f on f.company = c.id and f.icp_version = (select id from icp_versions where status = 'published')
        where not c.sole_trader and (c.name ilike %s or c.primary_domain ilike %s) order by f.score desc nulls last limit %s""",
        f"%{_like(query)}%", f"%{_like(query)}%", max(1, min(limit, 50))))


def _like(q: str) -> str:
    return q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")[:80]


@server.tool(annotations=READ_ONLY)
def why_tier(account: str) -> dict:
    """Why a company has its tier: every rule it matches or misses, what was unknown, the exclude that applied, its
    owner and why. `account` is a domain, a name or an id."""
    def run(cur):
        cid = _company(cur, account)
        if cid is None:
            return {"error": f"No company matches '{account}'."}
        c = views.company(cur, cid, {"role": "revops", "id": 0}, allowed=False)
        return {k: c[k] for k in ("name", "domain", "lifecycle", "industry", "employees", "country", "fit", "owner", "tests")}
    return _read(run)


@server.tool(annotations=READ_ONLY)
def segment_figures(segment: str) -> dict:
    """One segment's figures: companies by tier, reachable companies, win rate with its range, roles on won deals, why
    they buy and the tests run on it. `segment` is its key or label."""
    def run(cur):
        key = next((k for k, v in C.SEGMENT_LABEL.items() if segment.lower() in (k, v.lower())), None)
        if key is None:
            return {"error": f"No segment matches '{segment}'.", "segments": list(C.SEGMENT_LABEL.values())}
        return views.segment(cur, key, False)
    return _read(run)


@server.tool(annotations=READ_ONLY)
def who_owns(person: str = "") -> dict:
    """Who owns what in the active plan: each person's accounts by tier and hours, or one person's book when `person`
    is an email or a name."""
    def run(cur):
        plan = db.val(cur, "select id from territory_plans where status = 'active'")
        if person:
            u = db.one(cur, "select id from users where lower(email) = lower(%s) or lower(name) = lower(%s)", person, person)
            if not u:
                return {"error": f"No one matches '{person}'."}
            return views.person(cur, u["id"], False)
        return {"people": db.all(cur, """select u.name, u.role, s.hours_available, s.hours_required, s.accounts_by_tier
                                         from capacity_snapshots s join users u on u.id = s.user_id where s.plan = %s""", plan)}
    return _read(run)


def main() -> None:
    server.run("stdio")
