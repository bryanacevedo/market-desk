"""Three product features (decisions 63 to 65): a new draft starts from the open draft, the Evidence page can run the deals
evidence again, and RevOps changes one account's owner by hand from the account sheet. Backend reads and endpoints run on the
demo database in a rolled-back transaction; the web wiring checks are plain reads of the source (the web app has no browser
test), next to the typecheck and the screen-copy gate."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from market import db, profiles, proposals, territories
from market.api import views

WEB = Path(__file__).resolve().parents[1] / "web" / "src"


@pytest.fixture
def who(cur):
    return {u["name"].split()[0]: u for u in db.all(cur, "select * from users")}


def _revops(cur):
    return db.one(cur, "select * from users where role = 'revops' and active order by id limit 1")


def _proposal(cur, key: str) -> int:
    """An open proposal that adds one exclude rule, so a draft's rules show whether it carried the earlier draft."""
    rule = {"key": key, "field": "employees", "op": "between", "value": [1, 2], "reason": "test"}
    return db.val(cur, """insert into change_proposals (kind, evidence, proposed_rules_diff, text_status, status, created_at, key)
                          values ('add_exclude', '{}', %s, 'withheld', 'open', app_now(), %s) returning id""",
                  db.J({"add": {"excludes": [rule]}}), f"test:{key}")


def _no_open_draft(cur):
    ids = [r["id"] for r in db.all(cur, "select id from icp_versions where status = 'draft'")]
    db.run(cur, "update change_proposals set draft_version = null where draft_version = any(%s)", ids)
    db.run(cur, "delete from icp_versions where id = any(%s)", ids)


def _has(rules: dict, key: str) -> bool:
    return any(r["key"] == key for r in rules["excludes"])


# ---- 63: a new draft starts from the open draft

def test_with_no_open_draft_a_new_draft_starts_from_the_published_version(cur, who):
    _no_open_draft(cur)
    pub = profiles.published(cur)
    vid = proposals.make_draft(cur, [_proposal(cur, "only_extra")], _revops(cur))
    d = db.one(cur, "select * from icp_versions where id = %s", vid)
    assert _has(d["rules"], "only_extra") and len(d["rules"]["excludes"]) == len(pub["rules"]["excludes"]) + 1
    assert "starts from" not in d["note"] and d["note"] == "From proposals"


def test_a_second_draft_carries_the_first_drafts_rules_and_says_so(cur, who):
    _no_open_draft(cur)
    first = proposals.make_draft(cur, [_proposal(cur, "first_extra")], _revops(cur))
    n_first = db.val(cur, "select number from icp_versions where id = %s", first)
    assert proposals.open_draft(cur)["id"] == first
    second = proposals.make_draft(cur, [_proposal(cur, "second_extra")], _revops(cur), note="Second try")
    d = db.one(cur, "select * from icp_versions where id = %s", second)
    assert _has(d["rules"], "first_extra") and _has(d["rules"], "second_extra")
    assert d["note"] == f"Second try. {proposals.started_from_note(n_first)}"
    assert f"open draft v{n_first}" in d["note"]
    # the version sheet shows the note, and compares the draft with the published version, so both rules read as added
    v = views.version(cur, second, who["Elena"])
    assert v["note"] == d["note"] and v["diff_base"] == profiles.published(cur)["number"]
    assert {x["change"] for x in v["diff"]} == {"Added"} and len(v["diff"]) == 2


def test_the_warning_names_only_the_drafts_whose_changes_this_draft_lacks(cur, who):
    _no_open_draft(cur)
    first = proposals.make_draft(cur, [_proposal(cur, "first_extra")], _revops(cur))
    second = proposals.make_draft(cur, [_proposal(cur, "second_extra")], _revops(cur))
    n_first, n_second = (db.val(cur, "select number from icp_versions where id = %s", i) for i in (first, second))
    # the second carries the first, so it has nothing to be warned about; the first lacks the second's rule
    assert views.version(cur, second, who["Elena"])["other_drafts"] == []
    assert views.version(cur, first, who["Elena"])["other_drafts"] == [n_second]
    assert views.changes(cur)["open_drafts"] == [n_first, n_second] and views.changes(cur)["new_draft_starts_from"] == n_second


def test_the_changes_page_says_which_draft_a_new_one_starts_from(cur):
    _no_open_draft(cur)
    assert views.changes(cur)["new_draft_starts_from"] is None
    vid = proposals.make_draft(cur, [_proposal(cur, "x_extra")], _revops(cur))
    assert views.changes(cur)["new_draft_starts_from"] == db.val(cur, "select number from icp_versions where id = %s", vid)


def test_the_draft_endpoint_sends_the_note_and_the_page_shows_it():
    src = (Path(__file__).resolve().parents[1] / "src" / "market" / "api" / "app.py").read_text()
    assert '"started_from"' in src and "proposals.started_from_note" in src
    page = (WEB / "pages" / "Changes.tsx").read_text()
    assert "toast(r.note" in page and "new_draft_starts_from" in page
    assert "not from an open draft" not in page


# ---- 64: Run again on the Evidence page

@pytest.fixture(scope="module")
def client(demo):
    from market.api.app import app
    with TestClient(app) as c:
        yield c


def test_only_revops_runs_the_evidence_again(client, demo):
    with db.tx() as cur:
        manager = db.val(cur, "select id from users where role = 'manager' and active order by id limit 1")
    r = client.post("/api/evidence/run", headers={"X-Acting-As": str(manager), "Content-Type": "application/json"})
    assert r.status_code == 403


def test_the_run_limit_says_what_it_is():
    from market.api.app import rate_limit
    rate_limit(None, limit=1, window=60.0, key="test-run-limit", message="Six an hour.")  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as e:
        rate_limit(None, limit=1, window=60.0, key="test-run-limit", message="Six an hour.")  # type: ignore[arg-type]
    assert e.value.status_code == 429 and e.value.detail == "Six an hour."


def test_the_run_gives_the_page_a_new_run_date(cur):
    from market import evidence
    before = db.val(cur, "select max(id) from analysis_runs")
    rid = evidence.run(cur)
    assert rid > before and views.evidence(cur, True)["run"]["id"] == rid and views.evidence(cur, True)["run"]["ran_at"]


def test_the_evidence_page_wires_run_again_to_the_endpoint():
    page = (WEB / "pages" / "Evidence.tsx").read_text()
    assert 'role === "revops"' in page and "Run again" in page and "Last run" in page
    assert '"/api/evidence/run", { method: "POST" }' in page            # no confirm: a run is cheap (decision 64)
    assert "disabled={busy}" in page and '"Running"' in page and "The evidence run finished." in page   # running, then finished
    assert "useBusy" in page and "e.message" in (WEB / "lib.tsx").read_text()                          # an error is shown as its own words


# ---- 65: a hand owner change for one account

def _ae_account(cur):
    active = db.val(cur, "select id from territory_plans where status = 'active'")
    return db.one(cur, """select a.company, a.owner from assignments a join users u on u.id = a.owner join companies c on c.id = a.company
                          where a.plan = %s and u.role = 'ae' and not c.sole_trader order by a.company limit 1""", active)


def test_revops_sees_who_holds_the_account_and_who_can_take_the_same_seat(cur, who):
    a = _ae_account(cur)
    h = views.company(cur, a["company"], _revops(cur))["hand_owner"]
    assert h["can"] and h["seat"] == "AE" and h["now"]["id"] == a["owner"]
    ids = [p["id"] for p in h["choices"]]
    assert a["owner"] not in ids and ids
    assert {db.val(cur, "select role from users where id = %s", i) for i in ids} == {"ae"}
    assert all(db.val(cur, "select active from users where id = %s", i) for i in ids)


def test_nobody_else_is_offered_the_form(cur, who):
    a = _ae_account(cur)
    assert views.company(cur, a["company"], who["Elena"])["hand_owner"] is None


def test_an_account_outside_the_plan_in_effect_says_so(cur):
    active = db.val(cur, "select id from territory_plans where status = 'active'")
    c = db.val(cur, "select id from companies c where not sole_trader and not exists (select 1 from assignments a where a.plan = %s and a.company = c.id) limit 1", active)
    if c is None:
        pytest.skip("every account is in the plan")
    assert views.company(cur, c, _revops(cur))["hand_owner"] == {"can": False, "why": "This account is not in the plan in effect."}


def test_the_change_needs_a_reason_the_same_seat_and_a_different_person(cur, who):
    a = _ae_account(cur)
    other = views.company(cur, a["company"], _revops(cur))["hand_owner"]["choices"][0]["id"]
    with pytest.raises(ValueError, match="note"):
        territories.change_owner_by_hand(cur, a["company"], other, " ", _revops(cur))
    with pytest.raises(ValueError, match="already holds"):
        territories.change_owner_by_hand(cur, a["company"], a["owner"], "Same person", _revops(cur))
    sdr = db.val(cur, "select id from users where role = 'sdr' and active order by id limit 1")
    with pytest.raises(ValueError, match="seat"):
        territories.change_owner_by_hand(cur, a["company"], sdr, "Wrong seat", _revops(cur))
    with pytest.raises(PermissionError):
        territories.change_owner_by_hand(cur, a["company"], other, "Not RevOps", who["Elena"])


def test_the_result_is_written_to_the_audit_and_shown_on_the_sheet(cur, who):
    rv = _revops(cur)
    a = _ae_account(cur)
    other = views.company(cur, a["company"], rv)["hand_owner"]["choices"][0]
    territories.change_owner_by_hand(cur, a["company"], other["id"], "Took over the relationship", rv)
    row = db.one(cur, "select * from audit_log where action = 'owner_changed_by_hand' and object_id = %s order by id desc limit 1", str(a["company"]))
    assert row["actor"] == rv["name"] and row["detail"]["note"] == "Took over the relationship"
    assert row["detail"]["to"] == other["id"] and row["detail"]["from"] == a["owner"]
    for viewer in (rv, who["Elena"]):  # RevOps and a manager both see the result under Owner
        c = views.company(cur, a["company"], viewer)
        assert c["owner"]["id"] == other["id"] and c["owner"]["reason"] == "manual" and c["owner"]["note"] == "Took over the relationship"
        top = c["owner_changes"][0]
        assert top["to"] == other["name"] and top["who"] == rv["name"] and top["note"] == "Took over the relationship" and top["was"]
    # and now the person who held it is a choice, and the new holder is not
    ids = [p["id"] for p in views.company(cur, a["company"], rv)["hand_owner"]["choices"]]
    assert a["owner"] in ids and other["id"] not in ids


def test_the_endpoint_refuses_a_manager(client, demo):
    with db.tx() as cur:
        a = _ae_account(cur)
        manager = db.val(cur, "select id from users where role = 'manager' and active order by id limit 1")
        other = db.val(cur, "select id from users where role = 'ae' and active and id <> %s limit 1", a["owner"])
    r = client.post(f"/api/companies/{a['company']}/owner", headers={"X-Acting-As": str(manager)}, json={"to": other, "note": "Because"})
    assert r.status_code == 403
    r = client.post(f"/api/companies/{a['company']}/owner", headers={"X-Acting-As": str(manager)}, json={"to": other, "note": ""})
    assert r.status_code == 422


def test_the_account_sheet_wires_the_owner_form_to_the_endpoint():
    src = (WEB / "sheets.tsx").read_text()
    assert "function OwnerForm" in src and "<OwnerForm company={c} />" in src
    assert "/owner`" in src and "h.choices" in src and "h.now" in src and "owner_changes" in src
    assert "reason.trim().length >= 3" in src and "disabled={busy || !ok}" in src
