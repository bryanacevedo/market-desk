"""Notices. A rollback is one person's call, for speed, so everyone else who could have made it is told: the other managers
and RevOps see it under "Waiting on you" until they open it, with who rolled back what and the reason."""
from __future__ import annotations

from . import db

RECIPIENT_ROLES = ("manager", "revops")


def rolled_back(cur, kind: str, by: dict, *, subject: str, restored: str, reason: str, path: str) -> int:
    return db.val(cur, """insert into notices (kind, subject, restored, reason, path, by_user) values (%s,%s,%s,%s,%s,%s) returning id""",
                  kind, subject, restored, reason, path, by["id"])


def unseen(cur, user: dict) -> list[dict]:
    """What this person has not yet opened. Never their own rollback; only managers and RevOps are told."""
    if user["role"] not in RECIPIENT_ROLES:
        return []
    rows = db.all(cur, """select n.id, n.kind, n.subject, n.restored, n.reason, n.path, u.name as who from notices n
                          join users u on u.id = n.by_user
                          where n.by_user <> %s and not exists (select 1 from notice_seen s where s.notice = n.id and s.user_id = %s)
                          order by n.id desc limit 5""", user["id"], user["id"])
    return [{"what": f"{r['who']} rolled back {r['subject']} to {r['restored']}: {r['reason']}", "path": r["path"], "notice": r["id"]}
            for r in rows]


def see(cur, notice: int, user: dict) -> None:
    db.run(cur, """insert into notice_seen (notice, user_id) select id, %s from notices where id = %s
                   on conflict do nothing""", user["id"], notice)
