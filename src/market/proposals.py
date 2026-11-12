"""Profile change proposals. Code decides every proposal from the findings and the segment tests (docs/SPEC.md 9.4 and
15.9); the model only words it, behind gates. RevOps makes a proposal a draft or dismisses it; publishing still needs a
second person."""
from __future__ import annotations

import copy

from . import ai, audit, db, profiles
from . import catalog as C
from .db import J
from .fit import COMPANY_SQL, company_inputs, fit

FIELD_OF = {"industry": "industry", "size_band": "employees", "region": "region", "revenue_band": "revenue_band",
            "pricing_model": "pricing_model", "tech": "tech", "country": "country"}


def pct(x: float | None) -> str:
    return "" if x is None else f"{round(100 * x)}%"


def finding_view(f: dict) -> dict:
    """A finding as the screens and the model see it: rates as written on screen."""
    top = (f.get("top_loss_codes") or [None])[0]
    return {"id": f["id"], "trait": C.FIELD_LABEL.get(f["trait"], f["trait"]), "value": f["value_label"],
            "opportunities": f["opps"], "win_rate": pct(f["win_rate"]),
            "range": f"{pct(f['wr_low'])} to {pct(f['wr_high'])}",
            "rest_win_rate": pct(f["rest_wins"] / f["rest_opps"]) if f["rest_opps"] else "",
            "verdict": {"clear_higher": "Clearly higher", "clear_lower": "Clearly lower", "not_clear": "Not clear",
                        "too_few": "Too few to tell", "explained_by_size": "Explained by size"}[f["verdict"]],
            "top_loss": f"{C.LOSS_LABEL[top['code']].lower()} {pct(top['share'])}" if top else None}


def _rule_for(f: dict) -> dict:
    field = FIELD_OF[f["trait"]]
    v = f["value"]
    if f["trait"] == "size_band":
        lo, hi = next((lo, hi) for b, lo, hi in C.SIZE_BANDS if b == v)
        return {"field": "employees", "op": "between", "value": [lo, min(hi, 1_000_000)]}
    if field == "tech":
        return {"field": "tech", "op": "has_any", "value": [v]}
    if field == "pricing_model":
        return {"field": "pricing_model", "op": "eq", "value": v}
    return {"field": field, "op": "in", "value": [v]}


def _covered(rules: dict, rule: dict, kinds: tuple[str, ...]) -> bool:
    for kind in kinds:
        for r in rules.get(kind, []):
            if r["field"] != rule["field"]:
                continue
            rv, v = r["value"], rule["value"]
            if r["op"] == "between" and rule["op"] == "between":
                if rv[0] <= v[0] and v[1] <= rv[1] or (kind != "factors" and not (v[1] < rv[0] or v[0] > rv[1])):
                    return True
            elif r["op"] == "eq" and v == rv:
                return True
            elif isinstance(rv, list) and isinstance(v, list) and set(v) <= set(rv):
                return True
            elif isinstance(rv, list) and v in rv:
                return True
    return False


def _reach_ab(cur, rules: dict, rule: dict) -> float:
    """Share of companies with this value that the published profile puts in tier A or B."""
    from .fit import matches
    rows = db.all(cur, COMPANY_SQL + " where c.lifecycle = 'prospect'")
    hit = ab = 0
    for r in rows:
        data, mf = company_inputs(r)
        if matches(rule, data):
            hit += 1
            if fit(rules, data, model_fields=mf)["tier"] in ("A", "B"):
                ab += 1
    return ab / hit if hit else 0.0


def decide(cur) -> list[dict]:
    """What code proposes from the latest run and the read tests. Pure decision; `generate` writes them."""
    run = db.val(cur, "select max(id) from analysis_runs")
    pub = profiles.published(cur)
    rules = pub["rules"]
    findings = db.all(cur, "select * from findings where run = %s order by p_value", run)
    s = {r["key"]: r["value"] for r in db.all(cur, "select key, value from settings")}
    out: list[dict] = []
    adds_by_trait: set[str] = set()
    for f in findings:
        if f["verdict"] != "clear_higher" or f["trait"] not in FIELD_OF:
            continue
        rule = _rule_for(f)
        if _covered(rules, rule, ("factors",)):
            continue
        key = f"add_rule:{f['trait']}:{f['value']}"
        out.append({"key": key, "kind": "add_rule", "finding": f, "rule": rule | {"key": f"{f['trait']}_{f['value']}".lower().replace(" ", "_"),
                    "weight": 20, "why": f"{f['value_label']} wins more often."}})
        adds_by_trait.add(f["trait"])
    for f in findings:
        if f["verdict"] != "clear_lower" or f["trait"] not in FIELD_OF or f["trait"] in adds_by_trait:
            continue
        rule = _rule_for(f)
        if _covered(rules, rule, ("penalties", "excludes")):
            continue
        if _reach_ab(cur, rules, rule) < 0.10:
            continue
        top = (f["top_loss_codes"] or [None])[0]
        lost = f["opps"] - f["wins"]
        share = (top["n"] / lost) if top and lost else 0
        if top and share > 0.5:
            out.append({"key": f"add_exclude:{f['trait']}:{f['value']}", "kind": "add_exclude", "finding": f,
                        "rule": rule | {"key": f"no_{f['value']}".lower().replace(" ", "_"),
                                        "reason": f"Loses on {C.LOSS_LABEL[top['code']].lower()}"}})
        else:
            out.append({"key": f"penalty:{f['trait']}:{f['value']}", "kind": "penalty", "finding": f,
                        "rule": rule | {"key": f"low_{f['value']}".lower().replace(" ", "_").replace(",", ""), "weight": 20,
                                        "why": f"{f['value_label']} rarely closes."}})
    min_opps = int(s.get("drop_rule_min_opps", 60))
    for kind, r in profiles.all_rules(rules):
        f = db.one(cur, "select * from findings where run = %s and trait = 'rule' and value = %s", run, J(r.get("key")))
        if f and f["opps"] >= min_opps and f["verdict"] in ("not_clear", "explained_by_size") and kind != "excludes":
            out.append({"key": f"drop_rule:{r['key']}", "kind": "drop_rule", "finding": f, "rule": r, "from": kind})
    from . import tests_seg
    for t in db.all(cur, "select * from segment_tests where status = 'read' and decision = 'expand'"):
        rep = tests_seg.read(cur, t["id"])
        if rep["enough"] and rep["interval"] and rep["interval"][0] > 0:
            out.append({"key": f"segment_expand:{t['segment']}", "kind": "segment_expand", "finding": None, "test": t,
                        "report": rep, "rule": {"key": f"segment_{t['segment']}", "field": "segment", "op": "in",
                                                "value": [t["segment"]], "weight": 10,
                                                "why": "Worked accounts booked more meetings than held-back ones."}})
    return out


def _diff(p: dict) -> dict:
    if p["kind"] == "add_rule" or p["kind"] == "segment_expand":
        return {"add": {"factors": [p["rule"]]}}
    if p["kind"] == "penalty":
        return {"add": {"penalties": [p["rule"]]}}
    if p["kind"] == "add_exclude":
        return {"add": {"excludes": [p["rule"]]}}
    if p["kind"] == "drop_rule":
        return {"remove": {p["from"]: [p["rule"]["key"]]}}
    return {}


def apply_diff(rules: dict, diff: dict) -> dict:
    out = copy.deepcopy(rules)
    for kind, items in (diff.get("add") or {}).items():
        out.setdefault(kind, [])
        keys = {r["key"] for r in out[kind]}
        out[kind] += [i for i in items if i["key"] not in keys]
    for kind, keys in (diff.get("remove") or {}).items():
        out[kind] = [r for r in out.get(kind, []) if r["key"] not in keys]
    return out


def _payload(p: dict) -> dict:
    r = p["rule"]
    if p["kind"] == "segment_expand":
        value_label = C.SEGMENT_LABEL[r["value"][0]]
        rep = p["report"]
        findings = [{"id": p["test"]["id"], "trait": "Segment test", "value": value_label,
                     "opportunities": rep["treated"]["accounts"], "win_rate": pct(rep["treated"]["rate"]),
                     "range": f"{pct(rep['interval'][0])} to {pct(rep['interval'][1])}",
                     "rest_win_rate": pct(rep["holdout"]["rate"]), "verdict": "Clearly higher", "top_loss": None}]
    else:
        from .evidence import rule_label
        value_label = rule_label(r).split(": ", 1)[1] if p["kind"] == "drop_rule" else p["finding"]["value_label"]
        findings = [finding_view(p["finding"])]
    return {"change": {"kind": p["kind"], "field": r["field"], "field_label": C.FIELD_LABEL.get(r["field"], r["field"]),
                       "op": r["op"], "value_label": value_label, "weight": r.get("weight")}, "findings": findings}


def generate(cur) -> list[int]:
    """Writes every proposal code decides that is not already on file, worded by the model behind its gate."""
    made = []
    now = db.val(cur, "select app_now()")
    for p in decide(cur):
        if db.val(cur, "select 1 from change_proposals where key = %s", p["key"]):
            continue
        payload = _payload(p)
        sentences, fails = ai.proposal_text(cur, payload)
        evidence = {"finding_ids": [p["finding"]["id"]] if p.get("finding") else [],
                    "test_ids": [p["test"]["id"]] if p.get("test") else [], "payload": payload}
        pid = db.val(cur, """insert into change_proposals (kind, evidence, proposed_rules_diff, text_sentences, text_status,
                             status, created_at, key) values (%s,%s,%s,%s,%s,'open',%s,%s) returning id""",
                     p["kind"], J(evidence), J(_diff(p)), J(sentences) if sentences else None,
                     "ok" if sentences else "withheld", now, p["key"])
        audit.log(cur, "desk", "proposal_opened", "proposal", pid, {"kind": p["kind"], "withheld": not sentences})
        made.append(pid)
    return made


def make_draft(cur, proposal_ids: list[int], by: dict, note: str | None = None) -> int:
    if by["role"] != "revops":
        raise PermissionError("RevOps turns proposals into a draft.")
    rows = db.all(cur, "select * from change_proposals where id = any(%s) and status = 'open' for update", proposal_ids)
    if not rows:
        raise ValueError("No open proposals were chosen.")
    pub = profiles.published(cur)
    rules = pub["rules"]
    for r in rows:
        rules = apply_diff(rules, r["proposed_rules_diff"])
    vid = profiles.create_draft(cur, author=by["id"], rules=rules, note=note or "From proposals")
    db.run(cur, "update change_proposals set status = 'drafted', decided_by = %s, draft_version = %s where id = any(%s)",
           by["id"], vid, [r["id"] for r in rows])
    audit.log(cur, by["name"], "proposals_drafted", "icp_version", vid, {"proposals": [r["id"] for r in rows]}, actor_id=by["id"])
    return vid


def dismiss(cur, proposal_id: int, by: dict, reason: str) -> None:
    if by["role"] not in ("revops", "manager"):
        raise PermissionError("RevOps or a manager dismisses a proposal.")
    if not reason or len(reason.strip()) < 3:
        raise ValueError("Say why it is dismissed.")
    n = db.run(cur, """update change_proposals set status = 'dismissed', decided_by = %s, reason = %s
                       where id = %s and status = 'open'""", by["id"], reason.strip(), proposal_id)
    if not n:
        raise ValueError("Only an open proposal can be dismissed.")
    audit.log(cur, by["name"], "proposal_dismissed", "proposal", proposal_id, {"reason": reason.strip()}, actor_id=by["id"])
