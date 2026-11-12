"""The simulated world: an invented seller (Lumen Ledger), its team, a universe of companies, three years of CRM
history, call notes, coverage and public counts. A fixed seed writes the same rows every time.

The relationships below are planted on purpose and disclosed in README. The code that finds them is the product's
real code; when a planted effect was not found, the world was tuned, never the rules (docs/DECISIONS.md).
"""
from __future__ import annotations

import hashlib
import math
import random
from datetime import date, datetime, timedelta, timezone

from .. import catalog as C
from .. import db
from ..db import J
from ..privacy import redact
from . import names as N

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
HISTORY_START = NOW - timedelta(days=36 * 30)

PLANTED = {
    "P1": "Usage-based pricing wins new business at about 38%, other pricing models about 16%. Pricing model is "
          "drawn independently of size, region and industry; about 15% of companies have it unknown.",
    "P2": "2,000 to 4,999 employees win about 8% with won-deal cycles about twice as long.",
    "P3": "Healthcare software loses, with about 60% of its losses coded compliance.",
    "P4": "Salesforce users win more in the crude cut only because they cluster at 120 to 1,999 employees; within a "
          "size band Salesforce has no effect.",
    "P5": "Brazil: 9 opportunities, all at marketplaces, 5 won.",
    "P6": "DACH: the signer role is findable for about 40% of companies against about 85% elsewhere.",
    "P7": "Two finished segment tests of 520 accounts: fintech 120 to 499 books meetings at about 22% worked against "
          "10% held back; developer tools at about 11% against 10%.",
    "P8": "HQ city and founding year carry no effect on winning.",
}

INDUSTRY_SHARE = {"Software": 16, "Fintech": 12, "Data infrastructure": 9, "Developer tools": 8, "Marketplaces": 4,
                  "Healthcare software": 6, "IT services": 11, "Agencies": 7, "E-commerce": 10, "Manufacturing": 7,
                  "Education": 3, "Government": 2, "Media": 3, "Logistics": 2}
COUNTRY_SHARE = {"US": 44, "CA": 5, "MX": 1.5, "GB": 9, "IE": 1, "DE": 6.5, "AT": 1.2, "CH": 1.8, "FR": 4, "NL": 3,
                 "BE": 1, "SE": 2, "DK": 1, "NO": 1, "FI": 0.5, "ES": 2, "IT": 2, "PT": 0.5, "BR": 3, "AR": 0.5,
                 "AU": 3, "IN": 3, "SG": 2.5}
COUNTRY_GROUP = {c: (g, r) for g, (r, cs) in C.REGION_GROUPS.items() for c in cs}
PRICING_SHARE = {"usage": 28, "seat": 34, "transaction": 12, "mixed": 11, "unknown": 15}

# Win probability parts (new business). Salesforce, HQ city and founding year have no term: P4, P8.
BASE_BY_BAND = {"20 to 119": 0.09, "120 to 499": 0.24, "500 to 1,999": 0.24, "2,000 to 4,999": 0.065, "5,000+": 0.06}
PRICE_MULT = {"usage": 2.15, "unknown": 1.0, "seat": 0.92, "transaction": 0.92, "mixed": 0.92}
INDUSTRY_MULT = {"Fintech": 1.15, "Software": 1.0, "Data infrastructure": 1.05, "Developer tools": 0.95,
                 "Marketplaces": 0.95, "Healthcare software": 0.33, "Education": 0.4, "Government": 0.4}
SOURCE_SHARE = {"outbound": 50, "inbound": 25, "event": 15, "partner": 10}
SOURCE_MULT = {"outbound": 0.85, "inbound": 1.35, "event": 1.0, "partner": 1.2}
# Companies with deals, by size band (stratified so P2 and P3 have enough opportunities in the window).
DEAL_COMPANIES_BY_BAND = {"20 to 119": 240, "120 to 499": 510, "500 to 1,999": 390, "2,000 to 4,999": 210, "5,000+": 70}
DEAL_INDUSTRY_WEIGHT = {**{i: 1.0 for i in C.PROFILE_INDUSTRIES}, "Healthcare software": 2.0, "IT services": 0.25,
                        "Agencies": 0.15, "E-commerce": 0.2, "Manufacturing": 0.12, "Education": 0.05,
                        "Government": 0.04, "Media": 0.12, "Logistics": 0.15}
DEAL_REGION_WEIGHT = {"North America": 1.0, "Europe": 0.85, "Latin America": 0.0, "Asia Pacific": 0.2}

LOSS_MIX = {"price": 18, "timing": 15, "no_decision": 25, "competitor": 15, "missing_feature": 12, "compliance": 3,
            "champion_left": 5, "bad_fit": 5, "other": 2}
LOSS_TEXT = {
    "price": ["Too expensive vs budget", "pricing came in 2x what they planned", "budget cut, cant justify cost",
              "CFO balked at the annual price", "price, they wanted 40% off"],
    "timing": ["not this quarter, revisit after their audit", "timing. ERP migration first", "pushed to next FY",
               "bad timing, mid reorg", "come back after Q1 close"],
    "no_decision": ["went dark after demo", "no decision, stuck in committee", "ghosted after pricing call",
                    "status quo, spreadsheets are fine for now", "never got past the controller"],
    "competitor": ["went with {c}", "chose {c}, cheaper on overages", "{c} already in their stack", "lost to {c} on integrations",
                   "picked {c} after bake-off"],
    "missing_feature": ["needs multi-entity consolidation we dont have", "no native SAP connector", "wanted rev rec for hardware bundles",
                        "missing usage alerts for their customers", "need ASC 606 for multi-element contracts in v1"],
    "compliance": ["HIPAA BAA required, we cant sign", "security review failed on data residency", "infosec blocked: PHI in usage records",
                   "compliance team said no to US hosting", "needs SOC 2 type 2 plus HITRUST"],
    "champion_left": ["our champion left the company", "controller resigned mid eval", "VP Fin moved on, new one not engaged",
                      "champion laid off"],
    "bad_fit": ["too small, 3 invoices a month", "they bill hours not usage", "not a fit, consumer business",
                "one product flat fee, no need"],
    "other": ["acquired, parent decides tools", "legal entity restructuring", "see notes"],
}
CHURN_TEXT = {
    "price": ["renewal price too high", "cut costs, cancelled at renewal"],
    "competitor": ["moved to {c}", "consolidated onto {c}"],
    "missing_feature": ["outgrew us, needed multi-entity", "needed procurement module"],
    "champion_left": ["new CFO brought own tools", "champion left, nobody owned it"],
    "bad_fit": ["moved to flat pricing, no longer needed usage billing", "business pivoted to services"],
    "other": ["acquired, moved to parent stack", "company shut down"],
}

REASONS = ["we rebuild usage invoices by hand every month", "month end takes us eleven days because of billing",
           "finance and product never agree on the usage number", "our auditors flagged revenue recognition on overages",
           "we are moving to usage pricing next year and the billing system cannot do it",
           "every price change means an engineering ticket", "we leak revenue on overages we never bill",
           "the board wants clean ARR reporting", "we need to close the books faster",
           "invoices go out late because the usage export breaks"]
OBJECTIONS = ["we already built this in house", "the migration looks like six months of work",
              "our ERP team wants one vendor for everything", "the price per invoice is too high at our volume",
              "we cannot send patient data to a US cloud", "procurement needs a security review first",
              "we only send a handful of invoices a month", "timing is wrong until after our audit"]
COMPETITOR_LINES = ["{c} quoted lower on overages", "they are already piloting {c}", "{c} has the SAP connector"]


def _pick(rng: random.Random, weights: dict) -> str:
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def _band(emp: int) -> str | None:
    return C.size_band(emp)


def _revenue_band(emp: int, rng: random.Random) -> str:
    rev = emp * math.exp(rng.gauss(math.log(180_000), 0.45))
    for limit, band in ((5e6, "<$5M"), (20e6, "$5M-$20M"), (100e6, "$20M-$100M"), (500e6, "$100M-$500M")):
        if rev < limit:
            return band
    return "$500M+"


def _tech(emp: int, rng: random.Random) -> list[str]:
    band = _band(emp)
    sweet = band in ("120 to 499", "500 to 1,999")
    big = band in ("2,000 to 4,999", "5,000+")
    p = {"Salesforce": 0.9 if sweet else (0.04 if big else 0.03),
         "Snowflake": 0.35 if sweet else (0.45 if big else 0.08), "NetSuite": 0.3,
         "Stripe": 0.4 if not big else 0.25, "HubSpot": 0.45 if band == "20 to 119" else 0.15,
         "BigQuery": 0.15, "QuickBooks": 0.5 if band == "20 to 119" else 0.03, "Zuora": 0.05 if not big else 0.15,
         "Chargebee": 0.08, "Databricks": 0.1 if not big else 0.2, "SAP": 0.4 if big else 0.03,
         "Legacy on-prem ERP": 0.25 if big else 0.05}
    return [t for t in C.TECH if rng.random() < p[t]]


def _company_name(rng: random.Random, industry: str, used: set[str]) -> tuple[str, str]:
    while True:
        stem = rng.choice(N.START) + rng.choice(N.MID) + rng.choice(N.END)
        name = f"{stem} {rng.choice(N.SUFFIX[industry])}" if rng.random() < 0.7 else stem
        dom = (stem + ("" if rng.random() < 0.5 else rng.choice(N.SUFFIX[industry]).split()[0])).lower() + ".example"
        if name not in used and dom not in used:
            used.add(name)
            used.add(dom)
            return name, dom


INDUSTRY_PHRASE = {
    "Software": "builds subscription software for finance and operations teams",
    "Fintech": "provides payment and lending infrastructure for online businesses",
    "Data infrastructure": "runs a managed data warehouse and streaming platform",
    "Developer tools": "makes tools developers use to build, test and deploy code",
    "Marketplaces": "operates an online marketplace connecting buyers and sellers",
    "Healthcare software": "makes clinical scheduling and records software for hospitals",
    "IT services": "provides managed IT services and systems integration",
    "Agencies": "is a creative and digital marketing agency",
    "E-commerce": "sells consumer goods online through its own store",
    "Manufacturing": "manufactures industrial components",
    "Education": "runs schools and online courses",
    "Government": "is a public sector body delivering local services",
    "Media": "publishes news and video content",
    "Logistics": "runs freight and warehousing services",
}
PRICING_PHRASE = {
    "usage": "Customers pay per API call and per gigabyte processed.",
    "seat": "Customers pay per user per month.",
    "transaction": "It takes a fee on each transaction it processes.",
    "mixed": "Customers pay a platform fee plus a charge for usage above their plan.",
}


def build(cur, *, seed: int = 7, n_companies: int = 18_000) -> dict:
    rng = random.Random(seed)
    db.run(cur, "update sim_clock set enabled = true, at = %s", NOW)

    # ---------------------------------------------------------------- team, settings, sources
    users = {}
    for name, email, role, tz, started, hours in C.USERS:
        users[name.split()[0]] = db.val(cur, """insert into users (name, email, role, timezone, started_on, selling_hours_month)
            values (%s,%s,%s,%s,%s,%s) returning id""", name, email, role, tz, started, hours)
    for k, (v, note) in C.SETTINGS.items():
        db.run(cur, "insert into settings (key, value, note) values (%s,%s,%s)", k, J(v), note)
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
    for s in sources:
        db.run(cur, """insert into sources (key, label, kind, adapter, paid, unit, price_cents_per_unit, licence_note,
                       no_redistribution, cadence_hours) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", *s)
    for key, *_rest in sources:
        cadence = next(s[9] for s in sources if s[0] == key)
        # technographics last ran four days ago against a daily cadence: the stale-source alert has something to say.
        last = NOW - timedelta(days=4, hours=3) if key == "technographics" else NOW - timedelta(hours=min(cadence, 48) * 0.5)
        for i in range(3):
            st = last - timedelta(hours=cadence * i)
            db.run(cur, """insert into source_runs (source, started_at, finished_at, rows_read, rows_changed)
                           values (%s,%s,%s,%s,%s)""", key, st, st + timedelta(minutes=7 + i), n_companies if key in
                   ("firmographics", "technographics", "coverage") else 400, rng.randint(20, 300))

    # ---------------------------------------------------------------- companies
    used: set[str] = set()
    comps = []
    for i in range(n_companies):
        industry = _pick(rng, INDUSTRY_SHARE)
        country = _pick(rng, COUNTRY_SHARE)
        group, region = COUNTRY_GROUP[country]
        emp = int(math.exp(rng.gauss(math.log(170), 1.15)))
        emp = 5 + int(rng.random() * 15) if rng.random() < 0.025 else max(20, min(60_000, emp))
        if emp == 2000:
            emp = 2001
        pricing = _pick(rng, PRICING_SHARE)
        name, dom = _company_name(rng, industry, used)
        comps.append({
            "i": i, "name": name, "domain": dom, "country": country, "region": region, "region_group": group,
            "hq_city": rng.choice(N.CITIES[country]), "founded_year": int(2024 - min(40, rng.expovariate(1 / 11))),
            "industry": industry, "employees": emp, "revenue_band": _revenue_band(emp, rng), "pricing": pricing,
            "tech": _tech(emp, rng), "sole_trader": country in ("GB", "IE") and emp < 25 and rng.random() < 0.12,
            "lifecycle": "prospect", "vendor_industry": rng.random() > 0.06, "rev_source":
            "funding_db" if rng.random() < 0.05 else "firmographics",
        })
    # Brazil (P5): only marketplaces in the sweet spot get deals; make sure at least nine exist.
    br = [c for c in comps if c["country"] == "BR" and c["industry"] == "Marketplaces" and 120 <= c["employees"] <= 1999]
    for c in [c for c in comps if c["country"] == "BR" and c not in br][: max(0, 9 - len(br))]:
        c["industry"], c["employees"] = "Marketplaces", rng.randint(150, 900)
        br.append(c)
    # Model-read cases (S6): a few companies with no vendor industry whose description says government or education.
    for c in rng.sample([c for c in comps if c["industry"] in ("Government", "Education")], 6):
        c["vendor_industry"] = False

    for c in comps:
        desc = f"{c['name']} {INDUSTRY_PHRASE[c['industry']]}."
        if c["pricing"] != "unknown" and rng.random() < 0.8:
            desc += " " + PRICING_PHRASE[c["pricing"]]
        elif c["pricing"] == "unknown" and rng.random() < 0.25:
            # The vendor has no pricing model, but the description states one: the model may read it.
            c["desc_pricing"] = rng.choice(["usage", "seat"])
            desc += " " + PRICING_PHRASE[c["desc_pricing"]]
        desc += f" Founded in {c['founded_year']}, it is based in {c['hq_city']}."
        c["description"] = desc

    # ---------------------------------------------------------------- deals
    by_band: dict[str, list[dict]] = {}
    for c in comps:
        if c["country"] == "BR" or c["employees"] < 20 or c["sole_trader"]:
            continue
        by_band.setdefault(_band(c["employees"]), []).append(c)
    deal_cos: list[dict] = []
    for band, k in DEAL_COMPANIES_BY_BAND.items():
        pool = by_band.get(band, [])
        w = [DEAL_INDUSTRY_WEIGHT[c["industry"]] * DEAL_REGION_WEIGHT[c["region"]] for c in pool]
        chosen: set[int] = set()
        k = min(k, sum(1 for x in w if x > 0))
        while len(chosen) < k:
            c = rng.choices(pool, weights=w)[0]
            chosen.add(c["i"])
        deal_cos.extend(comps[i] for i in sorted(chosen))
    deal_cos.extend(br[:9])

    team_ae = {"North America": users["Grace"], "Europe": users["Hannah"]}
    deals: list[dict] = []
    span = (NOW - HISTORY_START).days

    def when() -> datetime:
        # Deal flow grows over the three years: density rises linearly, so two thirds land in the last two years.
        u = rng.random()
        frac = (math.sqrt(1 + 3 * u) - 1)  # inverse of a linear density from 1 to 2 over [0, 1]
        return HISTORY_START + timedelta(days=frac * span, hours=rng.randint(8, 18), minutes=rng.choice((0, 15, 30, 45)))

    def win_p(c: dict, source: str) -> float:
        p = BASE_BY_BAND[_band(c["employees"])] * PRICE_MULT[c["pricing"]] * INDUSTRY_MULT.get(c["industry"], 0.6)
        return min(0.9, p * SOURCE_MULT[source])

    br_wins = {id(c): (j < 5) for j, c in enumerate(br[:9])}
    for c in deal_cos:
        n_deals = 1 if c["country"] == "BR" else (2 if rng.random() < 0.25 else 1)
        start = when() if c["country"] != "BR" else NOW - timedelta(days=rng.randint(200, 600))
        for j in range(n_deals):
            source = _pick(rng, SOURCE_SHARE)
            created = start if j == 0 else start + timedelta(days=rng.randint(240, 420))
            if created > NOW - timedelta(days=2):
                break
            won = br_wins[id(c)] if c["country"] == "BR" else rng.random() < win_p(c, source)
            slow = 2.0 if _band(c["employees"]) == "2,000 to 4,999" else 1.0
            cycle = max(9, int(math.exp(rng.gauss(math.log(85 if won else 70), 0.45)) * slow))
            if c["country"] == "BR":
                cycle = min(cycle, (NOW - created).days - 5)
            closed = created + timedelta(days=cycle, hours=rng.randint(-3, 3))
            acv = int(math.exp(rng.gauss(math.log(38_000), 0.55)) * (max(c["employees"], 60) / 300) ** 0.22)
            loss_code = None
            if not won:
                loss_code = "compliance" if c["industry"] == "Healthcare software" and rng.random() < 0.6 else _pick(rng, LOSS_MIX)
            deals.append({"c": c, "kind": "new", "created": created, "closed": closed if closed < NOW else None,
                          "won": won, "acv": acv * 100, "source": source, "loss": loss_code,
                          "owner": (users["Grace"] if rng.random() < 0.5 else users["Omar"]) if c["region"] == "North America"
                          else team_ae.get(c["region"], users["Omar"])})
            if won and closed < NOW:
                break

    # Expansion at customers, later.
    for d in list(deals):
        for _k in range(3 if d["won"] and d["closed"] else 0):
            if rng.random() > 0.55:
                continue
            created = d["closed"] + timedelta(days=rng.randint(90, 420) * (_k + 1))
            if created < NOW - timedelta(days=20):
                cyc = max(7, int(math.exp(rng.gauss(math.log(52), 0.4))))
                closed = created + timedelta(days=cyc)
                deals.append({"c": d["c"], "kind": "expansion", "created": created,
                              "closed": closed if closed < NOW else None, "won": rng.random() < 0.45,
                              "acv": int(d["acv"] * rng.uniform(0.2, 0.45)), "source": "inbound", "loss": None,
                              "owner": d["owner"]})

    # ---------------------------------------------------------------- write companies and provenance
    cid: dict[int, int] = {}
    with cur.copy("""copy companies (name, primary_domain, country, region, region_group, hq_city, founded_year, industry,
                     employees, revenue_band, pricing_model, tech, description, lifecycle, sole_trader, crm_id, created_at)
                     from stdin""") as cp:
        for c in comps:
            cp.write_row((c["name"], c["domain"], c["country"], c["region"], c["region_group"], c["hq_city"],
                          c["founded_year"], c["industry"] if c["vendor_industry"] else None, c["employees"],
                          c["revenue_band"], c["pricing"], c["tech"], c["description"], "prospect", c["sole_trader"],
                          None, HISTORY_START))
    for r in db.all(cur, "select id, primary_domain from companies"):
        cid[r["primary_domain"]] = r["id"]
    for c in comps:
        c["id"] = cid[c["domain"]]
    obs = NOW - timedelta(days=9)
    with cur.copy("copy field_values (company, field, value, source, observed_at, confidence) from stdin") as cp:
        for c in comps:
            if c["vendor_industry"]:
                cp.write_row((c["id"], "industry", J(c["industry"]), "firmographics", obs, 0.95))
            cp.write_row((c["id"], "employees", J(c["employees"]), "firmographics", obs, 0.9))
            cp.write_row((c["id"], "revenue_band", J(c["revenue_band"]), c["rev_source"], obs, 0.8))
            cp.write_row((c["id"], "pricing_model", J(c["pricing"]), "firmographics", obs, 0.85))
            cp.write_row((c["id"], "tech", J(c["tech"]), "technographics", NOW - timedelta(days=4), 0.8))

    # ---------------------------------------------------------------- write deals, roles, customers, notes
    contacts_seen = 0
    deal_rows = []
    for d in sorted(deals, key=lambda d: d["created"]):
        c = d["c"]
        outcome = "open" if d["closed"] is None else ("won" if d["won"] else "lost")
        loss_text = None
        comp = None
        if outcome == "lost":
            d["loss"] = d["loss"] or _pick(rng, LOSS_MIX)
            if d["loss"] == "competitor":
                comp = rng.choice(C.COMPETITORS)
            loss_text = rng.choice(LOSS_TEXT[d["loss"]]).format(c=comp or rng.choice(C.COMPETITORS))
        snap = {"industry": c["industry"], "employees": c["employees"], "region": c["region"],
                "region_group": c["region_group"], "country": c["country"], "revenue_band": c["revenue_band"],
                "pricing_model": c["pricing"], "tech": c["tech"], "hq_city": c["hq_city"],
                "founded_year": c["founded_year"]}
        stage = {"won": "Closed won", "lost": "Closed lost"}.get(outcome) or rng.choice(["Discovery", "Evaluation", "Proposal"])
        did = db.val(cur, """insert into deals (company, kind, created_at, closed_at, stage, outcome, amount_cents,
                             loss_reason_text, competitor, source, owner, snapshot)
                             values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
                     c["id"], d["kind"], d["created"], d["closed"], stage, outcome, d["acv"], loss_text, comp,
                     d["source"], d["owner"], J(snap))
        d["id"], d["outcome"] = did, outcome
        deal_rows.append(d)
        if d["kind"] != "new":
            continue
        # roles: personas on the deal, never names
        small = c["employees"] < 120
        big = c["employees"] >= 2000
        personas = ["cfo", "controller"] + rng.sample(["revops", "data"], rng.randint(0, 2))
        if big:
            personas += ["procurement", "security"]
        if small:
            personas = ["ceo"] + personas[:2]
        signer = "ceo" if small and rng.random() < 0.6 else ("cfo" if rng.random() < 0.8 else "controller")
        champion = rng.choice([p for p in personas if p not in ("procurement", "security", signer)] or [personas[0]])
        for p in personas:
            db.run(cur, "insert into deal_roles (deal, persona, seniority, was_signer, was_champion) values (%s,%s,%s,%s,%s)",
                   did, p, {"cfo": "c_suite", "ceo": "c_suite", "controller": "director"}.get(p, "manager"),
                   p == signer and outcome == "won", p == champion)
        d["personas"] = personas

    # customers and lifecycle
    customers = {}
    for d in deal_rows:
        if d["kind"] == "new" and d["outcome"] == "won":
            c = d["c"]
            start = d["closed"].date()
            years = (NOW.date() - start).days / 365
            churned = None
            if rng.random() < 1 - (1 - 0.12) ** years:
                churned = start + timedelta(days=int(rng.uniform(0.3, 1.0) * (NOW.date() - start).days))
                churned = max(churned, start + timedelta(days=30))
                if churned >= NOW.date():
                    churned = None
            customers[c["id"]] = (start, churned, d["acv"], d["owner"])
    for co, (start, churned, acv, owner) in customers.items():
        code = _pick(rng, {"price": 25, "competitor": 20, "missing_feature": 20, "champion_left": 15, "bad_fit": 12, "other": 8}) if churned else None
        text = rng.choice(CHURN_TEXT[code]).format(c=rng.choice(C.COMPETITORS)) if code else None
        db.run(cur, """insert into customers (company, started_on, churned_on, churn_reason_text, arr_cents)
                       values (%s,%s,%s,%s,%s)""", co, start, churned, text, acv)
        db.run(cur, "update companies set lifecycle = %s, owner_id = %s, crm_id = %s where id = %s",
               "churned" if churned else "customer", owner, f"CRM-{co:06d}", co)
    for d in deal_rows:
        if d["outcome"] == "open" and d["c"]["id"] not in customers:
            db.run(cur, "update companies set lifecycle = 'open_opp', owner_id = %s, crm_id = %s where id = %s",
                   d["owner"], f"CRM-{d['c']['id']:06d}", d["c"]["id"])
        elif d["c"]["id"] not in customers:
            db.run(cur, "update companies set crm_id = %s where id = %s and crm_id is null", f"CRM-{d['c']['id']:06d}", d["c"]["id"])
    # Some customers grew after they bought: their deal snapshot keeps the size they had then, and the analysis
    # reads the snapshot, never today's company.
    for co in sorted(customers):
        if rng.random() < 0.08:
            c = next(x for x in comps if x["id"] == co)
            grown = int(c["employees"] * rng.uniform(1.6, 6.5))
            db.run(cur, "update companies set employees = %s where id = %s", grown, co)
            db.run(cur, "update field_values set value = %s where company = %s and field = 'employees'", J(grown), co)
    # competitors and partners
    for j, name in enumerate(C.COMPETITORS):
        db.run(cur, """insert into companies (name, primary_domain, country, region, region_group, industry, employees,
                       revenue_band, pricing_model, tech, description, lifecycle, created_at)
                       values (%s,%s,'US','North America','North America','Software',%s,'$20M-$100M','seat','{}',%s,'competitor',%s)""",
               name, name.lower().replace(" ", "") + ".example", 180 + 70 * j, f"{name} sells billing software.", HISTORY_START)

    # call notes on about 900 closed new-business deals; names are planted, then redacted at import
    closed_new = [d for d in deal_rows if d["kind"] == "new" and d["outcome"] in ("won", "lost")]
    noted = rng.sample(closed_new, min(900, len(closed_new)))
    authors = [users[k] for k in ("Maya", "Daniel", "Priya", "Tom", "Grace", "Omar", "Hannah")]
    note_count = 0
    for d in noted:
        contacts = []
        for p in d.get("personas", ["cfo"]):
            full = f"{rng.choice(N.FIRST)} {rng.choice(N.LAST)}"
            contacts.append((full, C.PERSONAS[p].lower()))
        contacts_seen += len(contacts)
        for k in range(rng.choice((1, 2, 2, 3, 3, 4))):
            who, role = rng.choice(contacts)
            if d["outcome"] == "won":
                said = rng.choice(REASONS)
            elif d.get("loss") == "competitor":
                said = rng.choice(COMPETITOR_LINES).format(c=rng.choice(C.COMPETITORS))
            elif d.get("loss") == "compliance":
                said = rng.choice(["we cannot send patient data to a US cloud", "procurement needs a security review first"])
            else:
                said = rng.choice(OBJECTIONS)
            opener = rng.choice([f"Call with {who}, {role}.", f"Spoke to {who.split()[0]} ({role}).",
                                 f"{who} joined, {role}.", f"Follow-up with Mr. {who.split()[-1]}."])
            raw = f"{opener} Said \"{said}\". " + rng.choice(["Next step: demo for finance.", "Sent pricing.",
                                                              "Agreed to loop in procurement.", "Will follow up after their close.",
                                                              f"Email {who.split()[0].lower()}@{d['c']['domain']} the deck."])
            text = redact(raw, contacts)
            at = d["created"] + timedelta(days=min(k * 14 + rng.randint(1, 10), max(1, (d["closed"] - d["created"]).days)))
            db.run(cur, "insert into call_notes (deal, written_at, author, text_redacted) values (%s,%s,%s,%s)",
                   d["id"], at, rng.choice(authors), text)
            note_count += 1

    # ---------------------------------------------------------------- coverage (P6) and public counts
    with cur.copy("copy reachability (company, persona, has_named_contact_source, email_fill_rate, observed_at) from stdin") as cp:
        for c in comps:
            dach = c["region_group"] == "DACH"
            for p, base in (("cfo", 0.85), ("controller", 0.8), ("revops", 0.75), ("data", 0.7), ("ceo", 0.9)):
                found = rng.random() < (0.40 if dach else base)
                cp.write_row((c["id"], p, found, round(rng.uniform(0.5, 0.95) if found else 0.0, 2), NOW - timedelta(days=5)))
    cells: dict[tuple, int] = {}
    for c in comps:
        b = C.size_band(c["employees"])
        if b:
            cells[(c["country"], c["industry"], b)] = cells.get((c["country"], c["industry"], b), 0) + 1
    with cur.copy("copy public_counts (source, country, industry, size_band, year, companies) from stdin") as cp:
        for (country, ind, b), n in sorted(cells.items()):
            if rng.random() < 0.05:
                continue  # some cells have no public count: coverage there is unknown, never 100%
            under = COUNTRY_GROUP[country][0] in ("DACH", "France and Benelux") and country in ("DE", "AT", "CH", "FR")
            factor = (1.75 if under else 1.18) * rng.uniform(0.92, 1.12)
            cp.write_row(("public_counts", country, ind, b, 2024, max(n, int(round(n * factor)))))

    return {"companies": len(comps) + len(C.COMPETITORS), "deals": len(deal_rows),
            "new_business": sum(1 for d in deal_rows if d["kind"] == "new"), "customers": len(customers),
            "call_notes": note_count, "contacts_redacted": contacts_seen}


def world_id(domain: str) -> str:
    return "co_" + hashlib.sha256(domain.encode()).hexdigest()[:12]


def as_of(d: date | datetime) -> str:
    return d.isoformat()
