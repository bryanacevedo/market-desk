"""Books to a CRM (decision 41): nothing without one; with one, every assigned account with its AE and SDR, the
answers kept, refusals listed, and a CRM that does not answer leaves the row queued."""
import pytest

from market import crm, db, territories
from market.db import J


def _plan(cur):
    return db.val(cur, "select id from territory_plans where status = 'active'")


def test_no_crm_queues_nothing(cur, monkeypatch):
    monkeypatch.delenv("CRM", raising=False)
    assert crm.queue_plan(cur, _plan(cur)) == 0
    assert db.val(cur, "select count(*) from crm_outbox where status = 'queued'") == 0


def test_books_carry_the_account_its_ae_and_its_sdr(cur, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    items = crm.plan_items(cur, _plan(cur))
    assert items and all(i["world_id"].startswith("co_") and i["name"] and i["domain"] for i in items)
    sdr = [i for i in items if "sdr_owner_id" in i]
    assert sdr and all(i["sdr_owner_id"].endswith("@lumenledger.example") for i in sdr)
    roles = {r["email"]: r["role"] for r in db.all(cur, "select email, role from users")}
    assert all(roles[i["sdr_owner_id"]] == "sdr" for i in sdr)
    assert all(roles[i["owner_id"]] == "ae" for i in items if "owner_id" in i)
    n = crm.queue_plan(cur, _plan(cur))
    assert n == len(items)
    assert db.val(cur, "select count(*) from crm_outbox where status = 'queued'") == -(-n // crm.CHUNK)


def test_refusals_are_read_from_the_latest_answer(cur):
    items = [{"world_id": "co_x", "domain": "one.example", "sdr_owner_id": "maya.okafor@lumenledger.example"},
             {"world_id": "co_y", "domain": "two.example"}]
    answer = {"results": [{"index": 0, "id": "acc_1", "created": False, "refused": [{"field": "sdr_owner_id", "reason": "owner_pinned"}]},
                          {"index": 1, "error": "Name is required.", "code": "invalid"}]}
    db.run(cur, "insert into crm_outbox (kind, payload, status, answer, sent_at) values ('books', %s, 'sent', %s, app_now())",
           J({"items": items}), J(answer))
    mine = [r for r in crm.refusals(cur) if r["domain"] == "one.example"]
    assert [(r["field"], r["reason"], r["proposed"]) for r in mine] == [("sdr_owner_id", "owner_pinned", "maya.okafor@lumenledger.example")]
    assert "two.example" in [e["domain"] for e in crm.errors(cur)]
    # A manager resolved the pin and the next send was taken: the refusal is gone, and so is the error.
    later = {"results": [{"index": 0, "id": "acc_1", "created": False, "refused": []}, {"index": 1, "id": "acc_2", "created": True}]}
    db.run(cur, "insert into crm_outbox (kind, payload, status, answer, sent_at) values ('books', %s, 'sent', %s, app_now() + interval '1 minute')",
           J({"items": items}), J(later))
    assert not [r for r in crm.refusals(cur) if r["domain"] == "one.example"]
    assert "two.example" not in [e["domain"] for e in crm.errors(cur)]


def test_the_demo_shows_the_rehearsals_pinned_sdr(cur):
    """The demo replays the rehearsal (world/journal.jsonl): CRM Desk refused one SDR a manager pinned."""
    pinned = [r for r in crm.refusals(cur) if r["reason"] == "owner_pinned"]
    assert len(pinned) == 1 and pinned[0]["field"] == "sdr_owner_id"
    s = crm.summary(cur)
    assert s["sent"] == 1317 and s["errors"] == [] and s["failed"] == []   # distinct accounts, sent twice in the rehearsal


def test_a_crm_that_does_not_answer_leaves_the_row_queued(cur, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.setenv("CRM_DESK_URL", "http://127.0.0.1:9")   # nothing listens there
    monkeypatch.setenv("CRM_DESK_KEY", "rd_test")
    db.run(cur, "insert into crm_outbox (kind, payload) values ('books', %s)", J({"items": [{"domain": "x.example"}]}))
    row = db.one(cur, "select * from crm_outbox where status = 'queued' order by id desc limit 1")
    with pytest.raises(crm.CrmDown):
        crm.deliver(cur, row)
    assert db.val(cur, "select status from crm_outbox where id = %s", row["id"]) == "queued"


def test_activation_queues_the_books_in_the_same_transaction(cur, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    draft = db.val(cur, "select id from territory_plans where status = 'draft' order by id limit 1")
    manager = db.one(cur, "select * from users where role = 'manager'")
    before = db.val(cur, "select count(*) from crm_outbox")
    territories.activate(cur, draft, manager)
    assert db.val(cur, "select count(*) from crm_outbox where plan = %s", draft) > 0
    assert db.val(cur, "select count(*) from crm_outbox") > before


def test_a_refused_send_is_shown_not_retried(cur, monkeypatch):
    monkeypatch.setattr(crm, "_send", lambda body: (401, {"error": "That key is not valid.", "code": "unauthorized"}))
    db.run(cur, "insert into crm_outbox (kind, payload) values ('books', %s)", J({"items": [{"domain": "x.example"}]}))
    row = db.one(cur, "select * from crm_outbox where status = 'queued' order by id desc limit 1")
    crm.deliver(cur, row)
    failed = crm.summary(cur)["failed"]
    assert [f["last_error"] for f in failed if f["id"] == row["id"]] == ["That key is not valid."]


def test_desk_links_take_only_https_and_known_desks(monkeypatch):
    from market.api.app import desk_links
    monkeypatch.setenv("DESK_LINKS", "crm_desk=https://c.example/,events_desk=http://e.example,evil=https://x.example")
    assert desk_links() == {"crm_desk": "https://c.example"}
    monkeypatch.delenv("DESK_LINKS")
    assert desk_links() == {}


def test_go_account_opens_the_company_sheet(demo):
    from fastapi.testclient import TestClient

    from market.api.app import app
    with db.tx() as cur:
        c = db.one(cur, "select id, primary_domain from companies where not sole_trader order by id limit 1")
    client = TestClient(app)
    r = client.get(f"/go/account/world:{crm.world_id(c['primary_domain'])}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"/accounts?sheet=company:{c['id']}"
    assert client.get("/go/account/world:co_000000000000", follow_redirects=False).status_code == 404
