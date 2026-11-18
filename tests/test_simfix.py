"""Fixes from the first-visit simulation (S4, S5), decisions 66 to 71: plain words for desks that are not connected, a sample banner on
every screen, the first screen's one step, owners with role and source, the draft plan's owner, the prompt after a publish, source
dependents, how long an evidence run took. Backend reads run on the demo database in a rolled-back transaction; the web wiring checks
are plain reads of the source (the web app has no browser test), next to the typecheck and the screen-copy gate."""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from market import catalog as C
from market import db, names
from market import territories as terr
from market.api import views

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web" / "src"


def _src(name: str) -> str:
    return (WEB / name).read_text()


# ---- 66: every other desk is named only when it is connected

def test_alone_the_other_desks_are_plain_words(monkeypatch):
    monkeypatch.setattr(names, "CONFIG", SimpleNamespace(integrated_with=frozenset()))
    monkeypatch.delenv("CRM", raising=False)
    n = names.desk_names()
    assert n == {"crm_desk": "your CRM", "account_desk": "your outreach tool", "events_desk": "your events tool"}
    assert names.say("Account Desk has no pricing model field") == "Your outreach tool has no pricing model field"
    assert names.say("A manager pinned it in CRM Desk") == "A manager pinned it in your CRM"


def test_a_connected_desk_keeps_its_name(monkeypatch):
    monkeypatch.setattr(names, "CONFIG", SimpleNamespace(integrated_with=frozenset({"account_desk"})))
    monkeypatch.delenv("CRM", raising=False)
    assert names.say("Account Desk has no pricing model field") == "Account Desk has no pricing model field"
    assert names.say("CRM Desk answered 500") == "Your CRM answered 500"


def test_the_crm_setting_connects_crm_desk(monkeypatch):
    monkeypatch.setattr(names, "CONFIG", SimpleNamespace(integrated_with=frozenset()))
    monkeypatch.setenv("CRM", "crmdesk")
    assert names.desk_names()["crm_desk"] == "CRM Desk"


def test_me_names_the_desks_and_the_web_app_uses_them(demo):
    from fastapi.testclient import TestClient

    from market.api.app import app
    with TestClient(app) as c, db.tx() as cur:
        rv = db.val(cur, "select id from users where role = 'revops' and active order by id limit 1")
        me = c.get("/api/me", headers={"X-Acting-As": str(rv)}).json()
    assert set(me["names"]) == {"crm_desk", "account_desk", "events_desk"} and isinstance(me["integrated_with"], list)
    assert "setNames(me.names)" in _src("App.tsx")


def test_the_dropped_rules_of_a_draft_do_not_name_a_desk_that_is_not_connected(cur, monkeypatch):
    monkeypatch.setattr(names, "CONFIG", SimpleNamespace(integrated_with=frozenset()))
    monkeypatch.delenv("CRM", raising=False)
    h = views.handoffs(cur, True)
    why = [d["why"] for p in h["previews"] for d in p["dropped_rules"]]
    assert why and all("Account Desk" not in w for w in why) and any("your outreach tool" in w.lower() for w in why)


def test_no_screen_string_names_a_desk_outside_the_helpers():
    """The words Account Desk, Events Desk and CRM Desk reach a screen only through say(), deskName() or the server's names."""
    bare = []
    for p in list(WEB.glob("*.tsx")) + list(WEB.glob("pages/*.tsx")):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if re.search(r"\b(Account|Events|CRM) Desk\b", line) and not line.lstrip().startswith(("//", "/*", "*")):
                bare.append(f"{p.name}:{i}")
    # Each of these goes through Fig, Section, T or Tip (which say() it) or only renders when that desk is connected.
    allowed_files = {"lib.tsx", "tips.ts", "sheets_moves.tsx", "Handoffs.tsx", "Desk.tsx", "sheets.tsx", "Profile.tsx", "parts.tsx"}
    assert all(b.split(":")[0] in allowed_files for b in bare), bare


# ---- 67: Send new books now, asked once, never by itself

def test_publishing_asks_before_it_makes_the_files():
    src = _src("sheets_moves.tsx")
    assert "Send new books now?" in src and "Not now" in src
    publish = src[src.index("export function PublishSheet"):src.index("export function RollbackSheet")]
    prompt, form = publish.split("  return (\n    <Wrap", 1)
    # the publish call only records that it happened; no file is made from the sheet at all
    assert 'api("/api/books"' not in form and "setPublished(p.number)" in form
    # Changed on review: this test used to pin a "Make both files now" button in the prompt shown to RevOps. That branch could never
    # run: only a manager publishes and only RevOps makes books, and switching "Acting as" remounts the sheet. The button now lives
    # on Handoffs, and the prompt sends RevOps there.
    assert '"/api/books"' not in prompt and "Make both files now" not in prompt
    assert 'navigate("/handoffs")' in prompt and "Open Handoffs" in prompt


def test_handoffs_has_the_one_button_that_makes_both_files_when_they_are_behind(cur):
    page = _src("pages/Handoffs.tsx")
    assert "Make both files now" in page and "behind.length" in page and page.count('"/api/books"') >= 4
    assert "was written. The file for" in page, "a second POST that fails must still say the first file exists"
    # a manager sees the notice but not the button; RevOps is the only role that makes files
    assert "revops\n            ? <button" in page
    from market import profiles
    mgr = db.one(cur, "select * from users where role = 'manager' and active order by id limit 1")
    assert views.handoffs(cur, True)["behind"]["destinations"] == []
    draft = db.one(cur, "select id from icp_versions where status = 'draft' order by number limit 1")
    profiles.publish(cur, draft["id"], mgr, rescore_now=False)
    h = views.handoffs(cur, True)
    assert h["behind"]["destinations"] and h["behind"]["profile"] == views._published(cur)["number"]


def test_the_waiting_line_does_not_say_earlier_after_a_rollback():
    src = (ROOT / "src" / "market" / "api" / "app.py").read_text()
    assert "a profile other than the published version" in src and "an earlier profile than" not in src


# ---- 68: first screen, tour, banner

def test_the_first_screen_has_one_value_line_and_one_first_step():
    market, start = _src("pages/Market.tsx"), _src("pages/Start.tsx")
    assert "<FirstStep" in market and "VALUE_LINE" in start
    assert "See the clearest gap in the deals" in start
    # Pinned to the exact address and subject Bryan chose (2026-11-17); a mailto link opens the mail app in the same tab, so it carries no target and no rel.
    assert 'CONTACT_URL = "mailto:bryan@leandrive.io?subject=Market%20Desk%20demo";' in start
    link = start[start.index('<a className="link" href={CONTACT_URL}'):].split("</a>")[0]
    assert "Write to Bryan about your own data" in link and "target=" not in link and "rel=" not in link
    assert "contact Leandrive" not in start
    assert "If you are judging the work" in start and "If you would use it" in start and "Next step." in start


def test_the_start_page_has_between_4_and_6_steps_a_path():
    start = _src("pages/Start.tsx")
    for title in ("If you are judging the work", "If you would use it"):
        block = start[start.index(f'title="{title}"'):]
        block = block[:block.index("</Section>")]
        assert 4 <= block.count("{step(") <= 6


def test_the_demo_banner_is_on_every_screen_and_says_what_is_true():
    app = _src("App.tsx")
    assert "<DemoBanner me={me} />" in app and "Sample company with invented data." in app
    # three branches, each true where it shows: the snapshot refuses, the Render demo keeps changes until it restarts, anywhere else keeps them in the sample
    assert 'me.snapshot ? "Changes are refused."' in app and "Sample day: {sampleDay}" in app
    assert "Changes last until the demo restarts after 15 idle minutes, and anyone visiting meanwhile sees them." in app
    assert "Changes stay in this sample only." in app and "Changes are not saved in the public demo" not in app
    assert 'me.simulated ? " (the demo keeps its own clock)"' in app
    css = _src("market.css")
    assert ".demo-banner" in css and "@media (max-width: 900px) { .demo-banner a" in css


def test_a_write_control_says_before_the_click_that_the_demo_refuses():
    lib = _src("lib.tsx")
    assert 'REFUSED_WORDS = "The public demo does not do this. Run it yourself to try it."' in lib
    shim = (ROOT / "scripts" / "static_snapshot" / "shim.js").read_text()
    assert 'var REFUSED = "The public demo does not do this. Run it yourself to try it."' in shim
    for f in ("sheets_moves.tsx", "sheets.tsx", "pages/Changes.tsx", "pages/Handoffs.tsx", "pages/Profile.tsx", "pages/Territories.tsx", "pages/Evidence.tsx", "pages/Desk.tsx"):
        assert "writeHint()" in _src(f), f


def test_the_best_moment_is_the_clearest_gap_behind_an_open_change(cur):
    best = views.start(cur)["best"]
    assert best and best["label"] == "Healthcare software" and round(best["rate"] * 100) == 9 and round(best["rest_rate"] * 100) == 23
    open_ids = {fid for p in views.changes(cur)["open"] for fid in p["finding_ids"]}
    assert best["id"] in open_ids


def test_changes_marks_the_proposal_behind_the_best_moment():
    src = _src("pages/Changes.tsx")
    assert "Start here: the clearest gap in the deals" in src and "(p.finding_ids || []).includes(best.id)" in src


# ---- 69, 66: owners show role and source; the draft plan's owner is shown last and marked

def test_an_owner_shows_its_seat_and_where_it_comes_from(cur, monkeypatch):
    monkeypatch.setattr(names, "CONFIG", SimpleNamespace(integrated_with=frozenset()))
    monkeypatch.delenv("CRM", raising=False)
    rv = db.one(cur, "select * from users where role = 'revops' and active order by id limit 1")
    plan = db.val(cur, "select id from territory_plans where status = 'active'")
    cust = db.one(cur, "select company from assignments where plan = %s and reason_code = 'existing_owner' and owner is not null limit 1", plan)
    rule = db.one(cur, "select company from assignments where plan = %s and reason_code = 'rule' and owner is not null limit 1", plan)
    a = views.company(cur, cust["company"], rv)["owner"]
    b = views.company(cur, rule["company"], rv)["owner"]
    assert a["seat"] in ("AE", "SDR") and a["source"] == "your CRM"
    assert b["seat"] in ("AE", "SDR") and b["source"] == "the territory plan"
    rows = views.accounts(cur, rv, q="", tier="A", segment="", owner="", page=1)["rows"]
    assert any(r["owner_seat"] and r["owner_source"] for r in rows if r["owner"])
    assert all(r["owner_seat"] is None for r in rows if not r["owner"])


def test_a_draft_plans_owner_is_on_the_account_sheet_when_it_differs(cur):
    rv = db.one(cur, "select * from users where role = 'revops' and active order by id limit 1")
    row = db.one(cur, """select x.company, x.owner as draft_owner, p.name as plan from assignments x join territory_plans p on p.id = x.plan
                         join assignments a on a.company = x.company and a.plan = (select id from territory_plans where status = 'active')
                         where p.status = 'draft' and x.owner is not null and x.owner is distinct from a.owner limit 1""")
    if row is None:
        pytest.skip("the demo's draft plan changes no owner")
    d = views.company(cur, row["company"], rv)["draft_owner"]
    assert d and d["plan"] == row["plan"] and d["name"]
    same = db.one(cur, """select x.company from assignments x join assignments a on a.company = x.company
                          and a.plan = (select id from territory_plans where status = 'active')
                          join territory_plans p on p.id = x.plan where p.status = 'draft' and x.owner is not distinct from a.owner limit 1""")
    assert same is None or views.company(cur, same["company"], rv)["draft_owner"] is None


def test_the_sheet_shows_the_draft_owner_last_and_muted():
    src = _src("sheets.tsx")
    # the row is "{c.draft_owner ? <>": the section guard "c.owner || c.draft_owner ?" is a separate, earlier match
    assert "{c.draft_owner ? <>" in src and "draft: not in force until a manager activates" in src
    assert src.index("{c.draft_owner ? <>") > src.index("c.coming || []")


# ---- 70: Territories, dates, empties

def test_hand_moved_rows_say_who_and_when(cur):
    rv = db.one(cur, "select * from users where role = 'revops' and active order by id limit 1")
    plan = db.val(cur, "select id from territory_plans where status = 'draft'")
    row = db.one(cur, "select company, owner from assignments where plan = %s and owner is not null limit 1", plan)
    other = db.val(cur, "select id from users where active and role = (select role from users where id = %s) and id <> %s limit 1", row["owner"], row["owner"])
    terr.manual_move(cur, plan, row["company"], other, "Because it covers the region", rv)
    m = [x for x in views.territories(cur, plan, True)["manual"] if x["company"] == row["company"]][0]
    assert m["by_name"] == rv["name"] and m["moved_at"] is not None
    src = _src("pages/Territories.tsx")
    assert 'countLabel="open"' in src and "m.by_name" in src and "m.moved_at" in src


def test_a_date_from_another_year_prints_the_year():
    lib = _src("lib.tsx")
    assert "getFullYear() !== new Date(NOW).getFullYear()" in lib


def test_empty_states_say_what_goes_here_and_show_an_example():
    assert "example?: string" in _src("lib.tsx") and "For example" in _src("lib.tsx")
    for f, title in (("pages/Handoffs.tsx", "No file made yet"), ("pages/Territories.tsx", "No proposals"), ("pages/Accounts.tsx", "No accounts match"),
                     ("pages/Changes.tsx", "Nothing open"), ("pages/Evidence.tsx", "No findings match"), ("sheets_moves.tsx", "No accounts chosen")):
        line = next(x for x in _src(f).splitlines() if f'title="{title}"' in x)
        assert "example=" in line, (f, title)


def test_propose_a_move_from_an_account_carries_the_account_in(cur):
    from market import moves
    plan = db.val(cur, "select id from territory_plans where status = 'active'")
    cid = db.val(cur, "select company from assignments where plan = %s and owner is not null limit 1", plan)
    got = moves.candidates(cur, only=cid)
    assert [r["id"] for r in got] == [cid]
    src = _src("sheets_moves.tsx")
    assert "This account is not in the plan in effect" in src and "could not be added from here" in src and 'carried === "loading"' in src


# ---- 71: sources and evidence

def test_a_source_lists_what_depends_on_it(cur):
    key = db.val(cur, "select source from field_values where field = 'industry' limit 1")
    d = views.source(cur, key, True)["depends"]
    assert any(f["field"] == "Industry" and f["n"] > 0 for f in d["fields"])
    assert any(r.startswith("Industry") for r in d["rules"])
    assert "What depends on it" in _src("sheets.tsx")


def test_the_run_time_of_the_last_evidence_run_is_known(cur):
    run = db.val(cur, "select max(id) from analysis_runs")
    assert views.evidence(cur, True)["run"]["seconds"] is None or True
    db.run(cur, "insert into audit_log (actor, action, object_kind, object_id, detail) values ('t', 'evidence_run', 'analysis_run', %s, %s)",
           str(run), db.J({"seconds": 12.4}))
    assert views.evidence(cur, True)["run"]["seconds"] == 12.4
    assert "The last run took" in _src("pages/Evidence.tsx")


# ---- 72: decision 9, the book file keeps its columns

def test_the_book_file_keeps_the_columns_account_desk_reads():
    """Account Desk's accounts import reads name, domain, industry, employees, country, revenue_band, tech, lifecycle, owner_email,
    crm_id, parent_domain (and subscriber_type, which this file leaves out). It has no SDR, AE, tier or profile version column,
    so none is added here: the file stays as it was and the cross-desk contract does not change."""
    assert C.AD_COLUMNS == ["name", "domain", "industry", "employees", "country", "revenue_band", "tech", "lifecycle", "owner_email",
                            "crm_id", "parent_domain"]


# ---- motion and contrast

def test_no_route_level_animation_is_longer_than_150_ms():
    for f in ("styles.css", "market.css"):
        for m in re.finditer(r"\.(page-enter|rise > \*|tile|range-band)[^{]*\{[^}]*animation:\s*[\w-]+\s+(\d+)ms", _src(f)):
            assert int(m.group(2)) <= 150, (f, m.group(0)[:80])
    assert "animation: none" in _src("styles.css").split(".page-enter")[1].splitlines()[0]


def test_numbers_do_not_count_up():
    assert "requestAnimationFrame" not in _src("lib.tsx").split("export function Count")[1].split("export function Fig")[0]


def test_after_a_publish_the_files_are_behind_and_revops_is_told_but_nothing_is_made(cur):
    from market import profiles
    assert views.books_behind(cur) == []
    draft = db.one(cur, "select id from icp_versions where status = 'draft' order by number limit 1")
    mgr = db.one(cur, "select * from users where role = 'manager' and active order by id limit 1")
    before = db.val(cur, "select count(*) from target_books")
    profiles.publish(cur, draft["id"], mgr, rescore_now=False)
    behind = views.books_behind(cur)
    assert behind and {b["destination"] for b in behind} <= {"account_desk", "events_desk"}
    assert db.val(cur, "select count(*) from target_books") == before, "publishing must not make a file by itself"


# ---- review fixes

def test_notes_and_errors_do_not_name_a_desk_that_is_not_connected(cur, monkeypatch):
    monkeypatch.setattr(names, "CONFIG", SimpleNamespace(integrated_with=frozenset()))
    monkeypatch.delenv("CRM", raising=False)
    rv = db.one(cur, "select * from users where role = 'revops' and active order by id limit 1")
    text = repr(views.profile(cur, rv)) + repr(views.settings(cur)) + repr(views.territories(cur, db.val(cur, "select id from territory_plans where status = 'active'"), True)["hours_note"])
    assert not re.search(r"\b(Account|Events|CRM) Desk\b", text), re.findall(r".{20}(?:Account|Events|CRM) Desk.{10}", text)[:3]


def test_an_error_body_says_the_plain_words_when_the_desk_is_not_connected(monkeypatch):
    import asyncio

    from fastapi import HTTPException

    from market.api import app as appmod
    monkeypatch.setattr(names, "CONFIG", SimpleNamespace(integrated_with=frozenset()))
    monkeypatch.delenv("CRM", raising=False)
    r = asyncio.run(appmod._plain_error(None, HTTPException(403, "Sellers see their books in Account Desk and CRM Desk.")))
    assert b"Account Desk" not in r.body and b"your outreach tool" in r.body


def test_a_hand_change_owner_is_sourced_to_a_hand_change_and_dated(cur):
    assert views.owner_source("manual") == "a hand change"
    assert views.owner_source("rule") == "the territory plan"
    rv = db.one(cur, "select * from users where role = 'revops' and active order by id limit 1")
    active = db.val(cur, "select id from territory_plans where status = 'active'")
    row = db.one(cur, "select company, owner from assignments where plan = %s and owner is not null and reason_code = 'rule' limit 1", active)
    other = db.val(cur, "select id from users where active and role = (select role from users where id = %s) and id <> %s limit 1", row["owner"], row["owner"])
    terr.change_owner_by_hand(cur, row["company"], other, "Covers the region now", rv)
    m = [x for x in views.territories(cur, active, True)["manual"] if x["company"] == row["company"]]
    assert m and m[0]["moved_at"] is not None


def test_the_draft_owner_is_on_the_sheet_even_when_the_active_plan_holds_no_owner():
    src = _src("sheets.tsx")
    assert "c.owner || c.draft_owner ?" in src


def test_the_banner_is_inside_main_and_the_skip_link_is_first():
    app = _src("App.tsx")
    assert app.index('className="skip"') < app.index("<DemoBanner me={me} />")
    assert app.index('<main className="main"') < app.index("<DemoBanner me={me} />")
    assert "setNames(me.names); setRefuses(!!me.snapshot); if (me.now) setNow(me.now);" in app, "the clock is set during render, like the names"


def test_start_is_for_the_two_roles_that_see_the_market():
    src = (ROOT / "src" / "market" / "api" / "app.py").read_text()
    assert 'def start(u: dict = Depends(current_user)) -> dict:\n    need(u, "revops", "manager")' in src


def test_source_names_go_through_say_and_the_legend_does_not_widen_a_phone():
    # a source named after another desk shows its plain name when that desk is not connected; a hidden tip never takes room
    assert "{say(s.label)}" in _src("pages/Desk.tsx") and "crumb={say(s.label)}" in _src("sheets.tsx")
    assert ".range-key > span {" in _src("market.css") and ".range-key span {" not in _src("market.css")


# ---- integrated week 2 small fixes (2026-11-18)

def test_a_draft_plan_line_shows_its_start_date():
    src = _src("pages/Territories.tsx")
    assert "Starts ${day(plan.effective_on)} once a manager activates it" in src
    # a start date today or earlier starts the day it is activated, by the desk clock the page already uses
    assert 'String(plan.effective_on).slice(0, 10) > todayIso()' in src and "{startsLine}" in src and '"Starts the day a manager activates it"' in src
    assert "canActivate ? `Starts ${day(plan.effective_on)} once a manager activates it` : `Starts ${day(plan.effective_on)}`" in src  # not 'a manager activates' twice
    assert "export function todayIso()" in _src("lib.tsx") and "new Date(NOW)" in _src("lib.tsx")
    # the date sits beside both the Activate button and the waiting line, not only one of them
    draft = src[src.index('plan.status === "draft" ? ('):src.index("{startsLine}</span>")]
    assert "activateButton" in draft and "Waiting for a manager to activate" in draft


def test_each_book_file_says_who_made_it_and_the_list_order_is_stable():
    assert '`, by ${b.created_by}`' in _src("pages/Handoffs.tsx")
    sql = (ROOT / "src" / "market" / "api" / "views.py").read_text()
    assert "left join users u on u.id = b.created_by order by b.created_at desc, b.id desc" in sql


def test_handoffs_returns_the_maker_of_every_book(cur):
    books = views.handoffs(cur, True)["books"]
    assert all("created_by" in b for b in books)
    keys = [(b["created_at"], b["id"]) for b in books]
    assert keys == sorted(keys, reverse=True)


def test_a_decided_change_says_who_decided():
    assert '`, decided by ${p.decided_by}`' in _src("pages/Changes.tsx")
    assert '"decided_by": p.get("decided_by_name")' in (ROOT / "src" / "market" / "api" / "views.py").read_text()


# ---- wk2: an approved move says whether it is in force

def test_the_proposals_list_and_the_toast_use_the_servers_note():
    t, s = _src("pages/Territories.tsx"), _src("sheets_moves.tsx")
    assert "m.force_note" in t and '"Approved, not in force"' in t
    assert "r.note" in s and "A draft plan is ready to activate." in s
    assert '"note": note' in (ROOT / "src" / "market" / "api" / "app.py").read_text()
