"""Capacity, territories and assignment (docs/SPEC.md 9.1). Capacity is throughput x window x seats (L-016): hours a
month each account needs by tier, against each person's selling hours times their effective FTE."""
from __future__ import annotations

import math
from datetime import date

from . import audit, db
from . import catalog as C
from .db import J


def settings(cur) -> dict:
    return {r["key"]: r["value"] for r in db.all(cur, "select key, value from settings")}


def effective_fte(user: dict, on: date) -> float:
    """Linear ramp from 0 to 1 over ramp_months from the start date (Bridge Group 2025 average ramp: 3 months)."""
    if user["started_on"] > on:
        return 0.0
    months = (on - user["started_on"]).days / 30.44
    ramp = user["ramp_months"] or 0
    return 1.0 if ramp == 0 else round(min(1.0, months / ramp), 3)


def segment_economics(cur) -> dict:
    """Shrunk win rate and median ACV per segment, from the latest evidence run. Used for expected value."""
    run = db.val(cur, "select max(id) from analysis_runs")
    k = float(settings(cur).get("shrink_k", 20))
    rows = db.all(cur, "select value, opps, wins, acv_median from findings where run = %s and trait = 'segment'", run)
    opps = sum(r["opps"] for r in rows) or 1
    wins = sum(r["wins"] for r in rows)
    overall = wins / opps
    acv_all = db.val(cur, """select percentile_cont(0.5) within group (order by amount_cents) from deals
                             where kind = 'new' and outcome = 'won'""") or 0
    out = {"_overall": {"win_rate": overall, "acv": int(acv_all)}}
    for r in rows:
        out[r["value"]] = {"win_rate": (r["wins"] + k * overall) / (r["opps"] + k),
                           "acv": int(r["acv_median"]) if r["wins"] >= 15 and r["acv_median"] else int(acv_all)}
    return out


def expected_value(econ: dict, segment: str, score: int | None) -> int:
    e = econ.get(segment) or econ["_overall"]
    return int(e["win_rate"] * e["acv"] * (score or 0) / 100)


def _people(cur, ids: list[int]) -> list[dict]:
    return db.all(cur, "select * from users where id = any(%s) and active order by id", ids)


def build_plan(cur, *, name: str, author: int, territories: list[dict], on: date, created_at=None) -> int:
    """Creates a draft plan and assigns accounts. territories: [{key, label, region_groups, segments, people, ae}]."""
    vid = db.val(cur, "select id from icp_versions where status = 'published'")
    pid = db.val(cur, """insert into territory_plans (name, status, based_on, author, created_at, effective_on)
                         values (%s, 'draft', %s, %s, coalesce(%s, app_now()), %s) returning id""", name, vid, author, created_at, on)
    for t in territories:
        t["id"] = db.val(cur, """insert into territories (plan, key, label, rule, owner, paired_ae)
                                 values (%s,%s,%s,%s,%s,%s) returning id""", pid, t["key"], t["label"],
                         J({"region_groups": t["region_groups"], "segments": t["segments"], "people": t["people"]}),
                         t["people"][0], t.get("ae"))
    assign(cur, pid, on=on)
    audit.log(cur, "user", "plan_drafted", "plan", pid, {"name": name}, actor_id=author)
    return pid


def assign(cur, plan_id: int, *, on: date) -> dict:
    s = settings(cur)
    hours = s["hours_per_tier"]
    band = float(s.get("balance_band", 0.15))
    plan = db.one(cur, "select * from territory_plans where id = %s", plan_id)
    terrs = db.all(cur, "select * from territories where plan = %s order by id", plan_id)
    econ = segment_economics(cur)
    manual = {r["company"]: r for r in db.all(cur, "select * from assignments where plan = %s and reason_code = 'manual'", plan_id)}
    db.run(cur, "delete from assignments where plan = %s and reason_code <> 'manual'", plan_id)
    rows = db.all(cur, """
        select c.id, c.lifecycle, c.owner_id, c.region_group, c.region, f.tier, f.score, f.segment, f.judged,
               exists (select 1 from deals d where d.company = c.id and d.outcome = 'open') as open_deal,
               exists (select 1 from segment_test_members m join segment_tests t on t.id = m.test
                       where m.company = c.id and m.grp = 'held_back' and t.status = 'running') as held,
               exists (select 1 from segment_test_members m join segment_tests t on t.id = m.test
                       where m.company = c.id and m.grp = 'worked' and t.status = 'running') as test_worked
        from companies c join account_fit f on f.company = c.id and f.icp_version = %s
        where not c.sole_trader""", plan["based_on"])
    people_ids = sorted({p for t in terrs for p in t["rule"]["people"]})
    people = {u["id"]: u for u in _people(cur, people_ids)}
    avail = {u: float(people[u]["selling_hours_month"]) * effective_fte(people[u], on) for u in people}
    used = {u: 0.0 for u in people}
    ev = {u: 0 for u in people}
    count: dict[int, dict] = {u: {"A": 0, "B": 0, "C": 0, "X": 0} for u in people}
    placed: dict[int, tuple] = {}

    def territory_of(r: dict) -> dict | None:
        for t in terrs:
            if r["region_group"] in t["rule"]["region_groups"] and r["segment"] in t["rule"]["segments"]:
                return t
        return None

    for r in rows:
        if r["id"] in manual:
            m = manual[r["id"]]
            if m["owner"] in people:
                used[m["owner"]] += hours.get(r["tier"], 0)
                ev[m["owner"]] += expected_value(econ, r["segment"], r["score"])
                count[m["owner"]][r["tier"]] += 1
            continue
        if r["lifecycle"] in ("customer", "open_opp") and r["owner_id"]:
            t = territory_of(r)
            placed[r["id"]] = (t["id"] if t else None, r["owner_id"], "open_deal" if r["open_deal"] else "existing_owner")
    cands = [r for r in rows if r["id"] not in placed and r["id"] not in manual and r["lifecycle"] == "prospect"
             and r["judged"] and r["tier"] in ("A", "B") and not r["held"]]
    cands.sort(key=lambda r: (not r["test_worked"], r["tier"], -expected_value(econ, r["segment"], r["score"]), r["id"]))
    for r in cands:
        t = territory_of(r)
        if not t:
            continue
        need = float(hours[r["tier"]])
        team = [p for p in t["rule"]["people"] if p in people]
        best = max(team, key=lambda p: (avail[p] - used[p], -p), default=None)
        # A running test's worked accounts stay worked, however full the book: dropping them would end the test.
        if best is None or (avail[best] - used[best] < need and not r["test_worked"]):
            continue
        used[best] += need
        e = expected_value(econ, r["segment"], r["score"])
        ev[best] += e
        count[best][r["tier"]] += 1
        placed[r["id"]] = (t["id"], best, "rule", e, r["tier"])
    # Balancing: move the lowest-value accounts from the richest person to the poorest in a territory, until each is
    # within the band of the territory mean and nobody is over their hours, or report that it cannot.
    report = {}
    for t in terrs:
        team = [p for p in t["rule"]["people"] if p in people and avail[p] > 0]
        if len(team) < 2:
            report[t["key"]] = {"balanced": True, "moves": 0}
            continue
        moves = 0
        for _ in range(400):
            mean = sum(ev[p] for p in team) / len(team)
            hi = max(team, key=lambda p: ev[p])
            lo = min(team, key=lambda p: ev[p])
            if mean == 0 or (ev[hi] - mean) <= band * mean and (mean - ev[lo]) <= band * mean:
                break
            mine = sorted([(cid, v) for cid, v in placed.items() if len(v) == 5 and v[1] == hi and v[0] == t["id"]],
                          key=lambda x: x[1][3])
            moved = False
            for cid, v in mine:
                need = float(hours[v[4]])
                if avail[lo] - used[lo] >= need and ev[lo] + v[3] <= mean * (1 + band):
                    placed[cid] = (v[0], lo, "balance_move", v[3], v[4], hi)
                    used[hi] -= need
                    used[lo] += need
                    ev[hi] -= v[3]
                    ev[lo] += v[3]
                    count[hi][v[4]] -= 1
                    count[lo][v[4]] += 1
                    moves += 1
                    moved = True
                    break
            if not moved:
                break
        mean = sum(ev[p] for p in team) / len(team)
        ok = mean == 0 or all(abs(ev[p] - mean) <= band * mean for p in team)
        report[t["key"]] = {"balanced": ok, "moves": moves}
    with cur.copy("copy assignments (plan, company, territory, owner, reason_code, moved_from, created_by) from stdin") as cp:
        for cid, v in placed.items():
            cp.write_row((plan_id, cid, v[0], v[1], v[2], v[5] if len(v) > 5 else None, plan["author"]))
    db.run(cur, "update territory_plans set balance_report = %s where id = %s", J(report), plan_id)
    snapshot(cur, plan_id)
    return report


def snapshot(cur, plan_id: int) -> None:
    """Hours and accounts per person, read back from the plan's assignments."""
    s = settings(cur)
    hours = s["hours_per_tier"]
    plan = db.one(cur, "select * from territory_plans where id = %s", plan_id)
    terrs = db.all(cur, "select rule from territories where plan = %s", plan_id)
    people = {u["id"]: u for u in _people(cur, sorted({p for t in terrs for p in t["rule"]["people"]}))}
    econ = segment_economics(cur)
    rows = db.all(cur, """select a.owner, f.tier, f.segment, f.score from assignments a
                          join account_fit f on f.company = a.company and f.icp_version = %s where a.plan = %s""",
                  plan["based_on"], plan_id)
    used = {u: 0.0 for u in people}
    ev = {u: 0 for u in people}
    count = {u: {"A": 0, "B": 0, "C": 0, "X": 0} for u in people}
    for r in rows:
        if r["owner"] in people:
            used[r["owner"]] += float(hours.get(r["tier"], 0))
            ev[r["owner"]] += expected_value(econ, r["segment"], r["score"]) if r["tier"] in ("A", "B") else 0
            count[r["owner"]][r["tier"]] += 1
    db.run(cur, "delete from capacity_snapshots where plan = %s", plan_id)
    for u, user in people.items():
        fte = effective_fte(user, plan["effective_on"])
        db.run(cur, """insert into capacity_snapshots (plan, user_id, effective_fte, hours_available, hours_required,
                       accounts_by_tier, expected_value_cents) values (%s,%s,%s,%s,%s,%s,%s)""",
               plan_id, u, fte, round(float(user["selling_hours_month"]) * fte, 1), round(used[u], 1), J(count[u]), ev[u])


def place_test_members(cur, test_id: int) -> int:
    """A started test's worked accounts join the active plan with their territory's lead, however full that book is:
    the test is a deliberate spend, and the Capacity tab shows what it costs."""
    plan = db.one(cur, "select * from territory_plans where status = 'active'")
    if not plan:
        return 0
    terrs = db.all(cur, "select * from territories where plan = %s order by id", plan["id"])
    rows = db.all(cur, """select c.id, c.region_group, f.segment from segment_test_members m join companies c on c.id = m.company
                          join account_fit f on f.company = c.id and f.icp_version = %s
                          where m.test = %s and m.grp = 'worked'
                            and not exists (select 1 from assignments a where a.plan = %s and a.company = c.id)""",
                  plan["based_on"], test_id, plan["id"])
    n = 0
    for r in rows:
        t = next((t for t in terrs if r["region_group"] in t["rule"]["region_groups"] and r["segment"] in t["rule"]["segments"]), None)
        if not t:
            continue
        db.run(cur, """insert into assignments (plan, company, territory, owner, reason_code, created_by)
                       values (%s,%s,%s,%s,'rule',%s)""", plan["id"], r["id"], t["id"], t["owner"], plan["author"])
        n += 1
    snapshot(cur, plan["id"])
    return n


def manual_move(cur, plan_id: int, company: int, to_user: int, note: str, by: dict) -> None:
    if by["role"] not in ("revops", "manager"):
        raise PermissionError("RevOps or a manager moves an account.")
    if not note or len(note.strip()) < 3:
        raise ValueError("A manual move needs a note.")
    plan = db.one(cur, "select * from territory_plans where id = %s", plan_id)
    if plan["status"] != "draft":
        raise ValueError("Accounts move in a draft plan.")
    cur_row = db.one(cur, "select * from assignments where plan = %s and company = %s", plan_id, company)
    db.run(cur, """insert into assignments (plan, company, territory, owner, reason_code, note, moved_from, created_by)
                   values (%s,%s,%s,%s,'manual',%s,%s,%s)
                   on conflict (plan, company) do update set owner = excluded.owner, reason_code = 'manual',
                   note = excluded.note, moved_from = excluded.moved_from, created_by = excluded.created_by""",
           plan_id, company, cur_row["territory"] if cur_row else None, to_user, note.strip(),
           cur_row["owner"] if cur_row else None, by["id"])
    audit.log(cur, by["name"], "manual_move", "company", company, {"plan": plan_id, "to": to_user, "note": note.strip()},
              actor_id=by["id"])
    snapshot(cur, plan_id)


def what_changes(cur, plan_id: int) -> dict:
    """Accounts whose owner differs from the active plan, by person, and open deals that would cross owners."""
    active = db.val(cur, "select id from territory_plans where status = 'active'")
    rows = db.all(cur, """
        select d.company, c.name, d.owner as to_owner, a.owner as from_owner, d.reason_code, d.note,
               exists (select 1 from deals x where x.company = d.company and x.outcome = 'open') as open_deal
        from assignments d join companies c on c.id = d.company
        left join assignments a on a.plan = %s and a.company = d.company
        where d.plan = %s and d.owner is distinct from a.owner""", active, plan_id)
    gains: dict[int, int] = {}
    losses: dict[int, int] = {}
    for r in rows:
        if r["to_owner"]:
            gains[r["to_owner"]] = gains.get(r["to_owner"], 0) + 1
        if r["from_owner"]:
            losses[r["from_owner"]] = losses.get(r["from_owner"], 0) + 1
    crossing = [r for r in rows if r["open_deal"] and r["from_owner"] and r["reason_code"] != "manual"]
    return {"changes": len(rows), "gains": gains, "losses": losses, "crossing": crossing, "sample": rows[:200]}


def activate(cur, plan_id: int, by: dict) -> None:
    plan = db.one(cur, "select * from territory_plans where id = %s for update", plan_id)
    if plan["status"] != "draft":
        raise ValueError("Only a draft plan can be activated.")
    if by["role"] != "manager":
        raise PermissionError("A manager activates a plan.")
    if plan["author"] == by["id"]:
        raise PermissionError("Someone other than the author activates a plan.")
    ch = what_changes(cur, plan_id)
    if ch["crossing"]:
        raise ValueError(f"{len(ch['crossing'])} open deals would change owner without a note.")
    db.run(cur, "update territory_plans set status = 'retired' where status = 'active'")
    db.run(cur, "update territory_plans set status = 'active', activated_by = %s, activated_at = app_now() where id = %s",
           by["id"], plan_id)
    for r in ch["sample"] if ch["changes"] <= 200 else db.all(cur, "select company, owner as to_owner from assignments where plan = %s", plan_id):
        audit.log(cur, by["name"], "owner_moved", "company", r["company"], {"plan": plan_id, "to": r["to_owner"]}, actor_id=by["id"])
    audit.log(cur, by["name"], "plan_activated", "plan", plan_id, {"changes": ch["changes"]}, actor_id=by["id"])


def hiring_gap(cur, plan_id: int) -> dict:
    """A and B prospects in served regions the plan cannot cover at current hours, and the people that would take."""
    s = settings(cur)
    hours = s["hours_per_tier"]
    plan = db.one(cur, "select * from territory_plans where id = %s", plan_id)
    rows = db.all(cur, """
        select f.tier, count(*) as n from companies c join account_fit f on f.company = c.id and f.icp_version = %s
        where c.lifecycle = 'prospect' and f.tier in ('A','B') and f.judged and c.region = any(%s) and not c.sole_trader
          and not exists (select 1 from assignments a where a.plan = %s and a.company = c.id)
          and not exists (select 1 from segment_test_members m join segment_tests t on t.id = m.test
                          where m.company = c.id and m.grp = 'held_back' and t.status = 'running')
        group by f.tier""", plan["based_on"], C.SERVED_REGIONS, plan_id)
    by = {r["tier"]: r["n"] for r in rows}
    need = sum(by.get(t, 0) * float(hours[t]) for t in ("A", "B"))
    return {"accounts": sum(by.values()), "by_tier": by, "hours": round(need), "people": math.ceil(need / 100)}


def capacity_accounts(cur, plan_id: int) -> float:
    """Accounts the plan's people can work in 12 months: accounts they can hold at once at the hours their current book
    uses per account, times the turns a year (12 / account_cycle_months)."""
    r = db.one(cur, """select sum(hours_available) as avail, sum(hours_required) as used,
                       sum((accounts_by_tier->>'A')::int + (accounts_by_tier->>'B')::int) as n
                       from capacity_snapshots where plan = %s""", plan_id)
    if not r or not r["n"]:
        return 0.0
    per = float(r["used"]) / r["n"]
    turns = 12 / float(settings(cur).get("account_cycle_months", 3))
    return float(r["avail"]) / per * turns if per else 0.0
