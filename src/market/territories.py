"""Capacity, territories and assignment (docs/SPEC.md 9.1). Capacity is throughput x window x seats: hours a
month each account needs by tier, against each person's selling hours times their effective FTE."""
from __future__ import annotations

import logging
import math
from datetime import date

from . import audit, db, jobs, notices
from . import catalog as C
from .db import J

log = logging.getLogger("market.territories")


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
    start = db.val(cur, "select window_start from analysis_runs where id = %s", run)
    acv_all = db.val(cur, """select percentile_cont(0.5) within group (order by amount_cents) from deals
                             where kind = 'new' and outcome = 'won' and closed_at >= %s""", start) or 0
    # The share of worked accounts that become deals, as in SOM: expected value is never every account a deal.
    o = db.one(cur, """select count(distinct company) as n, count(distinct company) filter (where opportunities > 0) as k
                       from desk_results where worked and destination = 'account_desk' and period_end - period_start >= 60
                       and (test is null or (select status from segment_tests t where t.id = test) <> 'running')""")
    opp = (o["k"] / o["n"]) if o and o["n"] else float(settings(cur).get("opp_rate_default", 0.10))
    out = {"_overall": {"win_rate": overall, "acv": int(acv_all), "opp": opp}}
    for r in rows:
        out[r["value"]] = {"win_rate": (r["wins"] + k * overall) / (r["opps"] + k), "opp": opp,
                           "acv": int(r["acv_median"]) if r["wins"] >= 15 and r["acv_median"] else int(acv_all)}
    return out


def expected_value(econ: dict, segment: str, score: int | None) -> int:
    e = econ.get(segment) or econ["_overall"]
    return int(e["opp"] * e["win_rate"] * e["acv"] * (score or 0) / 100)


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


def assign(cur, plan_id: int, *, on: date, as_of: date | None = None) -> dict:
    s = settings(cur)
    hours = s["hours_per_tier"]
    band = float(s.get("balance_band", 0.15))
    plan = db.one(cur, "select * from territory_plans where id = %s", plan_id)
    terrs = db.all(cur, "select * from territories where plan = %s order by id", plan_id)
    econ = segment_economics(cur)
    # A refill (as_of given) keeps every account already placed and only fills the hours that are free; a fresh
    # assignment keeps only the hand moves.
    if as_of:
        manual = {r["company"]: r for r in db.all(cur, "select * from assignments where plan = %s", plan_id)}
    else:
        manual = {r["company"]: r for r in db.all(cur, "select * from assignments where plan = %s and reason_code = 'manual'", plan_id)}
        db.run(cur, "delete from assignments where plan = %s and reason_code <> 'manual'", plan_id)
    rows = db.all(cur, """
        select c.id, c.owner_id, c.region_group, c.region, f.tier, f.score, f.segment, f.judged,
               -- What was true on the plan's date, not today: a customer who signed later is still a prospect here.
               case when exists (select 1 from customers u where u.company = c.id and u.started_on <= %(on)s
                                 and (u.churned_on is null or u.churned_on > %(on)s)) then 'customer'
                    when exists (select 1 from deals d where d.company = c.id and d.created_at::date <= %(on)s
                                 and (d.closed_at is null or d.closed_at::date > %(on)s)) then 'open_opp'
                    else 'prospect' end as lifecycle,
               exists (select 1 from deals d where d.company = c.id and d.created_at::date <= %(on)s
                       and (d.closed_at is null or d.closed_at::date > %(on)s)) as open_deal,
               exists (select 1 from segment_test_members m join segment_tests t on t.id = m.test
                       where m.company = c.id and m.grp = 'held_back' and t.status = 'running') as held,
               exists (select 1 from segment_test_members m join segment_tests t on t.id = m.test
                       where m.company = c.id and m.grp = 'worked' and t.status = 'running') as test_worked
        from companies c join account_fit f on f.company = c.id and f.icp_version = %(v)s
        where not c.sole_trader""", {"on": as_of or min(on, plan["created_at"].date()), "v": plan["based_on"]})
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
                used[m["owner"]] += float(s.get("hours_test_account", 0.25)) if m["reason_code"] == "test" else float(hours.get(r["tier"], 0))
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
        need = float(s.get("hours_test_account", 0.25)) if r["test_worked"] else float(hours[r["tier"]])
        team = [p for p in t["rule"]["people"] if p in people]
        best = max(team, key=lambda p: (avail[p] - used[p], -p), default=None)
        # A running test's worked accounts stay worked, however full the book: dropping them would end the test.
        if best is None or (avail[best] - used[best] < need and not r["test_worked"]):
            continue
        used[best] += need
        e = expected_value(econ, r["segment"], r["score"])
        ev[best] += e
        count[best][r["tier"]] += 1
        placed[r["id"]] = (t["id"], best, "test" if r["test_worked"] else "rule", e, r["tier"])
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
            mine = sorted([(cid, v) for cid, v in placed.items() if len(v) == 5 and v[1] == hi and v[0] == t["id"] and v[2] == "rule"],
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
    # Balanced means within the band and nobody over their hours (SPEC 9.1); otherwise the report says it cannot.
    for t in terrs:
        team = [p for p in t["rule"]["people"] if p in people]
        over = [p for p in team if used[p] > avail[p] + 0.05]
        rep = report.setdefault(t["key"], {"balanced": True, "moves": 0})
        if over:
            rep["balanced"] = False
            rep["over_hours"] = len(over)
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
    terrs = db.all(cur, "select key, rule from territories where plan = %s", plan_id)
    owners = {r["owner"] for r in db.all(cur, "select distinct owner from assignments where plan = %s and owner is not null", plan_id)}
    people = {u["id"]: u for u in _people(cur, sorted({p for t in terrs for p in t["rule"]["people"]} | owners))}
    econ = segment_economics(cur)
    rows = db.all(cur, """select a.owner, a.reason_code, f.tier, f.segment, f.score from assignments a
                          join account_fit f on f.company = a.company and f.icp_version = %s where a.plan = %s""",
                  plan["based_on"], plan_id)
    test_hours = float(s.get("hours_test_account", 0.25))
    used = {u: 0.0 for u in people}
    ev = {u: 0 for u in people}
    count = {u: {"A": 0, "B": 0, "C": 0, "X": 0} for u in people}
    for r in rows:
        if r["owner"] in people:
            used[r["owner"]] += test_hours if r["reason_code"] == "test" else float(hours.get(r["tier"], 0))
            ev[r["owner"]] += expected_value(econ, r["segment"], r["score"]) if r["tier"] in ("A", "B") else 0
            count[r["owner"]][r["tier"]] += 1
    db.run(cur, "delete from capacity_snapshots where plan = %s", plan_id)
    for u, user in people.items():
        fte = effective_fte(user, plan["effective_on"])
        db.run(cur, """insert into capacity_snapshots (plan, user_id, effective_fte, hours_available, hours_required,
                       accounts_by_tier, expected_value_cents) values (%s,%s,%s,%s,%s,%s,%s)""",
               plan_id, u, fte, round(float(user["selling_hours_month"]) * fte, 1), round(used[u], 1), J(count[u]), ev[u])
    report = plan["balance_report"] or {}
    for t in terrs:
        over = [p for p in t["rule"]["people"] if p in people and used[p] > float(people[p]["selling_hours_month"]) * effective_fte(people[p], plan["effective_on"]) + 0.05]
        rep = report.setdefault(t["key"], {"balanced": True, "moves": 0})
        if over:
            rep["balanced"] = False
            rep["over_hours"] = len(over)
    db.run(cur, "update territory_plans set balance_report = %s where id = %s", J(report), plan_id)


def place_test_members(cur, test_id: int) -> int:
    """A started test's worked accounts join the active plan with their territory's lead, however full that book is:
    the test is a deliberate spend, and the Capacity tab shows what it costs."""
    plan = db.one(cur, "select * from territory_plans where status = 'active'")
    if not plan:
        return 0
    terrs = db.all(cur, "select * from territories where plan = %s order by id", plan["id"])
    # The held-back group is never worked: it leaves every live plan the day the test starts.
    db.run(cur, """delete from assignments a using territory_plans p, segment_test_members m
                   where p.id = a.plan and p.status in ('active', 'scheduled', 'draft') and m.test = %s and m.company = a.company
                     and m.grp = 'held_back' and a.reason_code not in ('existing_owner', 'open_deal')""", test_id)
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
                       values (%s,%s,%s,%s,'test',%s)""", plan["id"], r["id"], t["id"], t["owner"], plan["author"])
        n += 1
    snapshot(cur, plan["id"])
    return n


def manual_move(cur, plan_id: int, company: int, to_user: int, note: str, by: dict) -> None:
    if by["role"] != "revops":
        raise PermissionError("RevOps moves an account by hand; a manager activates the plan.")
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
        select d.company, c.name, d.owner as to_owner, a.owner as from_owner, d.reason_code, d.note, c.owner_id as crm_owner,
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
    # An open deal may follow its CRM owner; moving it to anyone else needs a manual move with a note.
    crossing = [r for r in rows if r["open_deal"] and r["to_owner"] != r["crm_owner"] and r["reason_code"] != "manual"]
    # "changes" counts every row whose owner differs. Of those, only the accounts with an owner on both sides change hands;
    # the rest gain an owner (nobody had them) or lose theirs (nobody takes them).
    owner_changes = sum(1 for r in rows if r["from_owner"] and r["to_owner"])
    newly_assigned = sum(1 for r in rows if r["to_owner"] and not r["from_owner"])
    newly_unassigned = sum(1 for r in rows if r["from_owner"] and not r["to_owner"])
    return {"changes": len(rows), "owner_changes": owner_changes, "newly_assigned": newly_assigned, "newly_unassigned": newly_unassigned,
            "gains": gains, "losses": losses, "crossing": crossing, "sample": rows[:200], "all": rows}


def scheduled_plan(cur) -> dict | None:
    """The plan activated for a start date that has not come, if there is one (one at a time)."""
    return db.one(cur, "select * from territory_plans where status = 'scheduled'")


def _refuse_while_scheduled(cur) -> None:
    s = scheduled_plan(cur)
    if s:
        raise ValueError(f"A plan is scheduled for {s['effective_on']:%-d %b %Y}: cancel it first.")


def activate(cur, plan_id: int, by: dict) -> None:
    """Activates a draft plan. Starting today or earlier, it takes effect now. Starting later, it is scheduled: the owners
    stay as they are until the start date and the CRM is told what is coming (decision 55)."""
    plan = db.one(cur, "select * from territory_plans where id = %s for update", plan_id)
    if plan["status"] != "draft":
        raise ValueError("Only a draft plan can be activated.")
    if by["role"] != "manager":
        raise PermissionError("A manager activates a plan.")
    if plan["author"] == by["id"]:
        raise PermissionError("Someone other than the author activates a plan.")
    _refuse_while_scheduled(cur)
    active = db.val(cur, "select id from territory_plans where status = 'active'")
    if plan["drafted_from"] and plan["drafted_from"] != active:
        raise ValueError("The active plan changed after these moves were drafted. Propose them again.")
    ch = what_changes(cur, plan_id)
    if ch["crossing"]:
        raise ValueError(f"{len(ch['crossing'])} open deals would change owner without a note.")
    from . import crm  # the books go to a CRM when one is set (shared-world DESIGN.md 7, step 1)
    if plan["effective_on"] > db.val(cur, "select app_now()::date"):
        db.run(cur, "update territory_plans set status = 'scheduled', activated_by = %s, activated_at = app_now() where id = %s", by["id"], plan_id)
        audit.log(cur, by["name"], "plan_scheduled", "plan", plan_id, {"changes": ch["changes"], "replaces": active,
                  "effective_on": str(plan["effective_on"])}, actor_id=by["id"])
        crm.queue_schedule(cur, plan_id)
        jobs.enqueue(cur, "apply_scheduled_plan", {}, dedupe_key="apply_scheduled_plan")
        return
    _make_active(cur, plan_id, by, active, ch)


def _make_active(cur, plan_id: int, by: dict, active: int | None, ch: dict, scheduled_for: date | None = None) -> None:
    from . import crm
    db.run(cur, "update territory_plans set status = 'retired' where status = 'active'")
    db.run(cur, "update territory_plans set status = 'active', activated_by = %s, activated_at = app_now(), replaced = %s, "
                "restored_by = null, restored_at = null where id = %s", by["id"], active, plan_id)
    for r in ch["all"]:
        audit.log(cur, by["name"], "owner_moved", "company", r["company"], {"plan": plan_id, "from": r["from_owner"],
                  "to": r["to_owner"]}, actor_id=by["id"])
    audit.log(cur, by["name"], "plan_activated", "plan", plan_id, {"changes": ch["changes"], "replaced": active}, actor_id=by["id"])
    crm.queue_plan(cur, plan_id, scheduled_for)


def apply_scheduled(cur) -> int:
    """Makes the scheduled plan the one in effect once its start date has come. The books are sent again in full: the CRM has
    normally applied the schedule itself, so they change nothing, and they put right a CRM that was down, an account placed
    since, or a batch lost on the way."""
    plan = db.one(cur, "select * from territory_plans where status = 'scheduled' and effective_on <= app_now()::date for update")
    if plan is None:
        return 0
    by = db.one(cur, "select * from users where id = %s and active and role = 'manager'", plan["activated_by"]) or \
        db.one(cur, "select * from users where active and role = 'manager' and id <> %s order by id limit 1", plan["author"])
    if by is None:
        raise ValueError("No manager is left to apply the scheduled plan.")
    active = db.val(cur, "select id from territory_plans where status = 'active'")
    sync_hand_changes(cur)              # what a person moved in the CRM since the plan was scheduled
    reconcile_hand_changes(cur, plan["id"])
    _make_active(cur, plan["id"], by, active, what_changes(cur, plan["id"]), plan["effective_on"])
    return 1


def cancel_schedule(cur, by: dict) -> int:
    """A manager takes a scheduled plan back to draft before its start date. What the CRM was told is withdrawn."""
    if by["role"] != "manager":
        raise PermissionError("A manager cancels a schedule.")
    plan = db.one(cur, "select * from territory_plans where status = 'scheduled' for update")
    if plan is None:
        raise ValueError("No plan is scheduled.")
    if plan["effective_on"] <= db.val(cur, "select app_now()::date"):
        raise ValueError("The start date has come, so the plan is taking effect. Roll it back instead.")
    from . import crm
    crm.cancel_unsent(cur, plan["id"])
    db.run(cur, "delete from plan_hand_changes where plan = %s", plan["id"])   # a new schedule starts clean
    crm.queue_cancel(cur, plan["id"])
    db.run(cur, "update territory_plans set status = 'draft', activated_by = null, activated_at = null where id = %s", plan["id"])
    audit.log(cur, by["name"], "plan_schedule_cancelled", "plan", plan["id"], {"effective_on": str(plan["effective_on"])}, actor_id=by["id"])
    return plan["id"]


def roles_by_company(cur, plan_id: int) -> dict[int, tuple[int | None, int | None]]:
    """company -> (AE, SDR) for a plan, the way the CRM is told: an SDR placed on an account works it beside the territory's
    paired AE; anyone else placed is the AE."""
    out: dict[int, tuple[int | None, int | None]] = {}
    for r in db.all(cur, """select a.company, a.owner, u.role as owner_role, t.paired_ae from assignments a left join users u on u.id = a.owner
                            left join territories t on t.id = a.territory where a.plan = %s""", plan_id):
        out[r["company"]] = (r["paired_ae"], r["owner"]) if r["owner_role"] == "sdr" else (r["owner"], None)
    return out


def scheduled_moves_for(cur, plan_id: int, active_id: int | None) -> dict[int, dict]:
    """The roles a plan would change against the plan in effect: what the sheet counts before a plan is activated."""
    if not active_id:
        return {}
    old, new = roles_by_company(cur, active_id), roles_by_company(cur, plan_id)
    return {c: True for c, (ae, sdr) in new.items() if c in old and ((ae and ae != old[c][0]) or (sdr and sdr != old[c][1]))}


def scheduled_moves(cur) -> dict[int, dict]:
    """company -> {"owner": user id or None, "sdr": ...} for each role the scheduled plan changes against the plan in effect."""
    s = scheduled_plan(cur)
    active = db.val(cur, "select id from territory_plans where status = 'active'")
    if not s or not active:
        return {}
    old, new = roles_by_company(cur, active), roles_by_company(cur, s["id"])
    hand = {(r["company"], r["role"]) for r in hand_changes(cur, s["id"])}
    out = {}
    for c, (ae, sdr) in new.items():
        if c not in old:
            continue
        ch = {}
        if ae and ae != old[c][0] and (c, "owner") not in hand:
            ch["owner"] = ae
        if sdr and sdr != old[c][1] and (c, "sdr") not in hand:
            ch["sdr"] = sdr
        if ch:
            out[c] = ch
    return out


def hand_changes(cur, plan_id: int) -> list[dict]:
    """The accounts a person moved by hand while this plan was scheduled, which the plan no longer moves (decision 57)."""
    return db.all(cur, """select h.*, u.name as to_name, p.name as planned_name from plan_hand_changes h
                          left join users u on u.id = h.to_user left join users p on p.id = h.planned_owner
                          where h.plan = %s order by h.company, h.role""", plan_id)


def _planned_for(cur, plan_id: int, company: int, role: str) -> int | None:
    ae, sdr = roles_by_company(cur, plan_id).get(company, (None, None))
    return sdr if role == "sdr" else ae


def record_hand_change(cur, plan_id: int, company: int, role: str, *, source: str, to_user: int | None, by_name: str | None,
                       note: str | None = None) -> bool:
    """Notes that a person moved this account's AE or SDR by hand, so the scheduled plan leaves it alone. Only a role the plan
    would have changed counts; returns whether it was recorded."""
    old = db.val(cur, "select id from territory_plans where status = 'active'")
    if old is None:
        return False
    before = roles_by_company(cur, old).get(company, (None, None))[1 if role == "sdr" else 0]
    planned = _planned_for(cur, plan_id, company, role)
    if planned is None or planned == before:
        return False
    db.run(cur, """insert into plan_hand_changes (plan, company, role, source, to_user, planned_owner, by_name, note)
                   values (%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (plan, company, role) do update set source = excluded.source, to_user = excluded.to_user,
                   by_name = excluded.by_name, note = excluded.note, at = app_now()""",
           plan_id, company, role, source, to_user, planned, by_name, note)
    return True


def change_owner_by_hand(cur, company: int, to_user: int, note: str, by: dict) -> dict:
    """RevOps moves one account's AE or SDR in the plan in effect, now, outside any plan. A plan scheduled for later that
    would move the same role no longer does (it keeps the person's choice), and the CRM is told the plain owner and to drop
    what it holds. Standalone this is the one hand path; with a CRM the same fact also arrives from the CRM's side."""
    if by["role"] != "revops":
        raise PermissionError("RevOps changes an owner by hand.")
    if not note or len(note.strip()) < 3:
        raise ValueError("A change by hand needs a note.")
    active = db.val(cur, "select id from territory_plans where status = 'active'")
    person = db.one(cur, "select id, name, role from users where id = %s and active", to_user)
    if active is None or person is None or person["role"] not in ("ae", "sdr"):
        raise ValueError("Pick an AE or an SDR who is on the team.")
    row = db.one(cur, "select * from assignments where plan = %s and company = %s", active, company)
    if row is None:
        raise ValueError("That account is not in the plan in effect.")
    role = "sdr" if person["role"] == "sdr" else "owner"
    if (db.val(cur, "select role from users where id = %s", row["owner"]) == "sdr") != (role == "sdr"):
        raise ValueError("That account's seat is held by the other kind of person; change it in a plan.")
    if row["owner"] == to_user:
        raise ValueError("That person already holds this account.")
    moves = scheduled_moves(cur).get(company, {})          # worked out before the change, against the old owners
    db.run(cur, """update assignments set owner = %s, reason_code = 'manual', note = %s, moved_from = %s, created_by = %s
                   where plan = %s and company = %s""", to_user, note.strip(), row["owner"], by["id"], active, company)
    audit.log(cur, by["name"], "owner_changed_by_hand", "company", company, {"plan": active, "to": to_user, "from": row["owner"],
              "role": role, "note": note.strip()}, actor_id=by["id"])
    snapshot(cur, active)
    dropped = False
    sched = scheduled_plan(cur)
    if sched and role in moves:
        dropped = record_hand_change(cur, sched["id"], company, role, source="market_desk", to_user=to_user, by_name=by["name"], note=note.strip())
        if dropped:
            audit.log(cur, by["name"], "scheduled_move_dropped", "company", company, {"plan": sched["id"], "role": role}, actor_id=by["id"])
    elif sched:
        # Already dropped by an earlier hand change: the start date keeps the latest choice, not the first one.
        db.run(cur, """update plan_hand_changes set source = 'market_desk', to_user = %s, by_name = %s, note = %s, at = app_now()
                       where plan = %s and company = %s and role = %s""", to_user, by["name"], note.strip(), sched["id"], company, role)
    from . import crm
    crm.queue_hand_change(cur, active, company, role, to_user, dropped)
    return {"role": role, "dropped_from_schedule": dropped}


def sync_hand_changes(cur) -> int:
    """Asks the CRM which accounts a person moved by hand since the plan was scheduled. A CRM that cannot say, or does not
    answer, leaves what is recorded as it is: on the start date the CRM still refuses to overwrite them (`changed_by_hand`)."""
    s = scheduled_plan(cur)
    from . import crm
    if s is None or not crm.enabled() or not crm.supports_by_hand():
        return 0
    try:
        rows = crm.by_hand(s["effective_on"])
    except crm.CrmDown as exc:
        log.warning("could not read the CRM's hand changes: %s", exc)
        return 0
    ids = {r["primary_domain"].lower(): r["id"] for r in db.all(cur, "select id, primary_domain from companies where primary_domain = any(%s)",
                                                               [str(r.get("account_domain") or "").lower() for r in rows])}
    users = {r["email"].lower(): r["id"] for r in db.all(cur, "select id, email from users")}
    n = 0
    for r in rows:
        c = ids.get(str(r.get("account_domain") or "").lower())
        role = "sdr" if r.get("role") == "sdr" else "owner"
        if c is None:
            continue
        if not db.val(cur, "select 1 from plan_hand_changes where plan = %s and company = %s and role = %s", s["id"], c, role):
            n += record_hand_change(cur, s["id"], c, role, source="crm_desk", to_user=users.get(str(r.get("owner_email") or "").lower()),
                                    by_name=r.get("by"), note=r.get("note"))
    return n


def reconcile_hand_changes(cur, plan_id: int) -> int:
    """On the start date: an account a person moved by hand keeps the owner it has, in this desk's plan too. Its assignment takes
    the person's choice (or, when this desk does not know that person, the owner it had), never the one the plan drafted."""
    n = 0
    old = db.val(cur, "select id from territory_plans where status = 'active'")
    for h in hand_changes(cur, plan_id):
        keep = h["to_user"] or (roles_by_company(cur, old).get(h["company"], (None, None))[1 if h["role"] == "sdr" else 0] if old else None)
        planned = db.one(cur, "select owner from assignments where plan = %s and company = %s", plan_id, h["company"])
        if keep is None or planned is None:
            continue
        kind = db.val(cur, "select role from users where id = %s", keep)
        owner_kind = db.val(cur, "select role from users where id = %s", planned["owner"])
        if (h["role"] == "sdr") != (kind == "sdr") or (h["role"] == "sdr") != (owner_kind == "sdr"):
            continue                      # the assignment holds the other seat; the books still leave this role alone
        db.run(cur, """update assignments set owner = %s, reason_code = 'manual', note = %s, moved_from = %s
                       where plan = %s and company = %s""", keep,
               f"Changed by hand{' by ' + h['by_name'] if h['by_name'] else ''}: the plan no longer moves it", h["planned_owner"], plan_id, h["company"])
        audit.log(cur, "system", "owner_kept_by_hand", "company", h["company"], {"plan": plan_id, "kept": keep, "planned": h["planned_owner"],
                  "role": h["role"]})
        n += 1
    if n:
        snapshot(cur, plan_id)
    return n


def activation_preview(cur, plan_id: int, by: dict) -> dict:
    """What pressing Activate does, in counts, before it is pressed."""
    from . import crm
    plan = db.one(cur, "select p.*, a.name as author_name from territory_plans p join users a on a.id = p.author where p.id = %s", plan_id)
    if plan is None:
        raise ValueError("No such plan.")
    active = db.one(cur, "select id, name from territory_plans where status = 'active'")
    ch = what_changes(cur, plan_id)
    names = {u["id"]: u["name"] for u in db.all(cur, "select id, name from users")}
    ids = sorted(set(ch["gains"]) | set(ch["losses"]), key=lambda k: names[k])
    today = db.val(cur, "select app_now()::date")
    why = None
    if plan["status"] != "draft":
        why = "Only a draft plan can be activated."
    elif by["role"] != "manager" or plan["author"] == by["id"]:
        why = "A manager other than the author activates it."
    elif plan["drafted_from"] and plan["drafted_from"] != (active or {}).get("id"):
        why = "The active plan changed after these moves were drafted."
    elif ch["crossing"]:
        why = f"{len(ch['crossing'])} open deals would change owner without a note."
    sched = scheduled_plan(cur)
    if why is None and sched:
        why = f"A plan is scheduled for {sched['effective_on']:%-d %b %Y}: cancel it first."
    return {"scheduled_changes": len(scheduled_moves_for(cur, plan_id, active and active["id"])), "starts_later": plan["effective_on"] > today,
            "id": plan_id, "name": plan["name"], "status": plan["status"], "effective_on": plan["effective_on"], "today": today,
            "replaces": active and active["name"], "owner_changes": ch["changes"], "changes_hands": ch["owner_changes"],
            "crossing": len(ch["crossing"]),
            "people": [{"name": names[k], "gains": ch["gains"].get(k, 0), "losses": ch["losses"].get(k, 0)} for k in ids],
            "crm": crm.enabled(), "batches": crm.batch_count(cur, plan_id), "can_activate": why is None, "blocked": why}


def _rollback_target(cur) -> tuple[dict, dict]:
    _refuse_while_scheduled(cur)
    cur_plan = db.one(cur, "select * from territory_plans where status = 'active' for update")
    if not cur_plan or not cur_plan["replaced"]:
        raise ValueError("There is no earlier plan to go back to.")
    prev = db.one(cur, "select * from territory_plans where id = %s", cur_plan["replaced"])
    return cur_plan, prev


def rollback_preview(cur, by: dict) -> dict:
    from . import crm
    cur_plan = db.one(cur, "select * from territory_plans where status = 'active'")
    sched = scheduled_plan(cur)
    if sched:
        return {"available": False, "blocked": f"A plan is scheduled for {sched['effective_on']:%-d %b %Y}: cancel it first."}
    if not cur_plan or not cur_plan["replaced"]:
        return {"available": False}
    prev = db.one(cur, "select * from territory_plans where id = %s", cur_plan["replaced"])
    changes = db.val(cur, """select count(*) from assignments a left join assignments b on b.plan = %s and b.company = a.company
                             where a.plan = %s and a.owner is distinct from b.owner""", prev["id"], cur_plan["id"])
    st = crm.send_state(cur, cur_plan["id"])
    return {"available": True, "can_roll_back": by["role"] == "manager", "from": cur_plan["name"], "to": prev["name"],
            "owner_changes": changes, "crm": crm.enabled(), "sent_batches": st["sent"], "sent_accounts": st["sent_accounts"],
            "waiting_batches": st["waiting"], "batches": crm.batch_count(cur, prev["id"])}


def rollback(cur, by: dict, reason: str = "") -> int:
    """Deactivate the active plan and bring back the one it replaced. Waiting batches are cancelled; the earlier plan's
    books are sent in their place. Batches the CRM already took stay there until the earlier plan's books overwrite them."""
    if by["role"] != "manager":
        raise PermissionError("A manager rolls a plan back.")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ValueError("A rollback needs a reason.")
    cur_plan, prev = _rollback_target(cur)
    rows = db.all(cur, """select a.company, a.owner as from_owner, b.owner as to_owner from assignments a
                          left join assignments b on b.plan = %s and b.company = a.company
                          where a.plan = %s and a.owner is distinct from b.owner""", prev["id"], cur_plan["id"])
    db.run(cur, """update territory_plans set status = 'retired', rolled_back_by = %s, rolled_back_at = app_now(), rolled_back_reason = %s
                   where id = %s""", by["id"], reason, cur_plan["id"])
    db.run(cur, "update territory_plans set status = 'active', restored_by = %s, restored_at = app_now() where id = %s",
           by["id"], prev["id"])
    for r in rows:
        audit.log(cur, by["name"], "owner_moved", "company", r["company"], {"plan": prev["id"], "from": r["from_owner"],
                  "to": r["to_owner"], "rollback": True}, actor_id=by["id"])
    audit.log(cur, by["name"], "plan_rolled_back", "plan", cur_plan["id"], {"restored": prev["id"], "changes": len(rows), "reason": reason}, actor_id=by["id"])
    notices.rolled_back(cur, "plan_rolled_back", by, subject=cur_plan["name"], restored=prev["name"], reason=reason, path="/territories")
    # A test that started while the rolled-back plan was active keeps its worked accounts.
    for t in db.all(cur, "select id from segment_tests where status = 'running'"):
        place_test_members(cur, t["id"])
    from . import crm
    crm.cancel_unsent(cur, cur_plan["id"])
    crm.queue_plan(cur, prev["id"])
    return prev["id"]


def copy_with_moves(cur, *, name: str, author: int, on: date, moves: list[dict], note: str, by: int) -> int:
    """A draft plan that is the active plan with only these accounts moved: nothing else is assigned afresh, so
    activating it changes exactly the accounts listed. moves: [{company, to_owner, to_territory}]."""
    active = db.one(cur, "select * from territory_plans where status = 'active'")
    if not active:
        raise ValueError("There is no active plan to move accounts in.")
    vid = db.val(cur, "select id from icp_versions where status = 'published'")
    pid = db.val(cur, """insert into territory_plans (name, status, based_on, author, effective_on, balance_report, drafted_from)
                         values (%s, 'draft', %s, %s, %s, %s, %s) returning id""", name, vid, author, on,
                 J(active["balance_report"] or {}), active["id"])
    db.run(cur, """insert into territories (plan, key, label, rule, owner, paired_ae)
                   select %s, key, label, rule, owner, paired_ae from territories where plan = %s""", pid, active["id"])
    db.run(cur, """insert into assignments (plan, company, territory, owner, reason_code, note, moved_from, created_by)
                   select %s, a.company, n.id, a.owner, a.reason_code, a.note, a.moved_from, a.created_by
                   from assignments a left join territories o on o.id = a.territory
                   left join territories n on n.plan = %s and n.key = o.key where a.plan = %s""", pid, pid, active["id"])
    for m in moves:
        cur_row = db.one(cur, "select * from assignments where plan = %s and company = %s", pid, m["company"])
        terr = cur_row["territory"] if cur_row else None
        if m.get("to_territory"):
            terr = db.val(cur, "select id from territories where plan = %s and key = %s", pid, m["to_territory"]) or terr
        db.run(cur, """insert into assignments (plan, company, territory, owner, reason_code, note, moved_from, created_by)
                       values (%s,%s,%s,%s,'manual',%s,%s,%s)
                       on conflict (plan, company) do update set owner = excluded.owner, territory = excluded.territory,
                       reason_code = 'manual', note = excluded.note, moved_from = excluded.moved_from, created_by = excluded.created_by""",
               pid, m["company"], terr, m["to_owner"], note, cur_row["owner"] if cur_row else None, by)
    snapshot(cur, pid)
    audit.log(cur, "user", "plan_drafted", "plan", pid, {"name": name, "from_plan": active["id"], "moves": len(moves)}, actor_id=author)
    return pid


def hiring_gap(cur, plan_id: int) -> dict:
    """A and B prospects in served regions the plan cannot cover at current hours, and the people that would take."""
    s = settings(cur)
    hours = s["hours_per_tier"]
    plan = db.one(cur, "select * from territory_plans where id = %s", plan_id)
    rows = db.all(cur, """
        select f.tier, count(*) as n from companies c join account_fit f on f.company = c.id and f.icp_version = %s
        where c.lifecycle = 'prospect' and f.tier in ('A','B') and f.judged and c.region = any(%s) and not c.sole_trader
          and f.segment in (select jsonb_array_elements_text(t.rule->'segments') from territories t where t.plan = %s)
          and not exists (select 1 from assignments a where a.plan = %s and a.company = c.id)
          and not exists (select 1 from segment_test_members m join segment_tests t on t.id = m.test
                          where m.company = c.id and m.grp = 'held_back' and t.status = 'running')
        group by f.tier""", plan["based_on"], C.SERVED_REGIONS, plan_id, plan_id)
    by = {r["tier"]: r["n"] for r in rows}
    need = sum(by.get(t, 0) * float(hours[t]) for t in ("A", "B"))
    per = float(db.val(cur, "select avg(selling_hours_month) from users where role = 'sdr' and active") or 100)
    return {"accounts": sum(by.values()), "by_tier": by, "hours": round(need), "people": math.ceil(need / per),
            "hours_per_person": per}


def capacity_accounts(cur, plan_id: int) -> float:
    """Accounts the plan's people can work in 12 months: accounts they can hold at once at the hours their current book
    uses per account, times the turns a year (12 / account_cycle_months)."""
    # Hours per account from the plan's own A and B accounts at their tier hours, test accounts left out.
    hours = settings(cur)["hours_per_tier"]
    r = db.one(cur, """select sum(hours_available) as avail from capacity_snapshots where plan = %s""", plan_id)
    mix = db.all(cur, """select f.tier, count(*) as n from assignments a join territory_plans p on p.id = a.plan
                         join account_fit f on f.company = a.company and f.icp_version = p.based_on
                         where a.plan = %s and a.reason_code <> 'test' and f.tier in ('A','B') group by f.tier""", plan_id)
    n = sum(m["n"] for m in mix)
    if not r or not n:
        return 0.0
    per = sum(m["n"] * float(hours[m["tier"]]) for m in mix) / n
    turns = 12 / float(settings(cur).get("account_cycle_months", 3))
    return float(r["avail"]) / per * turns if per else 0.0


def release_test(cur, test_id: int) -> int:
    """A test that is read or stopped hands its worked accounts back: they leave every live plan, and the next plan
    places them by its rules."""
    n = db.run(cur, """delete from assignments a using territory_plans p, segment_test_members m
                       where p.id = a.plan and p.status in ('active', 'scheduled', 'draft') and a.reason_code = 'test'
                         and m.test = %s and m.company = a.company and m.grp = 'worked'""", test_id)
    # The freed hours are filled again by the plan's own rules, from what is true today; hand moves stay.
    today = db.val(cur, "select app_now()::date")
    for p in db.all(cur, "select id, effective_on from territory_plans where status in ('active', 'scheduled', 'draft')"):
        assign(cur, p["id"], on=p["effective_on"], as_of=today)
    return n


def draft_from_active(cur, by: dict, name: str, on) -> int:
    """RevOps drafts the next plan from the active plan's territories, assigned afresh under the published profile."""
    if by["role"] != "revops":
        raise PermissionError("RevOps drafts plans.")
    active = db.one(cur, "select * from territory_plans where status = 'active'")
    if not active:
        raise ValueError("There is no active plan to start from.")
    terrs = [{"key": t["key"], "label": t["label"], "region_groups": t["rule"]["region_groups"],
              "segments": t["rule"]["segments"], "people": t["rule"]["people"], "ae": t["paired_ae"]}
             for t in db.all(cur, "select * from territories where plan = %s order by id", active["id"])]
    return build_plan(cur, name=name, author=by["id"], territories=terrs, on=on)


@jobs.handler("apply_scheduled_plan")
def _apply_scheduled(cur, payload: dict) -> None:
    """Hourly while a plan is scheduled; started again by the next scheduling."""
    from datetime import timedelta
    sync_hand_changes(cur)
    apply_scheduled(cur)
    # No dedupe key: this job is still "running" now, and a key would make the next one a silent no-op.
    if scheduled_plan(cur) and not db.val(cur, "select 1 from jobs where kind = 'apply_scheduled_plan' and status = 'queued'"):
        jobs.enqueue(cur, "apply_scheduled_plan", {}, delay=timedelta(hours=1))
