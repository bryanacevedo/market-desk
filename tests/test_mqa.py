"""Phase 3 step 5 (decisions 49 to 51): Market Desk decides marketing qualified accounts when it is connected to CRM Desk,
publishes the rule as a definition, and sends the result through the outbox (kind `mqa`)."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from market import crm, db, mqa
from market.db import J

POINTS = {"form": 10, "meeting": 10, "attended": 5, "email_reply": 5, "call_connected": 5, "linkedin_accepted": 2}
NOW = datetime(2026, 11, 12, 14, 0, tzinfo=timezone.utc)


def _t(i, acct, people, type="form", days=3, **kw):
    return mqa.Touch(activity=f"act_{i}", account=acct, people=tuple(people), type=type, occurred_at=NOW - timedelta(days=days), **kw)


# ---------------------------------------------------------------- the definition

def test_the_first_read_publishes_version_one_and_the_hash_is_crm_desks_hash(cur):
    d = mqa.current(cur)
    assert (d["name"], d["owner_desk"], d["version"], d["changed_by"]) == ("mqa", "market_desk", 1, "system")
    assert d["hash"] == mqa.hash_of(d["body"]) and d["hash"].startswith("sha256:") and len(d["hash"]) == 71
    assert d["body"]["rule"] == {"tiers": ["A", "B"], "untiered": False, "min_points": 20, "min_people": 2, "window_days": 30}
    assert d["body"]["points_from"]["owner_desk"] == "crm_desk"
    assert mqa.current(cur)["version"] == 1                      # reading again publishes nothing


def test_the_published_hash_is_the_documented_one(cur):
    import hashlib
    body = mqa.current(cur)["body"]
    expect = "sha256:" + hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    assert mqa.current(cur)["hash"] == expect


def test_a_changed_rule_is_the_next_version_with_a_name_and_an_unchanged_one_is_not(cur):
    mqa.current(cur)
    same = mqa.set_rule(cur, {"tiers": ["B", "A"]}, "Elena")
    assert same["version"] == 1                                  # a list that is a set is sorted: the same body
    v2 = mqa.set_rule(cur, {"min_points": 30}, "Elena")
    assert (v2["version"], v2["changed_by"], v2["body"]["rule"]["min_points"]) == (2, "Elena", 30)
    assert v2["hash"] != mqa.current(cur)["hash"] or v2["version"] == mqa.current(cur)["version"]
    assert [v["version"] for v in mqa.versions(cur)["versions"]] == [2, 1]
    assert mqa.version(cur, 1)["body"]["rule"]["min_points"] == 20 and mqa.version(cur, 9) is None
    assert mqa.rule(cur)["min_points"] == 30


@pytest.mark.parametrize("bad", [{"tiers": []}, {"tiers": ["Z"]}, {"min_points": 0}, {"min_people": True}, {"window_days": 400}])
def test_a_rule_that_cannot_work_is_refused(cur, bad):
    with pytest.raises(ValueError):
        mqa.set_rule(cur, bad, "Elena")


# ---------------------------------------------------------------- what engagement is worth

def test_points_follow_crm_desks_published_weights_and_our_own_outbound_pays_nothing():
    cases = [(dict(type="form"), 10), (dict(type="attended"), 5), (dict(type="meeting", meeting_status="booked"), 10),
             (dict(type="meeting", meeting_status="held"), 10), (dict(type="meeting", meeting_status="no_show"), 0),
             (dict(type="email", direction="in"), 5), (dict(type="email", direction="out"), 0),
             (dict(type="call", outcome="connected"), 5), (dict(type="call", outcome="voicemail"), 0),
             (dict(type="linkedin", direction="out", outcome="accepted"), 2), (dict(type="linkedin", direction="out", outcome="sent"), 0),
             (dict(type="note"), 0), (dict(type="proposal"), 0)]
    for kw, expect in cases:
        assert mqa.worth(mqa.Touch(activity="a", account="x", people=("p",), **kw), POINTS) == expect, kw


def test_engagement_counts_points_and_people_inside_the_window_once_per_person():
    touches = [_t(1, "acc_1", ["p1"], "form"), _t(2, "acc_1", ["p2"], "email", direction="in"),
               _t(3, "acc_1", ["p2", "p3"], "meeting", meeting_status="held"),   # a meeting pays everyone who attended
               _t(3, "acc_1", ["p2"], "meeting", meeting_status="held"),          # the same activity again: counted once
               _t(4, "acc_1", ["p4"], "form", days=45),                           # outside the window
               _t(5, "acc_1", ["p5"], "email", direction="out"),                  # our own touch
               _t(6, "acc_2", ["p9"], "form")]
    got = mqa.engagement(touches, POINTS, NOW - timedelta(days=30), NOW)
    assert got == {"acc_1": (10 + 5 + 10 + 10, 3), "acc_2": (10, 1)}


def test_an_activity_with_no_account_takes_the_persons_account_and_nothing_else_is_kept():
    asked = []

    def account_of(p):
        asked.append(p)
        return {"p1": "acc_1"}.get(p)
    got = mqa.engagement([_t(1, None, ["p1"], "form"), _t(2, None, ["ghost"], "form")], POINTS, NOW - timedelta(days=30), NOW, account_of)
    assert got == {"acc_1": (10, 1)} and asked == ["p1", "ghost"]
    assert all(isinstance(v, tuple) and all(isinstance(n, int) for n in v) for v in got.values())     # counts only


# ---------------------------------------------------------------- fit, and who qualifies

@pytest.fixture
def domains(cur):
    """One company scored A, one scored C and one with no score under the published version."""
    v = db.val(cur, "select id from icp_versions where status = 'published'")
    pick = lambda tier: db.val(cur, """select c.primary_domain from companies c join account_fit f on f.company = c.id
                                       where f.icp_version = %s and f.tier = %s and not c.sole_trader order by c.id limit 1""", v, tier)  # noqa: E731
    unscored = db.val(cur, """select c.primary_domain from companies c where not c.sole_trader and not exists
                              (select 1 from account_fit f where f.company = c.id and f.icp_version = %s) order by c.id limit 1""", v)
    if unscored is None:      # every company is scored in the demo: take one and drop its score for this test
        unscored = db.val(cur, "select c.primary_domain from companies c where not c.sole_trader order by c.id desc limit 1")
        db.run(cur, "delete from account_fit where icp_version = %s and company = (select id from companies where primary_domain = %s)", v, unscored)
    return {"A": pick("A"), "C": pick("C"), "none": unscored}


def _facts(domain, **kw):
    return {"domain": domain, "type": "prospect", "do_not_prospect": False, "deleted": False, "tier": None} | kw


def test_decide_needs_the_fit_the_points_the_people_a_prospect_that_may_be_prospected(cur, domains):
    r = mqa.rule(cur)
    found = {"a": (25, 2), "c": (25, 2), "few": (25, 1), "low": (19, 3), "cust": (40, 3), "dnp": (40, 3), "gone": (40, 3), "none": (30, 2)}
    facts = {"a": _facts(domains["A"]), "c": _facts(domains["C"]), "few": _facts(domains["A"]), "low": _facts(domains["A"]),
             "cust": _facts(domains["A"], type="customer"), "dnp": _facts(domains["A"], do_not_prospect=True),
             "gone": _facts(domains["A"], deleted=True), "none": _facts(domains["none"])}
    got = mqa.decide(cur, {k: v for k, v in found.items()}, {k: v for k, v in facts.items() if k not in ("few", "low")}, r)
    # "a" qualifies; the unscored company does not (a tier is required); C is not a tier the rule names; a customer, a flagged and a deleted account never do
    assert set(got) == {domains["A"]} and got[domains["A"]] == (25, 2)
    # the one-person account fails on people and the 19-point one on points, even with the facts at hand
    assert mqa.decide(cur, {"few": (25, 1), "low": (19, 3)}, {"few": _facts(domains["A"]), "low": _facts(domains["A"])}, r) == {}


def test_a_tier_is_required_by_default_and_untiered_is_the_rules_choice(cur, domains):
    assert mqa.rule(cur)["untiered"] is False  # Bryan, 2026-11-13: MQA requires a tier
    assert mqa.decide(cur, {"n": (30, 2)}, {"n": _facts(domains["none"])}, mqa.rule(cur)) == {}
    assert mqa.decide(cur, {"n": (30, 2)}, {"n": _facts(domains["none"])}, {**mqa.rule(cur), "untiered": True})


def test_a_company_this_desk_does_not_hold_is_judged_by_the_tier_crm_desk_holds(cur):
    r = mqa.rule(cur)
    unknown = lambda tier: mqa.decide(cur, {"n": (30, 2)}, {"n": _facts("not-ours.example", tier=tier)}, r)  # noqa: E731
    assert unknown("A") and not unknown(None) and not unknown("Not judged") and not unknown("C")


# ---------------------------------------------------------------- what is sent

def test_plan_marks_new_accounts_updates_counts_and_clears_ended_marks():
    marked = {"stay.example": {"mqa_at": "2026-11-01T00:00:00+00:00", "mqa_points": 20, "mqa_people": 2},
              "grow.example": {"mqa_at": "2026-11-01T00:00:00+00:00", "mqa_points": 20, "mqa_people": 2},
              "gone.example": {"mqa_at": "2026-11-01T00:00:00+00:00", "mqa_points": 20, "mqa_people": 2}}
    desired = {"new.example": (30, 3), "stay.example": (20, 2), "grow.example": (35, 3)}
    items = {i["domain"]: i for i in mqa.plan(desired, marked, NOW)}
    assert items["new.example"] == {"world_id": crm.world_id("new.example"), "domain": "new.example", "mqa_at": NOW.isoformat(), "mqa_points": 30, "mqa_people": 3}
    assert items["grow.example"]["mqa_points"] == 35 and "mqa_at" not in items["grow.example"]     # the date a mark began is not rewritten
    assert items["gone.example"]["mqa_at"] is None and "mqa_points" not in items["gone.example"]
    assert "stay.example" not in items


class StubEngagement:
    """Implements the four optional engagement methods and nothing of the Salesforce-shaped interface."""

    def __init__(self, touches, facts, marked=None, points=POINTS):
        self._touches, self._facts, self._marked, self._points = touches, facts, marked or {}, points
        self.asked = []

    def definition(self, name):
        return {"name": name, "owner_desk": "crm_desk", "version": 4, "hash": "sha256:" + "ab" * 32, "body": {"rule": {"points": self._points}}}

    def touches(self, since):
        self.asked.append(since)
        return iter(self._touches)

    def account_facts(self, account_id):
        return self._facts[account_id]

    def marked(self):
        return self._marked

    def contact_account(self, contact_id):
        return None


def _engaged(domain):
    return [_t(1, "acc_q", ["p1"], "form"), _t(2, "acc_q", ["p2"], "meeting", meeting_status="booked"), _t(3, "acc_q", ["p3"], "email", direction="in")], \
           {"acc_q": _facts(domain)}


def test_a_run_queues_the_changes_as_kind_mqa_and_keeps_no_person(cur, domains, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    touches, facts = _engaged(domains["A"])
    out = mqa.sync(StubEngagement(touches, facts, {"old.example": {"mqa_at": "2026-10-20T00:00:00+00:00", "mqa_points": 21, "mqa_people": 2}}), now=NOW, cur=cur)
    assert (out["qualify"], out["marked"], out["cleared"], out["queued"]) == (1, 1, 1, 2)
    assert out["points_from"] == {"name": "mql", "owner_desk": "crm_desk", "version": 4, "hash": "sha256:" + "ab" * 32}
    rows = db.all(cur, "select * from crm_outbox where kind = 'mqa' order by id")
    assert len(rows) == 1 and rows[0]["status"] == "queued" and rows[0]["payload"]["definition_version"] == 1
    items = {i["domain"]: i for i in rows[0]["payload"]["items"]}
    assert items[domains["A"]] == {"world_id": crm.world_id(domains["A"]), "domain": domains["A"], "mqa_at": NOW.isoformat(), "mqa_points": 25, "mqa_people": 3}
    assert items["old.example"]["mqa_at"] is None
    blob = json.dumps(rows[0]["payload"])
    assert not any(p in blob for p in ("p1", "p2", "p3", "act_"))                      # no person and no activity id leaves the run
    assert db.one(cur, "select * from definitions_read where name = 'mql'")["version"] == 4
    assert db.val(cur, "select count(*) from jobs where kind = 'crm_deliver' and status = 'queued'")


def test_the_window_is_the_rules_and_ends_now(cur, domains, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    reader = StubEngagement(*_engaged(domains["A"]))
    out = mqa.sync(reader, now=NOW, cur=cur)
    assert reader.asked == [NOW - timedelta(days=30)] and out["window_from"] == (NOW - timedelta(days=30)).isoformat()


def test_a_newer_run_replaces_a_request_still_waiting(cur, domains, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    mqa.sync(StubEngagement(*_engaged(domains["A"])), now=NOW, cur=cur)
    mqa.sync(StubEngagement(*_engaged(domains["A"])), now=NOW, cur=cur)
    assert db.val(cur, "select count(*) from crm_outbox where kind = 'mqa' and status = 'queued'") == 1
    assert db.val(cur, "select count(*) from crm_outbox where kind = 'mqa' and status = 'cancelled'") == 1


def test_a_crm_that_does_not_follow_this_desk_is_not_asked_again_every_hour(cur, domains, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    touches, facts = _engaged(domains["A"])
    mqa.sync(StubEngagement(touches, facts), now=NOW, cur=cur)
    row = db.one(cur, "select * from crm_outbox where kind = 'mqa'")
    refused = {"results": [{"index": 0, "id": "a", "refused": [{"field": f, "reason": "computed_by_crm_desk"} for f in ("mqa_at", "mqa_points", "mqa_people")]}]}
    db.run(cur, "update crm_outbox set status = 'sent', answer = %s, sent_at = app_now() where id = %s", J(refused), row["id"])
    out = mqa.sync(StubEngagement(touches, facts), now=NOW + timedelta(hours=1), cur=cur)
    assert out["queued"] == 0 and db.val(cur, "select count(*) from crm_outbox where kind = 'mqa'") == 1
    # the engagement moved: that is a new decision, so it is sent
    touches2 = touches + [_t(9, "acc_q", ["p3"], "form")]
    assert mqa.sync(StubEngagement(touches2, facts), now=NOW + timedelta(hours=2), cur=cur)["queued"] == 1


def test_a_reader_without_the_engagement_methods_decides_nothing(cur, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    class SalesforceShaped:
        def opportunities_changed(self, since, limit): ...
        def accounts_changed(self, since, limit): ...
    with pytest.raises(mqa.MqaUnavailable):
        mqa.sync(SalesforceShaped(), now=NOW, cur=cur)
    assert not db.val(cur, "select count(*) from crm_outbox where kind = 'mqa'")


def test_a_definition_without_points_decides_nothing(cur, monkeypatch):
    with pytest.raises(mqa.MqaUnavailable):
        mqa.sync(StubEngagement([], {}, points={"form": 10}), now=NOW, cur=cur)


def test_nothing_runs_without_a_crm_and_the_schedule_can_be_turned_off(monkeypatch):
    monkeypatch.delenv("CRM", raising=False)
    assert not mqa.enabled()
    monkeypatch.setenv("CRM", "crmdesk")
    assert mqa.enabled()
    monkeypatch.setenv("CRM_MQA", "0")
    assert not mqa.enabled()


def test_the_job_keeps_its_schedule_through_an_outage(cur, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.setenv("CRM_DESK_URL", "http://crm.invalid")
    monkeypatch.setenv("CRM_DESK_KEY", "k")

    def down(reader, **kw):
        raise crm.CrmDown("CRM Desk did not answer", 120)
    monkeypatch.setattr(mqa, "sync", down)
    mqa._run(cur, {})
    assert db.val(cur, "select count(*) from jobs where kind = 'crm_mqa' and status = 'queued'") == 1


# ---------------------------------------------------------------- the outbox: same batch call, same key, same journal

def test_delivery_uses_the_batch_call_the_idempotency_key_and_journals_the_kind(cur, monkeypatch, tmp_path):
    journal = tmp_path / "j.jsonl"
    monkeypatch.setenv("CRM_JOURNAL", str(journal))
    sent = []
    answer = {"results": [{"index": 0, "id": "acc_1", "changed": ["mqa_at", "mqa_points", "mqa_people"], "refused": []}]}
    monkeypatch.setattr(crm, "_send", lambda body, key=None: (sent.append((body, key)), (200, answer))[1])
    payload = {"items": [{"world_id": "co_x", "domain": "x.example", "mqa_at": NOW.isoformat(), "mqa_points": 25, "mqa_people": 3}], "definition_version": 1}
    db.run(cur, "insert into crm_outbox (kind, payload) values ('mqa', %s)", J(payload))
    row = db.one(cur, "select * from crm_outbox where kind = 'mqa'")
    crm.deliver(cur, row)
    assert sent == [(payload, f"market-desk:outbox:{row['id']}")]
    (line,) = [json.loads(x) for x in journal.read_text().splitlines()]
    assert (line["actor"], line["method"], line["path"], line["kind"], line["status"]) == ("market_desk", "POST", "/accounts/batch", "mqa", 200)
    assert line["body"] == payload and line["answer"] == answer


def test_replay_keeps_an_mqa_row_as_an_mqa_row(cur, tmp_path):
    j = tmp_path / "j.jsonl"
    at = "2026-11-12T10:00:00+00:00"
    body = {"items": [{"world_id": "co_x", "domain": "x.example", "mqa_at": at, "mqa_points": 25, "mqa_people": 3}], "definition_version": 1}
    j.write_text("\n".join(json.dumps(x) for x in [
        {"at": at, "actor": "market_desk", "method": "GET", "path": "/changes/activities", "since": at, "count": 4, "next": None},
        {"at": at, "actor": "market_desk", "method": "POST", "path": "/accounts/batch", "kind": "mqa", "body": body, "status": 200,
         "answer": {"results": [{"index": 0, "id": "a", "refused": [{"field": "mqa_at", "reason": "computed_by_crm_desk"}]}]}}]) + "\n")
    assert crm.replay(cur, j) == 1
    assert db.val(cur, "select count(*) from crm_outbox where kind = 'mqa' and status = 'sent'") == 1
    assert [r["reason"] for r in crm.refusals(cur) if r["domain"] == "x.example"] == ["computed_by_crm_desk"]


def test_handoffs_says_why_crm_desk_refused_an_mqa_field(cur):
    from market.api import views
    db.run(cur, "insert into crm_outbox (kind, payload, status, answer, sent_at) values ('mqa', %s, 'sent', %s, app_now())",
           J({"items": [{"world_id": "co_x", "domain": "x.example", "mqa_at": NOW.isoformat(), "mqa_points": 25, "mqa_people": 3}]}),
           J({"results": [{"index": 0, "id": "a", "refused": [{"field": "mqa_points", "reason": "computed_by_crm_desk"}]}]}))
    s = views.crm_desk(cur)
    r = [r for r in s["refusals"] if r["domain"] == "x.example"][0]
    assert r["what"] == "Engagement points" and "decides marketing qualified itself" in r["why"]
    assert s["mqa"]["rule_version"] == 1 and s["mqa"]["last_request"]["items"] == 1


# ---------------------------------------------------------------- the real reader, on responses shaped like CRM Desk's

def _reader(handler):
    return crm.CrmDeskReader("http://crm.test", "rd_k", client=httpx.Client(base_url="http://crm.test", transport=httpx.MockTransport(handler),
                                                                           headers={"authorization": "Bearer rd_k"}))


def test_the_crm_desk_reader_reduces_activities_to_scoring_facts_and_drops_the_people():
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.url.path, dict(req.url.params)))
        if req.url.path == "/api/v1/changes/activities":
            if req.url.params.get("since", "").startswith("2026-10"):
                return httpx.Response(200, json={"data": [
                    {"id": "act_1", "type": "email", "direction": "in", "subject": "Re: Hello", "body": "private words", "occurred_at": "2026-11-10T10:00:00-04:00",
                     "account_id": "acc_1", "contact_id": "con_1", "outcome": None, "meeting_status": None, "contact_email": "a@x.example",
                     "attendees": [{"contact_id": "con_1", "email": "a@x.example"}]},
                    {"id": "act_2", "type": "meeting", "direction": None, "occurred_at": "2026-11-11T10:00:00-04:00", "account_id": None, "contact_id": "con_2",
                     "meeting_status": "held", "attendees": [{"contact_id": "con_2"}, {"contact_id": "con_3"}]},
                    {"id": "act_3", "deleted": True, "object": "activity", "updated_at": "2026-11-11T10:00:00-04:00"}],
                    "next": "2026-11-11T10:00:00-04:00|act_2", "has_more": True})
            return httpx.Response(200, json={"data": [], "next": "2026-11-11T10:00:00-04:00|act_2", "has_more": False})
        raise AssertionError(req.url.path)
    got = list(_reader(handler).touches(datetime(2026, 10, 13, tzinfo=timezone.utc)))
    assert [(t.activity, t.account, t.people, t.type, t.direction, t.meeting_status) for t in got] == [
        ("act_1", "acc_1", ("con_1",), "email", "in", None), ("act_2", None, ("con_2", "con_3"), "meeting", None, "held")]
    assert not any("private" in str(vars(t)) or "x.example" in str(vars(t)) for t in got)
    assert seen[0][1]["since"] == "2026-10-13T00:00:00+00:00" and seen[1][1]["since"] == "2026-11-11T10:00:00-04:00|act_2"


def test_the_crm_desk_reader_reads_the_points_the_facts_and_the_marks():
    account = {"id": "acc_1", "object": "account", "domain": "q.example", "type": "prospect", "do_not_prospect": {"value": True, "source": "x", "at": None},
               "market": {"tier": "B"}, "merged_into": None, "deleted": False, "mqa_at": "2026-11-01T10:00:00-04:00", "mqa_points": 22, "mqa_people": 2}

    def handler(req: httpx.Request):
        p = req.url.path
        if p == "/api/v1/definitions/mql":
            return httpx.Response(200, json={"name": "mql", "owner_desk": "crm_desk", "version": 1, "hash": "sha256:" + "0" * 64,
                                             "body": {"automatic": True, "rule": {"points": POINTS}}})
        if p == "/api/v1/accounts/acc_1":
            return httpx.Response(200, json=account)
        if p == "/api/v1/accounts/acc_gone" or p == "/api/v1/contacts/con_gone":
            return httpx.Response(404, json={"error": "No such record.", "code": "not_found"})
        if p == "/api/v1/contacts/con_1":
            return httpx.Response(200, json={"id": "con_1", "account_id": "acc_1", "email": "a@x.example"})
        if p == "/api/v1/changes/accounts":
            return httpx.Response(200, json={"data": [account, {**account, "id": "acc_2", "domain": "n.example", "mqa_at": None},
                                                      {"id": "acc_3", "deleted": True}], "next": "n", "has_more": False})
        raise AssertionError(p)
    r = _reader(handler)
    points, used = mqa.read_points(r)
    assert points == POINTS and used["version"] == 1 and used["hash"].startswith("sha256:")
    assert r.account_facts("acc_1") == {"domain": "q.example", "type": "prospect", "do_not_prospect": True, "deleted": False, "tier": "B"}
    assert r.account_facts("acc_gone")["deleted"] is True and r.contact_account("con_gone") is None and r.contact_account("con_1") == "acc_1"
    assert r.marked() == {"q.example": {"mqa_at": "2026-11-01T10:00:00-04:00", "mqa_points": 22, "mqa_people": 2}}


def test_the_crm_desk_reader_fails_closed(monkeypatch):
    for status, text in ((500, "CRM Desk"), (403, "403")):
        with pytest.raises(crm.CrmDown, match=text):
            _reader(lambda req, s=status: httpx.Response(s, json={})).definition("mql")


# ---------------------------------------------------------------- the published definition, over HTTP

@pytest.fixture(scope="module")
def client(demo):
    from fastapi.testclient import TestClient

    from market.api.app import app
    with TestClient(app) as c:
        yield c


def test_the_definition_is_published_in_crm_desks_shape(client):
    j = client.get("/api/definitions").json()
    assert (j["desk"], j["schema_version"]) == ("market_desk", 1)
    (d,) = j["definitions"]
    assert (d["name"], d["owner_desk"], d["version"]) == ("mqa", "market_desk", 1) and d["hash"] == mqa.hash_of(d["body"])
    assert j["index"][0]["link"] == "/api/definitions/mqa" and j["index"][0]["read_at"] is None
    one = client.get("/api/definitions/mqa").json()
    assert one == d
    assert client.get("/api/definitions/mqa?version=1").json() == d
    assert client.get("/api/definitions/mqa?version=99").status_code == 404
    assert client.get("/api/definitions/icp").status_code == 404
    v = client.get("/api/definitions/mqa/versions").json()
    assert v["name"] == "mqa" and v["versions"][0]["version"] == 1 and "body" not in v["versions"][0]


def test_the_definition_holds_no_company_person_or_money(client):
    text = json.dumps(client.get("/api/definitions").json())
    assert "@" not in text and "cents" not in text
