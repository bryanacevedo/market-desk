"""Territory move proposals (a reason, an effective date, a decision with who and when, an approval that drafts a plan
changing only those accounts), and the confirmation counts and rollback of Publish ICP and Activate plan."""
from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from market import crm, db, moves, profiles, territories


@pytest.fixture
def who(cur):
    return {u["name"].split()[0]: u for u in db.all(cur, "select * from users")}


def _active(cur):
    return db.one(cur, "select * from territory_plans where status = 'active'")


def _pick(cur, owner_from=None, n=3):
    """n accounts of the active plan that belong to one person, and another seller of the same role."""
    a = _active(cur)
    owner = owner_from or db.val(cur, """select owner from assignments a join users u on u.id = a.owner where a.plan = %s and u.role = 'ae'
                                         group by owner order by count(*) desc limit 1""", a["id"])
    ids = [r["company"] for r in db.all(cur, """select a.company from assignments a join companies c on c.id = a.company
                                                where a.plan = %s and a.owner = %s and not c.sole_trader and a.reason_code = 'rule'
                                                and not exists (select 1 from deals d where d.company = a.company and d.outcome = 'open')
                                                order by a.company limit %s""", a["id"], owner, n)]
    other = db.val(cur, "select id from users where role = 'ae' and active and id <> %s order by id limit 1", owner)
    return ids, owner, other


def _tomorrow(cur):
    return db.val(cur, "select app_now()::date + 30")


def test_a_proposal_carries_reason_date_and_proposer(cur, who):
    ids, _owner, other = _pick(cur)
    pid = moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason="Tom is over capacity", effective_on=_tomorrow(cur))
    p = moves.detail(cur, pid, who["Elena"])
    assert (p["status"], p["reason"], p["count"]) == ("open", "Tom is over capacity", 3)
    assert p["proposed_by"] == "Sam Kowalski" and p["effective_on"] == _tomorrow(cur)
    assert p["can_decide"] is True
    assert moves.detail(cur, pid, who["Sam"])["can_decide"] is False


def test_a_proposal_is_refused_when_it_is_wrong(cur, who):
    ids, owner, other = _pick(cur)
    day = _tomorrow(cur)
    with pytest.raises(ValueError, match="reason"):
        moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason=" ", effective_on=day)
    with pytest.raises(ValueError, match="past"):
        moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason="Because", effective_on=dt.date(2020, 1, 1))
    with pytest.raises(ValueError, match="already belongs"):
        moves.propose(cur, who["Sam"], companies=ids, to_owner=owner, reason="Because", effective_on=day)
    with pytest.raises(ValueError, match="AE or an SDR"):
        moves.propose(cur, who["Sam"], companies=ids, to_owner=who["Elena"]["id"], reason="Because", effective_on=day)
    moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason="Because", effective_on=day)
    with pytest.raises(ValueError, match="already in an open proposal"):
        moves.propose(cur, who["Sam"], companies=ids[:1], to_owner=other, reason="Again", effective_on=day)
    sdr = db.one(cur, "select * from users where role = 'sdr' limit 1")
    with pytest.raises(PermissionError):
        moves.propose(cur, sdr, companies=ids[:1], to_owner=other, reason="Because", effective_on=day)


def test_approval_drafts_a_plan_that_changes_only_those_accounts(cur, who):
    ids, owner, other = _pick(cur, n=4)
    pid = moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason="Tom is over capacity", effective_on=_tomorrow(cur))
    plan = moves.approve(cur, pid, who["Elena"])
    p = db.one(cur, "select * from move_proposals where id = %s", pid)
    assert p["status"] == "approved" and p["decided_by"] == who["Elena"]["id"] and p["decided_at"] and p["plan"] == plan
    d = db.one(cur, "select * from territory_plans where id = %s", plan)
    assert d["status"] == "draft" and d["effective_on"] == _tomorrow(cur) and d["author"] == who["Sam"]["id"]
    ch = territories.what_changes(cur, plan)
    assert ch["changes"] == 4 and {r["company"] for r in ch["all"]} == set(ids)
    assert all(r["to_owner"] == other and r["from_owner"] == owner for r in ch["all"])
    row = db.one(cur, "select * from assignments where plan = %s and company = %s", plan, ids[0])
    assert row["reason_code"] == "manual" and row["note"] == "Tom is over capacity" and row["moved_from"] == owner
    # nothing else was assigned afresh
    assert db.val(cur, "select count(*) from assignments where plan = %s", plan) == db.val(cur, "select count(*) from assignments where plan = %s", _active(cur)["id"])


def test_the_proposer_never_decides_and_a_rejection_needs_a_reason(cur, who):
    ids, _o, other = _pick(cur)
    pid = moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason="Because", effective_on=_tomorrow(cur))
    with pytest.raises(PermissionError):
        moves.approve(cur, pid, who["Sam"])
    with pytest.raises(ValueError, match="reason"):
        moves.reject(cur, pid, who["Elena"], " ")
    moves.reject(cur, pid, who["Elena"], "Wait for the hire")
    p = moves.detail(cur, pid, who["Elena"])
    assert (p["status"], p["decided_by"], p["decision_note"]) == ("rejected", "Elena Duarte", "Wait for the hire") and p["decided_at"]
    with pytest.raises(ValueError, match="already decided"):
        moves.approve(cur, pid, who["Elena"])
    assert db.val(cur, "select count(*) from audit_log where action = 'move_rejected' and object_id = %s", str(pid)) == 1


def test_a_manager_can_propose_and_revops_decides(cur, who):
    ids, _o, other = _pick(cur)
    pid = moves.propose(cur, who["Elena"], companies=ids, to_owner=other, reason="A new hire takes them", effective_on=_tomorrow(cur))
    with pytest.raises(PermissionError):
        moves.approve(cur, pid, who["Elena"])
    plan = moves.approve(cur, pid, who["Sam"])
    # RevOps authored the plan, so the manager can activate it
    assert db.val(cur, "select author from territory_plans where id = %s", plan) == who["Sam"]["id"]
    territories.activate(cur, plan, who["Elena"])
    assert _active(cur)["id"] == plan


def test_activating_a_move_plan_sends_only_through_the_usual_path(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    ids, _o, other = _pick(cur)
    plan = moves.approve(cur, moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason="Because", effective_on=_tomorrow(cur)), who["Elena"])
    pre = territories.activation_preview(cur, plan, who["Elena"])
    assert pre["owner_changes"] == 3 and pre["can_activate"] and pre["crm"] is True
    assert pre["batches"] == -(-db.val(cur, "select count(*) from assignments a join companies c on c.id = a.company where a.plan = %s and not c.sole_trader", plan) // crm.CHUNK)
    before = db.val(cur, "select count(*) from crm_outbox where status = 'queued'")
    territories.activate(cur, plan, who["Elena"])
    assert db.val(cur, "select count(*) from crm_outbox where status = 'queued'") - before == pre["batches"]


def test_a_move_plan_is_refused_when_the_active_plan_changed(cur, who):
    ids, _o, other = _pick(cur)
    plan = moves.approve(cur, moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason="Because", effective_on=_tomorrow(cur)), who["Elena"])
    draft = db.val(cur, "select id from territory_plans where status = 'draft' and drafted_from is null limit 1")
    territories.activate(cur, draft, who["Elena"])
    with pytest.raises(ValueError, match="active plan changed"):
        territories.activate(cur, plan, who["Elena"])
    assert territories.activation_preview(cur, plan, who["Elena"])["can_activate"] is False


def test_the_preview_says_nothing_is_sent_without_a_crm(cur, who, monkeypatch):
    monkeypatch.delenv("CRM", raising=False)
    draft = db.val(cur, "select id from territory_plans where status = 'draft' limit 1")
    pre = territories.activation_preview(cur, draft, who["Elena"])
    assert pre["crm"] is False and pre["batches"] == 0 and pre["owner_changes"] > 0
    assert pre["owner_changes"] == sum(p["gains"] for p in pre["people"])


def test_rollback_restores_the_earlier_plan_and_records_who_and_when(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    first = _active(cur)
    draft = db.val(cur, "select id from territory_plans where status = 'draft' limit 1")
    territories.activate(cur, draft, who["Elena"])
    assert db.val(cur, "select replaced from territory_plans where id = %s", draft) == first["id"]
    st = crm.send_state(cur, draft)
    assert st["waiting"] > 0 and st["sent"] == 0
    pre = territories.rollback_preview(cur, who["Elena"])
    assert pre["available"] and pre["to"] == first["name"] and pre["owner_changes"] > 0 and pre["waiting_batches"] == st["waiting"]
    with pytest.raises(PermissionError):
        territories.rollback(cur, who["Sam"])
    territories.rollback(cur, who["Elena"])
    now = _active(cur)
    assert now["id"] == first["id"] and now["restored_by"] == who["Elena"]["id"] and now["restored_at"]
    gone = db.one(cur, "select * from territory_plans where id = %s", draft)
    assert gone["status"] == "retired" and gone["rolled_back_by"] == who["Elena"]["id"] and gone["rolled_back_at"]
    # batches still waiting are cancelled; the earlier plan's books are queued in their place
    assert crm.send_state(cur, draft)["waiting"] == 0
    assert db.val(cur, "select count(*) from crm_outbox where plan = %s and status = 'cancelled'", draft) == st["waiting"]
    assert db.val(cur, "select count(*) from crm_outbox where plan = %s and status = 'queued'", first["id"]) == crm.batch_count(cur, first["id"])
    log = db.one(cur, "select actor, at from audit_log where action = 'plan_rolled_back' and object_id = %s", str(draft))
    assert log["actor"] == "Elena Duarte"


def test_rollback_reports_batches_already_sent(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    draft = db.val(cur, "select id from territory_plans where status = 'draft' limit 1")
    territories.activate(cur, draft, who["Elena"])
    db.run(cur, "update crm_outbox set status = 'sent', sent_at = app_now() where id = (select min(id) from crm_outbox where plan = %s)", draft)
    pre = territories.rollback_preview(cur, who["Elena"])
    assert pre["sent_batches"] == 1 and pre["sent_accounts"] > 0
    territories.rollback(cur, who["Elena"])
    assert crm.send_state(cur, draft)["sent"] == 1     # what the CRM took stays taken


def test_there_is_nothing_to_roll_back_to_on_a_fresh_plan(cur, who):
    db.run(cur, "update territory_plans set replaced = null where status = 'active'")
    assert territories.rollback_preview(cur, who["Elena"]) == {"available": False}
    with pytest.raises(ValueError):
        territories.rollback(cur, who["Elena"])


def test_publish_rollback_republishes_the_version_it_replaced(cur, who):
    pub = profiles.published(cur)
    draft = db.one(cur, "select * from icp_versions where status = 'draft' order by number limit 1")
    by = who["Elena"] if draft["author"] != who["Elena"]["id"] else who["Sam"]
    profiles.publish(cur, draft["id"], by, rescore_now=True)
    assert db.val(cur, "select replaced from icp_versions where id = %s", draft["id"]) == pub["id"]
    with pytest.raises(PermissionError):
        profiles.rollback(cur, who["Sam"])
    profiles.rollback(cur, who["Elena"])
    assert profiles.published(cur)["id"] == pub["id"]
    back = db.one(cur, "select * from icp_versions where id = %s", pub["id"])
    assert back["restored_by"] == who["Elena"]["id"] and back["restored_at"]
    gone = db.one(cur, "select * from icp_versions where id = %s", draft["id"])
    assert gone["status"] == "retired" and gone["rolled_back_by"] == who["Elena"]["id"]
    assert db.val(cur, "select count(*) from account_fit where icp_version = %s", pub["id"]) > 10000
    assert db.val(cur, "select actor from audit_log where action = 'profile_rolled_back' and object_id = %s", str(draft["id"])) == "Elena Duarte"


@pytest.fixture(scope="module")
def client(demo):
    from market.api.app import app
    with TestClient(app) as c:
        yield c


def test_the_api_previews_and_refuses_the_wrong_person(client, demo):
    with db.tx() as cur:
        ids = {u["name"].split()[0]: u["id"] for u in db.all(cur, "select id, name from users")}
        draft = db.val(cur, "select id from territory_plans where status = 'draft' limit 1")
        vdraft = db.val(cur, "select id from icp_versions where status = 'draft' limit 1")
    h = lambda who: {"X-Acting-As": str(ids[who]), "content-type": "application/json"}  # noqa: E731
    pre = client.get(f"/api/plans/{draft}/activate-preview", headers=h("Elena")).json()
    assert pre["owner_changes"] > 0 and "batches" in pre and pre["can_activate"] is True
    assert client.get(f"/api/plans/{draft}/activate-preview", headers=h("Maya")).status_code == 403
    pv = client.get(f"/api/profile/versions/{vdraft}/publish-preview", headers=h("Elena")).json()
    assert pv["companies"] > 10000 and pv["replaces"] >= 1 and "tier_moves" in pv
    assert client.post("/api/plans/rollback", json={}, headers=h("Sam")).status_code == 403
    assert client.post("/api/profile/rollback", json={}, headers=h("Sam")).status_code == 403
    assert client.post("/api/move-proposals", json={"companies": [1], "to": ids["Grace"], "reason": "x"}, headers=h("Sam")).status_code == 422
    assert client.get("/api/move-proposals", headers=h("Sam")).status_code == 200
    assert client.get("/api/move-proposals/options", headers=h("Sam")).json()["people"]
