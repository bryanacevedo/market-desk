"""Erasure: a team member leaves no name behind and their accounts move with a note; a company's notes can go."""
from __future__ import annotations

import pytest

from market import db, erasure


def test_erase_a_team_member(cur, users):
    tom = users["Tom"]
    live = "select count(*) from assignments a join territory_plans p on p.id = a.plan and p.status in ('active','draft') where a.owner = %s"
    held = db.val(cur, live, tom["id"])
    assert held > 0
    out = erasure.erase_user(cur, tom["id"], users["Sam"])
    assert out["accounts_moved"] == held
    u = db.one(cur, "select * from users where id = %s", tom["id"])
    assert u["erased"] and not u["active"] and "Whitaker" not in u["name"] and "whitaker" not in u["email"]
    assert db.val(cur, live, tom["id"]) == 0
    assert db.val(cur, "select count(*) from assignments where reason_code = 'manual' and note like 'Owner erased%%'") >= held
    assert db.val(cur, "select count(*) from erasures where kind = 'user' and subject = %s", str(tom["id"])) == 1
    with pytest.raises(PermissionError):
        erasure.erase_user(cur, users["Daniel"]["id"], users["Maya"])


def test_erase_a_companys_notes(cur, users):
    cid = db.val(cur, "select d.company from call_notes n join deals d on d.id = n.deal limit 1")
    out = erasure.erase_company_notes(cur, cid, users["Sam"])
    assert out["notes"] > 0
    assert not db.val(cur, "select count(*) from call_notes n join deals d on d.id = n.deal where d.company = %s", cid)
    assert not db.val(cur, "select count(*) from quotes q join call_notes n on n.id = q.call_note join deals d on d.id = n.deal where d.company = %s", cid)
