"""Erasure (docs/SPEC.md 13). Team members are the only people stored: erasing one scrubs their name and email, takes
them off every active plan through a manual move with a note, and records the erasure without the erased data.
A company's call notes, and the quotes taken from them, can be erased on request too."""
from __future__ import annotations

from . import audit, db, territories


def erase_user(cur, user_id: int, by: dict) -> dict:
    if by["role"] not in ("revops", "manager"):
        raise PermissionError("RevOps or a manager erases a team member.")
    u = db.one(cur, "select * from users where id = %s for update", user_id)
    if u is None or u["erased"]:
        raise ValueError("No such team member, or already erased.")
    if u["id"] == by["id"]:
        raise ValueError("Someone else erases you.")
    moved = 0
    for plan in db.all(cur, "select id, status from territory_plans where status in ('active', 'draft')"):
        rows = db.all(cur, """select a.company, a.territory, t.owner as lead, t.paired_ae from assignments a
                              left join territories t on t.id = a.territory where a.plan = %s and a.owner = %s""", plan["id"], user_id)
        for r in rows:
            to = r["lead"] if r["lead"] and r["lead"] != user_id else (r["paired_ae"] if r["paired_ae"] != user_id else None)
            db.run(cur, """update assignments set owner = %s, reason_code = 'manual', moved_from = null, created_by = %s,
                           note = 'Owner erased; moved to the territory lead' where plan = %s and company = %s""",
                   to, by["id"], plan["id"], r["company"])
            moved += 1
        db.run(cur, "delete from capacity_snapshots where plan = %s and user_id = %s", plan["id"], user_id)
        territories.snapshot(cur, plan["id"])
    db.run(cur, "update deals set owner = null where owner = %s", user_id)
    db.run(cur, "update companies set owner_id = null where owner_id = %s", user_id)
    db.run(cur, "update call_notes set author = null where author = %s", user_id)
    # Their name in the audit log and in notes on plan moves goes too.
    db.run(cur, "update audit_log set actor = 'Erased team member' where actor_id = %s or actor = %s", user_id, u["name"])
    for part in sorted({u["name"], u["name"].split()[0]}, key=len, reverse=True):
        db.run(cur, "update assignments set note = regexp_replace(note, %s, 'Erased team member', 'g') where note ~ %s",
               rf"\m{part}\M", rf"\m{part}\M")
        db.run(cur, "update notices set reason = regexp_replace(reason, %s, 'Erased team member', 'g') where reason ~ %s",
               rf"\m{part}\M", rf"\m{part}\M")
        db.run(cur, "update territory_plans set rolled_back_reason = regexp_replace(rolled_back_reason, %s, 'Erased team member', 'g') where rolled_back_reason ~ %s",
               rf"\m{part}\M", rf"\m{part}\M")
        db.run(cur, "update icp_versions set rolled_back_reason = regexp_replace(rolled_back_reason, %s, 'Erased team member', 'g') where rolled_back_reason ~ %s",
               rf"\m{part}\M", rf"\m{part}\M")
        db.run(cur, "update audit_log set detail = regexp_replace(detail::text, %s, 'Erased team member', 'g')::jsonb where detail::text ~ %s",
               rf"\m{part}\M", rf"\m{part}\M")
    db.run(cur, """update users set name = 'Erased team member', email = 'erased-' || id || '@erased.invalid',
                   active = false, erased = true where id = %s""", user_id)
    db.run(cur, "insert into erasures (kind, subject, by_user) values ('user', %s, %s)", str(user_id), by["id"])
    audit.log(cur, by["name"], "user_erased", "user", user_id, {"accounts_moved": moved}, actor_id=by["id"])
    return {"accounts_moved": moved}


def erase_company_notes(cur, company_id: int, by: dict) -> dict:
    if by["role"] not in ("revops", "manager"):
        raise PermissionError("RevOps or a manager erases notes.")
    rows = db.all(cur, """select q.id, q.text from quotes q join call_notes n on n.id = q.call_note
                          join deals d on d.id = n.deal where d.company = %s""", company_id)
    gone, texts = [r["id"] for r in rows], [r["text"] for r in rows]
    n = db.run(cur, "delete from call_notes where deal in (select id from deals where company = %s)", company_id)
    # A segment story that quoted one of these notes is withheld, and the stored model output that held it is cleared.
    for st in db.all(cur, "select id, sentences from segment_stories where sentences is not null"):
        quoted = {q.get("id") for q in ((st["sentences"] or {}).get("payload") or {}).get("quotes", [])}
        if quoted & set(gone):
            db.run(cur, """update segment_stories set sentences = null, status = 'withheld',
                           failures = '["A quoted note was erased"]' where id = %s""", st["id"])
    if gone:
        db.run(cur, """update llm_calls set output = '{}' where task = 'segment_story'
                       and exists (select 1 from unnest(%s::text[]) t where position(t in output::text) > 0)""", texts)
    db.run(cur, "update deals set loss_reason_text = null where company = %s", company_id)
    db.run(cur, "update customers set churn_reason_text = null where company = %s", company_id)
    db.run(cur, "insert into erasures (kind, subject, by_user) values ('company_notes', %s, %s)", str(company_id), by["id"])
    audit.log(cur, by["name"], "notes_erased", "company", company_id, {"notes": n}, actor_id=by["id"])
    return {"notes": n}
