"""The market on the shared world (shared-world DESIGN.md, Phase 2): Market Desk's universe, history and team read from
the slice of `lumen-world` vendored in `world/`, instead of drawn by `sim/world.py` (kept as the rollback with
WORLD=legacy).

The companies are the same ones `sim/world.py` draws (lumen-world reproduces its draws; 27 carrying the seller's name
are renamed). What changes: the team is the one roster (Jonas Weber, Leah Ahn and Lukas Brandt join), the history is
the world's (moved into working hours, cut at 13 August 2026, then played to now as the world plans it), deals carry
the US dollar amount at their close, and call notes arrive with the names they mention and are redacted here before
anything is stored (decision 1). Market Desk still stores no people: the slice holds none, only counts of findable
roles per company.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from .. import catalog as C
from .. import db
from ..db import J
from ..privacy import redact
from . import world as legacy

ROOT = Path(__file__).resolve().parents[3]
WORLD = ROOT / "world"
ROLE = {"revops": "revops", "manager": "manager"}


def read(name: str) -> list[dict]:
    with (WORLD / name).open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def clock() -> dict:
    return json.loads((WORLD / "public/clock.json").read_text())


NOW = datetime.fromisoformat(clock()["now"]) if (WORLD / "public/clock.json").exists() else legacy.NOW
HISTORY_START = datetime.fromisoformat(clock()["history_start"]) if (WORLD / "public/clock.json").exists() else legacy.HISTORY_START


def build(cur) -> dict:
    db.run(cur, "set local timezone = 'UTC'")
    db.run(cur, "update sim_clock set enabled = true, at = %s", NOW)

    # ---------------------------------------------------------------- the team: the one roster
    users: dict[str, int] = {}
    for t in read("public/team.csv"):
        role = ROLE.get(t["market_desk_role"]) or ({"SDR": "sdr", "AE": "ae"}.get(t["team"]) if t["market_desk_role"] == "plan" else None)
        if not role:
            continue
        users[t["email"]] = db.val(cur, """insert into users (name, email, role, timezone, started_on, selling_hours_month, created_at)
            values (%s,%s,%s,%s,%s,%s,least(%s::date, '2026-10-15'::date)) returning id""",
            t["name"], t["email"], role, t["timezone"], t["started_on"], int(t["selling_hours_month"]), t["started_on"])
    for k, (v, note) in C.SETTINGS.items():
        db.run(cur, "insert into settings (key, value, note) values (%s,%s,%s)", k, J(v), note)
    _sources(cur)

    # ---------------------------------------------------------------- companies, as a company-data vendor shows them
    comps = read("truth/companies.csv")
    data = {d["world_id"]: d for d in read("truth/company_data.csv")}
    with cur.copy("""copy companies (name, primary_domain, country, region, region_group, hq_city, founded_year, industry,
                     employees, revenue_band, pricing_model, tech, description, lifecycle, sole_trader, crm_id, created_at)
                     from stdin""") as cp:
        for c in comps:
            d = data.get(c["world_id"], {})
            competitor = c["kind"] == "competitor"
            cp.write_row((c["name"], c["domain"], c["country"], c["region"], c["region_group"], c["hq_city"] or None,
                          int(c["founded_year"]) if c["founded_year"] else None,
                          c["industry"] if competitor else (d.get("industry") or None),
                          int(d["employees"]) if d.get("employees") else int(c["employees"]),
                          (d.get("revenue_band") or None) if not competitor else c["revenue_band"],
                          c["pricing_model"], [t for t in c["tech"].split(";") if t], d.get("description") or
                          f"{c['name']} sells billing software.", "competitor" if competitor else "prospect",
                          c["sole_trader"] == "true", None, HISTORY_START))
    cid = {r["primary_domain"]: r["id"] for r in db.all(cur, "select id, primary_domain from companies")}
    by_wid = {c["world_id"]: cid[c["domain"]] for c in comps}
    obs = NOW - timedelta(days=9)
    with cur.copy("copy field_values (company, field, value, source, observed_at, confidence) from stdin") as cp:
        for c in comps:
            if c["kind"] != "company":
                continue
            d, co = data[c["world_id"]], by_wid[c["world_id"]]
            if d["industry"]:
                cp.write_row((co, "industry", J(d["industry"]), "firmographics", obs, 0.95))
            cp.write_row((co, "employees", J(int(d["employees"])), "firmographics", obs, 0.9))
            if d["revenue_band"]:
                cp.write_row((co, "revenue_band", J(d["revenue_band"]), d["revenue_source"] or "firmographics", obs, 0.8))
            if d["pricing_model"]:
                cp.write_row((co, "pricing_model", J(d["pricing_model"]), "firmographics", obs, 0.85))
            cp.write_row((co, "tech", J([t for t in d["tech"].split(";") if t]), "technographics", NOW - timedelta(days=4), 0.8))

    # ---------------------------------------------------------------- deals, as the CRM holds them now
    now = NOW.isoformat()
    deal_id: dict[str, int] = {}
    deals = sorted((d for d in read("truth/deals.csv") if d["created_at"] < now), key=lambda d: (d["created_at"], d["deal_id"]))
    for d in deals:
        closed = d["planned_close_at"] and d["planned_close_at"] < now
        outcome = d["planned_outcome"] if closed else "open"
        stage = {"won": "Closed won", "lost": "Closed lost"}.get(outcome) or (d["stage_at_cut"] or "Discovery")
        deal_id[d["deal_id"]] = db.val(cur, """insert into deals (company, kind, created_at, closed_at, stage, outcome, amount_cents,
                                           loss_reason_text, competitor, source, owner, snapshot)
                                           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                                       by_wid[d["company_world_id"]], d["kind"], d["created_at"], d["planned_close_at"] if closed else None,
                                       stage, outcome, int(d["amount_usd_cents"]),
                                       redact(d["loss_text"], []) if outcome == "lost" and d["loss_text"] else None,
                                       (d["competitor"] or None) if outcome == "lost" else None, d["source"],
                                       users.get(d["owner_email"]), J(json.loads(d["snapshot"])))
    for r in read("truth/deal_roles.csv"):
        if r["deal_id"] in deal_id:
            db.run(cur, "insert into deal_roles (deal, persona, seniority, was_signer, was_champion) values (%s,%s,%s,%s,%s)",
                   deal_id[r["deal_id"]], r["persona"], r["seniority"], r["is_signer"] == "true", r["is_champion"] == "true")

    # ---------------------------------------------------------------- customers, by the dates they bought and left
    customers = 0
    for cu in read("truth/customers.csv"):
        if cu["started_on"] >= now[:10]:
            continue
        churned = cu["churned_on"] if cu["churned_on"] and cu["churned_on"] < now[:10] else None
        co = by_wid[cu["company_world_id"]]
        db.run(cur, """insert into customers (company, started_on, churned_on, churn_reason_text, arr_cents)
                       values (%s,%s,%s,%s,%s)""", co, cu["started_on"], churned,
               redact(cu["churn_text"], []) if churned and cu["churn_text"] else None, int(cu["arr_usd_cents"]))
        db.run(cur, "update companies set lifecycle = %s, owner_id = %s, crm_id = %s where id = %s",
               "churned" if churned else "customer", users.get(cu["owner_email"]), f"CRM-{co:06d}", co)
        customers += 1
    for d in deals:
        co = by_wid[d["company_world_id"]]
        closed = d["planned_close_at"] and d["planned_close_at"] < now
        if not closed:
            db.run(cur, "update companies set lifecycle = 'open_opp', owner_id = %s, crm_id = coalesce(crm_id, %s) where id = %s and lifecycle = 'prospect'",
                   users.get(d["owner_email"]), f"CRM-{co:06d}", co)
        else:
            db.run(cur, "update companies set crm_id = coalesce(crm_id, %s) where id = %s", f"CRM-{co:06d}", co)

    # ---------------------------------------------------------------- call notes, redacted before they are stored
    notes = 0
    for n in read("truth/call_notes.csv"):
        if n["deal_id"] not in deal_id or n["written_at"] >= now:
            continue
        names = [x for x in n["redact"].split(";") if x]
        people = [(x, "contact") for x in names if "@" not in x]
        db.run(cur, "insert into call_notes (deal, written_at, author, text_redacted) values (%s,%s,%s,%s)",
               deal_id[n["deal_id"]], n["written_at"], users.get(n["author_email"]), redact(n["text"], people))
        notes += 1

    # ---------------------------------------------------------------- coverage (P6) and public counts
    with cur.copy("copy reachability (company, persona, has_named_contact_source, email_fill_rate, observed_at) from stdin") as cp:
        for r in read("truth/coverage.csv"):
            if r["persona"] not in ("cfo", "ceo", "controller", "revops", "data"):
                continue
            found = r["findable"] == "true"
            cp.write_row((by_wid[r["world_id"]], r["persona"], found, 0.8 if found else 0.0, NOW - timedelta(days=5)))
    with cur.copy("copy public_counts (source, country, industry, size_band, year, companies) from stdin") as cp:
        for r in read("public/public_counts.csv"):
            cp.write_row(("public_counts", r["country"], r["industry"], r["size_band"], int(r["year"]), int(r["companies"])))
    return {"companies": len(comps), "deals": len(deal_id), "customers": customers, "call_notes": notes}


def _sources(cur) -> None:
    """The same sources and run history as the legacy build, without its random run sizes."""
    sources = [
        ("crm", "CRM", "crm", "sim", False, None, None, "Your own CRM.", False, 6),
        ("firmographics", "Company data vendor", "firmographic", "sim", True, "company", 1.0,
         "Invented demo data. A real vendor's licence terms go here.", False, 24 * 7),
        ("technographics", "Technology detection vendor", "technographic", "sim", True, "company", 0.5,
         "Invented demo data. A real vendor's licence terms go here.", False, 24),
        ("funding_db", "Funding database", "firmographic", "sim", True, "company", 2.0,
         "Invented demo data standing in for a licence that forbids redistribution.", True, 24 * 7),
        ("registry", "Companies registry", "registry", "sim", False, None, None,
         "Open government licence in a real install (Companies House, GLEIF).", False, 24 * 30),
        ("public_counts", "Statistics office counts", "public_counts", "sim", False, None, None,
         "Census SUSB files and Eurostat SBS in a real install; simulated here.", False, 24 * 365),
        ("coverage", "Contact coverage vendor", "coverage", "sim", True, "company", 0.2,
         "Counts of findable roles only. No names are stored.", False, 24 * 7),
        ("account_desk", "Account Desk results", "desk_results", "sim", False, None, None, "Our own desk.", False, 24),
        ("events_desk", "Events Desk results", "desk_results", "sim", False, None, None, "Our own desk.", False, 24),
        ("model", "AI reading descriptions", "model", "sim", True, "call", 0.4,
         "Reads vendor descriptions only.", False, 24),
    ]
    n = db.val(cur, "select count(*) from companies")
    for s in sources:
        db.run(cur, """insert into sources (key, label, kind, adapter, paid, unit, price_cents_per_unit, licence_note,
                       no_redistribution, cadence_hours) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", *s)
    for i_s, s in enumerate(sources):
        key, cadence = s[0], s[9]
        last = NOW - timedelta(days=4, hours=3) if key == "technographics" else NOW - timedelta(hours=min(cadence, 48) * 0.5)
        for i in range(3):
            st = last - timedelta(hours=cadence * i)
            db.run(cur, """insert into source_runs (source, started_at, finished_at, rows_read, rows_changed)
                           values (%s,%s,%s,%s,%s)""", key, st, st + timedelta(minutes=7 + i),
                   max(n, 18_000) if key in ("firmographics", "technographics", "coverage") else 400, 40 + 23 * i_s + 7 * i)
