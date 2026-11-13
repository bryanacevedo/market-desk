"""Marketing qualified accounts (MQA), decided here when this desk is connected to CRM Desk (docs/DECISIONS.md 49 to 51;
CRM Desk's own decisions 64 and 72).

An account is marketing qualified when it fits and has engaged: its tier is one the rule names, and at least
`min_people` of its people earned `min_points` between them inside `window_days`. This desk holds the first half: tiers
are its own. It holds none of the second: engagement is people doing things (a form, a reply, a meeting), and this desk
stores no people (design principle 3). So it reads engagement from CRM Desk, counts it, and keeps nothing of it: per
account, points and the number of people who scored go to CRM Desk and nowhere else here. A person's id is held in
memory while a run counts, and never written. The weights come from CRM Desk's `mql` definition (the same points a person earns toward MQL), read with a
key's `read` scope; this desk records which version it read (`definitions_read`) so a statement can say so.

What it sends, through the same outbox and the same batch call as the books (kind `mqa`): `mqa_at`, `mqa_points` and
`mqa_people` for an account that qualifies, and `mqa_at: null` for one that stopped. CRM Desk takes them from this
desk's key only while it is set to follow this desk; otherwise it refuses each field (`computed_by_crm_desk`) and
Handoffs lists the refusal. The rule is a numbered, hashed definition owned here and published at `/api/definitions`.

Optional and additive: nothing here runs without `CRM=crmdesk`, and a reader that lacks the engagement methods (a
Salesforce-shaped one) makes the run say so and send nothing.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import db, jobs
from .db import J

log = logging.getLogger("market.mqa")

NAME = "mqa"
OWNER = "market_desk"
SCHEMA_VERSION = 1
# The numbers CRM Desk starts with (its DEFAULT_MQA). Today's rule is the newest published version, so a change is a
# new version with a name on it, never an edit.
DEFAULT_RULE = {"tiers": ["A", "B"], "untiered": True, "min_points": 20, "min_people": 2, "window_days": 30}
ACCOUNT_TYPES = ["former_customer", "other", "prospect"]        # a customer, a partner or a competitor is not marketed to as a prospect
POINT_KINDS = ("form", "meeting", "email_reply", "call_connected", "attended", "linkedin_accepted")
RUN_EVERY = timedelta(hours=1)


class MqaUnavailable(Exception):
    """The run cannot decide anything (the reader has no engagement, or CRM Desk has no points to read). Nothing is
    sent on a guess."""


# ---------------------------------------------------------------- the definition

def _body(rule: dict) -> dict:
    """What is published. No ids and no dates, lists that are sets are sorted, so an unchanged rule keeps its hash."""
    return {"rule": {"tiers": sorted(rule["tiers"]), "untiered": bool(rule["untiered"]), "min_points": int(rule["min_points"]),
                     "min_people": int(rule["min_people"]), "window_days": int(rule["window_days"])},
            "account_types": ACCOUNT_TYPES,
            "not_when": ["do_not_prospect", "deleted", "merged"],
            "tier_from": "this desk's published profile version; an account it has not scored counts as untiered",
            "points_from": {"definition": "mql", "owner_desk": "crm_desk", "field": "rule.points"},
            "engagement_from": "crm_desk activities inside the window; this desk keeps counts only, never a person"}


def hash_of(body: dict) -> str:
    """The same hash CRM Desk puts on its definitions (docs/API.md, Definitions), so one reader checks both."""
    return "sha256:" + hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _row(r: dict) -> dict:
    return {"name": r["name"], "owner_desk": OWNER, "version": r["version"], "hash": r["hash"],
            "published_at": r["published_at"].isoformat(), "changed_by": r["changed_by"], "body": r["body"]}


def current(cur) -> dict:
    """The newest version of the rule. The first read publishes version 1 (as `system`), the way CRM Desk does."""
    r = db.one(cur, "select * from definition_versions where name = %s order by version desc limit 1", NAME)
    if r is None:
        return set_rule(cur, DEFAULT_RULE, "system")
    return _row(r)


def rule(cur) -> dict:
    return current(cur)["body"]["rule"]


def set_rule(cur, new: dict, by: str) -> dict:
    """Publishes a rule as the next version when its body differs from the newest; returns the newest either way."""
    new = {**DEFAULT_RULE, **new}
    if (not isinstance(new["tiers"], list) or not new["tiers"] or any(t not in ("A", "B", "C", "X") for t in new["tiers"])
            or any(not isinstance(new[k], int) or isinstance(new[k], bool) or new[k] < 1 for k in ("min_points", "min_people", "window_days"))
            or new["window_days"] > 365):
        raise ValueError("The MQA rule needs tiers from A, B, C, X and whole numbers of one or more for points, people and days.")
    body = _body(new)
    last = db.one(cur, "select * from definition_versions where name = %s order by version desc limit 1", NAME)
    if last is not None and last["hash"] == hash_of(body):
        return _row(last)
    row = db.one(cur, "insert into definition_versions (name, version, hash, body, changed_by) values (%s, %s, %s, %s, %s) returning *",
                 NAME, (last["version"] + 1) if last else 1, hash_of(body), J(body), by)
    return _row(row)


def published(cur) -> dict:
    """The index and the bodies this desk owns, in the shape of CRM Desk's `GET /definitions`."""
    d = current(cur)
    return {"desk": OWNER, "schema_version": SCHEMA_VERSION, "as_of": db.val(cur, "select app_now()").isoformat(), "definitions": [d],
            "index": [{k: d[k] for k in ("name", "owner_desk", "version", "hash")} | {"read_at": None, "link": "/api/definitions/" + NAME}]}


def versions(cur) -> dict:
    return {"name": NAME, "versions": [{"version": r["version"], "hash": r["hash"], "published_at": r["published_at"].isoformat(),
                                        "changed_by": r["changed_by"]}
                                       for r in db.all(cur, "select * from definition_versions where name = %s order by version desc", NAME)]}


def version(cur, number: int) -> dict | None:
    r = db.one(cur, "select * from definition_versions where name = %s and version = %s", NAME, number)
    return None if r is None else _row(r)


# ---------------------------------------------------------------- what engagement is worth (CRM Desk's points)

@dataclass(frozen=True)
class Touch:
    """One activity, reduced to what scoring needs. `people` are CRM Desk's own opaque ids: counted, never stored."""
    activity: str
    account: str | None
    people: tuple[str, ...]
    type: str
    direction: str | None = None
    outcome: str | None = None
    meeting_status: str | None = None
    occurred_at: datetime | None = None


def worth(t: Touch, points: dict) -> int:
    """What one activity pays each person on it, by CRM Desk's published points. Our own outbound touches pay nothing:
    only what the person did."""
    if t.type == "form":
        return points["form"]
    if t.type == "attended":
        return points["attended"]
    if t.type == "meeting":
        return points["meeting"] if t.meeting_status in ("booked", "held") else 0
    if t.type == "email":
        return points["email_reply"] if t.direction == "in" else 0
    if t.type == "call":
        return points["call_connected"] if t.outcome == "connected" else 0
    if t.type == "linkedin":
        return points["linkedin_accepted"] if t.outcome == "accepted" else 0
    return 0


def engagement(touches, points: dict, start: datetime, end: datetime, account_of=None) -> dict[str, tuple[int, int]]:
    """Per CRM account id: (points, people who scored) inside [start, end]. Each activity counts once per person. An
    activity with no account takes its person's account from `account_of(person)`, when the reader can say. Only the
    two counts survive this function."""
    per: dict[str, dict[str, int]] = {}
    seen: set[tuple[str, str]] = set()
    for t in touches:
        if t.occurred_at is None or not (start <= t.occurred_at <= end):
            continue
        pts = worth(t, points)
        if pts <= 0:
            continue
        for person in dict.fromkeys(t.people):
            if (t.activity, person) in seen:
                continue
            seen.add((t.activity, person))
            acct = t.account or (account_of(person) if account_of else None)
            if acct:
                per.setdefault(acct, {})[person] = per.get(acct, {}).get(person, 0) + pts
    return {a: (sum(p.values()), len(p)) for a, p in per.items()}


# ---------------------------------------------------------------- the run

def enabled() -> bool:
    """On with `CRM=crmdesk`, like the books; `CRM_MQA=0` turns only this off."""
    from . import crm
    return crm.enabled() and os.environ.get("CRM_MQA", "").strip().lower() not in ("0", "false", "no", "off")


def fits(cur, domain: str, r: dict, crm_tier: str | None = None) -> bool:
    """Whether an account's tier is one the rule names, read from the profile version published now. A company this
    desk does not hold, or holds but has not scored, has no tier of this desk's: the tier CRM Desk holds for it counts
    (none means untiered, which the rule says to count or not)."""
    c = db.one(cur, "select id from companies where primary_domain = %s and not sole_trader", domain)
    f = None if c is None else db.one(cur, """select f.tier from account_fit f join icp_versions v on v.id = f.icp_version
                                              where f.company = %s and v.status = 'published'""", c["id"])
    tier = crm_tier if f is None else f["tier"]
    if tier is None or tier == "Not judged":
        return bool(r["untiered"])
    return tier in r["tiers"]


def decide(cur, found: dict[str, tuple[int, int]], facts: dict[str, dict], r: dict) -> dict[str, tuple[int, int]]:
    """{domain: (points, people)} for every account that qualifies. `found` is engagement by CRM account id; `facts`
    is what CRM Desk says about the accounts that cleared the thresholds (domain, type, flags)."""
    out: dict[str, tuple[int, int]] = {}
    for aid, (pts, n) in found.items():
        if pts < r["min_points"] or n < r["min_people"]:
            continue
        f = facts.get(aid)
        if not f or not f.get("domain") or f.get("deleted") or f.get("do_not_prospect") or f.get("type") not in ACCOUNT_TYPES:
            continue
        if fits(cur, f["domain"], r, f.get("tier")):
            out[f["domain"].lower()] = (pts, n)
    return out


def plan(desired: dict[str, tuple[int, int]], marked: dict[str, dict], now: datetime) -> list[dict]:
    """The items that bring CRM Desk from what it holds to `desired`: a new mark with its date, new counts for a mark
    that stays, and `mqa_at: null` for one that ended. `marked` is what CRM Desk says it holds now (domain to its
    `mqa_at`, points and people), so a mark written before this desk was connected, or by an earlier run that the CRM
    refused, is judged like any other."""
    from .crm import world_id
    stamp = now.isoformat()
    items = []
    for domain in sorted(desired):
        pts, n = desired[domain]
        m = marked.get(domain)
        if m is None or m.get("mqa_at") is None:
            items.append({"world_id": world_id(domain), "domain": domain, "mqa_at": stamp, "mqa_points": pts, "mqa_people": n})
        elif (m.get("mqa_points"), m.get("mqa_people")) != (pts, n):
            items.append({"world_id": world_id(domain), "domain": domain, "mqa_points": pts, "mqa_people": n})
    for domain in sorted(set(marked) - set(desired)):
        items.append({"world_id": world_id(domain), "domain": domain, "mqa_at": None})
    return items


def _shape(items: list[dict]) -> set:
    return {(i["domain"], i.get("mqa_points"), i.get("mqa_people"), "mqa_at" in i and i["mqa_at"] is None) for i in items}


def _already_refused(cur, items: list[dict]) -> bool:
    """True when the newest mqa request CRM Desk answered carried the same decisions and it refused some: CRM Desk is not
    following this desk, so sending them again every hour would only pile up rows. Handoffs already lists the refusal."""
    last = db.one(cur, "select payload, answer from crm_outbox where kind = 'mqa' and status = 'sent' order by id desc limit 1")
    if last is None or not items:
        return False
    return (any(r.get("refused") for r in (last["answer"] or {}).get("results", []))
            and _shape(last["payload"]["items"]) >= _shape(items))


def queue(cur, items: list[dict], version_number: int) -> int:
    """Queues the items (100 to a request). A request still waiting is cancelled first: the new items are worked out
    against what CRM Desk holds now and replace the old ones."""
    from .crm import CHUNK
    db.run(cur, "update crm_outbox set status = 'cancelled', last_error = 'Superseded by a newer MQA run' "
                "where kind = 'mqa' and status = 'queued'")
    if _already_refused(cur, items):
        return 0
    for i in range(0, len(items), CHUNK):
        db.run(cur, "insert into crm_outbox (kind, payload) values ('mqa', %s)", J({"items": items[i:i + CHUNK], "definition_version": version_number}))
    if items:
        jobs.enqueue(cur, "crm_deliver", {}, dedupe_key="crm_deliver")
    return len(items)


def read_points(reader) -> tuple[dict, dict]:
    """CRM Desk's `mql` definition: the points, and which version they came from."""
    d = reader.definition("mql")
    points = ((d.get("body") or {}).get("rule") or {}).get("points") or {}
    if any(not isinstance(points.get(k), int) for k in POINT_KINDS):
        raise MqaUnavailable("CRM Desk's mql definition holds no points to count engagement by.")
    return points, {"name": "mql", "owner_desk": d.get("owner_desk") or "crm_desk", "version": d["version"], "hash": d["hash"]}


def sync(reader, *, now: datetime | None = None, cur=None) -> dict:
    """One run: read CRM Desk's points and the window's activity, decide, and queue what changed. The caller delivers
    (the `crm_deliver` job, or `python -m market crm-mqa`). The reads happen outside any transaction; `cur` is a test's own
    transaction."""
    from .deals_in import _scope
    for m in ("definition", "touches", "account_facts", "marked"):
        if not hasattr(reader, m):
            raise MqaUnavailable("This CRM reader cannot say who engaged with an account, so this desk decides nothing.")
    with _scope(cur) as c:
        r = rule(c)
        now = now or db.val(c, "select app_now()")
    start = now - timedelta(days=r["window_days"])
    points, used = read_points(reader)
    cache: dict[str, str | None] = {}

    def account_of(person: str) -> str | None:
        if person not in cache:
            cache[person] = reader.contact_account(person) if hasattr(reader, "contact_account") else None
        return cache[person]

    seen = []
    found = engagement(_tap(reader.touches(start), seen), points, start, now, account_of)
    cache.clear()                                         # nothing about a person outlives the counting
    clear = [a for a, (p, n) in found.items() if p >= r["min_points"] and n >= r["min_people"]]
    facts = {a: reader.account_facts(a) for a in clear}
    marked = reader.marked()
    with _scope(cur) as c:
        db.run(c, """insert into definitions_read (name, owner_desk, version, hash, read_at) values (%s, %s, %s, %s, app_now())
                       on conflict (name) do update set owner_desk = excluded.owner_desk, version = excluded.version,
                       hash = excluded.hash, read_at = excluded.read_at""", used["name"], used["owner_desk"], used["version"], used["hash"])
        d = current(c)
        desired = decide(c, found, facts, r)
        items = plan(desired, marked, now)
        n = queue(c, items, d["version"])
        _journal(c, "/changes/activities", start, len(seen))
    return {"definition": {"version": d["version"], "hash": d["hash"]}, "points_from": used, "window_from": start.isoformat(),
            "activities_read": len(seen), "accounts_with_engagement": len(found), "qualify": len(desired), "queued": n,
            "marked": sum(1 for i in items if i.get("mqa_at")), "cleared": sum(1 for i in items if "mqa_at" in i and i["mqa_at"] is None),
            "counts_changed": sum(1 for i in items if "mqa_at" not in i)}


def _tap(touches, seen: list):
    for t in touches:
        seen.append(1)
        yield t


def _journal(cur, path: str, since: datetime, count: int) -> None:
    """With CRM_JOURNAL set, the read is noted the way a pull's reads are; the replay ignores reads."""
    journal = os.environ.get("CRM_JOURNAL")
    if journal:
        at = db.val(cur, "select app_now()")
        with open(journal, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": at.isoformat(), "actor": "market_desk", "method": "GET", "path": path, "since": since.isoformat(),
                                "count": count, "next": None}, sort_keys=True) + "\n")


def state(cur) -> dict:
    """For Handoffs: the rule this desk decides by, and which version of CRM Desk's points it last read."""
    d = current(cur)
    read = db.one(cur, "select version, hash, read_at from definitions_read where name = 'mql'")
    last = db.one(cur, "select id, status, sent_at, jsonb_array_length(payload->'items') as items from crm_outbox where kind = 'mqa' order by id desc limit 1")
    return {"enabled": enabled(), "rule_version": d["version"], "rule_hash": d["hash"], "points_read": read, "last_request": last}


@jobs.handler("crm_mqa")
def _run(cur, payload: dict) -> None:
    """Hourly while a CRM is set. An outage or a reader that cannot answer ends this run, never the schedule."""
    from . import crm
    wait = RUN_EVERY
    if enabled():
        try:
            sync(crm.CrmDeskReader.from_env())    # its own transactions; the rows it queues go out through crm_deliver
        except crm.CrmDown as exc:
            wait = timedelta(seconds=exc.retry_after or 300)
            log.warning("mqa run stopped: %s", exc)
        except MqaUnavailable as exc:
            log.warning("mqa run skipped: %s", exc)
    jobs.enqueue(cur, "crm_mqa", {}, delay=wait, dedupe_key="crm_mqa")
