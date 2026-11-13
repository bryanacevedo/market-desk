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
        territories.rollback(cur, who["Sam"], "Because")
    territories.rollback(cur, who["Elena"], "Because")
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
    territories.rollback(cur, who["Elena"], "Because")
    assert crm.send_state(cur, draft)["sent"] == 1     # what the CRM took stays taken


def test_there_is_nothing_to_roll_back_to_on_a_fresh_plan(cur, who):
    db.run(cur, "update territory_plans set replaced = null where status = 'active'")
    assert territories.rollback_preview(cur, who["Elena"]) == {"available": False}
    with pytest.raises(ValueError):
        territories.rollback(cur, who["Elena"], "Because")


def test_publish_rollback_republishes_the_version_it_replaced(cur, who):
    pub = profiles.published(cur)
    draft = db.one(cur, "select * from icp_versions where status = 'draft' order by number limit 1")
    by = who["Elena"] if draft["author"] != who["Elena"]["id"] else who["Sam"]
    profiles.publish(cur, draft["id"], by, rescore_now=True)
    assert db.val(cur, "select replaced from icp_versions where id = %s", draft["id"]) == pub["id"]
    with pytest.raises(PermissionError):
        profiles.rollback(cur, who["Sam"], "Because")
    profiles.rollback(cur, who["Elena"], "Because")
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
    assert client.post("/api/plans/rollback", json={"reason": "Because"}, headers=h("Sam")).status_code == 403
    assert client.post("/api/profile/rollback", json={"reason": "Because"}, headers=h("Sam")).status_code == 403
    assert client.post("/api/move-proposals", json={"companies": [1], "to": ids["Grace"], "reason": "x"}, headers=h("Sam")).status_code == 422
    assert client.get("/api/move-proposals", headers=h("Sam")).status_code == 200
    assert client.get("/api/move-proposals/options", headers=h("Sam")).json()["people"]


# ---------------------------------------------------------------- rollback: a reason, and nobody is left unaware

def test_a_rollback_needs_a_reason(cur, who):
    draft = db.val(cur, "select id from territory_plans where status = 'draft' limit 1")
    territories.activate(cur, draft, who["Elena"])
    with pytest.raises(ValueError, match="reason"):
        territories.rollback(cur, who["Elena"], "  ")
    with pytest.raises(ValueError, match="reason"):
        territories.rollback(cur, who["Elena"])
    assert _active(cur)["id"] == draft


def test_a_profile_rollback_needs_a_reason(cur, who):
    pub = profiles.published(cur)
    draft = db.one(cur, "select * from icp_versions where status = 'draft' order by number limit 1")
    by = who["Elena"] if draft["author"] != who["Elena"]["id"] else who["Sam"]
    profiles.publish(cur, draft["id"], by, rescore_now=False)
    with pytest.raises(ValueError, match="reason"):
        profiles.rollback(cur, who["Elena"], "")
    assert profiles.published(cur)["id"] == draft["id"] and pub["id"] != draft["id"]


def test_a_rollback_is_told_to_the_others_with_its_reason_and_shown_in_history(cur, who):
    from market import notices
    from market.api import views
    second = db.one(cur, """insert into users (name, email, role, started_on) values ('Noor Haddad', 'noor@example.test', 'manager', '2024-01-01')
                            returning *""")
    draft = db.val(cur, "select id from territory_plans where status = 'draft' limit 1")
    territories.activate(cur, draft, who["Elena"])
    territories.rollback(cur, second, "It moved the wrong accounts")
    other = who["Elena"]
    assert notices.unseen(cur, second) == []                             # not the one who did it
    for person in (other, who["Sam"]):                                   # the other manager, and RevOps
        got = notices.unseen(cur, person)
        assert len(got) == 1 and "It moved the wrong accounts" in got[0]["what"] and "Noor Haddad rolled back" in got[0]["what"]
        assert got[0]["path"] == "/territories"
    assert [u for u in who.values() if u["role"] not in ("manager", "revops") and notices.unseen(cur, u)] == []
    notices.see(cur, got[0]["notice"], who["Sam"])
    assert notices.unseen(cur, who["Sam"]) == [] and len(notices.unseen(cur, other)) == 1
    hist = views.history(cur, ("plan_rolled_back",))
    assert hist[0]["note"] == "It moved the wrong accounts" and hist[0]["who"] == "Noor Haddad"
    assert db.val(cur, "select rolled_back_reason from territory_plans where id = %s", draft) == "It moved the wrong accounts"


def test_a_profile_rollback_notice_and_history(cur, who):
    from market import notices
    from market.api import views
    draft = db.one(cur, "select * from icp_versions where status = 'draft' order by number limit 1")
    by = who["Elena"] if draft["author"] != who["Elena"]["id"] else who["Sam"]
    profiles.publish(cur, draft["id"], by, rescore_now=False)
    profiles.rollback(cur, who["Elena"], "Scores dropped for good fits")
    got = notices.unseen(cur, who["Sam"])
    assert got and got[0]["path"] == "/profile" and "Scores dropped for good fits" in got[0]["what"]
    assert views.history(cur, ("profile_rolled_back",))[0]["note"] == "Scores dropped for good fits"


def test_the_api_takes_the_reason_and_shows_the_notice(client, demo):
    with db.tx() as cur:
        ids = {u["name"].split()[0]: u["id"] for u in db.all(cur, "select id, name from users")}
    h = lambda who: {"X-Acting-As": str(ids[who]), "content-type": "application/json"}  # noqa: E731
    assert client.post("/api/plans/rollback", json={}, headers=h("Elena")).status_code == 422
    assert client.post("/api/profile/rollback", json={"reason": "x"}, headers=h("Elena")).status_code == 422
    with db.tx() as cur:
        from market import notices

        notices.rolled_back(cur, "plan_rolled_back", {"id": ids["Elena"]}, subject="A", restored="B", reason="Test reason", path="/territories")
    me = client.get("/api/me", headers=h("Sam")).json()
    mine = [w for w in me["waiting"] if w.get("notice")]
    assert mine and "Test reason" in mine[0]["what"]
    assert client.post(f"/api/notices/{mine[0]['notice']}/seen", json={}, headers=h("Sam")).status_code == 200
    assert not [w for w in client.get("/api/me", headers=h("Sam")).json()["waiting"] if w.get("notice") == mine[0]["notice"]]
    with db.tx() as cur:
        db.run(cur, "delete from notices")


# ---------------------------------------------------------------- move by territory rule

def _territory(cur):
    """The active plan's territory holding the most accounts, with a seller who is not its owner of all of them."""
    a = _active(cur)
    t = db.one(cur, """select t.id, t.key, t.label, count(*) n from territories t join assignments x on x.territory = t.id
                       join companies c on c.id = x.company and not c.sole_trader
                       where t.plan = %s group by t.id order by n desc limit 1""", a["id"])
    to = db.val(cur, "select id from users where role = 'sdr' and active order by id limit 1")
    return t, to


def test_rule_matches_counts_what_the_territory_holds(cur, who):
    t, to = _territory(cur)
    m = moves.rule_matches(cur, t["key"], to)
    assert m["matched"] == t["n"] and m["territory"] == t["label"] and m["regions"] and m["segments"]
    assert m["matched"] == m["eligible"] + m["already_there"] + m["in_open_proposal"] == len(m["ids"]) + m["already_there"] + m["in_open_proposal"]
    assert m["proposals"] == -(-m["eligible"] // moves.MAX_ACCOUNTS)
    with pytest.raises(ValueError, match="not in the active plan"):
        moves.rule_matches(cur, "nowhere")


def test_a_move_by_territory_takes_every_account_the_rule_holds(cur, who):
    t, to = _territory(cur)
    m = moves.rule_matches(cur, t["key"], to)
    ids = moves.propose_by_territory(cur, who["Sam"], territory=t["key"], to_owner=to, reason="Cover the whole territory", effective_on=_tomorrow(cur))
    assert len(ids) == m["proposals"]
    held = sum(db.val(cur, "select count(*) from move_proposal_accounts where proposal = %s", i) for i in ids)
    assert held == m["eligible"] and all(db.val(cur, "select count(*) from move_proposal_accounts where proposal = %s", i) <= 200 for i in ids)
    p = moves.detail(cur, ids[0], who["Elena"])
    assert p["by_territory"] == t["label"] and p["can_decide"]
    # the same accounts cannot be proposed again while these are open
    assert moves.rule_matches(cur, t["key"], to)["eligible"] == 0


def test_above_the_cap_a_territory_move_splits(cur, who, monkeypatch):
    t, to = _territory(cur)
    monkeypatch.setattr(moves, "MAX_ACCOUNTS", 40)
    m = moves.rule_matches(cur, t["key"], to)
    assert m["eligible"] > 80 and m["proposals"] == -(-m["eligible"] // 40) > 2
    ids = moves.propose_by_territory(cur, who["Sam"], territory=t["key"], to_owner=to, reason="Cover the territory", effective_on=_tomorrow(cur))
    sizes = [db.val(cur, "select count(*) from move_proposal_accounts where proposal = %s", i) for i in ids]
    assert len(ids) == m["proposals"] and sum(sizes) == m["eligible"] and max(sizes) == 40
    assert moves.detail(cur, ids[1], who["Elena"])["reason"].endswith(f"(part 2 of {len(ids)})")


@pytest.mark.parametrize("crmdesk", [False, True])
def test_a_territory_move_follows_the_usual_approval_and_activation(cur, who, monkeypatch, crmdesk):
    if crmdesk:
        monkeypatch.setenv("CRM", "crmdesk")
    else:
        monkeypatch.delenv("CRM", raising=False)
    t, to = _territory(cur)
    monkeypatch.setattr(moves, "MAX_ACCOUNTS", 25)
    pid = moves.propose_by_territory(cur, who["Elena"], territory=t["key"], to_owner=to, reason="A new hire", effective_on=_tomorrow(cur))[0]
    with pytest.raises(PermissionError):
        moves.approve(cur, pid, who["Elena"])                                  # not the proposer
    plan = moves.approve(cur, pid, who["Sam"])
    pre = territories.activation_preview(cur, plan, who["Elena"])
    assert pre["owner_changes"] == 25 and pre["crm"] is crmdesk
    before = db.val(cur, "select count(*) from crm_outbox where status = 'queued'")
    territories.activate(cur, plan, who["Elena"])
    assert (db.val(cur, "select count(*) from crm_outbox where status = 'queued'") - before > 0) is crmdesk
    assert db.val(cur, "select count(*) from assignments where plan = %s and owner = %s", plan, to) >= 25


def test_the_api_previews_and_proposes_by_territory(client, demo):
    with db.tx() as cur:
        ids = {u["name"].split()[0]: u["id"] for u in db.all(cur, "select id, name from users")}
        t, to = _territory(cur)
        day = str(_tomorrow(cur))
    h = lambda who: {"X-Acting-As": str(ids[who]), "content-type": "application/json"}  # noqa: E731
    r = client.get(f"/api/move-proposals/territory-preview?territory={t['key']}&to={to}", headers=h("Sam")).json()
    assert r["matched"] == t["n"] and "ids" not in r and r["eligible"] > 0
    assert client.get(f"/api/move-proposals/territory-preview?territory={t['key']}", headers=h("Maya")).status_code == 403
    body = {"territory": t["key"], "to": to, "reason": "Cover it", "effective_on": day}
    assert client.post("/api/move-proposals/by-territory", json=body, headers=h("Maya")).status_code == 403
    got = client.post("/api/move-proposals/by-territory", json=body, headers=h("Sam"))
    assert got.status_code == 200 and len(got.json()["ids"]) == r["proposals"]
    assert client.post("/api/move-proposals/by-territory", json=body, headers=h("Sam")).status_code == 422   # nothing left to move
    with db.tx() as cur:
        db.run(cur, "delete from move_proposals")
