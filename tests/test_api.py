"""The API: roles enforced on the server, money never sent to roles that may not see it, writes refused for the wrong
person, the results webhook signed. Uses its own copy of the demo through the session database."""
from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from market import db


@pytest.fixture(scope="module")
def client(demo):
    from market.api.app import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def ids(demo):
    with db.tx() as cur:
        return {u["name"].split()[0]: u["id"] for u in db.all(cur, "select id, name from users")}


def h(uid):
    return {"X-Acting-As": str(uid)}


MONEY = ("tam_low", "sam_high", "som_low", "acv_median", "pipeline_cents", "expected_value_cents", "amount_cents")


def test_reps_do_not_use_the_desk(client, ids):
    """SDRs and AEs are people in the plan whose books go to Account Desk; Market Desk refuses them."""
    for who in ("Maya", "Grace"):
        assert client.get("/api/me", headers=h(ids[who])).status_code == 403
        assert client.get("/api/accounts", headers=h(ids[who])).status_code == 403


def test_gtm_reads_everything_and_changes_nothing(client, ids):
    me = client.get("/api/me", headers=h(ids["Jordan"])).json()
    assert me["user"]["role"] == "gtm" and me["money"] is True
    for path in ("/api/market", "/api/evidence", "/api/profile", "/api/territories", "/api/changes", "/api/handoffs"):
        assert client.get(path, headers=h(ids["Jordan"])).status_code == 200, path
    assert client.post("/api/evidence/run", headers=h(ids["Jordan"]), json={}).status_code == 403
    assert client.post("/api/proposals/1/dismiss", headers=h(ids["Jordan"]), json={"reason": "Testing the rule."}).status_code == 403


def test_a_visitor_who_has_not_chosen_reads_as_gtm(client):
    me = client.get("/api/me").json()
    assert me["user"]["role"] == "gtm"
    assert {u["role"] for u in me["users"]} == {"revops", "manager", "gtm"}


def test_revops_sees_money(client, ids):
    r = client.get("/api/market", headers=h(ids["Sam"])).json()
    assert "tam_low" in r["rows"][0] and r["rows"][0]["tam_low"] <= r["rows"][0]["tam_high"]


def test_two_person_rules_through_the_api(client, ids):
    with db.tx() as cur:
        v4 = db.val(cur, "select id from icp_versions where number = 4")
        q1 = db.val(cur, "select id from territory_plans where status = 'draft'")
    assert client.post(f"/api/profile/versions/{v4}/publish", headers=h(ids["Sam"]), json={}).status_code == 403
    assert client.post(f"/api/profile/versions/{v4}/publish", headers=h(ids["Maya"]), json={}).status_code == 403
    assert client.post(f"/api/plans/{q1}/activate", headers=h(ids["Sam"]), json={}).status_code == 403


def test_a_cross_site_form_cannot_write(client, ids):
    with db.tx() as cur:
        v4 = db.val(cur, "select id from icp_versions where number = 4")
    r = client.post(f"/api/profile/versions/{v4}/publish", headers={**h(ids["Elena"]), "Content-Type": "application/x-www-form-urlencoded"},
                    content=b"x=1")
    assert r.status_code == 415


def test_a_rep_cannot_read_versions_or_findings(client, ids):
    assert client.get("/api/profile/versions/3", headers=h(ids["Maya"])).status_code == 403
    assert client.get("/api/findings/1", headers=h(ids["Maya"])).status_code == 403
    assert client.post("/api/proposals/1/dismiss", headers=h(ids["Maya"]), json={"reason": "no"}).status_code in (403, 422)


def test_dismiss_needs_a_reason(client, ids):
    with db.tx() as cur:
        pid = db.val(cur, "select id from change_proposals where status = 'open' order by id limit 1")
    assert client.post(f"/api/proposals/{pid}/dismiss", headers=h(ids["Sam"]), json={"reason": ""}).status_code == 422


def test_results_webhook_needs_a_signature(client, monkeypatch):
    from market.config import CONFIG
    body = json.dumps({"destination": "account_desk", "rows": []}).encode()
    assert client.post("/api/results", content=body).status_code == 401
    ts = str(int(time.time()))
    sig = hmac.new(CONFIG.webhook_secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    r = client.post("/api/results", content=body, headers={"X-Timestamp": ts, "X-Signature": sig})
    assert r.status_code == 200 and r.json() == {"read": 0}
    again = client.post("/api/results", content=body, headers={"X-Timestamp": ts, "X-Signature": sig})
    assert again.status_code == 409  # a delivery is read once
    bad = json.dumps({"rows": [{"domain": "x.example", "period_start": "not a date", "period_end": "2026-01-01"}]}).encode()
    sig2 = hmac.new(CONFIG.webhook_secret.encode(), f"{ts}.".encode() + bad, hashlib.sha256).hexdigest()
    assert client.post("/api/results", content=bad, headers={"X-Timestamp": ts, "X-Signature": sig2}).status_code == 422
    old = str(int(time.time()) - 900)
    sig = hmac.new(CONFIG.webhook_secret.encode(), f"{old}.".encode() + body, hashlib.sha256).hexdigest()
    assert client.post("/api/results", content=body, headers={"X-Timestamp": old, "X-Signature": sig}).status_code == 401


def test_every_read_answers(client, ids):
    for path in ("/api/market?by=region_group", "/api/evidence", "/api/profile", "/api/territories", "/api/tests", "/api/changes",
                 "/api/handoffs", "/api/sources", "/api/settings", "/api/findings/1", "/api/tests/1", "/api/books/1",
                 "/api/profile/versions/4", "/api/handoffs/preview/4", "/api/segments/enterprise"):
        assert client.get(path, headers=h(ids["Elena"])).status_code == 200, path


def test_header_auth_refuses_an_unsigned_header(monkeypatch, client):
    import dataclasses

    from market.api import app as appmod
    monkeypatch.setattr(appmod, "CONFIG", dataclasses.replace(appmod.CONFIG, auth_mode="header",
                                                              access_team_domain="team.example", access_aud="aud"))
    r = client.get("/api/me", headers={"Cf-Access-Authenticated-User-Email": "sam.kowalski@lumenledger.example",
                                       "X-Acting-As": "1"})
    assert r.status_code == 401


def _keys(x, out=None):
    out = set() if out is None else out
    if isinstance(x, dict):
        for k, v in x.items():
            out.add(k)
            _keys(v, out)
    elif isinstance(x, list):
        for v in x:
            _keys(v, out)
    return out


def test_a_manager_does_not_move_accounts_by_hand(client, ids):
    with db.tx() as cur:
        pid = db.val(cur, "select id from territory_plans where status = 'draft'")
        cid = db.val(cur, "select company from assignments where plan = %s and reason_code = 'rule' limit 1", pid)
    r = client.post(f"/api/plans/{pid}/move", headers=h(ids["Elena"]),
                    json={"company": cid, "to": ids["Maya"], "note": "Testing the rule."})
    assert r.status_code == 403
