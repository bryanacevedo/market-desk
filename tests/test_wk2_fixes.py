"""Integrated week 2 fixes (decisions 73 to 78): an approved move while a plan is scheduled, capacity on moves, the company
totals, who CRM Desk holds as owner, the book file's columns, asking a manager to approve, the source owner, what changed since
the version before, when things reached CRM Desk, and the trace links and delivery order of the CRM outbox."""
from __future__ import annotations

import csv
import io
from datetime import timedelta

import pytest

from market import crm, db, handoff, jobs, moves, notices, telemetry, territories
from market.api import views


@pytest.fixture
def who(cur):
    return {u["name"].split()[0]: u for u in db.all(cur, "select * from users")}


def _revops(cur):
    return db.one(cur, "select * from users where role = 'revops' and active order by id limit 1")


def _active(cur):
    return db.one(cur, "select * from territory_plans where status = 'active'")


def _today(cur):
    return db.val(cur, "select app_now()::date")


def _accounts(cur, n=3, skip=(), owner_not=None):
    """n prospects of one AE in the plan in effect, by rule, with no open deal, and an AE to give them to."""
    a = _active(cur)
    owner = db.val(cur, """select owner from assignments a join users u on u.id = a.owner where a.plan = %s and u.role = 'ae'
                           and (%s::int is null or a.owner <> %s) group by owner order by count(*) desc limit 1""", a["id"], owner_not, owner_not)
    ids = [r["company"] for r in db.all(cur, """select a.company from assignments a join companies c on c.id = a.company
                where a.plan = %s and a.owner = %s and not c.sole_trader and a.reason_code = 'rule' and not (a.company = any(%s))
                and not exists (select 1 from deals d where d.company = a.company and d.outcome = 'open') order by a.company limit %s""",
                                       a["id"], owner, list(skip), n)]
    other = db.val(cur, "select id from users where role = 'ae' and active and id <> %s order by id limit 1", owner)
    return ids, owner, other


def _schedule_a_plan(cur, who, days=30):
    """A plan for three accounts, approved and scheduled `days` ahead, so another approval meets a scheduled plan."""
    ids, owner, other = _accounts(cur)
    day = _today(cur) + timedelta(days=days)
    plan = moves.approve(cur, moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason="A new hire", effective_on=day), who["Elena"])
    territories.activate(cur, plan, who["Elena"])
    return plan, ids, day


def _propose_while_scheduled(cur, who, sched_ids, days):
    ids, owner, other = _accounts(cur, skip=sched_ids)
    day = _today(cur) + timedelta(days=days)
    pid = moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason="Cover the region", effective_on=day)
    return pid, ids, owner, other, day


def _owner(cur, plan, company):
    return db.val(cur, "select owner from assignments where plan = %s and company = %s", plan, company)


# ---- B4: an approved move takes effect on its date while a plan is scheduled

def test_an_approval_while_a_plan_is_scheduled_keeps_the_moves_for_their_date_and_carries_them(cur, who):
    sched, sched_ids, sched_day = _schedule_a_plan(cur, who, 30)
    pid, ids, owner, other, day = _propose_while_scheduled(cur, who, sched_ids, 10)
    active = _active(cur)["id"]
    assert moves.approve(cur, pid, who["Elena"]) is None                       # no draft plan that cannot be activated
    assert db.val(cur, "select plan from move_proposals where id = %s", pid) is None
    assert db.val(cur, "select count(*) from scheduled_moves where proposal = %s and status = 'pending'", pid) == 3
    assert all(_owner(cur, active, c) == owner for c in ids)                   # nothing moves before its date
    assert all(_owner(cur, sched, c) == other for c in ids)                    # the scheduled plan carries them: they survive its start
    row = next(r for r in moves.listing(cur) if r["id"] == pid)
    assert row["force_note"] == f"Approved, not in force: the accounts move on {day:%-d %b %Y}."
    assert row["moves"]["waiting"] == 3 and moves.detail(cur, pid, who["Elena"])["force_note"] == row["force_note"]
    coming = views.company(cur, ids[0], who["Elena"])["coming"]
    assert [c["from"] for c in coming] == [day] and coming[0]["role"] == "owner"
    # The date comes.
    db.run(cur, "update scheduled_moves set effective_on = app_now()::date where proposal = %s", pid)
    n0 = db.val(cur, "select count(*) from audit_log where action = 'owner_moved'")
    assert moves.apply_due(cur) == 3
    assert all(_owner(cur, active, c) == other for c in ids)
    assert db.val(cur, "select count(*) from audit_log where action = 'owner_moved'") == n0 + 3
    assert db.val(cur, "select count(*) from scheduled_moves where proposal = %s and status = 'applied'", pid) == 3
    assert next(r for r in moves.listing(cur) if r["id"] == pid)["force_note"] is None
    assert views.company(cur, ids[0], who["Elena"])["coming"] == []
    assert moves.apply_due(cur) == 0
    # Then the scheduled plan starts: the accounts are still with the person the proposal named.
    db.run(cur, "update territory_plans set effective_on = app_now()::date where id = %s", sched)
    assert territories.apply_scheduled(cur) == 1
    assert all(_owner(cur, sched, c) == other for c in ids)


def test_a_move_dated_after_the_scheduled_plan_starts_is_not_carried_into_it(cur, who):
    sched, sched_ids, sched_day = _schedule_a_plan(cur, who, 30)
    pid, ids, owner, other, day = _propose_while_scheduled(cur, who, sched_ids, 40)
    assert moves.approve(cur, pid, who["Elena"]) is None
    assert all(_owner(cur, sched, c) == owner for c in ids)                    # it would have moved them 10 days early
    db.run(cur, "update territory_plans set effective_on = app_now()::date where id = %s", sched)
    assert territories.apply_scheduled(cur) == 1                               # the scheduled plan starts first
    assert all(_owner(cur, sched, c) == owner for c in ids)
    db.run(cur, "update scheduled_moves set effective_on = app_now()::date where proposal = %s", pid)
    assert moves.apply_due(cur) == 3                                           # then the move applies to the plan now in effect
    assert all(_owner(cur, sched, c) == other for c in ids)


def test_a_move_dated_today_applies_at_once_while_a_plan_is_scheduled(cur, who):
    sched, sched_ids, _ = _schedule_a_plan(cur, who, 30)
    pid, ids, owner, other, _day = _propose_while_scheduled(cur, who, sched_ids, 0)
    active = _active(cur)["id"]
    assert moves.approve(cur, pid, who["Elena"]) is None
    assert all(_owner(cur, active, c) == other for c in ids) and all(_owner(cur, sched, c) == other for c in ids)
    row = next(r for r in moves.listing(cur) if r["id"] == pid)
    assert row["force_note"] is None and row["moves"] == {"moved": 3, "waiting": 0, "kept": 0, "on": None, "tracked": True}


def test_a_hand_change_after_the_approval_is_not_undone_on_the_date(cur, who):
    sched, sched_ids, _ = _schedule_a_plan(cur, who, 30)
    pid, ids, owner, other, _day = _propose_while_scheduled(cur, who, sched_ids, 10)
    moves.approve(cur, pid, who["Elena"])
    third = db.val(cur, "select id from users where role = 'ae' and active and id not in (%s, %s) order by id limit 1", owner, other)
    territories.change_owner_by_hand(cur, ids[0], third, "Keeps the relationship", _revops(cur))
    db.run(cur, "update scheduled_moves set effective_on = app_now()::date where proposal = %s", pid)
    assert moves.apply_due(cur) == 2
    assert _owner(cur, _active(cur)["id"], ids[0]) == third
    st = moves.move_state(cur, pid)
    assert (st["moved"], st["kept"], st["waiting"]) == (2, 1, 0)


def test_an_account_with_a_waiting_move_cannot_be_proposed_again(cur, who):
    sched, sched_ids, _ = _schedule_a_plan(cur, who, 30)
    pid, ids, owner, other, day = _propose_while_scheduled(cur, who, sched_ids, 10)
    moves.approve(cur, pid, who["Elena"])
    third = db.val(cur, "select id from users where role = 'ae' and active and id not in (%s, %s) order by id limit 1", owner, other)
    with pytest.raises(ValueError, match="waiting for its date"):
        moves.propose(cur, who["Sam"], companies=ids[:1], to_owner=third, reason="Again", effective_on=day)


def test_with_no_plan_scheduled_an_approval_still_drafts_a_plan(cur, who):
    ids, owner, other = _accounts(cur)
    pid = moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason="A new hire", effective_on=_today(cur) + timedelta(days=5))
    plan = moves.approve(cur, pid, who["Elena"])
    assert plan and db.val(cur, "select status from territory_plans where id = %s", plan) == "draft"
    assert db.val(cur, "select count(*) from scheduled_moves where proposal = %s", pid) == 0


def test_a_move_that_applies_goes_to_crm_desk_and_the_screen_says_when(cur, who, monkeypatch):
    sched, sched_ids, _ = _schedule_a_plan(cur, who, 30)
    pid, ids, owner, other, _day = _propose_while_scheduled(cur, who, sched_ids, 0)
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.setattr(crm, "features", lambda: [])
    assert moves.delivery(cur, pid) == {"sent": 0, "waiting": 0, "failed": 0, "sent_at": None, "error": None, "any": False}
    moves.approve(cur, pid, who["Elena"])
    d = moves.delivery(cur, pid)
    assert d["waiting"] == 1 and d["sent"] == 0 and d["any"]
    row = db.one(cur, "select * from crm_outbox where ref = %s", f"move:{pid}")
    assert row["kind"] == "books" and len(row["payload"]["items"]) == 3
    assert {i["owner_id"] for i in row["payload"]["items"]} == {db.val(cur, "select email from users where id = %s", other)}
    db.run(cur, "update crm_outbox set status = 'sent', sent_at = app_now() where id = %s", row["id"])
    d = moves.delivery(cur, pid)
    assert d["sent"] == 1 and d["waiting"] == 0 and d["sent_at"]
    assert views.crm_desk(cur)["deliveries"][0]["what"].startswith("Move of 3 to ")
    monkeypatch.setenv("CRM", "")
    assert moves.delivery(cur, pid) is None


def test_a_future_move_tells_a_crm_that_can_hold_a_date(cur, who, monkeypatch):
    sched, sched_ids, _ = _schedule_a_plan(cur, who, 30)
    pid, ids, owner, other, day = _propose_while_scheduled(cur, who, sched_ids, 10)
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.setattr(crm, "features", lambda: ["scheduled_owner"])
    moves.approve(cur, pid, who["Elena"])
    items = db.one(cur, "select payload from crm_outbox where ref = %s", f"move:{pid}")["payload"]["items"]
    assert len(items) == 3 and {i["owner_effective_on"] for i in items} == {str(day)}


# ---- J2, QUESTIONS 7: the hours after a move, a warning over 100%, never a block

def test_the_hours_a_person_would_hold_after_a_move_are_shown_and_never_block(cur, who):
    ids, owner, other = _accounts(cur, n=5)
    plan = _active(cur)
    cap = moves.capacity_after(cur, other, ids)
    hours = territories.settings(cur)["hours_per_tier"]
    tiers = db.all(cur, "select f.tier from account_fit f where f.icp_version = %s and f.company = any(%s)", plan["based_on"], ids)
    now = db.one(cur, "select hours_required, hours_available from capacity_snapshots where plan = %s and user_id = %s", plan["id"], other)
    assert cap["person"] == db.val(cur, "select name from users where id = %s", other)
    assert cap["hours_now"] == round(float(now["hours_required"]), 1)
    assert cap["hours_after"] == round(float(now["hours_required"]) + sum(float(hours.get(t["tier"], 0)) for t in tiers), 1)
    assert cap["hours_available"] == round(float(now["hours_available"]), 1)
    # Accounts the person already holds add nothing.
    held = db.val(cur, "select company from assignments where plan = %s and owner = %s limit 1", plan["id"], other)
    assert moves.capacity_after(cur, other, [held])["hours_after"] == cap["hours_now"]
    # Over 100%: it says so, and the proposal is still made.
    db.run(cur, "update capacity_snapshots set hours_available = hours_required where plan = %s and user_id = %s", plan["id"], other)
    over = moves.capacity_after(cur, other, ids)
    assert over["over"] and over["hours_after"] > over["hours_available"]
    pid = moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason="Cover the region", effective_on=_today(cur) + timedelta(days=3))
    assert pid
    code = next(t["key"] for t in db.all(cur, "select key from territories where plan = %s order by id", plan["id"]))
    m = moves.rule_matches(cur, code, other)
    assert m["capacity"]["person"] == cap["person"] and "ids" in m


# ---- J6: one count of companies

def test_the_dashboard_counts_the_companies_the_accounts_list_counts(cur, who):
    from market import sizing
    sizing.run(cur)
    market = views.market(cur, "segment", True)["figures"]["companies"]
    listed = views.accounts(cur, who["Elena"], q="", tier="", segment="", owner="", page=1)["total"]
    assert market == listed
    # A sole trader is a person, not a company: neither screen counts one.
    assert db.val(cur, "select count(*) from companies where sole_trader") > 0


# ---- J28: who CRM Desk holds as owner, and who set it

def test_the_account_says_when_crm_desk_holds_a_different_owner(cur, who):
    ids, owner, other = _accounts(cur, n=1)
    mine = db.val(cur, "select email from users where id = %s", owner)
    assert views.company(cur, ids[0], who["Elena"])["crm_differs"] == []
    theirs = db.one(cur, "select name, email from users where id = %s", other)
    db.run(cur, """insert into crm_owner_reads (company, ae_email, ae_set_by, sdr_email, sdr_set_by) values (%s,%s,%s,null,null)""",
           ids[0], theirs["email"].upper(), "Account Desk")
    d = views.company(cur, ids[0], who["Elena"])["crm_differs"]
    assert len(d) == 1 and d[0]["seat"] == "AE" and d[0]["crm"] == theirs["name"] and d[0]["set_by"] == "Account Desk"
    assert d[0]["here"] == db.val(cur, "select name from users where id = %s", owner)
    db.run(cur, "update crm_owner_reads set ae_email = %s where company = %s", mine, ids[0])
    assert views.company(cur, ids[0], who["Elena"])["crm_differs"] == []


def test_the_crm_read_keeps_who_set_each_owner(cur):
    from market import deals_in
    c = db.one(cur, "select id, primary_domain from companies where not sole_trader order by id limit 1")
    acct = deals_in.CrmAccount(id="a1", domain=c["primary_domain"], name="X", country=None, owner_email="Tom@Example.com", sdr_owner_email=None,
                               owner_set_by="Account Desk", sdr_owner_set_by=None)
    page = deals_in.Page([acct], None, False)

    class Reader:
        def accounts_changed(self, since, limit):
            return page

        def opportunities_changed(self, since, limit):
            return deals_in.Page([], None, False)
    deals_in.pull(Reader(), cur=cur)
    r = db.one(cur, "select * from crm_owner_reads where company = %s", c["id"])
    assert (r["ae_email"], r["ae_set_by"], r["sdr_email"]) == ("tom@example.com", "Account Desk", None)


# ---- J3: the book file says who works each account as SDR and as AE, its tier and the profile version

def test_the_book_file_has_sdr_and_ae_columns_tier_and_version(cur):
    from market import catalog as C
    rv = _revops(cur)
    bid = handoff.build_book(cur, "account_desk", rv)
    raw = bytes(db.val(cur, "select bytes from target_book_files where book = %s and path = 'accounts.csv'", bid)).decode()
    rows = list(csv.DictReader(io.StringIO(raw)))
    assert list(rows[0]) == C.AD_COLUMNS + C.BOOK_EXTRA_COLUMNS
    number = db.val(cur, "select number from icp_versions where status = 'published'")
    assert {r["profile_version"] for r in rows} == {f"v{number}"} and {r["tier"] for r in rows} <= {"A", "B"}
    sdr = [r for r in rows if r["sdr_email"]]
    ae = [r for r in rows if r["ae_email"] and not r["sdr_email"]]
    assert sdr and ae
    assert all(r["sdr_email"] == r["owner_email"] for r in sdr) and all(r["ae_email"] == r["owner_email"] for r in ae)
    paired = {r["ae_email"] for r in sdr}
    assert "" not in paired or len(paired) > 1


# ---- J4: ask a manager to approve, with a reason

def test_asking_for_approval_lands_in_a_managers_waiting_on_you_with_the_reason(cur, who):
    rv = _revops(cur)
    nid = notices.asked(cur, rv, subject="profile version 4", reason="The Q1 plan depends on it", path="/profile")
    mine = notices.unseen(cur, who["Elena"])
    assert any(n["notice"] == nid and n["what"] == f"{rv['name']} asks you to approve profile version 4: The Q1 plan depends on it" for n in mine)
    assert not any(n["notice"] == nid for n in notices.unseen(cur, rv))                   # never the asker
    other_revops = {**rv, "id": -1}
    assert not any(n["notice"] == nid for n in notices.unseen(cur, other_revops))         # only managers are asked
    with pytest.raises(ValueError, match="why"):
        notices.asked(cur, rv, subject="x", reason=" ", path="/profile")
    notices.see(cur, nid, who["Elena"])
    assert not any(n["notice"] == nid for n in notices.unseen(cur, who["Elena"]))


def test_the_ask_endpoint_takes_a_draft_and_only_a_draft(demo):
    from fastapi.testclient import TestClient

    from market.api.app import app
    with db.tx() as cur:
        rv = _revops(cur)
        published = db.val(cur, "select id from icp_versions where status = 'published'")
    with TestClient(app) as client:
        r = client.post("/api/approval-asks", json={"kind": "icp", "id": published, "reason": "Needed for Q1"},
                        headers={"X-Acting-As": str(rv["id"])})
        assert r.status_code == 422 and r.json()["detail"] == "Only a draft waits for approval."


# ---- J5: who looks after a source; Run now only where a run exists

def test_a_source_names_its_owner_and_only_the_crm_read_can_run_now(cur, monkeypatch):
    rv = _revops(cur)
    s = views.source(cur, "technographics", True)
    assert s["owner"] and rv["name"] in s["owner"] and s["can_run"] is False
    assert all(r["owner"] == s["owner"] for r in views.sources(cur, True)["rows"])
    monkeypatch.setenv("CRM", "crmdesk")
    monkeypatch.setenv("CRM_PULL", "1")
    assert views.source(cur, "crm", True)["can_run"] is True and views.source(cur, "technographics", True)["can_run"] is False
    db.run(cur, "delete from jobs where kind = 'crm_pull'")
    assert crm.run_pull_now(cur) is True
    assert db.val(cur, "select count(*) from jobs where kind = 'crm_pull' and status = 'queued'") == 1
    db.run(cur, "update jobs set run_at = app_now() + interval '1 hour' where kind = 'crm_pull'")
    assert crm.run_pull_now(cur) is True
    assert db.val(cur, "select count(*) from jobs where kind = 'crm_pull' and run_at <= app_now()") == 1
    monkeypatch.setenv("CRM_PULL", "")
    assert crm.run_pull_now(cur) is False


# ---- J1: what changed since the version and the plan before

def test_accounts_can_be_listed_by_what_changed_since_the_version_before(cur, who):
    pub = db.one(cur, "select id, number from icp_versions where status = 'published'")
    prev = db.one(cur, "select id, number from icp_versions where number < %s and status <> 'draft' order by number desc limit 1", pub["number"])
    db.run(cur, "update icp_versions set replaced = %s where id = %s", prev["id"], pub["id"])
    page = views.accounts(cur, who["Elena"], q="", tier="", segment="", owner="", page=1, changed="tier")
    expect = db.val(cur, """select count(*) from companies c join account_fit f on f.company = c.id and f.icp_version = %s
                            join account_fit p on p.company = c.id and p.icp_version = %s
                            where c.lifecycle <> 'competitor' and not c.sole_trader and f.judged and p.judged and p.tier <> f.tier""",
                    pub["id"], prev["id"])
    assert page["total"] == expect == page["since"]["tier"] and page["since"]["version"] == prev["number"]
    assert all(r["was_tier"] and r["was_tier"] != r["tier"] for r in page["rows"])


def test_a_plan_lists_the_accounts_it_gives_to_someone_else(cur, who):
    ids, owner, other = _accounts(cur)
    pid = moves.propose(cur, who["Sam"], companies=ids, to_owner=other, reason="A new hire", effective_on=_today(cur) + timedelta(days=5))
    plan = moves.approve(cur, pid, who["Elena"])
    out = views.territories(cur, plan, True)["owner_changes"]
    assert out["total"] == 3 and {r["id"] for r in out["rows"]} == set(ids)
    assert {r["to_owner"] for r in out["rows"]} == {db.val(cur, "select name from users where id = %s", other)}
    assert out["against"] == db.val(cur, "select name from territory_plans where status = 'active'")


# ---- QUESTIONS 2, M44: the CRM outbox keeps the request's trace, and a delivery links to every request it sends

@pytest.fixture
def tracing(monkeypatch):
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider)
    monkeypatch.setattr(telemetry, "_on", True)
    yield provider, exporter


def _no_waiting_rows(cur):
    db.run(cur, "update crm_outbox set status = 'cancelled' where status = 'queued'")


def test_tracing_off_leaves_the_outbox_trace_null_and_delivers_as_before(cur, monkeypatch):
    _no_waiting_rows(cur)
    rid = crm.queue_row(cur, "books", {"items": []}, ref="plan:1")
    assert db.val(cur, "select trace_parent from crm_outbox where id = %s", rid) is None
    sent = []
    monkeypatch.setattr(crm, "deliver", lambda c, row: sent.append(row["id"]) or {})
    crm._deliver_one(cur, {})
    assert sent == [rid]


def test_each_delivery_is_a_span_linked_to_the_request_that_queued_its_row(cur, tracing, monkeypatch):
    from opentelemetry import trace
    provider, exporter = tracing
    _no_waiting_rows(cur)
    ids, ctxs = [], []
    for name in ("POST /api/a", "POST /api/b"):
        with provider.get_tracer("test").start_as_current_span(name) as request:
            ids.append(crm.queue_row(cur, "books", {"items": []}, ref="plan:1"))
            ctxs.append(request.get_span_context())
    stored = [db.val(cur, "select trace_parent from crm_outbox where id = %s", i) for i in ids]
    assert [s.split("-")[1] for s in stored] == [f"{c.trace_id:032x}" for c in ctxs]
    monkeypatch.setattr(crm, "deliver", lambda c, row: db.run(c, "update crm_outbox set status = 'sent' where id = %s", row["id"]) and {})
    assert trace.get_current_span().get_span_context().trace_id == 0
    crm._deliver_one(cur, {})
    crm._deliver_one(cur, {})
    spans = [s for s in exporter.get_finished_spans() if s.name == "crm deliver"]
    assert len(spans) == 2
    for span, ctx, request_span in zip(spans, ctxs, ("POST /api/a", "POST /api/b")):
        assert span.parent is None and span.kind == trace.SpanKind.CLIENT          # linked, not parented
        assert [(lk.context.trace_id, lk.context.span_id) for lk in span.links] == [(ctx.trace_id, ctx.span_id)], request_span
    assert spans[0].context.trace_id != spans[1].context.trace_id and spans[0].context.trace_id != ctxs[0].trace_id


def test_the_delivery_job_does_not_join_the_trace_of_the_first_request(cur, tracing):
    provider, _ = tracing
    db.run(cur, "delete from jobs where kind = 'crm_deliver'")
    with provider.get_tracer("test").start_as_current_span("POST /api/a"):
        crm.wake(cur)
    assert db.val(cur, "select trace_parent from jobs where kind = 'crm_deliver'") is None


def test_a_missing_or_malformed_stored_context_is_skipped_not_fatal(cur, tracing):
    _, exporter = tracing
    with telemetry.delivery_span("crm deliver", [None, "garbage", "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"]):
        pass
    span = [s for s in exporter.get_finished_spans() if s.name == "crm deliver"][0]
    assert len(span.links) == 1 and f"{span.links[0].context.trace_id:032x}" == "0af7651916cd43dd8448eb211c80319c"


def test_owners_are_delivered_before_a_backlog_of_tier_batches(cur, monkeypatch):
    _no_waiting_rows(cur)
    slow = [crm.queue_row(cur, "scores", {"items": []}, icp_version=None, ref="scores:3") for _ in range(3)]
    marks = crm.queue_row(cur, "mqa", {"items": []}, ref="mqa")
    plan_books = crm.queue_row(cur, "books", {"items": []}, ref="plan:1")
    hand = crm.queue_row(cur, "books", {"items": []}, ref="hand:7")
    order = []
    monkeypatch.setattr(crm, "deliver", lambda c, row: order.append(row["id"]) or db.run(c, "update crm_outbox set status = 'sent' where id = %s", row["id"]) or {})
    for _ in range(6):
        crm._deliver_one(cur, {})
    # Books before marks before tiers; rows of one kind keep their order, so an older plan send never lands after a newer owner change.
    assert order == [plan_books, hand, marks, *slow]


def test_a_retry_after_waits_without_losing_the_row(cur, monkeypatch):
    _no_waiting_rows(cur)
    rid = crm.queue_row(cur, "books", {"items": []}, ref="plan:1")

    def slow_down(c, row):
        raise crm.CrmDown("CRM Desk asked to slow down", 30)
    monkeypatch.setattr(crm, "deliver", slow_down)
    db.run(cur, "delete from jobs where kind = 'crm_deliver'")
    crm._deliver_one(cur, {})
    assert db.val(cur, "select status from crm_outbox where id = %s", rid) == "queued"
    assert db.val(cur, "select count(*) from jobs where kind = 'crm_deliver' and status = 'queued' and run_at > app_now()") == 1


def test_the_migration_keeps_the_job_quiet_while_it_waits_for_a_lock():
    from pathlib import Path
    sql = (Path(__file__).resolve().parents[1] / "migrations" / "0010_wk2_moves_traces_owners.sql").read_text()
    assert "set local lock_timeout = '5s'" in sql and sql.index("set local lock_timeout") < sql.index("\nalter table crm_outbox add")
    assert jobs  # the module the worker runs these on


# ---- the screens (source checks, as the repo does: there is no browser test)

from pathlib import Path  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "web" / "src"


def _src(name: str) -> str:
    return (WEB / name).read_text()


def test_the_territories_page_says_the_start_once_and_can_ask_a_manager():
    src = _src("pages/Territories.tsx")
    assert '"Starts the day it is activated"' in src and "once a manager activates it" not in src
    assert 'openSheet("ask", `plan-${plan.id}`)' in src and "Ask for approval" in src
    assert "deliveryLine(plan.delivery)" in src and "deliveryLine(m.delivery)" in src            # when it reached CRM Desk (J39)
    assert "data.owner_changes" in src and '"Changes owner"' in src and "In this plan" in src     # J1: the accounts a plan moves


def test_the_move_forms_show_the_hours_after_and_the_date_has_no_default():
    src = _src("sheets_moves.tsx")
    assert "<CapacityAfter" in src and "<CapacityNote c={match.capacity}" in src                  # list mode and by-territory mode
    assert "const date = on;" in src and "opts.today" in src and "!!date" in src                   # m3: the person chooses the date
    assert "if (r.plan)" in src and "The accounts moved." in src                                  # B4: no draft plan to open when a plan is scheduled
    assert "p.moves.waiting" in src and "deliveryLine(p.delivery)" in src and "export function AskSheet" in src
    assert "/api/approval-asks" in src
    owner = _src("sheets.tsx")
    assert "<CapacityAfter to={to ? Number(to) : null} ids={[c.id]} />" in owner                  # the hand move says it too
    parts = _src("parts.tsx")
    assert "never blocks" in parts and "Over 100% of their hours" in parts


def test_the_account_sheet_and_source_sheet_say_the_new_things():
    src = _src("sheets.tsx")
    assert "c.crm_differs" in src and "say(`, set by ${x.set_by}`)" in src and "say(`CRM Desk, ${x.seat}`)" in src         # J28
    assert "Looked after by" in src and "Run now" in src and "s.can_run" in src                          # J5
    assert 'openSheet("ask", `icp-${v.id}`)' in src


def test_accounts_can_be_listed_by_what_changed_and_handoffs_lists_each_send():
    acc = _src("pages/Accounts.tsx")
    assert '"changed"' in acc and "Tier moved since v" in acc and "Owner moved since last plan" in acc
    hand = _src("pages/Handoffs.tsx")
    assert "data.crm.deliveries" in hand and "deliveryLine(" in hand


def test_the_evidence_run_says_what_it_did_and_the_time_it_ran():
    src = _src("pages/Evidence.tsx")
    assert "No new suggestions" in src and "no verdict changed" in src and "dayTime(data.run.ran_at)" in src


def test_the_published_rules_are_titled_with_their_version_and_a_new_visit_starts_as_the_default_person():
    assert "`Published v${p.number}`" in _src("pages/Profile.tsx")
    api, app = _src("api.ts"), _src("App.tsx")
    assert "sessionStorage" in api and "localStorage" not in api and "storedActingAs" in app and "localStorage" not in app.replace("localStorage.getItem", "")


def test_the_totals_tips_no_longer_explain_a_gap_that_is_gone():
    tips = _src("tips.ts")
    assert "a few under the count on Market" not in tips and "excluding competitors and one-person businesses" in tips


def test_the_evidence_run_answers_with_what_it_made_and_what_changed(demo, monkeypatch):
    """m1: a run says how many suggestions it added and how many verdicts changed; a second run with the same deals says none."""
    from fastapi.testclient import TestClient

    from market.api import app as app_mod
    monkeypatch.setattr(app_mod, "rate_limit", lambda *a, **k: None)
    with db.tx() as cur:
        rv = _revops(cur)
    with TestClient(app_mod.app) as client:
        r = client.post("/api/evidence/run", headers={"X-Acting-As": str(rv["id"]), "Content-Type": "application/json"})
        assert r.status_code == 200, r.text
        again = client.post("/api/evidence/run", headers={"X-Acting-As": str(rv["id"]), "Content-Type": "application/json"}).json()
    assert set(r.json()) == {"run", "suggestions", "changed"}
    assert again["suggestions"] == 0 and again["changed"] == 0
