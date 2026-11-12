"""The shared world export (docs/SPEC.md 5.1): companies, invented people and tiers with stable ids, meant to become
the source the other desks load their accounts and people from. People are generated here, from the seed and the
company's world id only; they never enter this desk's database (docs/DECISIONS.md 1 and 11)."""
from __future__ import annotations

import csv
import hashlib
import json
import random
from pathlib import Path

from . import catalog as C
from . import db
from .sim import names as N

FORMAT_VERSION = "1"
SEED = 7
TITLES = {"cfo": ["CFO", "VP Finance", "Head of Finance"], "controller": ["Controller", "Director of Accounting"],
          "revops": ["Head of Revenue Operations", "Billing Operations Manager"],
          "data": ["Head of Data", "Finance Systems Manager"], "ceo": ["CEO", "Co-founder and CEO"]}
SENIORITY = {"cfo": "c_suite", "ceo": "c_suite", "controller": "director", "revops": "director", "data": "manager"}


def world_id(domain: str) -> str:
    return "co_" + hashlib.sha256(domain.encode()).hexdigest()[:12]


def person_id(company_wid: str, i: int) -> str:
    return "pe_" + hashlib.sha256(f"{company_wid}:{i}".encode()).hexdigest()[:12]


def people_for(company_wid: str, domain: str, employees: int | None) -> list[dict]:
    rng = random.Random(f"{SEED}:{company_wid}")
    personas = (["ceo"] if (employees or 0) < 120 else []) + ["cfo", "controller", "revops", "data"]
    n = rng.randint(2, 6)
    out = []
    used = set()
    for i in range(n):
        p = personas[i % len(personas)]
        while True:
            first, last = rng.choice(N.FIRST), rng.choice(N.LAST)
            if (first, last) not in used:
                used.add((first, last))
                break
        out.append({"world_id": person_id(company_wid, i), "company_world_id": company_wid, "first_name": first,
                    "last_name": last, "title": rng.choice(TITLES[p]), "persona": p, "seniority": SENIORITY[p],
                    "email": f"{first.lower()}.{last.lower()}@{domain}"})
    return out


def export(out_dir: str) -> dict:
    """Demo only: on a live desk this would invent people at real companies (docs/DECISIONS.md 11)."""
    from .config import CONFIG
    if CONFIG.mode != "demo":
        raise SystemExit("The world export invents people. It runs on the demo only.")
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    with db.tx() as cur:
        cur.execute("set transaction read only")
        vid = db.val(cur, "select id from icp_versions where status = 'published'")
        num = db.val(cur, "select number from icp_versions where id = %s", vid)
        rows = db.all(cur, """
            select c.id, c.name, c.primary_domain, p.primary_domain as parent_domain, c.industry, c.employees, c.country,
                   c.region, c.region_group, c.revenue_band, c.pricing_model, c.tech, c.lifecycle, c.hq_city, c.founded_year,
                   f.score, f.tier, f.judged, f.segment, u.email as owner_email
            from companies c left join companies p on p.id = c.parent_id
            left join account_fit f on f.company = c.id and f.icp_version = %s
            left join assignments a on a.company = c.id and a.plan = (select id from territory_plans where status = 'active')
            left join users u on u.id = a.owner
            where not c.sole_trader
            order by c.primary_domain""", vid)
        # The same rule as a book file: only values a vendor, the CRM or a person gave, from a source that may be
        # passed on; the rest is left blank.
        from .handoff import exportable_values
        vals = exportable_values(cur, [r["id"] for r in rows])
        now = db.val(cur, "select app_now()")
    files = {"companies.csv": ["world_id", "name", "domain", "parent_domain", "industry", "employees", "country", "region",
                               "region_group", "revenue_band", "pricing_model", "tech", "lifecycle", "hq_city", "founded_year"],
             "people.csv": ["world_id", "company_world_id", "first_name", "last_name", "title", "persona", "seniority", "email"],
             "tiers.csv": ["company_world_id", "icp_version", "score", "tier", "segment", "owner_email"]}
    counts = {}
    writers = {}
    handles = {}
    for name, header in files.items():
        handles[name] = (d / name).open("w", newline="", encoding="utf-8")
        writers[name] = csv.writer(handles[name], lineterminator="\n")
        writers[name].writerow(header)
        counts[name] = 0
    for r in rows:
        wid = world_id(r["primary_domain"])
        v = vals[r["id"]]
        writers["companies.csv"].writerow([wid, r["name"], r["primary_domain"], r["parent_domain"] or "", v.get("industry") or "",
                                           v.get("employees") or "", r["country"], r["region"], r["region_group"],
                                           v.get("revenue_band") or "", v.get("pricing_model") or "", ";".join(v.get("tech") or []),
                                           r["lifecycle"], r["hq_city"] or "", r["founded_year"] or ""])
        counts["companies.csv"] += 1
        tier = "Not judged" if r["judged"] is False else (r["tier"] or "")
        writers["tiers.csv"].writerow([wid, num, "" if r["score"] is None else r["score"], tier, r["segment"] or "",
                                       r["owner_email"] or ""])
        counts["tiers.csv"] += 1
        if r["tier"] in ("A", "B") and r["judged"] and r["lifecycle"] != "competitor":
            for p in people_for(wid, r["primary_domain"], r["employees"]):
                writers["people.csv"].writerow([p[k] for k in files["people.csv"]])
                counts["people.csv"] += 1
    for h in handles.values():
        h.close()
    manifest = {"format_version": FORMAT_VERSION, "seller": C.SELLER, "seed": SEED, "icp_version": num,
                "built": str(now)[:10],
                "rows": counts, "sha256": {n: hashlib.sha256((d / n).read_bytes()).hexdigest() for n in files},
                "note": "Every company, person and domain is invented. People exist only in this export."}
    (d / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
