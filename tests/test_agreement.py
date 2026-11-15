"""What Market Desk states for Tally in CRM Desk (CRM Desk docs/TALLY-SPEC.md section 5) and where Events Desk reads the ICP."""
import json

import pytest

from market import agreement, db
from market.db import J


@pytest.fixture(scope="module")
def client(demo):
    from fastapi.testclient import TestClient

    from market.api.app import app
    with TestClient(app) as c:
        yield c


def _auth(key="desk-secret"):
    return {"Authorization": f"Bearer {key}"}


def test_nothing_is_served_without_a_read_key_and_a_wrong_key_is_refused(client, monkeypatch):
    monkeypatch.delenv("DESK_READ_KEY", raising=False)
    for path in ("/api/agreement/statement", "/api/agreement/owners", "/api/icp"):
        assert client.get(path).status_code == 404, path
    monkeypatch.setenv("DESK_READ_KEY", "desk-secret")
    for path in ("/api/agreement/statement", "/api/agreement/owners", "/api/icp"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=_auth("nope")).status_code == 401, path
    assert client.get("/api/agreement/statement", headers=_auth()).status_code == 200


def test_the_statement_has_crm_desks_contract_and_holds_no_person_or_money(client, monkeypatch):
    monkeypatch.setenv("DESK_READ_KEY", "desk-secret")
    j = client.get("/api/agreement/statement", headers=_auth()).json()
    assert (j["desk"], j["schema_version"]) == ("market_desk", 1) and j["as_of"]
    d, i = j["definitions_owned"]
    assert i["name"] == "icp" and i["version"] == j["plan"]["icp_version"] and i["published_at"]      # Tally times rule 3's grace from this
    assert d["name"] == "mqa" and d["hash"].startswith("sha256:") and d["version"] >= 1
    assert "outbox" not in j                                   # no CRM set: the desk states no queue, and Tally says so
    p = j["plan"]
    assert set(p) >= {"id", "name", "activated_at", "effective_on", "batches", "batches_sent", "items", "items_sent", "owners_etag", "icp_version"}
    assert p["icp_version"].startswith("v") and "@" not in json.dumps(j) and "cents" not in json.dumps(j)


def test_the_queue_and_the_plan_count_the_outbox(cur, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    plan = db.val(cur, "select id from territory_plans where status = 'active'")
    db.run(cur, "delete from crm_outbox where plan = %s", plan)
    for status, attempts, err in (("sent", 1, None), ("sent", 1, None), ("queued", 2, None), ("failed", 3, "answered 502")):
        db.run(cur, "insert into crm_outbox (plan, kind, payload, status, attempts, last_error, sent_at) values (%s, 'books', %s, %s, %s, %s, "
                    "case when %s = 'sent' then app_now() end)", plan, J({"items": [{"domain": "a.example"}] * 100}), status, attempts, err, status)
    db.run(cur, "insert into crm_outbox (plan, kind, payload, status) values (%s, 'books', %s, 'cancelled')", plan, J({"items": [{"domain": "x.example"}]}))
    st = agreement.statement(cur)
    books = next(o for o in st["outbox"] if o["kind"] == "books")
    assert (books["to"], books["queued"], books["retrying"], books["failed"], books["last_error"]) == ("crm_desk", 1, 1, 1, "answered 502")
    assert books["oldest_queued_at"] and books["last_sent_at"]
    p = st["plan"]
    assert (p["batches"], p["batches_sent"], p["items"], p["items_sent"]) == (4, 2, 400, 200)      # the cancelled row is not a batch


def test_the_etag_changes_when_an_owner_moves(cur):
    plan = db.one(cur, "select * from territory_plans where status = 'active'")
    before = agreement.statement(cur)["plan"]["owners_etag"]
    assert agreement.statement(cur)["plan"]["owners_etag"] == before
    c = db.one(cur, "select company, owner from assignments where plan = %s limit 1", plan["id"])
    other = db.val(cur, "select id from users where role in ('sdr', 'ae') and id is distinct from %s limit 1", c["owner"])
    db.run(cur, "update assignments set owner = %s where plan = %s and company = %s", other, plan["id"], c["company"])
    assert agreement.statement(cur)["plan"]["owners_etag"] != before


def test_owners_are_paged_and_the_planned_owner_is_in_force_when_the_plan_is_in_effect(cur):
    plan = db.val(cur, "select id from territory_plans where status = 'active'")
    first = agreement.owners(cur, str(plan), None)
    assert first["plan"] == str(plan) and 0 < len(first["data"]) <= agreement.PAGE
    r = first["data"][0]
    assert r["domain"] and r["world_id"].startswith("co_") and r["owner_email"] == r["planned_owner_email"] and r["sdr_owner_email"] == r["sdr_planned_owner_email"]
    seen, cursor, n = set(), None, 0
    while True:
        page = agreement.owners(cur, str(plan), cursor)
        seen |= {x["domain"] for x in page["data"]}
        n += len(page["data"])
        cursor = page["next"]
        if not cursor:
            break
    assert n == len(seen) == db.val(cur, "select count(*) from assignments a join companies c on c.id = a.company where a.plan = %s and not c.sole_trader", plan)
    with pytest.raises(agreement.PlanChanged):
        agreement.owners(cur, "999999", None)


def test_a_scheduled_plan_states_the_plan_in_effect_as_what_is_in_force(cur):
    active = db.one(cur, "select * from territory_plans where status = 'active'")
    sdr = db.val(cur, "select id from users where role = 'sdr' limit 1")
    ae = db.val(cur, "select id from users where role = 'ae' limit 1") or sdr
    new = db.val(cur, """insert into territory_plans (name, status, based_on, author, activated_by, activated_at, effective_on)
                         values ('Next', 'scheduled', %s, %s, (select id from users where role = 'manager' limit 1), app_now(), app_now()::date + 30) returning id""",
                 active["based_on"], active["author"])
    c = db.val(cur, "select company from assignments where plan = %s limit 1", active["id"])
    db.run(cur, "insert into assignments (plan, company, owner, reason_code) values (%s, %s, %s, 'rule')", new, c, ae)
    st = agreement.statement(cur)["plan"]
    assert st["id"] == str(new) and st["name"] == "Next"
    rows = {x["domain"]: x for x in agreement.owners(cur, str(new), None)["data"]}
    dom = db.val(cur, "select primary_domain from companies where id = %s", c)
    mine = rows[dom]
    assert mine["planned_owner_email"] == db.val(cur, "select email from users where id = %s", ae) and mine["effective_on"] == st["effective_on"]


def test_the_icp_is_served_as_the_events_desk_document_with_a_version_and_a_hash(client, monkeypatch):
    monkeypatch.setenv("DESK_READ_KEY", "desk-secret")
    j = client.get("/api/icp", headers=_auth()).json()
    assert (j["desk"], j["name"], j["format"]) == ("market_desk", "icp", "icp.md") and j["version"] >= 1
    assert j["markdown"].startswith("# ") and "## Size" in j["markdown"] and j["hash"].startswith("sha256:") and len(j["hash"]) == 71
    assert client.get("/api/icp", headers=_auth()).json() == j      # the same text and hash each time
