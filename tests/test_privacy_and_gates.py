"""Privacy at import, the AI gates with failing fixtures, fit reproduction and the shared world export."""
from __future__ import annotations

import random

from market import ai, db, fit
from market.privacy import redact
from market.sim import names as N


# Names from outside the generator's own lists, so the redaction cannot pass by agreeing with itself.
OUTSIDE = ["Kevin Smith", "Siobhan O'Brien", "Hugo van der Berg", "Marta-Louise Klein", "José Núñez", "Dmitri Volkov",
           "Priyanka Desai", "Chen Wei", "Fatima Zahra", "Liam Gallagher", "Ingrid Solberg", "Tomasz Nowak", "Aisha Bello",
           "Rafael Ortega", "Yuki Tanabe", "Grace Okoye", "Henrik Lund", "Camille Durand", "Mateo Rossi", "Nora Haddad",
           "Oliver Grant", "Zainab Musa", "Pedro Alves", "Sven Eriksson", "Leila Karimi"]


def test_fifty_planted_names_never_reach_the_database(cur):
    rng = random.Random(11)
    deal = db.val(cur, "select min(id) from deals")
    planted = []
    forms = [lambda f, r: f"Call with {f}, {r}. Said \"we bill by hand\".",
             lambda f, r: f"Spoke to {f.split()[0]} ({r}) about pricing.",
             lambda f, r: f"Follow-up with Mr. {f.split()[-1]} next week.",
             lambda f, r: f"Email {f.split()[0].lower()}@acme.example the deck, cc {f}.",
             lambda f, r: f"{f} called from +1 415 555 0134 to confirm.",
             lambda f, r: f"{f.lower()} agreed on terms.",
             lambda f, r: f"Note from {f.split()[0][0]}. {f.split()[-1]}: send the contract.",
             lambda f, r: f"see linkedin.com/in/{f.replace(' ', '').lower()} before the call",
             lambda f, r: f"Met {f} at the dinner.",
             lambda f, r: f"The CFO, {f.split()[0]}, wants a pilot."]
    for i in range(50):
        full = OUTSIDE[i % len(OUTSIDE)] if i % 2 else f"{rng.choice(N.FIRST)} {rng.choice(N.LAST)}"
        planted.append(full)
        role = rng.choice(["controller", "finance leader", "revenue operations"])
        raw = forms[i % len(forms)](full, role)
        contacts = [(full, role)] if i % 3 or i % 10 == 5 else []  # a third are not in the CRM list (lower case always is)
        db.run(cur, "insert into call_notes (deal, written_at, text_redacted) values (%s, app_now(), %s)", deal, redact(raw, contacts))
    texts = " ".join(r["text_redacted"] for r in db.all(cur, "select text_redacted from call_notes order by id desc limit 50")).lower()
    import re as _re
    words = set(_re.findall(r"[\w']+", texts))
    for full in planted:
        for part in full.replace("-", " ").split():
            if part.lower() not in ("van", "der"):
                assert part.lower() not in words, (full, part, texts)
    assert "@acme.example" not in texts and "555 0134" not in texts and "linkedin.com/in" not in texts


def test_redaction_keeps_business_words():
    t = 'chose Billform, cheaper on overages. HIPAA BAA required. Lumen Ledger demo for Finance, after Q1 close.'
    assert redact(t, []) == t


def test_classify_gate():
    desc = "Acme provides payment and lending infrastructure for online businesses. Customers pay per user per month."
    good = {"industry": "Fintech", "industry_quote": "provides payment and lending infrastructure for online businesses",
            "pricing_model": "seat", "pricing_quote": "Customers pay per user per month.", "instructions_in_text": False}
    assert ai.classify_gate(desc, good) == []
    assert ai.classify_gate(desc, {**good, "industry": "Banking"})
    assert ai.classify_gate(desc, {**good, "industry_quote": "provides payments"})
    assert ai.classify_gate(desc, {**good, "pricing_quote": None})
    assert ai.classify_gate(desc, {**good, "pricing_model": "unknown", "pricing_quote": None}) == []


def test_loss_gate_never_invents_a_competitor():
    out = ai.loss_gate("went with a homegrown tool", {"code": "competitor", "competitor": "Meterly"})
    assert out["competitor"] is None
    out = ai.loss_gate("chose Billform, cheaper", {"code": "competitor", "competitor": "Billform"})
    assert out["competitor"] == "Billform"
    out = ai.loss_gate("went with Stripe Billing", {"code": "competitor", "competitor": "Stripe Billing"})
    assert out["competitor"] is None


def test_story_gate():
    payload = {"segment": {"key": "x", "label": "X"}, "figures": [{"id": "win_rate", "label": "Win rate", "value": "31%"}],
               "quotes": [{"id": 4, "kind": "reason_to_buy", "text": "we rebuild invoices by hand"}]}
    ok = {"sentences": [{"text": "Buyers say \"we rebuild invoices by hand\" and win at 31%.", "quote_ids": [4], "figure_ids": ["win_rate"]}]}
    assert ai.story_gate(payload, ok, ["Marta Klein"]) == []
    assert ai.story_gate(payload, {"sentences": [{"text": "They win 40% of deals.", "quote_ids": [4]}]}, [])
    assert ai.story_gate(payload, {"sentences": [{"text": "Buyers say \"we love it\".", "quote_ids": [4]}]}, [])
    assert ai.story_gate(payload, {"sentences": [{"text": "Marta Klein signs.", "quote_ids": [4]}]}, ["Marta Klein"])
    assert ai.story_gate(payload, {"sentences": [{"text": "No quote.", "quote_ids": []}]}, [])
    assert ai.story_gate(payload, {"sentences": [{"text": "Bad id.", "quote_ids": [99]}]}, [])


def test_proposal_gate():
    payload = {"change": {"kind": "add_rule", "field": "pricing_model", "field_label": "Pricing model", "op": "eq",
                          "value_label": "Usage-based", "weight": 20},
               "findings": [{"id": 7, "trait": "Pricing model", "value": "Usage-based", "opportunities": 330, "win_rate": "38%",
                             "range": "33% to 44%", "rest_win_rate": "14%", "verdict": "Clearly higher", "top_loss": None}]}
    good = {"describes": {"kind": "add_rule", "field": "pricing_model", "value_label": "Usage-based"},
            "sentences": [{"text": "Add a rule for usage-based pricing.", "finding_ids": [7]},
                          {"text": "Usage-based won 38% of 330 opportunities against 14% for the rest.", "finding_ids": [7]}]}
    assert ai.proposal_gate(payload, good) == []
    bad_num = {**good, "sentences": [good["sentences"][0], {"text": "Usage-based won 45% of deals.", "finding_ids": [7]}]}
    assert ai.proposal_gate(payload, bad_num)
    bad_change = {**good, "describes": {"kind": "penalty", "field": "pricing_model", "value_label": "Usage-based"}}
    assert ai.proposal_gate(payload, bad_change)
    extra_trait = {**good, "sentences": [good["sentences"][0], {"text": "Usage-based fintech won 38%.", "finding_ids": [7]}]}
    assert ai.proposal_gate(payload, extra_trait)
    needs = {**good, "sentences": [good["sentences"][0], {"text": "The buyer needs usage-based billing at 38%.", "finding_ids": [7]}]}
    assert ai.proposal_gate(payload, needs)
    assert ai.proposal_gate(payload, {**good, "sentences": good["sentences"][:1]})


def test_stored_fit_reproduces_from_its_inputs(cur):
    vid = db.val(cur, "select id from icp_versions where status = 'published'")
    rules = db.val(cur, "select rules from icp_versions where id = %s", vid)
    rows = db.all(cur, "select * from account_fit where icp_version = %s order by md5(company::text) limit 500", vid)
    for r in rows:
        f = fit.fit(rules, r["inputs"]["fields"], model_fields=frozenset(r["inputs"]["model_fields"]))
        assert (f["score"], f["tier"], f["judged"]) == (r["score"], r["tier"], r["judged"])


def test_model_read_field_cannot_exclude():
    rules = {"factors": [{"key": "industry", "field": "industry", "op": "in", "value": ["Software"], "weight": 50},
                         {"key": "size", "field": "employees", "op": "between", "value": [100, 500], "weight": 50}],
             "excludes": [{"key": "gov", "field": "industry", "op": "in", "value": ["Government"], "reason": "Sector we do not sell to"}],
             "tiers": {"A": 85, "B": 65}}
    co = {"industry": "Government", "employees": 200, "lifecycle": "prospect"}
    assert fit.fit(rules, co)["tier"] == "X"
    f = fit.fit(rules, co, model_fields=frozenset({"industry"}))
    assert f["tier"] != "X" and f["not_applied"][0]["reason"] == "Sector we do not sell to"


def test_not_judged_below_sixty_percent_known():
    rules = {"factors": [{"key": "a", "field": "industry", "op": "in", "value": ["Software"], "weight": 50},
                         {"key": "b", "field": "tech", "op": "has_any", "value": ["Stripe"], "weight": 50}], "tiers": {"A": 85, "B": 65}}
    f = fit.fit(rules, {"industry": "Software", "tech": [], "lifecycle": "prospect"})
    assert f["judged"] is False and f["score"] is None and f["scored_out_of"] == 0.5


def test_world_export_is_stable(cur, tmp_path):
    from market import world_export
    a = world_export.export(str(tmp_path / "a"))
    b = world_export.export(str(tmp_path / "b"))
    assert a["sha256"] == b["sha256"]
    sole = db.val(cur, "select count(*) from companies where sole_trader")
    assert sole > 0 and a["rows"]["companies.csv"] == db.val(cur, "select count(*) from companies") - sole
    assert a["rows"]["people.csv"] > 1000
    head = (tmp_path / "a" / "people.csv").read_text().splitlines()[1].split(",")
    assert head[0].startswith("pe_") and head[1].startswith("co_")
    # people never enter the database
    for col in ("first_name", "last_name"):
        assert not db.val(cur, "select count(*) from information_schema.columns where column_name = %s", col)
