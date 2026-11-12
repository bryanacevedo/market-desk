"""The demo, built in order: the world, then everything the desk computes from it, with the people in the story doing
what they would have done on the dates they did it. The clock opens on 2026-11-11."""
from __future__ import annotations

import random
from datetime import date, datetime, timezone

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


def profile_history(cur, u: dict) -> dict[int, int]:
    ids = {}
    for i, v in enumerate(profiles.demo_versions(), start=1):
        status = "draft" if v["published"] is None else ("published" if i == 3 else "retired")
        ids[i] = db.val(cur, """insert into icp_versions (number, status, rules, note, author, published_by, published_at, created_at)
                               values (%s,%s,%s,%s,%s,%s,%s,%s) returning id""", i, status, J(v["rules"]), v["note"],
                        u["Sam"]["id"], u["Elena"]["id"] if v["published"] else None,
                        _ts(v["published"]) if v["published"] else None, _ts(v["created"]))
        audit.log(cur, "Sam Kowalski", "profile_draft_created", "icp_version", ids[i], {"number": i}, actor_id=u["Sam"]["id"])
        if v["published"]:
            audit.log(cur, "Elena Duarte", "profile_published", "icp_version", ids[i], {"number": i}, actor_id=u["Elena"]["id"])
    return ids


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
            db.run(cur, """insert into desk_results (company, destination, period_start, period_end, worked, held_back, test,
                           meetings, opportunities, pipeline_cents, read_at, source_run)
                           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                   cid, "account_desk" if grp == "worked" else None, start, end, grp == "worked", grp == "held_back",
                   test_id, m, opp, opp * rng.randint(25_000, 60_000) * 100, world.NOW, src)


def book_results(cur, book_id: int, start: date, seed: int) -> None:
    rng = random.Random(seed)
    src = db.val(cur, "select max(id) from source_runs where source = 'account_desk'")
    rows = db.all(cur, """select r.company, r.tier from target_book_rows r where r.book = %s and not r.test_member
                          and not exists (select 1 from desk_results x where x.company = r.company and x.test is not null)""", book_id)
    for r in rows:
        p = 0.14 if r["tier"] == "A" else 0.08
        m = 1 if rng.random() < p else 0
        opp = 1 if m and rng.random() < 0.4 else 0
        won = 1 if opp and rng.random() < 0.15 else 0
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
        db.run(cur, """insert into desk_results (company, destination, period_start, period_end, worked, held_back, meetings,
                       opportunities, read_at, source_run) values (%s,'events_desk',%s,%s,true,false,%s,%s,%s,%s)""",
               cid, s, e, m, 1 if m and rng.random() < 0.3 else 0, world.NOW, src)
    return len(ids)


def build_demo(n_companies: int = 18_000, seed: int = 7) -> dict:
    info: dict = {}
    with db.tx() as cur:
        info["world"] = world.build(cur, seed=seed, n_companies=n_companies)
    with db.tx() as cur:
        info["model_read_fields"] = read_descriptions(cur)
        info["losses_coded"] = code_losses(cur)
    with db.tx() as cur:
        u = users(cur)
        v = profile_history(cur, u)
        segments.load_segments(cur, v[3])
        info["analysis_run"] = run = evidence.run(cur)
        for i in (3, 4):
            rules = db.val(cur, "select rules from icp_versions where id = %s", v[i])
            db.run(cur, "update icp_versions set rules = %s, based_on_analysis = %s where id = %s",
                   J(profiles.attach_evidence(cur, rules, run)), run, v[i])
        for i in (1, 2, 3):
            fit.score_version(cur, v[i])
        segments.roles(cur)
        info["quotes"] = segments.quotes(cur)
    with db.tx() as cur:
        u = users(cur)
        sam, elena = u["Sam"], u["Elena"]
        db.run(cur, "update sim_clock set at = %s", _ts("2026-04-20"))
        t1 = tests_seg.create_draft(cur, "fintech_core", "Fintech companies of 120 to 499 people book meetings at twice the rate of the rest.", sam)
        t2 = tests_seg.create_draft(cur, "devtools", "Developer tools companies book meetings at twice the rate of the rest.", sam)
        tests_seg.start(cur, t1, sam, started_on=date(2026, 5, 1), ends_on=date(2026, 8, 31))
        tests_seg.start(cur, t2, sam, started_on=date(2026, 5, 1), ends_on=date(2026, 8, 31))
        test_results(cur, t1, 0.22, 0.106, date(2026, 5, 1), date(2026, 8, 31), seed + 1)
        test_results(cur, t2, 0.11, 0.106, date(2026, 5, 1), date(2026, 8, 31), seed + 2)
        db.run(cur, "update segment_tests set status = 'read' where id = any(%s)", [t1, t2])
        # The plan that is active now, drafted by Sam and activated by Elena on 1 July.
        db.run(cur, "update sim_clock set at = %s", _ts("2026-06-24"))
        h2 = territories.build_plan(cur, name="Second half 2026", author=sam["id"], territories=TERRITORIES_H2(u),
                                    on=date(2026, 7, 1), created_at=_ts("2026-06-24"))
        db.run(cur, "update sim_clock set at = %s", _ts("2026-07-01"))
        territories.activate(cur, h2, elena)
        b1 = handoff.build_book(cur, "account_desk", sam, at=_ts("2026-07-01"))
        db.run(cur, "update sim_clock set at = %s", _ts("2026-10-01"))
        t3 = tests_seg.create_draft(cur, "data_infra", "Data infrastructure companies book meetings at twice the rate of the rest.", sam)
        tests_seg.start(cur, t3, sam, started_on=date(2026, 10, 1), ends_on=date(2027, 1, 31))
        b2 = handoff.build_book(cur, "account_desk", sam, at=_ts("2026-10-01"))
        # Running test members join the book; a held-back one is refused by the database (scenario S4).
        held = db.val(cur, "select company from segment_test_members where test = %s and grp = 'held_back' order by company limit 1", t3)
        try:
            with cur.connection.transaction():
                db.run(cur, "insert into target_book_rows (book, company, tier, owner, segment) values (%s,%s,'A',null,'data_infra')", b2, held)
        except Exception as exc:  # noqa: BLE001 the refusal is the point
            audit.log(cur, "desk", "book_row_refused", "company", held, {"book": b2, "why": str(exc).splitlines()[0]})
        handoff.build_book(cur, "events_desk", sam, at=_ts("2026-10-02"))
        db.run(cur, "update sim_clock set at = %s", world.NOW)
        test_results(cur, t3, 0.04, 0.03, date(2026, 10, 1), date(2026, 11, 10), seed + 3)
        book_results(cur, b1, date(2026, 7, 1), seed + 4)
        info["event_accounts"] = event_results(cur, seed + 5)
        info["books"] = [b1, b2]
    with db.tx() as cur:
        u = users(cur)
        sam, elena = u["Sam"], u["Elena"]
        db.run(cur, "update sim_clock set at = %s", _ts("2026-11-09"))
        q1 = territories.build_plan(cur, name="First quarter 2027", author=sam["id"], territories=territories_q1(u),
                                    on=date(2027, 1, 1), created_at=_ts("2026-11-09"))
        moved = db.one(cur, """select a.company, a.owner from assignments a join account_fit f on f.company = a.company
                              and f.icp_version = (select based_on from territory_plans where id = %s)
                              where a.plan = %s and a.reason_code = 'rule' and a.owner = %s order by a.company limit 1""",
                       q1, q1, u["Daniel"]["id"])
        territories.manual_move(cur, q1, moved["company"], u["Maya"]["id"],
                                "Maya met their finance team at the Austin dinner; she keeps it.", sam)
        db.run(cur, "update sim_clock set at = %s", world.NOW)
        info["sizing_run"] = sizing.run(cur)
        db.run(cur, "update sim_clock set at = %s", _ts("2026-11-10"))
        t1 = db.val(cur, "select id from segment_tests where segment = 'fintech_core'")
        tests_seg.decide(cur, t1, "expand", elena, "Worth territory: twice the meetings.")
        db.run(cur, "update sim_clock set at = %s", world.NOW)
        info["proposals"] = proposals.generate(cur)
        # Draft v4 already holds the usage and size proposals: they are marked as drafted into it.
        v4 = db.val(cur, "select id from icp_versions where number = 4")
        db.run(cur, """update change_proposals set status = 'drafted', decided_by = %s, draft_version = %s
                       where key like 'add_rule:pricing_model:%%' or key like 'penalty:size_band:%%2,000 to 4,999%%'""", sam["id"], v4)
        region = db.val(cur, "select id from change_proposals where key = 'drop_rule:region'")
        if region:
            proposals.dismiss(cur, region, elena, "We only sell where we have a team and entities: North America and Europe.")
        info["stories"] = segments.stories(cur)
        info["alerts"] = monitors.run_all(cur)
    return info
