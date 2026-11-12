"""What each page and sheet reads. Every function takes the cursor and returns plain data; money keys are left out for
roles that may not see company money (docs/SPEC.md 3)."""
from __future__ import annotations

from .. import catalog as C
from .. import db, fit, handoff, profiles, tests_seg
from .. import territories as terr
from ..evidence import rule_label

VERDICT = {"clear_higher": "Clearly higher", "clear_lower": "Clearly lower", "not_clear": "Not clear",
           "too_few": "Too few to tell", "explained_by_size": "Explained by size"}
MONEY_KEYS = {"tam_low", "tam_high", "sam_low", "sam_high", "som_low", "som_high", "acv_median", "acv_p25", "acv_p75",
              "acv_basis", "expected_value_cents", "pipeline_cents", "price_cents_per_unit", "spend_cents", "amount_cents",
              "arr_cents", "ev", "ev_mean", "pipeline"}


def strip(obj, allowed: bool):
    if allowed:
        return obj
    if isinstance(obj, dict):
        return {k: strip(v, allowed) for k, v in obj.items() if k not in MONEY_KEYS}
    if isinstance(obj, list):
        return [strip(x, allowed) for x in obj]
    return obj


def _published(cur) -> dict:
    return db.one(cur, "select * from icp_versions where status = 'published'")


def _active_plan(cur) -> int | None:
    return db.val(cur, "select id from territory_plans where status = 'active'")


def _label(dim: str, key: str) -> str:
    return C.SEGMENT_LABEL.get(key, key) if dim == "segment" else key


# ---------------------------------------------------------------- Market

def market(cur, by: str, allowed: bool) -> dict:
    run = db.val(cur, "select max(id) from sizing_runs")
    rows = db.all(cur, "select * from segment_sizing where run = %s and dimension = %s", run, by)
    total = db.one(cur, "select * from segment_sizing where run = %s and dimension = 'total'", run)
    ev_run = db.val(cur, "select max(id) from analysis_runs")
    wr = {r["value"]: r for r in db.all(cur, "select value, opps, wins, wr_low, wr_high, win_rate from findings where run = %s and trait = %s",
                                        ev_run, "segment" if by == "segment" else "region")}
    plan = _active_plan(cur)
    owned = {r["k"]: r["n"] for r in db.all(cur, f"""
        select {'f.segment' if by == 'segment' else 'c.region_group'} as k, count(*) as n from assignments a
        join companies c on c.id = a.company join account_fit f on f.company = c.id
          and f.icp_version = (select id from icp_versions where status = 'published')
        where a.plan = %s and f.tier in ('A','B') group by 1""", plan)}
    order = [s["key"] for s in C.SEGMENTS] + ["outside"]
    stories = {r["segment"]: r["status"] for r in db.all(cur, """select distinct on (segment) segment, status from segment_stories
                                                              order by segment, drafted_at desc""")}
    out = []
    for r in rows:
        f = wr.get(r["key"]) if by == "segment" else None
        out.append({**{k: r[k] for k in ("key", "universe_count", "fit_a", "fit_b", "fit_c", "fit_x", "not_judged",
                                         "public_count", "coverage_share", "reachable_count", "sam_count", "tam_low",
                                         "tam_high", "sam_low", "sam_high", "som_low", "som_high")},
                    "label": _label(by, r["key"]), "owned": owned.get(r["key"], 0), "story": stories.get(r["key"]),
                    "win_rate": f and {"rate": f["win_rate"], "low": f["wr_low"], "high": f["wr_high"], "opps": f["opps"]}})
    if by == "segment":
        out.sort(key=lambda x: order.index(x["key"]) if x["key"] in order else 99)
    else:
        out.sort(key=lambda x: -x["universe_count"])
    figs = {"companies": total["universe_count"], "in_profile": total["fit_a"] + total["fit_b"],
            "reachable": total["sam_count"], "som_low": total["som_low"], "som_high": total["som_high"]}
    return strip({"by": by, "rows": out, "figures": figs}, allowed)


def segment(cur, key: str, allowed: bool) -> dict | None:
    if key not in C.SEGMENT_LABEL:
        return None
    run = db.val(cur, "select max(id) from sizing_runs")
    sz = db.one(cur, "select * from segment_sizing where run = %s and dimension = 'segment' and key = %s", run, key)
    ev_run = db.val(cur, "select max(id) from analysis_runs")
    f = db.one(cur, "select * from findings where run = %s and trait = 'segment' and value = %s", ev_run, db.J(key))
    roles = db.all(cur, "select * from segment_roles where segment = %s order by share_of_won_deals desc", key)
    story = db.one(cur, "select * from segment_stories where segment = %s order by drafted_at desc limit 1", key)
    quotes = db.all(cur, """select min(id) as id, kind, text, count(*) as n from quotes where segment = %s
                            group by kind, text order by count(*) desc, text limit 9""", key)
    losses = None
    if f:
        losses = f["top_loss_codes"]
    definition = next((s["when"] for s in C.SEGMENTS if s["key"] == key), [])
    pub = _published(cur)
    coverage = db.all(cur, """
        select x.field, round(avg(x.known::int)::numeric, 3) as filled from (
          select c.id, 'industry' as field, c.industry is not null as known from companies c join account_fit f on f.company = c.id and f.icp_version = %s where f.segment = %s
          union all select c.id, 'pricing_model', c.pricing_model <> 'unknown' from companies c join account_fit f on f.company = c.id and f.icp_version = %s where f.segment = %s
          union all select c.id, 'tech', cardinality(c.tech) > 0 from companies c join account_fit f on f.company = c.id and f.icp_version = %s where f.segment = %s
        ) x group by x.field order by x.field""", pub["id"], key, pub["id"], key, pub["id"], key)
    tests = db.all(cur, "select id, status, started_on, ends_on, decision from segment_tests where segment = %s order by id", key)
    story_out = None
    if story:
        body = story["sentences"] or {}
        quotes_by_id = {q["id"]: q for q in (body.get("payload") or {}).get("quotes", [])}
        story_out = {"status": story["status"], "sentences": body.get("sentences"),
                     "quotes": quotes_by_id, "figures": (body.get("payload") or {}).get("figures", [])}
    return strip({"key": key, "label": C.SEGMENT_LABEL[key], "definition": [rule_label(w) for w in definition],
                  "sizing": (sz and {k: v for k, v in sz.items() if k not in ("run",)}) if allowed else None,
                  "finding": f and finding_row(f),
                  "roles": [{"persona": C.PERSONAS[r["persona"]], "share": r["share_of_won_deals"],
                             "signer": r["share_as_signer"], "n": r["n_won_deals"]} for r in roles],
                  "story": story_out, "quotes": quotes, "losses": losses, "coverage": coverage, "tests": tests}, allowed)


# ---------------------------------------------------------------- Evidence

def finding_row(f: dict) -> dict:
    return {"id": f["id"], "trait": f["trait"], "trait_label": C.FIELD_LABEL.get(f["trait"], "Rule" if f["trait"] == "rule" else f["trait"]),
            "value": f["value_label"], "opps": f["opps"], "wins": f["wins"], "rate": f["win_rate"], "low": f["wr_low"],
            "high": f["wr_high"], "rest_opps": f["rest_opps"], "rest_rate": (f["rest_wins"] / f["rest_opps"]) if f["rest_opps"] else None,
            "verdict": f["verdict"], "verdict_label": VERDICT[f["verdict"]],
            "cycle": f["cycle_median_days"] and {"median": f["cycle_median_days"], "low": f["cycle_low"], "high": f["cycle_high"]},
            "cycle_n": f["cycle_n"], "acv_median": f["acv_median"], "acv_p25": f["acv_p25"], "acv_p75": f["acv_p75"],
            "churn": f["churn_rate_12m"], "churn_n": f["churn_n"], "losses": f["top_loss_codes"]}


def evidence(cur, allowed: bool) -> dict:
    run = db.one(cur, "select * from analysis_runs order by id desc limit 1")
    rows = db.all(cur, """select * from findings where run = %s order by case verdict when 'clear_higher' then 0
                          when 'clear_lower' then 1 when 'explained_by_size' then 2 when 'not_clear' then 3 else 4 end,
                          opps desc""", run["id"])
    prev = db.val(cur, "select max(id) from analysis_runs where id < %s", run["id"])
    changes = []
    if prev:
        changes = db.all(cur, """select f.id, f.trait, f.value_label, f.verdict, p.verdict as was from findings f
                                 left join findings p on p.run = %s and p.trait = f.trait and p.value = f.value
                                 where f.run = %s and (p.id is null or p.verdict <> f.verdict)""", prev, run["id"])
    return strip({"run": {"id": run["id"], "ran_at": run["ran_at"], "deals": run["deals_considered"],
                          "tested": run["tests_run"], "window_start": run["window_start"], "window_end": run["window_end"]},
                  "rows": [finding_row(f) for f in rows], "changes": changes,
                  "traits": sorted({(r["trait"], C.FIELD_LABEL.get(r["trait"], "Rule")) for r in rows})}, allowed)


def finding(cur, fid: int, allowed: bool) -> dict | None:
    f = db.one(cur, "select * from findings where id = %s", fid)
    if not f:
        return None
    run = db.one(cur, "select * from analysis_runs where id = %s", f["run"])
    strata = db.all(cur, "select * from finding_strata where finding = %s", fid)
    order = [b[0] for b in C.SIZE_BANDS]
    strata.sort(key=lambda s: order.index(s["size_band"]))
    deals = db.all(cur, """select d.id, d.outcome, d.created_at, d.closed_at, d.amount_cents, d.loss_code, d.competitor,
                           d.source, c.id as company, c.name, c.primary_domain, d.snapshot
                           from deals d join companies c on c.id = d.company
                           where d.kind = 'new' and d.outcome in ('won','lost') and d.closed_at between %s and %s
                           order by d.closed_at desc""", run["window_start"], run["window_end"])
    from ..evidence import deal_traits, published_rules
    rules = {r["key"]: r for r in published_rules(cur)}
    picked = []
    for d in deals:
        if f["trait"] == "rule":
            r = rules.get(f["value"])
            snap = {**d["snapshot"], "segment": fit.segment_of({"segments": C.SEGMENTS}, d["snapshot"])}
            ok = bool(r and fit.matches(r, snap))
        else:
            ok = any(t == f["trait"] and v == f["value"] for t, _label, v in deal_traits(d["snapshot"], d["source"]))
        if ok:
            picked.append({k: d[k] for k in ("id", "outcome", "created_at", "closed_at", "amount_cents", "loss_code",
                                             "competitor", "company", "name", "primary_domain")})
    return strip({**finding_row(f), "segment_key": f["value"] if f["trait"] == "segment" else None,
                  "strata": strata, "deals": picked[:200], "deal_count": len(picked),
                  "loss_labels": C.LOSS_LABEL}, allowed)


# ---------------------------------------------------------------- Profile

def _rules_view(cur, rules: dict) -> list[dict]:
    out = []
    for kind, r in profiles.all_rules(rules):
        ev = (r.get("evidence") or {}).get("finding_id")
        f = db.one(cur, "select * from findings where id = %s", ev) if ev else None
        out.append({"kind": kind, "key": r["key"], "label": rule_label(r), "weight": r.get("weight"),
                    "reason": r.get("reason"), "finding": f and finding_row(f), "hypothesis": f is None,
                    "travels": r["field"] in C.AD_FIELDS})
    return out


def profile(cur, u: dict) -> dict:
    pub = _published(cur)
    versions = db.all(cur, """select v.id, v.number, v.status, v.note, v.created_at, v.published_at, a.name as author,
                              p.name as published_by, v.author as author_id from icp_versions v join users a on a.id = v.author
                              left join users p on p.id = v.published_by order by v.number desc""")
    drafts = [v for v in versions if v["status"] == "draft"]
    return {"published": {"id": pub["id"], "number": pub["number"], "tiers": pub["rules"]["tiers"],
                          "rules": _rules_view(cur, pub["rules"]), "published_at": pub["published_at"]},
            "drafts": [{**d, "can_publish": u["role"] == "manager" and d["author_id"] != u["id"]} for d in drafts],
            "versions": versions,
            "job": db.one(cur, "select status, count(*) as n from jobs where kind = 'rescore_batch' and status <> 'done' group by status limit 1")}


def version(cur, vid: int, u: dict) -> dict | None:
    v = db.one(cur, """select v.*, a.name as author_name, p.name as publisher from icp_versions v join users a on a.id = v.author
                       left join users p on p.id = v.published_by where v.id = %s""", vid)
    if not v:
        return None
    prev = db.one(cur, "select rules from icp_versions where number = %s", v["number"] - 1)
    diff = []
    if prev:
        old = {(k, r["key"]): rule_label(r) for k, r in profiles.all_rules(prev["rules"])}
        new = {(k, r["key"]): rule_label(r) for k, r in profiles.all_rules(v["rules"])}
        for key, label in new.items():
            if key not in old:
                diff.append({"change": "Added", "kind": key[0], "rule": label})
            elif old[key] != label:
                diff.append({"change": "Changed", "kind": key[0], "rule": label, "was": old[key]})
        for key, label in old.items():
            if key not in new:
                diff.append({"change": "Removed", "kind": key[0], "rule": label})
        oldw = {r["key"]: r.get("weight") for _k, r in profiles.all_rules(prev["rules"])}
        for k, r in profiles.all_rules(v["rules"]):
            if r["key"] in oldw and oldw[r["key"]] != r.get("weight") and r.get("weight") is not None:
                diff.append({"change": "Reweighted", "kind": k, "rule": rule_label(r), "was": str(oldw[r["key"]])})
    return {"id": v["id"], "number": v["number"], "status": v["status"], "note": v["note"], "author": v["author_name"],
            "publisher": v["publisher"], "created_at": v["created_at"], "published_at": v["published_at"],
            "tiers": v["rules"]["tiers"], "rules": _rules_view(cur, v["rules"]), "diff": diff,
            "can_publish": v["status"] == "draft" and u["role"] == "manager" and v["author"] != u["id"],
            "is_author": v["author"] == u["id"],
            "dropped": handoff.compile_for_account_desk(v["rules"])[1]}


# ---------------------------------------------------------------- Accounts and companies

PAGE = 50


def accounts(cur, u: dict, *, q: str, tier: str, segment: str, owner: str, page: int, region: str = "") -> dict:
    pub = _published(cur)
    plan = _active_plan(cur)
    where = ["c.lifecycle <> 'competitor'", "not c.sole_trader"]
    args: list = []
    if owner == "unassigned":
        where.append("a.owner is null")
    elif owner.isdigit():
        where.append("a.owner = %s")
        args.append(int(owner))
    if q:
        where.append("(c.name ilike %s or c.primary_domain ilike %s)")
        args += [f"%{q}%", f"%{q}%"]
    if tier == "NJ":
        where.append("not f.judged")
    elif tier in ("A", "B", "C", "X"):
        where.append("f.tier = %s and f.judged")
        args.append(tier)
    if segment in C.SEGMENT_LABEL:
        where.append("f.segment = %s")
        args.append(segment)
    if region in C.REGION_GROUPS:
        where.append("c.region_group = %s")
        args.append(region)
    sql = f"""
        from companies c join account_fit f on f.company = c.id and f.icp_version = %s
        left join assignments a on a.company = c.id and a.plan = %s left join users u on u.id = a.owner
        where {' and '.join(where)}"""
    total = db.val(cur, "select count(*) " + sql, pub["id"], plan, *args)
    rows = db.all(cur, """select c.id, c.name, c.primary_domain, c.lifecycle, c.employees, c.region_group, c.region,
                          coalesce(c.industry, (select v.value #>> '{}' from field_values v where v.company = c.id
                                                and v.field = 'industry' and v.source = 'model' limit 1)) as industry,
                          f.tier, f.judged, f.score, f.scored_out_of, f.segment, u.name as owner, a.reason_code,
                          (select r.meetings from desk_results r where r.company = c.id order by r.period_end desc limit 1) as last_meetings,
                          (select r.destination from desk_results r where r.company = c.id order by r.period_end desc limit 1) as last_dest
                          """ + sql + " order by f.judged desc, f.score desc nulls last, c.name limit %s offset %s",
                   pub["id"], plan, *args, PAGE, (page - 1) * PAGE)
    for r in rows:
        r["segment_label"] = C.SEGMENT_LABEL.get(r["segment"], r["segment"])
        # A tier A prospect in our regions that nobody has hours for (SPEC 7: shown, never demoted).
        r["over_capacity"] = (r["tier"] == "A" and r["judged"] and r["lifecycle"] == "prospect" and not r["owner"]
                              and r["region"] in C.SERVED_REGIONS)
    owners = db.all(cur, "select id, name from users where role in ('sdr','ae') and active order by name")
    return {"rows": rows, "total": total, "page": page, "pages": max(1, -(-total // PAGE)), "owners": owners,
            "segments": [{"key": s["key"], "label": s["label"]} for s in C.SEGMENTS] + [C.OUTSIDE]}


def company(cur, cid: int, u: dict, allowed: bool | None = None) -> dict | None:
    # A sole trader is a person, not a company: never shown (docs/SPEC.md 13).
    c = db.one(cur, "select * from companies where id = %s and not sole_trader", cid)
    if not c:
        return None
    plan = _active_plan(cur)
    a = db.one(cur, """select a.*, u.name as owner_name, m.name as moved_from_name from assignments a left join users u on u.id = a.owner
                       left join users m on m.id = a.moved_from where a.plan = %s and a.company = %s""", plan, cid)
    if allowed is None:
        allowed = u["role"] in ("revops", "manager")
    fields = db.all(cur, """select f.field, f.value, f.source, s.label as source_label, f.observed_at, f.confidence, f.quote
                            from field_values f join sources s on s.key = f.source where f.company = %s order by f.field, f.observed_at desc""", cid)
    history = db.all(cur, """select v.number, v.status, f.tier, f.judged, f.score from account_fit f join icp_versions v on v.id = f.icp_version
                             where f.company = %s order by v.number""", cid)
    pub = _published(cur)
    cur_fit = db.one(cur, "select * from account_fit where company = %s and icp_version = %s", cid, pub["id"])
    labels = {r["key"]: rule_label(r) for _k, r in profiles.all_rules(pub["rules"])}
    deals = db.all(cur, """select id, kind, outcome, created_at, closed_at, amount_cents, loss_code, competitor, stage
                           from deals where company = %s order by created_at desc""", cid)
    results = db.all(cur, """select destination, period_start, period_end, worked, meetings, opportunities, won, lost,
                             pipeline_cents, read_at from desk_results where company = %s order by period_end desc""", cid)
    tests = db.all(cur, """select t.id, t.segment, t.status, m.grp from segment_test_members m join segment_tests t on t.id = m.test
                           where m.company = %s""", cid)
    if not allowed:
        results = [r for r in results if r["worked"]]
        for t in tests:
            if t["status"] == "running":
                t["grp"] = None
    for t in tests:
        t["segment_label"] = C.SEGMENT_LABEL.get(t["segment"], t["segment"])
    breakdown = cur_fit["breakdown"] if cur_fit else {}
    for f in breakdown.get("factors", []):
        f["label"] = labels.get(f["key"], f["key"])
    for f in breakdown.get("not_applied", []):
        f["label"] = labels.get(f.get("key"), f.get("reason"))
    from ..crm import world_id
    return strip({"id": c["id"], "name": c["name"], "domain": c["primary_domain"], "world_id": world_id(c["primary_domain"]),
                  "lifecycle": c["lifecycle"],
                  "industry": c["industry"], "employees": c["employees"], "country": C.COUNTRY_NAME.get(c["country"], c["country"]),
                  "region_group": c["region_group"], "revenue_band": c["revenue_band"], "pricing_model": c["pricing_model"],
                  "tech": c["tech"], "description": c["description"], "sole_trader": c["sole_trader"],
                  "fields": fields, "fit": cur_fit and {"score": cur_fit["score"], "tier": cur_fit["tier"], "judged": cur_fit["judged"],
                                                        "scored_out_of": cur_fit["scored_out_of"], "excluded": cur_fit["excluded"],
                                                        "segment": cur_fit["segment"], "segment_label": C.SEGMENT_LABEL.get(cur_fit["segment"]),
                                                        "breakdown": breakdown, "version": pub["number"]},
                  "history": history, "owner": a and {"name": a["owner_name"], "id": a["owner"], "reason": a["reason_code"],
                                                      "note": a["note"], "moved_from": a["moved_from_name"]},
                  "deals": deals, "results": results, "tests": tests}, allowed)


def raise_forbidden():
    from fastapi import HTTPException
    raise HTTPException(403, "This account is not in your book.")


# ---------------------------------------------------------------- Territories and capacity

def territories(cur, plan_id: int | None, allowed: bool) -> dict:
    plans = db.all(cur, """select p.id, p.name, p.status, p.created_at, p.activated_at, a.name as author, x.name as activated_by,
                           p.author as author_id, p.balance_report from territory_plans p join users a on a.id = p.author
                           left join users x on x.id = p.activated_by order by case p.status when 'active' then 0 when 'draft' then 1 else 2 end, p.id desc""")
    plan_id = plan_id or (plans[0]["id"] if plans else None)
    plan = next((p for p in plans if p["id"] == plan_id), None)
    if not plan:
        return {"plans": plans, "plan": None}
    people = db.all(cur, """select s.*, u.name, u.role, u.started_on, u.ramp_months, u.selling_hours_month from capacity_snapshots s
                            join users u on u.id = s.user_id where s.plan = %s order by u.role desc, u.name""", plan_id)
    terrs = db.all(cur, """select t.id, t.key, t.label, t.rule, u.name as ae, t.paired_ae as paired_ae_id from territories t left join users u on u.id = t.paired_ae
                           where t.plan = %s order by t.id""", plan_id)
    names = {u["id"]: u["name"] for u in db.all(cur, "select id, name from users")}
    evs = {p["user_id"]: p["expected_value_cents"] for p in people}
    for t in terrs:
        t["people"] = [{"id": i, "name": names[i]} for i in t["rule"]["people"]]
        t["region_groups"] = t["rule"]["region_groups"]
        t["segments"] = [C.SEGMENT_LABEL[s] for s in t["rule"]["segments"]]
        vals = [evs.get(i, 0) for i in t["rule"]["people"]]
        t["ev_mean"] = sum(vals) / len(vals) if vals else 0
        t["accounts"] = db.val(cur, "select count(*) from assignments where territory = %s", t["id"])
        t["balance"] = (plan["balance_report"] or {}).get(t["key"])
    for p in people:
        p["ev"] = p.pop("expected_value_cents")
        t = next((t for t in terrs if p["user_id"] in t["rule"]["people"]), None) or \
            next((t for t in terrs if t.get("paired_ae_id") == p["user_id"]), None)
        p["territory"] = t["label"] if t else None
        p["ev_mean"] = t["ev_mean"] if t else None
    gap = terr.hiring_gap(cur, plan_id)
    ch = terr.what_changes(cur, plan_id) if plan["status"] == "draft" else None
    manual = db.all(cur, """select a.company, c.name, a.note, u.name as owner, m.name as moved_from from assignments a
                            join companies c on c.id = a.company left join users u on u.id = a.owner left join users m on m.id = a.moved_from
                            where a.plan = %s and a.reason_code = 'manual'""", plan_id)
    s = {r["key"]: r for r in db.all(cur, "select key, value, note from settings")}
    pub = _published(cur)
    a_cap = db.one(cur, """select sum((s.accounts_by_tier->>'A')::int) as held from capacity_snapshots s where s.plan = %s""", plan_id)
    a_total = db.val(cur, """select count(*) from account_fit f join companies c on c.id = f.company where f.icp_version = %s
                             and f.tier = 'A' and f.judged and c.lifecycle = 'prospect' and c.region = any(%s)""", pub["id"], C.SERVED_REGIONS)
    if ch:
        people_ids = sorted(set(ch["gains"]) | set(ch["losses"]), key=lambda k: names[k])
        ch = {"changes": ch["changes"], "crossing": len(ch["crossing"]),
              "people": [{"name": names[k], "gains": ch["gains"].get(k, 0), "losses": ch["losses"].get(k, 0)} for k in people_ids]}
    return strip({"plans": plans, "plan": plan, "people": people, "territories": terrs, "gap": gap, "changes": ch,
                  "manual": manual, "hours_per_tier": s["hours_per_tier"]["value"], "hours_note": s["hours_per_tier"]["note"],
                  "a_capacity": {"held": a_cap["held"] or 0, "tier_a": a_total}}, allowed)


def person(cur, uid: int, allowed: bool) -> dict | None:
    u = db.one(cur, "select id, name, role, started_on, ramp_months, selling_hours_month, timezone from users where id = %s", uid)
    if not u:
        return None
    plan = _active_plan(cur)
    snap = db.one(cur, "select * from capacity_snapshots where plan = %s and user_id = %s", plan, uid)
    pub = _published(cur)
    book = db.all(cur, """select c.id, c.name, c.primary_domain, f.tier, f.score, f.segment, a.reason_code from assignments a
                          join companies c on c.id = a.company join account_fit f on f.company = c.id and f.icp_version = %s
                          where a.plan = %s and a.owner = %s order by f.tier, f.score desc nulls last limit 300""", pub["id"], plan, uid)
    for b in book:
        b["segment_label"] = C.SEGMENT_LABEL.get(b["segment"])
    fte = snap["effective_fte"] if snap else None
    return strip({**u, "capacity": snap and {"hours_available": snap["hours_available"], "hours_required": snap["hours_required"],
                                             "fte": fte, "by_tier": snap["accounts_by_tier"], "ev": snap["expected_value_cents"]},
                  "book": book}, allowed)


def plan_move(cur, plan_id: int, cid: int) -> dict | None:
    a = db.one(cur, """select a.*, c.name, u.name as owner_name, m.name as moved_from_name, x.name as by_name, t.label as territory_label,
                       p.name as plan_name from assignments a join companies c on c.id = a.company join territory_plans p on p.id = a.plan
                       left join users u on u.id = a.owner left join users m on m.id = a.moved_from left join users x on x.id = a.created_by
                       left join territories t on t.id = a.territory where a.plan = %s and a.company = %s""", plan_id, cid)
    return a


# ---------------------------------------------------------------- Tests

def _test_row(cur, t: dict) -> dict:
    rep = tests_seg.read(cur, t["id"])
    eligible = len(tests_seg.eligible(cur, t["segment"], exclude_test=t["id"])) if t["status"] == "draft" else None
    return {**t, "segment_label": C.SEGMENT_LABEL.get(t["segment"]), "report": rep, "eligible": eligible,
            "members": db.val(cur, "select count(*) from segment_test_members where test = %s", t["id"])}


def tests(cur) -> dict:
    rows = db.all(cur, """select t.*, u.name as decided_by_name from segment_tests t left join users u on u.id = t.decided_by
                          order by case t.status when 'running' then 0 when 'draft' then 1 else 2 end, t.id desc""")
    pub = _published(cur)
    elig = {r["segment"]: r["n"] for r in db.all(cur, """
        select f.segment, count(*) as n from account_fit f join companies c on c.id = f.company
        where f.icp_version = %s and f.tier in ('A','B') and f.judged and c.lifecycle = 'prospect' and not c.sole_trader
          and c.region in ('North America', 'Europe') and not exists (select 1 from segment_test_members m join segment_tests t on t.id = m.test
                          where m.company = c.id and t.status in ('running','read'))
          and not exists (select 1 from target_book_rows r join target_books b on b.id = r.book
                          where r.company = c.id and b.destination = 'account_desk' and b.created_at > app_now() - interval '180 days')
        group by f.segment""", pub["id"])}
    return {"rows": [_test_row(cur, t) for t in rows], "cohort": tests_seg.default_cohort(),
            "segments": [{"key": s["key"], "label": s["label"], "eligible": elig.get(s["key"], 0)} for s in C.SEGMENTS]}


def test(cur, tid: int) -> dict | None:
    t = db.one(cur, """select t.*, u.name as decided_by_name, c.name as created_by_name from segment_tests t
                       left join users u on u.id = t.decided_by left join users c on c.id = t.created_by where t.id = %s""", tid)
    if not t:
        return None
    out = _test_row(cur, t)
    out["sample"] = db.all(cur, """select c.id, c.name, c.primary_domain, m.grp, coalesce(sum(r.meetings), 0) as meetings
                                   from segment_test_members m join companies c on c.id = m.company
                                   left join desk_results r on r.company = c.id and r.test = m.test where m.test = %s
                                   group by c.id, c.name, c.primary_domain, m.grp order by m.grp desc, c.name limit 40""", tid)
    out["refused"] = db.all(cur, """select l.at, l.object_id, c.name from audit_log l left join companies c on c.id::text = l.object_id
                                    where l.action = 'book_row_refused' and exists (select 1 from segment_test_members m
                                    where m.test = %s and m.company::text = l.object_id)""", tid)
    return out


# ---------------------------------------------------------------- Changes

def _proposal_row(cur, p: dict) -> dict:
    payload = (p["evidence"] or {}).get("payload") or {}
    ch = payload.get("change") or {}
    return {"id": p["id"], "kind": p["kind"], "status": p["status"], "created_at": p["created_at"],
            "change": ch, "findings": payload.get("findings", []), "sentences": p["text_sentences"],
            "text_status": p["text_status"], "reason": p["reason"], "decided_by": p.get("decided_by_name"),
            "draft_number": p.get("draft_number"), "draft_version": p.get("draft_version"), "finding_ids": p["evidence"].get("finding_ids", []),
            "test_ids": p["evidence"].get("test_ids", []), "diff": p["proposed_rules_diff"]}


def changes(cur) -> dict:
    rows = db.all(cur, """select p.*, u.name as decided_by_name, v.number as draft_number from change_proposals p
                          left join users u on u.id = p.decided_by left join icp_versions v on v.id = p.draft_version
                          order by case p.status when 'open' then 0 else 1 end, p.id""")
    return {"open": [_proposal_row(cur, p) for p in rows if p["status"] == "open"],
            "decided": [_proposal_row(cur, p) for p in rows if p["status"] != "open"]}


def proposal(cur, pid: int) -> dict | None:
    p = db.one(cur, """select p.*, u.name as decided_by_name, v.number as draft_number from change_proposals p
                       left join users u on u.id = p.decided_by left join icp_versions v on v.id = p.draft_version where p.id = %s""", pid)
    return p and _proposal_row(cur, p)


# ---------------------------------------------------------------- Handoffs

def handoffs(cur, allowed: bool) -> dict:
    books = db.all(cur, """select b.id, b.version, b.destination, b.created_at, b.rows, b.dropped_rules, b.diff, v.number as icp_number,
                           p.name as plan_name, u.name as created_by from target_books b join icp_versions v on v.id = b.icp_version
                           join territory_plans p on p.id = b.plan left join users u on u.id = b.created_by order by b.created_at desc""")
    for b in books:
        b["files"] = [r["path"] for r in db.all(cur, "select path from target_book_files where book = %s order by path", b["id"])]
        b["results"] = db.one(cur, """select count(*) as accounts, coalesce(sum(r.meetings), 0) as meetings,
                                      coalesce(sum(r.opportunities), 0) as opportunities, coalesce(sum(r.won), 0) as won,
                                      coalesce(sum(r.pipeline_cents), 0) as pipeline_cents
                                      from desk_results r where r.destination = %s and r.test is null and r.company in
                                      (select company from target_book_rows where book = %s)
                                      and r.period_start >= %s::date and r.period_start < coalesce((select min(n.created_at)
                                        from target_books n where n.destination = %s and n.created_at > %s), 'infinity')::date""",
                                   b["destination"], b["id"], b["created_at"], b["destination"], b["created_at"])
    events = db.one(cur, """select count(*) as accounts, coalesce(sum(meetings), 0) as meetings, coalesce(sum(opportunities), 0) as opportunities
                            from desk_results where destination = 'events_desk'""")
    drafts = db.all(cur, "select id, number from icp_versions where status = 'draft' order by number")
    previews = [handoff.preview(cur, d["id"]) | {"id": d["id"]} for d in drafts]
    return strip({"books": books, "events": events, "previews": previews, "crm": crm_desk(cur)}, allowed)


def crm_desk(cur) -> dict | None:
    """What went to CRM Desk and what it refused. None when no CRM is set and nothing was ever sent (the desk alone)."""
    from .. import crm
    s = crm.summary(cur)
    if not s["enabled"] and not s["sent"] and not s["queued"]:
        return None
    for r in s["refusals"]:
        c = db.one(cur, "select id, name from companies where primary_domain = %s", r["domain"])
        r["company"], r["name"] = (c["id"], c["name"]) if c else (None, r["domain"])
        r["proposed_name"] = db.val(cur, "select name from users where email = %s", r["proposed"]) or r["proposed"]
        r["what"] = {"sdr_owner_id": "SDR", "owner_id": "Owner"}.get(r["field"], r["field"])
        r["why"] = {"owner_pinned": "A manager pinned it in CRM Desk",
                    "kept_value_a_person_entered": "Someone in CRM Desk entered a different value"}.get(r["reason"], "CRM Desk kept its own value")
    for e in s["errors"]:
        c = db.one(cur, "select id, name from companies where primary_domain = %s", e["domain"])
        e["company"], e["name"] = (c["id"], c["name"]) if c else (None, e["domain"])
    return s


def book(cur, bid: int, allowed: bool) -> dict | None:
    b = db.one(cur, """select b.*, v.number as icp_number, p.name as plan_name from target_books b join icp_versions v on v.id = b.icp_version
                       join territory_plans p on p.id = b.plan where b.id = %s""", bid)
    if not b:
        return None
    files = db.all(cur, "select path, length(bytes) as size from target_book_files where book = %s order by path", bid)
    rows = db.all(cur, """select r.company, c.name, c.primary_domain, r.tier, r.segment, r.test_member, u.name as owner
                          from target_book_rows r join companies c on c.id = r.company left join users u on u.id = r.owner
                          where r.book = %s order by r.tier, c.name limit 100""", bid)
    for r in rows:
        r["segment_label"] = C.SEGMENT_LABEL.get(r["segment"])
    md = None
    if b["destination"] == "events_desk":
        md = bytes(db.val(cur, "select bytes from target_book_files where book = %s and path = 'icp.md'", bid)).decode()
    return strip({**{k: b[k] for k in ("id", "version", "destination", "created_at", "rows", "dropped_rules", "diff", "icp_number",
                                       "plan_name", "file_sha256")}, "files": files, "sample": rows, "markdown": md}, allowed)


# ---------------------------------------------------------------- Sources, Settings

def sources(cur, allowed: bool) -> dict:
    rows = db.all(cur, """
        select s.*, r.finished_at as last_run, r.rows_read, r.rows_changed,
               s.cadence_hours, (r.finished_at < app_now() - make_interval(hours => s.cadence_hours)) as stale
        from sources s left join lateral (select * from source_runs x where x.source = s.key order by finished_at desc nulls last limit 1) r on true
        order by s.kind, s.label""")
    fill = {}
    for r in db.all(cur, """select f.source, f.field, count(distinct f.company) as n from field_values f group by f.source, f.field"""):
        fill.setdefault(r["source"], []).append({"field": C.FIELD_LABEL.get(r["field"], r["field"]), "n": r["n"]})
    total = db.val(cur, "select count(*) from companies")
    for r in rows:
        r["fill"] = [{**f, "share": f["n"] / total} for f in fill.get(r["key"], [])]
        r["spend_cents"] = round(float(r["price_cents_per_unit"] or 0) * (r["rows_read"] or 0)) if r["paid"] else 0
    alerts = db.all(cur, "select * from alerts where resolved_at is null order by at desc")
    return strip({"rows": rows, "alerts": alerts, "companies": total}, allowed)


def source(cur, key: str, allowed: bool) -> dict | None:
    s = db.one(cur, "select * from sources where key = %s", key)
    if not s:
        return None
    runs = db.all(cur, "select * from source_runs where source = %s order by started_at desc limit 10", key)
    return strip({**s, "runs": runs}, allowed)




def settings(cur) -> dict:
    rows = db.all(cur, "select key, value, note, updated_at from settings order by key")
    team = db.all(cur, "select id, name, role, started_on, ramp_months, selling_hours_month, active from users order by role, name")
    return {"settings": rows, "team": team}

