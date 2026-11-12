"""The demo, built in order: the world, then everything the desk computes from it, with the people in the story doing
what they would have done on the dates they did it. The clock opens on 2026-11-11."""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from .. import (
    ai,
    audit,
    db,
    evidence,
    fit,
    handoff,
    monitors,
    profiles,
    proposals,
    segments,
    sizing,
    territories,
    tests_seg,
)
from ..catalog import SEGMENTS
from ..db import J
from . import world


def _ts(d: str) -> datetime:
    return datetime.fromisoformat(d).replace(hour=15, tzinfo=timezone.utc)


def users(cur) -> dict[str, dict]:
    return {u["name"].split()[0]: u for u in db.all(cur, "select * from users")}


def read_descriptions(cur) -> int:
    """The model reads descriptions where the vendor gave no industry or no pricing model (docs/SPEC.md 11.1)."""
    rows = db.all(cur, """select id, name, description, industry, pricing_model from companies
                          where (industry is null or pricing_model = 'unknown') and lifecycle <> 'competitor' order by id""")
    n = 0
    for r in rows:
        out = ai.classify(cur, r["name"], r["description"])
        if not out:
            continue
        for field, quote in (("industry", "industry_quote"), ("pricing_model", "pricing_quote")):
            current = r[field]
            if out[field] != "unknown" and current in (None, "unknown"):
                db.run(cur, """insert into field_values (company, field, value, source, observed_at, confidence, quote)
                               values (%s,%s,%s,'model',app_now() - interval '6 days',0.7,%s)""",
                       r["id"], field, J(out[field]), out[quote])
                n += 1
    return n


def code_losses(cur) -> int:
    n = 0
    for d in db.all(cur, "select id, loss_reason_text from deals where outcome = 'lost' and loss_reason_text is not null"):
        out = ai.code_loss(cur, d["loss_reason_text"], "loss")
        db.run(cur, "update deals set loss_code = %s, loss_code_source = 'model', competitor = coalesce(competitor, %s) where id = %s",
               out["code"], out["competitor"], d["id"])
        n += 1
    for c in db.all(cur, "select company, churn_reason_text from customers where churn_reason_text is not null"):
        out = ai.code_loss(cur, c["churn_reason_text"], "churn")
        db.run(cur, "update customers set churn_reason_code = %s where company = %s", out["code"], c["company"])
        n += 1
    return n


def insert_version(cur, u: dict, number: int, *, status: str, published: str | None = None) -> int:
    v = profiles.demo_versions()[number - 1]
    vid = db.val(cur, """insert into icp_versions (number, status, rules, note, author, published_by, published_at, created_at)
                         values (%s,%s,%s,%s,%s,%s,%s,%s) returning id""", number, status, J(v["rules"]), v["note"],
                 u["Sam"]["id"], u["Elena"]["id"] if published else None, _ts(published) if published else None, _ts(v["created"]))
    audit.log(cur, "Sam Kowalski", "profile_draft_created", "icp_version", vid, {"number": number}, actor_id=u["Sam"]["id"])
    return vid


def clock(cur, at) -> None:
    db.run(cur, "update sim_clock set at = %s", at if isinstance(at, datetime) else _ts(at))


def open_deal(cur, company: int, created: datetime, source: str, rng: random.Random) -> None:
    """An opportunity a desk reported becomes an open deal in the CRM, so results and the CRM agree."""
    c = db.one(cur, "select * from companies where id = %s", company)
    owner = db.val(cur, """select id from users where role = 'ae' and started_on <= %s::date
                           order by case when %s = 'Europe' and name like 'Hannah%%' then 0 when %s <> 'Europe' and name not like 'Hannah%%' then 0 else 1 end, md5(%s::text || name) limit 1""",
                   created, c["region"], c["region"], company)
    snap = {k: c[k] for k in ("industry", "employees", "region", "region_group", "country", "revenue_band", "pricing_model",
                              "tech", "hq_city", "founded_year")}
    did = db.val(cur, """insert into deals (company, kind, created_at, stage, outcome, amount_cents, source, owner, snapshot)
                         values (%s,'new',%s,%s,'open',%s,%s,%s,%s) returning id""", company, created,
                 rng.choice(["Discovery", "Evaluation"]), rng.randint(25_000, 60_000) * 100, source, owner, J(snap))
    for p in ("cfo", "controller"):
        db.run(cur, "insert into deal_roles (deal, persona, seniority) values (%s,%s,%s)", did, p, "c_suite" if p == "cfo" else "director")
    db.run(cur, "update companies set lifecycle = 'open_opp', owner_id = %s, crm_id = coalesce(crm_id, %s) where id = %s and lifecycle = 'prospect'",
           owner, f"CRM-{company:06d}", company)


TERRITORIES_H2 = lambda u: [  # noqa: E731
    {"key": "na_fin_sw", "label": "North America: fintech and software", "region_groups": ["North America"],
     "segments": ["fintech_core", "fintech_large", "software"], "people": [u["Maya"]["id"], u["Daniel"]["id"]],
     "ae": u["Grace"]["id"]},
    {"key": "na_tech", "label": "North America: data, developer tools, marketplaces, small",
     "region_groups": ["North America"], "segments": ["data_infra", "devtools", "marketplaces", "small"],
     "people": [u["Tom"]["id"]], "ae": u["Omar"]["id"]},
    {"key": "europe", "label": "Europe", "region_groups": ["UK and Ireland", "DACH", "France and Benelux", "Nordics", "Southern Europe"],
     "segments": [s["key"] for s in SEGMENTS if s["key"] != "enterprise"], "people": [u["Priya"]["id"]], "ae": u["Hannah"]["id"]},
    {"key": "enterprise", "label": "Enterprise", "region_groups": ["North America", "UK and Ireland", "DACH", "France and Benelux",
                                                                    "Nordics", "Southern Europe"],
     "segments": ["enterprise"], "people": [u["Grace"]["id"], u["Hannah"]["id"]], "ae": None},
]


def territories_q1(u: dict) -> list[dict]:
    t = TERRITORIES_H2(u)
    t[2] = {**t[2], "key": "europe_west", "label": "Europe: UK, France, Benelux, Nordics, South",
            "region_groups": ["UK and Ireland", "France and Benelux", "Nordics", "Southern Europe"]}
    t.insert(3, {"key": "dach", "label": "DACH", "region_groups": ["DACH"],
                 "segments": t[2]["segments"], "people": [u["Nadia"]["id"]], "ae": u["Hannah"]["id"]})
    t[-1] = {**t[-1], "people": [u["Grace"]["id"], u["Hannah"]["id"], u["Omar"]["id"]]}
    return t


def test_results(cur, test_id: int, worked_rate: float, held_rate: float, start: date, end: date, seed: int) -> None:
    """Meetings read from the CRM for every member of a test, worked or held back, counted the same way."""
    rng = random.Random(seed)
    for grp, rate in (("worked", worked_rate), ("held_back", held_rate)):
        ids = [r["company"] for r in db.all(cur, "select company from segment_test_members where test = %s and grp = %s order by company",
                                             test_id, grp)]
        hit = set(rng.sample(ids, round(rate * len(ids))))
        src = db.val(cur, "select max(id) from source_runs where source = 'crm'")
        for cid in ids:
            m = (1 + (rng.random() < 0.25)) if cid in hit else 0
            opp = 1 if cid in hit and rng.random() < 0.35 else 0
            if opp:
                open_deal(cur, cid, _ts(str(end)) - timedelta(days=rng.randint(0, 12)), "outbound" if grp == "worked" else "inbound", rng)
            db.run(cur, """insert into desk_results (company, destination, period_start, period_end, worked, held_back, test,
                           meetings, opportunities, pipeline_cents, read_at, source_run)
                           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                   cid, "account_desk" if grp == "worked" else None, start, end, grp == "worked", grp == "held_back",
                   test_id, m, opp, opp * rng.randint(25_000, 60_000) * 100, world.NOW, src)


def book_results(cur, book_id: int, start: date, seed: int) -> None:
    """Account Desk's results on a book's accounts; an opportunity is an open deal opened in late October."""
    rng = random.Random(seed)
    src = db.val(cur, "select max(id) from source_runs where source = 'account_desk'")
    rows = db.all(cur, """select r.company, r.tier from target_book_rows r where r.book = %s and not r.test_member
                          and not exists (select 1 from desk_results x where x.company = r.company and x.test is not null)""", book_id)
    for r in rows:
        p = 0.14 if r["tier"] == "A" else 0.08
        m = 1 if rng.random() < p else 0
        opp = 1 if m and rng.random() < 0.4 else 0
        won = 0
        if opp:
            open_deal(cur, r["company"], _ts("2026-10-20") + timedelta(days=rng.randint(0, 18)), "outbound", rng)
        db.run(cur, """insert into desk_results (company, destination, period_start, period_end, worked, held_back, meetings,
                       opportunities, won, pipeline_cents, read_at, source_run) values (%s,'account_desk',%s,%s,true,false,%s,%s,%s,%s,%s,%s)""",
               r["company"], start, world.NOW.date(), m, opp, won, opp * rng.randint(25_000, 70_000) * 100, world.NOW, src)


def event_results(cur, seed: int) -> int:
    rng = random.Random(seed)
    src = db.val(cur, "select max(id) from source_runs where source = 'events_desk'")
    vid = db.val(cur, "select id from icp_versions where status = 'published'")
    ids = [r["company"] for r in db.all(cur, """select f.company from account_fit f join companies c on c.id = f.company
              where f.icp_version = %s and f.tier in ('A','B') and c.lifecycle = 'prospect' order by md5(c.primary_domain || 'events') limit 180""", vid)]
    events = [(date(2026, 3, 18), date(2026, 3, 19)), (date(2026, 5, 6), date(2026, 5, 7)),
              (date(2026, 9, 9), date(2026, 9, 10)), (date(2026, 10, 21), date(2026, 10, 22))]
    for i, cid in enumerate(ids):
        s, e = events[i % 4]
        m = 1 if rng.random() < 0.3 else 0
        # Only the October event is recent enough to have opened deals that are still open.
        opp = 1 if m and i % 4 == 3 and rng.random() < 0.35 else 0
        if opp:
            open_deal(cur, cid, _ts(str(e)), "event", rng)
        db.run(cur, """insert into desk_results (company, destination, period_start, period_end, worked, held_back, meetings,
                       opportunities, read_at, source_run) values (%s,'events_desk',%s,%s,true,false,%s,%s,%s,%s)""",
               cid, s, e, m, opp, world.NOW, src)
    return len(ids)


def build_demo(n_companies: int = 18_000, seed: int = 7) -> dict:
    """In date order, so nothing on file knows what happened after it."""
    info: dict = {}
    with db.tx() as cur:
        info["world"] = world.build(cur, seed=seed, n_companies=n_companies)
    with db.tx() as cur:
        info["model_read_fields"] = read_descriptions(cur)
        info["losses_coded"] = code_losses(cur)
    with db.tx() as cur:
        u = users(cur)
        sam, elena = u["Sam"], u["Elena"]
        # Versions 1 and 2, the second published since April 2025.
        v1 = insert_version(cur, u, 1, status="retired", published="2024-02-01")
        v2 = insert_version(cur, u, 2, status="published", published="2025-04-01")
        segments.load_segments(cur, v2)
        segments.roles(cur)
        for v in (v1, v2):
            fit.score_version(cur, v)
        # January: the first-half plan, drafted by Sam, activated by Elena.
        clock(cur, "2026-01-02")
        h1 = territories.build_plan(cur, name="First half 2026", author=sam["id"], territories=TERRITORIES_H2(u),
                                    on=date(2026, 1, 5), created_at=_ts("2026-01-02"))
        clock(cur, "2026-01-05")
        territories.activate(cur, h1, elena)
        # April: two segment tests drafted; they start on 1 May with the first Account Desk book.
        clock(cur, "2026-04-20")
        t1 = tests_seg.create_draft(cur, "fintech_core", "Fintech companies of 120 to 499 people book meetings at twice the rate of the rest.", sam)
        t2 = tests_seg.create_draft(cur, "devtools", "Developer tools companies book meetings at twice the rate of the rest.", sam)
        clock(cur, "2026-05-01")
        tests_seg.start(cur, t1, sam, started_on=date(2026, 5, 1), ends_on=date(2026, 8, 31))
        tests_seg.start(cur, t2, sam, started_on=date(2026, 5, 1), ends_on=date(2026, 8, 31))
        b1 = handoff.build_book(cur, "account_desk", sam, at=_ts("2026-05-01"))
        # Late May: the evidence run behind version 3, published by Elena on 2 June.
        clock(cur, "2026-05-25")
        r1 = evidence.run(cur)
        v3 = insert_version(cur, u, 3, status="draft")
        rules = db.val(cur, "select rules from icp_versions where id = %s", v3)
        db.run(cur, "update icp_versions set rules = %s, based_on_analysis = %s where id = %s",
               J(profiles.attach_evidence(cur, rules, r1)), r1, v3)
        clock(cur, "2026-06-02")
        profiles.publish(cur, v3, elena, rescore_now=True)
        segments.load_segments(cur, v3)
        # The second-half plan keeps the running tests' accounts.
        clock(cur, "2026-06-24")
        h2 = territories.build_plan(cur, name="Second half 2026", author=sam["id"], territories=TERRITORIES_H2(u),
                                    on=date(2026, 7, 1), created_at=_ts("2026-06-24"))
        clock(cur, "2026-07-01")
        territories.activate(cur, h2, elena)
        b2 = handoff.build_book(cur, "account_desk", sam, at=_ts("2026-07-01"))
        # 31 August: the two tests end and are read from the CRM.
        clock(cur, "2026-08-31")
        test_results(cur, t1, 0.22, 0.106, date(2026, 5, 1), date(2026, 8, 31), seed + 1)
        test_results(cur, t2, 0.11, 0.106, date(2026, 5, 1), date(2026, 8, 31), seed + 2)
        db.run(cur, "update segment_tests set status = 'read' where id = any(%s)", [t1, t2])
        # 1 October: the data infrastructure test starts, and its worked group joins the next book.
        clock(cur, "2026-10-01")
        t3 = tests_seg.create_draft(cur, "data_infra", "Data infrastructure companies book meetings at twice the rate of the rest.", sam)
        tests_seg.start(cur, t3, sam, started_on=date(2026, 10, 1), ends_on=date(2027, 1, 31))
        b3 = handoff.build_book(cur, "account_desk", sam, at=_ts("2026-10-01"))
        held = db.val(cur, "select company from segment_test_members where test = %s and grp = 'held_back' order by company limit 1", t3)
        try:
            with cur.connection.transaction():
                db.run(cur, "insert into target_book_rows (book, company, tier, owner, segment) values (%s,%s,'A',null,'data_infra')", b3, held)
        except Exception as exc:  # noqa: BLE001 the refusal is the point (scenario S4)
            audit.log(cur, "desk", "book_row_refused", "company", held, {"book": b3, "why": str(exc).splitlines()[0]})
        clock(cur, "2026-10-02")
        handoff.build_book(cur, "events_desk", sam, at=_ts("2026-10-02"))
        clock(cur, "2026-11-09")
        info["event_accounts"] = event_results(cur, seed + 5)
        book_results(cur, b2, date(2026, 7, 1), seed + 4)
        test_results(cur, t3, 0.04, 0.03, date(2026, 10, 1), date(2026, 11, 8), seed + 3)
        info["books"] = [b1, b2, b3]
    with db.tx() as cur:
        u = users(cur)
        sam, elena = u["Sam"], u["Elena"]
        # Nightly rescoring after the CRM moved: open deals are tier X now.
        fit.score_version(cur, db.val(cur, "select id from icp_versions where status = 'published'"))
        q1 = territories.build_plan(cur, name="First quarter 2027", author=sam["id"], territories=territories_q1(u),
                                    on=date(2027, 1, 1), created_at=_ts("2026-11-09"))
        moved = db.one(cur, """select a.company, a.owner from assignments a where a.plan = %s and a.reason_code = 'rule'
                              and a.owner = %s order by a.company limit 1""", q1, u["Daniel"]["id"])
        territories.manual_move(cur, q1, moved["company"], u["Maya"]["id"],
                                "Maya has worked this account since the spring; she keeps it.", sam)
        # 10 November: the nightly evidence run, Sam's draft version 4, then the day's decisions.
        clock(cur, datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc))
        info["analysis_run"] = r2 = evidence.run(cur)
        clock(cur, "2026-11-10")
        v4 = insert_version(cur, u, 4, status="draft")
        rules = db.val(cur, "select rules from icp_versions where id = %s", v4)
        db.run(cur, "update icp_versions set rules = %s, based_on_analysis = %s where id = %s",
               J(profiles.attach_evidence(cur, rules, r2)), r2, v4)
        segments.roles(cur)
        info["quotes"] = segments.quotes(cur)
        info["sizing_run"] = sizing.run(cur)
        tests_seg.decide(cur, t1, "expand", elena, "Worth territory: twice the meetings.")
        info["proposals"] = db.val(cur, "select count(*) from change_proposals")
        db.run(cur, """update change_proposals set status = 'drafted', decided_by = %s, draft_version = %s
                       where key like 'add_rule:pricing_model:%%' or key like 'penalty:size_band:%%2,000 to 4,999%%'""", sam["id"], v4)
        region = db.val(cur, "select id from change_proposals where key = 'drop_rule:region'")
        if region:
            proposals.dismiss(cur, region, elena, "We only sell where we have a team and entities: North America and Europe.")
        info["stories"] = segments.stories(cur)
        clock(cur, world.NOW)
        info["alerts"] = monitors.run_all(cur)
    return info
