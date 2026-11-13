"""Deals in: the history Market Desk reads for evidence, win rates and capacity, when it is not the demo's own.

Two feeders, one writer. A deals CSV (`python -m market import-deals FILE`) is the standalone path: no CRM is needed.
A CRM that speaks Salesforce's nouns (`CrmReader`) is the connected path: `CRM=crmdesk` with `CRM_PULL=1` reads
CRM Desk's opportunity feed. Both produce the same normalised row and call `upsert`, so a deal is stored once, keyed
by `(source_system, external_id)`, and a later import or pull of the same opportunity updates it rather than adding a
second one.

Rules this file keeps (decision 47):
- Nothing is invented. A trait the file does not give is absent from the deal's snapshot, which evidence already
  reads as unknown. A lead source or loss reason we cannot map is stored as unknown, never guessed.
- The snapshot is the company as the row says it was, never today's company, so an old deal is not given a
  size the company only reached later. `snapshot_source` says where each snapshot came from.
- No people. Free text goes through `privacy.redact`; a row's owner is a user's email, never a contact.
- All valid rows land in one transaction; a rejected row is listed by number and reason, without echoing its values.
"""
from __future__ import annotations

import contextlib
import csv
import hashlib
import io
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from . import audit, db, privacy
from . import catalog as C
from .db import J

MAX_BYTES = 5 * 1024 * 1024
MAX_ROWS = 50_000
SYSTEMS = ("csv", "salesforce", "hubspot", "crmdesk")
_DOMAIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

NEW_TYPES = {"new", "new business", "new_business", "newbusiness"}
EXPANSION_TYPES = {"existing business", "existing_business", "expansion", "upsell", "cross sell", "cross-sell", "add on", "add-on"}
RENEWAL_TYPES = {"renewal", "renewals"}
SOURCES = {"outbound": "outbound", "inbound": "inbound", "event": "event", "events": "event", "trade show": "event",
           "conference": "event", "partner": "partner", "partner referral": "partner", "referral partner": "partner",
           "web": "inbound", "website": "inbound", "web form": "inbound", "phone inquiry": "inbound",
           "sdr generated": "outbound", "outbound sdr": "outbound", "cold outreach": "outbound"}
LOSS_WORDS = [  # first match wins; an exact code always maps to itself
    ("price", ("price", "pricing", "cost", "expensive", "discount")),
    ("no_decision", ("no decision", "no_decision", "stalled", "went dark", "no response", "no budget")),
    ("timing", ("timing", "not now", "postponed", "next year", "next quarter", "deferred")),
    ("competitor", ("competitor", "lost to", "went with")),
    ("missing_feature", ("feature", "missing", "capability", "integration")),
    ("compliance", ("compliance", "security", "legal", "gdpr", "audit")),
    ("champion_left", ("champion", "left the company", "left company", "sponsor left")),
    ("bad_fit", ("bad fit", "not a fit", "poor fit", "wrong fit", "disqualified")),
]


@dataclass
class Row:
    """One opportunity, whichever feeder it came from. Money is in cents of the install's currency."""
    external_id: str
    account_domain: str
    account_name: str
    created_at: datetime
    stage: str
    is_closed: bool
    is_won: bool
    amount_cents: int
    type: str | None
    closed_at: datetime | None = None
    country: str | None = None
    lead_source: str | None = None
    loss_reason: str | None = None
    competitor: str | None = None
    owner_email: str | None = None
    traits: dict = field(default_factory=dict)        # industry, employees, revenue_band, pricing_model, tech, hq_city, founded_year
    snapshot: dict | None = None                       # a CRM's own snapshot of the account when the opportunity was made
    index: int = 0                                     # the row's line in the file, for the report
    feeder: str = "csv"                                # "csv" (a file, whatever CRM it was exported from) or "crm" (a pull)
    currency: str | None = None


def loss_code(text: str | None) -> tuple[str | None, str]:
    """(code, how). A reason that is not one of ours and matches no word is unknown, never 'other' by default."""
    t = (text or "").strip().lower()
    if not t:
        return None, "none"
    if t.replace(" ", "_") in C.LOSS_CODES:
        return t.replace(" ", "_"), "import_map"
    for code, words in LOSS_WORDS:
        if any(w in t for w in words):
            return code, "import_map"
    return None, "unmapped"


def _clean(v: str | None, n: int = 200) -> str | None:
    v = (v or "").strip()
    if not v:
        return None
    if _CONTROL.search(v):
        raise ValueError("a control character")
    if len(v) > n:
        raise ValueError(f"longer than {n} characters")
    return v


def domain_of(v: str | None) -> str | None:
    v = (v or "").strip().lower()
    v = re.sub(r"^[a-z]+://", "", v)
    v = re.sub(r"^www\.", "", v).split("/")[0].split("?")[0]
    return v if _DOMAIN.match(v) else None


def _when(v: str | None, what: str) -> datetime | None:
    v = (v or "").strip()
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{what} is not a date (use YYYY-MM-DD)") from None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _flag(v: str | None) -> bool | None:
    v = (v or "").strip().lower()
    return True if v in ("1", "true", "yes", "y") else False if v in ("0", "false", "no", "n") else None


ALIASES = {
    "external_id": ("opportunity_id", "id", "opportunity id", "opportunityid", "external_id"),
    "account_domain": ("account_domain", "domain", "website", "account.website", "account_website"),
    "account_name": ("account_name", "account.name", "account", "company"),
    "created": ("created_date", "createddate", "created_at", "created", "opportunity_created_date"),
    "closed": ("close_date", "closedate", "closed_at", "closed"),
    "stage": ("stage", "stagename", "stage_name"),
    "is_closed": ("is_closed", "isclosed"),
    "is_won": ("is_won", "iswon"),
    "amount": ("amount", "amount_usd"),
    "type": ("type", "opportunity_type"),
    "lead_source": ("lead_source", "leadsource"),
    "loss_reason": ("loss_reason", "closed_lost_reason", "loss_reason__c", "reason_lost"),
    "competitor": ("competitor", "competitor__c"),
    "owner_email": ("owner_email", "owner.email", "owner"),
    "country": ("country", "account.billingcountry", "billing_country"),
    "currency": ("currency", "currencyisocode"),
    "industry": ("industry", "account.industry"),
    "employees": ("employees", "numberofemployees", "account.numberofemployees"),
    "revenue_band": ("revenue_band",),
    "pricing_model": ("pricing_model",),
    "tech": ("tech", "technologies"),
    "hq_city": ("hq_city", "city", "account.billingcity"),
    "founded_year": ("founded_year", "year_founded"),
}
REQUIRED = ("external_id", "account_domain", "account_name", "created", "stage", "is_closed", "is_won", "amount", "type")


def read_csv(text: str, *, blank_type: str | None = None) -> tuple[list[Row], list[dict], dict]:
    """(rows, rejected, info). A rejected entry is {row, reason}; info names the columns it used and the ones it ignored."""
    rdr = csv.DictReader(io.StringIO(text))
    heads = {(h or "").strip().lower(): h for h in (rdr.fieldnames or [])}
    col = {k: next((heads[a] for a in al if a in heads), None) for k, al in ALIASES.items()}
    missing = [k for k in REQUIRED if col[k] is None]
    if missing:
        raise ValueError("The file has no column for: " + ", ".join(missing) + ". See the README for the column names.")
    used = {v for v in col.values() if v}
    info = {"ignored_columns": sorted(h for h in (rdr.fieldnames or []) if h not in used)}
    rows, rejected, seen = [], [], set()
    for i, raw in enumerate(rdr, start=2):  # line 1 is the header
        g = lambda k, raw=raw: raw.get(col[k]) if col[k] else None  # noqa: E731
        try:
            ext = _clean(g("external_id"), 120)
            if not ext:
                raise ValueError("no opportunity id")
            if ext in seen:
                raise ValueError("the opportunity id appears twice in the file")
            seen.add(ext)
            dom = domain_of(g("account_domain"))
            if not dom:
                raise ValueError("the account domain is not a domain")
            name = _clean(g("account_name"))
            if not name:
                raise ValueError("no account name")
            created = _when(g("created"), "the created date")
            if created is None:
                raise ValueError("no created date")
            closed_flag, won_flag = _flag(g("is_closed")), _flag(g("is_won"))
            if closed_flag is None or won_flag is None:
                raise ValueError("is_closed and is_won must be true or false")
            if won_flag and not closed_flag:
                raise ValueError("a won deal must be closed")
            closed = _when(g("closed"), "the close date")
            if closed_flag and closed is None:
                raise ValueError("a closed deal needs a close date")
            cur_ = (g("currency") or "").strip().upper()
            if cur_ and cur_ != "USD":
                raise ValueError("the currency is not USD (convert it first)")
            amt = (g("amount") or "").replace(",", "").replace("$", "").strip()
            try:
                cents = round(float(amt) * 100)
            except ValueError:
                raise ValueError("the amount is not a number") from None
            if cents < 0:
                raise ValueError("the amount is negative")
            typ = (g("type") or "").strip().lower() or blank_type
            if typ is None:
                raise ValueError("no type (new business or existing business); pass --blank-type new if blank means new")
            traits: dict = {}
            for k in ("industry", "revenue_band", "pricing_model", "hq_city"):
                if (v := _clean(g(k))):
                    traits[k] = v
            if (v := (g("employees") or "").replace(",", "").strip()):
                if not v.isdigit():
                    raise ValueError("employees is not a whole number")
                traits["employees"] = int(v)
            if (v := (g("founded_year") or "").strip()):
                if not (v.isdigit() and 1800 <= int(v) <= 2100):
                    raise ValueError("founded_year is not a year")
                traits["founded_year"] = int(v)
            if (v := _clean(g("tech"), 400)):
                traits["tech"] = [t.strip() for t in v.split(";") if t.strip()]
            r = Row(external_id=ext, account_domain=dom, account_name=name, created_at=created, stage=_clean(g("stage"), 80) or "",
                    is_closed=closed_flag, is_won=won_flag, amount_cents=cents, type=typ, closed_at=closed if closed_flag else None,
                    country=(_clean(g("country"), 40) or "").upper() or None, lead_source=_clean(g("lead_source"), 80),
                    loss_reason=_clean(g("loss_reason"), 500), competitor=_clean(g("competitor"), 80),
                    owner_email=(_clean(g("owner_email"), 200) or "").lower() or None, traits=traits, index=i)
            rows.append(r)
        except ValueError as exc:
            rejected.append({"row": i, "reason": str(exc)})
    if len(rows) + len(rejected) > MAX_ROWS:
        raise ValueError(f"Over {MAX_ROWS:,} rows. Split the file.")
    return rows, rejected, info


# ---------------------------------------------------------------- the writer

def _region(country: str | None) -> tuple[str, str]:
    for region, (group, countries) in C.REGION_GROUPS.items():
        if country in countries:
            return region, group
    return "Other", "Other"


def _kind(typ: str | None) -> str | None:
    t = (typ or "").strip().lower()
    return "new" if t in NEW_TYPES else "expansion" if t in EXPANSION_TYPES else None


def _company(cur, r: Row, origin: str) -> tuple[int | None, str | None]:
    """The company id for a row, made from the row when this desk does not hold it. Never from a guess: a new company
    needs a country."""
    cid = db.val(cur, "select id from companies where primary_domain = %s", r.account_domain)
    if cid is not None:
        return cid, None
    if not r.country or len(r.country) != 2:
        return None, "a company this desk does not hold needs its country (two letters)"
    region, group = _region(r.country)
    t = r.traits
    cid = db.val(cur, """insert into companies (name, primary_domain, country, region, region_group, hq_city, founded_year, industry,
                                               employees, revenue_band, pricing_model, origin)
                         values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                 r.account_name, r.account_domain, r.country, region, group, t.get("hq_city"), t.get("founded_year"), t.get("industry"),
                 t.get("employees"), t.get("revenue_band"), t.get("pricing_model") if t.get("pricing_model") in
                 ("usage", "seat", "transaction", "mixed", "unknown") else None, origin)
    return cid, None


def _snapshot(cur, r: Row, company: int, now: datetime) -> tuple[dict, str]:
    c = db.one(cur, "select country, region, region_group, founded_year, industry, employees, revenue_band, pricing_model, tech, hq_city "
                    "from companies where id = %s", company)
    stable = {k: c[k] for k in ("country", "region", "region_group") if c[k]}
    if r.feeder == "csv":
        snap = {**stable, **{k: v for k, v in r.traits.items() if v is not None}}
        return snap, "csv_row"
    if r.snapshot:
        keep = ("industry", "employees", "revenue_band", "pricing_model", "tech", "hq_city", "founded_year", "country", "region", "region_group")
        return {**stable, **{k: v for k, v in r.snapshot.items() if k in keep and v not in (None, "", [])}}, "crm_snapshot"
    if r.created_at >= now - timedelta(days=7):  # a deal opened this week: the company today is the company then
        return {k: v for k, v in c.items() if v not in (None, "", [])}, "crm_first_seen"
    return {**stable, **({"founded_year": c["founded_year"]} if c["founded_year"] else {})}, "crm_backfill"


def upsert(cur, rows: list[Row], system: str, *, actor: str, by: int | None = None, blank_type: str | None = None,
           file_sha: str | None = None, rejected: list[dict] | None = None, info: dict | None = None) -> dict:
    """Writes the rows. Returns the report. The caller holds the transaction: a failure rolls every row back."""
    if system not in SYSTEMS:
        raise ValueError(f"system must be one of {', '.join(SYSTEMS)}")
    now = db.val(cur, "select app_now()")
    users = {u["email"].lower(): u["id"] for u in db.all(cur, "select id, email from users")}
    inserted = updated = no_owner = renewals = unmapped = 0
    rejected = list(rejected or [])
    for r in rows:
        origin = "crm" if r.feeder == "crm" else "deals_import"
        dom = domain_of(r.account_domain)
        if dom is None:
            rejected.append({"row": r.index, "reason": "the account domain is not a domain"})
            continue
        r.account_domain = dom
        if r.amount_cents is None or r.amount_cents < 0:
            rejected.append({"row": r.index, "reason": "the amount is missing or negative"})
            continue
        if (r.currency or "USD").upper() != "USD":
            rejected.append({"row": r.index, "reason": "the currency is not USD (convert it first)"})
            continue
        if r.is_closed and r.closed_at is None:
            rejected.append({"row": r.index, "reason": "a closed deal needs a close date"})
            continue
        kind = _kind(r.type)
        if kind is None:
            if (r.type or "").strip().lower() in RENEWAL_TYPES:
                renewals += 1
            else:
                rejected.append({"row": r.index, "reason": "the type is not new business, existing business or a renewal"})
            continue
        if r.closed_at is not None and r.closed_at < r.created_at:
            rejected.append({"row": r.index, "reason": "the close date is before the created date"})
            continue
        if r.created_at > now or (r.closed_at is not None and r.closed_at > now):
            rejected.append({"row": r.index, "reason": "a date is after today"})
            continue
        cid, why = _company(cur, r, origin)
        if cid is None:
            rejected.append({"row": r.index, "reason": why})
            continue
        outcome = ("won" if r.is_won else "lost") if r.is_closed else "open"
        src = SOURCES.get((r.lead_source or "").strip().lower())
        owner = users.get((r.owner_email or "").lower())
        if r.owner_email and owner is None:
            no_owner += 1
        code, how = loss_code(r.loss_reason) if outcome == "lost" else (None, "none")
        unmapped += how == "unmapped"
        text = privacy.redact(r.loss_reason, []) if outcome == "lost" and r.loss_reason else None
        comp = r.competitor if r.competitor in C.COMPETITORS and outcome == "lost" else None
        existing = db.one(cur, "select id from deals where source_system = %s and external_id = %s", system, r.external_id)
        if existing:
            db.run(cur, """update deals set stage = %s, outcome = %s, amount_cents = %s, closed_at = %s, loss_reason_text = %s,
                           loss_code = %s, loss_code_source = %s, competitor = %s, owner = coalesce(%s, owner) where id = %s""",
                   r.stage or ("Closed won" if r.is_won else "Closed lost" if r.is_closed else "Open"), outcome, r.amount_cents,
                   r.closed_at, text, code, how if how != "none" else None, comp, owner, existing["id"])
            updated += 1
        else:
            snap, snap_src = _snapshot(cur, r, cid, now)
            db.run(cur, """insert into deals (company, kind, created_at, closed_at, stage, outcome, amount_cents, loss_reason_text, loss_code,
                                              loss_code_source, competitor, source, owner, snapshot, external_id, source_system, snapshot_source)
                           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                   cid, kind, r.created_at, r.closed_at, r.stage or ("Closed won" if r.is_won else "Closed lost" if r.is_closed else "Open"),
                   outcome, r.amount_cents, text, code, how if how != "none" else None, comp, src, owner, J(snap), r.external_id, system, snap_src)
            inserted += 1
        if kind == "new" and outcome == "won":
            db.run(cur, "insert into customers (company, started_on, arr_cents, origin) values (%s,%s,%s,%s) on conflict (company) do nothing",
                   cid, r.closed_at.date(), r.amount_cents, origin)
            db.run(cur, "update companies set lifecycle = 'customer' where id = %s and lifecycle in ('prospect', 'open_opp')", cid)
        elif outcome == "open":
            db.run(cur, "update companies set lifecycle = 'open_opp' where id = %s and lifecycle = 'prospect'", cid)
    report = {"total": inserted + updated + renewals + len(rejected), "inserted": inserted, "updated": updated,
              "rejected": rejected, "renewals_skipped": renewals, "owner_not_found": no_owner,
              "loss_reason_unmapped": unmapped, **(info or {})}
    iid = db.val(cur, """insert into deal_imports (by_user, actor, system, file_sha256, total, inserted, updated, rejected, report)
                         values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                 by, actor, system, file_sha, report["total"], inserted, updated, len(rejected), J(report))
    audit.log(cur, actor, "deals_imported", "deal_import", iid, {"system": system, "inserted": inserted, "updated": updated,
                                                                "rejected": len(rejected)}, actor_id=by)
    report["import_id"] = iid
    return report


class _DryRun(Exception):
    """Raised to roll a dry run back."""


def import_file(path: str, system: str = "csv", *, commit: bool = False, blank_type: str | None = None, actor: str = "cli") -> dict:
    """The CLI path. A dry run (the default) reads and checks every row inside a transaction it rolls back."""
    from .config import CONFIG
    if CONFIG.public_demo:
        raise SystemExit("The public demo holds invented data only. It takes no deals file.")
    if "crm_desk" in CONFIG.integrated_with:
        raise SystemExit("INTEGRATED_WITH names crm_desk: the deal history comes from CRM Desk, so this desk does not import its own. "
                         "Remove crm_desk from INTEGRATED_WITH to import a file.")
    p = Path(path)
    if p.stat().st_size > MAX_BYTES:
        raise SystemExit("Over 5 MB. Split the file.")
    raw = p.read_bytes()
    try:
        rows, rejected, info = read_csv(raw.decode("utf-8-sig"), blank_type=blank_type)
    except (ValueError, UnicodeDecodeError, csv.Error) as exc:
        raise SystemExit(str(exc)) from None
    sha = hashlib.sha256(raw).hexdigest()
    try:
        with db.tx() as cur:
            report = upsert(cur, rows, system, actor=actor, blank_type=blank_type, file_sha=sha, rejected=rejected, info=info)
            if not commit:
                raise _DryRun
    except _DryRun:
        pass
    report["committed"] = commit
    return report


# ---------------------------------------------------------------- the CRM read side, in Salesforce's nouns

@dataclass
class Page:
    rows: list
    next: str | None
    has_more: bool


@dataclass
class CrmOpportunity:
    """An Opportunity as Salesforce names it (HubSpot: a deal). The CRM Desk adapter drops names, contacts and roles
    at this boundary: Market Desk stores no people."""
    id: str
    account_domain: str
    account_name: str
    stage_name: str
    amount_cents: int | None
    created_at: datetime
    is_closed: bool
    is_won: bool
    close_date: datetime | None = None
    type: str | None = None
    lead_source: str | None = None
    owner_email: str | None = None
    loss_reason: str | None = None
    competitor: str | None = None
    account_snapshot: dict | None = None
    country: str | None = None
    updated_at: datetime | None = None
    currency: str | None = None


@dataclass
class CrmAccount:
    """An Account with its owners: the AE (Salesforce OwnerId) and the SDR (a custom field)."""
    id: str
    domain: str
    name: str
    country: str | None = None
    owner_email: str | None = None
    sdr_owner_email: str | None = None
    updated_at: datetime | None = None


class CrmReader(Protocol):
    """What Market Desk reads back from a CRM. A Salesforce adapter implements the same two methods with SOQL
    (Opportunity and Account, ordered by SystemModstamp); a stub with only these runs the whole pull."""
    def opportunities_changed(self, since: str | None, limit: int) -> Page: ...
    def accounts_changed(self, since: str | None, limit: int) -> Page: ...


def opportunity_row(o: CrmOpportunity, index: int = 0) -> Row:
    return Row(external_id=o.id, account_domain=o.account_domain, account_name=o.account_name, created_at=o.created_at,
               stage=o.stage_name, is_closed=o.is_closed, is_won=o.is_won, amount_cents=o.amount_cents, type=o.type,
               closed_at=o.close_date if o.is_closed else None, country=o.country, lead_source=o.lead_source,
               loss_reason=o.loss_reason, competitor=o.competitor, owner_email=o.owner_email, snapshot=o.account_snapshot, index=index,
               feeder="crm", currency=o.currency)


def _journal(method: str, path: str, since: str | None, page: Page, at) -> None:
    j = os.environ.get("CRM_JOURNAL")
    if j:
        with open(j, "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": at.isoformat(), "actor": "market_desk", "method": method, "path": path, "since": since,
                                "count": len(page.rows), "next": page.next}, sort_keys=True) + "\n")


def _cursor(cur, feed: str) -> str | None:
    return db.val(cur, "select since from crm_cursors where feed = %s", feed)


def _save_cursor(cur, feed: str, since: str | None) -> None:
    db.run(cur, "insert into crm_cursors (feed, since) values (%s, %s) on conflict (feed) do update set since = excluded.since, updated_at = app_now()",
           feed, since)


@contextlib.contextmanager
def _scope(cur):
    """A caller's own cursor (a test, inside its transaction), or a transaction of this page's own."""
    if cur is not None:
        yield cur
    else:
        with db.tx() as c:
            yield c


def pull(reader: CrmReader, *, system: str = "crmdesk", limit: int = 200, max_pages: int = 500, cur=None) -> dict:
    """Reads the CRM's accounts, then its opportunities, a page at a time, each page in its own transaction with its
    cursor, so a CRM that goes away mid-pull leaves what was read and resumes where it stopped. Accounts come first so
    a deal's company is known; a company the desk does not hold is made from the account, never from a guess."""
    out = {"accounts": 0, "opportunities": 0, "inserted": 0, "updated": 0, "rejected": 0}
    for _ in range(max_pages):
        with _scope(cur) as c:
            since = _cursor(c, "accounts")
            page = reader.accounts_changed(since, limit)
            for a in page.rows:
                if a.country and len(a.country) == 2 and not db.val(c, "select 1 from companies where primary_domain = %s", a.domain):
                    region, group = _region(a.country.upper())
                    db.run(c, "insert into companies (name, primary_domain, country, region, region_group, origin) values (%s,%s,%s,%s,%s,'crm')",
                           a.name, a.domain, a.country.upper(), region, group)
            out["accounts"] += len(page.rows)
            _journal("GET", "/changes/accounts", since, page, db.val(c, "select app_now()"))
            _save_cursor(c, "accounts", page.next or since)
        if not page.has_more:
            break
    for _ in range(max_pages):
        with _scope(cur) as c:
            since = _cursor(c, "opportunities")
            page = reader.opportunities_changed(since, limit)
            rows = [opportunity_row(o, i) for i, o in enumerate(page.rows)]
            if rows:
                rep = upsert(c, rows, system, actor="crm_pull")
                out["inserted"] += rep["inserted"]
                out["updated"] += rep["updated"]
                out["rejected"] += len(rep["rejected"])
            out["opportunities"] += len(page.rows)
            _journal("GET", "/changes/opportunities", since, page, db.val(c, "select app_now()"))
            _save_cursor(c, "opportunities", page.next or since)
        if not page.has_more:
            break
    return out
