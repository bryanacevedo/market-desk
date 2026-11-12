"""Scenario coverage as a test (review gate 3): every scenario docs/SCENARIOS.md promises exists in the demo database.
Writes docs/SCENARIO-COVERAGE.md. A missing scenario fails the build."""
from __future__ import annotations

from pathlib import Path

from market import db, fit, tests_seg

DOC = Path(__file__).resolve().parents[1] / "docs" / "SCENARIO-COVERAGE.md"


def _finding(cur, trait: str, value: str) -> dict | None:
    run = db.val(cur, "select max(id) from analysis_runs")
    return db.one(cur, "select * from findings where run = %s and trait = %s and value = %s", run, trait, db.J(value))


def scenarios(cur) -> list[tuple[str, str, str, int, bool]]:
    """(key, scenario, where it shows, how many, holds)."""
    out = []
    p1 = _finding(cur, "pricing_model", "usage")
    p1_prop = db.val(cur, "select count(*) from change_proposals where key = 'add_rule:pricing_model:usage'")
    v4 = db.val(cur, "select id from icp_versions where number = 4")
    from market import handoff
    dropped = handoff.preview(cur, v4)["dropped_rules"]
    out.append(("P1", "Usage pricing is Clearly higher, proposed as a rule, and dropped from the Account Desk export",
                "Evidence, Changes, Handoffs", p1["opps"] if p1 else 0,
                bool(p1 and p1["verdict"] == "clear_higher" and p1_prop and any(d["key"] == "usage_pricing" for d in dropped))))
    p2 = _finding(cur, "size_band", "2,000 to 4,999")
    others = db.val(cur, "select avg(cycle_median_days) from findings where run = %s and trait = 'size_band' and value_label in ('120 to 499','500 to 1,999')",
                    db.val(cur, "select max(id) from analysis_runs"))
    out.append(("P2", "2,000 to 4,999 employees is Clearly lower with a longer won-deal cycle, and a penalty is proposed",
                "Evidence, Changes", p2["opps"] if p2 else 0,
                bool(p2 and p2["verdict"] == "clear_lower" and p2["cycle_median_days"] and p2["cycle_median_days"] > 1.3 * float(others)
                     and db.val(cur, "select count(*) from change_proposals where kind = 'penalty' and key like 'penalty:size_band:2,000%%'"))))
    p3 = _finding(cur, "industry", "Healthcare software")
    top = (p3["top_loss_codes"] or [{}])[0] if p3 else {}
    lost = (p3["opps"] - p3["wins"]) if p3 else 0
    out.append(("P3", "Healthcare software is Clearly lower, compliance above half its losses, an exclude proposed",
                "Evidence, Finding sheet, Changes", p3["opps"] if p3 else 0,
                bool(p3 and p3["verdict"] == "clear_lower" and top.get("code") == "compliance" and top["n"] / lost > 0.5
                     and db.val(cur, "select count(*) from change_proposals where kind = 'add_exclude' and key like '%%Healthcare%%'"))))
    p4 = _finding(cur, "tech", "Salesforce")
    out.append(("P4", "Salesforce is Explained by size", "Evidence", p4["opps"] if p4 else 0,
                bool(p4 and p4["verdict"] == "explained_by_size")))
    p5 = _finding(cur, "country", "BR")
    br_ind = db.all(cur, """select distinct d.snapshot->>'industry' as i from deals d join companies c on c.id = d.company
                            where c.country = 'BR' and d.kind = 'new'""")
    out.append(("P5", "Brazil is Too few to tell: 9 opportunities, 5 won, all marketplaces, and no proposal names it",
                "Evidence, Finding sheet", p5["opps"] if p5 else 0,
                bool(p5 and p5["verdict"] == "too_few" and p5["opps"] == 9 and p5["wins"] == 5 and [r["i"] for r in br_ind] == ["Marketplaces"]
                     and not db.val(cur, "select count(*) from change_proposals where key like '%%BR%%'"))))
    dach = db.one(cur, "select * from segment_sizing where run = (select max(id) from sizing_runs) and dimension = 'region_group' and key = 'DACH'")
    out.append(("P6", "DACH's SAM is far below its TAM (high end under half)", "Market, by region",
                dach["universe_count"], bool(dach and dach["sam_high"] < 0.5 * dach["tam_high"])))
    t1 = db.val(cur, "select id from segment_tests where segment = 'fintech_core'")
    r1 = tests_seg.read(cur, t1)
    out.append(("P7a", "The fintech 120 to 499 test reads a clear lift and a segment_expand proposal exists", "Tests, Changes",
                r1["treated"]["accounts"] + r1["holdout"]["accounts"],
                bool(r1["clear"] and r1["interval"][0] > 0 and db.val(cur, "select count(*) from change_proposals where kind = 'segment_expand'"))))
    t2 = db.val(cur, "select id from segment_tests where segment = 'devtools'")
    r2 = tests_seg.read(cur, t2)
    out.append(("P7b", "The developer tools test reads no clear difference", "Tests",
                r2["treated"]["accounts"] + r2["holdout"]["accounts"], bool(r2["enough"] and not r2["clear"])))
    clear_p8 = db.val(cur, """select count(*) from findings where run = (select max(id) from analysis_runs)
                              and trait in ('hq_city','founded') and verdict in ('clear_higher','clear_lower')""")
    tested = db.val(cur, """select count(*) from findings where run = (select max(id) from analysis_runs) and trait in ('hq_city','founded')
                            and opps >= 30""")
    out.append(("P8", "No HQ city or founding period finding is clear", "Evidence", tested, clear_p8 == 0 and tested >= 10))
    pub = db.val(cur, "select id from icp_versions where status = 'published'")
    moves = fit.what_moves(cur, v4, pub)
    out.append(("S1", "Draft v4 has companies that move tier against v3", "Profile", moves["total"], moves["total"] > 0))
    # The draft for next quarter: Nadia's ramp leaves the team short, and someone is over their hours.
    draft = db.val(cur, "select id from territory_plans where status = 'draft'")
    over = db.val(cur, "select count(*) from capacity_snapshots s where s.plan = %s and s.hours_required > s.hours_available + 0.05", draft)
    from market import territories
    gap = territories.hiring_gap(cur, draft)
    out.append(("S2", "A plan with someone over capacity and a hiring gap above zero", "Territories, Capacity", over,
                over > 0 and gap["accounts"] > 0))
    manual = db.val(cur, "select count(*) from assignments where reason_code = 'manual' and length(note) > 3")
    out.append(("S3", "A manual move with a note", "Territories, Plan move sheet", manual, manual > 0))
    refused = db.val(cur, "select count(*) from audit_log where action = 'book_row_refused'")
    out.append(("S4", "A held-back company refused from an Account Desk book", "Tests, audit log", refused, refused > 0))
    nj = db.val(cur, "select count(*) from account_fit where icp_version = %s and not judged", pub)
    out.append(("S5", "A not-judged company", "Accounts, Company sheet", nj, nj > 0))
    na = db.val(cur, "select count(*) from account_fit where icp_version = %s and jsonb_array_length(breakdown->'not_applied') > 0", pub)
    out.append(("S6", "A model-read field that could not exclude a company", "Company sheet", na, na > 0))
    wh = db.val(cur, "select count(*) from segment_stories where status = 'withheld'")
    out.append(("S7", "A withheld segment story", "Market, Segment sheet", wh, wh > 0))
    dis = db.val(cur, "select count(*) from change_proposals where status = 'dismissed' and length(reason) > 3")
    out.append(("S8", "A proposal dismissed with a reason", "Changes", dis, dis > 0))
    t3 = db.val(cur, "select id from segment_tests where status = 'running'")
    r3 = tests_seg.read(cur, t3)
    out.append(("S9", "A test too small to read", "Tests", r3["still_needed"]["holdout"] + r3["still_needed"]["treated"],
                not r3["enough"]))
    stale = db.val(cur, "select count(*) from alerts where kind = 'source_stale' and resolved_at is null")
    out.append(("S10", "A source that missed its run", "Sources", stale, stale > 0))
    run_read = db.one(cur, "select count(*) filter (where status = 'running') as r, count(*) filter (where status = 'read') as d from segment_tests")
    out.append(("S11", "One running test and one read test", "Tests", run_read["r"] + run_read["d"], run_read["r"] >= 1 and run_read["d"] >= 1))
    v4row = db.one(cur, "select author, status from icp_versions where id = %s", v4)
    out.append(("S12", "Draft v4's author cannot publish it", "Profile", 1, v4row["status"] == "draft"))
    q1 = db.one(cur, "select author, status from territory_plans where status = 'draft'")
    out.append(("S13", "The Q1 draft plan cannot be activated by its author", "Territories", 1, q1 is not None))
    return out


def test_every_scenario_exists(cur):
    rows = scenarios(cur)
    lines = ["# Scenario coverage", "", "Generated by `tests/test_scenarios.py` from the demo database. Do not edit by hand.", "",
             "| Key | Scenario | Where it shows | How many | Holds |", "|---|---|---|---|---|"]
    for key, what, where, n, ok in rows:
        lines.append(f"| {key} | {what} | {where} | {n:,} | {'yes' if ok else 'NO'} |")
    DOC.write_text("\n".join(lines) + "\n")
    missing = [r[0] for r in rows if not r[4]]
    assert not missing, f"scenarios missing from the demo: {missing}"


def test_author_cannot_publish_and_planner_cannot_activate(cur, users):
    from market import profiles, territories
    v4 = db.val(cur, "select id from icp_versions where number = 4")
    q1 = db.val(cur, "select id from territory_plans where status = 'draft'")
    import pytest
    with pytest.raises(PermissionError):
        profiles.publish(cur, v4, users["Sam"])
    with pytest.raises(PermissionError):
        territories.activate(cur, q1, users["Sam"])
    territories.activate(cur, q1, users["Elena"])
    assert db.val(cur, "select status from territory_plans where id = %s", q1) == "active"
    profiles.publish(cur, v4, users["Elena"], rescore_now=True)
    assert db.val(cur, "select status from icp_versions where id = %s", v4) == "published"
