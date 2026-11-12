"""Profile versions: drafts, two-person publish, evidence attached to every rule, and the history the demo opens with."""
from __future__ import annotations

import copy
from datetime import datetime

from . import audit, db, jobs
from . import catalog as C
from .db import J

TRAIT_OF = {"industry": "industry", "region": "region", "revenue_band": "revenue_band", "tech": "tech",
            "pricing_model": "pricing_model", "country": "country"}


def all_rules(rules: dict) -> list[tuple[str, dict]]:
    return [(kind, r) for kind in ("factors", "penalties", "excludes") for r in rules.get(kind, [])]


def rule_evidence(cur, run_id: int, rule: dict) -> dict | None:
    """The rule's own finding (deals matching the rule against the rest), if the rule was in the published profile when
    the run happened; otherwise the findings on the values it names."""
    from .evidence import rule_label
    own = db.one(cur, """select id, verdict, opps from findings where run = %s and trait = 'rule' and value = %s
                         and value_label = %s""", run_id, J(rule.get("key")), rule_label(rule))
    if own:
        return {"finding_id": own["id"], "verdict": own["verdict"], "opps": own["opps"]}
    trait = TRAIT_OF.get(rule["field"])
    vals = rule["value"] if isinstance(rule["value"], list) else [rule["value"]]
    if rule["field"] == "employees":
        lo, hi = rule["value"]
        names = [b for b, blo, bhi in C.SIZE_BANDS if blo <= hi and bhi >= lo]
        rows = db.all(cur, "select id, verdict, opps from findings where run = %s and trait = 'size_band' and value_label = any(%s)",
                      run_id, names)
    elif rule["field"] == "segment":
        rows = db.all(cur, "select id, verdict, opps from findings where run = %s and trait = 'segment' and value = any(%s::jsonb[])",
                      run_id, [J(v) for v in vals])
    elif trait:
        rows = db.all(cur, "select id, verdict, opps from findings where run = %s and trait = %s and value = any(%s::jsonb[])",
                      run_id, trait, [J(v) for v in vals])
    else:
        rows = []
    if not rows:
        return None
    best = max(rows, key=lambda r: r["opps"])
    return {"finding_id": best["id"], "verdict": best["verdict"], "opps": best["opps"]}


def attach_evidence(cur, rules: dict, run_id: int) -> dict:
    out = copy.deepcopy(rules)
    for kind in ("factors", "penalties", "excludes"):
        for r in out.get(kind, []):
            ev = rule_evidence(cur, run_id, r)
            r["evidence"] = {"finding_id": ev["finding_id"]} if ev else None
    return out


def create_draft(cur, *, author: int, rules: dict, note: str, at: datetime | None = None) -> int:
    n = (db.val(cur, "select max(number) from icp_versions") or 0) + 1
    vid = db.val(cur, """insert into icp_versions (number, status, rules, note, author, created_at)
                         values (%s, 'draft', %s, %s, %s, coalesce(%s, app_now())) returning id""",
                 n, J(rules), note, author, at)
    audit.log(cur, "user", "profile_draft_created", "icp_version", vid, {"number": n}, actor_id=author)
    return vid


def publish(cur, version_id: int, by: dict, *, at: datetime | None = None, rescore_now: bool = False) -> None:
    v = db.one(cur, "select * from icp_versions where id = %s for update", version_id)
    if v is None or v["status"] != "draft":
        raise ValueError("Only a draft can be published.")
    if by["role"] != "manager":
        raise PermissionError("A manager publishes a profile.")
    if v["author"] == by["id"]:
        raise PermissionError("Someone other than the author publishes a profile.")
    db.run(cur, "update icp_versions set status = 'retired' where status = 'published'")
    db.run(cur, "update icp_versions set status = 'published', published_by = %s, published_at = coalesce(%s, app_now()) where id = %s",
           by["id"], at, version_id)
    audit.log(cur, by["name"], "profile_published", "icp_version", version_id, {"number": v["number"]}, actor_id=by["id"])
    if rescore_now:
        from .fit import score_version
        score_version(cur, version_id)
    else:
        jobs.enqueue(cur, "rescore_version", {"version": version_id}, dedupe_key=f"rescore_version:{version_id}")


def published(cur) -> dict | None:
    return db.one(cur, "select * from icp_versions where status = 'published'")


# ---------------------------------------------------------------- the history the demo opens with

def demo_versions() -> list[dict]:
    v3 = copy.deepcopy(C.AD_ICP) | {"segments": C.SEGMENTS}
    v1 = copy.deepcopy(v3)
    v1["factors"][0]["value"] = C.PROFILE_INDUSTRIES + ["Healthcare software"]
    v1["factors"][1]["value"] = [50, 2000]
    v1["tiers"] = {"A": 80, "B": 60}
    v1["penalties"] = []
    v2 = copy.deepcopy(v3)
    v2["penalties"] = []
    v2["factors"] = [f for f in v2["factors"] if f["key"] != "revenue"] + [
        {"key": "revenue", "field": "revenue_band", "op": "in", "value": ["$20M-$100M", "$100M-$500M", "$500M+"], "weight": 15}]
    v4 = copy.deepcopy(v3)
    v4["factors"].append({"key": "usage_pricing", "field": "pricing_model", "op": "eq", "value": "usage", "weight": 20,
                          "why": "Usage-based pricing wins far more often."})
    v4["penalties"].append({"key": "too_big", "field": "employees", "op": "between", "value": [2000, 4999], "weight": 20,
                            "why": "2,000 to 4,999 employees rarely close."})
    return [
        {"rules": v1, "note": "First profile, from the founders' first 40 customers.", "created": "2024-01-15",
         "published": "2024-02-01"},
        {"rules": v2, "note": "Healthcare out after a year of compliance losses; revenue band widened.",
         "created": "2025-03-20", "published": "2025-04-01"},
        {"rules": v3, "note": "Revenue band narrowed; legacy ERP penalty added. The profile Account Desk runs.",
         "created": "2026-05-25", "published": "2026-06-02"},
        {"rules": v4, "note": "Usage pricing and the 2,000 to 4,999 penalty, from the evidence.", "created": "2026-11-10",
         "published": None},
    ]
