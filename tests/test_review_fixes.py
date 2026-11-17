"""Fixes from the S4 persona review (2026-11-17): the version sheet compares a draft with the version it was built on and
names the other open drafts, What changes separates accounts that change hands from accounts that gain an owner, Handoffs
says what the next file will use, Sources carries the stale-source alert and the run time. The web wiring checks are
plain reads of the source: the web app has no browser test, so these keep a fix from being deleted by accident."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from market import db, monitors, profiles, territories
from market.api import views

WEB = Path(__file__).resolve().parents[1] / "web" / "src"


@pytest.fixture
def who(cur):
    return {u["name"].split()[0]: u for u in db.all(cur, "select * from users")}


def _extra_exclude(rules: dict, key: str) -> dict:
    out = copy.deepcopy(rules)
    out["excludes"] = out.get("excludes", []) + [{"key": key, "field": "employees", "op": "between", "value": [1, 2], "reason": "test"}]
    return out


def test_a_draft_is_compared_with_the_published_version_not_the_number_before(cur, who):
    pub = profiles.published(cur)
    first = profiles.create_draft(cur, author=who["Sam"]["id"], rules=_extra_exclude(pub["rules"], "first_extra"), note="first")
    second = profiles.create_draft(cur, author=who["Sam"]["id"], rules=_extra_exclude(pub["rules"], "second_extra"), note="second")
    v = views.version(cur, second, who["Elena"])
    assert v["diff_base"] == pub["number"]
    assert [(d["change"], d["rule"]) for d in v["diff"]] == [("Added", d["rule"]) for d in v["diff"]]
    assert len(v["diff"]) == 1 and v["diff"][0]["change"] == "Added"
    assert not any(d["change"] == "Removed" for d in v["diff"])  # the old base (the draft before) made the first draft's rule read as removed
    n_first = db.val(cur, "select number from icp_versions where id = %s", first)
    assert v["other_drafts"] == [n for n in v["other_drafts"] if n != v["number"]] and n_first in v["other_drafts"]


def test_a_published_version_is_compared_with_the_one_it_replaced(cur, who):
    pub = profiles.published(cur)
    assert pub["replaced"]
    prior = db.one(cur, "select number from icp_versions where id = %s", pub["replaced"])
    v = views.version(cur, pub["id"], who["Elena"])
    assert v["diff_base"] == prior["number"] and v["other_drafts"] == []


def test_what_changes_separates_hands_changed_from_owners_gained_or_lost(cur, who):
    act = db.one(cur, "select * from territory_plans where status = 'active'")
    draft = db.val(cur, "select id from territory_plans where status = 'draft' order by id limit 1")
    base = territories.what_changes(cur, draft)
    assert base["changes"] == base["owner_changes"] + base["newly_assigned"] + base["newly_unassigned"]
    # an account that has an owner in the active plan and none in the draft, and one the other way round
    rows = db.all(cur, """select a.company, a.owner from assignments a join assignments d on d.company = a.company and d.plan = %s
                          where a.plan = %s and a.owner is not null and d.owner is not distinct from a.owner order by a.company limit 2""",
                  draft, act["id"])
    db.run(cur, "update assignments set owner = null where plan = %s and company = %s", draft, rows[0]["company"])
    db.run(cur, "update assignments set owner = null where plan = %s and company = %s", act["id"], rows[1]["company"])
    now = territories.what_changes(cur, draft)
    assert now["newly_unassigned"] == base["newly_unassigned"] + 1
    assert now["newly_assigned"] == base["newly_assigned"] + 1
    assert now["owner_changes"] == base["owner_changes"]
    assert now["changes"] == base["changes"] + 2
    pre = territories.activation_preview(cur, draft, who["Elena"])
    assert pre["changes_hands"] == now["owner_changes"] and pre["owner_changes"] == now["changes"]


def test_changes_lists_the_open_drafts_a_new_draft_would_not_include(cur):
    assert views.changes(cur)["open_drafts"] == [r["number"] for r in db.all(cur, "select number from icp_versions where status = 'draft' order by number")]


def test_the_plan_view_sends_the_split(cur, who):
    draft = db.val(cur, "select id from territory_plans where status = 'draft' order by id limit 1")
    ch = views.territories(cur, draft, True)["changes"]
    assert {"changes", "owner_changes", "newly_assigned", "newly_unassigned"} <= set(ch)
    assert ch["changes"] == ch["owner_changes"] + ch["newly_assigned"] + ch["newly_unassigned"]


def test_handoffs_say_which_profile_and_plan_the_next_file_uses(cur):
    h = views.handoffs(cur, True)
    assert h["next"]["profile"] == profiles.published(cur)["number"]
    assert h["next"]["plan"] == db.val(cur, "select name from territory_plans where status = 'active'")


def test_sources_carry_the_stale_alert_and_each_run_has_a_finish_time(cur):
    db.run(cur, "update source_runs set finished_at = finished_at - interval '30 days', started_at = started_at - interval '30 days' where source = 'technographics'")
    assert "technographics" in monitors.stale_sources(cur)
    s = views.sources(cur, True)
    mine = [a for a in s["alerts"] if a["object_id"] == "technographics"]
    assert mine and mine[0]["title"].endswith("missed its run") and mine[0]["body"].startswith("Last finished ")
    runs = views.source(cur, "technographics", True)["runs"]
    assert runs and all("finished_at" in r for r in runs)


@pytest.mark.parametrize("path,needle", [
    ("pages/Desk.tsx", "data.alerts"),                       # Sources shows the stale-source alert
    ("sheets.tsx", "dayTime(r.finished_at"),                 # and the time the run finished
    ("pages/Evidence.tsx", "Last run"),                      # Evidence shows its run date
    ("pages/Profile.tsx", "Other moves"),                    # What moves adds up to its total
    ("pages/Handoffs.tsx", "data.next"),                     # Handoffs names the profile and plan
    ("pages/Territories.tsx", "owner_changes"),              # What changes shows the split
    ("pages/Changes.tsx", "open_drafts"),                    # Changes warns that a new draft starts from the published version
    ("sheets.tsx", "other_drafts"),                          # the version sheet warns of a second open draft
    ("App.tsx", 'href="#main"'),                             # skip link
])
def test_the_web_app_keeps_each_review_fix(path, needle):
    assert needle in (WEB / path).read_text()
