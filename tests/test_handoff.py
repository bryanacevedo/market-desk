"""The handoffs. Account Desk equivalence: a copy of Account Desk's fit formula (its src/outbound/scoring.py `fit`, as of
2026-11-11, pasted here, not imported across repos) scores every exported company from the exported ICP; the tier must
equal Market Desk's. Events Desk: every heading of its sample ICP document is present, every number equals the
profile's, and each example's stated tier equals the mapping of its score."""
from __future__ import annotations

import csv
import io
import json
import re

from market import catalog as C
from market import db, handoff

# ---------------------------------------------------------------- Account Desk's fit, copied verbatim (minus intent)

def _ad_matches(rule, account):
    value = account.get(rule["field"])
    op, target = rule["op"], rule["value"]
    if value is None:
        return False
    if op == "in":
        return value in target
    if op == "between":
        return target[0] <= value <= target[1]
    if op == "has_any":
        return bool(set(value or []) & set(target))
    if op == "has_none":
        return not (set(value or []) & set(target))
    raise ValueError(f"unknown ICP operator {op}")


AD_MIN_KNOWN = 0.6


def _ad_known(rule, account):
    v = account.get(rule["field"])
    return v is not None and v != [] and v != ""


def ad_fit(rules, account):
    if account.get("lifecycle") in ("customer", "open_opp", "competitor"):
        return {"score": 0, "tier": "X"}
    for ex in rules.get("excludes", []):
        if _ad_matches(ex, account):
            return {"score": 0, "tier": "X"}
    total = sum(f["weight"] for f in rules["factors"] if f["weight"] > 0) or 1
    known = [f for f in rules["factors"] if _ad_known(f, account)]
    known_total = sum(f["weight"] for f in known if f["weight"] > 0) or 1
    got = 0.0
    for f in rules["factors"]:
        if f not in known:
            continue
        if _ad_matches(f, account):
            got += 100.0 * f["weight"] / known_total
    if known_total / total < AD_MIN_KNOWN:
        return {"score": 0, "tier": "C"}
    for p in rules.get("penalties", []):
        if _ad_matches(p, account):
            got -= p["weight"]
    score = int(round(max(0.0, min(100.0, got))))
    tiers = rules.get("tiers", {"A": 70, "B": 50})
    return {"score": score, "tier": "A" if score >= tiers["A"] else "B" if score >= tiers["B"] else "C"}


# Account Desk's setup_desk.region_of
NORTH_AMERICA = {"US", "CA", "MX"}
EUROPE = {"GB", "IE", "DE", "FR", "NL", "BE", "LU", "ES", "PT", "IT", "AT", "CH", "SE", "NO", "DK", "FI", "IS", "PL", "CZ",
          "SK", "HU", "RO", "BG", "GR", "HR", "SI", "EE", "LV", "LT", "CY", "MT"}


def region_of(c):
    c = (c or "").upper()
    return "North America" if c in NORTH_AMERICA else "Europe" if c in EUROPE else None


def _files(cur, book):
    return {r["path"]: bytes(r["bytes"]) for r in db.all(cur, "select path, bytes from target_book_files where book = %s", book)}


def test_account_desk_book_shape_and_equivalence(cur):
    book = db.val(cur, "select max(id) from target_books where destination = 'account_desk'")
    files = _files(cur, book)
    rows = list(csv.DictReader(io.StringIO(files["accounts.csv"].decode())))
    assert list(rows[0].keys()) == C.AD_COLUMNS
    icp = json.loads(files["icp.json"])
    assert set(icp) == {"factors", "penalties", "excludes", "tiers"}
    dropped = db.val(cur, "select dropped_rules from target_books where id = %s", book)
    assert dropped == []  # the published v3 carries nothing Account Desk cannot read
    ours = {r["primary_domain"]: r["tier"] for r in db.all(cur, """select c.primary_domain, r.tier from target_book_rows r
            join companies c on c.id = r.company where r.book = %s""", book)}
    checked = 0
    for r in rows:
        if not (r["industry"] and r["employees"] and r["revenue_band"] and r["tech"]):
            continue  # every exported field known, as the spec requires for the comparison
        acct = {"industry": r["industry"], "employees": int(r["employees"]), "region": region_of(r["country"]),
                "revenue_band": r["revenue_band"], "tech": r["tech"].split(";"), "lifecycle": r["lifecycle"]}
        assert ad_fit(icp, acct)["tier"] == ours[r["domain"]], r["domain"]
        checked += 1
    assert checked > 300


def test_draft_preview_lists_usage_as_dropped(cur):
    v4 = db.val(cur, "select id from icp_versions where number = 4")
    p = handoff.preview(cur, v4)
    assert [d["key"] for d in p["dropped_rules"]] == ["usage_pricing"]
    assert all(f["field"] in C.AD_FIELDS for k in ("factors", "penalties") for f in p["icp"][k])


def test_book_never_carries_a_model_read_value_or_a_restricted_source(cur):
    book = db.val(cur, "select max(id) from target_books where destination = 'account_desk'")
    rows = list(csv.DictReader(io.StringIO(_files(cur, book)["accounts.csv"].decode())))
    by_domain = {r["domain"]: r for r in rows}
    model = db.all(cur, """select c.primary_domain from field_values f join companies c on c.id = f.company
                           where f.source = 'model' and f.field = 'industry'""")
    restricted = db.all(cur, """select c.primary_domain from field_values f join companies c on c.id = f.company
                                where f.source = 'funding_db' and f.field = 'revenue_band'""")
    assert any(m["primary_domain"] in by_domain for m in restricted)
    for m in model:
        if m["primary_domain"] in by_domain:
            assert by_domain[m["primary_domain"]]["industry"] == ""
    for m in restricted:
        if m["primary_domain"] in by_domain:
            assert by_domain[m["primary_domain"]]["revenue_band"] == ""


def test_events_desk_document(cur):
    book = db.val(cur, "select max(id) from target_books where destination = 'events_desk'")
    md = _files(cur, book)["icp.md"].decode()
    for h in ["Seller:", "Owner:", "Last reviewed:", "## The short version", "## Size", "## Where we win",
              "## How we tier a company", "## Who we talk to", "## Kinds of company we see", "## Who we skip",
              "## Companies we know", "## Looks right, is not"]:
        assert h in md, h
    rules = db.val(cur, "select rules from icp_versions where id = (select icp_version from target_books where id = %s)", book)
    lo, hi = next(f["value"] for f in rules["factors"] if f["field"] == "employees")
    assert f"{lo:,} to {hi:,} employees" in md
    for name, tier in re.findall(r"^- (.+?): tier (\d)\.", md, re.M):
        cid = db.val(cur, "select id from companies where name = %s", name)
        t = db.val(cur, "select tier from account_fit where company = %s and icp_version = (select icp_version from target_books where id = %s)", cid, book)
        assert {"A": "1", "B": "2"}.get(t, "3") == tier, name
    assert "" + chr(0x2014) + "" not in md and "" + chr(0x2013) + "" not in md


def test_held_back_member_refused_by_the_database(cur):
    import psycopg
    import pytest
    t = db.val(cur, "select id from segment_tests where status = 'running'")
    held = db.val(cur, "select company from segment_test_members where test = %s and grp = 'held_back' limit 1", t)
    book = db.val(cur, "select max(id) from target_books where destination = 'account_desk'")
    with pytest.raises(psycopg.errors.RaiseException):
        with cur.connection.transaction():
            db.run(cur, "insert into target_book_rows (book, company, tier, segment) values (%s,%s,'A','data_infra')", book, held)


def test_book_diff_between_versions(cur):
    b2 = db.one(cur, "select * from target_books where destination = 'account_desk' order by version desc limit 1")
    assert b2["diff"]["previous"] is not None and b2["diff"]["added"] > 0
