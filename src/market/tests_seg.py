"""Segment tests: work a cohort of a segment, hold back a fixed share, and compare meetings before a segment gets
territory. Sized with Account Desk's n_per_arm; read at 90% as Account Desk reads its play tests."""
from __future__ import annotations

import hashlib
import math

from . import audit, db, stats
from .db import J

CONF = 0.90


def default_cohort() -> int:
    """(1 + 4) x the held-back accounts needed to read a 10-point lift on a 10% base, rounded up to ten: 520."""
    return int(math.ceil(5 * stats.n_per_arm(0.10, 0.10) / 10) * 10)


def _h(*parts) -> str:
    return hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()


def eligible(cur, segment: str, *, exclude_test: int | None = None) -> list[dict]:
    """Prospects at tier A or B under the published profile, in the segment, not a sole trader, and not a member of
    another running or read test."""
    return db.all(cur, """
        select c.id, c.primary_domain from companies c
        join account_fit f on f.company = c.id and f.icp_version = (select id from icp_versions where status = 'published')
        where f.segment = %s and f.tier in ('A','B') and f.judged and c.lifecycle = 'prospect' and not c.sole_trader
          and not exists (select 1 from segment_test_members m join segment_tests t on t.id = m.test
                          where m.company = c.id and t.status in ('running','read') and t.id is distinct from %s)
        order by c.id""", segment, exclude_test)


def create_draft(cur, segment: str, hypothesis: str, by: dict, cohort: int | None = None) -> int:
    if by["role"] != "revops":
        raise PermissionError("RevOps drafts segment tests.")
    cohort = cohort or default_cohort()
    n = len(eligible(cur, segment))
    if n < cohort:
        raise ValueError(f"This segment has {n} eligible companies; a test needs {cohort}.")
    tid = db.val(cur, """insert into segment_tests (segment, hypothesis, cohort_size, status, created_by, created_at)
                         values (%s,%s,%s,'draft',%s, app_now()) returning id""", segment, hypothesis, cohort, by["id"])
    audit.log(cur, by["name"], "test_drafted", "segment_test", tid, {"segment": segment}, actor_id=by["id"])
    return tid


def start(cur, test_id: int, by: dict, *, started_on=None, ends_on=None) -> dict:
    t = db.one(cur, "select * from segment_tests where id = %s for update", test_id)
    if t["status"] != "draft":
        raise ValueError("Only a draft test can start.")
    pool = eligible(cur, t["segment"], exclude_test=test_id)
    if len(pool) < t["cohort_size"]:
        raise ValueError(f"This segment has {len(pool)} eligible companies; the test needs {t['cohort_size']}.")
    cohort = sorted(pool, key=lambda c: _h("cohort", test_id, c["primary_domain"]))[: t["cohort_size"]]
    ranked = sorted(cohort, key=lambda c: _h("held", test_id, c["primary_domain"]))
    held = round(float(t["held_back_share"]) * len(cohort))
    for i, c in enumerate(ranked):
        db.run(cur, "insert into segment_test_members (test, company, grp) values (%s,%s,%s)", test_id, c["id"],
               "held_back" if i < held else "worked")
    db.run(cur, """update segment_tests set status = 'running', started_on = coalesce(%s, app_now()::date),
                   ends_on = coalesce(%s, app_now()::date + 120) where id = %s""", started_on, ends_on, test_id)
    audit.log(cur, by["name"], "test_started", "segment_test", test_id, {"worked": len(cohort) - held, "held_back": held},
              actor_id=by["id"])
    return {"worked": len(cohort) - held, "held_back": held}


def read(cur, test_id: int) -> dict:
    """Meetings, worked against held back, counted the same way in both groups from the CRM's results."""
    g = db.one(cur, """
        select count(*) filter (where m.grp = 'worked') as wn,
               count(*) filter (where m.grp = 'worked' and coalesce(r.meetings, 0) > 0) as wk,
               count(*) filter (where m.grp = 'held_back') as hn,
               count(*) filter (where m.grp = 'held_back' and coalesce(r.meetings, 0) > 0) as hk
        from segment_test_members m
        left join (select company, sum(meetings) as meetings from desk_results where test = %s group by company) r
          on r.company = m.company
        where m.test = %s""", test_id, test_id)
    rep = stats.lift_report(g["wk"], g["wn"], g["hk"], g["hn"], conf=CONF)
    rep["clear"] = bool(rep["enough"] and rep["interval"] and (rep["interval"][0] > 0 or rep["interval"][1] < 0))
    return rep


def decide(cur, test_id: int, decision: str, by: dict, note: str | None = None) -> None:
    if by["role"] not in ("revops", "manager"):
        raise PermissionError("RevOps or a manager decides a test.")
    if decision not in ("expand", "drop", "extend"):
        raise ValueError("Expand, drop or extend.")
    t = db.one(cur, "select * from segment_tests where id = %s for update", test_id)
    if t["status"] not in ("running", "read"):
        raise ValueError("Only a running or read test can be decided.")
    status = "running" if decision == "extend" else "read"
    db.run(cur, """update segment_tests set decision = %s, decided_by = %s, decision_note = %s, status = %s,
                   ends_on = case when %s = 'extend' then ends_on + 60 else ends_on end where id = %s""",
           decision, by["id"], note, status, decision, test_id)
    audit.log(cur, by["name"], f"test_{decision}", "segment_test", test_id, {"note": note}, actor_id=by["id"])
    if decision == "expand":
        from . import proposals
        proposals.generate(cur)


_ = J
