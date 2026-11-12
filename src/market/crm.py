"""Market Desk's books, written to a CRM (shared-world DESIGN.md section 7, step 1, and section 2a).

Optional and additive: with `CRM` unset Market Desk exports its books as files, as it always has, and nothing here
runs. With `CRM=crmdesk`, activating a plan queues every assigned account (tier, segment, fit score, profile version,
the AE who owns it and the SDR who works it) in `crm_outbox`, in the activation's own transaction, 100 accounts to a
row. The `crm_deliver` job sends each row to CRM Desk's `POST /api/v1/accounts/batch` and keeps the answer. A pinned
owner comes back refused with `owner_pinned`; the Handoffs page lists every refusal, and a manager decides in CRM Desk.

Every call fails closed: a timeout, a refused connection, a 429 or a 5xx leaves the row queued and the job retries
with backoff. With `CRM_JOURNAL` set (the shared-world rehearsal), each request and answer is also appended to that
file, so the demos can replay the same conversation (`replay`).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from . import db, jobs
from .db import J

CHUNK = 100  # accounts per request: each sent and committed on its own, well inside CRM Desk's feed settle


def enabled() -> bool:
    return os.environ.get("CRM", "").strip().lower() == "crmdesk"


def world_id(domain: str) -> str:
    return "co_" + hashlib.sha256(domain.encode()).hexdigest()[:12]


def plan_items(cur, plan_id: int) -> list[dict]:
    """Every account the plan assigns, with its tier and segment under the published profile, the AE who owns it and
    the SDR who works it (decision 39: sellers see their books where they work)."""
    rows = db.all(cur, """
        select c.primary_domain, c.name, c.country, c.region, c.industry, c.employees, c.revenue_band, f.tier, f.segment, f.score, v.number as icp_version, u.email as owner_email, u.role as owner_role,
               ae.email as ae_email
        from assignments a join companies c on c.id = a.company
        left join territories t on t.id = a.territory
        left join users u on u.id = a.owner
        left join users ae on ae.id = t.paired_ae
        left join icp_versions v on v.status = 'published'
        left join account_fit f on f.company = c.id and f.icp_version = v.id
        where a.plan = %s and not c.sole_trader
        order by c.primary_domain""", plan_id)
    items = []
    for r in rows:
        # Market Desk creates the accounts it plans (DESIGN.md section 5): the name and what the company-data vendor
        # shows travel with every item, so an account CRM Desk does not hold yet is made, and one it holds is matched.
        item = {"world_id": world_id(r["primary_domain"]), "domain": r["primary_domain"], "name": r["name"],
                "country": r["country"], "region": r["region"]}
        item.update({k: r[k] for k in ("industry", "employees", "revenue_band") if r[k] is not None})
        if r["tier"]:
            item.update(tier=r["tier"], segment=r["segment"], fit_score=r["score"], icp_version=f"v{r['icp_version']}")
        if r["owner_role"] == "sdr":
            item["sdr_owner_id"] = r["owner_email"]
            if r["ae_email"]:
                item["owner_id"] = r["ae_email"]
        elif r["owner_email"]:
            item["owner_id"] = r["owner_email"]
        items.append(item)
    return items


def queue_plan(cur, plan_id: int) -> int:
    """Queues the plan's books. Called in the activation's transaction; does nothing without a CRM."""
    if not enabled():
        return 0
    items = plan_items(cur, plan_id)
    for i in range(0, len(items), CHUNK):
        db.run(cur, "insert into crm_outbox (plan, kind, payload) values (%s, 'books', %s)", plan_id, J({"items": items[i:i + CHUNK]}))
    jobs.enqueue(cur, "crm_deliver", {}, dedupe_key="crm_deliver")
    return len(items)


class CrmDown(Exception):
    """CRM Desk did not answer with a decision. `retry_after` is the seconds it asked to wait, when it said."""

    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


def _send(body: dict) -> tuple[int, dict]:
    import httpx
    url, key = os.environ.get("CRM_DESK_URL", ""), os.environ.get("CRM_DESK_KEY", "")
    if not (url and key):
        raise CrmDown("CRM=crmdesk needs CRM_DESK_URL and CRM_DESK_KEY (a key made with --desk market_desk).")
    try:
        r = httpx.post(url.rstrip("/") + "/api/v1/accounts/batch", json=body, timeout=30.0,
                       headers={"authorization": f"Bearer {key}", "content-type": "application/json"})
    except httpx.HTTPError as exc:
        raise CrmDown(f"CRM Desk did not answer: {type(exc).__name__}") from exc
    if r.status_code == 429:
        raise CrmDown("CRM Desk asked to slow down", float(r.headers.get("retry-after") or 30))
    if r.status_code >= 500:
        raise CrmDown(f"CRM Desk answered {r.status_code}")
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"error": f"CRM Desk answered {r.status_code} without JSON"}


def deliver(cur, row: dict) -> dict:
    status, answer = _send(row["payload"])
    if status >= 400:  # a decision, not an outage: a bad key, a refused body. Handoffs shows it; a person fixes it.
        db.run(cur, "update crm_outbox set status = 'failed', attempts = attempts + 1, last_error = %s, answer = %s where id = %s",
               str(answer.get("error") or f"CRM Desk answered {status}")[:300], J(answer), row["id"])
        return answer
    db.run(cur, "update crm_outbox set status = 'sent', attempts = attempts + 1, answer = %s, sent_at = app_now() where id = %s",
           J(answer), row["id"])
    journal = os.environ.get("CRM_JOURNAL")
    if journal:
        at = db.val(cur, "select app_now()")
        with open(journal, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": at.isoformat(), "actor": "market_desk", "method": "POST", "path": "/accounts/batch",
                                "body": row["payload"], "status": status, "answer": answer}, sort_keys=True) + "\n")
    return answer


@jobs.handler("crm_deliver")
def _deliver_one(cur, payload: dict) -> None:
    """One row per job, so each batch commits on its own; the next row is queued as its own job. A CRM that does not
    answer leaves the row queued and the job retries with backoff, or after the wait a 429 asked for."""
    row = db.one(cur, "select * from crm_outbox where status = 'queued' order by id limit 1 for update skip locked")
    if row is None:
        return
    try:
        deliver(cur, row)
    except CrmDown as exc:
        if exc.retry_after:
            from datetime import timedelta
            jobs.enqueue(cur, "crm_deliver", {}, delay=timedelta(seconds=exc.retry_after))
            return
        raise  # the job retries with backoff; nothing is marked sent on a guess
    jobs.enqueue(cur, "crm_deliver", {})


def _latest(cur) -> dict[str, dict]:
    """Each account's latest answer from the CRM: its refusals and its error, from the last row that carried it."""
    latest: dict[str, dict] = {}
    for row in db.all(cur, "select payload, answer, sent_at from crm_outbox where status = 'sent' order by sent_at, id"):
        items = row["payload"]["items"]
        for res in (row["answer"] or {}).get("results", []):
            it = items[res["index"]]
            latest[it["domain"]] = {"item": it, "refused": res.get("refused") or [], "error": res.get("error"), "at": row["sent_at"]}
    return latest


def refusals(cur) -> list[dict]:
    """The changes the CRM refused in each account's latest answer: an account accepted later is no longer listed."""
    out = []
    for domain, r in _latest(cur).items():
        for f in r["refused"]:
            out.append({"domain": domain, "field": f["field"], "reason": f["reason"], "proposed": r["item"].get(f["field"]),
                        "at": r["at"]})
    return sorted(out, key=lambda r: (r["domain"], r["field"]))


def errors(cur) -> list[dict]:
    """Accounts the CRM could not take at all in their latest answer, with its reason."""
    return sorted(({"domain": d, "error": r["error"], "at": r["at"]} for d, r in _latest(cur).items() if r["error"]),
                  key=lambda r: r["domain"])


def summary(cur) -> dict:
    latest = _latest(cur)
    return {"enabled": enabled(),
            "sent": len(latest),  # distinct accounts the CRM has answered for, however many times each was sent
            "queued": db.val(cur, "select coalesce(sum(jsonb_array_length(payload->'items')), 0) from crm_outbox where status = 'queued'"),
            "failed": db.all(cur, "select id, last_error, created_at from crm_outbox where status = 'failed' order by id"),
            "last_sent_at": max((r["at"] for r in latest.values()), default=None),
            "refusals": refusals(cur), "errors": errors(cur)}


def replay(cur, journal: Path) -> int:
    """The demo build: what Market Desk sent in the rehearsal and how CRM Desk answered, kept as sent rows, so the
    demo shows the same refusals CRM Desk's demo shows."""
    if not journal.exists():
        return 0
    n = 0
    for line in journal.read_text().splitlines():
        step = json.loads(line)
        if step["actor"] != "market_desk":
            continue
        plan = db.val(cur, "select id from territory_plans where status = 'active'")
        db.run(cur, """insert into crm_outbox (plan, kind, payload, status, attempts, answer, sent_at, created_at)
                       values (%s, 'books', %s, 'sent', 1, %s, %s, %s)""", plan, J(step["body"]), J(step["answer"]), step["at"], step["at"])
        n += 1
    return n
