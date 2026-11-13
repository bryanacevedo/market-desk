"""Market Desk's books, written to a CRM (shared-world DESIGN.md section 7, step 1, and section 2a).

Optional and additive: with `CRM` unset Market Desk exports its books as files, as it always has, and nothing here
runs. With `CRM=crmdesk`, activating a plan queues every assigned account (tier, segment, fit score, profile version,
the AE who owns it and the SDR who works it) in `crm_outbox`, in the activation's own transaction, 100 accounts to a
row. The `crm_deliver` job sends each row to CRM Desk's `POST /api/v1/accounts/batch` and keeps the answer. A pinned
owner comes back refused with `owner_pinned`; the Handoffs page lists every refusal, and a manager decides in CRM Desk.

Every call fails closed: a timeout, a refused connection, a 429 or a 5xx leaves the row queued and the job retries
with backoff. Publishing an ICP version queues the version's tiers the same way (kind `scores`, no owners, so a pin or
a manager's move is never touched). The read side (`CrmReader`, Salesforce's nouns) pulls opportunities into the deals
table through `deals_in`. With `CRM_JOURNAL` set (the shared-world rehearsal), each request and answer is also appended to that
file, so the demos can replay the same conversation (`replay`).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from . import db, jobs
from .db import J

log = logging.getLogger("market.crm")
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


def score_items(cur, plan_id: int, version_id: int) -> list[dict]:
    """The published version on every account of the plan that has been scored under it: tier, segment, score and
    version only. No owners and no firmographics, so CRM Desk's pins and people's edits are left alone."""
    rows = db.all(cur, """
        select c.primary_domain, c.name, f.tier, f.segment, f.score, v.number
        from assignments a join companies c on c.id = a.company
        join icp_versions v on v.id = %s
        join account_fit f on f.company = c.id and f.icp_version = v.id
        where a.plan = %s and not c.sole_trader order by c.primary_domain""", version_id, plan_id)
    return [{"world_id": world_id(r["primary_domain"]), "domain": r["primary_domain"], "tier": r["tier"],
             "segment": r["segment"], "fit_score": r["score"], "icp_version": f"v{r['number']}"} for r in rows]


def queue_scores(cur, version_id: int) -> int:
    """Queues the published version's tiers for the active plan's accounts. Called once the version is scored.
    Rows of another version still waiting are cancelled: only the newest version is worth sending. Does nothing
    without a CRM, without an active plan, or when the version is no longer the published one."""
    if not enabled():
        return 0
    plan = db.val(cur, "select id from territory_plans where status = 'active'")
    if plan is None or db.val(cur, "select status from icp_versions where id = %s", version_id) != "published":
        return 0
    db.run(cur, """update crm_outbox set status = 'cancelled', last_error = 'Superseded by a newer profile version'
                   where kind = 'scores' and status = 'queued' and icp_version is distinct from %s""", version_id)
    items = score_items(cur, plan, version_id)
    for i in range(0, len(items), CHUNK):
        db.run(cur, "insert into crm_outbox (plan, kind, payload, icp_version) values (%s, 'scores', %s, %s)",
               plan, J({"items": items[i:i + CHUNK]}), version_id)
    if items:
        jobs.enqueue(cur, "crm_deliver", {}, dedupe_key="crm_deliver")
    return len(items)


def score_batches(cur) -> int:
    """How many requests publishing a profile version sends: the active plan's accounts, 100 to a request."""
    if not enabled():
        return 0
    plan = db.val(cur, "select id from territory_plans where status = 'active'")
    return 0 if plan is None else batch_count(cur, plan)


@jobs.handler("crm_scores")
def _scores_after_rescore(cur, payload: dict) -> None:
    """Publishing rescores in batches of its own, so the tiers do not exist yet when the manager clicks. This job waits
    for them (a check every 30 seconds) and then queues the send."""
    from datetime import timedelta
    vid = payload["version"]
    if db.val(cur, "select status from icp_versions where id = %s", vid) != "published":
        return
    if db.val(cur, "select count(*) from jobs where status in ('queued', 'running') and kind in ('rescore_version', 'rescore_batch') "
                   "and (payload->>'version')::int = %s", vid):
        jobs.enqueue(cur, "crm_scores", payload, delay=timedelta(seconds=30))
        return
    queue_scores(cur, vid)


def batch_count(cur, plan_id: int) -> int:
    """How many requests activating this plan sends to the CRM: 0 with no CRM set."""
    if not enabled():
        return 0
    n = db.val(cur, "select count(*) from assignments a join companies c on c.id = a.company where a.plan = %s and not c.sole_trader", plan_id)
    return -(-n // CHUNK)


def send_state(cur, plan_id: int) -> dict:
    """What a plan's books have done so far: requests already sent (these cannot be pulled back), still waiting, and refused."""
    rows = db.all(cur, "select status, count(*) as n, coalesce(sum(jsonb_array_length(payload->'items')), 0) as accounts "
                       "from crm_outbox where plan = %s group by status", plan_id)
    by = {r["status"]: r for r in rows}
    g = lambda k, f: int(by[k][f]) if k in by else 0  # noqa: E731
    return {"sent": g("sent", "n"), "sent_accounts": g("sent", "accounts"), "waiting": g("queued", "n"), "failed": g("failed", "n")}


def cancel_unsent(cur, plan_id: int) -> int:
    """Batches of this plan still waiting are cancelled. Batches already sent stay sent: the CRM keeps what it took."""
    return db.run(cur, "update crm_outbox set status = 'cancelled', last_error = 'Rolled back before it was sent' "
                       "where plan = %s and status = 'queued'", plan_id)


class CrmDown(Exception):
    """CRM Desk did not answer with a decision. `retry_after` is the seconds it asked to wait, when it said."""

    def __init__(self, msg: str, retry_after: float | None = None):
        super().__init__(msg)
        self.retry_after = retry_after


def _send(body: dict, key: str | None = None) -> tuple[int, dict]:
    import httpx
    url, api_key = os.environ.get("CRM_DESK_URL", ""), os.environ.get("CRM_DESK_KEY", "")
    if not (url and api_key):
        raise CrmDown("CRM=crmdesk needs CRM_DESK_URL and CRM_DESK_KEY (a key made with --desk market_desk).")
    try:
        r = httpx.post(url.rstrip("/") + "/api/v1/accounts/batch", json=body, timeout=30.0,
                       headers={"authorization": f"Bearer {api_key}", "content-type": "application/json",
                                 **({"idempotency-key": key} if key else {})})
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
    status, answer = _send(row["payload"], f"market-desk:outbox:{row['id']}")
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
            f.write(json.dumps({"at": at.isoformat(), "actor": "market_desk", "method": "POST", "path": "/accounts/batch", "kind": row["kind"],
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


def _latest(cur) -> dict[tuple[str, str], dict]:
    """Each account's latest answer from the CRM: its refusals and its error, from the last row that carried it."""
    latest: dict[tuple[str, str], dict] = {}
    for row in db.all(cur, "select kind, payload, answer, sent_at from crm_outbox where status = 'sent' order by sent_at, id"):
        items = row["payload"]["items"]
        for res in (row["answer"] or {}).get("results", []):
            it = items[res["index"]]
            latest[(it["domain"], row["kind"])] = {"item": it, "refused": res.get("refused") or [], "error": res.get("error"),
                                                  "at": row["sent_at"], "kind": row["kind"]}
    return latest


def refusals(cur) -> list[dict]:
    """The changes the CRM refused in each account's latest answer: an account accepted later is no longer listed."""
    out = []
    for (domain, _kind), r in _latest(cur).items():
        for f in r["refused"]:
            out.append({"domain": domain, "field": f["field"], "reason": f["reason"], "proposed": r["item"].get(f["field"]),
                        "at": r["at"]})
    return sorted(out, key=lambda r: (r["domain"], r["field"]))


def errors(cur) -> list[dict]:
    """Accounts the CRM could not take at all in their latest answer, with its reason."""
    return sorted(({"domain": d, "error": r["error"], "at": r["at"]} for (d, _k), r in _latest(cur).items() if r["error"]),
                  key=lambda r: r["domain"])


def icp_state(cur) -> dict:
    """Where the published profile version stands in the CRM, for Handoffs: how many accounts the CRM has answered for
    under it, how many are waiting, and what could not be sent."""
    v = db.one(cur, "select id, number from icp_versions where status = 'published'")
    if v is None:
        return {"published": None, "accounts_on_published": 0, "waiting": 0, "failed": 0, "no_active_plan": False}
    on = {d for (d, _k), r in _latest(cur).items() if r["item"].get("icp_version") == f"v{v['number']}" and not r["error"]}
    return {"published": v["number"], "accounts_on_published": len(on),
            "waiting": db.val(cur, "select coalesce(sum(jsonb_array_length(payload->'items')), 0) from crm_outbox "
                                   "where kind = 'scores' and status = 'queued' and icp_version = %s", v["id"]),
            "failed": db.val(cur, "select count(*) from crm_outbox where kind = 'scores' and status = 'failed' and icp_version = %s", v["id"]),
            "no_active_plan": db.val(cur, "select count(*) from territory_plans where status = 'active'") == 0}


def summary(cur) -> dict:
    latest = _latest(cur)
    return {"enabled": enabled(),
            "sent": len({d for d, _k in latest}),  # distinct accounts the CRM has answered for, however many times each was sent
            "queued": db.val(cur, "select coalesce(sum(jsonb_array_length(payload->'items')), 0) from crm_outbox where status = 'queued'"),
            "failed": db.all(cur, "select id, last_error, created_at from crm_outbox where status = 'failed' order by id"),
            "last_sent_at": max((r["at"] for r in latest.values()), default=None), "icp": icp_state(cur),
            "refusals": refusals(cur), "errors": errors(cur)}


def replay(cur, journal: Path) -> int:
    """The demo build: what Market Desk sent in the rehearsal and how CRM Desk answered, kept as sent rows, so the
    demo shows the same refusals CRM Desk's demo shows."""
    if not journal.exists():
        return 0
    n = 0
    for line in journal.read_text().splitlines():
        step = json.loads(line)
        if step["actor"] != "market_desk" or step.get("method", "POST") != "POST":
            continue  # a pull's reads (GET) are not part of the exchange this replays
        plan = db.val(cur, "select id from territory_plans where status = 'active'")
        db.run(cur, """insert into crm_outbox (plan, kind, payload, status, attempts, answer, sent_at, created_at)
                       values (%s, %s, %s, 'sent', 1, %s, %s, %s)""", plan, step.get("kind", "books"), J(step["body"]),
               J(step["answer"]), step["at"], step["at"])
        n += 1
    return n


# ---------------------------------------------------------------- the read side: CRM Desk as a CrmReader

class CrmDeskReader:
    """CRM Desk's change feeds, in the nouns of `deals_in.CrmReader` (Salesforce's Opportunity and Account). Names,
    contacts and roles stay behind this boundary. Every call fails closed: a timeout, a refusal or a 5xx raises
    `CrmDown` and the pull resumes from its saved cursor."""

    def __init__(self, url: str, key: str, client=None):
        import httpx
        self.c = client or httpx.Client(base_url=url.rstrip("/"), timeout=30.0, headers={"authorization": f"Bearer {key}"})

    @classmethod
    def from_env(cls) -> "CrmDeskReader":
        url, key = os.environ.get("CRM_DESK_URL", ""), os.environ.get("CRM_DESK_KEY", "")
        if not (url and key):
            raise CrmDown("CRM=crmdesk needs CRM_DESK_URL and CRM_DESK_KEY (a key made with --desk market_desk).")
        return cls(url, key)

    def _get(self, path: str, since: str | None, limit: int) -> dict:
        import httpx
        try:
            r = self.c.get("/api/v1" + path, params={"limit": limit, **({"since": since} if since else {})})
        except httpx.HTTPError as exc:
            raise CrmDown(f"CRM Desk did not answer: {type(exc).__name__}") from exc
        if r.status_code == 429:
            raise CrmDown("CRM Desk asked to slow down", float(r.headers.get("retry-after") or 30))
        if r.status_code >= 400:
            raise CrmDown(f"CRM Desk answered {r.status_code} on {path}")
        return r.json()

    @staticmethod
    def _when(v):
        from datetime import datetime
        return None if not v else datetime.fromisoformat(v.replace("Z", "+00:00"))

    def opportunities_changed(self, since, limit):
        from .deals_in import CrmOpportunity, Page
        j = self._get("/changes/opportunities", since, limit)
        out = []
        for r in j["data"]:
            if r.get("deleted") or r.get("merged_into") or not r.get("account_domain") or not r.get("created_at"):
                continue
            snap = r.get("account_snapshot") or None
            out.append(CrmOpportunity(
                id=f"crmdesk:{r['id']}", account_domain=r["account_domain"], account_name=r.get("account_name") or r["account_domain"],
                stage_name=r["stage"], amount_cents=r.get("amount_cents"), currency=r.get("currency"), created_at=self._when(r["created_at"]),
                is_closed=bool(r["is_closed"]), is_won=bool(r["is_won"]), close_date=self._when(r.get("closed_at")),
                type={"new_business": "new business", "existing_business": "existing business", "renewal": "renewal"}.get(r.get("type") or ""),
                lead_source=r.get("lead_source"), owner_email=(r.get("owner") or {}).get("email"), loss_reason=r.get("loss_reason"),
                competitor=r.get("competitor"), account_snapshot=snap, country=(snap or {}).get("country"),
                updated_at=self._when(r.get("updated_at"))))
        return Page(out, j.get("next"), bool(j.get("has_more")))

    def accounts_changed(self, since, limit):
        from .deals_in import CrmAccount, Page
        j = self._get("/changes/accounts", since, limit)
        out = [CrmAccount(id=str(r["id"]), domain=r["domain"], name=r["name"], country=r.get("country"),
                          owner_email=(r.get("owner") or {}).get("email"), sdr_owner_email=(r.get("sdr_owner") or {}).get("email"),
                          updated_at=self._when(r.get("updated_at")))
               for r in j["data"] if not (r.get("deleted") or r.get("merged_into")) and r.get("domain")]
        return Page(out, j.get("next"), bool(j.get("has_more")))


def pull_enabled() -> bool:
    """Reading the CRM's deals back is a second switch: `CRM=crmdesk` alone only writes."""
    return enabled() and os.environ.get("CRM_PULL", "").strip().lower() in ("1", "true", "yes", "on")


@jobs.handler("crm_pull")
def _pull(cur, payload: dict) -> None:
    from datetime import timedelta

    from . import deals_in
    if not pull_enabled():
        return
    wait = timedelta(minutes=15)
    try:
        deals_in.pull(CrmDeskReader.from_env())   # its own transactions, one per page
    except CrmDown as exc:                        # the pull resumes from its cursor; never let an outage end the schedule
        wait = timedelta(seconds=exc.retry_after or 120)
        log.warning("crm pull stopped: %s", exc)
    jobs.enqueue(cur, "crm_pull", {}, delay=wait, dedupe_key="crm_pull")
