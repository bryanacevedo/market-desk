"""Territory move proposals. A manager or RevOps person proposes moving accounts to another owner (and, if wanted, another
territory) with a reason and an effective date. Someone else decides.

An approval with no plan scheduled drafts a plan that is the active plan with only those accounts moved; a manager activates it
as any plan, and the activation sends the books to the CRM. An approval while a plan is scheduled cannot draft one (a second plan
cannot be activated until the scheduled one starts), so the moves are kept as scheduled moves (decision 73): they apply to the
plan in effect on the proposal's date, and are carried into the scheduled plan when it starts on or after that date, so the
accounts move on the date the proposal named."""
from __future__ import annotations

from datetime import date, timedelta

from . import audit, db, jobs, territories
from . import catalog as C

MAX_ACCOUNTS = 200


def _user(cur, uid: int) -> dict | None:
    return db.one(cur, "select id, name, role, active from users where id = %s", uid)


def propose(cur, by: dict, *, companies: list[int], to_owner: int, reason: str, effective_on: date,
            to_territory: str | None = None, by_territory: str | None = None) -> int:
    if by["role"] not in ("revops", "manager"):
        raise PermissionError("A manager or RevOps proposes a move.")
    reason = (reason or "").strip()
    if len(reason) < 3:
        raise ValueError("A move needs a reason.")
    companies = list(dict.fromkeys(companies))
    if not companies or len(companies) > MAX_ACCOUNTS:
        raise ValueError(f"Propose between 1 and {MAX_ACCOUNTS} accounts at a time.")
    today = db.val(cur, "select app_now()::date")
    if effective_on < today:
        raise ValueError("The effective date cannot be in the past.")
    owner = _user(cur, to_owner)
    if not owner or not owner["active"] or owner["role"] not in ("ae", "sdr"):
        raise ValueError("Choose an AE or an SDR to take the accounts.")
    active = db.one(cur, "select id from territory_plans where status = 'active'")
    if not active:
        raise ValueError("There is no active plan to move accounts in.")
    if to_territory:
        t = db.one(cur, "select rule, paired_ae from territories where plan = %s and key = %s", active["id"], to_territory)
        if not t:
            raise ValueError("That territory is not in the active plan.")
        if to_owner not in t["rule"]["people"] and to_owner != t["paired_ae"]:
            raise ValueError(f"{owner['name']} is not in that territory.")
    rows = db.all(cur, """select c.id, c.name, a.owner from companies c left join assignments a on a.plan = %s and a.company = c.id
                          where c.id = any(%s) and not c.sole_trader""", active["id"], companies)
    if len(rows) != len(companies):
        raise ValueError("One of those accounts is not in the plan.")
    for r in rows:
        if r["owner"] == to_owner:
            raise ValueError(f"{r['name']} already belongs to {owner['name']}.")
    busy = db.one(cur, """select c.name from move_proposal_accounts x join move_proposals p on p.id = x.proposal and p.status = 'open'
                          join companies c on c.id = x.company where x.company = any(%s) limit 1""", companies)
    if busy:
        raise ValueError(f"{busy['name']} is already in an open proposal.")
    waiting = db.one(cur, """select c.name from scheduled_moves m join companies c on c.id = m.company
                             where m.company = any(%s) and m.status = 'pending' limit 1""", companies)
    if waiting:
        raise ValueError(f"{waiting['name']} has an approved move waiting for its date.")
    pid = db.val(cur, """insert into move_proposals (to_owner, to_territory, reason, effective_on, proposed_by, by_territory)
                         values (%s,%s,%s,%s,%s,%s) returning id""", to_owner, to_territory or None, reason, effective_on, by["id"],
                         by_territory)
    for r in rows:
        db.run(cur, "insert into move_proposal_accounts (proposal, company, from_owner) values (%s,%s,%s)", pid, r["id"], r["owner"])
    audit.log(cur, by["name"], "move_proposed", "move_proposal", pid,
              {"accounts": len(rows), "to": to_owner, "effective_on": str(effective_on), "reason": reason,
               "by_territory": by_territory}, actor_id=by["id"])
    return pid


def rule_matches(cur, territory: str, to_owner: int | None = None) -> dict:
    """The accounts a territory's rule (its regions and segments) holds in the active plan, counted for a move to one person.
    Accounts that already belong to the new owner, or sit in an open proposal, are left out and counted apart."""
    plan = db.one(cur, "select id from territory_plans where status = 'active'")
    if not plan:
        raise ValueError("There is no active plan to move accounts in.")
    t = db.one(cur, "select id, label, rule from territories where plan = %s and key = %s", plan["id"], territory)
    if not t:
        raise ValueError("That territory is not in the active plan.")
    rows = db.all(cur, """select c.id, a.owner,
                          (exists (select 1 from move_proposal_accounts x join move_proposals p on p.id = x.proposal and p.status = 'open'
                                   where x.company = c.id)
                           or exists (select 1 from scheduled_moves m where m.company = c.id and m.status = 'pending')) as busy
                          from assignments a join companies c on c.id = a.company
                          where a.plan = %s and a.territory = %s and not c.sole_trader order by c.id""", plan["id"], t["id"])
    already = [r for r in rows if to_owner and r["owner"] == to_owner]
    busy = [r for r in rows if r not in already and r["busy"]]
    ids = [r["id"] for r in rows if r not in already and r not in busy]
    return {"territory": t["label"], "regions": t["rule"].get("region_groups", []), "segments": [C.SEGMENT_LABEL.get(k, k) for k in t["rule"].get("segments", [])],
            "capacity": capacity_after(cur, to_owner, ids) if to_owner and ids else None, "matched": len(rows), "already_there": len(already), "in_open_proposal": len(busy), "eligible": len(ids),
            "proposals": -(-len(ids) // MAX_ACCOUNTS), "cap": MAX_ACCOUNTS, "ids": ids}


def propose_by_territory(cur, by: dict, *, territory: str, to_owner: int, reason: str, effective_on: date,
                         to_territory: str | None = None) -> list[int]:
    """One proposal for every account the territory's rule holds, or several of at most 200 when it holds more.
    Each one is decided on its own, by the same path as a list of accounts."""
    m = rule_matches(cur, territory, to_owner)
    if not m["ids"]:
        raise ValueError("No accounts in that territory are left to move to this person.")
    ids, parts = m["ids"], m["proposals"]
    out = []
    for i in range(parts):
        chunk = ids[i * MAX_ACCOUNTS:(i + 1) * MAX_ACCOUNTS]
        suffix = f" (part {i + 1} of {parts})" if parts > 1 else ""
        out.append(propose(cur, by, companies=chunk, to_owner=to_owner, reason=reason.strip()[:500 - len(suffix)] + suffix,
                           effective_on=effective_on, to_territory=to_territory, by_territory=m["territory"]))
    return out


def can_decide(proposal: dict, by: dict) -> bool:
    """A different person decides: a manager, or RevOps when a manager proposed."""
    if proposal["status"] != "open" or proposal["proposed_by"] == by["id"]:
        return False
    return by["role"] == "manager" or (by["role"] == "revops" and proposal["proposer_role"] == "manager")


def _open(cur, pid: int, by: dict) -> dict:
    p = db.one(cur, """select p.*, u.role as proposer_role from move_proposals p join users u on u.id = p.proposed_by
                       where p.id = %s for update of p""", pid)
    if p is None:
        raise ValueError("No such proposal.")
    if p["status"] != "open":
        raise ValueError("That proposal is already decided.")
    if p["proposed_by"] == by["id"]:
        raise PermissionError("Someone other than the proposer decides.")
    if not can_decide(p, by):
        raise PermissionError("A manager decides a move that RevOps proposed.")
    return p


def approve(cur, pid: int, by: dict) -> int | None:
    """Approve. With no plan scheduled, draft the plan and return its id. While a plan is scheduled, keep the moves as scheduled
    moves (decision 73) and return None: nothing is left for a manager to activate."""
    p = _open(cur, pid, by)
    accounts = db.all(cur, "select company from move_proposal_accounts where proposal = %s order by company", pid)
    sched = territories.scheduled_plan(cur)
    if sched:
        return _approve_scheduled(cur, p, accounts, by, sched)
    owner = _user(cur, p["to_owner"])
    # The plan's author is the RevOps person of the pair, so a manager other than the author can activate it.
    author = p["proposed_by"] if p["proposer_role"] == "revops" else (by["id"] if by["role"] == "revops" else p["proposed_by"])
    name = f"Moves to {owner['name']}, {p['effective_on'].strftime('%d %b %Y').lstrip('0')}"
    if db.val(cur, "select count(*) from territory_plans where name = %s", name):
        name += f" ({pid})"
    plan = territories.copy_with_moves(cur, name=name, author=author, on=p["effective_on"], note=p["reason"], by=author,
                                       moves=[{"company": a["company"], "to_owner": p["to_owner"], "to_territory": p["to_territory"]}
                                              for a in accounts])
    db.run(cur, "update move_proposals set status = 'approved', decided_by = %s, decided_at = app_now(), plan = %s where id = %s",
           by["id"], plan, pid)
    audit.log(cur, by["name"], "move_approved", "move_proposal", pid, {"plan": plan, "accounts": len(accounts)}, actor_id=by["id"])
    return plan


def _approve_scheduled(cur, p: dict, accounts: list[dict], by: dict, sched: dict) -> None:
    """Approval while a plan is scheduled. The moves wait for the proposal's date and then apply to the plan in effect; when the
    scheduled plan starts on or after that date it carries them too, so they survive its start. An account a person already moved
    by hand while the plan was scheduled keeps that person's choice in the scheduled plan (decision 57)."""
    pid, on = p["id"], p["effective_on"]
    moves = [{"company": a["company"], "to_owner": p["to_owner"], "to_territory": p["to_territory"]} for a in accounts]
    db.run(cur, "update move_proposals set status = 'approved', decided_by = %s, decided_at = app_now() where id = %s", by["id"], pid)
    for m in moves:
        db.run(cur, """insert into scheduled_moves (proposal, company, to_owner, to_territory, effective_on) values (%s,%s,%s,%s,%s)""",
               pid, m["company"], m["to_owner"], m["to_territory"], on)
    carried = 0
    if on <= sched["effective_on"]:
        role = "sdr" if db.val(cur, "select role from users where id = %s", p["to_owner"]) == "sdr" else "owner"
        held = {h["company"] for h in territories.hand_changes(cur, sched["id"]) if h["role"] == role}
        carried = len(territories.place_moves(cur, sched["id"], [m for m in moves if m["company"] not in held],
                                              note=p["reason"], by=p["proposed_by"]))
    audit.log(cur, by["name"], "move_approved", "move_proposal", pid,
              {"plan": None, "accounts": len(accounts), "effective_on": str(on), "carried_into": sched["id"] if on <= sched["effective_on"] else None,
               "carried": carried}, actor_id=by["id"])
    from . import crm
    today = db.val(cur, "select app_now()::date")
    if on <= today:
        apply_due(cur)
    else:
        crm.queue_move_schedule(cur, pid, moves, on)
        jobs.enqueue(cur, "apply_scheduled_moves", {}, dedupe_key="apply_scheduled_moves")
    return None


def apply_due(cur) -> int:
    """Applies every scheduled move whose date has come to the plan in effect, one proposal at a time: the owner changes, the
    audit log says so, the hours are counted again and the CRM is sent the books for those accounts. An account whose owner a
    person changed by hand since the approval is left as that person set it. Returns how many accounts moved."""
    active = db.val(cur, "select id from territory_plans where status = 'active'")
    if active is None:
        return 0
    n = 0
    for p in db.all(cur, """select p.id, p.reason, p.decided_by, p.to_owner from move_proposals p
                            where exists (select 1 from scheduled_moves m where m.proposal = p.id and m.status = 'pending'
                                          and m.effective_on <= app_now()::date) order by p.id"""):
        rows = db.all(cur, """select id, company, to_owner, to_territory from scheduled_moves
                              where proposal = %s and status = 'pending' and effective_on <= app_now()::date for update""", p["id"])
        done = territories.place_moves(cur, active, [{"company": r["company"], "to_owner": r["to_owner"], "to_territory": r["to_territory"]} for r in rows],
                                       note=p["reason"], by=p["decided_by"])
        by = _user(cur, p["decided_by"])
        for d in done:
            audit.log(cur, by["name"], "owner_moved", "company", d["company"], {"plan": active, "from": d["from_owner"], "to": d["to_owner"],
                                                                               "proposal": p["id"]}, actor_id=by["id"])
        db.run(cur, "update scheduled_moves set status = 'applied', applied_at = app_now() where id = any(%s)", [r["id"] for r in rows])
        if done:
            from . import crm
            crm.queue_moves(cur, active, [d["company"] for d in done], p["id"])
        n += len(done)
    return n


@jobs.handler("apply_scheduled_moves")
def _apply_scheduled_moves(cur, payload: dict) -> None:
    """Hourly while any approved move waits for its date; started again by the next approval."""
    apply_due(cur)
    # No dedupe key: this job is still "running" now, and a key would make the next one a silent no-op.
    if db.val(cur, "select 1 from scheduled_moves where status = 'pending' limit 1") and \
            not db.val(cur, "select 1 from jobs where kind = 'apply_scheduled_moves' and status = 'queued'"):
        jobs.enqueue(cur, "apply_scheduled_moves", {}, delay=timedelta(hours=1))


def drop_for_hand_change(cur, company: int, role: str) -> int:
    """A person moved this account's owner by hand after a move was approved for it: the waiting move is dropped, so the hand
    change is not undone on the date. Only a move for the same seat (AE or SDR) is dropped."""
    return db.run(cur, """update scheduled_moves m set status = 'dropped', applied_at = app_now(),
                          dropped_why = 'Changed by hand before its date'
                          where m.company = %s and m.status = 'pending'
                            and (select (u.role = 'sdr') from users u where u.id = m.to_owner) = (%s = 'sdr')""", company, role)


def delivery(cur, pid: int) -> dict | None:
    """When an approved proposal's owners reached CRM Desk, from the outbox: None with no CRM set (nothing is sent)."""
    from . import crm
    return crm.delivery_state(cur, f"move:{pid}") if crm.enabled() else None


def capacity_after(cur, to_owner: int, companies: list[int]) -> dict | None:
    """The hours a person would hold after taking these accounts, against the hours they have (decision 74): their book in the
    plan in effect plus the tier hours of each account that is not already theirs. It informs; nothing refuses a move for it."""
    plan = db.one(cur, "select id, based_on, effective_on from territory_plans where status = 'active'")
    user = db.one(cur, "select id, name, selling_hours_month, started_on, ramp_months from users where id = %s", to_owner)
    if not plan or not user:
        return None
    hours = territories.settings(cur)["hours_per_tier"]
    now = db.one(cur, "select hours_required, hours_available from capacity_snapshots where plan = %s and user_id = %s", plan["id"], to_owner)
    have = float(now["hours_required"]) if now else 0.0
    avail = float(now["hours_available"]) if now else round(float(user["selling_hours_month"]) * territories.effective_fte(user, plan["effective_on"]), 1)
    rows = db.all(cur, """select f.tier, a.owner from companies c join account_fit f on f.company = c.id and f.icp_version = %s
                          left join assignments a on a.company = c.id and a.plan = %s where c.id = any(%s)""", plan["based_on"], plan["id"], companies)
    add = sum(float(hours.get(r["tier"], 0)) for r in rows if r["owner"] != to_owner)
    after = round(have + add, 1)
    return {"person": user["name"], "hours_now": round(have, 1), "hours_after": after, "hours_available": round(avail, 1),
            "over": after > avail + 0.05}


def pending_count(cur) -> int:
    return db.val(cur, "select count(*) from scheduled_moves where status = 'pending'")


def move_state(cur, pid: int) -> dict:
    """What became of an approved proposal's accounts: moved, still waiting for the date, or kept as a person set them."""
    rows = db.all(cur, "select status, count(*) as n, min(effective_on) as due from scheduled_moves where proposal = %s group by status", pid)
    by = {r["status"]: r for r in rows}
    return {"moved": by["applied"]["n"] if "applied" in by else 0, "waiting": by["pending"]["n"] if "pending" in by else 0,
            "kept": by["dropped"]["n"] if "dropped" in by else 0, "on": by["pending"]["due"] if "pending" in by else None,
            "tracked": bool(rows)}


def reject(cur, pid: int, by: dict, note: str) -> None:
    _open(cur, pid, by)
    note = (note or "").strip()
    if len(note) < 3:
        raise ValueError("A rejection needs a reason.")
    db.run(cur, "update move_proposals set status = 'rejected', decided_by = %s, decided_at = app_now(), decision_note = %s where id = %s",
           by["id"], note, pid)
    audit.log(cur, by["name"], "move_rejected", "move_proposal", pid, {"note": note}, actor_id=by["id"])


def force_note(cur, plan_status: str | None, plan_name: str | None, pid: int | None = None) -> str | None:
    """What an approved proposal is doing, in words, from the server's real state; None when it is in force (or nothing to say).
    With a plan scheduled at approval the accounts wait for the proposal's date (decision 73). Otherwise approving only drafts
    the plan, and a draft cannot be activated while another plan is scheduled, so the note says which of the two holds."""
    if pid is not None and plan_status is None:
        st = move_state(cur, pid)
        if st["waiting"]:
            return f"Approved, not in force: the accounts move on {st['on']:%-d %b %Y}."
        return None
    if plan_status == "scheduled":
        return f"Approved, not in force: {plan_name} starts on its start date."
    if plan_status != "draft":
        return None
    s = territories.scheduled_plan(cur)
    if s:
        return f"Approved, not in force: cancel the plan starting {s['effective_on']:%-d %b %Y} first, or activate after it starts."
    return f"Approved, not in force: a manager activates {plan_name}."


def listing(cur) -> list[dict]:
    rows = db.all(cur, """select p.id, p.status, p.reason, p.effective_on, p.proposed_at, p.decided_at, p.plan,
                          u.name as to_owner, a.name as proposed_by, d.name as decided_by,
                          (select count(*) from move_proposal_accounts x where x.proposal = p.id) as accounts,
                          pl.name as plan_name, pl.status as plan_status
                          from move_proposals p join users u on u.id = p.to_owner join users a on a.id = p.proposed_by
                          left join users d on d.id = p.decided_by left join territory_plans pl on pl.id = p.plan
                          order by case p.status when 'open' then 0 else 1 end, p.id desc""")
    for r in rows:
        r["force_note"] = force_note(cur, r["plan_status"], r["plan_name"], r["id"]) if r["status"] == "approved" else None
        r["moves"] = move_state(cur, r["id"]) if r["status"] == "approved" and r["plan"] is None else None
        r["delivery"] = delivery(cur, r["id"]) if r["status"] == "approved" else None
    return rows


def detail(cur, pid: int, by: dict) -> dict | None:
    p = db.one(cur, """select p.*, u.name as to_owner_name, a.name as proposer, a.role as proposer_role, d.name as decider,
                       pl.name as plan_name, pl.status as plan_status from move_proposals p join users u on u.id = p.to_owner
                       join users a on a.id = p.proposed_by left join users d on d.id = p.decided_by
                       left join territory_plans pl on pl.id = p.plan where p.id = %s""", pid)
    if not p:
        return None
    t = db.val(cur, """select t.label from territories t join territory_plans a on a.id = t.plan and a.status = 'active'
                       where t.key = %s""", p["to_territory"]) if p["to_territory"] else None
    rows = db.all(cur, """select c.id, c.name, c.primary_domain, f.tier, o.name as from_owner from move_proposal_accounts x
                          join companies c on c.id = x.company left join users o on o.id = x.from_owner
                          left join icp_versions v on v.status = 'published'
                          left join account_fit f on f.company = c.id and f.icp_version = v.id
                          where x.proposal = %s order by c.name""", pid)
    return {"id": p["id"], "status": p["status"], "reason": p["reason"], "effective_on": p["effective_on"], "to_owner": p["to_owner_name"],
            "to_territory": t, "by_territory": p["by_territory"], "proposed_by": p["proposer"], "proposed_at": p["proposed_at"], "decided_by": p["decider"],
            "decided_at": p["decided_at"], "decision_note": p["decision_note"], "plan": p["plan"], "plan_name": p["plan_name"],
            "plan_status": p["plan_status"], "force_note": force_note(cur, p["plan_status"], p["plan_name"], pid) if p["status"] == "approved" else None,
            "moves": move_state(cur, pid) if p["status"] == "approved" and p["plan"] is None else None,
            "delivery": delivery(cur, pid) if p["status"] == "approved" else None,
            "accounts": rows[:200], "count": len(rows),
            "can_decide": can_decide({**p, "proposer_role": p["proposer_role"]}, by)}


def candidates(cur, *, q: str = "", owner: int | None = None, only: int | None = None, limit: int = 30) -> list[dict]:
    """Accounts in the active plan to choose from: by name or domain, or everything one person owns."""
    plan = db.val(cur, "select id from territory_plans where status = 'active'")
    where, args = ["a.plan = %s", "not c.sole_trader"], [plan]
    q = (q or "").strip()
    if q:
        where.append("(c.name ilike %s or c.primary_domain ilike %s)")
        args += [f"%{q}%", f"%{q}%"]
    if owner:
        where.append("a.owner = %s")
        args.append(owner)
    if only:
        where.append("c.id = %s")
        args.append(only)
    if not q and not owner and not only:
        return []
    return db.all(cur, f"""select c.id, c.name, c.primary_domain, f.tier, u.name as owner, a.owner as owner_id
                           from assignments a join companies c on c.id = a.company left join users u on u.id = a.owner
                           left join icp_versions v on v.status = 'published'
                           left join account_fit f on f.company = c.id and f.icp_version = v.id
                           where {' and '.join(where)} order by f.score desc nulls last, c.name limit {int(limit)}""", *args)
