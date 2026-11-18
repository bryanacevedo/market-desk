"""What each page and sheet reads. Every function takes the cursor and returns plain data; money keys are left out for
roles that may not see company money (docs/SPEC.md 3)."""
from __future__ import annotations

from .. import catalog as C
from .. import crm, db, fit, handoff, names, profiles, proposals, tests_seg
from .. import territories as terr
from ..evidence import rule_label
from ..names import say as _say

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


CUSTOMER_REASONS = {"existing_owner", "customer_team", "open_deal"}


def _plain_dropped(rows):
    return [{**d, "why": names.say(d["why"])} for d in rows or []]


def owner_source(reason: str | None) -> str:
    """Where an owner comes from (decision 66): the plan for a prospect, customer records for a customer or an open deal."""
    if reason == "manual":
        return "a hand change"
    return names.desk_names()["crm_desk"] if reason in CUSTOMER_REASONS else "the territory plan"


def _seat(role: str | None) -> str | None:
    return {"sdr": "SDR", "ae": "AE"}.get(role or "")


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
                                 where f.run = %s and (p.id is null or p.verdict <> f.verdict) order by f.id""", prev, run["id"])
    took = db.val(cur, """select (detail->>'seconds')::numeric from audit_log where action = 'evidence_run' and object_id = %s::text
                          order by id desc limit 1""", run["id"])
    return strip({"run": {"id": run["id"], "ran_at": run["ran_at"], "deals": run["deals_considered"], "seconds": took and float(took),
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
    for v in versions:
        v["note"] = names.say(v["note"])
    drafts = [v for v in versions if v["status"] == "draft"]
    return {"published": {"id": pub["id"], "number": pub["number"], "tiers": pub["rules"]["tiers"],
                          "rules": _rules_view(cur, pub["rules"]), "published_at": pub["restored_at"] or pub["published_at"]},
            "drafts": [{**d, "can_publish": u["role"] == "manager" and d["author_id"] != u["id"]} for d in drafts],
            "versions": versions, "history": history(cur, ("profile_published", "profile_rolled_back")),
            "can_roll_back": u["role"] == "manager" and profiles.rollback_target(cur) is not None,
            "job": db.one(cur, "select status, count(*) as n from jobs where kind = 'rescore_batch' and status <> 'done' group by status limit 1")}


def history(cur, actions: tuple[str, ...]) -> list[dict]:
    """Who changed what and when, from the audit log, newest first."""
    rows = db.all(cur, """select at, actor, action, object_id, detail from audit_log where action = any(%s)
                          order by id desc limit 12""", list(actions))
    out = []
    for r in rows:
        d = r["detail"] or {}
        if r["action"] == "profile_published":
            n = db.val(cur, "select number from icp_versions where id = %s", int(r["object_id"]))
            out.append({"at": r["at"], "who": r["actor"], "what": f"Published version {n}"})
        elif r["action"] == "profile_rolled_back":
            out.append({"at": r["at"], "who": r["actor"], "what": f"Rolled back version {d.get('number')} to version {d.get('restored_number')}",
                        "note": d.get("reason")})
        elif r["action"] == "plan_activated":
            n = db.val(cur, "select name from territory_plans where id = %s", int(r["object_id"]))
            out.append({"at": r["at"], "who": r["actor"], "what": f"Activated {n}", "figure": d.get("changes")})
        elif r["action"] == "plan_rolled_back":
            a = db.val(cur, "select name from territory_plans where id = %s", int(r["object_id"]))
            b = db.val(cur, "select name from territory_plans where id = %s", int(d.get("restored")))
            out.append({"at": r["at"], "who": r["actor"], "what": f"Rolled back {a} to {b}", "figure": d.get("changes"),
                        "note": d.get("reason")})
    return out


def publish_preview(cur, vid: int, u: dict) -> dict | None:
    """What Publish does, in counts. The draft is scored here in a read-only transaction, never stored."""
    v = version(cur, vid, u)
    if v is None:
        return None
    pub = _published(cur)
    mv = fit.what_moves(cur, vid, pub["id"]) if v["status"] == "draft" else {"total": 0, "moves": []}
    return {"id": vid, "number": v["number"], "status": v["status"], "replaces": pub["number"], "rule_changes": len(v["diff"]),
            "companies": db.val(cur, "select count(*) from companies"), "tier_moves": mv["total"], "moves": mv["moves"][:6],
            "crm": crm.enabled(), "batches": crm.score_batches(cur), "can_publish": v["can_publish"]}


def profile_rollback_preview(cur, u: dict) -> dict:
    t = profiles.rollback_target(cur)
    if t is None:
        return {"available": False}
    now, prev = t
    mv = fit.what_moves(cur, prev["id"], now["id"])
    return {"available": True, "can_roll_back": u["role"] == "manager", "from": now["number"], "to": prev["number"],
            "companies": db.val(cur, "select count(*) from companies"), "tier_moves": mv["total"], "moves": mv["moves"][:6],
            "crm": crm.enabled(), "batches": crm.score_batches(cur)}


def move_options(cur) -> dict:
    """Who can take accounts and which territories exist, for the proposal form."""
    people = db.all(cur, "select id, name, role from users where active and role in ('ae', 'sdr') order by role, name")
    terrs = db.all(cur, """select t.key, t.label, t.rule from territories t join territory_plans p on p.id = t.plan and p.status = 'active'
                           order by t.id""")
    return {"people": people, "territories": [{"key": t["key"], "label": t["label"], "people": t["rule"]["people"],
                                              "regions": t["rule"].get("region_groups", []), "segments": [C.SEGMENT_LABEL.get(k, k) for k in t["rule"].get("segments", [])]}
                                             for t in terrs],
            "today": db.val(cur, "select app_now()::date")}


def _rule_state(rules: dict) -> dict:
    return {(k, r["key"]): (rule_label(r), r.get("weight")) for k, r in profiles.all_rules(rules)}


def _drafts_with_changes_this_lacks(cur, v: dict, published: dict | None) -> list[int]:
    """Open drafts, other than this one, with a change from the published version that this draft does not carry. A draft
    made from another open draft (decision 63) carries its rules, so that one is not listed; 2 drafts made apart are."""
    base = _rule_state(published["rules"]) if published else {}
    mine = _rule_state(v["rules"])
    out = []
    for d in db.all(cur, "select number, rules from icp_versions where status = 'draft' and id <> %s order by number", v["id"]):
        theirs = _rule_state(d["rules"])
        changed = {k: theirs.get(k) for k in set(base) | set(theirs) if base.get(k) != theirs.get(k)}
        if any(mine.get(k) != val for k, val in changed.items()):
            out.append(d["number"])
    return out


def version(cur, vid: int, u: dict) -> dict | None:
    v = db.one(cur, """select v.*, a.name as author_name, p.name as publisher from icp_versions v join users a on a.id = v.author
                       left join users p on p.id = v.published_by where v.id = %s""", vid)
    if not v:
        return None
    # A draft is compared with the published version (a draft made from an open draft carries that draft's rules, so its
    # diff shows them as well). A published or retired
    # version is compared with the one it replaced when that is recorded, else with the number before.
    if v["status"] == "draft":
        prev = db.one(cur, "select number, rules from icp_versions where status = 'published'")
    elif v["replaced"]:
        prev = db.one(cur, "select number, rules from icp_versions where id = %s", v["replaced"])
    else:
        prev = db.one(cur, "select number, rules from icp_versions where number = %s", v["number"] - 1)
    other_drafts = _drafts_with_changes_this_lacks(cur, v, prev) if v["status"] == "draft" else []
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
    return {"id": v["id"], "number": v["number"], "status": v["status"], "note": names.say(v["note"]), "author": v["author_name"],
            "publisher": v["publisher"], "created_at": v["created_at"], "published_at": v["published_at"],
            "tiers": v["rules"]["tiers"], "rules": _rules_view(cur, v["rules"]), "diff": diff, "diff_base": prev["number"] if prev else None,
            "other_drafts": other_drafts,
            "can_publish": v["status"] == "draft" and u["role"] == "manager" and v["author"] != u["id"],
            "is_author": v["author"] == u["id"],
            "dropped": _plain_dropped(handoff.compile_for_account_desk(v["rules"])[1])}


# ---------------------------------------------------------------- Accounts and companies

PAGE = 50


def _coming(cur, company_ids: list[int]) -> dict[int, list[dict]]:
    """company -> the owners a scheduled plan, or an approved move waiting for its date, will give it: who and from when
    ("Moves to Ana from 1 Jan 2027")."""
    from .. import territories
    names = {x["id"]: x["name"] for x in db.all(cur, "select id, name from users")}
    out: dict[int, list[dict]] = {}
    waiting: dict[tuple, object] = {}
    # An approved move proposal waits for its date while a plan is scheduled (decision 73).
    for m in db.all(cur, """select m.company, m.to_owner, m.effective_on, u.role from scheduled_moves m join users u on u.id = m.to_owner
                            where m.status = 'pending' and m.company = any(%s) order by m.effective_on, m.id""", company_ids):
        role = "SDR" if m["role"] == "sdr" else "owner"
        out.setdefault(m["company"], []).append({"role": role, "name": names[m["to_owner"]], "from": m["effective_on"]})
        waiting[(m["company"], role, m["to_owner"])] = m["effective_on"]
    s = territories.scheduled_plan(cur)
    if not s:
        return out
    moves = territories.scheduled_moves(cur)
    for c in company_ids:
        for role, uid in (moves.get(c) or {}).items():
            word = "owner" if role == "owner" else "SDR"
            if (c, word, uid) in waiting and waiting[(c, word, uid)] <= s["effective_on"]:
                continue   # a waiting move already says this person takes it, earlier: the plan carries the same move
            out.setdefault(c, []).append({"role": word, "name": names[uid], "from": s["effective_on"]})
    # A person moved it by hand after the plan was scheduled: the plan no longer moves it (decision 57).
    wanted = set(company_ids)
    for h in territories.hand_changes(cur, s["id"]):
        if h["company"] in wanted:
            out.setdefault(h["company"], []).append({"role": "owner" if h["role"] == "owner" else "SDR", "name": h["planned_name"],
                                                    "from": s["effective_on"], "by_hand": True, "kept": h["to_name"], "by": h["by_name"]})
    return out


def _crm_differs(cur, cid: int, a: dict | None) -> list[dict]:
    """The seats where CRM Desk holds a different person than the plan in effect, and who set each there (J28, decision 77). Read
    only: this desk shows it and changes nothing. Empty when CRM Desk was never read for the account or holds the same people."""
    r = db.one(cur, "select * from crm_owner_reads where company = %s", cid)
    if r is None:
        return []
    mine = {"AE": None, "SDR": None}
    if a and a["owner"]:
        who = db.one(cur, "select email, role from users where id = %s", a["owner"])
        if who and who["role"] == "sdr":
            mine["SDR"] = who["email"]
            ae = db.val(cur, "select u.email from territories t join users u on u.id = t.paired_ae where t.id = %s", a["territory"]) if a["territory"] else None
            mine["AE"] = ae
        elif who:
            mine["AE"] = who["email"]
    out = []
    for seat, email, by in (("AE", r["ae_email"], r["ae_set_by"]), ("SDR", r["sdr_email"], r["sdr_set_by"])):
        if email and email.lower() != (mine[seat] or "").lower():
            out.append({"seat": seat, "crm": db.val(cur, "select name from users where lower(email) = %s", email.lower()) or email,
                        "here": db.val(cur, "select name from users where lower(email) = %s", mine[seat].lower()) if mine[seat] else None,
                        "set_by": names.say(by) if by else None, "read_at": r["read_at"]})
    return out


def _before(cur, pub: dict, plan: int | None) -> tuple[dict | None, int | None]:
    """The profile version the published one replaced, and the plan the one in effect replaced: what "changed since" compares with."""
    prev_v = db.one(cur, "select id, number from icp_versions where id = %s", pub["replaced"]) if pub.get("replaced") else None
    prev_p = db.val(cur, "select replaced from territory_plans where id = %s", plan) if plan else None
    return prev_v, prev_p


def accounts(cur, u: dict, *, q: str, tier: str, segment: str, owner: str, page: int, region: str = "", changed: str = "") -> dict:
    pub = _published(cur)
    plan = _active_plan(cur)
    prev_v, prev_p = _before(cur, pub, plan)
    where = ["c.lifecycle <> 'competitor'", "not c.sole_trader"]
    args: list = []
    if changed == "tier" and prev_v:
        where.append("pf.judged and f.judged and pf.tier is distinct from f.tier")
    elif changed == "owner" and prev_p:
        where.append("a.owner is distinct from pa.owner")
    elif changed:
        where.append("false")
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
    # The version and the plan before, for "changed since"; with none before, these joins match nothing.
    sql = f"""
        from companies c join account_fit f on f.company = c.id and f.icp_version = %s
        left join assignments a on a.company = c.id and a.plan = %s left join users u on u.id = a.owner
        left join account_fit pf on pf.company = c.id and pf.icp_version = %s
        left join assignments pa on pa.company = c.id and pa.plan = %s left join users pu on pu.id = pa.owner
        where {' and '.join(where)}"""
    base = (pub["id"], plan, prev_v and prev_v["id"], prev_p)
    total = db.val(cur, "select count(*) " + sql, *base, *args)
    rows = db.all(cur, """select c.id, c.name, c.primary_domain, c.lifecycle, c.employees, c.region_group, c.region,
                          coalesce(c.industry, (select v.value #>> '{}' from field_values v where v.company = c.id
                                                and v.field = 'industry' and v.source = 'model' limit 1)) as industry,
                          f.tier, f.judged, f.score, f.scored_out_of, f.segment, u.name as owner, u.role as owner_role, a.reason_code,
                          case when pf.judged and f.judged then pf.tier end as was_tier, pu.name as was_owner, (pa.company is not null) as had_plan_before,
                          (select r.meetings from desk_results r where r.company = c.id order by r.period_end desc limit 1) as last_meetings,
                          (select r.destination from desk_results r where r.company = c.id order by r.period_end desc limit 1) as last_dest
                          """ + sql + " order by f.judged desc, f.score desc nulls last, c.name limit %s offset %s",
                   *base, *args, PAGE, (page - 1) * PAGE)
    for r in rows:
        r["segment_label"] = C.SEGMENT_LABEL.get(r["segment"], r["segment"])
        r["owner_seat"] = _seat(r["owner_role"]) if r["owner"] else None
        r["owner_source"] = owner_source(r["reason_code"]) if r["owner"] else None
        # A tier A prospect in our regions that nobody has hours for (SPEC 7: shown, never demoted).
        r["over_capacity"] = (r["tier"] == "A" and r["judged"] and r["lifecycle"] == "prospect" and not r["owner"]
                              and r["region"] in C.SERVED_REGIONS)
    coming = _coming(cur, [r["id"] for r in rows])
    for r in rows:
        r["coming"] = coming.get(r["id"], [])
    owners = db.all(cur, "select id, name from users where role in ('sdr','ae') and active order by name")
    since = {"version": prev_v and prev_v["number"], "plan": bool(prev_p)}
    if prev_v:
        since["tier"] = db.val(cur, """select count(*) from companies c join account_fit f on f.company = c.id and f.icp_version = %s
                                       join account_fit pf on pf.company = c.id and pf.icp_version = %s
                                       where c.lifecycle <> 'competitor' and not c.sole_trader and f.judged and pf.judged and pf.tier <> f.tier""",
                               pub["id"], prev_v["id"])
    if prev_p:
        since["owner"] = db.val(cur, """select count(*) from companies c left join assignments a on a.company = c.id and a.plan = %s
                                        left join assignments pa on pa.company = c.id and pa.plan = %s
                                        where c.lifecycle <> 'competitor' and not c.sole_trader and a.owner is distinct from pa.owner""", plan, prev_p)
    return {"rows": rows, "total": total, "page": page, "pages": max(1, -(-total // PAGE)), "owners": owners, "since": since,
            "segments": [{"key": s["key"], "label": s["label"]} for s in C.SEGMENTS] + [C.OUTSIDE]}


def company(cur, cid: int, u: dict, allowed: bool | None = None) -> dict | None:
    # A sole trader is a person, not a company: never shown (docs/SPEC.md 13).
    c = db.one(cur, "select * from companies where id = %s and not sole_trader", cid)
    if not c:
        return None
    plan = _active_plan(cur)
    a = db.one(cur, """select a.*, u.name as owner_name, u.role as owner_role, m.name as moved_from_name from assignments a left join users u on u.id = a.owner
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
    owner_changes = [{"at": r["at"], "who": r["actor"], "to": r["to_name"], "was": r["from_name"], "note": (r["detail"] or {}).get("note")}
                     for r in db.all(cur, """select l.at, l.actor, l.detail, t.name as to_name, f.name as from_name from audit_log l
                                             left join users t on t.id = (l.detail->>'to')::int left join users f on f.id = (l.detail->>'from')::int
                                             where l.action = 'owner_changed_by_hand' and l.object_kind = 'company' and l.object_id = %s
                                             order by l.id desc limit 5""", str(cid))]
    return strip({"id": c["id"], "name": c["name"], "domain": c["primary_domain"], "world_id": world_id(c["primary_domain"]),
                  "lifecycle": c["lifecycle"],
                  "industry": c["industry"], "employees": c["employees"], "country": C.COUNTRY_NAME.get(c["country"], c["country"]),
                  "region_group": c["region_group"], "revenue_band": c["revenue_band"], "pricing_model": c["pricing_model"],
                  "tech": c["tech"], "description": c["description"], "sole_trader": c["sole_trader"],
                  "fields": fields, "fit": cur_fit and {"score": cur_fit["score"], "tier": cur_fit["tier"], "judged": cur_fit["judged"],
                                                        "scored_out_of": cur_fit["scored_out_of"], "excluded": cur_fit["excluded"],
                                                        "segment": cur_fit["segment"], "segment_label": C.SEGMENT_LABEL.get(cur_fit["segment"]),
                                                        "breakdown": breakdown, "version": pub["number"]},
                  "history": history, "coming": _coming(cur, [cid]).get(cid, []), "owner": a and {"name": a["owner_name"], "id": a["owner"], "reason": a["reason_code"],
                                                      "note": a["note"], "moved_from": a["moved_from_name"],
                                                      "seat": _seat(a["owner_role"]) if a["owner"] else None,
                                                      "source": owner_source(a["reason_code"])},
                  "draft_owner": _draft_owner(cur, cid, a), "crm_differs": _crm_differs(cur, cid, a),
                  "owner_changes": owner_changes, "hand_owner": _hand_owner(cur, cid, a, u),
                  "deals": deals, "results": results, "tests": tests}, allowed)


def _draft_owner(cur, cid: int, a: dict | None) -> dict | None:
    """The owner the newest draft plan would give this account (decision 69), shown last and marked draft. None when there is no
    draft plan, the newest draft does not hold the account, or it gives the same person."""
    d = db.one(cur, """select p.id, p.name, x.owner, u.name as owner_name, u.role as owner_role from territory_plans p
                       join assignments x on x.plan = p.id and x.company = %s left join users u on u.id = x.owner
                       where p.id = (select max(id) from territory_plans where status = 'draft')""", cid)
    if not d or d["owner"] == (a or {}).get("owner"):
        return None
    return {"plan": d["name"], "name": d["owner_name"], "seat": _seat(d["owner_role"]) if d["owner"] else None}


def _hand_owner(cur, cid: int, a: dict | None, u: dict) -> dict | None:
    """What the owner form on the account sheet shows RevOps, the only role the endpoint lets change an owner by hand
    (decision 65): who holds the account now and the people who can take the same seat. None for anyone else.
    What it says about a scheduled plan follows territories.change_owner_by_hand and reconcile_hand_changes: the plan stops
    moving the account only when it would move this seat to the same kind of person; when its assignment holds the other kind
    (decision 57's case left open), the start date still gives the account to that person, and the form says so."""
    if u["role"] != "revops":
        return None
    if a is None:
        return {"can": False, "why": "This account is not in the plan in effect."}
    seat = db.val(cur, "select role from users where id = %s", a["owner"]) if a["owner"] else None
    kind = "sdr" if seat == "sdr" else "ae"
    people = db.all(cur, "select id, name from users where active and role = %s and id is distinct from %s order by name", kind, a["owner"])
    role = "sdr" if kind == "sdr" else "owner"
    drops, still_to = False, None
    sched = terr.scheduled_plan(cur)
    if sched:
        planned = db.one(cur, """select a.owner, u.name, u.role from assignments a join users u on u.id = a.owner
                                 where a.plan = %s and a.company = %s""", sched["id"], cid)
        if planned and planned["owner"] != a["owner"] and (planned["role"] == "sdr") != (kind == "sdr"):
            still_to = planned["name"]
        else:
            drops = role in terr.scheduled_moves(cur).get(cid, {})
    return {"can": True, "seat": kind.upper(), "now": {"id": a["owner"], "name": a["owner_name"]}, "choices": people,
            "drops_scheduled_move": drops, "scheduled_still_to": still_to}


def raise_forbidden():
    from fastapi import HTTPException
    raise HTTPException(403, "This account is not in your book.")


# ---------------------------------------------------------------- Territories and capacity

def territories(cur, plan_id: int | None, allowed: bool) -> dict:
    plans = db.all(cur, """select p.id, p.name, p.status, p.created_at, p.activated_at, a.name as author, x.name as activated_by,
                           p.author as author_id, p.balance_report, p.replaced, p.restored_at, p.effective_on from territory_plans p join users a on a.id = p.author
                           left join users x on x.id = p.activated_by order by case p.status when 'active' then 0 when 'scheduled' then 1 when 'draft' then 2 else 3 end, p.id desc""")
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
    manual = db.all(cur, """select a.company, c.name, a.note, u.name as owner, m.name as moved_from, x.name as by_name,
                            (select max(l.at) from audit_log l where l.action in ('manual_move', 'owner_changed_by_hand') and l.object_kind = 'company'
                             and l.object_id = a.company::text and (l.detail->>'plan')::int = a.plan) as moved_at
                            from assignments a join companies c on c.id = a.company left join users u on u.id = a.owner
                            left join users m on m.id = a.moved_from left join users x on x.id = a.created_by
                            where a.plan = %s and a.reason_code = 'manual'""", plan_id)
    s = {r["key"]: r for r in db.all(cur, "select key, value, note from settings")}
    pub = _published(cur)
    a_cap = db.one(cur, """select sum((s.accounts_by_tier->>'A')::int) as held from capacity_snapshots s where s.plan = %s""", plan_id)
    a_total = db.val(cur, """select count(*) from account_fit f join companies c on c.id = f.company where f.icp_version = %s
                             and f.tier = 'A' and f.judged and c.lifecycle = 'prospect' and c.region = any(%s)""", pub["id"], C.SERVED_REGIONS)
    if ch:
        people_ids = sorted(set(ch["gains"]) | set(ch["losses"]), key=lambda k: names[k])
        ch = {"changes": ch["changes"], "owner_changes": ch["owner_changes"], "newly_assigned": ch["newly_assigned"],
              "newly_unassigned": ch["newly_unassigned"], "crossing": len(ch["crossing"]),
              "people": [{"name": names[k], "gains": ch["gains"].get(k, 0), "losses": ch["losses"].get(k, 0)} for k in people_ids]}
    hist = history(cur, ("plan_activated", "plan_rolled_back"))
    plan = {**plan, "delivery": crm.delivery_state(cur, f"plan:{plan['id']}") if crm.enabled() else None}
    owner_changes = plan_owner_changes(cur, plan)
    return strip({"plans": plans, "plan": plan, "history": hist, "people": people, "territories": terrs, "gap": gap, "changes": ch,
                  "manual": manual, "owner_changes": owner_changes, "hours_per_tier": s["hours_per_tier"]["value"], "hours_note": _say(s["hours_per_tier"]["note"]),
                  "a_capacity": {"held": a_cap["held"] or 0, "tier_a": a_total}}, allowed)


def plan_owner_changes(cur, plan: dict, limit: int = 100) -> dict | None:
    """The accounts this plan gives to someone other than the plan it is compared with: the plan in effect for a draft or a scheduled
    plan, the plan it replaced for the one in effect (J1). None when there is nothing to compare with."""
    if plan["status"] in ("draft", "scheduled"):
        base = db.one(cur, "select id, name from territory_plans where status = 'active'")
    elif plan["status"] == "active" and plan["replaced"]:
        base = db.one(cur, "select id, name from territory_plans where id = %s", plan["replaced"])
    else:
        base = None
    if base is None or base["id"] == plan["id"]:
        return None
    sql = """from assignments a join companies c on c.id = a.company and not c.sole_trader
             left join assignments b on b.plan = %s and b.company = a.company
             left join users u on u.id = a.owner left join users o on o.id = b.owner
             where a.plan = %s and a.owner is distinct from b.owner"""
    total = db.val(cur, "select count(*) " + sql, base["id"], plan["id"])
    rows = db.all(cur, "select c.id, c.name, c.primary_domain, u.name as to_owner, o.name as from_owner " + sql + " order by c.name limit %s",
                  base["id"], plan["id"], limit)
    return {"against": base["name"], "total": total, "rows": rows}


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
            "decided": [_proposal_row(cur, p) for p in rows if p["status"] != "open"],
            "open_drafts": [r["number"] for r in db.all(cur, "select number from icp_versions where status = 'draft' order by number")],
            "new_draft_starts_from": (proposals.open_draft(cur) or {}).get("number")}


def books_behind(cur) -> list[dict]:
    """The destinations whose newest file was made from a profile version other than the published one: after a publish the files
    are behind until RevOps makes new ones (decision 67). Nothing is made by itself. Empty when no file was ever made."""
    pub = _published(cur)["number"]
    return [r for r in db.all(cur, """select distinct on (b.destination) b.destination, v.number as made_from from target_books b
                                      join icp_versions v on v.id = b.icp_version order by b.destination, b.created_at desc, b.id desc""")
            if r["made_from"] != pub]


def start(cur) -> dict:
    """The one moment worth seeing first: of the findings behind the open changes, the one whose win rate differs most from the
    rest of the deals. It is where the first screen and Changes point a visitor. None when nothing open rests on a clear finding."""
    row = db.one(cur, """select f.id, f.trait, f.value_label, f.opps, f.win_rate, f.rest_wins, f.rest_opps
                         from change_proposals p, lateral jsonb_array_elements_text(coalesce(p.evidence->'finding_ids', '[]'::jsonb)) x(fid)
                         join findings f on f.id = x.fid::int
                         where p.status = 'open' and f.trait <> 'rule' and f.verdict in ('clear_higher', 'clear_lower') and f.rest_opps > 0
                         order by abs(f.diff) desc, f.opps desc limit 1""")
    if not row:
        return {"best": None}
    return {"best": {"id": row["id"], "label": row["value_label"], "trait": C.FIELD_LABEL.get(row["trait"], row["trait"]),
                     "rate": float(row["win_rate"]), "rest_rate": row["rest_wins"] / row["rest_opps"], "opps": row["opps"]}}


def proposal(cur, pid: int) -> dict | None:
    p = db.one(cur, """select p.*, u.name as decided_by_name, v.number as draft_number from change_proposals p
                       left join users u on u.id = p.decided_by left join icp_versions v on v.id = p.draft_version where p.id = %s""", pid)
    return p and _proposal_row(cur, p)


# ---------------------------------------------------------------- Handoffs

def handoffs(cur, allowed: bool) -> dict:
    books = db.all(cur, """select b.id, b.version, b.destination, b.created_at, b.rows, b.dropped_rules, b.diff, v.number as icp_number,
                           p.name as plan_name, u.name as created_by from target_books b join icp_versions v on v.id = b.icp_version
                           join territory_plans p on p.id = b.plan left join users u on u.id = b.created_by order by b.created_at desc, b.id desc""")
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
    for p in previews:
        p["dropped_rules"] = _plain_dropped(p["dropped_rules"])
    for b in books:
        b["dropped_rules"] = _plain_dropped(b["dropped_rules"])
    pub = _published(cur)
    plan = db.val(cur, "select name from territory_plans where status = 'active'")
    return strip({"books": books, "events": events, "previews": previews, "crm": crm_desk(cur),
                  "next": {"profile": pub["number"], "plan": plan},
                  "behind": {"profile": pub["number"], "destinations": [b["destination"] for b in books_behind(cur)]}}, allowed)


def crm_desk(cur) -> dict | None:
    """What went to CRM Desk and what it refused. None when no CRM is set and nothing was ever sent (the desk alone)."""
    from .. import crm
    s = crm.summary(cur)
    if not s["enabled"] and not s["sent"] and not s["queued"]:
        return None
    for r in s["refusals"]:
        c = db.one(cur, "select id, name from companies where primary_domain = %s", r["domain"])
        r["company"], r["name"] = (c["id"], c["name"]) if c else (None, r["domain"])
        r["proposed_name"] = (db.val(cur, "select name from users where email = %s", r["proposed"]) if isinstance(r["proposed"], str) else None) or r["proposed"]
        r["what"] = {"sdr_owner_id": "SDR", "owner_id": "Owner", "mqa_at": "Marketing qualified", "mqa_points": "Engagement points",
                     "mqa_people": "People engaged"}.get(r["field"], r["field"])
        r["why"] = names.say({"owner_pinned": "A manager pinned it in CRM Desk",
                    "kept_value_a_person_entered": "Someone in CRM Desk entered a different value",
                    "computed_by_crm_desk": "CRM Desk decides marketing qualified itself until it is set to follow this desk"
                    }.get(r["reason"], "CRM Desk kept its own value"))
    for f in s.get("failed") or []:
        f["last_error"] = names.say(f.get("last_error"))
    for e in s["errors"]:
        e["error"] = names.say(e.get("error"))
        c = db.one(cur, "select id, name from companies where primary_domain = %s", e["domain"])
        e["company"], e["name"] = (c["id"], c["name"]) if c else (None, e["domain"])
    from .. import mqa
    s["mqa"] = mqa.state(cur)
    s["deliveries"] = deliveries(cur)
    return s


def deliveries(cur, limit: int = 8) -> list[dict]:
    """The latest things sent to CRM Desk, each with where it stands (decision 78): "Sent <time>", "Waiting to send", or what
    CRM Desk did not take. Grouped by what the request was for, newest first."""
    rows = db.all(cur, """select ref, count(*) filter (where status = 'sent') as sent, count(*) filter (where status = 'queued') as waiting,
                          count(*) filter (where status = 'failed') as failed, max(sent_at) as sent_at, max(id) as last,
                          max(last_error) filter (where status = 'failed') as error
                          from crm_outbox where ref is not null and status <> 'cancelled' group by ref order by max(id) desc limit %s""", limit)
    for r in rows:
        kind, _, key = r["ref"].partition(":")
        if kind == "plan":
            r["what"] = db.val(cur, "select name from territory_plans where id = %s", int(key)) or "A plan"
        elif kind == "move":
            r["what"] = db.val(cur, """select 'Move of ' || (select count(*) from move_proposal_accounts x where x.proposal = p.id) || ' to ' || u.name
                                       from move_proposals p join users u on u.id = p.to_owner where p.id = %s""", int(key)) or "A move"
        elif kind == "scores":
            r["what"] = f"Tiers of profile version {db.val(cur, 'select number from icp_versions where id = %s', int(key))}"
        elif kind == "hand":
            r["what"] = f"Owner change, {db.val(cur, 'select name from companies where id = %s', int(key))}"
        else:
            r["what"] = "Marketing qualified marks"
        r["error"] = names.say(r["error"]) if r["error"] else None
    return rows


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
                                       "plan_name", "file_sha256")}, "dropped_rules": _plain_dropped(b["dropped_rules"]), "files": files, "sample": rows, "markdown": md}, allowed)


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
    owner = _source_owner(cur)
    for r in rows:
        r["owner"], r["can_run"] = owner, _can_run(r["key"])
    return strip({"rows": rows, "alerts": alerts, "companies": total}, allowed)


def _source_owner(cur) -> str | None:
    """Who looks after the sources: RevOps is the only role that opens this page, so its people are the owner."""
    n = [r["name"] for r in db.all(cur, "select name from users where active and role = 'revops' order by name")]
    return ", ".join(n) or None


def _can_run(key: str) -> bool:
    """Only the CRM read has a run this desk can start (the next read is brought forward). The sample sources have none."""
    return key == "crm" and crm.pull_enabled()


def source(cur, key: str, allowed: bool) -> dict | None:
    s = db.one(cur, "select * from sources where key = %s", key)
    if not s:
        return None
    runs = db.all(cur, "select * from source_runs where source = %s order by started_at desc limit 10", key)
    # What reads this source (S5 review): the fields it fills, and the published rules and tiers that use those fields.
    fills = db.all(cur, """select field, count(distinct company) as n from field_values where source = %s group by field order by field""", key)
    fields = {f["field"] for f in fills}
    pub = _published(cur)
    uses = [rule_label(r) for _k, r in profiles.all_rules(pub["rules"]) if r.get("field") in fields]
    depends = {"fields": [{"field": C.FIELD_LABEL.get(f["field"], f["field"]), "n": f["n"]} for f in fills], "rules": uses,
               "tiers": bool(uses), "version": pub["number"]}
    return strip({**s, "runs": runs, "depends": depends, "owner": _source_owner(cur), "can_run": _can_run(key)}, allowed)




def settings(cur) -> dict:
    rows = [{**r, "note": names.say(r["note"])} for r in db.all(cur, "select key, value, note, updated_at from settings order by key")]
    team = db.all(cur, "select id, name, role, started_on, ramp_months, selling_hours_month, active from users order by role, name")
    return {"settings": rows, "team": team}

