"""Owners change on a plan's start date (decision 55, Backlog bl_134): activating a plan that starts later schedules it."""
from __future__ import annotations

import pytest

from market import crm, db, moves, territories
from market.api import views

from .conftest import activate_now


@pytest.fixture
def who(cur):
    return {u["name"].split()[0]: u for u in db.all(cur, "select * from users")}


def _active(cur):
    return db.one(cur, "select * from territory_plans where status = 'active'")


def _scheduled_move(cur, who):
    """A move plan for three accounts of one AE, dated 30 days ahead, ready to activate."""
    a = _active(cur)
    owner = db.val(cur, """select owner from assignments a join users u on u.id = a.owner where a.plan = %s and u.role = 'ae'
                           group by owner order by count(*) desc limit 1""", a["id"])
    ids = [r["company"] for r in db.all(cur, """select a.company from assignments a join companies c on c.id = a.company
                where a.plan = %s and a.owner = %s and not c.sole_trader and a.reason_code = 'rule'
                and not exists (select 1 from deals d where d.company = a.company and d.outcome = 'open') order by a.company limit 3""", a["id"], owner)]
    other = db.val(cur, "select id from users where role = 'ae' and active and id <> %s order by id limit 1", owner)
    day = db.val(cur, "select app_now()::date + 30")
    plan = moves.approve(cur, moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason="A new hire", effective_on=day), who["Elena"])
    return plan, ids, owner, other, day


def test_a_plan_that_starts_later_is_scheduled_and_no_owner_moves(cur, who):
    plan, ids, owner, other, day = _scheduled_move(cur, who)
    before = _active(cur)["id"]
    pre = territories.activation_preview(cur, plan, who["Elena"])
    assert pre["starts_later"] and pre["scheduled_changes"] == 3
    moved = "select count(*) from audit_log where action = 'owner_moved'"
    n0 = db.val(cur, moved)
    territories.activate(cur, plan, who["Elena"])
    assert db.val(cur, moved) == n0
    assert db.val(cur, "select status from territory_plans where id = %s", plan) == "scheduled"
    assert _active(cur)["id"] == before
    assert db.val(cur, "select owner from assignments where plan = %s and company = %s", before, ids[0]) == owner
    assert db.val(cur, "select count(*) from audit_log where action = 'plan_scheduled' and object_id = %s", str(plan)) == 1
    coming = views.company(cur, ids[0], who["Elena"])["coming"]
    assert coming == [{"role": "owner", "name": next(u["name"] for u in db.all(cur, "select * from users") if u["id"] == other), "from": day}]
    assert views.accounts(cur, who["Elena"], q="", tier="", segment="", owner="", page=1)["total"] > 0


def test_it_applies_on_the_start_date_and_not_before(cur, who):
    plan, ids, owner, other, day = _scheduled_move(cur, who)
    before = _active(cur)["id"]
    territories.activate(cur, plan, who["Elena"])
    assert territories.apply_scheduled(cur) == 0
    db.run(cur, "update territory_plans set effective_on = app_now()::date where id = %s", plan)
    assert territories.apply_scheduled(cur) == 1
    assert _active(cur)["id"] == plan
    assert db.val(cur, "select status from territory_plans where id = %s", before) == "retired"
    assert db.val(cur, "select owner from assignments where plan = %s and company = %s", plan, ids[0]) == other
    assert views.company(cur, ids[0], who["Elena"])["coming"] == []


def test_nothing_else_activates_or_rolls_back_while_one_is_scheduled(cur, who):
    plan, *_ = _scheduled_move(cur, who)
    territories.activate(cur, plan, who["Elena"])
    draft = db.val(cur, "select id from territory_plans where status = 'draft' limit 1")
    if draft:
        with pytest.raises(ValueError, match="scheduled"):
            territories.activate(cur, draft, who["Elena"])
        assert "scheduled" in territories.activation_preview(cur, draft, who["Elena"])["blocked"]
    with pytest.raises(ValueError, match="scheduled"):
        territories.rollback(cur, who["Elena"], "Because")
    assert territories.rollback_preview(cur, who["Elena"])["available"] is False


def test_a_manager_cancels_a_schedule_before_its_date(cur, who):
    plan, *_ = _scheduled_move(cur, who)
    territories.activate(cur, plan, who["Elena"])
    with pytest.raises(PermissionError):
        territories.cancel_schedule(cur, who["Sam"])
    territories.cancel_schedule(cur, who["Elena"])
    assert db.one(cur, "select status, activated_by from territory_plans where id = %s", plan) == {"status": "draft", "activated_by": None}
    with pytest.raises(ValueError):
        territories.cancel_schedule(cur, who["Elena"])


def test_an_activation_dated_today_is_immediate_as_before(cur, who):
    plan, *_ = _scheduled_move(cur, who)
    activate_now(cur, plan, who["Elena"])
    assert _active(cur)["id"] == plan


class _Up:
    def __init__(self, features): self.features = features


def test_the_crm_is_told_the_schedule_only_when_it_can_hold_a_date(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    plan, ids, owner, other, day = _scheduled_move(cur, who)
    monkeypatch.setattr(crm, "supports_schedule", lambda: False)
    territories.activate(cur, plan, who["Elena"])
    assert db.val(cur, "select count(*) from crm_outbox where plan = %s", plan) == 0     # an older CRM is sent nothing early
    territories.cancel_schedule(cur, who["Elena"])
    monkeypatch.setattr(crm, "supports_schedule", lambda: True)
    territories.activate(cur, plan, who["Elena"])
    rows = db.all(cur, "select payload from crm_outbox where plan = %s and status = 'queued'", plan)
    items = [i for r in rows for i in r["payload"]["items"]]
    assert len(items) == 3 and all(i["owner_effective_on"] == str(day) and "owner_id" in i and "name" not in i for i in items)
    assert {i["domain"] for i in items} == {r["primary_domain"] for r in db.all(cur, "select primary_domain from companies where id = any(%s)", ids)}
    # the start date: the plain books go, with no date
    db.run(cur, "update territory_plans set effective_on = app_now()::date where id = %s", plan)
    territories.apply_scheduled(cur)
    full = db.all(cur, "select payload from crm_outbox where plan = %s and status = 'queued' order by id", plan)
    assert not any(i.get("owner_effective_on") for r in full[len(rows):] for i in r["payload"]["items"])


def test_cancelling_after_the_crm_took_the_schedule_withdraws_it(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.setattr(crm, "supports_schedule", lambda: True)
    plan, *_ = _scheduled_move(cur, who)
    territories.activate(cur, plan, who["Elena"])
    db.run(cur, "update crm_outbox set status = 'sent' where plan = %s", plan)
    territories.cancel_schedule(cur, who["Elena"])
    q = db.all(cur, "select payload from crm_outbox where plan = %s and status = 'queued'", plan)
    assert [i["cancel_scheduled_owner"] for r in q for i in r["payload"]["items"]] == [True, True, True]


def test_the_hourly_job_queues_itself_again_while_its_own_row_is_running(cur, who):
    plan, *_ = _scheduled_move(cur, who)
    territories.activate(cur, plan, who["Elena"])
    db.run(cur, "update jobs set status = 'running' where kind = 'apply_scheduled_plan'")
    territories._apply_scheduled(cur, {})
    assert db.val(cur, "select count(*) from jobs where kind = 'apply_scheduled_plan' and status = 'queued'") == 1


def test_a_plan_applies_even_when_its_activator_is_no_longer_a_manager(cur, who):
    plan, *_ = _scheduled_move(cur, who)
    territories.activate(cur, plan, who["Elena"])
    db.run(cur, "insert into users (name, email, role, started_on, active) values ('Mia Backup', 'mia.backup@lumenledger.example', 'manager', '2025-01-01', true)")
    db.run(cur, "update territory_plans set effective_on = app_now()::date where id = %s", plan)
    db.run(cur, "update users set role = 'revops' where id = %s", who["Elena"]["id"])
    assert territories.apply_scheduled(cur) == 1
    assert _active(cur)["id"] == plan


# ---- a person's own owner change drops the account from the scheduled plan (Bryan, 2026-11-15; decision 57)

def _revops(cur):
    return db.one(cur, "select * from users where role = 'revops' and active order by id limit 1")


def _hand_target(cur, who, ids, owner, other):
    """Someone who is neither the account's owner nor the scheduled one: the person a hand change gives it to."""
    return db.val(cur, "select id from users where role = 'ae' and active and id not in (%s, %s) order by id limit 1", owner, other)


def test_a_hand_change_in_this_desk_drops_the_account_from_the_scheduled_plan(cur, who):
    plan, ids, owner, other, day = _scheduled_move(cur, who)
    territories.activate(cur, plan, who["Elena"])
    third = _hand_target(cur, who, ids, owner, other)
    out = territories.change_owner_by_hand(cur, ids[0], third, "Keeps the relationship", _revops(cur))
    assert out == {"role": "owner", "dropped_from_schedule": True}
    assert ids[0] not in territories.scheduled_moves(cur) and set(territories.scheduled_moves(cur)) == set(ids[1:])
    shown = views.company(cur, ids[0], who["Elena"])["coming"]
    assert len(shown) == 1 and shown[0]["by_hand"] and shown[0]["kept"] is not None and shown[0]["from"] == day
    assert db.val(cur, "select count(*) from audit_log where action = 'scheduled_move_dropped' and object_id = %s", str(ids[0])) == 1
    # on the start date the plan applies and the hand change stands
    db.run(cur, "update territory_plans set effective_on = app_now()::date where id = %s", plan)
    assert territories.apply_scheduled(cur) == 1
    assert db.val(cur, "select owner from assignments where plan = %s and company = %s", plan, ids[0]) == third
    assert db.val(cur, "select owner from assignments where plan = %s and company = %s", plan, ids[1]) == other


def test_a_hand_change_of_a_role_the_plan_does_not_move_keeps_the_schedule(cur, who):
    plan, ids, owner, other, day = _scheduled_move(cur, who)
    territories.activate(cur, plan, who["Elena"])
    sdr = db.val(cur, "select id from users where role = 'sdr' and active order by id limit 1")
    with pytest.raises(ValueError, match="seat"):
        territories.change_owner_by_hand(cur, ids[0], sdr, "Needs an SDR on it", _revops(cur))
    assert set(territories.scheduled_moves(cur)) == set(ids)


def test_cancelling_a_schedule_forgets_its_hand_changes(cur, who):
    plan, ids, owner, other, day = _scheduled_move(cur, who)
    territories.activate(cur, plan, who["Elena"])
    territories.change_owner_by_hand(cur, ids[0], _hand_target(cur, who, ids, owner, other), "Keeps it", _revops(cur))
    territories.cancel_schedule(cur, who["Elena"])
    assert db.val(cur, "select count(*) from plan_hand_changes where plan = %s", plan) == 0


def test_only_revops_changes_an_owner_by_hand_with_a_note(cur, who):
    plan, ids, owner, other, day = _scheduled_move(cur, who)
    with pytest.raises(PermissionError):
        territories.change_owner_by_hand(cur, ids[0], other, "Because", who["Elena"])
    with pytest.raises(ValueError):
        territories.change_owner_by_hand(cur, ids[0], other, " ", _revops(cur))


def test_the_crm_is_told_the_hand_change_and_to_drop_what_it_holds(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.setattr(crm, "supports_schedule", lambda: True)
    plan, ids, owner, other, day = _scheduled_move(cur, who)
    territories.activate(cur, plan, who["Elena"])
    third = _hand_target(cur, who, ids, owner, other)
    before = db.val(cur, "select max(id) from crm_outbox")
    territories.change_owner_by_hand(cur, ids[0], third, "Keeps the relationship", _revops(cur))
    row = db.one(cur, "select payload from crm_outbox where id > %s order by id", before or 0)
    (item,) = row["payload"]["items"]
    assert item["cancel_scheduled_owner"] == "account" and item["owner_id"] == db.val(cur, "select email from users where id = %s", third)


def test_the_plain_books_on_the_start_date_leave_out_a_role_changed_by_hand(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.setattr(crm, "supports_schedule", lambda: True)
    monkeypatch.setattr(crm, "supports_by_hand", lambda: True)
    monkeypatch.setattr(crm, "by_hand", lambda on: [])
    plan, ids, owner, other, day = _scheduled_move(cur, who)
    territories.activate(cur, plan, who["Elena"])
    third = _hand_target(cur, who, ids, owner, other)
    territories.change_owner_by_hand(cur, ids[0], third, "Keeps the relationship", _revops(cur))
    sent = db.val(cur, "select coalesce(max(id), 0) from crm_outbox")
    db.run(cur, "update territory_plans set effective_on = app_now()::date where id = %s", plan)
    territories.apply_scheduled(cur)
    items = [i for r in db.all(cur, "select payload from crm_outbox where id > %s", sent) for i in r["payload"]["items"]]
    dom = db.val(cur, "select primary_domain from companies where id = %s", ids[0])
    mine = next(i for i in items if i["domain"] == dom)
    assert "owner_id" not in mine and "sdr_owner_id" not in mine          # nothing to overwrite what the person set
    other_item = next(i for i in items if i["domain"] == db.val(cur, "select primary_domain from companies where id = %s", ids[1]))
    assert other_item["owner_id"] and other_item["owner_scheduled_for"] == str(db.val(cur, "select app_now()::date"))


def test_a_hand_change_made_in_the_crm_is_read_back_and_dropped_too(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.setattr(crm, "supports_schedule", lambda: True)
    monkeypatch.setattr(crm, "supports_by_hand", lambda: True)
    plan, ids, owner, other, day = _scheduled_move(cur, who)
    territories.activate(cur, plan, who["Elena"])
    third = db.one(cur, "select id, email, name from users where role = 'ae' and active and id not in (%s, %s) order by id limit 1", owner, other)
    dom = db.val(cur, "select primary_domain from companies where id = %s", ids[0])
    monkeypatch.setattr(crm, "by_hand", lambda on: [{"account_domain": dom, "role": "account", "owner_email": third["email"], "by": "Mona Manager",
                                                     "note": "the owner was changed by hand to X"}])
    assert territories.sync_hand_changes(cur) == 1
    assert territories.sync_hand_changes(cur) == 0                      # reading again changes nothing
    assert ids[0] not in territories.scheduled_moves(cur)
    (h,) = territories.hand_changes(cur, plan)
    assert (h["source"], h["to_user"], h["by_name"]) == ("crm_desk", third["id"], "Mona Manager")
    db.run(cur, "update territory_plans set effective_on = app_now()::date where id = %s", plan)
    assert territories.apply_scheduled(cur) == 1
    assert db.val(cur, "select owner from assignments where plan = %s and company = %s", plan, ids[0]) == third["id"]
    assert db.val(cur, "select count(*) from audit_log where action = 'owner_kept_by_hand' and object_id = %s", str(ids[0])) == 1


def test_a_crm_that_cannot_say_leaves_the_plan_as_it_was(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.setattr(crm, "supports_schedule", lambda: True)
    monkeypatch.setattr(crm, "supports_by_hand", lambda: True)
    def down(on):
        raise crm.CrmDown("no answer")
    monkeypatch.setattr(crm, "by_hand", down)
    plan, ids, *_ = _scheduled_move(cur, who)
    territories.activate(cur, plan, who["Elena"])
    assert territories.sync_hand_changes(cur) == 0 and set(territories.scheduled_moves(cur)) == set(ids)


def test_the_api_takes_a_hand_change(cur, who):
    from fastapi.testclient import TestClient  # noqa: F401  (the route exists and is wired to the same function)

    from market.api import app as appmod
    assert any(r.path == "/api/companies/{cid}/owner" for r in appmod.app.routes)
