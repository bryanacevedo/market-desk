"""What this desk states about itself for Tally in CRM Desk (CRM Desk docs/TALLY-SPEC.md section 5, and its rules 1 to 3).

Two read-only calls, both behind one desk read key (`DESK_READ_KEY`, sent as a bearer token). Unset, nothing is served
(404), so a desk running alone exposes nothing and CRM Desk reads "not checked: answered 404", never agreement.

- `statement(cur)`: counts, versions and hashes. The definitions this desk owns and the versions it read from others, the
  state of its queue of writes to CRM Desk, and the plan in play (the scheduled plan if one waits, else the one in effect):
  how many batches it queued and how many were sent, how many accounts, and an etag over what the plan assigns.
- `owners(cur, plan_id, cursor)`: one row per planned account, 500 a page: the AE and SDR in force today and the ones the
  plan names, the tier and segment under the published profile. No person outside the team, no contact, no money.

Nothing here is invented: every figure is counted from the plan, the outbox and the definitions tables.
"""
from __future__ import annotations

import hashlib
import hmac
import os

from . import crm, db, mqa, territories

PAGE = 500
SCHEMA_VERSION = 1


def read_key() -> str:
    return os.environ.get("DESK_READ_KEY", "").strip()


def allowed(header: str | None) -> bool | None:
    """None: no key is set, so this desk serves nothing. False: a key is set and the request's is wrong."""
    key = read_key()
    if not key:
        return None
    given = (header or "")[7:] if (header or "").lower().startswith("bearer ") else ""
    return hmac.compare_digest(given.encode(), key.encode())


def _plan(cur) -> dict | None:
    """The plan Tally compares: the one scheduled for a later start if there is one, else the one in effect."""
    return db.one(cur, "select * from territory_plans where status in ('scheduled', 'active') order by (status = 'scheduled') desc limit 1")


def _outbox(cur) -> list[dict]:
    rows = db.all(cur, """select kind,
                          count(*) filter (where status = 'queued') as queued,
                          count(*) filter (where status = 'queued' and attempts > 0) as retrying,
                          count(*) filter (where status = 'failed' and (
                              (kind = 'books' and plan in (select id from territory_plans where status in ('active', 'scheduled')))
                              or (kind = 'scores' and icp_version = (select id from icp_versions where status = 'published'))
                              or (kind = 'mqa' and id > coalesce((select max(id) from crm_outbox where kind = 'mqa' and status = 'sent'), 0)))) as failed,
                          min(created_at) filter (where status = 'queued') as oldest_queued_at,
                          max(sent_at) filter (where status = 'sent') as last_sent_at
                          from crm_outbox where status <> 'cancelled' group by kind order by kind""")
    out = []
    for r in rows:
        err = db.val(cur, "select last_error from crm_outbox where kind = %s and status = 'failed' order by id desc limit 1", r["kind"]) if r["failed"] else None
        out.append({"to": "crm_desk", "kind": r["kind"], "queued": int(r["queued"]), "oldest_queued_at": r["oldest_queued_at"] and r["oldest_queued_at"].isoformat(),
                    "retrying": int(r["retrying"]), "failed": int(r["failed"]), "last_error": err,
                    "last_sent_at": r["last_sent_at"] and r["last_sent_at"].isoformat()})
    return out


def _etag(cur, plan: dict) -> str:
    """Changes when what the plan assigns, the people moved by hand, the published profile or the plan in effect changes."""
    parts = [str(plan["id"]), plan["status"], str(plan["effective_on"])]
    parts.append(str(db.val(cur, """select md5(coalesce(string_agg(company || ':' || coalesce(owner, 0) || ':' || coalesce(territory, 0), ',' order by company), ''))
                                    from assignments where plan = %s""", plan["id"])))
    parts.append(str(db.val(cur, """select md5(coalesce(string_agg(company || ':' || role || ':' || coalesce(to_user, 0), ',' order by company, role), ''))
                                    from plan_hand_changes where plan = %s""", plan["id"])))
    parts.append(str(db.val(cur, "select coalesce(max(number), 0) from icp_versions where status = 'published'")))
    parts.append(str(db.val(cur, "select coalesce(max(id), 0) from territory_plans where status = 'active'")))
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def statement(cur) -> dict:
    now = db.val(cur, "select app_now()")
    owned = mqa.current(cur)
    used = [{"name": r["name"], "owner_desk": r["owner_desk"], "version": r["version"], "hash": r["hash"], "read_at": r["read_at"].isoformat()}
            for r in db.all(cur, "select * from definitions_read order by name")]
    owned_list = [{"name": owned["name"], "version": owned["version"], "hash": owned["hash"], "published_at": owned["published_at"]}]
    pub = db.one(cur, "select number, published_at from icp_versions where status = 'published'")
    if pub:      # Tally's rule 3 times its grace window from this publish time
        text = icp(cur)
        owned_list.append({"name": "icp", "version": f"v{pub['number']}", "hash": text["hash"], "published_at": pub["published_at"] and pub["published_at"].isoformat()})
    out = {"desk": "market_desk", "as_of": now.isoformat(), "schema_version": SCHEMA_VERSION,
           "definitions_owned": owned_list,
           "definitions_used": used}
    if crm.enabled():      # with no CRM set this desk writes nothing, so it states no queue (Tally reads "does not state its queue")
        out["outbox"] = _outbox(cur)
    p = _plan(cur)
    if p:
        b = db.one(cur, """select count(*) filter (where status in ('queued', 'sent', 'failed')) as batches, count(*) filter (where status = 'sent') as sent,
                           coalesce(sum(jsonb_array_length(payload->'items')) filter (where status in ('queued', 'sent', 'failed')), 0) as items,
                           coalesce(sum(jsonb_array_length(payload->'items')) filter (where status = 'sent'), 0) as items_sent
                           from crm_outbox where plan = %s and kind = 'books'""", p["id"])
        v = db.val(cur, "select number from icp_versions where status = 'published'")
        out["plan"] = {"id": str(p["id"]), "name": p["name"], "activated_at": p["activated_at"] and p["activated_at"].isoformat(),
                       "effective_on": str(p["effective_on"]), "batches": int(b["batches"]), "batches_sent": int(b["sent"]),
                       "items": int(b["items"]), "items_sent": int(b["items_sent"]), "owners_etag": _etag(cur, p),
                       "icp_version": f"v{v}" if v else None}
    return out


class PlanChanged(Exception):
    """The plan asked for is not the plan this desk now states."""


def owners(cur, plan_id: str | None, cursor: str | None) -> dict:
    p = _plan(cur)
    if not p or (plan_id and str(p["id"]) != str(plan_id)):
        raise PlanChanged("That plan is not the one this desk states now.")
    planned = territories.roles_by_company(cur, p["id"])
    scheduled = p["status"] == "scheduled"
    inforce = territories.roles_by_company(cur, db.val(cur, "select id from territory_plans where status = 'active'") or 0) if scheduled else planned
    # Only while the plan waits: once it is in effect the assignments already hold what the person chose. An unknown person (no id here) is not stated.
    hand = {(h["company"], h["role"]): h["to_user"] for h in territories.hand_changes(cur, p["id"]) if scheduled and h["to_user"]}
    if scheduled and not db.val(cur, "select 1 from territory_plans where status = 'active'"):
        return {"plan": str(p["id"]), "data": [], "next": None}      # nothing is in force yet, so nothing can differ
    emails = {u["id"]: u["email"] for u in db.all(cur, "select id, email from users")}
    after = int(cursor) if cursor and str(cursor).isdigit() else 0
    rows = db.all(cur, """select c.id, c.primary_domain, f.tier, f.segment from assignments a join companies c on c.id = a.company
                          left join icp_versions v on v.status = 'published'
                          left join account_fit f on f.company = c.id and f.icp_version = v.id
                          where a.plan = %s and not c.sole_trader and c.id > %s order by c.id limit %s""", p["id"], after, PAGE)
    mail = lambda uid: emails.get(uid) if uid else None      # noqa: E731
    data = []
    for r in rows:
        c = r["id"]
        pae, psdr = planned.get(c, (None, None))
        iae, isdr = inforce.get(c, (None, None)) if c in inforce else (None, None)
        # A role a person moved by hand while the plan waited is the CRM's to hold: it is stated as agreed, not as a difference.
        if (c, "owner") in hand:
            pae = iae = hand[(c, "owner")]
        if (c, "sdr") in hand:
            psdr = isdr = hand[(c, "sdr")]
        data.append({"world_id": crm.world_id(r["primary_domain"]), "domain": r["primary_domain"], "tier": r["tier"], "segment": r["segment"],
                     "owner_email": mail(iae), "planned_owner_email": mail(pae), "sdr_owner_email": mail(isdr), "sdr_planned_owner_email": mail(psdr),
                     "effective_on": str(p["effective_on"])})
    nxt = str(rows[-1]["id"]) if len(rows) == PAGE else None
    return {"plan": str(p["id"]), "data": data, "next": nxt}


def icp(cur) -> dict | None:
    """The published profile as Events Desk's ICP document (icp.md), with its version and a hash of the text: what Events
    Desk's read-only ICP page shows when it runs beside this desk."""
    from . import handoff
    v = db.one(cur, "select * from icp_versions where status = 'published'")
    if v is None:
        return None
    md = handoff.events_desk_md(cur, v).decode()
    return {"desk": "market_desk", "name": "icp", "format": "icp.md", "version": v["number"],
            "hash": "sha256:" + hashlib.sha256(md.encode()).hexdigest(),
            "published_at": v["published_at"].isoformat() if v["published_at"] else None, "markdown": md}
