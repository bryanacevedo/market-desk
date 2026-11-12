"""Fit, tier and segment for every company, from a profile version.

`fit` is Account Desk's `scoring.fit` (src/outbound/scoring.py), ported from its code, plus an `eq` operator, a
Not judged state of its own (docs/DECISIONS.md 12) and the rule that a model-read value never excludes a company.
`fit` is pure: the stored inputs always give the stored score (tests/test_privacy_and_gates.py).
"""
from __future__ import annotations

from . import catalog as C
from . import db, jobs
from .db import J

MIN_KNOWN = 0.6
FIELDS = ("industry", "employees", "region", "revenue_band", "tech", "pricing_model", "country", "region_group",
          "lifecycle")


def matches(rule: dict, company: dict) -> bool:
    value = company.get(rule["field"])
    op, target = rule["op"], rule["value"]
    if value is None or value == "unknown":
        return False
    if op == "in":
        return value in target
    if op == "eq":
        return value == target
    if op == "between":
        return target[0] <= value <= target[1]
    if op == "has_any":
        return bool(set(value or []) & set(target))
    if op == "has_none":
        return not (set(value or []) & set(target))
    raise ValueError(f"unknown profile operator {op}")


def known(rule: dict, company: dict) -> bool:
    v = company.get(rule["field"])
    return v is not None and v != [] and v != "" and v != "unknown"


def segment_of(rules: dict, company: dict) -> str:
    for s in rules.get("segments", C.SEGMENTS):
        if all(matches(w, company) for w in s["when"]):
            return s["key"]
    return C.OUTSIDE["key"]


def fit(rules: dict, company: dict, *, model_fields: frozenset[str] = frozenset(), profile_only: bool = False) -> dict:
    """Returns {score, tier, judged, scored_out_of, factors, excluded, segment}. `model_fields` are fields whose value
    the model read from a description: they count toward the score but never trigger an exclude. `profile_only`
    skips the lifecycle check (the backtest scores customers too)."""
    seg = segment_of(rules, {**company, "segment": None})
    company = {**company, "segment": seg}
    out = {"segment": seg}
    if not profile_only and company.get("lifecycle") in ("customer", "open_opp", "competitor"):
        return out | {"score": 0, "tier": "X", "judged": True, "scored_out_of": 1.0, "factors": [],
                      "excluded": "Already has an open deal" if company["lifecycle"] == "open_opp" else "Already a customer",
                      "not_applied": []}
    not_applied = []
    for ex in rules.get("excludes", []):
        if matches(ex, company):
            if ex["field"] in model_fields:
                not_applied.append({"key": ex.get("key"), "reason": ex["reason"], "field": ex["field"]})
                continue
            return out | {"score": 0, "tier": "X", "judged": True, "scored_out_of": 1.0, "factors": [],
                          "excluded": ex["reason"], "not_applied": []}
    total = sum(f["weight"] for f in rules["factors"] if f["weight"] > 0) or 1
    known_f = [f for f in rules["factors"] if known(f, company)]
    known_total = sum(f["weight"] for f in known_f if f["weight"] > 0) or 1
    factors, got = [], 0.0
    for f in rules["factors"]:
        if f not in known_f:
            factors.append({"key": f["key"], "matched": None, "weight": f["weight"], "contribution": 0.0})
            continue
        m = matches(f, company)
        contribution = 100.0 * f["weight"] / known_total if m else 0.0
        got += contribution
        factors.append({"key": f["key"], "matched": m, "weight": f["weight"], "contribution": round(contribution, 1)})
    share = sum(f["weight"] for f in known_f if f["weight"] > 0) / total
    if share < MIN_KNOWN:
        return out | {"score": None, "tier": "C", "judged": False, "scored_out_of": round(share, 3), "factors": factors,
                      "excluded": None, "not_applied": not_applied}
    for p in rules.get("penalties", []):
        if matches(p, company):
            got -= p["weight"]
            factors.append({"key": p["key"], "matched": True, "weight": -p["weight"], "contribution": -p["weight"]})
    score = int(round(max(0.0, min(100.0, got))))
    tiers = rules.get("tiers", {"A": 70, "B": 50})
    tier = "A" if score >= tiers["A"] else "B" if score >= tiers["B"] else "C"
    return out | {"score": score, "tier": tier, "judged": True, "scored_out_of": round(share, 3), "factors": factors,
                  "excluded": None, "not_applied": not_applied}


def tier_label(row: dict) -> str:
    return "Not judged" if not row.get("judged", True) else row["tier"]


# ---------------------------------------------------------------- reading companies

COMPANY_SQL = """
select c.id, c.name, c.primary_domain, c.lifecycle, c.industry, c.employees, c.region, c.region_group, c.country,
       c.revenue_band, c.pricing_model, c.tech, c.owner_id, c.sole_trader,
       coalesce((select array_agg(distinct f.field) from field_values f where f.company = c.id and f.source = 'model'
                 and not exists (select 1 from field_values g where g.company = c.id and g.field = f.field
                                 and g.source <> 'model')), '{}') as model_fields,
       (select jsonb_object_agg(f.field, f.value) from field_values f where f.company = c.id and f.source = 'model'
          and not exists (select 1 from field_values g where g.company = c.id and g.field = f.field and g.source <> 'model'))
         as model_values
from companies c"""


def company_inputs(row: dict) -> tuple[dict, frozenset[str]]:
    """The fields fit reads, with model-read values filled where no vendor, CRM or person value exists."""
    data = {k: row.get(k) for k in FIELDS}
    mv = row.get("model_values") or {}
    for field, value in mv.items():
        if data.get(field) in (None, "unknown", []):
            data[field] = value
    return data, frozenset(row.get("model_fields") or [])


def score_version(cur, version_id: int, *, ids: list[int] | None = None) -> int:
    rules = db.val(cur, "select rules from icp_versions where id = %s", version_id)
    where = " where c.id = any(%s)" if ids is not None else ""
    rows = db.all(cur, COMPANY_SQL + where, *( [ids] if ids is not None else []))
    db.run(cur, "delete from account_fit where icp_version = %s" + (" and company = any(%s)" if ids is not None else ""),
           version_id, *([ids] if ids is not None else []))
    with cur.copy("""copy account_fit (company, icp_version, score, tier, judged, segment, scored_out_of,
                     components_missing, excluded, inputs, breakdown) from stdin""") as cp:
        for r in rows:
            data, mf = company_inputs(r)
            f = fit(rules, data, model_fields=mf)
            missing = [x["key"] for x in f["factors"] if x["matched"] is None]
            cp.write_row((r["id"], version_id, f["score"], f["tier"], f["judged"], f["segment"], f["scored_out_of"],
                          missing, f["excluded"], J({"fields": data, "model_fields": sorted(mf)}),
                          J({"factors": f["factors"], "not_applied": f["not_applied"]})))
    return len(rows)


@jobs.handler("rescore_version")
def _rescore(cur, payload: dict) -> None:
    """Publishing rescores every company in batches of 1,000, each its own job, with progress on the parent."""
    vid = payload["version"]
    ids = [r["id"] for r in db.all(cur, "select id from companies order by id")]
    for i in range(0, len(ids), 1000):
        jobs.enqueue(cur, "rescore_batch", {"version": vid, "ids": ids[i:i + 1000], "of": len(ids)},
                     dedupe_key=f"rescore:{vid}:{i}")


@jobs.handler("rescore_batch")
def _rescore_batch(cur, payload: dict) -> None:
    score_version(cur, payload["version"], ids=payload["ids"])


def what_moves(cur, draft_id: int, published_id: int) -> dict:
    """Counts of tier changes, by owner and by segment, and the list, for a draft against the published version.
    The draft's scores are computed in this read-only transaction, never stored."""
    rules = db.val(cur, "select rules from icp_versions where id = %s", draft_id)
    pub = {r["company"]: r for r in db.all(cur, "select company, tier, judged, score, segment from account_fit where icp_version = %s",
                                         published_id)}
    owners = {r["company"]: r["owner"] for r in db.all(cur, """select a.company, u.name as owner from assignments a
              join territory_plans p on p.id = a.plan and p.status = 'active' join users u on u.id = a.owner""")}
    moves: dict[tuple[str, str], int] = {}
    by_owner: dict[str, int] = {}
    by_segment: dict[str, int] = {}
    listing = []
    for r in db.all(cur, COMPANY_SQL):
        data, mf = company_inputs(r)
        f = fit(rules, data, model_fields=mf)
        old = pub.get(r["id"])
        if old is None:
            continue
        a, b = tier_label(old), tier_label(f)
        if a == b:
            continue
        moves[(a, b)] = moves.get((a, b), 0) + 1
        ow = owners.get(r["id"], "Unassigned")
        by_owner[ow] = by_owner.get(ow, 0) + 1
        by_segment[f["segment"]] = by_segment.get(f["segment"], 0) + 1
        listing.append({"company": r["id"], "name": r["name"], "domain": r["primary_domain"], "from": a, "to": b,
                        "score_from": old["score"], "score_to": f["score"], "segment": f["segment"], "owner": ow})
    order = {"A": 0, "B": 1, "C": 2, "Not judged": 3, "X": 4}
    listing.sort(key=lambda x: (order[x["to"]] - order[x["from"]], x["name"]))
    return {"total": len(listing),
            "moves": [{"from": a, "to": b, "count": n} for (a, b), n in sorted(moves.items(), key=lambda kv: -kv[1])],
            "by_owner": [{"owner": k, "count": v} for k, v in sorted(by_owner.items(), key=lambda kv: -kv[1])],
            "by_segment": [{"segment": k, "label": C.SEGMENT_LABEL.get(k, k), "count": v}
                           for k, v in sorted(by_segment.items(), key=lambda kv: -kv[1])],
            "list": listing[:300]}


def backtest(cur, version_id: int) -> list[dict]:
    """Keyplay's test lists, scored profile-only (the lifecycle check skipped): current customers, the top quarter of
    customers by ACV, closed-lost companies, churned customers, and a fixed random control of 500."""
    rules = db.val(cur, "select rules from icp_versions where id = %s", version_id)
    groups = {
        "Current customers": "select company as id from customers where churned_on is null",
        "Top quarter by deal size": """select company as id from customers where churned_on is null
            and arr_cents >= (select percentile_cont(0.75) within group (order by arr_cents) from customers where churned_on is null)""",
        "Closed lost": """select distinct company as id from deals where kind = 'new' and outcome = 'lost'
            and company not in (select company from customers)""",
        "Churned customers": "select company as id from customers where churned_on is not null",
        "Random control": "select id from companies where lifecycle <> 'competitor' order by md5(id::text || 'control') limit 500",
    }
    out = []
    for label, sql in groups.items():
        ids = [r["id"] for r in db.all(cur, sql)]
        mix = {"A": 0, "B": 0, "C": 0, "X": 0, "Not judged": 0}
        for r in db.all(cur, COMPANY_SQL + " where c.id = any(%s)", ids):
            data, mf = company_inputs(r)
            mix[tier_label(fit(rules, data, model_fields=mf, profile_only=True))] += 1
        out.append({"group": label, "n": len(ids), "mix": mix})
    return out
