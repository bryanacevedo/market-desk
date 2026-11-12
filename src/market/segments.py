"""Segments: their buying roles from won deals, the buyers' own words from call notes, and why they buy (worded by
the model behind its gate, or withheld)."""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from . import ai, db
from . import catalog as C
from .db import J
from .fit import segment_of

QUOTE = re.compile(r"\"([^\"]{8,200})\"")


def load_segments(cur, version_id: int) -> None:
    db.run(cur, "delete from segments")
    for i, s in enumerate(C.SEGMENTS + [{**C.OUTSIDE, "when": []}]):
        db.run(cur, "insert into segments (key, label, definition, icp_version, position) values (%s,%s,%s,%s,%s)",
               s["key"], s["label"], J(s["when"]), version_id, i)


def roles(cur) -> None:
    """Which personas were on won deals, and which signed, per segment."""
    db.run(cur, "delete from segment_roles")
    deals = db.all(cur, """select d.id, d.snapshot, array_agg(r.persona) as personas,
                           array_agg(r.persona) filter (where r.was_signer) as signers
                           from deals d join deal_roles r on r.deal = d.id
                           where d.kind = 'new' and d.outcome = 'won' group by d.id""")
    on = defaultdict(Counter)
    signed = defaultdict(Counter)
    n = Counter()
    for d in deals:
        seg = segment_of({"segments": C.SEGMENTS}, d["snapshot"])
        n[seg] += 1
        for p in set(d["personas"]):
            on[seg][p] += 1
        for p in set(d["signers"] or []):
            signed[seg][p] += 1
    for seg, cnt in on.items():
        for p, k in cnt.items():
            db.run(cur, """insert into segment_roles (segment, persona, share_of_won_deals, share_as_signer, n_won_deals)
                           values (%s,%s,%s,%s,%s)""", seg, p, k / n[seg], signed[seg][p] / n[seg], n[seg])


def quotes(cur) -> int:
    """The buyer's own words: spans in quotation marks in a redacted call note. Kind from the deal: won deals give
    reasons to buy, lost deals objections, a listed competitor's name makes it a competitor quote."""
    db.run(cur, "delete from quotes")
    rows = db.all(cur, """select n.id, n.text_redacted, d.outcome, d.snapshot from call_notes n join deals d on d.id = n.deal""")
    k = 0
    for r in rows:
        for m in QUOTE.finditer(r["text_redacted"]):
            text = m.group(1)
            kind = "competitor" if any(c.lower() in text.lower() for c in C.COMPETITORS) else (
                "reason_to_buy" if r["outcome"] == "won" else "objection")
            db.run(cur, "insert into quotes (call_note, segment, text, kind) values (%s,%s,%s,%s)", r["id"],
                   segment_of({"segments": C.SEGMENTS}, r["snapshot"]), text, kind)
            k += 1
    return k


def story_payload(cur, segment: str) -> tuple[dict, list[str]]:
    run = db.val(cur, "select max(id) from analysis_runs")
    f = db.one(cur, "select * from findings where run = %s and trait = 'segment' and value = %s", run, J(segment))
    figures = []
    if f:
        figures += [{"id": "win_rate", "label": "Win rate", "value": f"{round(100 * f['win_rate'])}%"},
                    {"id": "opportunities", "label": "Opportunities", "value": str(f["opps"])}]
        if f["cycle_median_days"]:
            figures.append({"id": "cycle", "label": "Won-deal cycle", "value": f"{int(f['cycle_median_days'])} days"})
    signer = db.one(cur, "select persona from segment_roles where segment = %s order by share_as_signer desc limit 1", segment)
    if signer:
        figures.append({"id": "signer", "label": "Most common signer", "value": C.PERSONAS[signer["persona"]]})
    qs = []
    for kind in ("reason_to_buy", "objection", "competitor"):
        qs += db.all(cur, """select min(id) as id, %s as kind, text from quotes where segment = %s and kind = %s
                             group by text order by count(*) desc, text limit 3""", kind, segment, kind)
    forbidden = [u["name"] for u in db.all(cur, "select name from users")]
    forbidden += [x for u in db.all(cur, "select name from users") for x in u["name"].split()]
    forbidden += [c["name"] for c in db.all(cur, """select distinct c.name from companies c join deals d on d.company = c.id""")]
    return ({"segment": {"key": segment, "label": C.SEGMENT_LABEL[segment]}, "figures": figures,
             "quotes": [{"id": q["id"], "kind": q["kind"], "text": q["text"]} for q in qs]}, forbidden)


def stories(cur) -> dict:
    out = {}
    now = db.val(cur, "select app_now()")
    for s in C.SEGMENTS:
        payload, forbidden = story_payload(cur, s["key"])
        if not payload["quotes"]:
            continue
        sentences, fails = ai.segment_story(cur, payload, forbidden)
        db.run(cur, """insert into segment_stories (segment, drafted_at, sentences, status, failures, source)
                       values (%s,%s,%s,%s,%s,%s)""", s["key"], now, J({"sentences": sentences, "payload": payload}),
               "ok" if sentences else "withheld", J(fails), "model")
        out[s["key"]] = "ok" if sentences else "withheld"
    return out
