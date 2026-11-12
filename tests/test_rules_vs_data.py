"""Review gate 2: the demo database breaks none of the product's rules (scripts/audit_rules.py)."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _audit():
    spec = importlib.util.spec_from_file_location("audit_rules", Path(__file__).resolve().parents[1] / "scripts" / "audit_rules.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_demo_breaks_no_rule(cur):
    res = _audit().run(cur)
    bad = [r for r in res if r["breaks"]]
    assert len(res) >= 30
    assert not bad, bad


def test_audit_catches_a_broken_rule(cur):
    """The audit is not vacuous: a planted break is found."""
    from market import db
    db.run(cur, "update customers set churned_on = started_on where company = (select min(company) from customers)")
    res = {r["rule"]: r["breaks"] for r in _audit().run(cur)}
    assert res["Churn comes after the start"] == 1
