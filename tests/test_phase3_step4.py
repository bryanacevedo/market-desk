"""Shared-world Phase 3, step 4 (decisions 46 to 48): publishing sends the profile version to a CRM, the deals CSV
import (the standalone evidence path), the CRM read side in Salesforce's nouns, INTEGRATED_WITH, and one CRM chosen."""
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from market import crm, db, deals_in, evidence, profiles
from market.config import Config
from market.db import J

HEAD = "opportunity_id,account_domain,account_name,created_date,stage,is_closed,is_won,amount,type,country,lead_source,loss_reason,industry,employees,competitor,owner_email,close_date\n"


@pytest.fixture
def who(cur):
    return {u["name"].split()[0]: u for u in db.all(cur, "select * from users")}


def _csv(*lines):
    """Every closed row gets a close date (or the one after a '|'); open rows get none."""
    out = []
    for line in lines:
        line, _, date = line.partition("|")
        out.append(line + "," + (date or ("2026-03-01" if line.split(",")[5] == "true" else "")))
    return HEAD + "\n".join(out) + "\n"


def _import(cur, text, system="csv", **kw):
    rows, rejected, info = deals_in.read_csv(text, **{k: v for k, v in kw.items() if k == "blank_type"})
    return deals_in.upsert(cur, rows, system, actor="test", rejected=rejected, info=info)


# ---------------------------------------------------------------- the deals CSV

def test_a_file_without_the_required_columns_is_refused_whole():
    with pytest.raises(ValueError, match="no column for"):
        deals_in.read_csv("opportunity_id,amount\n1,5\n")


def test_import_writes_deals_a_company_and_a_customer_and_nothing_invented(cur):
    rep = _import(cur, _csv(
        "o-1,newco.example,Newco,2026-01-10,Closed won,true,true,48000,New Business,DE,Inbound,,Software,120,,",
        "o-2,newco.example,Newco,2026-02-01,Closed lost,true,false,30000,New Business,DE,Weird Source,Went with Meterly because of price. Mail bob@x.com,Software,120,Meterly,",
        "o-3,newco.example,Newco,2026-03-01,Evaluation,false,false,20000,Existing Business,DE,,,Software,120,,"))
    assert (rep["inserted"], rep["updated"], rep["rejected"]) == (3, 0, [])
    c = db.one(cur, "select * from companies where primary_domain = 'newco.example'")
    assert (c["origin"], c["country"], c["region"], c["region_group"]) == ("deals_import", "DE", "DACH", "Europe")
    deals = {d["external_id"]: d for d in db.all(cur, "select * from deals where company = %s", c["id"])}
    assert deals["o-1"]["outcome"] == "won" and deals["o-1"]["source"] == "inbound" and deals["o-1"]["kind"] == "new"
    assert deals["o-2"]["source"] is None                      # a lead source we cannot map is unknown, not a guess
    assert deals["o-2"]["loss_code"] == "price" and deals["o-2"]["competitor"] == "Meterly"
    assert "bob@x.com" not in deals["o-2"]["loss_reason_text"]  # no people
    assert deals["o-3"]["kind"] == "expansion" and deals["o-3"]["outcome"] == "open"
    assert deals["o-1"]["snapshot_source"] == "csv_row" and deals["o-1"]["snapshot"]["employees"] == 120
    assert "pricing_model" not in deals["o-1"]["snapshot"]     # a trait the file did not give is absent
    cust = db.one(cur, "select * from customers where company = %s", c["id"])
    assert cust["origin"] == "deals_import" and cust["arr_cents"] == 4_800_000
    assert db.val(cur, "select lifecycle from companies where id = %s", c["id"]) == "customer"


def test_importing_again_updates_and_never_duplicates(cur):
    _import(cur, _csv("o-9,again.example,Again,2026-01-10,Proposal,false,false,10000,New Business,US,Outbound,,,,,"))
    snap = db.val(cur, "select snapshot from deals where external_id = 'o-9'")
    rep = _import(cur, _csv("o-9,again.example,Again,2026-01-10,Closed won,true,true,12000,New Business,US,Outbound,,,,,|2026-03-01"))
    assert (rep["inserted"], rep["updated"]) == (0, 1)
    d = db.all(cur, "select * from deals where external_id = 'o-9'")
    assert len(d) == 1 and d[0]["outcome"] == "won" and d[0]["amount_cents"] == 1_200_000
    assert d[0]["snapshot"] == snap                            # the snapshot is never rewritten by a later import


def test_a_closed_deal_without_its_close_date_is_rejected(cur):
    _, rejected, _ = deals_in.read_csv(HEAD + "o-8,a.example,A,2026-01-10,Closed won,true,true,1,New Business,US,,,,,,\n")
    assert rejected and "close date" in rejected[0]["reason"]


def test_rows_that_cannot_be_trusted_are_rejected_by_number_with_a_reason(cur):
    rep = _import(cur, _csv(
        "r-1,unknown-co.example,Unknown,2026-01-10,Open,false,false,100,New Business,,,,,,,",           # a new company with no country
        "r-2,x.example,X,2026-01-10,Open,false,false,100,,US,,,,,,",                                      # blank type
        "r-3,x.example,X,2026-01-10,Open,false,false,100,Renewal,US,,,,,,",                               # a renewal: skipped, counted
        "r-4,x.example,X,2999-01-10,Open,false,false,100,New Business,US,,,,,,",                          # after today
        "r-5,x.example,X,2026-01-10,Open,false,false,abc,New Business,US,,,,,,",                          # not a number
        "r-6,not a domain,X,2026-01-10,Open,false,false,1,New Business,US,,,,,,"))
    reasons = {r["row"]: r["reason"] for r in rep["rejected"]}
    assert set(reasons) == {2, 3, 5, 6, 7} and "country" in reasons[2] and "type" in reasons[3] and "after today" in reasons[5]
    assert rep["renewals_skipped"] == 1 and rep["inserted"] == 0
    assert not db.val(cur, "select count(*) from deals where external_id like 'r-%'")


def test_a_blank_type_can_be_read_as_new_business_when_the_operator_says_so(cur):
    rows, rejected, _ = deals_in.read_csv(_csv("b-1,blank.example,Blank,2026-01-10,Open,false,false,100,,US,,,,,,"), blank_type="new business")
    assert len(rows) == 1 and not rejected


def test_currency_other_than_usd_is_refused(cur):
    text = HEAD.rstrip() + ",currency\n" + "c-1,eur.example,Eur,2026-01-10,Open,false,false,100,New Business,DE,,,,,,,,EUR\n"
    _, rejected, _ = deals_in.read_csv(text)
    assert rejected and "USD" in rejected[0]["reason"]


def test_loss_reasons_map_only_when_we_can_and_say_when_we_could_not(cur):
    assert deals_in.loss_code("Too expensive") == ("price", "import_map")
    assert deals_in.loss_code("champion left") == ("champion_left", "import_map")
    assert deals_in.loss_code("the weather") == (None, "unmapped")
    assert deals_in.loss_code("") == (None, "none")


def test_imported_deals_feed_evidence_and_churn_is_not_claimed(cur):
    db.run(cur, "delete from deals")                           # inside this test's transaction: evidence sees only the imported history
    db.run(cur, "delete from customers")
    lines = [f"e-{i},ev{i}.example,Ev{i},2025-0{1 + i % 3}-05,Closed won,true,true,40000,New Business,US,Outbound,,Software,200,,|2025-09-01"
             for i in range(6)]
    rep = _import(cur, _csv(*lines))
    assert rep["inserted"] == 6
    run = evidence.run(cur)
    assert db.val(cur, "select count(*) from findings where run = %s and trait = 'industry'", run) >= 1
    # these customers are a year old and none churned, but nobody measured it: churn is not read as 0%
    assert not db.val(cur, "select count(*) from findings where run = %s and churn_n > 0", run)


def test_a_file_exported_from_salesforce_keeps_its_traits_and_its_origin(cur):
    rep = _import(cur, _csv("s-1,sfcsv.example,SfCsv,2026-01-10,Closed won,true,true,500,New Business,us,Inbound,,Software,90,,"), system="salesforce")
    assert rep["inserted"] == 1
    assert db.val(cur, "select origin from companies where primary_domain = 'sfcsv.example'") == "deals_import"
    d = db.one(cur, "select snapshot, snapshot_source, source_system from deals where external_id = 's-1'")
    assert (d["snapshot_source"], d["source_system"], d["snapshot"]["employees"]) == ("csv_row", "salesforce", 90)


def test_a_country_written_out_only_matters_for_a_company_the_desk_does_not_hold(cur):
    dom = db.val(cur, "select primary_domain from companies limit 1")
    rep = _import(cur, _csv(f"k-1,{dom},Held,2026-01-10,Open,false,false,10,New Business,USA,,,,,,"))
    assert rep["inserted"] == 1 and not rep["rejected"]
    rep = _import(cur, _csv("k-2,brandnew.example,Brand New,2026-01-10,Open,false,false,10,New Business,USA,,,,,,"))
    assert rep["rejected"] and "country" in rep["rejected"][0]["reason"]


def test_the_import_command_is_refused_when_crm_desk_is_present_or_on_the_public_demo(tmp_path, monkeypatch):
    f = tmp_path / "d.csv"
    f.write_text(_csv("z-1,z.example,Z,2026-01-10,Open,false,false,1,New Business,US,,,,,,"))
    monkeypatch.setattr(deals_in, "__name__", deals_in.__name__)
    from market import config
    monkeypatch.setattr(config, "CONFIG", Config(integrated_with=frozenset({"crm_desk"})))
    with pytest.raises(SystemExit, match="crm_desk"):
        deals_in.import_file(str(f))
    monkeypatch.setattr(config, "CONFIG", Config(public_demo=True))
    with pytest.raises(SystemExit, match="public demo"):
        deals_in.import_file(str(f))


def test_a_dry_run_writes_nothing(tmp_path, demo):
    f = tmp_path / "d.csv"
    f.write_text(_csv("dry-1,dry.example,Dry,2026-01-10,Open,false,false,100,New Business,US,,,,,,"))
    rep = deals_in.import_file(str(f))
    assert rep["inserted"] == 1 and rep["committed"] is False
    assert not db.read1("select 1 from deals where external_id = 'dry-1'")
    assert not db.read1("select 1 from deal_imports")


# ---------------------------------------------------------------- the CRM read side (Salesforce's nouns)

class StubReader:
    """Implements only the two read methods of `deals_in.CrmReader`: the whole pull must run on it."""

    def __init__(self, accounts, opps):
        self.accounts, self.opps = accounts, opps

    def _page(self, rows, since, limit):
        start = int(since or 0)
        part = rows[start:start + limit]
        return deals_in.Page(part, str(start + len(part)), start + len(part) < len(rows))

    def accounts_changed(self, since, limit):
        return self._page(self.accounts, since, limit)

    def opportunities_changed(self, since, limit):
        return self._page(self.opps, since, limit)


def _opp(i, stage="Closed won", closed=True, won=True, created=None, **kw):
    created = created or datetime(2026, 1, 5, tzinfo=timezone.utc)
    return deals_in.CrmOpportunity(id=f"sf:{i}", account_domain="sfco.example", account_name="SF Co", stage_name=stage, amount_cents=900_000,
                                   created_at=created, is_closed=closed, is_won=won,
                                   close_date=created + timedelta(days=60) if closed else None, type="new business", **kw)


def test_a_stub_with_only_the_read_methods_runs_the_whole_pull(cur):
    reader = StubReader([deals_in.CrmAccount(id="a1", domain="sfco.example", name="SF Co", country="US")], [_opp(1), _opp(2, "Negotiation", False, False)])
    out = deals_in.pull(reader, limit=1, cur=cur)
    assert out["accounts"] == 1 and out["opportunities"] == 2 and out["inserted"] == 2
    assert db.val(cur, "select origin from companies where primary_domain = 'sfco.example'") == "crm"
    assert db.val(cur, "select count(*) from deals where source_system = 'crmdesk'") >= 2
    assert db.val(cur, "select since from crm_cursors where feed = 'opportunities'") == "2"
    # the same opportunity again, now closed lost: updated in place, never a second deal
    reader.opps[1] = _opp(2, "Closed lost", True, False, loss_reason="too expensive")
    reader.opps = reader.opps[1:]
    db.run(cur, "update crm_cursors set since = null where feed = 'opportunities'")
    out = deals_in.pull(reader, cur=cur)
    assert (out["inserted"], out["updated"]) == (0, 1)
    assert db.val(cur, "select count(*) from deals where external_id = 'sf:2'") == 1
    assert db.val(cur, "select loss_code from deals where external_id = 'sf:2'") == "price"


def test_a_crm_deal_snapshot_is_the_crm_snapshot_or_the_backfill_never_todays_company(cur):
    deals_in.pull(StubReader([deals_in.CrmAccount(id="a", domain="sn.example", name="Sn", country="US")],
                             [deals_in.CrmOpportunity(id="sf:s1", account_domain="sn.example", account_name="Sn", stage_name="Closed won",
                                                      amount_cents=1, created_at=datetime(2025, 1, 1, tzinfo=timezone.utc), is_closed=True, is_won=True,
                                                      close_date=datetime(2025, 3, 1, tzinfo=timezone.utc), type="new business",
                                                      account_snapshot={"employees": 80, "industry": "Software", "junk": 1}),
                              deals_in.CrmOpportunity(id="sf:s2", account_domain="sn.example", account_name="Sn", stage_name="Closed won",
                                                      amount_cents=1, created_at=datetime(2025, 2, 1, tzinfo=timezone.utc), is_closed=True, is_won=True,
                                                      close_date=datetime(2025, 3, 1, tzinfo=timezone.utc), type="new business")]), cur=cur)
    a = db.one(cur, "select snapshot, snapshot_source from deals where external_id = 'sf:s1'")
    b = db.one(cur, "select snapshot, snapshot_source from deals where external_id = 'sf:s2'")
    assert a["snapshot_source"] == "crm_snapshot" and a["snapshot"]["employees"] == 80 and "junk" not in a["snapshot"]
    assert b["snapshot_source"] == "crm_backfill" and "employees" not in b["snapshot"]


def test_the_crm_desk_reader_maps_its_feeds_into_salesforce_nouns_and_leaves_people_behind():
    feed = {"data": [{"id": 7, "account_domain": "cd.example", "account_name": "CD", "stage": "Closed won", "is_closed": True, "is_won": True,
                      "amount_cents": 500, "created_at": "2026-01-01T00:00:00Z", "closed_at": "2026-02-01T00:00:00Z", "type": "new_business",
                      "lead_source": "Inbound", "owner": {"email": "tom@lumenledger.example"}, "contact_email": "someone@cd.example",
                      "contact_roles": [{"x": 1}], "account_snapshot": {"country": "US", "employees": 50}},
                     {"id": 8, "deleted": True, "account_domain": "cd.example"}], "next": "n1", "has_more": False}
    seen = {}

    def handler(req: httpx.Request):
        seen["path"], seen["auth"] = req.url.path, req.headers["authorization"]
        return httpx.Response(200, json=feed)
    reader = crm.CrmDeskReader("http://crm.test", "rd_k", client=httpx.Client(base_url="http://crm.test", transport=httpx.MockTransport(handler),
                                                                              headers={"authorization": "Bearer rd_k"}))
    page = reader.opportunities_changed(None, 10)
    assert seen["path"] == "/api/v1/changes/opportunities" and page.next == "n1" and not page.has_more
    (o,) = page.rows
    assert (o.id, o.type, o.owner_email, o.country) == ("crmdesk:7", "new business", "tom@lumenledger.example", "US")
    assert not any("someone@" in str(v) for v in vars(o).values())


def test_a_page_of_only_tombstones_still_moves_the_cursor(cur):
    class Tombs(StubReader):
        def opportunities_changed(self, since, limit):
            return deals_in.Page([], "7" if since is None else "9", since is None)   # everything on page 1 was deleted
    out = deals_in.pull(Tombs([], []), cur=cur)
    assert out["opportunities"] == 0
    assert db.val(cur, "select since from crm_cursors where feed = 'opportunities'") == "9"


def test_a_poison_crm_row_is_rejected_and_the_rest_of_the_page_lands(cur):
    good = _opp(31)
    upper = _opp(32)
    upper.account_domain = "SFCO.Example"                      # normalised, not a failed page
    no_close = _opp(33)
    no_close.close_date = None                                 # closed with no close date
    eur = _opp(34, currency="EUR")
    no_amount = _opp(35)
    no_amount.amount_cents = None
    no_type = _opp(36)
    no_type.type = None                                        # a blank type is not guessed
    out = deals_in.pull(StubReader([deals_in.CrmAccount(id="a", domain="sfco.example", name="SF Co", country="US")],
                                   [good, upper, no_close, eur, no_amount, no_type]), cur=cur)
    assert (out["inserted"], out["rejected"]) == (2, 4)
    assert db.val(cur, "select count(*) from deals where external_id in ('sf:31', 'sf:32')") == 2
    assert db.val(cur, "select report->'rejected'->0->>'reason' from deal_imports order by id desc limit 1")


def test_the_pull_job_survives_an_outage_and_keeps_its_schedule(cur, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.setenv("CRM_PULL", "1")

    def down(*a, **k):
        raise crm.CrmDown("CRM Desk did not answer", 45)
    monkeypatch.setattr(crm.CrmDeskReader, "from_env", classmethod(lambda cls: object()))
    monkeypatch.setattr(deals_in, "pull", down)
    crm._pull(cur, {})
    assert db.val(cur, "select count(*) from jobs where kind = 'crm_pull' and status = 'queued'") == 1


def test_a_crm_that_is_down_during_a_pull_raises_and_keeps_its_cursor(cur):
    class Down(StubReader):
        def opportunities_changed(self, since, limit):
            raise crm.CrmDown("CRM Desk did not answer")
    with pytest.raises(crm.CrmDown):
        deals_in.pull(Down([], []), cur=cur)


def test_pulling_is_a_second_switch_after_crm_equals_crmdesk(monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.delenv("CRM_PULL", raising=False)
    assert crm.enabled() and not crm.pull_enabled()
    monkeypatch.setenv("CRM_PULL", "1")
    assert crm.pull_enabled()
    monkeypatch.delenv("CRM")
    assert not crm.pull_enabled()


# ---------------------------------------------------------------- publishing sends the profile version

def _publish(cur, who, *, now=True):
    draft = db.one(cur, "select * from icp_versions where status = 'draft' order by number limit 1")
    by = who["Elena"] if draft["author"] != who["Elena"]["id"] else who["Sam"]
    profiles.publish(cur, draft["id"], by, rescore_now=now)
    return draft["id"]


def test_publishing_queues_the_new_version_to_the_crm_without_owners(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    vid = _publish(cur, who)
    rows = db.all(cur, "select * from crm_outbox where kind = 'scores' and status = 'queued'")
    assert rows and all(r["icp_version"] == vid for r in rows)
    items = [i for r in rows for i in r["payload"]["items"]]
    number = db.val(cur, "select number from icp_versions where id = %s", vid)
    assert items and all(i["icp_version"] == f"v{number}" and i["tier"] for i in items)
    assert not any(k in i for i in items for k in ("owner_id", "sdr_owner_id", "industry", "employees"))   # pins and people are untouched
    assert all(len(r["payload"]["items"]) <= crm.CHUNK for r in rows)


def test_publishing_with_no_crm_or_no_active_plan_sends_nothing(cur, who, monkeypatch):
    monkeypatch.delenv("CRM", raising=False)
    _publish(cur, who)
    assert not db.val(cur, "select count(*) from crm_outbox where kind = 'scores'")


def test_a_newer_version_supersedes_scores_still_waiting(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    first = _publish(cur, who)
    n = db.val(cur, "select count(*) from crm_outbox where kind = 'scores' and status = 'queued' and icp_version = %s", first)
    assert n
    v = profiles.published(cur)
    nid = profiles.create_draft(cur, author=who["Sam"]["id"], rules=v["rules"], note="next")
    profiles.publish(cur, nid, who["Elena"], rescore_now=True)
    assert not db.val(cur, "select count(*) from crm_outbox where kind = 'scores' and status = 'queued' and icp_version = %s", first)
    assert db.val(cur, "select count(*) from crm_outbox where kind = 'scores' and status = 'cancelled' and icp_version = %s", first) == n
    assert db.val(cur, "select count(*) from crm_outbox where kind = 'scores' and status = 'queued' and icp_version = %s", nid)


def test_a_profile_rollback_sends_the_restored_version(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    _publish(cur, who)
    db.run(cur, "delete from crm_outbox")
    restored = profiles.rollback(cur, who["Elena"], "Because")
    assert db.val(cur, "select count(*) from crm_outbox where kind = 'scores' and icp_version = %s", restored)


def test_the_deferred_publish_waits_for_the_rescore_then_queues(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    vid = _publish(cur, who, now=False)
    assert db.val(cur, "select count(*) from jobs where kind = 'crm_scores' and status = 'queued'")
    assert not db.val(cur, "select count(*) from crm_outbox where kind = 'scores'")      # no tiers exist yet, so nothing is sent
    crm._scores_after_rescore(cur, {"version": vid})                                      # the rescore jobs are still queued: it waits
    assert not db.val(cur, "select count(*) from crm_outbox where kind = 'scores'")
    db.run(cur, "delete from jobs where kind in ('rescore_version', 'rescore_batch')")
    from market.fit import score_version
    score_version(cur, vid)
    crm._scores_after_rescore(cur, {"version": vid})
    assert db.val(cur, "select count(*) from crm_outbox where kind = 'scores' and icp_version = %s", vid)


def test_a_scores_answer_does_not_hide_a_books_refusal_and_handoffs_shows_the_version(cur, who, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    items = [{"world_id": "co_x", "domain": "pin.example", "sdr_owner_id": "maya.okafor@lumenledger.example"}]
    db.run(cur, "insert into crm_outbox (kind, payload, status, answer, sent_at) values ('books', %s, 'sent', %s, app_now())", J({"items": items}),
           J({"results": [{"index": 0, "id": "a", "refused": [{"field": "sdr_owner_id", "reason": "owner_pinned"}]}]}))
    vid = _publish(cur, who)
    n = db.val(cur, "select number from icp_versions where id = %s", vid)
    db.run(cur, "insert into crm_outbox (kind, payload, status, answer, sent_at, icp_version) values ('scores', %s, 'sent', %s, app_now() + interval '1 minute', %s)",
           J({"items": [{"world_id": "co_x", "domain": "pin.example", "tier": "A", "icp_version": f"v{n}"}]}), J({"results": [{"index": 0, "id": "a", "refused": []}]}), vid)
    assert [r["field"] for r in crm.refusals(cur) if r["domain"] == "pin.example"] == ["sdr_owner_id"]
    st = crm.summary(cur)["icp"]
    assert st["published"] == n and st["accounts_on_published"] >= 1 and st["waiting"] > 0


def test_every_send_carries_an_idempotency_key(cur, monkeypatch):
    monkeypatch.setenv("CRM", "crmdesk")
    keys = []
    monkeypatch.setattr(crm, "_send", lambda body, key=None: (keys.append(key), (200, {"results": []}))[1])
    db.run(cur, "insert into crm_outbox (kind, payload) values ('scores', %s) returning id", J({"items": []}))
    row = db.one(cur, "select * from crm_outbox order by id desc limit 1")
    crm.deliver(cur, row)
    assert keys == [f"market-desk:outbox:{row['id']}"]


def test_replay_keeps_each_rows_kind_and_ignores_reads(cur, tmp_path):
    j = tmp_path / "j.jsonl"
    at = "2026-11-12T10:00:00+00:00"
    j.write_text("\n".join(json.dumps(x) for x in [
        {"at": at, "actor": "market_desk", "method": "POST", "path": "/accounts/batch", "body": {"items": []}, "status": 200, "answer": {"results": []}},
        {"at": at, "actor": "market_desk", "method": "POST", "path": "/accounts/batch", "kind": "scores", "body": {"items": []}, "status": 200, "answer": {"results": []}},
        {"at": at, "actor": "market_desk", "method": "GET", "path": "/changes/opportunities", "count": 1},
        {"at": at, "actor": "crm_desk", "method": "POST", "path": "/x", "body": {}, "status": 200, "answer": {}}]) + "\n")
    before = db.val(cur, "select count(*) from crm_outbox")
    assert crm.replay(cur, j) == 2
    assert db.val(cur, "select count(*) from crm_outbox where kind = 'scores'") == 1
    assert db.val(cur, "select count(*) from crm_outbox") == before + 2


# ---------------------------------------------------------------- configuration

def test_the_configuration_picks_exactly_one_crm(monkeypatch):
    for ok in ("", "crmdesk", "default"):
        monkeypatch.setenv("CRM", ok)
        Config().validate()
    monkeypatch.setenv("CRM", "salesforce")
    with pytest.raises(SystemExit, match="adapter"):
        Config().validate()


def test_integrated_with_names_known_desks_only_and_unset_means_alone(monkeypatch):
    monkeypatch.delenv("INTEGRATED_WITH", raising=False)
    assert Config().integrated_with == frozenset()
    monkeypatch.setenv("INTEGRATED_WITH", "crm_desk, Account_Desk")
    assert Config().integrated_with == {"crm_desk", "account_desk"}
    monkeypatch.setenv("INTEGRATED_WITH", "crm_desk,nope")
    with pytest.raises(SystemExit, match="nope"):
        Config().validate()
