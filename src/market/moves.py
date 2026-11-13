"""Territory move proposals. A manager or RevOps person proposes moving accounts to another owner (and, if wanted, another
territory) with a reason and an effective date. Someone else decides. An approval drafts a plan that is the active plan
with only those accounts moved; a manager activates it as any plan, and the activation sends the books to the CRM."""
from __future__ import annotations

from datetime import date

from . import audit, db, territories

MAX_ACCOUNTS = 200


def _user(cur, uid: int) -> dict | None:
    return db.one(cur, "select id, name, role, active from users where id = %s", uid)


def propose(cur, by: dict, *, companies: list[int], to_owner: int, reason: str, effective_on: date,
            to_territory: str | None = None) -> int:
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
    pid = db.val(cur, """insert into move_proposals (to_owner, to_territory, reason, effective_on, proposed_by)
                         values (%s,%s,%s,%s,%s) returning id""", to_owner, to_territory or None, reason, effective_on, by["id"])
    for r in rows:
        db.run(cur, "insert into move_proposal_accounts (proposal, company, from_owner) values (%s,%s,%s)", pid, r["id"], r["owner"])
    audit.log(cur, by["name"], "move_proposed", "move_proposal", pid,
              {"accounts": len(rows), "to": to_owner, "effective_on": str(effective_on), "reason": reason}, actor_id=by["id"])
    return pid


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


def approve(cur, pid: int, by: dict) -> int:
    """Approve: draft the plan. Returns the new plan's id."""
    p = _open(cur, pid, by)
    accounts = db.all(cur, "select company from move_proposal_accounts where proposal = %s order by company", pid)
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


def reject(cur, pid: int, by: dict, note: str) -> None:
    _open(cur, pid, by)
    note = (note or "").strip()
    if len(note) < 3:
        raise ValueError("A rejection needs a reason.")
    db.run(cur, "update move_proposals set status = 'rejected', decided_by = %s, decided_at = app_now(), decision_note = %s where id = %s",
           by["id"], note, pid)
    audit.log(cur, by["name"], "move_rejected", "move_proposal", pid, {"note": note}, actor_id=by["id"])


def listing(cur) -> list[dict]:
    return db.all(cur, """select p.id, p.status, p.reason, p.effective_on, p.proposed_at, p.decided_at, p.plan,
                          u.name as to_owner, a.name as proposed_by, d.name as decided_by,
                          (select count(*) from move_proposal_accounts x where x.proposal = p.id) as accounts
                          from move_proposals p join users u on u.id = p.to_owner join users a on a.id = p.proposed_by
                          left join users d on d.id = p.decided_by
                          order by case p.status when 'open' then 0 else 1 end, p.id desc""")


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
            "to_territory": t, "proposed_by": p["proposer"], "proposed_at": p["proposed_at"], "decided_by": p["decider"],
            "decided_at": p["decided_at"], "decision_note": p["decision_note"], "plan": p["plan"], "plan_name": p["plan_name"],
            "plan_status": p["plan_status"], "accounts": rows[:200], "count": len(rows),
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
